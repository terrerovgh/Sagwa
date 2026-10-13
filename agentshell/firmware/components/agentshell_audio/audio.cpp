// The main HAL owner calls these routines; native M5 tasks own only their I2S
// buffers.
#include "audio.hpp"
#include "M5Unified.h"
#include "esp_heap_caps.h"
#include <cstring>
#include <deque>
#include <cmath>
namespace shell {
static int16_t *pcm;
static size_t used;
static bool recording, pending,pet_audio;
static float level;
static int16_t block[320];
static std::deque<std::vector<int16_t>> speech;
static std::vector<int16_t> playing;
static AudioStatus status;
AudioStatus audio_status(){return status;}
bool audio_begin() {
  pcm = static_cast<int16_t *>(
      heap_caps_malloc(16000 * 8 * 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  auto c = M5.Mic.config();
  c.sample_rate = 16000;
  M5.Mic.config(c);
  M5.Speaker.setVolume(110);
  status.speaker_ready=M5.Speaker.begin();
  return pcm != nullptr && status.speaker_ready;
}
bool listening() { return recording; }
bool speaking() { return !pet_audio&&(M5.Speaker.isPlaying() || !speech.empty()); }
float audio_level(){return !pet_audio&&M5.Speaker.isPlaying()?level:0;}
bool pet_play(const uint8_t *data,size_t size){if(recording||speaking()||M5.Speaker.isPlaying()||size%2||size>64000)return false;playing.resize(size/2);memcpy(playing.data(),data,size);pet_audio=true;return M5.Speaker.playRaw(playing.data(),playing.size(),16000,false,1,0,false);}
bool record_start() {
  if (!pcm || recording)
    return false;
  voice_stop();
  M5.Speaker.end();
  status.speaker_ready=false;
  if (!M5.Mic.begin())
    return false;
  used = 0;
  pending = false;
  recording = true;
  return true;
}
void record_tick() {
  if (!recording)
    return;
  if (pending && !M5.Mic.isRecording()) {
    if (used + 320 <= 16000 * 8) {
      memcpy(pcm + used, block, sizeof(block));
      used += 320;
    }
    pending = false;
  }
  if (!pending && used + 320 <= 16000 * 8)
    pending = M5.Mic.record(block, 320, 16000, false);
}
std::vector<uint8_t> record_finish() {
  if (!recording)
    return {};
  M5.Mic.end();
  recording = false;
  pending = false;
  status.speaker_ready=M5.Speaker.begin();
  auto *bytes = reinterpret_cast<uint8_t *>(pcm);
  return std::vector<uint8_t>(bytes, bytes + used * 2);
}
void voice_stop() {
  pet_audio=false;level=0;
  M5.Speaker.stop();
  M5.Speaker.end();
  status.speaker_ready=false;
  speech.clear();
  playing.clear();
  if (!recording)
    status.speaker_ready=M5.Speaker.begin();
}
bool speaker_chunk(const uint8_t *data, size_t size) {
  if (recording || size % 2 || size > 8192 || speech.size() >= 512){status.rejected_chunks++;return false;}
  std::vector<int16_t> chunk(size / 2);
  memcpy(chunk.data(), data, size);
  speech.push_back(std::move(chunk));
  status.received_chunks++;status.received_bytes+=size;
  return true;
}
void speaker_tick() {
  if (recording)
    return;
  if (!M5.Speaker.isPlaying()) {
    playing.clear();pet_audio=false;level=0;
    if (!speech.empty()) {
      playing = std::move(speech.front());
      speech.pop_front();
      double energy=0;for(auto n:playing)energy+=double(n)*n;level=playing.empty()?0:std::sqrt(energy/playing.size())/32768;
      status.last_play_ok=M5.Speaker.playRaw(playing.data(), playing.size(), 16000, false, 1, 0,false);
      status.speaker_ready=status.last_play_ok;
      if(status.last_play_ok)status.queued_samples+=playing.size();else status.play_failures++;
    }
  }
}
} // namespace shell
