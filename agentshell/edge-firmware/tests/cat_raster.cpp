#include "cat_raster.hpp"
#include <array>
#include <cassert>
#include <cstdio>
#include <limits>
#include <vector>
using namespace sagwa;
int main() {
  const uint8_t white[] = {255, 255, 255, 255};
  const uint8_t colors[] = {0, 0, 255, 255, 0, 255, 0, 255};
  std::array<uint16_t, 11> storage{};
  storage.front() = storage.back() = 0x1234;
  auto *pixels = storage.data() + 1;
  CatTexture one{white, sizeof white, 1, 1, 4};
  { CatRaster frame(pixels, 3, 3, 0, 0, 0);
    frame.layer(one, 1, 1); assert(pixels[4] == 0xffff);
    assert(pixels[0] == 0); }
  { CatRaster frame(pixels, 3, 3, 0, 0, 0);
    frame.layer(one, 1, 1, 0, 0, 0, 1, 128);
    assert(pixels[4] == 0x8410); }
  { CatRaster frame(pixels, 3, 3, 0, 0, 0, 0, 128);
    frame.layer(one, 1, 1); assert(pixels[4] == 0x7bef); }
  { CatRaster frame(pixels, 3, 3, 900, 1, 1);
    frame.layer({colors, 4, 1, 1, 4}, 0, 0);
    assert(pixels[2] == 0xf800); }
  { CatRaster frame(pixels, 3, 3, 0, 0, 0);
    frame.layer({colors, sizeof colors, 2, 1, 8}, 1, 1, 0, 0, 900);
    assert(pixels[4] == 0xf800 && pixels[7] == 0x07e0); }
  { CatRaster frame(pixels, 3, 3, 0, 0, 0);
    frame.layer({colors, sizeof colors, 2, 1, 8}, -1, 0);
    assert(pixels[0] == 0x07e0); }
  { CatRaster frame(pixels, 3, 3, 0, 0, 0);
    frame.layer({white, 0, 1, 1, 4}, 0, 0);
    frame.layer({white, 4, 137, 1, 4}, 0, 0);
    frame.layer(one, std::numeric_limits<float>::quiet_NaN(), 0);
    frame.layer(one, 0, 0, 0, 0, 0, 0);
    frame.layer(one, 0, 0, 0, 0, 0, 1, 0);
    for (int i = 0; i < 9; ++i) assert(pixels[i] == 0); }
  assert(storage.front() == 0x1234 && storage.back() == 0x1234);
  std::vector<uint16_t> guarded(136 * 136 + 2, 0x4567);
  std::vector<uint8_t> texture(136 * 136 * 4);
  for (size_t i = 0; i < texture.size(); ++i)
    texture[i] = uint8_t((i * 73 + 19) % 256);
  for (int angle = -1800; angle <= 1800; angle += 37) {
    CatRaster frame(guarded.data() + 1, 136, 136, angle, 68, 128);
    frame.layer({texture.data(), texture.size(), 136, 136, 544},
                -13, -9, 68, 128, -angle, .063f + (angle + 1800) / 2000.f);
    assert(guarded.front() == 0x4567 && guarded.back() == 0x4567);
  }
  puts("PASS: RGB565 color/alpha/tint, root/local affine transforms, clipping, malformed textures and guarded136px stress; no hardware FPS claim.");
}
