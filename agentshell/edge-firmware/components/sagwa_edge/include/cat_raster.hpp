#pragma once
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>

namespace sagwa {
// Bounded, allocation-free compositor. Original BGRA/alpha assets stay intact.
// Composite on the product's pure-black background, then send one RGB565 image
// to LVGL. All access is protected by the same BSP display mutex as LVGL.
struct CatTexture {
  const uint8_t *data;
  size_t bytes;
  int width, height, stride;
};
class CatRaster {
  uint16_t *pixels_;
  int width_, height_;
  float root_c_, root_s_, root_x_, root_y_;
  uint32_t tint_;
  unsigned tint_alpha_;
  static unsigned div255(unsigned n) {
    n += 128;
    return (n + (n >> 8)) >> 8;
  }
public:
  CatRaster(uint16_t *pixels, int width, int height, int angle,
            float pivot_x, float pivot_y, uint32_t tint = 0,
            unsigned tint_alpha = 0)
      : pixels_(pixels), width_(std::clamp(width, 0, 136)),
        height_(std::clamp(height, 0, 136)),
        root_x_(std::isfinite(pivot_x) ? std::clamp(pivot_x, -256.f, 256.f) : 0),
        root_y_(std::isfinite(pivot_y) ? std::clamp(pivot_y, -256.f, 256.f) : 0),
        tint_(tint), tint_alpha_(std::min(255u, tint_alpha)) {
    const float radians = angle * (3.14159265358979323846f / 1800.f);
    root_c_ = std::cos(radians);
    root_s_ = std::sin(radians);
    if (pixels_) std::fill(pixels_, pixels_ + size_t(width_) * height_, 0);
  }
  void layer(const CatTexture &t, float x, float y, float pivot_x = 0,
             float pivot_y = 0, int angle = 0, float scale_y = 1,
             unsigned opacity = 255) {
    if (!pixels_ || !opacity || !t.data || t.width <= 0 || t.height <= 0 ||
        t.width > 136 || t.height > 136 || t.stride < t.width * 4 ||
        t.stride > 2048 || !std::isfinite(x) || !std::isfinite(y) ||
        !std::isfinite(pivot_x) || !std::isfinite(pivot_y) ||
        std::abs(x) > 512 || std::abs(y) > 512 ||
        std::abs(pivot_x) > 256 || std::abs(pivot_y) > 256 ||
        t.bytes < size_t(t.stride) * t.height || !std::isfinite(scale_y) ||
        scale_y < .01f || scale_y > 2.f)
      return;
    opacity = std::min(255u, opacity);
    const float rad = angle * (3.14159265358979323846f / 1800.f);
    const float c = std::cos(rad), s = std::sin(rad);
    // Local image transform followed by the character's root transform.
    const float a = root_c_ * c - root_s_ * s;
    const float b = (-root_c_ * s - root_s_ * c) * scale_y;
    const float d = root_s_ * c + root_c_ * s;
    const float e = (-root_s_ * s + root_c_ * c) * scale_y;
    const float local_x = x + pivot_x - c * pivot_x + s * scale_y * pivot_y;
    const float local_y = y + pivot_y - s * pivot_x - c * scale_y * pivot_y;
    const float tx = root_x_ + root_c_ * (local_x - root_x_) -
                     root_s_ * (local_y - root_y_);
    const float ty = root_y_ + root_s_ * (local_x - root_x_) +
                     root_c_ * (local_y - root_y_);
    float min_x = float(width_), min_y = float(height_), max_x = -1, max_y = -1;
    for (int corner = 0; corner < 4; ++corner) {
      const float sx = (corner & 1) ? t.width - .5f : -.5f;
      const float sy = (corner & 2) ? t.height - .5f : -.5f;
      const float dx = a * sx + b * sy + tx, dy = d * sx + e * sy + ty;
      min_x = std::min(min_x, dx); max_x = std::max(max_x, dx);
      min_y = std::min(min_y, dy); max_y = std::max(max_y, dy);
    }
    const int left = std::max(0, int(std::floor(min_x)));
    const int right = std::min(width_ - 1, int(std::ceil(max_x)));
    const int top = std::max(0, int(std::floor(min_y)));
    const int bottom = std::min(height_ - 1, int(std::ceil(max_y)));
    const float determinant = a * e - b * d;
    if (std::abs(determinant) < .01f) return;
    const float ia = e / determinant, ib = -b / determinant;
    const float id = -d / determinant, ie = a / determinant;
    for (int dy = top; dy <= bottom; ++dy) {
      float sx = ia * (left - tx) + ib * (dy - ty);
      float sy = id * (left - tx) + ie * (dy - ty);
      auto *row = pixels_ + size_t(dy) * width_;
      for (int dx = left; dx <= right; ++dx, sx += ia, sy += id) {
        if (sx < -.5f || sy < -.5f || sx >= t.width - .5f || sy >= t.height - .5f)
          continue;
        const int px = int(sx + .5f), py = int(sy + .5f);
        const auto *source = t.data + size_t(py) * t.stride + px * 4;
        const unsigned alpha = div255(source[3] * opacity);
        if (!alpha) continue;
        unsigned red = source[2], green = source[1], blue = source[0];
        if (tint_alpha_) {
          red = div255(red * (255 - tint_alpha_) + ((tint_ >> 16) & 255) * tint_alpha_);
          green = div255(green * (255 - tint_alpha_) + ((tint_ >> 8) & 255) * tint_alpha_);
          blue = div255(blue * (255 - tint_alpha_) + (tint_ & 255) * tint_alpha_);
        }
        red >>= 3; green >>= 2; blue >>= 3;
        if (alpha != 255) {
          const auto prior = row[dx];
          red = div255(red * alpha + (prior >> 11) * (255 - alpha));
          green = div255(green * alpha + ((prior >> 5) & 63) * (255 - alpha));
          blue = div255(blue * alpha + (prior & 31) * (255 - alpha));
        }
        row[dx] = uint16_t((red << 11) | (green << 5) | blue);
      }
    }
  }
};
} // namespace sagwa
