#pragma once
#include "weather.hpp"
#include <array>
#include <atomic>
#include <cstdint>
#include <string>
#include <vector>
namespace sagwa {
enum class Emotion : uint8_t {
  idle,
  alert,
  listening,
  thinking,
  speaking,
  working,
  celebrating,
  purring,
  sleeping,
  waking,
  stretching,
  tilted,
  error
};
enum class SkinId : uint8_t {
  pet,
  focus,
  telemetry,
  night,
  sentinel,
  terminal,
  multimedia,
  assistant,
  weather,
  recovery
};
enum class EventKind : uint8_t {
  tick,
  touch,
  stroke,
  tilt,
  shake,
  wake,
  listen,
  think,
  speak,
  done,
  offline,
  cancel,
  skin,
  network_result,
  menu,
  approval,
  sleep,
  stretch,
  celebrate,
  work,
  cancel_request,
  skin_catalog,
  focus_control
};
struct Event {
  EventKind kind = EventKind::tick;
  uint32_t at = 0;
  float x = 0, y = 0, value = 0;
  uint32_t generation = 0;
};
struct SensorSnapshot {
  WeatherSnapshot weather; // UI-owned copy of authenticated gateway data.
  uint32_t at = 0;
  bool imu = false;
  float ax = 0, ay = 0, az = 1, shake = 0;
  int battery = -1, rssi = -127;
  uint32_t heap = 0;
  float cpu = -1, light = 0, proximity = 0;
  bool environment = false;
  uint32_t environment_at = 0;
};
struct Pose {
  float breath = 1, blink = 1, gaze_x = 0, gaze_y = 0, ear_left = 0,
        ear_right = 0, tail = 0, lean = 0, stretch = 1, mouth = 0;
};
class AnimationFSM {
public:
  explicit AnimationFSM(uint32_t seed = 0x53414757) : seed_(seed) {}
  void event(const Event &);
  Pose step(uint32_t ms, const SensorSnapshot &,
            const std::array<float, 3> &bands, float breath_hz = .23f);
  Emotion state() const { return state_; }

private:
  uint32_t random();
  void transition(Emotion, uint32_t, uint32_t hold = 0);
  Emotion state_ = Emotion::idle;
  uint32_t seed_, since_ = 0, until_ = 0, next_blink_ = 0, blink_at_ = 0,
                  previous_ = 0;
  float gaze_x_ = 0, gaze_y_ = 0, target_x_ = 0, target_y_ = 0, ear_left_ = 0,
        ear_right_ = 0, stretch_ = 1, tail_ = 0, velocity_ = 0, blend_ = 0;
};
struct Widget {
  std::string id, type, label;
  int x = 16, y = 150, w = 288, h = 44;
  std::string page = "home";
};
struct Skin {
  SkinId mode = SkinId::pet;
  std::string id = "pet", title = "Sagwa";
  uint32_t fur = 0xEADBC6, patch = 0x513923, eyes = 0x79BCE8;
  float breath_hz = .23f;
  uint8_t brightness = 85;
  bool sounds = true;
  std::vector<Widget> widgets;
  uint32_t revision = 1;
};
std::array<Skin, 10> builtin_skins();
class SkinManager {
public:
  SkinManager();
  bool register_type(const std::string &);
  const std::vector<Skin> &catalog() const { return skins_; }
  const Skin &current() const { return skins_[selected_]; }
  bool select(const std::string &);
  bool apply(const std::string &, const std::string &id, std::string &error);
  bool reload(const std::string &root, const std::string &id,
              std::string &error);
  bool parse(const std::string &json, Skin &candidate,
             std::string &error) const;

private:
  std::vector<Skin> skins_;
  std::vector<std::string> types_;
  size_t selected_ = 0;
};
enum class Provider : uint8_t {
  local,
  homelab,
  openrouter,
  openai,
  xai,
  gemini,
  opencode,
  unavailable
};
enum class Preference : uint8_t { homelab_first, cloud_first, local_only };
struct UserPreferences {
  uint8_t schema = 1, routing = 0;
  uint8_t voice = 1, pet = 1, sounds = 1, sensors = 1;
  char skin[33] = "pet", target[17] = "mac-mini",
       capability[17] = "conversation";
};
bool valid_preferences(const UserPreferences &);
class Navigation {
public:
  int open(int next);
  int back();
  int current() const { return current_; }

private:
  std::array<int, 8> history_{};
  size_t depth_ = 0;
  int current_ = 0;
};
struct EndpointStatus {
  bool enabled = false, reachable = false, has_credentials = false,
       audio_input = false, tools = false;
  uint32_t checked_at = 0;
  std::string small_model, strong_model;
};
struct Request {
  std::string text, capability = "conversation", target = "mac-mini";
  bool private_context = false, tools = false, audio = false, image = false;
  Preference preference = Preference::homelab_first;
  uint32_t generation = 0;
};
bool transcript_request(const Request &captured, const std::string &text,
                        uint32_t generation, Request &out);
struct Route {
  Provider provider = Provider::unavailable;
  std::string model, local_reply;
  int local_command = 0;
};
class LLMRouter {
public:
  Route decide(const Request &, const std::array<EndpointStatus, 7> &,
               uint32_t now, uint32_t excluded = 0) const;
};
bool json_shape_safe(const std::string &, size_t max_bytes,
                     size_t max_depth = 16);
bool valid_uuid(const std::string &);
struct RecoverySnapshot {
  std::string task_id, state, summary, approval_id, action_hash, action;
  uint64_t expires_at = 0;
};
// Only an authenticated device snapshot may supply this input. Parsing never
// authorizes an action, changes generations, or replays microphone/photo data.
bool parse_recovery_snapshot(const std::string &, uint64_t now_epoch_ms,
                             RecoverySnapshot &);
void spectrum(const int16_t *pcm, size_t count, std::array<float, 3> &bands);
class SagwaPluginInterface {
public:
  virtual ~SagwaPluginInterface() = default;
  virtual const char *type() const = 0;
  virtual void mount(void *parent, const Widget &) = 0;
  virtual void update(const SensorSnapshot &, const std::array<float, 3> &,
                      uint32_t) = 0;
  virtual void unmount() = 0;
  virtual void on_event(const Event &) {}
};
struct RuntimeConfig {
  bool wake_enabled = false;
  std::string wake_model_sha256;
  std::string wake_word = "Sagwa", storage_root = "/skins",
              sd_root = "/sdcard/sagwa";
};
void start(const RuntimeConfig &);
} // namespace sagwa
