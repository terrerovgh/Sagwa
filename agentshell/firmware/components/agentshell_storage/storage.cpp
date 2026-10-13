#include "storage.hpp"
#include "hal.hpp"
#include "nvs.h"
#include <cstdio>
#include <cstring>
#include <ctime>
namespace shell {
static bool card;
static bool parse(const cJSON *p, Provision &out) {
  auto value = [&](const char *key) -> std::string {
    const char *s =
        cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(p, key));
    return s ? s : "";
  };
  out.ssid = value("wifi_ssid");
  out.password = value("wifi_password");
  out.ca = value("ca");
  out.certificate = value("certificate");
  out.key = value("key");
  out.device_id = value("device_id");
  out.gateways.clear();
  const cJSON *array = cJSON_GetObjectItemCaseSensitive(p, "gateways");
  const cJSON *item;
  cJSON_ArrayForEach(item, array) {
    const char *s = cJSON_GetStringValue(item);
    if (!s || std::string(s).find("wss://") != 0 ||
        std::string(s).find("/v1/device/ws") == std::string::npos)
      return false;
    out.gateways.emplace_back(s);
  }
  const cJSON *epoch = cJSON_GetObjectItemCaseSensitive(p, "epoch");
  out.epoch =
      cJSON_IsNumber(epoch) ? static_cast<int64_t>(epoch->valuedouble) : 0;
  return !out.ssid.empty() && out.ssid.size() <= 32 &&
         out.password.size() <= 64 && out.gateways.size() == 2 &&
         out.ca.size() > 100 && out.certificate.size() > 100 &&
         out.key.size() > 100 && out.device_id.find("device:") == 0 &&
         out.epoch > 1700000000;
}
bool load_provision(Provision &out) {
  nvs_handle_t handle;
  if (nvs_open("agentshell", NVS_READONLY, &handle) != ESP_OK)
    return false;
  size_t size = 0;
  esp_err_t err = nvs_get_blob(handle, "provision", nullptr, &size);
  if (err != ESP_OK || size > 24576) {
    nvs_close(handle);
    return false;
  }
  std::vector<char> buf(size);
  err = nvs_get_blob(handle, "provision", buf.data(), &size);
  nvs_close(handle);
  if (err != ESP_OK)
    return false;
  cJSON *p = cJSON_Parse(buf.data());
  bool ok = p && parse(p, out);
  cJSON_Delete(p);
  return ok;
}
bool install_provision(const cJSON *p, Provision &out) {
  Provision next;
  if (!parse(p, next))
    return false;
  char *text = cJSON_PrintUnformatted(p);
  if (!text)
    return false;
  nvs_handle_t handle;
  bool ok = false;
  if (nvs_open("agentshell", NVS_READWRITE, &handle) == ESP_OK) {
    ok = nvs_set_blob(handle, "provision", text, strlen(text)+1) == ESP_OK &&
         nvs_commit(handle) == ESP_OK;
    nvs_close(handle);
  }
  cJSON_free(text);
  if (ok)
    out = std::move(next);
  return ok;
}
uint64_t load_sequence() {
  nvs_handle_t h;
  uint64_t seq = 0;
  if (nvs_open("agentshell", NVS_READONLY, &h) == ESP_OK) {
    nvs_get_u64(h, "sequence", &seq);
    nvs_close(h);
  }
  return seq;
}
void save_sequence(uint64_t seq) {
  nvs_handle_t h;
  if (nvs_open("agentshell", NVS_READWRITE, &h) == ESP_OK) {
    nvs_set_u64(h, "sequence", seq);
    nvs_commit(h);
    nvs_close(h);
  }
}
bool sd_begin() {
  card = hal_sd_begin();
  return card;
}
void sd_log(const char *event) {
  if (!card)
    return;
  FILE *file = fopen("/sdcard/agentshell.log", "a");
  if (file) {
    fprintf(file, "%lld %s\n", static_cast<long long>(time(nullptr)), event);
    fclose(file);
  }
}
} // namespace shell
