#include "ota.hpp"
#include "esp_http_client.h"
#include "esp_ota_ops.h"
#include "nvs.h"
#include "mbedtls/base64.h"
#include "mbedtls/pk.h"
#include "psa/crypto.h"
#include <cstring>
#include <vector>
extern const uint8_t release_key[] asm("_binary_release_public_pem_start");
namespace shell {
bool ota_attempted(const cJSON *payload){
  const char *id=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(payload,"attempt_id"));if(!id||strlen(id)!=36)return false;
  nvs_handle_t handle;if(nvs_open("agentshell",NVS_READONLY,&handle)!=ESP_OK)return false;
  char prior[37]={};size_t size=sizeof(prior);bool same=nvs_get_str(handle,"ota_attempt",prior,&size)==ESP_OK&&!strcmp(prior,id);nvs_close(handle);return same;
}
static bool mark_attempt(const cJSON *payload){
  const char *id=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(payload,"attempt_id"));if(!id||strlen(id)!=36)return false;
  nvs_handle_t handle;if(nvs_open("agentshell",NVS_READWRITE,&handle)!=ESP_OK)return false;
  bool ok=nvs_set_str(handle,"ota_attempt",id)==ESP_OK&&nvs_commit(handle)==ESP_OK;nvs_close(handle);return ok;
}
bool ota_is_current(const cJSON *payload) {
  const char *manifest=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(payload,"manifest"));
  if(!manifest||strlen(manifest)>4096)return false;
  auto *m=cJSON_Parse(manifest);if(!m)return false;
  const char *hash=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(m,"sha256"));
  auto *size=cJSON_GetObjectItemCaseSensitive(m,"size");
  bool valid=hash&&strlen(hash)==64&&cJSON_IsNumber(size)&&size->valuedouble>0&&size->valuedouble<4*1024*1024;
  std::string expected=hash?hash:"";size_t length=valid?size_t(size->valuedouble):0;cJSON_Delete(m);
  const auto *partition=esp_ota_get_running_partition();if(!valid||!partition||length>partition->size)return false;
  psa_crypto_init();psa_hash_operation_t operation=PSA_HASH_OPERATION_INIT;
  if(psa_hash_setup(&operation,PSA_ALG_SHA_256)!=PSA_SUCCESS)return false;
  uint8_t buffer[4096],digest[32];size_t digest_size=0;bool ok=true;
  for(size_t offset=0;offset<length&&ok;offset+=sizeof(buffer)){
    size_t bytes=std::min(sizeof(buffer),length-offset);
    ok=esp_partition_read(partition,offset,buffer,bytes)==ESP_OK&&psa_hash_update(&operation,buffer,bytes)==PSA_SUCCESS;
  }
  ok=ok&&psa_hash_finish(&operation,digest,sizeof(digest),&digest_size)==PSA_SUCCESS;psa_hash_abort(&operation);
  char actual[65];for(int n=0;n<32;n++)sprintf(actual+2*n,"%02x",digest[n]);
  return ok&&expected==actual;
}
bool confirm_local_boot(bool healthy) {
  esp_ota_img_states_t state;
  const auto *running = esp_ota_get_running_partition();
  if (esp_ota_get_state_partition(running, &state) != ESP_OK ||
      state != ESP_OTA_IMG_PENDING_VERIFY)
    return healthy;
  if (!healthy) {
    esp_ota_mark_app_invalid_rollback_and_reboot();
    return false;
  }
  return esp_ota_mark_app_valid_cancel_rollback() == ESP_OK;
}
bool install_ota(const cJSON *payload, const Provision &provision) {
  const char *manifest = cJSON_GetStringValue(
      cJSON_GetObjectItemCaseSensitive(payload, "manifest"));
  const char *encoded = cJSON_GetStringValue(
      cJSON_GetObjectItemCaseSensitive(payload, "signature"));
  if (!manifest || !encoded || strlen(manifest) > 4096 ||
      strlen(encoded) > 1024)
    return false;
  psa_crypto_init();
  uint8_t digest[32], signature[768];
  size_t length = 0;
  size_t digest_length=0;
  if(psa_hash_compute(PSA_ALG_SHA_256,reinterpret_cast<const uint8_t*>(manifest),strlen(manifest),digest,sizeof(digest),&digest_length)!=PSA_SUCCESS || mbedtls_base64_decode(signature,sizeof(signature),&length,reinterpret_cast<const uint8_t*>(encoded),strlen(encoded)))return false;
  mbedtls_pk_context key;
  mbedtls_pk_init(&key);
  int result = mbedtls_pk_parse_public_key(
      &key, release_key,
      strlen(reinterpret_cast<const char *>(release_key)) + 1);
  if (!result)
    result = mbedtls_pk_verify(&key, MBEDTLS_MD_SHA256, digest, 32, signature,
                               length);
  mbedtls_pk_free(&key);
  if (result)
    return false;
  cJSON *m = cJSON_Parse(manifest);
  if (!m)
    return false;
  const char *u =
      cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(m, "url"));
  const char *hash =
      cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(m, "sha256"));
  const auto *size = cJSON_GetObjectItemCaseSensitive(m, "size");
  const char *target =
      cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(m, "target"));
  const char *version=cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(m,"version"));
  bool valid = u && hash && strlen(hash) == 64 && cJSON_IsNumber(size) &&
               size->valuedouble > 0 && size->valuedouble < 4 * 1024 * 1024 &&
               target && !strcmp(target, "esp32s3") && version && strlen(version)<32;
  std::string url = u ? u : "", expected = hash ? hash : "";
  std::string expected_version=version?version:"";
  size_t expected_size = size ? size_t(size->valuedouble) : 0;
  bool host = false;
  for (auto gateway : provision.gateways) {
    gateway.replace(0, 3, "https");
    auto end = gateway.find("/v1/device/ws");
    if(end==std::string::npos)continue;
    gateway.resize(end);
    host |= url==gateway + "/v1/device/firmware/"+expected;
  }
  cJSON_Delete(m);
  if (!valid || !host)
    return false;
  if(!mark_attempt(payload))return false;
  const auto *partition = esp_ota_get_next_update_partition(nullptr);
  if (!partition || partition->size < expected_size)
    return false;
  esp_http_client_config_t cfg = {};
  cfg.url = url.c_str();
  cfg.cert_pem = provision.ca.c_str();
  cfg.client_cert_pem = provision.certificate.c_str();
  cfg.client_key_pem = provision.key.c_str();
  cfg.timeout_ms = 10000;
  cfg.disable_auto_redirect = true;
  auto client = esp_http_client_init(&cfg);
  if (!client)
    return false;
  esp_ota_handle_t handle = 0;
  bool ok = esp_http_client_open(client, 0) == ESP_OK;
  if (ok) {
    esp_http_client_fetch_headers(client);
    ok = esp_http_client_get_status_code(client) == 200;
  }
  if (ok)
    ok = esp_ota_begin(partition, expected_size, &handle) == ESP_OK;
  psa_hash_operation_t sha=PSA_HASH_OPERATION_INIT;
  ok=ok&&psa_hash_setup(&sha,PSA_ALG_SHA_256)==PSA_SUCCESS;
  size_t received = 0;
  uint8_t buffer[4096];
  while (ok && received < expected_size) {
    int n = esp_http_client_read(
        client, reinterpret_cast<char *>(buffer),
        std::min(sizeof(buffer), expected_size - received));
    if (n <= 0) {
      ok = false;
      break;
    }
    received += n;
    ok=ok&&psa_hash_update(&sha,buffer,n)==PSA_SUCCESS;
    ok = esp_ota_write(handle, buffer, n) == ESP_OK;
  }
  ok=ok&&psa_hash_finish(&sha,digest,sizeof(digest),&digest_length)==PSA_SUCCESS;
  psa_hash_abort(&sha);
  char actual[65];
  for (int n = 0; n < 32; n++)
    sprintf(actual + 2 * n, "%02x", digest[n]);
  ok = ok && received == expected_size && expected == actual;
  esp_http_client_close(client);
  esp_http_client_cleanup(client);
  if (ok) {
    ok = esp_ota_end(handle) == ESP_OK;
    esp_app_desc_t description={};
    if(ok)ok=esp_ota_get_partition_description(partition,&description)==ESP_OK&&expected_version==description.version;
    if (ok)
      ok = esp_ota_set_boot_partition(partition) == ESP_OK;
  } else if (handle)
    esp_ota_abort(handle);
  return ok;
}
} // namespace shell
