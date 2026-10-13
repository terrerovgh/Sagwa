#pragma once
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>

namespace sagwa {
// Frame/latency accounting shared by the SPI completion ISR, the LVGL port
// task and UI_Task. Only 32-bit lock-free atomics: no heap, locks, floating
// point or 64-bit atomics, so record()/complete() are safe in an ISR.

// Bounded latency window: power-of-two histogram, count and maximum.
// record() feeds the live window; publish() moves it to the published copy
// once per period so readers never reset data another reader still needs.
class LatencyWindow {
public:
  static constexpr size_t buckets = 16; // bucket i: [2^i, 2^(i+1)) us; 15 saturates
  struct Summary {
    uint32_t count, p50_us, p95_us, max_us;
  };
  static size_t bucket(uint32_t us) {
    size_t i = 0;
    while (us > 1 && i + 1 < buckets) {
      us >>= 1;
      ++i;
    }
    return i;
  }
  void record(uint32_t us) {
    live_[bucket(us)].fetch_add(1, std::memory_order_relaxed);
    auto maximum = live_max_.load(std::memory_order_relaxed);
    while (us > maximum &&
           !live_max_.compare_exchange_weak(maximum, us,
                                            std::memory_order_relaxed)) {
    }
  }
  // Percentiles are bucket upper bounds clamped to the observed maximum. A
  // record racing with publish() is never lost or counted twice, but its
  // bucket and maximum may land in adjacent windows.
  void publish() {
    std::array<uint32_t, buckets> counts{};
    uint32_t total = 0;
    for (size_t i = 0; i < buckets; ++i)
      total += counts[i] = live_[i].exchange(0, std::memory_order_relaxed);
    const uint32_t maximum = live_max_.exchange(0, std::memory_order_relaxed);
    count_ = total;
    max_us_ = maximum;
    p50_us_ = percentile(counts, total, 50, maximum);
    p95_us_ = percentile(counts, total, 95, maximum);
  }
  Summary summary() const {
    return {count_.load(), p50_us_.load(), p95_us_.load(), max_us_.load()};
  }

private:
  static uint32_t percentile(const std::array<uint32_t, buckets> &counts,
                             uint32_t total, uint32_t pct, uint32_t maximum) {
    if (!total)
      return 0;
    // Smallest bucket whose cumulative count reaches ceil(total * pct / 100).
    const uint32_t rank = uint32_t((uint64_t(total) * pct + 99) / 100);
    uint32_t seen = 0;
    for (size_t i = 0; i < buckets; ++i) {
      seen += counts[i];
      if (seen >= rank) {
        const uint32_t upper =
            i + 1 < buckets ? (uint32_t(2) << i) - 1 : UINT32_MAX;
        return upper < maximum ? upper : maximum;
      }
    }
    return maximum;
  }
  std::array<std::atomic<uint32_t>, buckets> live_{};
  std::atomic<uint32_t> live_max_{0};
  std::atomic<uint32_t> count_{0}, p50_us_{0}, p95_us_{0}, max_us_{0};
};

// One pending start timestamp with a separate validity flag, so every uint32
// value (including 0 and same-tick ends) is exact. Writer and reader both run
// under the BSP display lock; atomics keep the flag/timestamp pair ordered.
class PendingStamp {
public:
  // Keeps the first start until taken; returns false if one was pending.
  bool arm(uint32_t at_us) {
    if (valid_.load(std::memory_order_acquire))
      return false;
    at_us_.store(at_us, std::memory_order_relaxed);
    valid_.store(true, std::memory_order_release);
    return true;
  }
  // Consumes the pending start; elapsed uses unsigned wrap-safe subtraction.
  bool take(uint32_t now_us, uint32_t &elapsed_us) {
    if (!valid_.exchange(false, std::memory_order_acq_rel))
      return false;
    elapsed_us = now_us - at_us_.load(std::memory_order_relaxed);
    return true;
  }

private:
  std::atomic<uint32_t> at_us_{0};
  std::atomic<bool> valid_{false};
};

// Turns SPI color-transfer completions into frames. A frame may span several
// transfers; only the transfer flagged last completes it. uint32 microsecond
// timestamps wrap every ~71.6 min; unsigned subtraction keeps gaps correct.
class FrameCompletions {
public:
  struct Result {
    bool frame;
    uint32_t gap_us; // 0 for the first frame or a non-final transfer
  };
  Result complete(uint32_t now_us, bool last) {
    transfers_.fetch_add(1, std::memory_order_relaxed);
    if (!last)
      return {false, 0};
    const bool had_previous = has_previous_;
    const uint32_t gap = had_previous ? now_us - previous_us_ : 0;
    previous_us_ = now_us;
    has_previous_ = true;
    frames_.fetch_add(1, std::memory_order_relaxed);
    return {true, gap};
  }
  uint32_t frames() const { return frames_.load(std::memory_order_relaxed); }
  uint32_t transfers() const {
    return transfers_.load(std::memory_order_relaxed);
  }

private:
  // Single writer (the completion ISR); readers use the atomic counters only.
  uint32_t previous_us_ = 0;
  bool has_previous_ = false;
  std::atomic<uint32_t> frames_{0}, transfers_{0};
};

// Completed-frame rate over fixed wall-clock windows. sample() is driven by a
// periodic task, never by flush starts, so a display pause yields a closed
// window with few or zero frames instead of a stale earlier rate.
class FrameRateWindow {
public:
  explicit FrameRateWindow(uint32_t window_ms = 1000) : window_ms_(window_ms) {}
  // Returns true when a window closed and new values were published.
  bool sample(uint32_t now_ms, uint32_t frames) {
    if (!started_) {
      started_ = true;
      start_ms_ = now_ms;
      start_frames_ = frames;
      return false;
    }
    const uint32_t elapsed = now_ms - start_ms_;
    if (elapsed < window_ms_)
      return false;
    const uint32_t counted = frames - start_frames_;
    fps_milli_ = uint32_t(uint64_t(counted) * 1000000 / elapsed);
    frames_ = counted;
    elapsed_ms_ = elapsed;
    closed_at_ms_ = now_ms;
    start_ms_ = now_ms;
    start_frames_ = frames;
    return true;
  }
  uint32_t fps_milli() const { return fps_milli_.load(); }
  uint32_t frames() const { return frames_.load(); }
  uint32_t elapsed_ms() const { return elapsed_ms_.load(); }
  uint32_t closed_at_ms() const { return closed_at_ms_.load(); }
  // A window is fresh if it closed within two nominal periods of now_ms.
  bool fresh(uint32_t now_ms) const {
    const uint32_t at = closed_at_ms_.load();
    return elapsed_ms_.load() && now_ms - at <= 2 * window_ms_;
  }
  uint32_t window_ms() const { return window_ms_; }

private:
  const uint32_t window_ms_;
  // sample() has one writer (UI_Task); published values are atomics.
  bool started_ = false;
  uint32_t start_ms_ = 0, start_frames_ = 0;
  std::atomic<uint32_t> fps_milli_{0}, frames_{0}, elapsed_ms_{0},
      closed_at_ms_{0};
};
} // namespace sagwa
