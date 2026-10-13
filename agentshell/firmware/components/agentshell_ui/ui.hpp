#pragma once
#include "cJSON.h"
#include "scene.hpp"
namespace shell {
void ui_begin();
void ui_next_avatar();
void ui_load_preferences(View &);
void ui_save_preferences(const View &);
void ui_draw(const View &, uint32_t ms);
uint32_t ui_last_draw_ms();
void ui_event(View &, const char *type, const cJSON *payload);
bool ui_photo(const std::vector<uint8_t> &);
} // namespace shell
