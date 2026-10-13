#pragma once
// Optional coordinate template for native UI extensions. Production Cat uses
// the authored transparent textures in rig_assets.h, not these rectangles.
namespace sagwa::rig {
struct Rect {
  int x, y, w, h;
};
inline constexpr Rect body{38, 61, 59, 68}, head{30, 21, 77, 61},
    left_ear{30, 5, 29, 34}, right_ear{78, 5, 29, 34};
inline constexpr Rect left_eye{43, 44, 17, 18}, right_eye{78, 44, 17, 18},
    left_paw{39, 111, 22, 21}, right_paw{75, 111, 22, 21};
inline constexpr int tail_x = 102, tail_y = 77, face_y = 44;
} // namespace sagwa::rig
