#include "cJSON.h"
#include "esp_efuse.h"
#include "esp_partition.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "platform.hpp"
#include <cstring>
namespace sagwa {
static std::string name(Provider p) {
  return "provider" + std::to_string(unsigned(p));
}
static bool valid_model(const std::string &s) {
  return !s.empty() && s.size() <= 128 &&
         s.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVW"
                             "XYZ0123456789_./:-") == std::string::npos;
}
static std::string field(cJSON *j, const char *k) {
  auto s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(j, k));
  return s ? s : "";
}
bool CredentialStore::load() {
  // nvs_get_str() reads only through an initialized encrypted NVS driver.
  nvs_sec_cfg_t cfg{};
  auto keys = esp_partition_find_first(
      ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_NVS_KEYS, "nvs_keys");
  encrypted_ = esp_efuse_is_flash_encryption_enabled() && keys &&
               nvs_flash_read_security_cfg(keys, &cfg) == ESP_OK &&
               nvs_flash_secure_init_partition("vault", &cfg) == ESP_OK;
  volatile uint8_t *secret = reinterpret_cast<volatile uint8_t *>(&cfg);
  for (size_t i = 0; i < sizeof cfg; ++i)
    secret[i] = 0;
  if (!encrypted_)
    return false;
  for (unsigned i = 2; i < profiles_.size(); ++i) {
    nvs_handle_t h;
    if (nvs_open_from_partition("vault", "sagwa_keys", NVS_READONLY, &h) !=
        ESP_OK)
      continue;
    size_t n = 0;
    auto k = name(Provider(i));
    if (nvs_get_str(h, k.c_str(), nullptr, &n) == ESP_OK && n <= 4096) {
      std::string text(n, '\0');
      if (nvs_get_str(h, k.c_str(), text.data(), &n) == ESP_OK) {
        auto j = cJSON_Parse(text.c_str());
        if (j) {
          auto &p = profiles_[i];
          p.key = field(j, "key");
          p.small_model = field(j, "small");
          p.strong_model = field(j, "strong");
          p.enabled = cJSON_IsTrue(cJSON_GetObjectItem(j, "enabled"));
          p.responses_api =
              cJSON_IsTrue(cJSON_GetObjectItem(j, "responses_api"));
          p.audio_input =
              i == 2 && cJSON_IsTrue(cJSON_GetObjectItem(j, "audio_input"));
          cJSON_Delete(j);
        }
      }
    }
    nvs_close(h);
  }
  return true;
}
bool CredentialStore::profile(Provider p, CloudProfile &out) const {
  auto i = size_t(p);
  if (!encrypted_ || i < 2 || i >= profiles_.size())
    return false;
  out = profiles_[i];
  return out.enabled && !out.key.empty() && valid_model(out.small_model) &&
         valid_model(out.strong_model);
}
bool CredentialStore::install(Provider p, const CloudProfile &v) {
  auto i = size_t(p);
  if (!encrypted_ || i < 2 || i >= profiles_.size() || v.key.empty() ||
      v.key.size() > 2048 || v.key.find_first_of("\r\n") != std::string::npos ||
      !valid_model(v.small_model) || !valid_model(v.strong_model))
    return false;
  auto *j = cJSON_CreateObject();
  cJSON_AddStringToObject(j, "key", v.key.c_str());
  cJSON_AddStringToObject(j, "small", v.small_model.c_str());
  cJSON_AddStringToObject(j, "strong", v.strong_model.c_str());
  cJSON_AddBoolToObject(j, "enabled", v.enabled);
  cJSON_AddBoolToObject(j, "responses_api", v.responses_api);
  cJSON_AddBoolToObject(j, "audio_input", i == 2 && v.audio_input);
  auto text = cJSON_PrintUnformatted(j);
  cJSON_Delete(j);
  if (!text)
    return false;
  nvs_handle_t h;
  bool ok = false;
  if (nvs_open_from_partition("vault", "sagwa_keys", NVS_READWRITE, &h) ==
      ESP_OK) {
    auto k = name(p);
    ok = nvs_set_str(h, k.c_str(), text) == ESP_OK && nvs_commit(h) == ESP_OK;
    nvs_close(h);
  }
  memset(text, 0, strlen(text));
  cJSON_free(text);
  if (ok)
    profiles_[i] = v;
  return ok;
}
bool CredentialStore::save_tokens(Provider p, const TokenSet &t) {
  if (!encrypted_ || size_t(p) < 2 || size_t(p) >= profiles_.size() ||
      t.access.size() > 1400 || t.refresh.size() > 1400)
    return false;
  auto *j = cJSON_CreateObject();
  cJSON_AddStringToObject(j, "access", t.access.c_str());
  cJSON_AddStringToObject(j, "refresh", t.refresh.c_str());
  cJSON_AddNumberToObject(j, "expires_at", double(t.expires_at));
  auto text = cJSON_PrintUnformatted(j);
  cJSON_Delete(j);
  if (!text)
    return false;
  if (strlen(text) > 3900) {
    memset(text, 0, strlen(text));
    cJSON_free(text);
    return false;
  }
  auto k = "oauth" + std::to_string(unsigned(p));
  nvs_handle_t h;
  bool ok = false;
  if (nvs_open_from_partition("vault", "sagwa_keys", NVS_READWRITE, &h) ==
      ESP_OK) {
    ok = nvs_set_str(h, k.c_str(), text) == ESP_OK && nvs_commit(h) == ESP_OK;
    nvs_close(h);
  }
  memset(text, 0, strlen(text));
  cJSON_free(text);
  return ok;
}
bool CredentialStore::load_tokens(Provider p, TokenSet &t) const {
  if (!encrypted_ || size_t(p) < 2 || size_t(p) >= profiles_.size())
    return false;
  nvs_handle_t h;
  if (nvs_open_from_partition("vault", "sagwa_keys", NVS_READONLY, &h) !=
      ESP_OK)
    return false;
  auto k = "oauth" + std::to_string(unsigned(p));
  size_t n = 0;
  bool ok = nvs_get_str(h, k.c_str(), nullptr, &n) == ESP_OK && n <= 8192;
  std::string text(ok ? n : 0, '\0');
  if (ok)
    ok = nvs_get_str(h, k.c_str(), text.data(), &n) == ESP_OK;
  nvs_close(h);
  auto *j = ok ? cJSON_Parse(text.c_str()) : nullptr;
  if (!j)
    return false;
  t.access = field(j, "access");
  t.refresh = field(j, "refresh");
  auto exp = cJSON_GetObjectItem(j, "expires_at");
  t.expires_at = cJSON_IsNumber(exp) ? int64_t(exp->valuedouble) : 0;
  cJSON_Delete(j);
  return !t.access.empty();
}
} // namespace sagwa
