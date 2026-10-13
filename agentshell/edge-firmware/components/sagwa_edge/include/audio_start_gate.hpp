#pragma once
#include <cstdint>

namespace sagwa {
// Event recovery and explicit audio control are independent sequence spaces.
// Only authenticated, task/generation-validated starts reach this gate.
class AudioStartGate {
public:
  void reset() {
    boundary_ = false;
    floor_ = control_ = 0;
  }
  void recover(uint64_t sequence) {
    if (!boundary_ || sequence > floor_)
      floor_ = sequence;
    boundary_ = true;
  }
  bool accept(uint64_t event_sequence, bool explicit_replay, bool has_control,
              uint64_t control_sequence) {
    if (has_control && (!control_sequence || control_sequence <= control_))
      return false;
    if (explicit_replay) {
      if (!has_control)
        return false;
    } else if (boundary_ && event_sequence <= floor_)
      return false;
    if (has_control)
      control_ = control_sequence;
    return true;
  }

private:
  bool boundary_ = false;
  uint64_t floor_ = 0, control_ = 0;
};
} // namespace sagwa
