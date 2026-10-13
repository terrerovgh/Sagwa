#include "controls.hpp"
#include <algorithm>
#include <cstdlib>
namespace shell {
namespace {
bool avatar(int x, int y) { return x >= 84 && x < 220 && y >= 8 && y < 144; }
void open(View &v, Page p) {
  if (p == Page::home)
    v.navigation.clear();
  else if (p != v.page)
    v.navigation.push_back(v.page);
  v.page = p;
  v.menu_scroll = v.scroll = 0;
  v.notice.clear();
}
} // namespace
Control Controls::update(View &v, const Input &i) {
  if (v.microphone) {
    tracking = false;
    if (key_voice && (!i.key_down || i.ms - record_since >= 8000)) {
      key_voice = false;
      return Control::end_voice;
    }
    return Control::none;
  }
  if (i.key_pressed) {
    tracking = false;
    if (v.speaker)
      return Control::stop_voice;
    if (!v.approval_id.empty())
      return Control::none;
    if (!voice_available(v)) {
      v.notice = "Muse no está disponible";
      return Control::refresh;
    }
    open(v, Page::home);
    key_voice = true;
    record_since = i.ms;
    return Control::start_voice;
  }
  if (!v.approval_id.empty()) {
    if (i.pressed && i.y >= 192 && i.x >= 160) {
      approving = true;
      approval_since = i.ms;
    }
    if (!i.held || i.y < 192 || i.x < 160) {
      approving = false;
      v.approval_hold_ms = 0;
    }
    if (approving) {
      v.approval_hold_ms = std::min<uint32_t>(1500, i.ms - approval_since);
      if (v.approval_hold_ms >= 1500) {
        approving = false;
        v.approval_hold_ms = 0;
        return Control::approve;
      }
    }
    if (i.pressed && i.y >= 192 && i.x < 152)
      return Control::deny;
    // Reading an approval never constitutes consent.
    if (i.pressed && i.y < 192) {
      tracking = true;
      origin_y = last_y = i.y;
    }
    if (tracking && i.held)
      last_y = i.y;
    if (tracking && !i.held) {
      tracking = false;
      int dy = last_y - origin_y;
      if (std::abs(dy) > 32) {
        unsigned total = text_lines(v.text), limit = total > 6 ? total - 6 : 0;
        v.scroll = dy < 0 ? std::min(limit, v.scroll + 5)
                          : (v.scroll > 5 ? v.scroll - 5 : 0);
      }
    }
    return Control::none;
  }
  approving = false;
  if (i.pressed) {
    tracking = true;
    gesture_done = false;
    origin_x = last_x = i.x;
    origin_y = last_y = i.y;
    max_motion = 0;
    touch_since = i.ms;
    origin_page = v.page;
    return Control::none;
  }
  if (!tracking)
    return Control::none;
  if (v.page != origin_page) {
    tracking = false;
    return Control::none;
  }
  if (i.held) {
    last_x = i.x;
    last_y = i.y;
  }
  int dx = last_x - origin_x, dy = last_y - origin_y;
  max_motion = std::max(max_motion, std::max(std::abs(dx), std::abs(dy)));
  if (!gesture_done && max_motion >= 36) {
    bool horizontal = std::abs(dx) > std::abs(dy) * 3 / 2,
         vertical = std::abs(dy) > std::abs(dx) * 3 / 2;
    if (horizontal && origin_x <= 20 && dx > 36) {
      tracking = false;
      if (origin_page == Page::home)
        open(v, Page::options);
      else {
        auto back = v.navigation.empty() ? Page::home : v.navigation.back();
        if (!v.navigation.empty())
          v.navigation.pop_back();
        v.page = back;
        v.scroll = v.menu_scroll = 0;
        v.notice.clear();
      }
      return origin_page == Page::photo ? Control::discard_photo
                                        : Control::refresh;
    }
    if (origin_page == Page::home && horizontal && origin_x >= 300 &&
        dx < -36) {
      tracking = false;
      open(v, Page::activities);
      return Control::refresh;
    }
    if (origin_page == Page::home && vertical && origin_y <= 20 && dy > 36) {
      tracking = false;
      open(v, Page::settings);
      return Control::none;
    }
  }
  if (!gesture_done && origin_page == Page::home &&
      avatar(origin_x, origin_y) && origin_x > 20 && origin_x < 300 &&
      origin_y > 20 && (max_motion >= 12 || i.ms - touch_since > 400)) {
    gesture_done = true;
    return Control::pet_stroke;
  }
  if (i.held)
    return Control::none;
  tracking = false;
  if (gesture_done)
    return Control::none;
  if (std::abs(dy) >= 32 && std::abs(dy) > std::abs(dx) * 3 / 2) {
    if ((origin_page == Page::home && origin_y >= 152) ||
        origin_page == Page::reader || origin_page == Page::error ||
        origin_page == Page::sensors || origin_page == Page::credits) {
      unsigned count = origin_page == Page::home     ? 3
                       : origin_page == Page::error  ? 6
                       : origin_page == Page::reader ? 7
                                                     : 8,
               size = origin_page == Page::reader || origin_page == Page::error
                          ? 20
                          : 16;
      auto text = reading_text(v);
      unsigned total = text_lines(text, 288, size),
               limit = total > count ? total - count : 0;
      v.scroll = dy < 0 ? std::min(limit, v.scroll + count)
                        : (v.scroll > count ? v.scroll - count : 0);
    } else {
      auto rows = page_rows(v);
      unsigned limit = rows.size() > 4 ? rows.size() - 4 : 0;
      v.menu_scroll = dy < 0 ? std::min(limit, v.menu_scroll + 3)
                             : (v.menu_scroll > 3 ? v.menu_scroll - 3 : 0);
    }
    return Control::none;
  }
  if (max_motion >= 12 || i.ms - touch_since > 1500)
    return Control::none;
  return tap(v, origin_x, origin_y);
}
Control Controls::tap(View &v, int x, int y) {
  if (v.page == Page::home) {
    if (y >= 152) {
      open(v, v.mode == "warning" ? Page::error : Page::reader);
      return v.page == Page::error ? Control::none : Control::read_result;
    }
    if (avatar(x, y))
      return Control::pet_stroke;
    return Control::none;
  }
  if (v.page == Page::photo && y >= 192) {
    if (x < 160) {
      open(v, Page::home);
      v.photo_ready = false;
      return Control::discard_photo;
    }
    return v.photo_ready && v.connected && agent_available(v, "muse")
               ? Control::send_photo
               : Control::photo;
  }
  if (v.page == Page::cancel && y >= 192) {
    if (x < 160) {
      open(v, Page::tasks);
      return Control::none;
    }
    if (v.task_active) {
      open(v, Page::home);
      return Control::cancel_task;
    }
    return Control::none;
  }
  if (y < 48 || y >= 224 || x < 8 || x >= 312)
    return Control::none;
  auto rows = page_rows(v);
  unsigned at = v.menu_scroll + (y - 48) / 44;
  if (at >= rows.size())
    return Control::none;
  auto r = rows[at];
  if (!r.enabled) {
    v.notice = "No disponible";
    return Control::none;
  }
  if (v.page == Page::agents) {
    if (r.id != "muse" && r.id != "auto") {
      v.notice = "Muse elige a sus delegados";
      return Control::none;
    }
    v.preferred = r.id;
    open(v, Page::options);
    return Control::none;
  }
  if (v.page == Page::destinations) {
    v.target = r.id;
    open(v, Page::options);
    return Control::none;
  }
  if (r.id == "voice_enabled") {
    v.voice_enabled = !v.voice_enabled;
    return Control::save_preferences;
  }
  if (r.id == "pet_enabled") {
    v.pet_enabled = !v.pet_enabled;
    return Control::save_preferences;
  }
  if (r.id == "pet_sounds") {
    v.pet_sounds = !v.pet_sounds;
    return Control::save_preferences;
  }
  if (r.id == "pet_sensors") {
    v.pet_sensors = !v.pet_sensors;
    return Control::save_preferences;
  }
  if (r.id == "pet_demo") {
    open(v, Page::home);
    return Control::pet_stroke;
  }
  if (r.id == "voice_sample")
    return Control::voice_sample;
  if (r.id == "camera")
    return Control::photo;
  if (r.id == "home" || r.id == "conversation") {
    v.capability = "conversation";
    open(v, Page::home);
    return Control::none;
  }
  if (r.id == "infra.diagnose" || r.id == "code.change") {
    v.capability = r.id;
    if (r.id == "code.change")
      v.target = v.repositories.front().id;
    else if (std::none_of(v.nodes.begin(), v.nodes.end(),
                          [&](const Choice &n) { return n.id == v.target; }))
      v.target = "mac-mini";
    open(v, Page::home);
    return Control::none;
  }
  if (r.id == "agents")
    open(v, Page::agents);
  else if (r.id == "destinations")
    open(v, Page::destinations);
  else if (r.id == "tasks")
    open(v, Page::tasks);
  else if (r.id == "cancel")
    open(v, Page::cancel);
  else if (r.id == "reader") {
    open(v, Page::reader);
    return Control::read_result;
  } else if (r.id == "settings")
    open(v, Page::settings);
  else if (r.id == "voice")
    open(v, Page::voice);
  else if (r.id == "pet")
    open(v, Page::pet);
  else if (r.id == "sensors")
    open(v, Page::sensors);
  else if (r.id == "credits")
    open(v, Page::credits);
  return Control::none;
}
} // namespace shell
