#include "bsp/m5stack_core_s3.h"
#include "esp_video_device.h"
#include "esp_video_init.h"
#include "esp_video_ioctl.h"
#include "platform.hpp"
#include <fcntl.h>
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

namespace sagwa {
bool capture_requested() {
  auto &r = runtime();
  if (r.updating || r.recording || r.playing || r.camera_capturing)
    return false;
  bool expected = false;
  if (!r.camera_open.compare_exchange_strong(expected, true))
    return false;
  if (r.updating) {
    r.camera_open = false;
    return false;
  }
  const uint32_t generation = r.generation.fetch_add(1) + 1;
  if (xQueueSend(r.camera_requests, &generation, 0) == pdTRUE)
    return true;
  r.camera_open = false;
  return false;
}

// One owner of BSP camera/video resources. Never starts from a sensor event.
static bool capture_frame(std::vector<uint8_t> &pixels) {
  constexpr size_t expected = 320 * 240 * 2;
  int fd = -1;
  bool started = false, ok = false;
  void *mapped = MAP_FAILED;
  size_t mapped_size = 0;
  const int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  if (bsp_camera_start(nullptr) == ESP_OK) {
    fd = open(BSP_CAMERA_DEVICE, O_RDONLY);
    if (fd >= 0) {
      v4l2_format fmt{};
      fmt.type = type;
      fmt.fmt.pix.width = 320;
      fmt.fmt.pix.height = 240;
      fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_RGB565X;
      timeval timeout{1, 0};
      v4l2_requestbuffers req{};
      req.count = 1;
      req.type = type;
      req.memory = V4L2_MEMORY_MMAP;
      if (ioctl(fd, VIDIOC_S_FMT, &fmt) == 0 && fmt.fmt.pix.width == 320 &&
          fmt.fmt.pix.height == 240 &&
          fmt.fmt.pix.pixelformat == V4L2_PIX_FMT_RGB565X &&
          ioctl(fd, VIDIOC_S_DQBUF_TIMEOUT, &timeout) == 0 &&
          ioctl(fd, VIDIOC_REQBUFS, &req) == 0 && req.count == 1) {
        v4l2_buffer buf{};
        buf.type = type;
        buf.memory = V4L2_MEMORY_MMAP;
        if (ioctl(fd, VIDIOC_QUERYBUF, &buf) == 0 && buf.length >= expected &&
            buf.length <= 2 * expected) {
          mapped_size = buf.length;
          mapped = mmap(nullptr, mapped_size, PROT_READ | PROT_WRITE,
                        MAP_SHARED, fd, buf.m.offset);
          if (mapped != MAP_FAILED && ioctl(fd, VIDIOC_QBUF, &buf) == 0 &&
              ioctl(fd, VIDIOC_STREAMON, &type) == 0) {
            started = true;
            for (int frame = 0; frame < 4; ++frame) {
              buf = {};
              buf.type = type;
              buf.memory = V4L2_MEMORY_MMAP;
              if (ioctl(fd, VIDIOC_DQBUF, &buf) != 0)
                break;
              if (frame == 3 && !(buf.flags & V4L2_BUF_FLAG_ERROR) &&
                  buf.index == 0 && buf.bytesused == expected) {
                const auto *bytes = static_cast<const uint8_t *>(mapped);
                pixels.assign(bytes, bytes + expected);
                ok = true;
              }
              if (ioctl(fd, VIDIOC_QBUF, &buf) != 0) {
                ok = false;
                break;
              }
            }
          }
        }
      }
    }
  }
  if (started)
    ioctl(fd, VIDIOC_STREAMOFF, &type);
  if (mapped != MAP_FAILED)
    munmap(mapped, mapped_size);
  if (fd >= 0)
    close(fd);
  esp_video_deinit();
  bsp_feature_enable(BSP_FEATURE_CAMERA, false);
  if (!ok)
    pixels.clear();
  return ok;
}

void camera_task(void *) {
  auto &r = runtime();
  for (;;) {
    uint32_t generation;
    xQueueReceive(r.camera_requests, &generation, portMAX_DELAY);
    auto result = std::make_unique<CameraResult>();
    result->generation = generation;
    if (generation == r.generation && r.camera_open && !r.updating) {
      r.camera_capturing = true;
      result->pixels = std::make_shared<std::vector<uint8_t>>();
      if (!capture_frame(*result->pixels)) {
        r.camera_failures.fetch_add(1);
        result->pixels.reset();
        result->error = "No se pudo capturar la foto.";
      } else
        r.camera_captures.fetch_add(1);
      r.camera_capturing = false;
    } else
      result->error = "Captura cancelada.";
    auto *ptr = result.get();
    // A canceled capture can leave an old result; retain the newest result
    // without blocking UI or leaving its capture screen waiting forever.
    CameraResult *stale = nullptr;
    if (uxQueueSpacesAvailable(r.camera_results) == 0 &&
        xQueueReceive(r.camera_results, &stale, 0) == pdTRUE)
      delete stale;
    if (xQueueSend(r.camera_results, &ptr, 0) == pdTRUE)
      result.release();
  }
}
} // namespace sagwa
