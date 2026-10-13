#include "focus_timer.hpp"
#include <cassert>
#include <cstdint>
#include <iostream>
using sagwa::FocusTimer;
int main() {
  FocusTimer t;
  assert(t.state() == FocusTimer::State::ready &&
         t.remaining_seconds() == 1500);
  assert(!t.tick(900000));
  assert(t.start(100));
  assert(!t.start(200));
  assert(!t.tick(101));
  assert(t.remaining_seconds() == 1500);
  assert(t.pause(1100));
  assert(t.remaining_ms() == 1499000);
  assert(!t.tick(500000));
  assert(t.start(500000));
  assert(t.tick(500000 + 1499000));
  assert(!t.tick(9999999));
  assert(!t.start(9999999));
  t.reset(FocusTimer::Phase::rest);
  assert(t.remaining_seconds() == 300);
  assert(t.start(UINT32_MAX - 1000));
  assert(!t.tick(999));
  assert(t.remaining_ms() == 298000);
  auto saved = t.snapshot(1999);
  FocusTimer restored;
  assert(restored.restore(saved));
  assert(restored.state() == FocusTimer::State::paused &&
         restored.remaining_ms() == 297000);
  assert(!restored.tick(700000));
  assert(restored.start(800000));
  assert(restored.tick(1097000));
  assert(!restored.tick(1097000));
  auto before = restored.snapshot(1097000);
  auto invalid = before;
  invalid.remaining_ms = 1;
  assert(!restored.restore(invalid));
  assert(restored.remaining_ms() == 0 &&
         restored.state() == FocusTimer::State::complete);
  invalid = before;
  invalid.phase = 255;
  assert(!restored.restore(invalid));
  invalid = before;
  invalid.state = 255;
  assert(!restored.restore(invalid));
  invalid = before;
  invalid.schema = 2;
  assert(!restored.restore(invalid));
  invalid = before;
  invalid.remaining_ms = 300001;
  assert(!restored.restore(invalid));
  restored.reset();
  auto ready = restored.snapshot(0);
  ready.remaining_ms = 1499999;
  assert(!restored.restore(ready));
  invalid = before;
  invalid.reserved = 1;
  assert(!restored.restore(invalid));
  static_assert(sizeof(FocusTimer::Snapshot) == 12,
                "Stable NVS snapshot format");
  std::cout << "PASS: FocusTimer elapsed time, pause/resume, one completion, "
               "rest, uint32 rollover, paused reboot snapshot and strict "
               "invalid snapshot rejection. No physical timing claim.\n";
}
