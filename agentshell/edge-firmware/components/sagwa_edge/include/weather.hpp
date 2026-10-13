#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
namespace sagwa {
enum class WeatherCondition : uint8_t {
  clear, cloudy, rain, storm, snow, fog, night, unknown
};
struct WeatherSnapshot {
  bool available = false;
  char city[41]{};
  int16_t temperature_centi_c = 0;
  WeatherCondition condition = WeatherCondition::unknown;
  uint32_t received_at = 0, ttl_ms = 0;
  bool fresh(uint32_t now) const {
    return available && ttl_ms > 0 && ttl_ms <= 900000 &&
           now - received_at < ttl_ms;
  }
  const char *description() const {
    switch (condition) {
    case WeatherCondition::clear: return "Despejado";
    case WeatherCondition::cloudy: return "Nublado";
    case WeatherCondition::rain: return "Lluvia";
    case WeatherCondition::storm: return "Tormenta";
    case WeatherCondition::snow: return "Nieve";
    case WeatherCondition::fog: return "Visibilidad reducida";
    case WeatherCondition::night: return "Noche despejada";
    default: return "Pronóstico";
    }
  }
  void text(char *out, size_t size, uint32_t now) const {
    if (!fresh(now)) {
      snprintf(out, size, "Clima: sin dato reciente\nElige una ciudad en el gateway");
      return;
    }
    const int v = temperature_centi_c;
    const int a = v < 0 ? -v : v;
    snprintf(out, size, "%s · %s%d.%d °C\n%s · pronóstico NWS",
             city, v < 0 ? "-" : "", a / 100, (a % 100) / 10, description());
  }
  uint32_t tint() const {
    if (condition == WeatherCondition::clear) return 0xE8C394;
    if (condition == WeatherCondition::night) return 0xA4B6DC;
    if (condition == WeatherCondition::rain || condition == WeatherCondition::snow ||
        condition == WeatherCondition::storm) return 0xADC3DD;
    return 0xEADBC6;
  }
};
} // namespace sagwa
