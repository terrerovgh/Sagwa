#include "frame_metrics.hpp"
#include <cassert>
#include <iostream>
using namespace sagwa;
int main() {
  // Multi-transfer frames: only the transfer flagged last completes a frame.
  FrameCompletions completions;
  assert(!completions.complete(1000, false).frame);
  assert(!completions.complete(2000, false).frame);
  auto first = completions.complete(3000, true);
  assert(first.frame && first.gap_us == 0);
  assert(!completions.complete(20000, false).frame);
  auto second = completions.complete(31000, true);
  assert(second.frame && second.gap_us == 28000);
  assert(completions.frames() == 2 && completions.transfers() == 5);
  // uint32 microsecond wrap keeps the gap exact.
  FrameCompletions wrapped;
  wrapped.complete(UINT32_MAX - 9999, true);
  auto across = wrapped.complete(18000, true);
  assert(across.frame && across.gap_us == 28000);
  // A timestamp of zero is a valid previous frame, not "no previous frame".
  FrameCompletions zero;
  zero.complete(0, true);
  assert(zero.complete(28000, true).gap_us == 28000);

  // Periodic windows are independent of flush starts and include pauses.
  FrameRateWindow rate(1000);
  assert(!rate.sample(500, 10) && !rate.fresh(500));
  assert(!rate.sample(1499, 45));
  assert(rate.sample(1500, 46)); // 36 frames in exactly 1000 ms
  assert(rate.fps_milli() == 36000 && rate.frames() == 36);
  assert(rate.elapsed_ms() == 1000 && rate.fresh(1500));
  // Display paused: no frames, but the sampler still closes the window.
  assert(rate.sample(2500, 46) && rate.fps_milli() == 0 && rate.frames() == 0);
  // A late sampler stretches the window; the rate covers the whole interval.
  assert(rate.sample(4500, 76));
  assert(rate.elapsed_ms() == 2000 && rate.fps_milli() == 15000);
  assert(rate.fresh(6500) && !rate.fresh(6501)); // stale beyond two windows
  // Millisecond clock and frame counter wrap together.
  FrameRateWindow wrap(1000);
  wrap.sample(UINT32_MAX - 499, UINT32_MAX - 9);
  assert(wrap.sample(500, 20) && wrap.elapsed_ms() == 1000);
  assert(wrap.frames() == 30 && wrap.fps_milli() == 30000);
  assert(wrap.fresh(600));

  // Latency windows: bounded buckets, percentiles, maximum, reset on publish.
  assert(LatencyWindow::bucket(0) == 0 && LatencyWindow::bucket(1) == 0);
  assert(LatencyWindow::bucket(2) == 1 && LatencyWindow::bucket(1023) == 9);
  assert(LatencyWindow::bucket(1024) == 10);
  assert(LatencyWindow::bucket(UINT32_MAX) == LatencyWindow::buckets - 1);
  LatencyWindow latency;
  latency.publish();
  auto empty = latency.summary();
  assert(empty.count == 0 && empty.p50_us == 0 && empty.p95_us == 0 &&
         empty.max_us == 0);
  for (int i = 0; i < 95; ++i)
    latency.record(600); // bucket [512, 1023]
  for (int i = 0; i < 5; ++i)
    latency.record(5000); // bucket [4096, 8191]
  latency.publish();
  auto window = latency.summary();
  assert(window.count == 100 && window.max_us == 5000);
  assert(window.p50_us == 1023 && window.p95_us == 1023);
  latency.record(5000); // one outlier in ten puts p95 in the slow bucket
  for (int i = 0; i < 9; ++i)
    latency.record(600);
  latency.publish();
  window = latency.summary();
  assert(window.count == 10 && window.p50_us == 1023);
  assert(window.p95_us == 5000); // bucket bound clamped to observed maximum
  // Saturating bucket keeps huge stalls bounded and still reports the max.
  latency.record(UINT32_MAX);
  latency.publish();
  window = latency.summary();
  assert(window.count == 1 && window.p95_us == UINT32_MAX &&
         window.max_us == UINT32_MAX);
  latency.publish(); // empty period resets the published copy
  assert(latency.summary().count == 0 && latency.summary().max_us == 0);
  // Pending stamps: exact timestamps with a separate validity flag.
  PendingStamp stamp;
  uint32_t elapsed = 123;
  assert(!stamp.take(10, elapsed) && elapsed == 123); // nothing pending
  assert(stamp.arm(1000)); // even timestamp kept exactly
  assert(stamp.take(1000, elapsed) && elapsed == 0); // same tick, no underflow
  assert(!stamp.take(1000, elapsed));                // consumed once
  assert(stamp.arm(0) && stamp.take(0, elapsed) && elapsed == 0); // zero valid
  assert(stamp.arm(1000) && !stamp.arm(5000)); // first invalidation wins
  assert(stamp.take(1700, elapsed) && elapsed == 700);
  assert(stamp.arm(UINT32_MAX - 99) && stamp.take(400, elapsed) &&
         elapsed == 500); // uint32 microsecond wrap
  // Refresh sequence in one tick: REFR_START takes the invalidation and arms
  // its own start; REFR_READY in the same microsecond reports 0, not UINT_MAX.
  PendingStamp invalidated, started;
  LatencyWindow to_refr, render;
  invalidated.arm(2000);
  if (invalidated.take(2000, elapsed))
    to_refr.record(elapsed);
  started.arm(2000);
  if (started.take(2000, elapsed))
    render.record(elapsed);
  to_refr.publish();
  render.publish();
  assert(to_refr.summary().count == 1 && to_refr.summary().max_us == 0);
  assert(render.summary().count == 1 && render.summary().max_us == 0);
  std::cout << "PASS: frame metrics multi-transfer, pause windows, uint32 wrap, "
               "exact pending stamps, bounded latency percentiles. No hardware "
               "timing claim.\n";
}
