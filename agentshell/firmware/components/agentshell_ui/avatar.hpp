#pragma once
#include "storage.hpp"
namespace shell {
void ui_avatar_begin(const Provision &);
void ui_avatar_offer(const cJSON *);
bool ui_avatar_frame(unsigned pose, unsigned frame, uint16_t *pixels);
cJSON *ui_avatar_status();
} // namespace shell
