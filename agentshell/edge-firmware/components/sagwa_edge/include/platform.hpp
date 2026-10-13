#pragma once
#include "edge.hpp"
#include "focus_timer.hpp"
#include "frame_metrics.hpp"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "storage.hpp"
#include <functional>
#include <memory>
namespace sagwa {
struct AudioCommand {
  enum Kind : uint8_t {
    ack,
    purr,
    complaint,
    record_begin,
    record_end,
    stop,
    pcm,
    end_stream
  } kind;
  uint32_t generation;
  std::vector<uint8_t> bytes;
};
struct Routed {
  Request request;
  Route route;
  std::vector<uint8_t> audio;
  uint32_t excluded = 0;
};
struct Reply {
  uint32_t generation;
  std::string brief, detail, error;
  std::string approval_id, action_hash;
  uint64_t expires_at = 0;
  std::string decision_id;
  bool decision_ok = false, clear_approval = false;
  Reply(uint32_t gen, std::string b = {}, std::string d = {},
        std::string e = {}, std::string aid = {}, std::string hash = {},
        uint64_t expiry = 0)
      : generation(gen), brief(std::move(b)), detail(std::move(d)),
        error(std::move(e)), approval_id(std::move(aid)),
        action_hash(std::move(hash)), expires_at(expiry) {}
};
struct Decision {
  std::string approval_id, action_hash;
  uint64_t expires_at = 0;
  bool approve = false;
  uint32_t generation = 0;
};
struct Descriptor {
  std::string json, id;
};
struct CameraResult {
  uint32_t generation = 0;
  std::shared_ptr<std::vector<uint8_t>> pixels;
  std::string error;
};
struct UpdateOffer {
  std::string json;
};
struct DeviceChoice {
  std::string id;
  bool available = false;
};
struct DeviceStatus {
  WeatherSnapshot weather;
  uint32_t received_at = 0;
  std::vector<DeviceChoice> agents, nodes;
  std::string task_id, task_state, task_summary;
};
struct CloudProfile {
  bool enabled = false, audio_input = false;
  std::string key, small_model, strong_model;
  bool responses_api = false;
};
struct TokenSet {
  std::string access, refresh;
  int64_t expires_at = 0;
};
// Implement only a provider's documented, authorized refresh flow. No
// subscription scraping.
class OAuthAdapter {
public:
  virtual ~OAuthAdapter() = default;
  virtual Provider provider() const = 0;
  virtual bool refresh(const TokenSet &, TokenSet &, std::string &) = 0;
};
class CredentialStore {
public:
  bool load();
  bool profile(Provider, CloudProfile &) const;
  bool install(Provider, const CloudProfile &);
  bool save_tokens(Provider, const TokenSet &);
  bool load_tokens(Provider, TokenSet &) const;

private:
  std::array<CloudProfile, 7> profiles_{};
  bool encrypted_ = false;
};
inline constexpr std::array<const char *, 11> measured_task_names = {
    "UI_Task", "Audio_Task", "Sensor_Task", "Router_Task", "Network_Task",
    "Console_Task", "Storage_Task", "Camera_Task", "Maintenance_Tas",
    "taskLVGL", "sensors_evt"};
struct Runtime {
  RuntimeConfig config;
  std::array<std::atomic<uint32_t>, measured_task_names.size()> stack_free_bytes{};
  std::atomic<uint32_t> stack_metrics_at{0};
  SkinManager skins;
  CredentialStore credentials;
  shell::Provision provision;
  QueueHandle_t events = nullptr, sensors = nullptr, requests = nullptr,
                network = nullptr, replies = nullptr, audio = nullptr,
                decisions = nullptr, reloads = nullptr,
                camera_requests = nullptr, camera_results = nullptr,
                updates = nullptr, preferences = nullptr, focus_saves = nullptr;
  EventGroupHandle_t flags = nullptr;
  SemaphoreHandle_t bands_mutex = nullptr, status_mutex = nullptr;
  std::atomic<uint32_t> generation{1};
  std::atomic<bool> sound_enabled{true}, recording{false}, playing{false},
      audio_fault{false};
  std::atomic<bool> sentinel_enabled{false};
  std::atomic<bool> voice_enabled{true}, pet_enabled{true}, pet_sounds{true},
      pet_sensors{true}, preferences_dirty{false},
      remote_preferences_dirty{false};
  std::atomic<bool> mic_monitoring{false};
  std::atomic<bool> camera_open{false}, camera_capturing{false},
      updating{false}, ui_ready{false}, boot_verified{false};
  std::atomic<uint32_t> failed_audio_generation{0};
  std::atomic<uint32_t> stopped_audio_generation{0};
  std::atomic<uint32_t> audio_stop_revision{0};
  std::array<float, 3> bands{};
  std::array<EndpointStatus, 7> endpoints{};
  DeviceStatus device_status; // status_mutex guards strings and vectors.
  std::atomic<uint32_t> status_revision{0};
  std::string selected_target = "mac-mini",
              selected_capability = "conversation";
  std::string
      pending_skin_id; // UI restores custom skin after its descriptor loads.
  std::atomic<Preference> preference{Preference::homelab_first};
  bool provisioned = false;
  std::atomic<uint32_t> ui_us{0}, wake_audio_us{0};
  // LCD counters advance from the SPI completion ISR, not UI loop iterations.
  std::atomic<uint32_t> lcd_transfer_us{0},
      lcd_last_at_ms{0}, lcd_frame_gap_max_us{0},
      touch_to_lcd_us{0}, sensor_to_lcd_us{0}, touch_pending_ms{0},
      sensor_pending_ms{0}, audio_written_samples{0}, audio_write_failures{0},
      camera_captures{0}, camera_failures{0}, ui_lock_misses{0};
  std::atomic<bool> lcd_dma_metrics{false};
  // S-201 N3a: SPI frame accounting, 1 s wall-clock windows sampled by UI_Task
  // and bounded latency windows published at the same period.
  FrameCompletions lcd_completions;
  FrameRateWindow lcd_rate{1000};
  LatencyWindow ui_lock_wait, lcd_invalidate_to_refr, lcd_refr_render,
      lcd_frame_gap;
  PendingStamp lcd_invalidate_pending, lcd_refr_started;
  std::atomic<uint32_t> ui_port_wakes{0};
  FocusTimer
      focus; // UI-owned; storage receives copies, never reads this clock.
};
constexpr EventBits_t wifi_bit = 1, wss_bit = 2, wake_bit = 4, audio_bit = 8;
Runtime &runtime();
inline void stop_voice() {
  auto &r = runtime();
  r.stopped_audio_generation = r.generation.load();
  r.audio_stop_revision.fetch_add(1);
}
inline void resume_voice() { runtime().stopped_audio_generation = 0; }
uint32_t now_ms();
void post(EventKind, float x = 0, float y = 0, float value = 0);
void post_turn(EventKind, uint32_t generation, float x = 0, float y = 0,
               float value = 0);
bool submit(Request *);
bool audio_send(AudioCommand *);
bool decide(Decision *);
void ui_reply(Reply *);
void ui_task(void *);
void audio_task(void *);
void sensor_task(void *);
void router_task(void *);
void network_task(void *);
void console_task(void *);
void storage_task(void *);
void camera_task(void *);
void maintenance_task(void *);
bool capture_requested();
cJSON *telemetry();
void save_preferences(); // UI owner snapshots; storage task persists off UI.
void save_focus();       // UI owner snapshots a paused-on-reboot timer, off UI
                         // writes.
bool apply_request_context(Request &);
using PluginFactory = std::function<std::unique_ptr<SagwaPluginInterface>()>;
bool register_plugin(
    const std::string &,
    PluginFactory); // register before start(), trusted native code only
bool cloud_query(const Routed &, const CloudProfile &, Reply &);
} // namespace sagwa
