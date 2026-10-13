#include "cJSON.h"
#include "esp_heap_caps.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "ota.hpp"
#include "platform.hpp"

namespace sagwa {
void maintenance_task(void *) {
  auto &r = runtime();
  const uint32_t started = now_ms();
  for (;;) {
    if (!r.boot_verified && now_ms() - started >= 30000) {
      const bool healthy =
          r.ui_ready && r.lcd_dma_metrics && r.lcd_completions.frames() > 0 &&
          (xEventGroupGetBits(r.flags) & audio_bit) &&
          heap_caps_get_free_size(MALLOC_CAP_INTERNAL) >= 24000;
      if (shell::confirm_local_boot(healthy))
        r.boot_verified = true;
    }
    UpdateOffer *offer = nullptr;
    if (xQueueReceive(r.updates, &offer, pdMS_TO_TICKS(250)) != pdTRUE)
      continue;
    std::unique_ptr<UpdateOffer> own(offer);
    if (!r.boot_verified || r.recording || r.playing || r.camera_open ||
        r.camera_capturing || r.updating || !r.provisioned)
      continue;
    if (!json_shape_safe(offer->json, 6144, 8))
      continue;
    auto *payload = cJSON_Parse(offer->json.c_str());
    if (!payload)
      continue;
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> json(payload, cJSON_Delete);
    if (shell::ota_is_current(payload) || shell::ota_attempted(payload))
      continue;
    r.updating = true;
    if (r.recording || r.playing || r.camera_open || r.camera_capturing) {
      r.updating = false;
      continue;
    }
    const uint32_t generation = r.generation.fetch_add(1) + 1;
    audio_send(new AudioCommand{AudioCommand::stop, generation, {}});
    post_turn(EventKind::work, generation);
    ui_reply(new Reply{generation, "Verificando actualización firmada."});
    const bool installed = shell::install_ota(payload, r.provision);
    if (installed)
      esp_restart();
    r.updating = false;
    ui_reply(new Reply{generation, "", "",
                       "Actualización rechazada. Sagwa sigue disponible."});
    post_turn(EventKind::offline, generation);
  }
}
} // namespace sagwa
