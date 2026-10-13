#include "bsp/m5stack_core_s3.h"
#include "esp_codec_dev.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_partition.h"
#include "esp_timer.h"
#include "esp_wn_models.h"
#include "model_path.h"
#include "platform.hpp"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <deque>
namespace sagwa {
extern const uint8_t meow_start[] asm("_binary_meow_pcm_start");
extern const uint8_t meow_end[] asm("_binary_meow_pcm_end");
extern const uint8_t ack_start[] asm("_binary_ack_pcm_start");
extern const uint8_t ack_end[] asm("_binary_ack_pcm_end");
extern const uint8_t complaint_start[] asm("_binary_complaint_pcm_start");
extern const uint8_t complaint_end[] asm("_binary_complaint_pcm_end");
extern const uint8_t purr_start[] asm("_binary_purr_pcm_start");
extern const uint8_t purr_end[] asm("_binary_purr_pcm_end");
class WakeDetector {
  srmodel_list_t *models_ = nullptr;
  const esp_wn_iface_t *iface_ = nullptr;
  model_iface_data_t *model_ = nullptr;
  std::vector<int16_t> frame_;
  size_t used_ = 0;

public:
  ~WakeDetector() {
    if (model_)
      iface_->destroy(model_);
    if (models_)
      esp_srmodel_deinit(models_);
  }
  bool begin(const RuntimeConfig &cfg) {
    if (!cfg.wake_enabled || cfg.wake_model_sha256.size() != 64)
      return false;
    auto *partition = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_SPIFFS, "model");
    uint8_t digest[32];
    if (!partition || esp_partition_get_sha256(partition, digest) != ESP_OK)
      return false;
    char hex[65];
    for (int i = 0; i < 32; i++)
      snprintf(hex + i * 2, 3, "%02x", digest[i]);
    if (cfg.wake_model_sha256 != hex)
      return false;
    models_ = esp_srmodel_init("model");
    if (!models_)
      return false;
    for (int i = 0; i < models_->num; ++i) {
      auto *name = models_->model_name[i];
      if (strncmp(name, ESP_WN_PREFIX, 2))
        continue;
      auto *iface = esp_wn_handle_from_name(name);
      if (!iface)
        continue;
      auto *m = iface->create(name, DET_MODE_90);
      if (!m)
        continue;
      bool exact = false;
      for (int word = 1; word <= iface->get_word_num(m); ++word) {
        auto *w = iface->get_word_name(m, word);
        exact |= w && cfg.wake_word == w;
      }
      if (exact && iface->get_word_num(m) == 1 &&
          iface->get_samp_rate(m) == 16000 && iface->get_channel_num(m) == 1) {
        auto n = iface->get_samp_chunksize(m);
        if (n > 0 && n <= 2048) {
          iface_ = iface;
          model_ = m;
          frame_.resize(n);
          return true;
        }
      }
      iface->destroy(m);
    }
    esp_srmodel_deinit(models_);
    models_ = nullptr;
    ESP_LOGW("sagwa_audio",
             "No matching Sagwa wake model; PWR remains available");
    return false;
  }
  bool feed(const int16_t *s, size_t n) {
    if (!model_)
      return false;
    bool detected = false;
    for (size_t i = 0; i < n; ++i) {
      frame_[used_++] = s[i];
      if (used_ == frame_.size()) {
        detected |= iface_->detect(model_, frame_.data()) == WAKENET_DETECTED;
        used_ = 0;
      }
    }
    return detected;
  }
};
static std::vector<uint8_t> wav(const std::vector<uint8_t> &pcm) {
  std::vector<uint8_t> out(44 + pcm.size());
  auto set16 = [&](int n, uint16_t v) {
    out[n] = v;
    out[n + 1] = v >> 8;
  };
  auto set32 = [&](int n, uint32_t v) {
    set16(n, v);
    set16(n + 2, v >> 16);
  };
  memcpy(out.data(), "RIFF", 4);
  set32(4, 36 + pcm.size());
  memcpy(out.data() + 8, "WAVEfmt ", 8);
  set32(16, 16);
  set16(20, 1);
  set16(22, 1);
  set32(24, 16000);
  set32(28, 32000);
  set16(32, 2);
  set16(34, 16);
  memcpy(out.data() + 36, "data", 4);
  set32(40, pcm.size());
  memcpy(out.data() + 44, pcm.data(), pcm.size());
  return out;
}
void audio_task(void *) {
  auto &r = runtime();
  i2s_std_config_t cfg{};
  cfg.clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(16000);
  cfg.slot_cfg = I2S_STD_PHILIP_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,
                                                    I2S_SLOT_MODE_STEREO);
  cfg.gpio_cfg.mclk = BSP_I2S_MCLK;
  cfg.gpio_cfg.bclk = BSP_I2S_SCLK;
  cfg.gpio_cfg.ws = BSP_I2S_LCLK;
  cfg.gpio_cfg.dout = BSP_I2S_DOUT;
  cfg.gpio_cfg.din = BSP_I2S_DSIN;
  if (bsp_audio_init(&cfg) != ESP_OK) {
    post(EventKind::offline);
    vTaskDelete(nullptr);
    return;
  }
  auto *mic = bsp_audio_codec_microphone_init();
  auto *speaker = bsp_audio_codec_speaker_init();
  esp_codec_dev_sample_info_t sample{};
  sample.sample_rate = 16000;
  sample.channel = 2;
  sample.bits_per_sample = 16;
  if (!mic || !speaker ||
      esp_codec_dev_open(mic, &sample) != ESP_CODEC_DEV_OK ||
      esp_codec_dev_open(speaker, &sample) != ESP_CODEC_DEV_OK) {
    post(EventKind::offline);
    vTaskDelete(nullptr);
    return;
  }
  esp_codec_dev_set_in_gain(mic, 24);
  esp_codec_dev_set_out_vol(speaker, 25);
  xEventGroupSetBits(r.flags, audio_bit);
  WakeDetector wake;
  if (wake.begin(r.config))
    xEventGroupSetBits(r.flags, wake_bit);
  std::array<int16_t, 640> stereo{}, out{};
  std::array<int16_t, 320> mono{};
  std::array<float, 3> playback_bands{}, microphone_bands{};
  std::vector<uint8_t> recorded;
  recorded.reserve(320000);
  const uint8_t *sfx = nullptr;
  size_t sfx_n = 0, sfx_pos = 0;
  bool loop = false, auto_record = false, auto_start = false;
  uint32_t record_ms = 0, purr_until = 0, last_spontaneous = 0, last_wake = 0,
           play_generation = 0;
  std::unique_ptr<AudioCommand> stream;
  std::deque<std::unique_ptr<AudioCommand>> pending;
  bool stream_ended = false;
  uint32_t pcm_at = 0, noise_at = 0;
  unsigned read_failures = 0;
  uint32_t audio_generation = r.generation, handled_audio_stop = 0;
  auto finish = [&] {
    r.recording = false;
    if (recorded.size() < 3200) {
      post_turn(EventKind::done, audio_generation);
      return;
    }
    auto *q = new Routed;
    q->request.audio = true;
    q->request.generation = audio_generation;
    q->request.preference = r.preference;
    if (!apply_request_context(q->request)) {
      delete q;
      ui_reply(new Reply{audio_generation, "", "",
                         "Destino ocupado. Inténtalo de nuevo."});
      return;
    }
    q->audio = wav(recorded); // Audio_Request goes to Router_Task; network not
                              // opened here.
    if (xQueueSend(r.requests, &q, 0) != pdTRUE)
      delete q;
    post_turn(EventKind::think, audio_generation);
  };
  auto finish_clip = [&] {
    if (loop) {
      sfx_pos = 0;
    } else {
      sfx = nullptr;
      stream.reset();
      if (auto_start) {
        auto_start = false;
        auto_record = true;
        r.recording = true;
        record_ms = now_ms();
        recorded.clear();
        post_turn(EventKind::listen, audio_generation);
      }
    }
  };
  auto fail_playback = [&] {
    r.audio_write_failures.fetch_add(1);
    r.failed_audio_generation = audio_generation;
    r.audio_fault = true;
    pending.clear();
    stream.reset();
    sfx = nullptr;
    loop = false;
    r.playing = false;
    stream_ended = false;
    auto_start = false;
    post_turn(EventKind::offline, audio_generation);
  };
  for (;;) {
    auto ms = now_ms();
    if (audio_generation != r.generation) {
      audio_generation = r.generation;
      pending.clear();
      stream.reset();
      sfx = nullptr;
      r.playing = false;
      r.recording = false;
      stream_ended = false;
      auto_start = false;
      recorded.clear();
    }
    if (r.stopped_audio_generation == audio_generation &&
        handled_audio_stop != r.audio_stop_revision) {
      handled_audio_stop = r.audio_stop_revision;
      pending.clear();
      stream.reset();
      sfx = nullptr;
      r.playing = false;
      stream_ended = false;
      auto_start = false;
    }
    AudioCommand *cmd = nullptr;
    // Leave commands in the bounded producer queue until playback has room.
    // Generation changes purge pending audio before this loop.
    while (pending.size() < 32 && xQueueReceive(r.audio, &cmd, 0) == pdTRUE) {
      std::unique_ptr<AudioCommand> own(cmd);
      if (cmd->generation != r.generation)
        continue;
      if ((r.updating || r.camera_open) && cmd->kind != AudioCommand::stop)
        continue;
      // Old queued PCM cannot resume after an I2S/clip/starvation failure.
      // Fresh PWR/wake controls use a new generation and remain actionable.
      if ((cmd->kind == AudioCommand::pcm ||
           cmd->kind == AudioCommand::end_stream) &&
          (cmd->generation == r.failed_audio_generation ||
           cmd->generation == r.stopped_audio_generation))
        continue;
      if (cmd->kind == AudioCommand::stop) {
        pending.clear();
        stream.reset();
        sfx = nullptr;
        r.playing = false;
        stream_ended = false;
        if (r.recording) {
          recorded.clear();
          r.recording = false;
        }
        auto_start = false;
      } else if (cmd->kind == AudioCommand::record_begin) {
        pending.clear();
        stream.reset();
        sfx = nullptr;
        r.playing = false;
        stream_ended = false;
        recorded.clear();
        r.recording = true;
        auto_record = false;
        record_ms = ms;
        post_turn(EventKind::listen, audio_generation);
      } else if (cmd->kind == AudioCommand::record_end && r.recording) {
        finish();
      } else if (cmd->kind == AudioCommand::pcm) {
        if (!r.recording && !cmd->bytes.empty() && cmd->bytes.size() <= 4096 &&
            cmd->bytes.size() % 2 == 0) {
          if (!stream) {
            sfx = nullptr;
            loop = false;
          }
          pending.push_back(std::move(own));
          pcm_at = ms;
          r.playing = true;
          stream_ended = false;
          post_turn(EventKind::speak, audio_generation);
        } else if (!r.recording) {
          fail_playback();
        }
      } else if (cmd->kind == AudioCommand::end_stream)
        stream_ended = true;
      else if (!r.recording && !r.playing && r.sound_enabled) {
        if (cmd->kind == AudioCommand::purr) {
          if (!sfx) {
            sfx = purr_start;
            sfx_n = purr_end - purr_start;
            sfx_pos = 0;
            loop = true;
          }
          purr_until = ms + 300;
        } else if (cmd->kind == AudioCommand::ack ||
                   ms - last_spontaneous >= 5000) {
          sfx = cmd->kind == AudioCommand::complaint ? complaint_start
                                                     : ack_start;
          sfx_n = cmd->kind == AudioCommand::complaint
                      ? complaint_end - complaint_start
                      : ack_end - ack_start;
          sfx_pos = 0;
          loop = false;
          last_spontaneous = ms;
        }
        play_generation = r.generation;
      }
    }
    if (!sfx && !pending.empty()) {
      stream = std::move(pending.front());
      pending.pop_front();
      sfx = stream->bytes.data();
      sfx_n = stream->bytes.size();
      sfx_pos = 0;
      loop = false;
      play_generation = stream->generation;
    }
    if (r.playing && !sfx && pending.empty() && ms - pcm_at > 3000) {
      fail_playback();
    }
    if (r.playing && stream_ended && !sfx && pending.empty()) {
      r.playing = false;
      stream_ended = false;
      post_turn(EventKind::done, audio_generation);
    }
    if (sfx && (play_generation != r.generation ||
                (loop && int32_t(ms - purr_until) >= 0) || r.recording)) {
      sfx = nullptr;
      stream.reset();
      r.playing = false;
    }
    if (sfx) {
      if (!sfx_n || sfx_n % 2 || sfx_pos % 2 || sfx_pos > sfx_n) {
        fail_playback();
        vTaskDelay(pdMS_TO_TICKS(20));
        continue;
      }
      if (sfx_pos == sfx_n) {
        finish_clip(); // Includes an ACK consumed by the first wake write.
        vTaskDelay(pdMS_TO_TICKS(1));
        continue;
      }
      size_t n = std::min<size_t>(320, (sfx_n - sfx_pos) / 2);
      spectrum(reinterpret_cast<const int16_t *>(sfx + sfx_pos), n,
               playback_bands);
      if (xSemaphoreTake(r.bands_mutex, 0) == pdTRUE) {
        r.bands = playback_bands;
        xSemaphoreGive(r.bands_mutex);
      }
      for (size_t i = 0; i < n; i++) {
        int16_t value;
        memcpy(&value, sfx + sfx_pos + i * 2, 2);
        out[i * 2] = out[i * 2 + 1] = value;
      }
      if (esp_codec_dev_write(speaker, out.data(), n * 4) != ESP_CODEC_DEV_OK) {
        fail_playback();
        vTaskDelay(pdMS_TO_TICKS(20));
        continue;
      }
      sfx_pos += n * 2;
      r.audio_written_samples.fetch_add(n);
      if (sfx_pos >= sfx_n) {
        finish_clip();
      }
      continue;
    }
    const bool monitor =
        !r.updating && !r.camera_open &&
        ((xEventGroupGetBits(r.flags) & wake_bit) || r.sentinel_enabled);
    r.mic_monitoring = monitor && !r.recording && !r.playing;
    if (!r.recording && !monitor) {
      r.mic_monitoring = false;
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }
    if (esp_codec_dev_read(mic, stereo.data(), stereo.size() * 2) !=
        ESP_CODEC_DEV_OK) {
      if (++read_failures >= 5 && r.recording) {
        recorded.clear();
        r.recording = false;
        post_turn(EventKind::offline, audio_generation);
      }
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }
    read_failures = 0;
    for (size_t i = 0; i < mono.size(); i++)
      mono[i] = (int32_t(stereo[i * 2]) + stereo[i * 2 + 1]) / 2;
    if (!r.playing)
      spectrum(mono.data(), mono.size(), microphone_bands);
    if (xSemaphoreTake(r.bands_mutex, 0) == pdTRUE) {
      r.bands = r.playing ? std::array<float, 3>{} : microphone_bands;
      xSemaphoreGive(r.bands_mutex);
    }
    if (r.sentinel_enabled && !r.recording && !r.playing &&
        ms - noise_at > 5000) {
      float energy = 0;
      for (auto sample : mono) {
        float v = sample / 32768.f;
        energy += v * v;
      }
      if (std::sqrt(energy / mono.size()) > .22f) {
        post_turn(EventKind::shake, audio_generation);
        noise_at = ms; // Visual-only noise reaction: no sockets or submit.
      }
    }
    if (r.recording && ms - record_ms < 100)
      continue;
    if (r.recording) {
      auto *bytes = reinterpret_cast<uint8_t *>(mono.data());
      size_t n = std::min<size_t>(mono.size() * 2, 320000 - recorded.size());
      recorded.insert(recorded.end(), bytes, bytes + n);
      if (recorded.size() >= 320000 || (auto_record && ms - record_ms >= 5000))
        finish();
    } else if (!r.playing && ms - last_wake > 2500 &&
               wake.feed(mono.data(), mono.size())) {
      last_wake = ms;
      r.generation.fetch_add(1);
      audio_generation = r.generation;
      post_turn(EventKind::wake, audio_generation);
      auto detected = esp_timer_get_time();
      sfx_n = ack_end - ack_start;
      if (r.sound_enabled && sfx_n >= 640 && sfx_n % 2 == 0) {
        sfx = ack_start;
        sfx_pos = 0;
        loop = false;
        play_generation = audio_generation;
        auto_start = true; // First bounded block before any network work.
        for (size_t i = 0; i < 320; i++) {
          int16_t v;
          memcpy(&v, sfx + i * 2, 2);
          out[i * 2] = out[i * 2 + 1] = v;
        }
        if (esp_codec_dev_write(speaker, out.data(), 1280) ==
            ESP_CODEC_DEV_OK) {
          sfx_pos = 640;
          r.wake_audio_us = esp_timer_get_time() - detected;
          r.audio_written_samples.fetch_add(320);
        } else {
          fail_playback();
        }
      } else {
        sfx = nullptr;
        auto_start = false;
        auto_record = true;
        r.recording = true;
        record_ms = now_ms();
        recorded.clear();
        post_turn(EventKind::listen, audio_generation);
      }
    }
  }
}
} // namespace sagwa
