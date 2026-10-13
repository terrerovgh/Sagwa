#pragma once
#include "cat_raster.hpp"
#include "edge.hpp"
#include <array>

namespace sagwa {
// Internal native asset interface. Layer order is also the compositing order.
// Textures are immutable BGRA bytes in flash; only the RGB565 target is writable.
enum class RigPart : size_t {
  tail, body, ear_left, ear_right, head, eye_left, eye_right,
  pupil_left, pupil_right, lid_left, lid_right, mouth_closed, mouth_open, count
};
struct RigLayer {
  CatTexture texture{};
  float x = 0, y = 0, pivot_x = 0, pivot_y = 0;
};
struct RigDefinition {
  const char *id;
  std::array<RigLayer, size_t(RigPart::count)> layers;
};
inline bool valid_rig(const RigDefinition &rig) {
  if (!rig.id || !*rig.id) return false;
  for (const auto &layer : rig.layers) {
    const auto &t = layer.texture;
    if (!t.data || t.width <= 0 || t.height <= 0 || t.width > 136 ||
        t.height > 136 || t.stride < t.width * 4 || t.stride > 544 ||
        t.bytes != size_t(t.stride) * size_t(t.height) ||
        !std::isfinite(layer.x) || !std::isfinite(layer.y) ||
        !std::isfinite(layer.pivot_x) || !std::isfinite(layer.pivot_y) ||
        std::abs(layer.x) > 136 || std::abs(layer.y) > 136 ||
        std::abs(layer.pivot_x) > 136 || std::abs(layer.pivot_y) > 136)
      return false;
  }
  return true;
}
// Called under the BSP display lock; validation is performed once when mounting.
inline void render_rig(const RigDefinition &rig, const Pose &pose,
                       uint16_t *pixels, uint32_t tint = 0,
                       unsigned tint_alpha = 0, bool small = false) {
  CatRaster frame(pixels, 136, 136, int(pose.lean * 120),
                  small ? 0 : 68, small ? 0 : 128, tint, tint_alpha);
  const auto mouth = unsigned(std::clamp(pose.mouth, 0.f, 1.f) * 255);
  for (size_t i = 0; i < rig.layers.size(); ++i) {
    const auto &l = rig.layers[i];
    float x = l.x, y = l.y, scale = 1;
    int angle = 0;
    unsigned opacity = 255;
    switch (static_cast<RigPart>(i)) {
    case RigPart::tail: angle = int(pose.tail * 180); break;
    case RigPart::body: scale = pose.breath * pose.stretch; break;
    case RigPart::ear_left: angle = int(-pose.ear_left * 180); break;
    case RigPart::ear_right: angle = int(pose.ear_right * 180); break;
    case RigPart::eye_left:
    case RigPart::eye_right: scale = std::max(.0625f, pose.blink); break;
    case RigPart::pupil_left:
    case RigPart::pupil_right:
      x += pose.gaze_x * 3;
      y += pose.gaze_y * 2;
      opacity = pose.blink < .3f ? 0 : 255;
      break;
    case RigPart::lid_left:
    case RigPart::lid_right: opacity = pose.blink < .22f ? 255 : 0; break;
    case RigPart::mouth_closed: opacity = 255 - mouth; break;
    case RigPart::mouth_open: opacity = mouth; break;
    default: break;
    }
    frame.layer(l.texture, x, y, l.pivot_x, l.pivot_y, angle, scale, opacity);
  }
}
} // namespace sagwa
