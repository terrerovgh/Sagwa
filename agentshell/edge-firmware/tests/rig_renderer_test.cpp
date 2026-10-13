#include "rig_renderer.hpp"
#include <cassert>
#include <iostream>
#include <limits>
using namespace sagwa;

int main() {
  const uint8_t transparent[] = {0, 0, 0, 0};
  const uint8_t red[] = {0, 0, 255, 255};
  const uint8_t blue[] = {255, 0, 0, 255};
  const uint8_t green[] = {0, 255, 0, 255};
  const uint8_t yellow[] = {0, 255, 255, 255};
  RigDefinition rig{"fixture", {}};
  for (auto &layer : rig.layers) layer.texture = {transparent, 4, 1, 1, 4};
  auto &closed = rig.layers[size_t(RigPart::mouth_closed)];
  closed = {{red, 4, 1, 1, 4}, 40, 40};
  auto &open = rig.layers[size_t(RigPart::mouth_open)];
  open = {{blue, 4, 1, 1, 4}, 40, 40};
  auto &pupil = rig.layers[size_t(RigPart::pupil_left)];
  pupil = {{green, 4, 1, 1, 4}, 60, 40};
  rig.layers[size_t(RigPart::lid_left)] = {{yellow, 4, 1, 1, 4}, 60, 40};
  assert(valid_rig(rig));
  std::array<uint16_t, 136 * 136> pixels{};
  Pose pose;
  render_rig(rig, pose, pixels.data());
  assert(pixels[40 * 136 + 40] == 0xf800); // Closed mouth.
  assert(pixels[40 * 136 + 60] == 0x07e0); // Independent pupil.
  pose.mouth = 1;
  render_rig(rig, pose, pixels.data());
  assert(pixels[40 * 136 + 40] == 0x001f);
  pose.blink = 0;
  render_rig(rig, pose, pixels.data());
  assert(pixels[40 * 136 + 60] == 0xffe0); // Lid replaces hidden pupil.
  pose.blink = 1;
  pose.gaze_x = 1;
  render_rig(rig, pose, pixels.data());
  assert(pixels[40 * 136 + 63] == 0x07e0);
  assert(pixels[40 * 136 + 60] == 0); // Target cleared each frame.
  auto invalid = rig;
  invalid.layers[0].texture.bytes = 3;
  assert(!valid_rig(invalid));
  invalid = rig;
  invalid.layers[0].x = std::numeric_limits<float>::quiet_NaN();
  assert(!valid_rig(invalid));
  invalid = rig;
  invalid.layers[0].texture.stride = 1;
  assert(!valid_rig(invalid));

  AnimationFSM fsm;
  SensorSnapshot sensor;
  sensor.imu = true;
  sensor.at = 1000;
  sensor.ay = 10;
  fsm.event({EventKind::speak, 1000});
  auto speaking = fsm.step(1000, sensor, {.4f, .2f, 0});
  assert(speaking.mouth > 0 && speaking.lean > 0);
  fsm.event({EventKind::cancel, 1028});
  auto stopped = fsm.step(1028, sensor, {.4f, .2f, 0});
  assert(stopped.mouth == 0 && fsm.state() == Emotion::idle);
  assert(fsm.step(2000, sensor, {}).lean == 0); // Stale IMU cannot tilt the rig.
  std::cout << "PASS: rig bounds, alpha, independent mouth/pupil/lid, playback cancel and stale IMU\n";
}
