#pragma once
#include <cstdint>
using BaseType_t = int;
using TickType_t = uint32_t;
using EventBits_t = uint32_t;
constexpr int pdTRUE = 1, pdFALSE = 0;
constexpr TickType_t portMAX_DELAY = UINT32_MAX;
#define pdMS_TO_TICKS(ms) (ms)
TickType_t xTaskGetTickCount();
void vTaskDelayUntil(TickType_t *, TickType_t);
void vTaskDelete(void *);
