#include "lvgl.h"
#include "platform.hpp"
#include "network.hpp"
#include <ctime>
namespace sagwa {
extern "C" const lv_font_t inter16;
class ClockPlugin final : public SagwaPluginInterface {
  lv_obj_t *label_ = nullptr;
  uint32_t refreshed_ = 0;

public:
  const char *type() const override { return "clock"; }
  void mount(void *parent, const Widget &w) override {
    label_ = lv_label_create(static_cast<lv_obj_t *>(parent));
    lv_obj_set_pos(label_, w.x, w.y);
    lv_obj_set_size(label_, w.w, w.h);
    lv_obj_set_style_text_font(label_, &inter16, 0);
    lv_obj_set_style_text_color(label_, lv_color_white(), 0);
    lv_label_set_text(label_, "Esperando hora verificada…");
  }
  void update(const SensorSnapshot &, const std::array<float, 3> &,
              uint32_t ms) override {
    if (!label_ || ms - refreshed_ < 1000)
      return;
    refreshed_ = ms;
    auto now = time(nullptr);
    if (!shell::time_synchronized())
      return;
    tm utc{};
    gmtime_r(&now, &utc);
    char text[32];
    strftime(text, sizeof text, "UTC %H:%M:%S", &utc);
    lv_label_set_text(label_, text);
  }
  void unmount() override {
    if (label_)
      lv_obj_delete(label_);
    label_ = nullptr;
  }
  ~ClockPlugin() { unmount(); }
};
void register_clock() {
  register_plugin("clock", [] { return std::make_unique<ClockPlugin>(); });
}
} // namespace sagwa
