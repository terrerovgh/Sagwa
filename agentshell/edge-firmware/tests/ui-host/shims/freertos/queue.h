#pragma once
#include "FreeRTOS.h"
#include <cstddef>
struct HostQueue;
using QueueHandle_t = HostQueue *;
QueueHandle_t xQueueCreate(unsigned capacity, size_t size);
BaseType_t xQueueReceive(QueueHandle_t, void *, TickType_t);
BaseType_t xQueuePeek(QueueHandle_t, void *, TickType_t);
BaseType_t xQueueSend(QueueHandle_t, const void *, TickType_t);
BaseType_t xQueueOverwrite(QueueHandle_t, const void *);
