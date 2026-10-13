#include "esp_log.h"
#include "network.hpp"
#include "nvs.h"
#include "platform.hpp"
#include "psa/crypto.h"
#include <dirent.h>
#include <fstream>
#include <map>
namespace sagwa {
void storage_task(void *) {
  auto &r = runtime();
  if (psa_crypto_init() != PSA_SUCCESS) {
    vTaskDelete(nullptr);
    return;
  }
  std::map<std::string, std::string> versions;
  for (;;) {
    // Never commit NVS in the network/audio/UI task. A reset before this
    // checkpoint remains safe: snapshot establishes a fresh speech boundary.
    if (!shell::persist_sequence())
      ESP_LOGW("sagwa", "Event cursor checkpoint failed; retrying");
    FocusTimer::Snapshot focus;
    if (xQueueReceive(r.focus_saves, &focus, 0) == pdTRUE) {
      nvs_handle_t handle;
      if (nvs_open("sagwa_ui", NVS_READWRITE, &handle) == ESP_OK) {
        const bool saved =
            nvs_set_blob(handle, "focus", &focus, sizeof(focus)) == ESP_OK &&
            nvs_commit(handle) == ESP_OK;
        nvs_close(handle);
        if (!saved)
          ESP_LOGW("sagwa", "Focus persistence failed; timer retained in RAM");
      }
    }
    UserPreferences prefs;
    if (xQueueReceive(r.preferences, &prefs, 0) == pdTRUE) {
      nvs_handle_t handle;
      if (nvs_open("sagwa_ui", NVS_READWRITE, &handle) == ESP_OK) {
        const bool saved = nvs_set_blob(handle, "preferences", &prefs,
                                        sizeof(prefs)) == ESP_OK &&
                           nvs_commit(handle) == ESP_OK;
        nvs_close(handle);
        if (!saved)
          ESP_LOGW(
              "sagwa",
              "Preference persistence failed; in-memory settings retained");
      }
    }
    for (auto root : {r.config.storage_root, r.config.sd_root}) {
      auto *d = opendir(root.c_str());
      if (!d)
        continue;
      while (auto *entry = readdir(d)) {
        std::string filename = entry->d_name;
        if (filename.size() < 6 || filename.size() > 37 ||
            filename.substr(filename.size() - 5) != ".json")
          continue;
        if (versions.size() >= 32 && !versions.count(root + "/" + filename))
          continue;
        auto id = filename.substr(0, filename.size() - 5);
        if (id.find_first_not_of("abcdefghijklmnopqrstuvwxyz_") !=
            std::string::npos)
          continue;
        auto path = root + "/" + filename;
        std::ifstream in(path, std::ios::binary);
        if (!in)
          continue;
        char buffer[8193];
        in.read(buffer, sizeof buffer);
        if (in.gcount() > 8192)
          continue;
        uint8_t digest[32];
        size_t length = 0;
        if (psa_hash_compute(PSA_ALG_SHA_256,
                             reinterpret_cast<uint8_t *>(buffer), in.gcount(),
                             digest, sizeof digest, &length) != PSA_SUCCESS ||
            length != 32)
          continue;
        std::string hash(reinterpret_cast<char *>(digest), 32);
        if (versions.count(path) && versions[path] == hash)
          continue;
        auto *q = new Descriptor{std::string(buffer, in.gcount()), id};
        if (xQueueSend(r.reloads, &q, 0) == pdTRUE)
          versions[path] = hash;
        else
          delete q;
      }
      closedir(d);
    }
    vTaskDelay(pdMS_TO_TICKS(2000));
  }
}
} // namespace sagwa
