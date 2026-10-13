#pragma once
#include "weather.hpp"
#include "cJSON.h"
#include <cmath>
#include <string>
namespace sagwa {
// This parser runs only after the existing authenticated WSS envelope gate.
// Bad/missing packets clear the previous data; no expired value is refreshed.
inline WeatherSnapshot weather_packet(const cJSON *p, uint32_t ms) {
  WeatherSnapshot out;
  auto field = [](const cJSON *j, const char *key) {
    const char *s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(j, key));
    return s ? std::string(s) : std::string{};
  };
  auto *w = cJSON_GetObjectItemCaseSensitive(p, "weather");
  auto integer = [&](const char *key, int low, int high, int &value) {
    auto *n = cJSON_GetObjectItemCaseSensitive(w, key);
    if (!cJSON_IsNumber(n) || !std::isfinite(n->valuedouble) ||
        n->valuedouble < low || n->valuedouble > high ||
        std::floor(n->valuedouble) != n->valuedouble)
      return false;
    value = int(n->valuedouble);
    return true;
  };
  int schema = 0, temperature = 0, ttl = 0;
  if (!cJSON_IsObject(w) || !integer("schema", 1, 1, schema) ||
      !cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(w, "available")) ||
      field(w, "source") != "nws" || field(w, "kind") != "forecast" ||
      !integer("temperature_centi_c", -9000, 6000, temperature) ||
      !integer("ttl_seconds", 1, 900, ttl))
    return out;
  const auto city = field(w, "city"), condition = field(w, "condition");
  if (city.empty() || city.size() > 40 ||
      city.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,'()-") != std::string::npos)
    return out;
  static constexpr const char *conditions[] = {
      "clear", "cloudy", "rain", "storm", "snow", "fog", "night", "unknown"};
  size_t index = 0;
  while (index < 8 && condition != conditions[index]) ++index;
  if (index == 8) return out;
  std::memcpy(out.city, city.data(), city.size());
  out.temperature_centi_c = temperature;
  out.condition = static_cast<WeatherCondition>(index);
  out.received_at = ms;
  out.ttl_ms = uint32_t(ttl) * 1000;
  out.available = true;
  return out;
}
} // namespace sagwa
