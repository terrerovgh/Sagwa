#include "context.hpp"
#include "context_format.hpp"
#include "esp_http_client.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "psa/crypto.h"
#include "miniz.h"
#include <atomic>
#include <cstring>
namespace shell {
namespace {
struct Offer {char hash[65],url[384],id[128],name[128];size_t size;uint32_t generation;};
struct Asset {uint8_t *bytes=nullptr;Offer offer={};uint32_t used=0;};
static Asset cache[3];static int selected=-1;
static Provision settings;static QueueHandle_t queue;static SemaphoreHandle_t guard;
static std::atomic<uint32_t> generation{0};static std::atomic<unsigned> failures{0};
static std::atomic<int> phase{0},http_status{0},transport_error{0};
static std::atomic<int64_t> header_length{0};static std::atomic<unsigned> received_bytes{0};
uint8_t *download(const Offer &o,const std::string &url) {
 bool compressed=false;
 esp_http_client_config_t cfg={};cfg.url=url.c_str();cfg.cert_pem=settings.ca.c_str();
 cfg.client_cert_pem=settings.certificate.c_str();cfg.client_key_pem=settings.key.c_str();
 cfg.timeout_ms=15000;cfg.disable_auto_redirect=true;cfg.buffer_size=4096;
 cfg.user_data=&compressed;cfg.event_handler=[](esp_http_client_event_t *e)->esp_err_t {
  if(e->event_id==HTTP_EVENT_ON_HEADER&&!strcasecmp(e->header_key,"Content-Encoding"))*static_cast<bool*>(e->user_data)=!strcasecmp(e->header_value,"deflate");
  return ESP_OK;
 };
 auto client=esp_http_client_init(&cfg);if(!client)return nullptr;
 esp_http_client_set_header(client,"Accept-Encoding","deflate");
 phase=1;received_bytes=0;transport_error=esp_http_client_open(client,0);bool ok=transport_error==ESP_OK;
 size_t wire_size=0;
 if(ok){phase=2;auto length=esp_http_client_fetch_headers(client);header_length=length;http_status=esp_http_client_get_status_code(client);ok=http_status==200&&length>0&&length<=int64_t(emoji_max_bytes+1024)&&(compressed||length==int64_t(o.size));if(ok)wire_size=length;}
 auto *data=ok?static_cast<uint8_t*>(heap_caps_malloc(o.size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)):nullptr;
 auto *wire=compressed&&ok?static_cast<uint8_t*>(heap_caps_malloc(wire_size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)):data;
 ok=ok&&data&&wire;size_t offset=0;if(ok)phase=3;
 while(ok&&offset<wire_size&&o.generation==generation.load()) {
  int n=esp_http_client_read(client,reinterpret_cast<char*>(wire+offset),std::min(size_t(4096),wire_size-offset));
  if(n<=0){transport_error=n;ok=false;break;}offset+=n;received_bytes=offset;
 }
 esp_http_client_close(client);esp_http_client_cleanup(client);
 if(ok)phase=4;
 ok=ok&&offset==wire_size&&o.generation==generation.load();
 if(compressed) {
  auto *decoder=ok?static_cast<tinfl_decompressor*>(heap_caps_calloc(1,sizeof(tinfl_decompressor),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)):nullptr;
  if(decoder){size_t input_size=wire_size,output_size=o.size;tinfl_init(decoder);ok=tinfl_decompress(decoder,wire,&input_size,data,data,&output_size,TINFL_FLAG_PARSE_ZLIB_HEADER|TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF)==TINFL_STATUS_DONE&&output_size==o.size&&input_size==wire_size;free(decoder);}else ok=false;
  free(wire);
 }
 ok=ok&&emoji_image_valid(data,o.size);
 if(ok){uint8_t digest[32];size_t length=0;psa_crypto_init();ok=psa_hash_compute(PSA_ALG_SHA_256,data,o.size,digest,32,&length)==PSA_SUCCESS&&length==32;
  char hash[65];for(int i=0;i<32;i++)sprintf(hash+i*2,"%02x",digest[i]);ok=ok&&strcmp(hash,o.hash)==0;}
 if(!ok){free(data);return nullptr;}phase=5;return data;
}
void loader(void *) {
 Offer o;
 for(;;){
  if(xQueueReceive(queue,&o,portMAX_DELAY)!=pdTRUE||o.generation!=generation.load())continue;
  bool found=false;xSemaphoreTake(guard,portMAX_DELAY);
  for(int i=0;i<3;i++)if(cache[i].bytes&&!strcmp(cache[i].offer.hash,o.hash)){
   if(o.generation==generation.load()){selected=i;cache[i].offer=o;cache[i].used=esp_timer_get_time()/1000;}found=true;break;}
  xSemaphoreGive(guard);if(found)continue;
  uint8_t *data=download(o,o.url);
  // A gateway outage may be recovered from the other configured gateway.
  for(const auto &gateway:settings.gateways)if(!data&&o.generation==generation.load()){
   auto origin=emoji_gateway_origin(gateway);if(origin.empty())continue;
   auto url=origin+"/v1/device/emoji/"+o.hash;if(url!=o.url)data=download(o,url);
  }
  if(!data){if(o.generation==generation.load())failures++;continue;}
  xSemaphoreTake(guard,portMAX_DELAY);
  if(o.generation!=generation.load()){free(data);xSemaphoreGive(guard);continue;}
  int slot=0;for(int i=0;i<3;i++)if(!cache[i].bytes){slot=i;break;}else if(cache[i].used<cache[slot].used)slot=i;
  free(cache[slot].bytes);cache[slot]={data,o,uint32_t(esp_timer_get_time()/1000)};selected=slot;
  xSemaphoreGive(guard);
 }
}
}
void ui_context_begin(const Provision &p) {
 if(queue)return;
 settings=p;guard=xSemaphoreCreateMutex();queue=xQueueCreate(1,sizeof(Offer));
 if(!guard||!queue)return;
 if(xTaskCreate(loader,"emoji",16384,nullptr,2,nullptr)!=pdPASS){vQueueDelete(queue);queue=nullptr;}
}
void ui_context_clear() {
 generation++;if(!queue||!guard)return;xQueueReset(queue);
 xSemaphoreTake(guard,portMAX_DELAY);selected=-1;xSemaphoreGive(guard);
}
void ui_context_offer(const cJSON *p) {
 if(!queue)return;
 auto field=[&](const char *key){const char *s=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(p,key));return std::string(s?s:"");};
 const auto hash=field("sha256"),url=field("url"),id=field("codepoint"),name=field("name");
 auto *size=cJSON_GetObjectItemCaseSensitive(p,"size");bool allowed=false;
 for(const auto &gateway:settings.gateways)allowed|=emoji_url_valid(url,gateway,hash);
 if(!allowed||url.size()>=384||id.empty()||id.size()>=128||name.size()>=128||!cJSON_IsNumber(size)||size->valuedouble<16||size->valuedouble>emoji_max_bytes||size->valuedouble!=size->valueint)return;
 for(char c:id)if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')||c=='_'))return;
 Offer o={};strcpy(o.hash,hash.c_str());strcpy(o.url,url.c_str());strcpy(o.id,id.c_str());strcpy(o.name,name.c_str());o.size=size->valueint;o.generation=++generation;
 xQueueOverwrite(queue,&o);
}
bool ui_context_frame(uint16_t *pixels,uint32_t ms,std::string &token,std::string &name) {
 if(!guard)return false;
 xSemaphoreTake(guard,portMAX_DELAY);
 if(selected<0){xSemaphoreGive(guard);return false;}
 auto &a=cache[selected];unsigned count=emoji_u16(a.bytes+8),duration=emoji_u32(a.bytes+12);
 unsigned frame=(ms-a.used)%duration*count/duration;
 token=std::string(a.offer.hash)+":"+std::to_string(frame);name=a.offer.name;
 const auto *source=a.bytes+16+frame*96*96*2;
 for(int n=0;n<96*96;n++)pixels[n]=emoji_u16(source+n*2);
 xSemaphoreGive(guard);return true;
}
cJSON *ui_context_status() {
 auto *p=cJSON_CreateObject();cJSON_AddNumberToObject(p,"failures",failures.load());
 cJSON_AddNumberToObject(p,"phase",phase.load());cJSON_AddNumberToObject(p,"http_status",http_status.load());cJSON_AddNumberToObject(p,"transport_error",transport_error.load());cJSON_AddNumberToObject(p,"header_length",header_length.load());cJSON_AddNumberToObject(p,"received_bytes",received_bytes.load());
 if(!guard)return p;
 xSemaphoreTake(guard,portMAX_DELAY);int count=0;
 for(auto &a:cache)if(a.bytes)count++;
 cJSON_AddNumberToObject(p,"cached",count);
 if(selected>=0){cJSON_AddStringToObject(p,"codepoint",cache[selected].offer.id);cJSON_AddStringToObject(p,"sha256",cache[selected].offer.hash);}
 xSemaphoreGive(guard);return p;
}
}
