// Headless LVGL 9.4 render harness. Hardware/network/audio are fixtures.
// Screens are rendered by the production graphics.cpp, never redrawn in Python.
#include "bsp/m5stack_core_s3.h"
#include "esp_timer.h"
#include "platform.hpp"
#include <cassert>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>

struct HostQueue {
  size_t capacity, size;
  std::deque<std::vector<uint8_t>> items;
};
static std::vector<std::unique_ptr<HostQueue>> queues;
QueueHandle_t xQueueCreate(unsigned capacity, size_t size) {
  queues.push_back(std::make_unique<HostQueue>(HostQueue{capacity, size, {}}));
  return queues.back().get();
}
BaseType_t xQueuePeek(QueueHandle_t q, void *out, TickType_t) {
  if (q->items.empty())
    return pdFALSE;
  memcpy(out, q->items.front().data(), q->size);
  return pdTRUE;
}
BaseType_t xQueueReceive(QueueHandle_t q, void *out, TickType_t wait) {
  if (!xQueuePeek(q, out, wait))
    return pdFALSE;
  q->items.pop_front();
  return pdTRUE;
}
BaseType_t xQueueSend(QueueHandle_t q, const void *in, TickType_t) {
  if (q->items.size() >= q->capacity)
    return pdFALSE;
  const auto *data = static_cast<const uint8_t *>(in);
  q->items.emplace_back(data, data + q->size);
  return pdTRUE;
}
BaseType_t xQueueOverwrite(QueueHandle_t q, const void *in) {
  q->items.clear();
  return xQueueSend(q, in, 0);
}
static uint32_t milliseconds = 1000;
static std::vector<uint16_t> framebuffer(320 * 240), draw_a(320 * 240),
    draw_b(320 * 240);
