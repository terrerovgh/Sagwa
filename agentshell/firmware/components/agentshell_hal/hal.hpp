#pragma once
#include <cstdint>
#include "cJSON.h"
#include <vector>
#include "pet.hpp"
namespace shell {
bool hal_begin();
bool hal_sd_begin();
void hal_update();
cJSON *sensors();
LocalSensors local_sensors();
bool presence();
bool key_pressed();
bool key_released();
bool key_held();
bool touch(int &x, int &y, bool &held);
int battery();
bool capture(std::vector<uint8_t> &);
void calibrate(bool start);
} // namespace shell
