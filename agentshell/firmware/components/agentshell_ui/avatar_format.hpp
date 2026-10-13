#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
namespace shell {
constexpr size_t avatar_max_bytes = 16 + 136 * 136 * 2 * 32;
inline unsigned avatar_u16(const uint8_t *p) {
  return p[0] | unsigned(p[1]) << 8;
}
inline bool avatar_valid(const uint8_t *p, size_t size, unsigned state) {
  if (!p || size < 16 || std::memcmp(p, "SAV1", 4) ||
      avatar_u16(p + 4) != 136 || avatar_u16(p + 6) != 136 ||
      avatar_u16(p + 12) != state || avatar_u16(p + 14) != 0)
    return false;
  unsigned frames = avatar_u16(p + 8), ms = avatar_u16(p + 10);
  return frames > 0 && frames <= 32 && ms >= 67 && ms <= 2000 &&
         size == 16 + size_t(frames) * 136 * 136 * 2;
}
} // namespace shell
