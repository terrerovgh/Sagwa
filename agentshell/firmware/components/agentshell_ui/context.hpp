#pragma once
#include "storage.hpp"
#include <string>
namespace shell {
void ui_context_begin(const Provision &);
void ui_context_offer(const cJSON *);
void ui_context_clear();
bool ui_context_frame(uint16_t *,uint32_t,std::string &,std::string &);
cJSON *ui_context_status();
}
