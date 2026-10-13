#pragma once
#include "noto.hpp"
#include <cstdint>
#include <string>
#include <vector>
namespace shell {
enum class Page {
  home,
  options,
  agents,
  destinations,
  activities,
  photo,
  cancel,
  reader,
  settings,
  sensors,
  voice,
  pet,
  tasks,
  credits,
  error
};
struct Choice {
  std::string id, label;
  bool available = false;
};
struct View {
  std::string mode = "offline", actor = "Muse",
              text = "Sin conexión. Sagwa está aquí.", full_text, task,
              approval_id, action_hash, context_name;
  std::string display_name = "Sagwa", preferred = "muse", target = "mac-mini",
              capability = "conversation", notice, sensor_text;
  int battery = -1;
  unsigned theme = 0, scroll = 0, menu_scroll = 0, approval_hold_ms = 0;
  uint64_t approval_expires_ms = 0;
  bool camera = false, microphone = false, connected = false, speaker = false,
       task_active = false, photo_ready = false, settings_ready = false;
  bool pet_enabled = true, pet_sounds = true, pet_sensors = true,
       voice_enabled = true;
  unsigned pet_pose = 0;
  float audio_level = 0;
  Page page = Page::home;
  std::vector<Choice> agents, nodes, repositories;
  std::vector<Page> navigation;
};
struct TextRun {
  int x, y;
  unsigned size;
  std::string text;
  bool operator!=(const TextRun &o) const {
    return x != o.x || y != o.y || size != o.size || text != o.text;
  }
};
using Frame = std::vector<TextRun>;
struct Row {
  std::string id, label, detail;
  bool enabled = true;
};
std::vector<Row> page_rows(const View &);
std::string reading_text(const View &);
const std::vector<std::string> &
wrap_text(const std::string &, unsigned width = 288, unsigned size = 16);
unsigned next_codepoint(const std::string &, size_t &);
unsigned text_width(const std::string &, unsigned size = 16);
unsigned text_lines(const std::string &, unsigned width = 288,
                    unsigned size = 16);
void compose(Frame &, const View &, uint32_t ms, const std::string &clock = "");
Graphic select_graphic(const View &, uint32_t);
Graphic select_sagwa_graphic(const View &, uint32_t);
unsigned status_icon(const View &);
const char *page_name(Page);
bool agent_available(const View &, const std::string &);
bool auto_available(const View &);
bool voice_available(const View &);
std::string agent_label(const std::string &);
std::string node_label(const std::string &);
std::string activity_label(const std::string &);
} // namespace shell
