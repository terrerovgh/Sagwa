#pragma once
#include "FreeRTOS.h"
using EventGroupHandle_t = EventBits_t *;
inline EventBits_t xEventGroupGetBits(EventGroupHandle_t group) { return *group; }
inline EventBits_t xEventGroupSetBits(EventGroupHandle_t group, EventBits_t bits) {
  return *group |= bits;
}
inline EventBits_t xEventGroupClearBits(EventGroupHandle_t group, EventBits_t bits) {
  auto previous = *group;
  *group &= ~bits;
  return previous;
}
