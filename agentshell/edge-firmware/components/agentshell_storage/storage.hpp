#pragma once
#include <cstdint>
#include "cJSON.h"
#include <string>
#include <vector>
namespace shell {
struct Provision {
  std::string ssid, password, ca, certificate, key, device_id;
  std::vector<std::string> gateways;
  int64_t epoch = 0;
};
bool load_provision(Provision &);
bool install_provision(const cJSON *, Provision &);
bool sd_begin();
void sd_log(const char *event);
uint64_t load_sequence();
bool save_sequence(uint64_t sequence);
} // namespace shell
