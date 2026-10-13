#include "cJSON.h"
#include "esp_heap_caps.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "platform.hpp"

namespace sagwa {
static void reading(cJSON *parent, const char *name, const char *unit,
                    bool available, uint32_t sampled, uint32_t ms,
                    const float *values, size_t count) {
  auto *j = cJSON_AddObjectToObject(parent, name);
  cJSON_AddBoolToObject(j, "available", available);
  cJSON_AddStringToObject(j, "unit", unit);
  const bool fresh = available && sampled && ms - sampled < 250;
  cJSON_AddNumberToObject(j, "age_s", sampled ? (ms - sampled) / 1000.0 : 0);
  if (!fresh)
    cJSON_AddNullToObject(j, "value");
  else if (count == 1)
    cJSON_AddNumberToObject(j, "value", values[0]);
  else {
    auto *array = cJSON_AddArrayToObject(j, "value");
    for (size_t i = 0; i < count; ++i)
      cJSON_AddItemToArray(array, cJSON_CreateNumber(values[i]));
  }
}
cJSON *telemetry() {
  auto &r = runtime();
  SensorSnapshot s{};
  xQueuePeek(r.sensors, &s, 0);
  const uint32_t ms = now_ms();
  auto *j = cJSON_CreateObject();
  const float acceleration[] = {s.ax, s.ay, s.az};
  reading(j, "acceleration", "g", s.imu, s.at, ms, acceleration, 3);
  reading(j, "ambient_light", "ADC counts (1x gain)", s.environment,
          s.environment_at, ms, &s.light, 1);
  reading(j, "proximity", "relative counts", s.environment, s.environment_at,
          ms, &s.proximity, 1);
  auto *power = cJSON_AddObjectToObject(j, "power");
  if (s.battery >= 0)
    cJSON_AddNumberToObject(power, "battery_pct", s.battery);
  else
    cJSON_AddNullToObject(power, "battery_pct");
  auto *runtime = cJSON_AddObjectToObject(j, "runtime");
  cJSON_AddNumberToObject(runtime, "uptime_s", esp_timer_get_time() / 1e6);
  cJSON_AddNumberToObject(runtime, "free_heap_bytes",
                          heap_caps_get_free_size(MALLOC_CAP_8BIT));
  cJSON_AddNumberToObject(runtime, "minimum_free_heap_bytes",
                          heap_caps_get_minimum_free_size(MALLOC_CAP_8BIT));
  cJSON_AddNumberToObject(
      runtime, "free_internal_heap_bytes",
      heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  cJSON_AddNumberToObject(
      runtime, "largest_internal_block_bytes",
      heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  cJSON_AddNumberToObject(runtime, "free_psram_bytes",
                          heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
  cJSON_AddNumberToObject(runtime, "reset_reason", esp_reset_reason());
  if (s.cpu >= 0)
    cJSON_AddNumberToObject(runtime, "cpu_pct", s.cpu);
  else
    cJSON_AddNullToObject(runtime, "cpu_pct");
  auto *stacks = cJSON_AddObjectToObject(runtime, "task_stack_free_bytes");
  const bool stacks_fresh = r.stack_metrics_at && ms - r.stack_metrics_at < 2500;
  for (size_t index = 0; index < measured_task_names.size(); ++index) {
    const auto bytes = r.stack_free_bytes[index].load();
    if (stacks_fresh && bytes)
      cJSON_AddNumberToObject(stacks, measured_task_names[index], bytes);
    else
      cJSON_AddNullToObject(stacks, measured_task_names[index]);
  }
  auto *ui = cJSON_AddObjectToObject(j, "ui");
  cJSON_AddNumberToObject(ui, "last_update_us", r.ui_us);
  cJSON_AddNumberToObject(ui, "lock_misses", r.ui_lock_misses);
  cJSON_AddBoolToObject(ui, "spi_completion_metrics", r.lcd_dma_metrics);
  cJSON_AddNumberToObject(ui, "completed_frames", r.lcd_frames);
  cJSON_AddNumberToObject(ui, "completed_transfers", r.lcd_transfers);
  cJSON_AddNumberToObject(ui, "last_transfer_us", r.lcd_transfer_us);
  cJSON_AddNumberToObject(ui, "max_frame_gap_us",
                          r.lcd_frame_gap_max_us.exchange(0));
  const bool fresh_frame = r.lcd_last_at_ms && ms - r.lcd_last_at_ms < 250;
  cJSON_AddNumberToObject(ui, "completed_fps",
                          fresh_frame ? r.lcd_fps_milli / 1000.0 : 0);
  auto *reaction = cJSON_AddObjectToObject(j, "reaction_timing");
  // Touch starts at FT touch delivery; sensor starts at the sampled IMU event.
  // Both end at completion of the next affected frame's last SPI transfer.
  cJSON_AddStringToObject(
      reaction, "scope",
      "delivered touch/IMU sample to last SPI transfer; excludes LCD scanout");
  cJSON_AddNumberToObject(reaction, "touch_to_lcd_ms",
                          r.touch_to_lcd_us / 1000.0);
  cJSON_AddNumberToObject(reaction, "sensor_sample_to_lcd_ms",
                          r.sensor_to_lcd_us / 1000.0);
  auto *audio = cJSON_AddObjectToObject(j, "audio");
  cJSON_AddBoolToObject(audio, "speaker_ready",
                        xEventGroupGetBits(r.flags) & audio_bit);
  cJSON_AddBoolToObject(audio, "recording", r.recording);
  cJSON_AddBoolToObject(audio, "playing", r.playing);
  cJSON_AddBoolToObject(audio, "microphone_monitoring", r.mic_monitoring);
  cJSON_AddBoolToObject(audio, "sagwa_wake_model_ready",
                        xEventGroupGetBits(r.flags) & wake_bit);
  cJSON_AddNumberToObject(audio, "written_mono_samples",
                          r.audio_written_samples);
  cJSON_AddNumberToObject(audio, "play_failures", r.audio_write_failures);
  cJSON_AddNumberToObject(audio, "wake_to_first_write_us", r.wake_audio_us);
  auto *camera = cJSON_AddObjectToObject(j, "camera");
  cJSON_AddBoolToObject(camera, "open", r.camera_open);
  cJSON_AddBoolToObject(camera, "capturing", r.camera_capturing);
  cJSON_AddNumberToObject(camera, "captures", r.camera_captures);
  cJSON_AddNumberToObject(camera, "failures", r.camera_failures);
  cJSON_AddBoolToObject(j, "boot_verified", r.boot_verified);
  return j;
}
} // namespace sagwa
