#include "bsp/m5stack_core_s3.h"
#include "esp_timer.h"
#include "lvgl.h"
#include "network.hpp"
#include "platform.hpp"
#include "cat_raster.hpp"
#include "diagnostics.hpp"
#include "skin_template.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <dirent.h>
#include <map>
#include <sys/stat.h>
namespace sagwa {
namespace {
std::atomic<uint32_t> flush_started_us{0}, frame_touch_ms{0},
    frame_sensor_ms{0};
std::atomic<bool> flush_last{false};
// Mirrors esp_lvgl_port's completion callback and keeps its flush-ready signal.
// No allocation, logging, floating point, JSON or LVGL object mutation in ISR.
bool lcd_done(esp_lcd_panel_io_handle_t, esp_lcd_panel_io_event_data_t *,
              void *ctx) {
  auto &r = runtime();
  const uint32_t us = uint32_t(esp_timer_get_time());
  r.lcd_transfers.fetch_add(1);
  r.lcd_transfer_us = us - flush_started_us.load();
  if (flush_last.load()) {
    static uint32_t previous_us = 0;
    const uint32_t gap = previous_us ? us - previous_us : 0;
    previous_us = us;
    auto maximum = r.lcd_frame_gap_max_us.load();
    while (gap > maximum &&
           !r.lcd_frame_gap_max_us.compare_exchange_weak(maximum, gap)) {
    }
    r.lcd_frames.fetch_add(1);
    r.lcd_last_at_ms = uint32_t(esp_timer_get_time() / 1000);
    if (auto at = frame_touch_ms.exchange(0))
      r.touch_to_lcd_us = (r.lcd_last_at_ms.load() - at) * 1000;
    if (auto at = frame_sensor_ms.exchange(0))
      r.sensor_to_lcd_us = (r.lcd_last_at_ms.load() - at) * 1000;
  }
  lv_display_flush_ready(static_cast<lv_display_t *>(ctx));
  return false;
}
void lcd_flush_start(lv_event_t *event) {
  auto *display = static_cast<lv_display_t *>(lv_event_get_target(event));
  auto &r = runtime();
  flush_started_us = uint32_t(esp_timer_get_time());
  flush_last = lv_display_flush_is_last(display);
  if (auto at = r.touch_pending_ms.exchange(0))
    frame_touch_ms = at;
  if (auto at = r.sensor_pending_ms.exchange(0))
    frame_sensor_ms = at;
  static uint32_t window_ms = 0, previous_frames = 0;
  const uint32_t ms = now_ms(), frames = r.lcd_frames;
  if (!window_ms) {
    window_ms = ms;
    previous_frames = frames;
  } else if (ms - window_ms >= 1000) {
    r.lcd_fps_milli = uint32_t(uint64_t(frames - previous_frames) * 1000000 /
                               (ms - window_ms));
    window_ms = ms;
    previous_frames = frames;
  }
}
} // namespace
extern "C" const lv_font_t inter16;
extern "C" {
extern const lv_image_dsc_t badge_cat, badge_listening, badge_thinking,
    badge_executing, badge_speaking, badge_approval, badge_warning,
    badge_sleeping, badge_camera;
}
static std::map<std::string, PluginFactory> factories;
bool register_plugin(const std::string &t, PluginFactory f) {
  if (!f || factories.size() >= 32 || t.empty() || t.size() > 32)
    return false;
  factories[t] = std::move(f);
  return true;
}
static lv_obj_t *label(lv_obj_t *p, int x, int y, int w, int h,
                       const char *text) {
  auto *l = lv_label_create(p);
  lv_obj_set_pos(l, x, y);
  lv_obj_set_size(l, w, h);
  lv_obj_set_style_text_font(l, &inter16, 0);
  lv_obj_set_style_text_color(l, lv_color_white(), 0);
  lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
  lv_label_set_text(l, text);
  return l;
}
static DiagnosticHistory diagnostics;
static void open_page(int next);
class BuiltinWidget final : public SagwaPluginInterface {
  std::string type_;
  lv_obj_t *obj_ = nullptr;
  uint32_t updated_ = 0;
  std::string last_;

public:
  explicit BuiltinWidget(std::string t) : type_(std::move(t)) {}
  const char *type() const override { return type_.c_str(); }
  void mount(void *p, const Widget &w) override {
    obj_ =
        label(static_cast<lv_obj_t *>(p), w.x, w.y, w.w, w.h, w.label.c_str());
    last_ = w.label;
  }
  void update(const SensorSnapshot &s, const std::array<float, 3> &b,
              uint32_t ms) override {
    if (!obj_ || ms - updated_ < 250)
      return;
    updated_ = ms;
    char text[192]{};
    if (type_ == "telemetry") {
      char cpu[16], bat[16];
      if (s.cpu < 0)
        snprintf(cpu, sizeof cpu, "--");
      else
        snprintf(cpu, sizeof cpu, "%.0f%%", s.cpu);
      if (s.battery < 0)
        snprintf(bat, sizeof bat, "--");
      else
        snprintf(bat, sizeof bat, "%d%%", s.battery);
      snprintf(text, sizeof text,
               "CPU %s · RAM %lu KB\nWi-Fi %d dBm · batería %s", cpu,
               (unsigned long)(s.heap / 1024), s.rssi, bat);
    } else if (type_ == "pomodoro") {
      const auto &timer = runtime().focus;
      auto left = timer.remaining_seconds();
      const char *state = timer.state() == FocusTimer::State::ready
                              ? "Toca para iniciar"
                          : timer.state() == FocusTimer::State::paused
                              ? "En pausa · toca para seguir"
                          : timer.state() == FocusTimer::State::complete
                              ? "Terminado · toca para elegir"
                              : "En curso · toca para pausar";
      snprintf(text, sizeof text, "%s  %02lu:%02lu\n%s",
               timer.phase() == FocusTimer::Phase::focus ? "Enfoque"
                                                         : "Descanso",
               (unsigned long)(left / 60), (unsigned long)(left % 60), state);
    } else if (type_ == "spectrum")
      snprintf(text, sizeof text,
               "Audio  graves %02d · medios %02d\nAgudos %02d", int(b[0] * 100),
               int(b[1] * 100), int(b[2] * 100));
    else if (type_ == "sensors") {
      char imu[64] = "IMU: sin lectura reciente";
      char light[64] = "Luz/proximidad: sin lectura";
      if (s.imu && ms - s.at < 250)
        snprintf(imu, sizeof imu, "IMU %.2f / %.2f / %.2f g", s.ax, s.ay, s.az);
      if (s.environment && ms - s.environment_at < 250)
        snprintf(light, sizeof light, "Luz %.0f · proximidad %.0f", s.light,
                 s.proximity);
      snprintf(text, sizeof text, "%s\n%s", imu, light);
    } else if (type_ == "weather") {
      s.weather.text(text, sizeof text, ms);
    } else if (type_ == "terminal")
      snprintf(text, sizeof text, "%s", diagnostics.text(2).c_str());
    else
      return;
    if (last_ != text) {
      last_ = text;
      lv_label_set_text(obj_, text);
    }
  }
  void unmount() override {
    if (obj_)
      lv_obj_delete(obj_);
    obj_ = nullptr;
  }
  ~BuiltinWidget() { unmount(); }
};
extern "C" {
extern const lv_image_dsc_t sagwa_body, sagwa_head, sagwa_ear_left,
    sagwa_ear_right, sagwa_tail, sagwa_eye_left, sagwa_eye_right, sagwa_pupil,
    sagwa_mouth_closed, sagwa_mouth_open, sagwa_lid_left, sagwa_lid_right;
}
struct Cat {
  lv_obj_t *root = nullptr, *image = nullptr;
  std::vector<uint16_t> pixels;
  lv_image_dsc_t descriptor{};
  SkinId mode = SkinId::pet;
  uint32_t fur = 0;
  static CatTexture texture(const lv_image_dsc_t &asset) {
    return {asset.data, asset.data_size, int(asset.header.w),
            int(asset.header.h), int(asset.header.stride)};
  }
  void make(lv_obj_t *screen, const Skin &skin) {
    mode = skin.mode;
    fur = skin.fur;
    if (pixels.empty())
      pixels.resize(136 * 136); // One PSRAM allocation; no per-frame heap.
    descriptor.header.magic = LV_IMAGE_HEADER_MAGIC;
    descriptor.header.cf = LV_COLOR_FORMAT_RGB565;
    descriptor.header.w = descriptor.header.h = 136;
    descriptor.header.stride = 136 * 2;
    descriptor.data_size = pixels.size() * sizeof(uint16_t);
    descriptor.data = reinterpret_cast<const uint8_t *>(pixels.data());
    root = lv_obj_create(screen);
    lv_obj_remove_style_all(root);
    lv_obj_set_pos(root, mode == SkinId::assistant ? 12 : 92, 8);
    lv_obj_set_size(root, 136, 136);
    lv_obj_remove_flag(root, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(root, LV_OBJ_FLAG_EVENT_BUBBLE);
    if (mode == SkinId::assistant) {
      lv_obj_set_style_transform_pivot_x(root, 0, 0);
      lv_obj_set_style_transform_pivot_y(root, 0, 0);
      lv_obj_set_style_transform_scale(root, 115, 0);
    }
    image = lv_image_create(root);
    lv_image_set_src(image, &descriptor);
    lv_obj_remove_flag(image, static_cast<lv_obj_flag_t>(
        LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE));
  }
  void draw(const Pose &pose, const WeatherSnapshot &weather, uint32_t ms) {
    const bool small = mode == SkinId::assistant;
    const bool climate = mode == SkinId::weather && weather.fresh(ms);
    CatRaster frame(pixels.data(), 136, 136, int(pose.lean * 120),
                    small ? 0 : 68, small ? 0 : 128, climate ? weather.tint() : fur,
                    mode == SkinId::terminal ? 160 : climate ? 32 : 0);
    frame.layer(texture(sagwa_tail), 91, 17, 12, 80, int(pose.tail * 180));
    frame.layer(texture(sagwa_body), 40, 45, 32, 88, 0,
                int(256 * pose.breath * pose.stretch) / 256.f);
    frame.layer(texture(sagwa_ear_left), 29, 5, 18, 34,
                int(-pose.ear_left * 180));
    frame.layer(texture(sagwa_ear_right), 80, 5, 7, 34,
                int(pose.ear_right * 180));
    frame.layer(texture(sagwa_head), 29, 22);
    for (int eye = 0; eye < 2; ++eye) {
      const int x = eye ? 68 : 42, y = eye ? 39 : 37;
      frame.layer(texture(eye ? sagwa_eye_right : sagwa_eye_left), x, y,
                  9, 7, 0, std::max(16, int(256 * pose.blink)) / 256.f);
      frame.layer(texture(sagwa_pupil), (eye ? 75 : 49) + int(pose.gaze_x * 3),
                  (eye ? 41 : 39) + int(pose.gaze_y * 2), 0, 0, 0, 1,
                  pose.blink < .3f ? 0 : 255);
      frame.layer(texture(eye ? sagwa_lid_right : sagwa_lid_left), x, y,
                  0, 0, 0, 1, pose.blink < .22f ? 255 : 0);
    }
    frame.layer(texture(sagwa_mouth_open), 48, 59, 0, 0, 0, 1,
                unsigned(std::max(0, std::min(255, int(pose.mouth * 255)))));
    // A real display transfer is requested each procedural frame, even if the
    // quantized pose happens to match. Metrics still count SPI completions.
    lv_obj_invalidate(image);
  }
};
static std::atomic<int> page{0};
static Navigation navigation;
static std::string brief = "Estoy aquí contigo.", detail = brief;
static std::atomic<bool> rebuild{true};
static void open_page(int next) {
  page = navigation.open(next);
  rebuild = true;
}
static Decision approval;
static std::string approval_detail, decision_notice;
static bool decision_pending = false;
static std::string plugin_page;
static std::vector<std::string> secondary_pages;
static std::shared_ptr<std::vector<uint8_t>> photo;
static bool clear_photo_on_rebuild = false;
static lv_image_dsc_t photo_descriptor{};
static std::string photo_status;
static DeviceStatus visible_status;
#ifdef SAGWA_UI_HOST
// Native gallery fixtures use this exact renderer; excluded from ESP firmware.
void host_screen(int next, const std::string &skin, const std::string &text,
                 const std::string &full,
                 std::shared_ptr<std::vector<uint8_t>> preview) {
  auto &r = runtime();
  post(EventKind::wake);
  open_page(next);
  r.skins.select(skin);
  brief = text;
  detail = full;
  plugin_page = "notas";
  r.camera_open = next == 8;
  photo = std::move(preview);
  clear_photo_on_rebuild = !photo;
  if (next == 6)
    approval = {"22222222-2222-4222-8222-222222222222", std::string(64, 'a'),
                uint64_t(time(nullptr) + 600) * 1000, false, r.generation};
  else
    approval = {};
  if (skin == "recovery") {
    xEventGroupClearBits(r.flags, wifi_bit | wss_bit);
    post(EventKind::offline);
  } else
    xEventGroupSetBits(r.flags, wifi_bit | wss_bit);
  approval_detail = full;
  decision_notice.clear();
  decision_pending = false;
}
int host_page() { return page.load(); }
bool host_decision_pending() { return decision_pending; }
#endif
static bool choices_fresh() {
  return (xEventGroupGetBits(runtime().flags) & wss_bit) &&
         visible_status.received_at &&
         now_ms() - visible_status.received_at < 45000;
}
static std::string choice_label(const DeviceChoice &choice) {
  const std::string name = choice.id == "mac-mini"    ? "Mac mini"
                           : choice.id == "tuf-infra" ? "TUF-1"
                           : choice.id == "muse"      ? "Muse"
                           : choice.id == "codex"     ? "Codex"
                           : choice.id == "grok"      ? "Grok"
                           : choice.id == "opencode"  ? "OpenCode"
                                                      : choice.id;
  const bool node = choice.id == "mac-mini" || choice.id == "tuf-infra";
  return name + ((choices_fresh() && choice.available) ? " · disponible"
                 : node                                ? " · sin conexión"
                                                       : " · no disponible");
}
static bool active_task(const std::string &state) {
  return state == "queued" || state == "running" || state == "needs_approval" ||
         state == "reconciling";
}
static std::string task_state_label(const std::string &state) {
  if (state == "completed")
    return "Completada";
  if (state == "queued")
    return "En espera";
  if (state == "running")
    return "En curso";
  if (state == "needs_approval")
    return "Necesita autorización";
  if (state == "reconciling")
    return "Recuperando conexión";
  if (state == "canceled")
    return "Cancelada";
  if (state == "failed")
    return "No se pudo completar";
  if (state == "interrupted")
    return "Interrumpida";
  return "Estado sin confirmar";
}
static void discard_photo() {
  runtime().camera_open = false;
  runtime().generation.fetch_add(1);
  clear_photo_on_rebuild = true;
}
static void touch_cb(lv_event_t *e) {
  static lv_point_t begin{}, last_stroke{};
  static uint32_t started = 0;
  auto *in = lv_indev_active();
  if (!in)
    return;
  lv_point_t point;
  lv_indev_get_point(in, &point);
  auto code = lv_event_get_code(e);
  if (code == LV_EVENT_PRESSED) {
    begin = point;
    last_stroke = point;
    started = now_ms();
  }
  bool assistant = runtime().skins.current().mode == SkinId::assistant;
  int cat_x = assistant ? 12 : 92, cat_y = 8, cat_size = assistant ? 61 : 136;
  auto on_cat = [&](const lv_point_t &p) {
    return p.x >= cat_x && p.x <= cat_x + cat_size && p.y >= cat_y &&
           p.y <= cat_y + cat_size;
  };
  if (code == LV_EVENT_PRESSING && page == 0 && runtime().pet_enabled &&
      on_cat(begin) && on_cat(point)) {
    post(EventKind::touch,
         (point.x - cat_x - cat_size / 2.f) / (cat_size / 2.f),
         (point.y - cat_y - cat_size / 2.f) / (cat_size / 2.f));
    if (std::abs(point.x - last_stroke.x) + std::abs(point.y - last_stroke.y) >
        12) {
      post(EventKind::stroke);
      audio_send(new AudioCommand{
          AudioCommand::purr, runtime().generation.load(), {}});
      last_stroke = point;
    }
  }
  if (code != LV_EVENT_RELEASED)
    return;
  int dx = point.x - begin.x, dy = point.y - begin.y;
  if (page && begin.x < 22 && dx > 45) {
    if (page == 8)
      discard_photo();
    page = navigation.back();
    rebuild = true;
    return;
  }
  if (!page) {
    if (begin.x < 22 && dx > 45) {
      open_page(9);
      rebuild = true;
    } else if (begin.x > 298 && dx < -45) {
      open_page(2);
      rebuild = true;
    } else if (begin.y < 20 && dy > 45) {
      open_page(3);
      rebuild = true;
    } else if (begin.y > 150 && std::abs(dx) + std::abs(dy) < 12 &&
               now_ms() - started < 500) {
      open_page(runtime().skins.current().mode == SkinId::focus &&
                        brief == "Estoy aquí contigo."
                    ? 10
                    : runtime().skins.current().mode == SkinId::terminal &&
                              brief == "Estoy aquí contigo."
                          ? 18
                    : 4);
      rebuild = true;
    }
  }
}
static void row_cb(lv_event_t *e) {
  auto idx = int(reinterpret_cast<intptr_t>(lv_event_get_user_data(e)));
  auto &r = runtime();
  if (page == 1) {
    auto &items = r.skins.catalog();
    if (size_t(idx) < items.size()) {

      post(EventKind::skin_catalog, 0, 0, idx);
      open_page(0);
      post(EventKind::wake);
      rebuild = true;
    }
  } else if (page == 2) {
    if (idx >= 6 && size_t(idx - 6) < secondary_pages.size()) {
      plugin_page = secondary_pages[idx - 6];
      open_page(7);
      rebuild = true;
      return;
    }
    if (idx == 1) {
      if (capture_requested()) {
        clear_photo_on_rebuild = true;
        photo_status.clear();
        open_page(8);
      } else {
        brief = "Termina la voz antes de abrir la cámara.";
        open_page(0);
      }
    } else if (idx == 2)
      open_page(14);
    else if (idx == 5)
      open_page(17);
    else if (idx == 0 || idx == 3 || idx == 4) {
      if (xSemaphoreTake(r.status_mutex, pdMS_TO_TICKS(5)) == pdTRUE) {
        r.selected_capability = idx == 3   ? "infra.diagnose"
                                : idx == 4 ? "code.change"
                                           : "conversation";
        xSemaphoreGive(r.status_mutex);
        brief = idx == 3   ? "Mantén PWR para pedir un diagnóstico."
                : idx == 4 ? "Mantén PWR para pedir cambios de código."
                           : "Estoy aquí contigo.";
        open_page(0);
        save_preferences();
      }
    }
    rebuild = true;
  } else if (page == 3) {
    const int destinations[] = {15, 16, 1, 17, 12, 13, 5};
    if (idx >= 0 && idx < 7)
      open_page(destinations[idx]);
    rebuild = true;
  } else if (page == 9) {
    const int destinations[] = {0, 1, 2, 11, 12, 13, 10};
    if (idx >= 0 && idx < 7)
      open_page(destinations[idx]);
    if (idx == 0 &&
        xSemaphoreTake(r.status_mutex, pdMS_TO_TICKS(5)) == pdTRUE) {
      r.selected_capability = "conversation";
      xSemaphoreGive(r.status_mutex);
      save_preferences();
    }
    rebuild = true;
  } else if (page == 10) {
    // LVGL callbacks run in the port task. UI_Task alone owns the clock.
    if (idx >= 0 && idx < 3)
      post(EventKind::focus_control, 0, 0, idx);
  } else if (page == 12 && idx >= 0 &&
             size_t(idx) < visible_status.nodes.size()) {
    if (xSemaphoreTake(r.status_mutex, pdMS_TO_TICKS(5)) == pdTRUE) {
      const auto &chosen = visible_status.nodes[idx];
      bool available = false;
      for (const auto &node : r.device_status.nodes)
        available |= node.id == chosen.id && node.available;
      if (available && choices_fresh() &&
          (chosen.id == "mac-mini" || chosen.id == "tuf-infra")) {
        r.selected_target = chosen.id;
        brief = "Destino seleccionado. Estoy lista para ayudarte.";
        open_page(0);
      }
      xSemaphoreGive(r.status_mutex);
      save_preferences();
    }
    rebuild = true;
  } else if (page == 15) {
    if (idx == 0) {
      r.voice_enabled = !r.voice_enabled;
      if (!r.voice_enabled)
        stop_voice();
      else
        resume_voice();
      save_preferences();
    }
    rebuild = true;
  } else if (page == 13 && idx == 0) {
    open_page(active_task(visible_status.task_state) && choices_fresh() ? 5
                                                                        : 0);
    rebuild = true;
  } else if (page == 16) {
    if (idx == 0)
      r.pet_enabled = !r.pet_enabled;
    else if (idx == 1)
      r.pet_sounds = !r.pet_sounds;
    else if (idx == 2)
      r.pet_sensors = !r.pet_sensors;
    else if (idx == 3)
      open_page(1);
    save_preferences();
    rebuild = true;
  } else if (page == 17 && idx >= 0 && idx < 3) {
    r.preference = Preference(idx);
    save_preferences();
    brief = idx == 2 ? "Solo funciones locales."
                     : "Preferencia de conexión seleccionada.";
    open_page(0);
    rebuild = true;
  } else if (page == 5) {
    if (idx == 0) {
      r.generation.fetch_add(1);
      audio_send(new AudioCommand{AudioCommand::stop, r.generation, {}});
      post(EventKind::cancel);
      brief = "Conversación cancelada.";
    }
    page = idx == 0 ? navigation.open(0) : navigation.back();
    rebuild = true;
  } else if (page == 8) {
    if (idx == 0 && photo && !r.camera_capturing &&
        (xEventGroupGetBits(r.flags) & wss_bit)) {
      auto *job = new Routed;
      job->request.image = true;
      job->request.private_context = true;
      job->request.generation = r.generation;
      job->request.preference = r.preference;
      if (!apply_request_context(job->request)) {
        delete job;
        photo_status = "Destino ocupado. Conservé la foto.";
        rebuild = true;
        return;
      }
      // A photograph describes the scene, regardless of the text tool mode.
      job->request.capability = "conversation";
      job->request.tools = false;
      job->audio = *photo;
      if (xQueueSend(r.requests, &job, 0) != pdTRUE) {
        delete job;
        photo_status = "Cola ocupada. Conservé la foto.";
        rebuild = true;
        return;
      }
      r.camera_open = false;
      brief = "Foto enviada a Muse.";
      clear_photo_on_rebuild = true;
    } else if (idx == 0) {
      photo_status = "Reconecta el equipo antes de enviar.";
      rebuild = true;
      return;
    } else {
      discard_photo();
      brief = "Foto descartada.";
    }
    open_page(0);
    rebuild = true;
  } else if (page == 6) {
    if (decision_pending)
      return;
    if (shell::time_synchronized() &&
        approval.expires_at > uint64_t(time(nullptr)) * 1000 &&
        approval.generation == r.generation) {
      auto *d = new Decision(approval);
      d->approve = idx == 0;
      if (decide(d)) {
        decision_pending = true;
        decision_notice = "Enviando tu decisión.";
      } else
        decision_notice = "Cola ocupada. Vuelve a intentar.";
      rebuild = true;
      return;
    } else {
      brief = "La autorización ha vencido.";
    }
    approval = {};
    approval_detail.clear();
    decision_pending = false;
    open_page(0);
    rebuild = true;
  }
}
static void rows(lv_obj_t *screen, const std::vector<std::string> &names,
                 int top = 30) {
  auto *list = lv_obj_create(screen);
  lv_obj_remove_style_all(list);
  lv_obj_set_pos(list, 12, top);
  lv_obj_set_size(list, 296, 240 - top);
  lv_obj_set_scroll_dir(list, LV_DIR_VER);
  lv_obj_set_scrollbar_mode(list, LV_SCROLLBAR_MODE_OFF);
  lv_obj_add_flag(list, LV_OBJ_FLAG_EVENT_BUBBLE);
  for (size_t i = 0; i < names.size(); ++i) {
    auto *row = lv_obj_create(list);
    lv_obj_remove_style_all(row);
    lv_obj_set_size(row, 296, 44);
    lv_obj_set_pos(row, 0, i * 48);
    lv_obj_add_flag(row, static_cast<lv_obj_flag_t>(LV_OBJ_FLAG_CLICKABLE |
                                                    LV_OBJ_FLAG_EVENT_BUBBLE));
    lv_obj_add_event_cb(row, row_cb, LV_EVENT_CLICKED,
                        reinterpret_cast<void *>(i));
    label(row, 4, 12, 288, 30, names[i].c_str());
  }
}
void ui_task(void *) {
  auto &r = runtime();
  for (auto &t : {"text", "telemetry", "pomodoro", "spectrum", "weather",
                  "status", "terminal"})
    if (!factories.count(t))
      register_plugin(t, [name = std::string(t)] {
        return std::make_unique<BuiltinWidget>(name);
      });
  for (auto &[name, f] : factories)
    r.skins.register_type(name);
  bsp_display_cfg_t cfg{};
  cfg.lvgl_port_cfg = ESP_LVGL_PORT_INIT_CONFIG();
  cfg.lvgl_port_cfg.task_affinity = 1;
  cfg.lvgl_port_cfg.task_max_sleep_ms = 16;
  cfg.buffer_size = 320 * 240;
  cfg.double_buffer = true;
  cfg.flags.buff_dma = true;
  cfg.flags.buff_spiram = true;
  auto *display = bsp_display_start_with_config(&cfg);
  if (!display) {
    vTaskDelete(nullptr);
    return;
  }
  if (bsp_display_lock(1000)) {
    esp_lcd_panel_io_callbacks_t callbacks{};
    callbacks.on_color_trans_done = lcd_done;
    r.lcd_dma_metrics =
        esp_lcd_panel_io_register_event_callbacks(
            bsp_display_get_panel_io(), &callbacks, display) == ESP_OK;
    if (r.lcd_dma_metrics)
      lv_display_add_event_cb(display, lcd_flush_start, LV_EVENT_FLUSH_START,
                              nullptr);
    bsp_display_unlock();
  }
  bsp_display_backlight_on();
  r.ui_ready = true;
  diagnostics.push(DiagnosticKind::started, now_ms());
  AnimationFSM fsm;
  SensorSnapshot snapshot;
  Cat cat;
  lv_obj_t *output = nullptr, *status = nullptr, *mic_indicator = nullptr;
  lv_obj_t *focus_clock = nullptr, *history_output = nullptr;
  std::vector<std::unique_ptr<SagwaPluginInterface>> plugins;
  TickType_t next = xTaskGetTickCount();
  uint32_t status_revision = UINT32_MAX;
  bool previously_fresh = false;
  bool channel_known = false, previous_channel = false;
  bool previous_recording = false, previous_playing = false;
  uint32_t focus_saved_at = now_ms();
  for (;;) {
    auto begin = esp_timer_get_time();
    auto ms = now_ms();
    xQueuePeek(r.sensors, &snapshot, 0);
    std::array<float, 3> bands{};
    if (xSemaphoreTake(r.bands_mutex, 0) == pdTRUE) {
      bands = r.bands;
      xSemaphoreGive(r.bands_mutex);
    }
    if (bsp_display_lock(5)) {
      ms = now_ms();
      bool history_changed = false;
      auto record = [&](DiagnosticKind kind) {
        history_changed |= diagnostics.push(kind, ms);
      };
      const bool channel = xEventGroupGetBits(r.flags) & wss_bit;
      if (!channel_known || channel != previous_channel) {
        record(channel ? DiagnosticKind::gateway_connected
                       : DiagnosticKind::gateway_disconnected);
        channel_known = true;
        previous_channel = channel;
      }
      const bool recording = r.recording.load(), playing = r.playing.load();
      if (recording != previous_recording) {
        record(recording ? DiagnosticKind::listening : DiagnosticKind::mic_stopped);
        previous_recording = recording;
      }
      if (playing != previous_playing) {
        record(playing ? DiagnosticKind::speaking : DiagnosticKind::voice_stopped);
        previous_playing = playing;
      }
      const bool focus_completed = r.focus.tick(ms);
      if (focus_completed || (r.focus.state() == FocusTimer::State::running &&
                              ms - focus_saved_at >= 60000)) {
        save_focus();
        focus_saved_at = ms;
      }
      if (focus_completed && page == 10)
        rebuild = true;
      // Callbacks also read this snapshot under the LVGL lock. Keep assignment
      // under that lock and preserve the existing LVGL -> status lock order.
      if (status_revision != r.status_revision &&
          xSemaphoreTake(r.status_mutex, pdMS_TO_TICKS(5)) == pdTRUE) {
        visible_status = r.device_status;
        status_revision = r.status_revision;
        xSemaphoreGive(r.status_mutex);
        if (page == 11 || page == 12 || page == 13)
          rebuild = true;
      }
      const bool fresh = choices_fresh();
      snapshot.weather = visible_status.weather;
      if (fresh != previously_fresh) {
        previously_fresh = fresh;
        if (page == 11 || page == 12)
          rebuild = true;
      }
      r.sound_enabled =
          r.pet_enabled && r.pet_sounds && r.skins.current().sounds;
      r.sentinel_enabled = r.pet_enabled && r.pet_sensors &&
                           r.skins.current().mode == SkinId::sentinel;
      if (r.remote_preferences_dirty.exchange(false)) {
        save_preferences();
        if (page == 15 || page == 16)
          rebuild = true;
      }
      CameraResult *camera = nullptr;
      while (xQueueReceive(r.camera_results, &camera, 0) == pdTRUE) {
        std::unique_ptr<CameraResult> own(camera);
        if (page != 8 || camera->generation != r.generation || !r.camera_open)
          continue;
        if (camera->pixels) {
          photo = camera->pixels;
          record(DiagnosticKind::camera_ready);
        } else {
          record(DiagnosticKind::camera_failed);
          r.camera_open = false;
          brief = camera->error;
          open_page(0);
        }
        rebuild = true;
      }
      Descriptor *descriptor = nullptr;
      while (xQueueReceive(r.reloads, &descriptor, 0) == pdTRUE) {
        std::unique_ptr<Descriptor> own(descriptor);
        std::string error;
        if (r.skins.apply(descriptor->json, descriptor->id, error)) {
          record(DiagnosticKind::skin_loaded);
          if (descriptor->id == r.pending_skin_id) {
            r.skins.select(descriptor->id);
            r.pending_skin_id.clear();
          }
          r.sound_enabled =
              r.pet_enabled && r.pet_sounds && r.skins.current().sounds;
          r.sentinel_enabled = r.pet_enabled && r.pet_sensors &&
                               r.skins.current().mode == SkinId::sentinel;
          rebuild = true;
        } else
          record(DiagnosticKind::skin_rejected);
      }
      Event e;
      std::array<Event, 24> plugin_events{};
      size_t event_count = 0;
      while (xQueueReceive(r.events, &e, 0) == pdTRUE) {
        if (e.kind != EventKind::focus_control && e.generation != r.generation)
          continue;
        switch (e.kind) {
        case EventKind::wake: record(DiagnosticKind::wake); break;
        case EventKind::work: record(DiagnosticKind::working); break;
        case EventKind::cancel: record(DiagnosticKind::cancelled); break;
        case EventKind::shake: record(DiagnosticKind::shake); break;
        default: break;
        }
        if (!page &&
            (e.kind == EventKind::touch || e.kind == EventKind::stroke))
          r.touch_pending_ms = e.at;
        if (!page && (e.kind == EventKind::tilt || e.kind == EventKind::shake))
          r.sensor_pending_ms =
              snapshot.imu && ms - snapshot.at < 250 ? snapshot.at : e.at;
        if (event_count < plugin_events.size())
          plugin_events[event_count++] = e;
        if (e.kind == EventKind::focus_control) {
          // save_focus() may advance the anchor after this frame's `ms`.
          // Read the monotonic clock again rather than passing an older stamp.
          const auto focus_now = now_ms();
          if (e.value == 0) {
            if (r.focus.state() == FocusTimer::State::running)
              r.focus.pause(focus_now);
            else {
              if (r.focus.state() == FocusTimer::State::complete)
                r.focus.reset(r.focus.phase());
              r.focus.start(focus_now);
            }
          } else if (e.value == 1) {
            r.focus.reset(r.focus.phase() == FocusTimer::Phase::focus
                              ? FocusTimer::Phase::rest
                              : FocusTimer::Phase::focus);
            r.focus.start(focus_now);
          } else if (e.value == 2)
            r.focus.reset(r.focus.phase());
          else
            continue;
          save_focus();
          focus_saved_at = ms;
          rebuild = true;
        } else if (e.kind == EventKind::cancel_request) {
          open_page(5);
          rebuild = true;
        } else if (e.kind == EventKind::skin_catalog) {
          auto index = size_t(e.value);
          if (index < r.skins.catalog().size()) {
            auto id = r.skins.catalog()[index].id;
            r.skins.select(id);
            r.pending_skin_id.clear();
            r.sound_enabled =
                r.pet_enabled && r.pet_sounds && r.skins.current().sounds;
            r.sentinel_enabled = r.pet_enabled && r.pet_sensors &&
                                 r.skins.current().mode == SkinId::sentinel;
            rebuild = true;
            save_preferences();
          }
        } else if (e.kind == EventKind::skin) {
          auto defaults = builtin_skins();
          int id = int(e.value);
          if (id >= 0 && id < 10) {
            r.skins.select(defaults[id].id);
            r.pending_skin_id.clear();
            r.sound_enabled =
                r.pet_enabled && r.pet_sounds && r.skins.current().sounds;
            r.sentinel_enabled = r.pet_enabled && r.pet_sensors &&
                                 r.skins.current().mode == SkinId::sentinel;
            rebuild = true;
            fsm.event({EventKind::wake, ms});
            save_preferences();
          }
        } else
          fsm.event(e);
      }
      Reply *reply = nullptr;
      while (xQueueReceive(r.replies, &reply, 0) == pdTRUE) {
        std::unique_ptr<Reply> own(reply);
        if (reply->generation != r.generation)
          continue;
        if (!reply->decision_id.empty()) {
          if (decision_pending && reply->decision_id == approval.approval_id) {
            record(reply->decision_ok ? DiagnosticKind::decision_received
                                      : DiagnosticKind::decision_failed);
            decision_pending = false;
            if (reply->decision_ok) {
              approval = {};
              approval_detail.clear();
              brief = "Decisión recibida. Revisa el progreso de la tarea.";
              if (page == 6)
                open_page(0);
            } else
              decision_notice = "No pude confirmar. Revisa la tarea.";
            rebuild = true;
          }
          continue;
        }
        if (reply->clear_approval) {
          approval = {};
          approval_detail.clear();
          decision_pending = false;
          if (page == 6)
            open_page(0);
        }
        brief = reply->error.empty() ? reply->brief : reply->error;
        record(reply->error.empty() ? DiagnosticKind::completed
                                    : DiagnosticKind::query_failed);
        detail = reply->detail.empty() ? brief : reply->detail;
        if (!reply->approval_id.empty()) {
          record(DiagnosticKind::approval_required);
          approval = {reply->approval_id, reply->action_hash, reply->expires_at,
                      false, reply->generation};
          approval_detail = detail;
          decision_pending = false;
          decision_notice.clear();
          open_page(6);
        }
        fsm.event(
            {reply->error.empty() ? EventKind::done : EventKind::offline, ms});
        rebuild = true;
      }
      if (!approval.approval_id.empty() &&
          (!shell::time_synchronized() || approval.generation != r.generation ||
           approval.expires_at <= uint64_t(time(nullptr)) * 1000)) {
        approval = {};
        approval_detail.clear();
        decision_pending = false;
        if (page == 6) {
          brief = "No puedo confirmar la autorización ahora.";
          open_page(0);
        }
        rebuild = true;
      }
      if (rebuild) {
        for (auto &plugin : plugins)
          plugin->unmount();
        plugins.clear();
        auto *screen = lv_screen_active();
        lv_obj_clean(screen);
        // Drop pixel storage only after LVGL no longer refers to the image.
        if (clear_photo_on_rebuild) {
          photo.reset();
          clear_photo_on_rebuild = false;
        }
        lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
        lv_obj_set_style_text_color(screen, lv_color_white(), 0);
        lv_obj_remove_event_cb(screen, touch_cb);
        lv_obj_add_event_cb(screen, touch_cb, LV_EVENT_ALL, nullptr);
        lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
        output = nullptr;
        status = nullptr;
        mic_indicator = nullptr;
        focus_clock = nullptr;
        history_output = nullptr;
        rebuild = false;
        if (!page) {
          cat.make(screen, r.skins.current());

          Widget text{"output", "text", brief, 16, 155, 288, 78};
          for (auto &w : r.skins.current().widgets)
            if (w.type == "text" && w.page == "home")
              text = w;
          auto *viewport = lv_obj_create(screen);
          lv_obj_remove_style_all(viewport);
          lv_obj_set_pos(viewport, text.x, text.y);
          lv_obj_set_size(viewport, text.w, text.h);
          lv_obj_set_scroll_dir(viewport, LV_DIR_VER);
          lv_obj_set_scrollbar_mode(viewport, LV_SCROLLBAR_MODE_OFF);
          lv_obj_add_flag(viewport, LV_OBJ_FLAG_EVENT_BUBBLE);
          output =
              label(viewport, 0, 0, text.w, LV_SIZE_CONTENT, brief.c_str());
          bool has_panel =
              std::any_of(r.skins.current().widgets.begin(),
                          r.skins.current().widgets.end(), [](const Widget &w) {
                            return w.page == "home" && w.type != "text" &&
                                   w.type != "status";
                          });
          if (has_panel && brief == "Estoy aquí contigo.")
            lv_obj_add_flag(viewport, LV_OBJ_FLAG_HIDDEN);
          lv_obj_add_flag(output,
                          static_cast<lv_obj_flag_t>(LV_OBJ_FLAG_CLICKABLE |
                                                     LV_OBJ_FLAG_SCROLLABLE));
          lv_obj_set_scroll_dir(output, LV_DIR_VER);
          lv_obj_add_flag(output, LV_OBJ_FLAG_EVENT_BUBBLE);
          for (auto &w : r.skins.current().widgets) {
            if (w.page != "home" || w.type == "text" || w.type == "status" ||
                (has_panel && brief != "Estoy aquí contigo."))
              continue;
            auto it = factories.find(w.type);
            if (it != factories.end()) {
              auto p = it->second();
              p->mount(screen, w);
              plugins.push_back(std::move(p));
            }
          }
          bsp_display_brightness_set(r.skins.current().brightness);
        } else if (page == 1) {
          label(screen, 16, 4, 260, 25, "Modos de Sagwa");
          std::vector<std::string> names;
          for (auto &s : r.skins.catalog())
            names.push_back(s.title);
          rows(screen, names);
        } else if (page == 2) {
          label(screen, 16, 4, 260, 25, "Herramientas");
          secondary_pages.clear();
          std::vector<std::string> names = {"Conversación", "Cámara",
                                            "Sensores",     "Diagnóstico",
                                            "Código",       "Enrutamiento"};
          for (auto &w : r.skins.current().widgets)
            if (w.page != "home" &&
                std::find(secondary_pages.begin(), secondary_pages.end(),
                          w.page) == secondary_pages.end()) {
              secondary_pages.push_back(w.page);
              names.push_back("Abrir " + w.page);
            }
          rows(screen, names);
        } else if (page == 3) {
          label(screen, 16, 4, 260, 25, "Preferencias");
          rows(screen, {"Voz", "Mascota", "Apariencia", "Enrutamiento",
                        "Destinos", "Tareas", "Cancelar conversación"});
        } else if (page == 9) {
          label(screen, 16, 4, 260, 25, "Sagwa");
          rows(screen, {"Conversación", "Modos", "Herramientas", "Agentes",
                        "Destinos", "Tareas", "Enfoque"});
        } else if (page == 10) {
          label(screen, 16, 4, 260, 25,
                r.focus.phase() == FocusTimer::Phase::focus ? "Enfoque"
                                                            : "Descanso");
          focus_clock = label(screen, 16, 35, 280, 44, "");
          const auto state = r.focus.state();
          rows(screen,
               {state == FocusTimer::State::running    ? "Pausar"
                : state == FocusTimer::State::paused   ? "Continuar"
                : state == FocusTimer::State::complete ? "Volver a empezar"
                                                       : "Iniciar",
                r.focus.phase() == FocusTimer::Phase::focus
                    ? "Descansar cinco minutos"
                    : "Enfocar 25 minutos",
                "Reiniciar temporizador"},
               86);
        } else if (page == 11 || page == 12) {
          label(screen, 16, 4, 260, 25,
                page == 11 ? "Agentes · Muse principal" : "Destinos");
          std::vector<std::string> names;
          const auto &choices =
              page == 11 ? visible_status.agents : visible_status.nodes;
          for (const auto &choice : choices)
            names.push_back(choice_label(choice));
          if (names.empty())
            names.push_back("Sin disponibilidad confirmada");
          rows(screen, names);
        } else if (page == 13) {
          label(screen, 16, 4, 260, 25, "Tarea reciente");
          auto *area = lv_obj_create(screen);
          lv_obj_remove_style_all(area);
          lv_obj_set_pos(area, 16, 35);
          lv_obj_set_size(area, 288, 140);
          lv_obj_set_scroll_dir(area, LV_DIR_VER);
          auto text = visible_status.task_state.empty()
                          ? "No hay tareas confirmadas."
                          : task_state_label(visible_status.task_state) + "\n" +
                                visible_status.task_summary;
          label(area, 0, 0, 288, LV_SIZE_CONTENT, text.c_str());
          auto *button = lv_obj_create(screen);
          lv_obj_remove_style_all(button);
          lv_obj_set_pos(button, 16, 185);
          lv_obj_set_size(button, 288, 44);
          lv_obj_add_event_cb(button, row_cb, LV_EVENT_CLICKED, nullptr);
          label(button, 4, 12, 280, 28,
                active_task(visible_status.task_state) && choices_fresh()
                    ? "Cancelar conversación"
                    : "Volver a conversación");
        } else if (page == 14) {
          label(screen, 16, 4, 260, 25, "Sensores · lectura local");
          Widget widget{"sensors", "sensors", "", 16, 42, 288, 74};
          auto p = std::make_unique<BuiltinWidget>("sensors");
          p->mount(screen, widget);
          plugins.push_back(std::move(p));
          widget = {"metrics", "telemetry", "", 16, 126, 288, 100};
          p = std::make_unique<BuiltinWidget>("telemetry");
          p->mount(screen, widget);
          plugins.push_back(std::move(p));
        } else if (page == 15) {
          label(screen, 16, 4, 260, 25, "Voz");
          rows(screen,
               {r.voice_enabled ? "Silenciar respuestas" : "Activar respuestas",
                "Español · voz cálida", "Respaldo automático de voz",
                "PWR: mantén, habla y suelta"});
        } else if (page == 16) {
          label(screen, 16, 4, 260, 25, "Mascota");
          rows(screen,
               {r.pet_enabled ? "Desactivar reacciones" : "Activar reacciones",
                r.pet_sounds ? "Silenciar sonidos" : "Activar sonidos",
                r.pet_sensors ? "Desactivar sensores" : "Activar sensores",
                "Cambiar apariencia"});
        } else if (page == 17) {
          label(screen, 16, 4, 260, 25, "Enrutamiento");
          rows(screen, {"Equipos locales primero", "Nube primero",
                        "Solo funciones locales"});
        } else if (page == 18) {
          label(screen, 16, 4, 260, 25, "Historial local");
          auto *area = lv_obj_create(screen);
          lv_obj_remove_style_all(area);
          lv_obj_set_pos(area, 16, 35);
          lv_obj_set_size(area, 288, 200);
          lv_obj_set_scroll_dir(area, LV_DIR_VER);
          const auto text = diagnostics.text();
          history_output = label(area, 0, 0, 288, LV_SIZE_CONTENT, text.c_str());
          lv_obj_add_flag(history_output, LV_OBJ_FLAG_EVENT_BUBBLE);
        } else if (page == 5) {
          label(screen, 16, 4, 260, 25, "¿Cancelar conversación?");
          rows(screen, {"Sí, cancelar", "Volver"});
        } else if (page == 6) {
          label(screen, 16, 4, 260, 25, "Autorizar acción");
          auto *area = lv_obj_create(screen);
          lv_obj_remove_style_all(area);
          lv_obj_set_pos(area, 16, 34);
          lv_obj_set_size(area, 288, 82);
          lv_obj_set_scroll_dir(area, LV_DIR_VER);
          label(area, 0, 0, 288, LV_SIZE_CONTENT, approval_detail.c_str());
          label(screen, 16, 117, 288, 24,
                decision_notice.empty() ? "Desliza para revisar la acción."
                                        : decision_notice.c_str());
          if (decision_pending) {
            label(screen, 16, 148, 288, 60,
                  "Espera la confirmación de tu decisión.");
          } else {
            auto *allow = lv_obj_create(screen);
            lv_obj_remove_style_all(allow);
            lv_obj_set_pos(allow, 16, 144);
            lv_obj_set_size(allow, 288, 44);
            lv_obj_add_event_cb(allow, row_cb, LV_EVENT_LONG_PRESSED, nullptr);
            label(allow, 4, 12, 280, 32, "Mantén para autorizar");
            auto *deny = lv_obj_create(screen);
            lv_obj_remove_style_all(deny);
            lv_obj_set_pos(deny, 16, 192);
            lv_obj_set_size(deny, 288, 44);
            lv_obj_add_event_cb(deny, row_cb, LV_EVENT_CLICKED,
                                reinterpret_cast<void *>(1));
            label(deny, 4, 12, 280, 32, "Denegar");
          }
        } else if (page == 8) {
          label(screen, 16, 4, 260, 25, "Cámara · vista previa local");
          if (photo) {
            photo_descriptor = {};
            photo_descriptor.header.magic = LV_IMAGE_HEADER_MAGIC;
            photo_descriptor.header.cf = LV_COLOR_FORMAT_RGB565_SWAPPED;
            photo_descriptor.header.w = 320;
            photo_descriptor.header.h = 240;
            photo_descriptor.header.stride = 640;
            photo_descriptor.data_size = photo->size();
            photo_descriptor.data = photo->data();
            auto *preview = lv_image_create(screen);
            lv_image_set_src(preview, &photo_descriptor);
            lv_image_set_pivot(preview, 0, 0);
            lv_image_set_scale(preview, 144);
            lv_obj_set_pos(preview, 70, 30);
            label(screen, 16, 166, 288, 24, photo_status.c_str());
            for (int i = 0; i < 2; ++i) {
              auto *button = lv_obj_create(screen);
              lv_obj_remove_style_all(button);
              lv_obj_set_pos(button, 16 + i * 152, 190);
              lv_obj_set_size(button, 136, 44);
              lv_obj_add_flag(button, LV_OBJ_FLAG_CLICKABLE);
              lv_obj_add_event_cb(button, row_cb, LV_EVENT_CLICKED,
                                  reinterpret_cast<void *>(i));
              label(button, 4, 12, 128, 28, i ? "Descartar" : "Enviar");
            }
          } else
            label(screen, 16, 90, 280, 48,
                  "Capturando foto.\nSolo se enviará si confirmas.");
        } else if (page == 7) {
          label(screen, 16, 4, 260, 25, plugin_page.c_str());
          for (auto &w : r.skins.current().widgets)
            if (w.page == plugin_page) {
              auto factory = factories.find(w.type);
              if (factory != factories.end()) {
                auto widget = factory->second();
                widget->mount(screen, w);
                plugins.push_back(std::move(widget));
              }
            }
        } else {
          label(screen, 16, 4, 260, 24, "Respuesta completa");
          auto *area = lv_obj_create(screen);
          lv_obj_remove_style_all(area);
          lv_obj_set_pos(area, 16, 35);
          lv_obj_set_size(area, 288, 200);
          lv_obj_set_scroll_dir(area, LV_DIR_VER);
          auto *l = label(area, 0, 0, 288, LV_SIZE_CONTENT, detail.c_str());
          lv_obj_add_flag(l, LV_OBJ_FLAG_EVENT_BUBBLE);
        }
      }
      if (history_output && history_changed) {
        const auto text = diagnostics.text();
        lv_label_set_text(history_output, text.c_str());
      }
      if (!status) {
        status = lv_image_create(lv_screen_active());
        lv_obj_set_pos(status, 283, 9);
        lv_image_set_src(status, &badge_cat);
        mic_indicator = label(lv_screen_active(), 280, 40, 36, 24, "");
      }
      if (r.recording)
        fsm.event({EventKind::listen, ms});
      else if (r.playing)
        fsm.event({EventKind::speak, ms});
      if (!page) {
        if (r.skins.current().mode == SkinId::night &&
            fsm.state() == Emotion::idle)
          fsm.event({EventKind::sleep, ms});
        if (r.recording)
          fsm.event({EventKind::listen, ms});
        else if (r.playing)
          fsm.event({EventKind::speak, ms});
        auto pose = fsm.step(ms, r.pet_sensors ? snapshot : SensorSnapshot{},
                             bands, r.skins.current().breath_hz);
        if (!r.pet_enabled)
          pose = {};
        if (r.skins.current().mode == SkinId::sentinel) {
          pose.ear_left += .14f;
          pose.ear_right += .14f;
        }
        if (r.skins.current().mode == SkinId::multimedia) {
          pose.tail += bands[0] * .3f;
          pose.ear_left += bands[1] * .2f;
          pose.ear_right += bands[2] * .2f;
        }
        if (r.pet_enabled && r.skins.current().mode == SkinId::weather &&
            snapshot.weather.fresh(ms) && fsm.state() == Emotion::idle) {
          const float target = snapshot.weather.condition == WeatherCondition::clear ? .06f
                             : snapshot.weather.condition == WeatherCondition::rain ? -.06f : 0;
          // Tiny procedural motion; no spontaneous sound or host command.
          pose.ear_left += target;
          pose.ear_right += target;
        }
        cat.draw(pose, snapshot.weather, ms);
      }
      if (status) {
        const lv_image_dsc_t *icon =
            (r.camera_open || r.camera_capturing) ? &badge_camera
            : r.recording                         ? &badge_listening
            : r.playing                           ? &badge_speaking
            : r.updating                          ? &badge_executing
            : !approval.approval_id.empty()       ? &badge_approval
            : fsm.state() == Emotion::thinking    ? &badge_thinking
            : fsm.state() == Emotion::working     ? &badge_executing
            : fsm.state() == Emotion::error       ? &badge_warning
            : fsm.state() == Emotion::sleeping    ? &badge_sleeping
            : r.mic_monitoring                    ? &badge_listening
            : (xEventGroupGetBits(r.flags) & (wss_bit | wifi_bit))
                ? &badge_cat
                : &badge_warning;
        // LVGL 9.4 invalidates even an unchanged image source. Leave the fixed
        // status area intact between real state transitions; the avatar still
        // requests its own completed SPI frame on every animation update.
        if (lv_image_get_src(status) != icon)
          lv_image_set_src(status, icon);
        if (mic_indicator) {
          const char *text = r.mic_monitoring && icon != &badge_listening ? "MIC" : "";
          if (strcmp(lv_label_get_text(mic_indicator), text))
            lv_label_set_text(mic_indicator, text);
        }
      }
      if (focus_clock) {
        char text[80];
        const auto left = r.focus.remaining_seconds();
        const char *state =
            r.focus.state() == FocusTimer::State::running  ? "En curso"
            : r.focus.state() == FocusTimer::State::paused ? "En pausa"
            : r.focus.state() == FocusTimer::State::complete
                ? "Terminado"
                : "Listo para empezar";
        snprintf(text, sizeof(text), "%02lu:%02lu · %s",
                 (unsigned long)(left / 60), (unsigned long)(left % 60), state);
        if (std::string(lv_label_get_text(focus_clock)) != text)
          lv_label_set_text(focus_clock, text);
      }
      for (auto &plugin : plugins) {
        for (size_t i = 0; i < event_count; ++i)
          plugin->on_event(plugin_events[i]);
        plugin->update(snapshot, bands, ms);
      }
      bsp_display_unlock();
    } else
      r.ui_lock_misses.fetch_add(1);
    r.ui_us = uint32_t(esp_timer_get_time() - begin);
    // M measured 26.4–31.3 completed SPI frames/s at a 32 ms cadence.
    // Leave headroom above 30 FPS; DMA completion remains the measured rate.
    // This is a candidate cadence, not a hardware performance guarantee.
    vTaskDelayUntil(&next, pdMS_TO_TICKS(28));
  }
}
} // namespace sagwa
