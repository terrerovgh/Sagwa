#pragma once
#include <cmath>
#include <cstdint>
namespace shell {
struct LocalSensors {
  uint32_t sampled_ms = 0;
  bool light_ok = false, proximity_ok = false, accel_ok = false,
       gyro_ok = false;
  float light = 0, proximity = 0, ax = 0, ay = 0, az = 0, gx = 0, gy = 0,
        gz = 0;
};
enum class PetSound { none, meow, purr };
struct PetReaction {
  unsigned pose = 0;
  PetSound sound = PetSound::none;
};
class Pet {
  bool ready = false, accel_ready = false, near = false, dark = false,
       sleeping = false;
  float light = 0, proximity = 0, ax = 0, ay = 0, az = 0, angle = 0;
  uint32_t sample = 0, dark_since = 0, pose_until = 0, last_sound = 0,
           last_motion = 0, last_idle = 0;
  unsigned pose = 0;
  PetSound sound(PetSound s, uint32_t ms) {
    if (last_sound && ms - last_sound < 5000)
      return PetSound::none;
    last_sound = ms;
    return s;
  }

public:
  PetReaction stroke(uint32_t ms) {
    pose = 7;
    pose_until = ms + 2000;
    sleeping = false;
    return {pose, sound(PetSound::purr, ms)};
  }
  PetReaction update(const LocalSensors &s, uint32_t ms, bool allowed) {
    if (!allowed) {
      pose_until = 0;
      return {};
    }
    PetSound audio = PetSound::none;
    if (s.sampled_ms && ms - s.sampled_ms <= 600 && sample != s.sampled_ms) {
      bool first = !ready;
      sample = s.sampled_ms;
      ready = true;
      if (s.light_ok && std::isfinite(s.light)) {
        light = first ? s.light : light + .6f * (s.light - light);
        if (light < 8 && !dark) {
          dark = true;
          dark_since = ms;
        }
        if (light > 18) {
          dark = false;
          if (sleeping) {
            sleeping = false;
            pose = 9;
            pose_until = ms + 1800;
          }
        }
        if (dark && ms - dark_since >= 30000)
          sleeping = true;
      } else {
        dark = false;
        sleeping = false;
      }
      if (s.proximity_ok && std::isfinite(s.proximity)) {
        proximity =
            first ? s.proximity : proximity + .6f * (s.proximity - proximity);
        if (!near && proximity > 300) {
          near = true;
          sleeping = false;
          pose = 1;
          pose_until = ms + 1800;
          audio = sound(PetSound::meow, ms);
        }
        if (near && proximity < 230)
          near = false;
      } else
        near = false;
      if (s.accel_ok && std::isfinite(s.ax) && std::isfinite(s.ay) &&
          std::isfinite(s.az)) {
        float delta =
            std::abs(s.ax - ax) + std::abs(s.ay - ay) + std::abs(s.az - az);
        float current_angle = std::atan2(s.ay, s.az);
        float rotation = std::abs(std::atan2(std::sin(current_angle - angle),
                                             std::cos(current_angle - angle)));
        bool moved =
            accel_ready &&
            (delta > .45f || rotation > .18f ||
             (s.gyro_ok &&
              (std::abs(s.gx) + std::abs(s.gy) + std::abs(s.gz) > 45)));
        if (moved && ms - last_motion > 1500) {
          last_motion = ms;
          angle = current_angle;
          pose = sleeping ? 9 : 11;
          sleeping = false;
          pose_until = ms + 1500;
        }
        if (!accel_ready)
          angle = current_angle;
        accel_ready = true;
        ax = s.ax;
        ay = s.ay;
        az = s.az;
      } else
        accel_ready = false;
    }
    // Old readings never keep a sensor-originated reaction alive.
    if (!s.sampled_ms || ms - s.sampled_ms > 600) {
      dark = false;
      sleeping = false;
      ready = false;
      accel_ready = false;
      near = false;
      sample = 0;
      if (pose != 7)
        pose_until = 0;
    }
    if (ms > pose_until) {
      pose = sleeping ? 8 : 0;
      if (!sleeping && ms - last_idle > 45000) {
        last_idle = ms;
        pose = 10;
        pose_until = ms + 1600;
      }
    }
    return {pose, audio};
  }
};
} // namespace shell
