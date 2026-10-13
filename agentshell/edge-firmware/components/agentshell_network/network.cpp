#include "network.hpp"
#include "esp_app_desc.h"
#include "esp_event.h"
#include "esp_netif_sntp.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "protocol.hpp"
#include <atomic>
#include <cstring>
#include <ctime>
#include <sys/time.h>
namespace shell {
static Provision config;
static QueueHandle_t incoming, controls, outgoing;
static esp_websocket_client_handle_t clients[2];
static std::atomic<bool> online[2], wifi_up;
static std::atomic<int> active{-1};
static std::atomic<uint64_t> sequence;
static std::atomic<uint64_t> persisted_sequence;
static std::atomic<uint32_t> synced_at{0};
static std::atomic<bool> clock_ready{false};
bool time_synchronized() {
  return clock_ready && time(nullptr) >= 1735689600 &&
         uint32_t(esp_timer_get_time() / 1000 - synced_at.load()) < 7200000;
}
static std::string session;
static portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
struct Connection {
  int index;
  std::vector<uint8_t> frame;
  int opcode = 0;
};
static Connection channels[2];
static void event(void *argument, esp_event_base_t, int32_t id, void *raw) {
  auto &c = *static_cast<Connection *>(argument);
  if (id == WEBSOCKET_EVENT_CONNECTED) {
    online[c.index] = true;
    return;
  }
  if (id == WEBSOCKET_EVENT_DISCONNECTED || id == WEBSOCKET_EVENT_ERROR ||
      id == WEBSOCKET_EVENT_CLOSED) {
    online[c.index] = false;
    c.frame.clear();
    return;
  }
  if (id != WEBSOCKET_EVENT_DATA || active.load() != c.index)
    return;
  auto *d = static_cast<esp_websocket_event_data_t *>(raw);
  if (d->op_code != 1 && d->op_code != 2)
    return;
  if (d->payload_len < 0 || d->payload_len > 32768) {
    esp_websocket_client_close(clients[c.index], 0);
    return;
  }
  if (d->payload_offset == 0) {
    c.frame.clear();
    c.opcode = d->op_code;
  }
  if (int(c.frame.size()) != d->payload_offset) {
    c.frame.clear();
    return;
  }
  c.frame.insert(c.frame.end(), d->data_ptr, d->data_ptr + d->data_len);
  if (int(c.frame.size()) == d->payload_len) {
    auto *p = new Packet{c.opcode == 2, std::move(c.frame)};
    if (xQueueSend(incoming, &p, pdMS_TO_TICKS(100)) != pdTRUE) {
      delete p;
      online[c.index] = false;
      esp_websocket_client_close(clients[c.index], 0);
    }
  }
}
static void wifi_event(void *, esp_event_base_t base, int32_t id, void *) {
  if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START)
    esp_wifi_connect();
  if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
    wifi_up = false;
    esp_wifi_connect();
  }
  if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP)
    wifi_up = true;
}
static void dispose(QueueHandle_t q) {
  Packet *p;
  while (xQueueReceive(q, &p, 0) == pdTRUE)
    delete p;
}
static void worker(void *) {
  bool started = false;
  int prior = -1;
  for (;;) {
    if (wifi_up && !started) {
      for (auto client : clients)
        esp_websocket_client_start(client);
      started = true;
    }
    const int chosen = online[0] ? 0 : online[1] ? 1 : -1;
    if (chosen != prior) {
      active = chosen;
      dispose(incoming);
      dispose(outgoing);
      dispose(controls);
      if (chosen >= 0) {
        portENTER_CRITICAL(&lock);
        session = uuid();
        portEXIT_CRITICAL(&lock);
        cJSON *p = cJSON_CreateObject();
        cJSON_AddNumberToObject(p, "last_sequence", sequence.load());
        cJSON *caps = cJSON_AddObjectToObject(p, "capabilities");
        cJSON_AddBoolToObject(caps, "microphone", true);
        cJSON_AddBoolToObject(caps, "camera", true);
        cJSON_AddBoolToObject(caps, "client_routes_transcripts", true);
        cJSON_AddStringToObject(caps, "firmware",
                                esp_app_get_description()->version);
        auto hello = message(session, 0, "device.hello", p);
        cJSON_Delete(p);
        esp_websocket_client_send_text(clients[chosen], hello.data(),
                                       hello.size(), pdMS_TO_TICKS(2000));
      }
      prior = chosen;
    }
    Packet *p = nullptr;
    if (chosen >= 0 &&
        (xQueueReceive(controls, &p, 0) == pdTRUE ||
         xQueueReceive(outgoing, &p, pdMS_TO_TICKS(10)) == pdTRUE)) {
      int result = p->binary
                       ? esp_websocket_client_send_bin(
                             clients[chosen],
                             reinterpret_cast<const char *>(p->data.data()),
                             p->data.size(), pdMS_TO_TICKS(1000))
                       : esp_websocket_client_send_text(
                             clients[chosen],
                             reinterpret_cast<const char *>(p->data.data()),
                             p->data.size(), pdMS_TO_TICKS(1000));
      if (result < 0)
        online[chosen] = false;
      delete p;
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}
bool network_begin(const Provision &p) {
  if (p.ssid.empty() || p.ssid.size() > 32 || p.password.size() > 64)
    return false;
  config = p;
  sequence = load_sequence();
  persisted_sequence = sequence.load();
  incoming = xQueueCreate(48, sizeof(Packet *));
  controls = xQueueCreate(12, sizeof(Packet *));
  outgoing = xQueueCreate(24, sizeof(Packet *));
  if (!incoming || !controls || !outgoing)
    return false;
  esp_netif_init();
  esp_event_loop_create_default();
  esp_netif_create_default_wifi_sta();
  wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
  if (esp_wifi_init(&init) != ESP_OK)
    return false;
  esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, nullptr);
  esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event,
                             nullptr);
  wifi_config_t cfg = {};
  // Wi-Fi fields have fixed byte capacities (including a full32-byte SSID
  // or64-byte hexadecimal PSK); zero initialization supplies shorter padding.
  memcpy(cfg.sta.ssid, p.ssid.data(), p.ssid.size());
  memcpy(cfg.sta.password, p.password.data(), p.password.size());
  esp_wifi_set_storage(WIFI_STORAGE_RAM);
  esp_wifi_set_mode(WIFI_MODE_STA);
  esp_wifi_set_config(WIFI_IF_STA, &cfg);
  esp_wifi_start();
  if (time(nullptr) < 1700000000 && p.epoch > 1700000000) {
    timeval t{time_t(p.epoch), 0};
    settimeofday(&t, nullptr);
  }
  esp_sntp_config_t sntp = ESP_NETIF_SNTP_DEFAULT_CONFIG("time.cloudflare.com");
  sntp.sync_cb = [](struct timeval *t) {
    if (t && t->tv_sec >= 1735689600) {
      synced_at = uint32_t(esp_timer_get_time() / 1000);
      clock_ready = true;
    }
  };
  esp_netif_sntp_init(&sntp);
  for (int i = 0; i < 2; i++) {
    channels[i].index = i;
    esp_websocket_client_config_t c = {};
    c.uri = config.gateways[i].c_str();
    c.cert_pem = config.ca.c_str();
    c.client_cert = config.certificate.c_str();
    c.client_key = config.key.c_str();
    c.buffer_size = 8192;
    c.reconnect_timeout_ms = 5000;
    c.enable_close_reconnect = true;
    c.network_timeout_ms = 8000;
    c.task_stack = 8192;
    c.ping_interval_sec = 15;
    c.pingpong_timeout_sec = 15;
    clients[i] = esp_websocket_client_init(&c);
    if (!clients[i])
      return false;
    esp_websocket_register_events(clients[i], WEBSOCKET_EVENT_ANY, event,
                                  &channels[i]);
  }
  return xTaskCreate(worker, "shell-net", 8192, nullptr, 4, nullptr) == pdPASS;
}
bool connected() { return active.load() >= 0; }
bool receive(Packet &packet) {
  if (!incoming)
    return false;
  Packet *p;
  if (xQueueReceive(incoming, &p, 0) != pdTRUE)
    return false;
  packet = std::move(*p);
  delete p;
  return true;
}
static bool enqueue(Packet *p, QueueHandle_t q) {
  if (!connected() || xQueueSend(q, &p, pdMS_TO_TICKS(250)) != pdTRUE) {
    delete p;
    return false;
  }
  return true;
}
bool send_json(const std::string &s, bool control) {
  return s.size() <= 32768 &&
         enqueue(new Packet{false, std::vector<uint8_t>(s.begin(), s.end())},
                 control ? controls : outgoing);
}
bool send_binary(const std::vector<uint8_t> &bytes) {
  return bytes.size() <= 8249 && enqueue(new Packet{true, bytes}, outgoing);
}
std::string session_id() {
  portENTER_CRITICAL(&lock);
  auto result = session;
  portEXIT_CRITICAL(&lock);
  return result;
}
void last_sequence(uint64_t n) {
  auto previous = sequence.load();
  while (n > previous && !sequence.compare_exchange_weak(previous, n)) {
  }
}
bool persist_sequence() {
  const auto next = sequence.load();
  if (next <= persisted_sequence.load())
    return true;
  if (!save_sequence(next))
    return false;
  persisted_sequence = next;
  return true;
}
} // namespace shell