static esp_lcd_panel_io_callbacks_t completion{};
static void *completion_context = nullptr;
static std::filesystem::path output;
static unsigned case_index = 0, frames_in_case = 0;
static unsigned sound_commands = 0;
static unsigned decision_commands = 0;
static bool decision_queue_ok = true, last_decision_approve = false;
static lv_indev_data_t touch_data{};
static bool testing_gestures = false;
static bool testing_approvals = false;
static bool testing_focus = false;
static unsigned focus_test = 0, focus_saves = 0;
static uint32_t paused_remaining = 0;
static unsigned approval_test = 0;
static unsigned gesture_index = 0, gesture_phase = 0;
struct Gesture {
  const char *name;
  lv_point_t start, end;
  int expected;
};
static const std::vector<Gesture> gestures = {
    {"left-edge opens menu", {3, 20}, {100, 20}, 9},
    {"menu opens modes", {80, 100}, {80, 100}, 1},
    {"back returns to menu", {3, 20}, {100, 20}, 9},
    {"back returns home", {3, 20}, {100, 20}, 0},
    {"right-edge opens tools", {316, 80}, {230, 80}, 2},
    {"tools opens local sensors", {80, 150}, {80, 150}, 14},
    {"back returns to tools", {3, 20}, {100, 20}, 2},
    {"back returns home again", {3, 20}, {100, 20}, 0},
    {"top-edge opens preferences", {200, 3}, {200, 80}, 3},
    {"preferences opens voice", {80, 52}, {80, 52}, 15},
    {"voice toggles output", {80, 52}, {80, 52}, 15},
    {"voice reactivation clears stopped clip", {80, 52}, {80, 52}, 15},
    {"back returns to preferences", {3, 20}, {100, 20}, 3},
    {"back returns home after voice", {3, 20}, {100, 20}, 0},
    {"tap opens full reading", {80, 166}, {80, 166}, 4},
    {"back leaves reading", {3, 20}, {100, 20}, 0},
    {"stroke pets avatar without recording", {140, 60}, {190, 60}, 0},
    {"terminal tap opens local history", {160, 185}, {160, 185}, 18},
    {"history back returns to terminal", {3, 20}, {100, 20}, 0},
    {"terminal response tap keeps full reading", {160, 185}, {160, 185}, 4},
    {"reading back returns to terminal", {3, 20}, {100, 20}, 0},
};
struct Case {
  const char *name;
  int page;
  const char *skin;
  const char *text;
};
static const std::vector<Case> cases = {
    {"home", 0, "pet", "Estoy aquí contigo. ¿Qué necesitas?"},
    {"menu", 9, "pet", ""},
    {"tools", 2, "pet", ""},
    {"settings", 3, "pet", ""},
    {"skins", 1, "pet", ""},
    {"agents", 11, "pet", ""},
    {"destinations", 12, "pet", ""},
    {"tasks", 13, "pet", ""},
    {"sensors", 14, "pet", ""},
    {"voice", 15, "pet", ""},
    {"pet-settings", 16, "pet", ""},
    {"routing", 17, "pet", ""},
    {"focus-ready", 10, "focus", ""},
    {"focus-running", 10, "focus", ""},
    {"focus-paused", 10, "focus", ""},
    {"focus-completed", 10, "focus", ""},
    {"reading", 4, "pet", ""},
    {"cancel", 5, "pet", ""},
    {"approval", 6, "pet", ""},
    {"camera-preview", 8, "pet", ""},
    {"plugin-notes", 7, "notes_pet", ""},
    {"mode-focus", 0, "focus", "Estoy aquí contigo."},
    {"mode-telemetry", 0, "telemetry", "Estoy aquí contigo."},
    {"mode-night", 0, "night", "Estoy aquí contigo."},
    {"mode-sentinel", 0, "sentinel", "Estoy aquí contigo."},
    {"mode-terminal", 0, "terminal", "Estoy aquí contigo."},
    {"local-history", 18, "terminal", ""},
    {"mode-multimedia", 0, "multimedia", "Estoy aquí contigo."},
    {"mode-assistant", 0, "assistant", "Estoy aquí contigo. ¿Qué necesitas?"},
    {"mode-weather", 0, "weather", "Estoy aquí contigo."},
    {"mode-weather-current", 0, "weather", "Estoy aquí contigo."},
    {"mode-weather-stale", 0, "weather", "Estoy aquí contigo."},
    {"mode-recovery", 0, "recovery",
     "Se perdió la conexión. Puedo acompañarte localmente."},
};
namespace sagwa {
static Runtime rt;
Runtime &runtime() { return rt; }
uint32_t now_ms() { return milliseconds; }
void post_turn(EventKind kind, uint32_t generation, float x, float y,
               float value) {
  Event event{kind, milliseconds, x, y, value, generation};
  xQueueSend(rt.events, &event, 0);
}
void post(EventKind kind, float x, float y, float value) {
  post_turn(kind, rt.generation, x, y, value);
}
bool audio_send(AudioCommand *p) {
  ++sound_commands;
  delete p;
  return true;
}
bool decide(Decision *p) {
  ++decision_commands;
  last_decision_approve = p->approve;
  delete p;
  return decision_queue_ok;
}
void save_preferences() {}
void save_focus() {
  auto snapshot = rt.focus.snapshot(now_ms());
  xQueueOverwrite(rt.focus_saves, &snapshot);
  ++focus_saves;
}
bool apply_request_context(Request &request) {
  request.target = rt.selected_target;
  request.capability = rt.selected_capability;
  return true;
}
bool capture_requested() {
  rt.camera_open = true;
  return true;
}
void host_screen(int, const std::string &, const std::string &,
                 const std::string &, std::shared_ptr<std::vector<uint8_t>>);
int host_page();
bool host_decision_pending();
} // namespace sagwa
namespace shell {
bool time_synchronized() { return true; }
} // namespace shell
int64_t esp_timer_get_time() { return int64_t(milliseconds) * 1000; }
TickType_t xTaskGetTickCount() { return milliseconds; }
static void flush(lv_display_t *display, const lv_area_t *area, uint8_t *data) {
  assert(area->x1 >= 0 && area->x2 < 320 && area->y1 >= 0 && area->y2 < 240);
  const auto *pixels = reinterpret_cast<const uint16_t *>(data);
  for (int y = area->y1; y <= area->y2; ++y)
    for (int x = area->x1; x <= area->x2; ++x)
      framebuffer[size_t(y) * 320 + x] = *pixels++;
  if (completion.on_color_trans_done)
    completion.on_color_trans_done(nullptr, nullptr, completion_context);
  else
    lv_display_flush_ready(display);
}
int esp_lcd_panel_io_register_event_callbacks(
    esp_lcd_panel_io_handle_t, const esp_lcd_panel_io_callbacks_t *callbacks,
    void *ctx) {
  completion = *callbacks;
  completion_context = ctx;
  return ESP_OK;
}
esp_lcd_panel_io_handle_t bsp_display_get_panel_io() { return nullptr; }
lv_display_t *bsp_display_start_with_config(const bsp_display_cfg_t *cfg) {
  assert(cfg->double_buffer && cfg->flags.buff_spiram && cfg->flags.buff_dma);
  lv_init();
  auto *display = lv_display_create(320, 240);
  lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);
  lv_display_set_buffers(display, draw_a.data(), draw_b.data(),
                         draw_a.size() * sizeof(uint16_t),
                         LV_DISPLAY_RENDER_MODE_PARTIAL);
  lv_display_set_flush_cb(display, flush);
  auto *input = lv_indev_create();
  lv_indev_set_type(input, LV_INDEV_TYPE_POINTER);
  lv_indev_set_display(input, display);
  lv_indev_set_read_cb(
      input, [](lv_indev_t *, lv_indev_data_t *data) { *data = touch_data; });
  touch_data.state = LV_INDEV_STATE_RELEASED;
  return display;
}
bool bsp_display_lock(uint32_t) { return true; }
void bsp_display_unlock() {}
void bsp_display_backlight_on() {}
void bsp_display_brightness_set(int brightness) {
  assert(brightness >= 0 && brightness <= 100);
}
struct GalleryComplete {};
static bool has_label(lv_obj_t *object, const char *text) {
  if (lv_obj_check_type(object, &lv_label_class) &&
      std::string(lv_label_get_text(object)).find(text) != std::string::npos)
    return true;
  for (uint32_t i = 0; i < lv_obj_get_child_count(object); ++i)
    if (has_label(lv_obj_get_child(object, i), text))
      return true;
  return false;
}
void vTaskDelete(void *) {
  throw std::runtime_error("Unexpected UI task shutdown");
}
static void save_frame(const std::filesystem::path &path) {
  // Catch configuration regressions that silently omit compressed Inter.
  size_t white = 0;
  for (size_t i = 45 * 320; i < framebuffer.size(); ++i)
    if (framebuffer[i] == 0xffff)
      ++white;
  assert(white > 25);
  std::ofstream file(path, std::ios::binary);
  file << "P6\n320 240\n255\n";
  for (auto color : framebuffer) {
    const unsigned r = (color >> 11) & 31, g = (color >> 5) & 63,
                   b = color & 31;
    const char rgb[] = {char((r << 3) | (r >> 2)), char((g << 2) | (g >> 4)),
                        char((b << 3) | (b >> 2))};
    file.write(rgb, sizeof rgb);
  }
  assert(file.good());
}
static void setup_case() {
  const auto &item = cases[case_index];
  auto &r = sagwa::runtime();
  r.focus.reset();
  if (std::string(item.name) == "focus-running")
    r.focus.start(milliseconds);
  else if (std::string(item.name) == "focus-paused") {
    r.focus.start(milliseconds - 51000);
    r.focus.pause(milliseconds);
  } else if (std::string(item.name) == "focus-completed") {
    r.focus.start(milliseconds - 1500000);
    r.focus.tick(milliseconds);
  }
  std::shared_ptr<std::vector<uint8_t>> preview;
  if (item.page == 8) {
    preview = std::make_shared<std::vector<uint8_t>>(320 * 240 * 2);
    for (unsigned y = 0; y < 240; ++y)
      for (unsigned x = 0; x < 320; ++x) {
        const uint16_t color = ((x / 40 + y / 40) % 2) ? 0x8410 : 0x3186;
        (*preview)[(y * 320 + x) * 2] = uint8_t(color >> 8);
        (*preview)[(y * 320 + x) * 2 + 1] = uint8_t(color);
      }
  }
  r.bands = {.25f, .5f, .15f};
  r.mic_monitoring = item.skin == std::string("sentinel");
  r.device_status.received_at = milliseconds;
  r.device_status.weather = {};
  if (std::string(item.name) == "mode-weather-current" ||
      std::string(item.name) == "mode-weather-stale") {
    auto &weather = r.device_status.weather;
    weather.available = true;
    std::strcpy(weather.city, "Ray City, GA");
    weather.temperature_centi_c = 2500;
    weather.condition = sagwa::WeatherCondition::rain;
    weather.received_at = milliseconds;
    weather.ttl_ms = std::string(item.name) == "mode-weather-current" ? 900000 : 1;
  }
  sagwa::SensorSnapshot sensors{};
  sensors.imu = sensors.environment = true;
  sensors.at = sensors.environment_at = milliseconds;
  sensors.ax = .02f;
  sensors.ay = .01f;
  sensors.az = .99f;
  sensors.light = 230;
  sensors.proximity = 80;
  sensors.heap = 7200000;
  sensors.cpu = 17;
  sensors.rssi = -49;
  sensors.battery = 81;
  xQueueOverwrite(r.sensors, &sensors);
  r.status_revision.fetch_add(1);
  const std::string full =
      item.page == 6
          ? "Acción de prueba: leer un diagnóstico local.\nDestino: Mac "
            "mini.\nSin cambios ni envío de fotos.\nEsta galería no autoriza "
            "ninguna acción."
          : "Respuesta de prueba para lectura ampliada.\n\nLa campaña queda en "
            "US$20 diarios: Cerca US$14 y Llamada US$6.\n\nAcentos: á é í ó ú "
            "ü ñ ¿¡.\n\nDesliza para leer y desde el borde izquierdo para "
            "volver.\n\nEsta galería usa datos sintéticos y no modifica "
            "anuncios, tareas ni equipos.";
  sagwa::host_screen(item.page, item.skin, item.text, full, std::move(preview));
  if (item.page == 18) {
    auto *reply = new sagwa::Reply{r.generation, "", "", "PRIVATE_TEST_ERROR"};
    xQueueSend(r.replies, &reply, 0);
  }
}
void vTaskDelayUntil(TickType_t *next, TickType_t increment) {
  if (testing_focus) {
    const bool wait = focus_test == 3 || focus_test == 5;
    touch_data.state = !wait && gesture_phase < 3 ? LV_INDEV_STATE_PRESSED
                                                  : LV_INDEV_STATE_RELEASED;
    if (focus_test == 0)
      touch_data.point = {160, 185};
    else if (focus_test == 6)
      touch_data.point = {80, 154};
    else if (focus_test == 7)
      touch_data.point = {80, 202};
    else if (focus_test == 8)
      touch_data.point =
          gesture_phase == 0 ? lv_point_t{3, 20} : lv_point_t{100, 20};
    else
      touch_data.point = {80, 105};
    if (wait && gesture_phase == 0)
      milliseconds +=
          focus_test == 3 ? 90000 : sagwa::runtime().focus.remaining_ms() + 1;
  }
  if (testing_approvals) {
    const bool hold = approval_test == 1 || approval_test == 2;
    const unsigned down = hold ? 20 : 3;
    const bool acknowledgment = approval_test == 3 || approval_test == 5;
    touch_data.state = !acknowledgment && gesture_phase < down
                           ? LV_INDEV_STATE_PRESSED
                           : LV_INDEV_STATE_RELEASED;
    touch_data.point =
        approval_test == 4 ? lv_point_t{80, 213} : lv_point_t{80, 164};
  }
  if (testing_gestures) {
    const auto &g = gestures[gesture_index];
    touch_data.state =
        gesture_phase < 3 ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
    touch_data.point = gesture_phase == 0 ? g.start : g.end;
  }
  milliseconds += increment;
  sagwa::SensorSnapshot current{};
  if (xQueuePeek(sagwa::runtime().sensors, &current, 0)) {
    current.at = current.environment_at = milliseconds;
    xQueueOverwrite(sagwa::runtime().sensors, &current);
  }
  *next = milliseconds;
  lv_tick_inc(increment);
  const auto focus_state_before_callback = sagwa::runtime().focus.state();
  const auto focus_phase_before_callback = sagwa::runtime().focus.phase();
  const auto focus_remaining_before_callback =
      sagwa::runtime().focus.remaining_ms();
  lv_timer_handler();
  if (testing_focus) {
    // Exercise the real callback and prove it only queues a control. The next
    // UI_Task iteration applies it, even when LVGL runs in another task.
    assert(sagwa::runtime().focus.state() == focus_state_before_callback &&
           sagwa::runtime().focus.phase() == focus_phase_before_callback &&
           sagwa::runtime().focus.remaining_ms() ==
               focus_remaining_before_callback);
    if (++gesture_phase < 6)
      return;
    auto &timer = sagwa::runtime().focus;
    using Timer = sagwa::FocusTimer;
    if (focus_test == 0)
      assert(sagwa::host_page() == 10 && timer.state() == Timer::State::ready);
    else if (focus_test == 1 || focus_test == 4)
      assert(timer.state() == Timer::State::running);
    else if (focus_test == 2) {
      assert(timer.state() == Timer::State::paused);
      paused_remaining = timer.remaining_ms();
    } else if (focus_test == 3)
      assert(timer.state() == Timer::State::paused &&
             timer.remaining_ms() == paused_remaining);
    else if (focus_test == 5)
      assert(timer.state() == Timer::State::complete &&
             has_label(lv_screen_active(), "Terminado"));
    else if (focus_test == 6)
      assert(timer.phase() == Timer::Phase::rest &&
             timer.state() == Timer::State::running);
    else if (focus_test == 7)
      assert(timer.phase() == Timer::Phase::rest &&
             timer.state() == Timer::State::ready &&
             timer.remaining_seconds() == 300);
    else if (focus_test == 8) {
      assert(sagwa::host_page() == 0 && timer.state() == Timer::State::ready &&
             focus_saves >= 6);
      std::cout << "FOCUS PASS: actual LVGL touch start/pause/resume, paused "
                   "time stable, completion, rest/reset, back gesture and "
                   "queued persistence\n";
      testing_focus = false;
      testing_approvals = true;
      gesture_phase = 0;
      sagwa::host_screen(6, "pet", "", "Acción original: leer diagnóstico.",
                         {});
      return;
    }
    ++focus_test;
    gesture_phase = 0;
    return;
  }
  if (testing_approvals) {
    const unsigned total = approval_test == 1 || approval_test == 2 ? 23 : 6;
    if (++gesture_phase < total)
      return;
    auto &r = sagwa::runtime();
    if (approval_test == 0) {
      assert(!sagwa::host_decision_pending() && decision_commands == 0);
      // Ordinary task output must never replace the immutable action being
      // approved.
      auto *reply = new sagwa::Reply{r.generation, "Estado de tarea.",
                                     "Texto ajeno a la acción."};
      xQueueSend(r.replies, &reply, 0);
      decision_queue_ok = false;
    } else if (approval_test == 1) {
      assert(
          has_label(lv_screen_active(), "Acción original: leer diagnóstico."));
      assert(!has_label(lv_screen_active(), "Texto ajeno a la acción."));
      assert(!sagwa::host_decision_pending() && decision_commands == 1);
      assert(sagwa::host_page() == 6);
      decision_queue_ok = true;
    } else if (approval_test == 2 || approval_test == 4) {
      assert(sagwa::host_decision_pending() && sagwa::host_page() == 6);
      assert(last_decision_approve == (approval_test == 2));
      auto *reply = new sagwa::Reply{r.generation};
      reply->decision_id = "22222222-2222-4222-8222-222222222222";
      reply->decision_ok = approval_test == 4;
      xQueueSend(r.replies, &reply, 0);
    } else if (approval_test == 3) {
      assert(!sagwa::host_decision_pending() && sagwa::host_page() == 6);
    } else if (approval_test == 5) {
      assert(!sagwa::host_decision_pending() && sagwa::host_page() == 0);
      assert(decision_commands == 3);
      std::cout << "APPROVAL PASS: short tap rejected, queue failure retained, "
                   "ACK failure retained, denial waits for successful ACK\n";
      throw GalleryComplete{};
    }
    ++approval_test;
    gesture_phase = 0;
    return;
  }
  if (testing_gestures) {
    if (++gesture_phase < 6)
      return;
    const auto &g = gestures[gesture_index];
    if (sagwa::host_page() != g.expected)
      throw std::runtime_error(std::string(g.name) + ": unexpected page " +
                               std::to_string(sagwa::host_page()));
    std::cout << "GESTURE PASS " << g.name << '\n';
    if (gesture_index == 16)
      sagwa::host_screen(0, "terminal", "Estoy aquí contigo.", "", {});
    if (gesture_index == 17) {
      assert(has_label(lv_screen_active(), "Historial local"));
      assert(has_label(lv_screen_active(), "Solicitud fallida"));
      assert(!has_label(lv_screen_active(), "PRIVATE_TEST_ERROR"));
    }
    if (gesture_index == 18)
      sagwa::host_screen(0, "terminal", "Respuesta breve.",
                         "Respuesta completa prioritaria.", {});
    if (gesture_index == 19)
      assert(has_label(lv_screen_active(), "Respuesta completa prioritaria."));
    if (gesture_index == 10)
      assert(!sagwa::runtime().voice_enabled);
    if (gesture_index == 11)
      assert(sagwa::runtime().voice_enabled &&
             sagwa::runtime().stopped_audio_generation == 0);
    gesture_phase = 0;
    if (++gesture_index == gestures.size()) {
      assert(sound_commands > 0 && !sagwa::runtime().recording &&
             !sagwa::runtime().camera_open);
      testing_gestures = false;
      testing_focus = true;
      gesture_phase = 0;
      sagwa::runtime().focus.reset();
      sagwa::host_screen(0, "focus", "Estoy aquí contigo.",
                         "Respuesta completa.", {});
      return;
    }
    return;
  }
  ++frames_in_case;
  if (frames_in_case == 12) {
    if (std::string(cases[case_index].name) == "mode-weather-current") {
      assert(has_label(lv_screen_active(), "Ray City, GA"));
      assert(has_label(lv_screen_active(), "pronóstico NWS"));
    }
    if (std::string(cases[case_index].name) == "mode-weather-stale") {
      assert(has_label(lv_screen_active(), "sin dato reciente"));
      assert(!has_label(lv_screen_active(), "25.0"));
    }
    if (cases[case_index].page == 18) {
      assert(has_label(lv_screen_active(), "Solicitud fallida"));
      assert(!has_label(lv_screen_active(), "PRIVATE_TEST_ERROR"));
    }
    save_frame(output / (std::string(cases[case_index].name) + ".ppm"));
    std::cout << "RENDERED " << cases[case_index].name << '\n';
    frames_in_case = 0;
    if (++case_index == cases.size()) {
      testing_gestures = true;
      sagwa::host_screen(0, "pet", "Estoy aquí contigo.",
                         "Respuesta completa de prueba.", {});
      return;
    }
    setup_case();
  }
}
int main(int argc, char **argv) {
  assert(argc == 2);
  output = argv[1];
  std::filesystem::create_directories(output);
  auto &r = sagwa::runtime();
  r.events = xQueueCreate(24, sizeof(sagwa::Event));
  r.focus_saves = xQueueCreate(1, sizeof(sagwa::FocusTimer::Snapshot));
  r.sensors = xQueueCreate(1, sizeof(sagwa::SensorSnapshot));
  r.requests = xQueueCreate(4, sizeof(sagwa::Routed *));
  r.replies = xQueueCreate(8, sizeof(sagwa::Reply *));
  r.reloads = xQueueCreate(8, sizeof(sagwa::Descriptor *));
  r.camera_results = xQueueCreate(1, sizeof(sagwa::CameraResult *));
  static EventBits_t flags =
      sagwa::wifi_bit | sagwa::wss_bit | sagwa::audio_bit;
  r.flags = &flags;
  r.device_status.agents = {
      {"muse", true}, {"codex", true}, {"grok", false}, {"opencode", false}};
  r.device_status.nodes = {{"mac-mini", true}, {"tuf-infra", false}};
  r.device_status.task_state = "completed";
  r.device_status.task_summary =
      "Prueba de interfaz completada. Datos sintéticos.";
  std::string error;
  assert(r.skins.apply(
      R"({"schema":1,"revision":1,"id":"notes_pet","base":"pet","title":"Notas","widgets":[{"id":"notes","type":"text","page":"notas","label":"Plugin nativo con descriptor JSON.\nEsta pantalla usa la misma tipografía y el mismo negro.","x":16,"y":40,"w":288,"h":176}]})",
      "notes_pet", error));
  setup_case();
  try {
    sagwa::ui_task(nullptr);
  } catch (const GalleryComplete &) {
    lv_deinit();
    std::cout << "PASS: " << cases.size() << " LVGL screens and "
              << gestures.size()
              << " actual LVGL pointer gestures; synthetic inputs, no hardware "
                 "claim\n";
    return 0;
  }
  return 1;
}
