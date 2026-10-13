#pragma once
#include <cstdint>
#include "storage.hpp"
namespace shell {
bool ota_is_current(const cJSON *payload);
bool ota_attempted(const cJSON *payload);
bool confirm_local_boot(bool healthy);
bool install_ota(const cJSON *payload, const Provision &);
} // namespace shell
