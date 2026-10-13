#pragma once
#include <cstdint>
namespace sagwa {
// Portable Pomodoro clock; monotonic uint32 milliseconds, no network
// dependency. All operations belong to UI_Task. Reboot restores a paused
// snapshot: powered-off time is never inferred from an unrelated monotonic
// clock or an untrusted RTC.
class FocusTimer {
public:
  enum class Phase : uint8_t { focus, rest };
  enum class State : uint8_t { ready, running, paused, complete };
  struct Snapshot {
    uint32_t schema = 1;
    uint32_t remaining_ms = 25 * 60 * 1000;
    uint8_t phase = uint8_t(Phase::focus);
    uint8_t state = uint8_t(State::ready);
    uint16_t reserved = 0;
  };

private:
  uint32_t remaining_ = 25 * 60 * 1000, anchor_ = 0;
  Phase phase_ = Phase::focus;
  State state_ = State::ready;

public:
  static constexpr uint32_t duration(Phase p) {
    return p == Phase::focus ? 1500000 : 300000;
  }
  Phase phase() const { return phase_; }
  State state() const { return state_; }
  uint32_t remaining_ms() const { return remaining_; }
  uint32_t remaining_seconds() const { return (remaining_ + 999) / 1000; }
  // True once on completion. A long scheduling gap subtracts at most one phase;
  // it never starts a break or a second session without the user choosing it.
  bool tick(uint32_t now) {
    if (state_ != State::running)
      return false;
    uint32_t elapsed = now - anchor_;
    anchor_ = now;
    if (elapsed >= remaining_) {
      remaining_ = 0;
      state_ = State::complete;
      return true;
    }
    remaining_ -= elapsed;
    return false;
  }
  bool start(uint32_t now) {
    if (state_ == State::running || state_ == State::complete)
      return false;
    anchor_ = now;
    state_ = State::running;
    return true;
  }
  bool pause(uint32_t now) {
    if (state_ != State::running)
      return false;
    tick(now);
    if (state_ == State::running)
      state_ = State::paused;
    return true;
  }
  void reset(Phase phase = Phase::focus) {
    phase_ = phase;
    remaining_ = duration(phase);
    state_ = State::ready;
  }
  Snapshot snapshot(uint32_t now) {
    tick(now);
    return {1, remaining_, uint8_t(phase_), uint8_t(state_)};
  }
  bool restore(const Snapshot &s) {
    if (s.schema != 1 || s.reserved != 0 || s.phase > uint8_t(Phase::rest) ||
        s.state > uint8_t(State::complete))
      return false;
    Phase p = Phase(s.phase);
    State state = State(s.state);
    if (s.remaining_ms > duration(p) ||
        ((state == State::complete) != (s.remaining_ms == 0)) ||
        (state == State::ready && s.remaining_ms != duration(p)))
      return false;
    phase_ = p;
    remaining_ = s.remaining_ms;
    state_ = state == State::running ? State::paused : state;
    anchor_ = 0;
    return true;
  }
};
} // namespace sagwa
