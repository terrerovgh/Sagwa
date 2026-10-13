#pragma once
#include "scene.hpp"
namespace shell {
enum class Control {
  none,
  start_voice,
  end_voice,
  stop_voice,
  photo,
  send_photo,
  discard_photo,
  cancel_task,
  approve,
  deny,
  refresh,
  pet_stroke,
  save_preferences,
  voice_sample,
  read_result
};
struct Input {
  int x = 0, y = 0;
  bool pressed = false, held = false, key_pressed = false, key_down = false;
  uint32_t ms = 0;
};
class Controls {
  bool key_voice = false, approving = false, tracking = false,
       gesture_done = false;
  uint32_t approval_since = 0, record_since = 0, touch_since = 0;
  int origin_x = 0, origin_y = 0, last_x = 0, last_y = 0, max_motion = 0;
  Page origin_page = Page::home;
  Control tap(View &, int, int);

public:
  Control update(View &, const Input &);
};
} // namespace shell
