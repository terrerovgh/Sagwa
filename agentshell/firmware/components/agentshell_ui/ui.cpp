#include "ui.hpp"
#include "M5Unified.h"
#include "avatar.hpp"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "inter.hpp"
#include "nvs.h"
#include <algorithm>
#include <cstring>
namespace shell {
static Frame previous, frame;
static bool first = true;
static Page previous_page = Page::home;
static uint32_t last_draw, transition_at, draw_finished;
uint32_t ui_last_draw_ms() { return draw_finished; }
static unsigned text_opacity = 255, previous_opacity = 255;
static unsigned previous_icon = 999;
static uint16_t *portrait, *photo_pixels;
static std::string signature;
extern const uint8_t status_start[] asm("_binary_status_bin_start");
static void draw_text(const TextRun &r) {
  int x = r.x;
  for (size_t at = 0; at < r.text.size();) {
    const auto &g = glyph(next_codepoint(r.text, at), r.size);
    for (unsigned y = 0; y < g.h; y++) {
      lgfx::rgb565_t line[40];
      unsigned w = std::min<unsigned>(40, g.w);
      for (unsigned i = 0; i < w; i++) {
        unsigned c = inter_pixels[g.offset + y * g.w + i] * text_opacity / 255;
        line[i].raw = ((c >> 3) << 11) | ((c >> 2) << 5) | (c >> 3);
      }
      int px = x + g.x, py = r.y + g.y + y;
      if (py < 240 && px < 320 && px >= 0)
        M5.Display.pushImage(px, py, std::min<unsigned>(w, 320 - px), 1, line);
    }
    x += g.advance;
    if (x >= 320)
      break;
  }
}
void ui_next_avatar() {}
void ui_begin() {
  M5.Display.setSwapBytes(
      true); // SAV1, status and camera preview are native RGB565 words.
  portrait = static_cast<uint16_t *>(
      heap_caps_calloc(136 * 136, 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  photo_pixels = static_cast<uint16_t *>(
      heap_caps_calloc(160 * 120, 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!portrait || !photo_pixels)
    abort();
  M5.Display.fillScreen(0);
  first = true;
}
void ui_load_preferences(View &v) {
  nvs_handle_t h;
  if (nvs_open("sagwa", NVS_READONLY, &h) != ESP_OK)
    return;
  uint8_t flags = 15;
  if (nvs_get_u8(h, "preferences", &flags) == ESP_OK) {
    v.pet_enabled = flags & 1;
    v.pet_sounds = flags & 2;
    v.pet_sensors = flags & 4;
    v.voice_enabled = flags & 8;
  }
  nvs_close(h);
}
void ui_save_preferences(const View &v) {
  nvs_handle_t h;
  if (nvs_open("sagwa", NVS_READWRITE, &h) != ESP_OK)
    return;
  uint8_t flags = v.pet_enabled | (v.pet_sounds << 1) | (v.pet_sensors << 2) |
                  (v.voice_enabled << 3);
  nvs_set_u8(h, "preferences", flags);
  nvs_commit(h);
  nvs_close(h);
}
bool ui_photo(const std::vector<uint8_t> &b) {
  if (b.size() != 320 * 240 * 2)
    return false;
  for (unsigned y = 0; y < 120; y++)
    for (unsigned x = 0; x < 160; x++) {
      unsigned at = (y * 2 * 320 + x * 2) * 2;
      photo_pixels[y * 160 + x] = uint16_t(b[at]) << 8 | b[at + 1];
    }
  first = true;
  return true;
}
void ui_draw(const View &v, uint32_t ms) {
  if (v.page != previous_page)
    transition_at = ms;
  bool transitioning = transition_at && ms - transition_at < 90;
  text_opacity = transitioning ? (ms - transition_at) * 255 / 90 : 255;
  compose(frame, v, ms);
  bool changed = first || v.page != previous_page ||
                 frame.size() != previous.size() ||
                 text_opacity != previous_opacity;
  if (!changed)
    for (unsigned i = 0; i < frame.size(); i++)
      if (frame[i] != previous[i]) {
        changed = true;
        break;
      }
  auto g = select_sagwa_graphic(v, ms);
  auto icon = status_icon(v);
  std::string token = std::to_string(g.avatar) + ":" + std::to_string(g.frame) +
                      ":" + std::to_string(icon) + ":" +
                      std::to_string(v.pet_pose);
  bool visual = token != signature;
  if (!changed && !visual && ms - last_draw < 67)
    return;
  last_draw = ms;
  bool home = v.page == Page::home && v.approval_id.empty();
  M5.Display.startWrite();
  if (first || v.page != previous_page) {
    M5.Display.fillScreen(0);
    previous_icon = 999;
  }
  if (changed) {
    if (home)
      M5.Display.fillRect(0, 150, 320, 90, 0);
    else
      M5.Display.fillScreen(0);
    for (const auto &r : frame)
      draw_text(r);
  }
  if (home) {
    // Alpha was retained in source PNGs and composited against pure black in
    // SAV1.
    ui_avatar_frame(g.avatar,
                    g.avatar == 4 ? (v.audio_level > .015f ? 1 : 0) : g.frame,
                    portrait);
    M5.Display.pushImage(84, 8, 136, 136, portrait);
    if (icon != previous_icon || first || changed)
      M5.Display.pushImage(280, 12, 28, 28,
                           reinterpret_cast<const uint16_t *>(
                               status_start + icon * 28 * 28 * 2));
  }
  if (v.page == Page::photo && v.photo_ready && changed)
    M5.Display.pushImage(80, 46, 160, 120, photo_pixels);
  M5.Display.endWrite();
  draw_finished = esp_timer_get_time() / 1000;
  previous = frame;
  previous_opacity = text_opacity;
  previous_page = v.page;
  signature = token;
  previous_icon = icon;
  first = false;
}
void ui_event(View &v, const char *type, const cJSON *p) {
  auto s = [&](const char *key) -> std::string {
    const char *value =
        cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(p, key));
    return value ? value : "";
  };
  if (!strcmp(type, "ui.result")) {
    auto offset = cJSON_GetObjectItemCaseSensitive(p, "offset");
    if (!cJSON_IsNumber(offset) || offset->valuedouble != offset->valueint)
      return;
    if (offset->valueint == 0)
      v.full_text.clear();
    if (offset->valueint == int(v.full_text.size()))
      v.full_text += s("text");
    return;
  }
  if (!strcmp(type, "ui.state")) {
    const auto mode = s("mode");
    if (!mode.empty())
      v.mode = mode;
    const auto actor = s("actor");
    if (!actor.empty())
      v.actor = actor;
    v.text = s("message");
    v.scroll = 0;
  } else if (!strcmp(type, "task.state") || !strcmp(type, "task.accepted")) {
    v.text = s("summary");
    v.full_text = s("full_text");
    if (v.full_text.empty())
      v.full_text = v.text;
    const auto state = s("state");
    v.task_active = state == "queued" || state == "running" ||
                    state == "needs_approval" || state == "reconciling";
    if (!v.task_active) {
      v.approval_id.clear();
      v.action_hash.clear();
    }
    v.mode = state == "completed" || state == "canceled"   ? "idle"
             : state == "failed" || state == "interrupted" ? "warning"
             : state == "needs_approval"                   ? "approval"
                                                           : "executing";
    v.scroll = 0;
  } else if (!strcmp(type, "approval.request")) {
    v.approval_id = s("approval_id");
    v.action_hash = s("action_hash");
    v.mode = "approval";
    v.page = Page::home;
    v.task_active = true;
    const auto *expires = cJSON_GetObjectItemCaseSensitive(p, "expires_at");
    v.approval_expires_ms =
        cJSON_IsNumber(expires) ? uint64_t(expires->valuedouble) : 0;
    v.scroll = 0;
    const cJSON *a = cJSON_GetObjectItemCaseSensitive(p, "action");
    char *text = cJSON_Print(a);
    v.text = text ? text : "Autorización solicitada";
    cJSON_free(text);
    v.text += "\nHash: " + v.action_hash;
  } else if (!strcmp(type, "voice.transcript"))
    v.text = s("text");
  else if (!strcmp(type, "error")) {
    auto code = s("code");
    v.text = code == "invalid_task" ? "Esa tarea ya no está disponible."
             : code == "unauthorized"
                 ? "Esta acción necesita autorización."
                 : "Algo falló. Puedes intentarlo de nuevo.";
    v.mode = "warning";
  } else if (!strcmp(type, "device.settings")) {
    v.agents.clear();
    v.nodes.clear();
    v.repositories.clear();
    const cJSON *entry;
    cJSON_ArrayForEach(entry, cJSON_GetObjectItemCaseSensitive(p, "agents")) {
      const char *id =
          cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(entry, "id"));
      if (id && v.agents.size() < 16)
        v.agents.push_back({id, agent_label(id),
                            cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(
                                entry, "available")) != 0});
    }
    cJSON_ArrayForEach(entry, cJSON_GetObjectItemCaseSensitive(p, "nodes")) {
      const char *id =
          cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(entry, "node"));
      if (id && (!strcmp(id, "mac-mini") || !strcmp(id, "tuf-infra")) &&
          v.nodes.size() < 3)
        v.nodes.push_back({id, node_label(id),
                           cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(
                               entry, "available")) != 0});
    }
    cJSON_ArrayForEach(entry,
                       cJSON_GetObjectItemCaseSensitive(p, "resources")) {
      const char *id =
          cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(entry, "id"));
      const char *kind =
          cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(entry, "kind"));
      const char *node =
          cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(entry, "node"));
      bool available = false;
      for (const auto &choice : v.nodes)
        if (node && choice.id == node)
          available = choice.available;
      if (id && kind && !strcmp(kind, "repository") &&
          v.repositories.size() < 3)
        v.repositories.push_back({id, id, available});
    }
    const auto prefs = cJSON_GetObjectItemCaseSensitive(p, "preferences");
    bool changed = false;
    for (auto pair : {std::make_pair("voice_enabled", &v.voice_enabled),
                      std::make_pair("pet_enabled", &v.pet_enabled),
                      std::make_pair("pet_sounds", &v.pet_sounds),
                      std::make_pair("pet_sensors", &v.pet_sensors)}) {
      const auto value = cJSON_GetObjectItemCaseSensitive(prefs, pair.first);
      if (cJSON_IsBool(value)) {
        bool state = cJSON_IsTrue(value);
        changed |= state != *pair.second;
        *pair.second = state;
      }
    }
    if (changed)
      ui_save_preferences(v);
    v.settings_ready = true;
  } else if (!strcmp(type, "device.snapshot")) {
    v.task.clear();
    v.task_active = false;
    v.approval_id.clear();
    v.action_hash.clear();
    v.scroll = 0;
    v.mode = "idle";
    v.text = "Sesión recuperada. Listo para hablar.";
    const auto *tasks = cJSON_GetObjectItemCaseSensitive(p, "tasks");
    const auto *task = cJSON_GetArrayItem(tasks, 0);
    if (task) {
      const char *id = cJSON_GetStringValue(
          cJSON_GetObjectItemCaseSensitive(task, "task_id"));
      if (id)
        v.task = id;
      ui_event(v, "task.state", task);
    }
    const auto *pending =
        cJSON_GetArrayItem(cJSON_GetObjectItemCaseSensitive(p, "approvals"), 0);
    if (pending)
      ui_event(v, "approval.request", pending);
  }
}
} // namespace shell
