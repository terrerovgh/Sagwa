/* Real production bsp_feature_en.c with a simulated register bus/RTOS mutex.
 * Verifies ownership and RMW/error behavior, not electrical operation. */
#include "bsp/m5stack_core_s3.h"
#include "freertos/semphr.h"
#include <assert.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static uint8_t regs[256];
static int adds, removes;
static bool fail_mutex_once=true;
static atomic_bool fail_read,fail_write,fail_lock;
static pthread_mutex_t transfer_lock=PTHREAD_MUTEX_INITIALIZER;
SemaphoreHandle_t xSemaphoreCreateMutex(void){
 if(fail_mutex_once){fail_mutex_once=false;return NULL;}
 pthread_mutex_t *p=malloc(sizeof(*p));assert(p);assert(!pthread_mutex_init(p,NULL));return p;
}
int xSemaphoreTake(SemaphoreHandle_t h,unsigned ms){(void)ms;if(atomic_exchange(&fail_lock,false))return 0;assert(!pthread_mutex_lock(h));return 1;}
int xSemaphoreGive(SemaphoreHandle_t h){assert(!pthread_mutex_unlock(h));return 1;}
esp_err_t bsp_i2c_init(void){return ESP_OK;}
void *bsp_i2c_get_handle(void){return &regs;}
esp_err_t i2c_master_bus_add_device(void *b,const i2c_device_config_t *c,i2c_master_dev_handle_t *out){assert(b==&regs&&c->device_address==0x34);adds++;*out=&regs;return ESP_OK;}
esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t h){assert(h==&regs);removes++;return ESP_OK;}
esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t h,const uint8_t *w,size_t wn,uint8_t *r,size_t rn,int timeout){
 assert(h==&regs&&wn==1&&rn==1&&timeout>0);if(atomic_exchange(&fail_read,false))return ESP_FAIL;
 assert(!pthread_mutex_lock(&transfer_lock));*r=regs[*w];assert(!pthread_mutex_unlock(&transfer_lock));usleep(100);return ESP_OK;
}
esp_err_t i2c_master_transmit(i2c_master_dev_handle_t h,const uint8_t *w,size_t n,int timeout){
 assert(h==&regs&&n==2&&timeout>0);if(atomic_exchange(&fail_write,false))return ESP_FAIL;
 assert(!pthread_mutex_lock(&transfer_lock));regs[w[0]]=w[1];assert(!pthread_mutex_unlock(&transfer_lock));return ESP_OK;
}
esp_io_expander_handle_t bsp_io_expander_init(void){return &adds;}
esp_err_t esp_io_expander_set_dir(esp_io_expander_handle_t h,int pin,int d){assert(h==&adds&&pin>=0&&d==1);return ESP_OK;}
esp_err_t esp_io_expander_set_level(esp_io_expander_handle_t h,int pin,bool level){assert(h==&adds&&pin>=0);(void)level;return ESP_OK;}
static void *enable_worker(void *arg){bsp_feature_t f=*(bsp_feature_t*)arg;assert(bsp_feature_enable(f,true)==ESP_OK);return NULL;}
int main(void){
 assert(bsp_pmu_init()==ESP_ERR_NO_MEM);assert(!bsp_pmu_get_handle()&&adds==1&&removes==1);
 assert(bsp_pmu_init()==ESP_OK);assert(bsp_pmu_init()==ESP_OK);assert(bsp_pmu_get_handle()==&regs&&adds==2);
 regs[0x90]=0x40;assert(bsp_feature_enable(BSP_FEATURE_MIC,true)==ESP_OK);assert(regs[0x90]==0x41&&regs[0x93]==28);
 assert(bsp_feature_enable(BSP_FEATURE_SPEAKER,true)==ESP_OK);assert(regs[0x90]==0x43&&regs[0x92]==13);
 assert(bsp_feature_enable(BSP_FEATURE_MIC,false)==ESP_OK);assert(regs[0x90]==0x42);
 assert(bsp_feature_enable(BSP_FEATURE_SPEAKER,false)==ESP_OK);assert(regs[0x90]==0x40);
 assert(bsp_display_brightness_set(100)==ESP_OK);assert(regs[0x90]==0xC0&&regs[0x99]==28);
 assert(bsp_display_brightness_set(0)==ESP_OK);assert(regs[0x90]==0x40);
 atomic_store(&fail_write,true);assert(bsp_feature_enable(BSP_FEATURE_MIC,true)==ESP_FAIL);
 atomic_store(&fail_read,true);assert(bsp_feature_enable(BSP_FEATURE_MIC,true)==ESP_FAIL);
 atomic_store(&fail_lock,true);assert(bsp_feature_enable(BSP_FEATURE_MIC,true)==ESP_ERR_TIMEOUT);
 assert(bsp_feature_enable(BSP_FEATURE_MIC,true)==ESP_OK); /* mutex released on both transfer failures */
 for(int i=0;i<100;i++){
  regs[0x90]=0x40;pthread_t a,b;bsp_feature_t mic=BSP_FEATURE_MIC,spk=BSP_FEATURE_SPEAKER;
  assert(!pthread_create(&a,NULL,enable_worker,&mic));assert(!pthread_create(&b,NULL,enable_worker,&spk));
  assert(!pthread_join(a,NULL));assert(!pthread_join(b,NULL));assert(regs[0x90]==0x43);
 }
 assert(adds==2&&removes==1);
 puts("PASS: production BSP ownership, mutex allocation cleanup, enable/disable bit preservation, concurrent LDO RMW, read/write/lock error recovery. Simulated bus; no electrical claim.");
 return 0;
}
