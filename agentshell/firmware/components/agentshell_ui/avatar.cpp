#include "avatar.hpp"
#include "avatar_format.hpp"
#include "context_format.hpp"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "psa/crypto.h"
#include "sagwa_assets.hpp"
#include <algorithm>
#include <atomic>
#include <cstring>
namespace shell {
namespace {
struct Offer {
  char hash[65] = {}, url[384] = {};
  unsigned state = 0, size = 0, generation = 0;
};
struct Cache {
  Offer offer;
  uint8_t *data = nullptr;
  unsigned used = 0;
};
Provision provision;
Offer offers[12];
Cache cache[3];
QueueHandle_t queue;
SemaphoreHandle_t mutex;
std::atomic<unsigned> generation{0}, failures{0};
unsigned counter = 0, requested = 99;
extern const uint8_t fallback[] asm("_binary_sagwa_bin_start");
std::string endpoint(const std::string &gateway, const std::string &hash) {
  return emoji_gateway_origin(gateway) + "/v1/device/avatar/" + hash;
}
bool allowed(const std::string &url, const std::string &hash) {
  if (hash.size() != 64 ||
      hash.find_first_not_of("0123456789abcdef") != std::string::npos)
    return false;
  for (const auto &g : provision.gateways)
    if (url == endpoint(g, hash))
      return true;
  return false;
}
uint8_t *download(const Offer &o, const std::string &url) {
  esp_http_client_config_t c = {};
  c.url = url.c_str();
  c.cert_pem = provision.ca.c_str();
  c.client_cert_pem = provision.certificate.c_str();
  c.client_key_pem = provision.key.c_str();
  c.disable_auto_redirect = true;
  c.timeout_ms = 5000;
  c.buffer_size = 4096;
  auto client = esp_http_client_init(&c);
  if (!client)
    return nullptr;
  bool ok = esp_http_client_open(client, 0) == ESP_OK;
  if (ok) {
    auto n = esp_http_client_fetch_headers(client);
    ok = esp_http_client_get_status_code(client) == 200 && n == o.size;
  }
  auto data = ok ? static_cast<uint8_t *>(heap_caps_malloc(
                       o.size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT))
                 : nullptr;
  ok = ok && data;
  unsigned offset = 0;
  while (ok && offset < o.size && o.generation == generation) {
    int n =
        esp_http_client_read(client, reinterpret_cast<char *>(data + offset),
                             std::min(4096u, o.size - offset));
    if (n <= 0) {
      ok = false;
      break;
    }
    offset += n;
  }
  esp_http_client_close(client);
  esp_http_client_cleanup(client);
  ok = ok && offset == o.size && o.generation == generation &&
       avatar_valid(data, o.size, o.state);
  if (ok) {
    uint8_t digest[32];
    size_t n = 0;
    psa_crypto_init();
    ok = psa_hash_compute(PSA_ALG_SHA_256, data, o.size, digest, 32, &n) ==
             PSA_SUCCESS &&
         n == 32;
    char hash[65];
    for (unsigned i = 0; i < 32; i++)
      sprintf(hash + i * 2, "%02x", digest[i]);
    ok = ok && std::strcmp(hash, o.hash) == 0;
  }
  if (!ok) {
    free(data);
    return nullptr;
  }
  return data;
}
void loader(void *) {
  Offer o;
  for (;;) {
    if (xQueueReceive(queue, &o, portMAX_DELAY) != pdTRUE)
      continue;
    if (o.generation != generation)
      continue;
    auto data = download(o, o.url);
    for (const auto &g : provision.gateways)
      if (!data && o.generation == generation) {
        auto url = endpoint(g, o.hash);
        if (url != o.url)
          data = download(o, url);
      }
    if (!data) {
      failures++;
      xSemaphoreTake(mutex, portMAX_DELAY);
      requested = 99;
      xSemaphoreGive(mutex);
      vTaskDelay(pdMS_TO_TICKS(1000));
      continue;
    }
    xSemaphoreTake(mutex, portMAX_DELAY);
    if (o.generation != generation) {
      free(data);
      xSemaphoreGive(mutex);
      continue;
    }
    unsigned slot = 0;
    for (unsigned i = 0; i < 3; i++)
      if (!cache[i].data) {
        slot = i;
        break;
      } else if (cache[i].used < cache[slot].used)
        slot = i;
    free(cache[slot].data);
    cache[slot] = {o, data, ++counter};
    requested = 99;
    xSemaphoreGive(mutex);
  }
}
} // namespace
void ui_avatar_begin(const Provision &p) {
  if (queue)
    return;
  provision = p;
  mutex = xSemaphoreCreateMutex();
  queue = xQueueCreate(1, sizeof(Offer));
  if (mutex && queue)
    xTaskCreate(loader, "sagwa-assets", 8192, nullptr, 1, nullptr);
}
void ui_avatar_offer(const cJSON *p) {
  if (!queue)
    return;
  const auto clips = cJSON_GetObjectItemCaseSensitive(p, "clips");
  if (!cJSON_IsArray(clips) || cJSON_GetArraySize(clips) > 12)
    return;
  Offer fresh[12] = {};
  const cJSON *clip;
  cJSON_ArrayForEach(clip, clips) {
    auto state = cJSON_GetObjectItemCaseSensitive(clip, "state"),
         size = cJSON_GetObjectItemCaseSensitive(clip, "size");
    const char *hash = cJSON_GetStringValue(
                   cJSON_GetObjectItemCaseSensitive(clip, "sha256")),
               *url = cJSON_GetStringValue(
                   cJSON_GetObjectItemCaseSensitive(clip, "url"));
    if (!cJSON_IsNumber(state) || state->valuedouble != state->valueint ||
        state->valueint < 0 || state->valueint >= 12 || !cJSON_IsNumber(size) ||
        size->valuedouble != size->valueint || size->valueint < 16 ||
        size->valueint > int(avatar_max_bytes) || !hash || !url ||
        strlen(url) >= 384 || !allowed(url, hash))
      return;
    auto &o = fresh[state->valueint];
    o.state = state->valueint;
    o.size = size->valueint;
    strcpy(o.hash, hash);
    strcpy(o.url, url);
  }
  xSemaphoreTake(mutex, portMAX_DELAY);
  unsigned next = ++generation;
  for (unsigned i = 0; i < 12; i++) {
    fresh[i].generation = next;
    offers[i] = fresh[i];
  }
  requested = 99;
  xQueueReset(queue);
  xSemaphoreGive(mutex);
}
bool ui_avatar_frame(unsigned pose, unsigned frame, uint16_t *pixels) {
  pose = std::min(pose, 11u);
  std::memcpy(pixels,
              fallback + fallback_poses[pose].offset +
                  (frame % fallback_poses[pose].frames) * 136 * 136 * 2,
              136 * 136 * 2);
  if (!queue || xSemaphoreTake(mutex, 0) != pdTRUE)
    return false;
  bool hit = false;
  for (auto &c : cache)
    if (c.data && c.offer.state == pose &&
        !strcmp(c.offer.hash, offers[pose].hash)) {
      unsigned n = avatar_u16(c.data + 8);
      std::memcpy(pixels, c.data + 16 + (frame % n) * 136 * 136 * 2,
                  136 * 136 * 2);
      c.used = ++counter;
      hit = true;
      break;
    }
  if (!hit && offers[pose].size && requested != pose) {
    requested = pose;
    xQueueOverwrite(queue, &offers[pose]);
  }
  xSemaphoreGive(mutex);
  return hit;
}
cJSON *ui_avatar_status() {
  auto p = cJSON_CreateObject();
  cJSON_AddNumberToObject(p, "download_failures", failures);
  cJSON_AddStringToObject(p, "source", "generated_sagwa_v2");
  return p;
}
} // namespace shell
