#pragma once
#include <cstdint>
#include <string>
#include <vector>
namespace shell {
bool audio_begin();
bool listening();
bool speaking();
float audio_level();
bool pet_play(const uint8_t *,size_t);
struct AudioStatus {
  bool speaker_ready=false,last_play_ok=false;
  uint32_t received_chunks=0,rejected_chunks=0,play_failures=0;
  uint64_t received_bytes=0,queued_samples=0;
};
AudioStatus audio_status();
bool record_start();
void record_tick();
std::vector<uint8_t> record_finish();
void voice_stop();
bool speaker_chunk(const uint8_t *, size_t);
void speaker_tick();
} // namespace shell
