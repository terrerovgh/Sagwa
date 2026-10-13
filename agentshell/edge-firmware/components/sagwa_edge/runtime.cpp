#include "bsp/m5stack_core_s3.h"
#include "cJSON.h"
#include "driver/i2c_master.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_spiffs.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "platform.hpp"
#include "sensor_event.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>
namespace sagwa {
static Runtime rt;
static std::atomic<float> measured_cpu{-1}, ambient{0}, proximity{0};
static std::atomic<int> battery{-1};
static std::atomic<uint32_t> environment_at{0};
Runtime &runtime() { return rt; }
uint32_t now_ms() { return uint32_t(esp_timer_get_time() / 1000); }
void post(EventKind k, float x, float y, float value) {
  post_turn(k, rt.generation.load(), x, y, value);
}
void post_turn(EventKind k, uint32_t generation, float x, float y,
               float value) {
  Event e{k, now_ms(), x, y, value, generation};
  xQueueSend(rt.events, &e, 0);
}
bool audio_send(AudioCommand *q) {
  if (xQueueSend(rt.audio, &q, 0) == pdTRUE)
    return true;
  delete q;
  return false;
}
bool decide(Decision *q) {
  if (xQueueSend(rt.decisions, &q, 0) == pdTRUE)
    return true;
  delete q;
  return false;
}
void ui_reply(Reply *q) {
  if (xQueueSend(rt.replies, &q, 0) != pdTRUE)
    delete q;
}
bool submit(Request *q) {
  auto *r = new Routed;
  r->request = std::move(*q);
  delete q;
  if (xQueueSend(rt.requests, &r, 0) == pdTRUE)
    return true;
  delete r;
  return false;
}
bool apply_request_context(Request &q) {
  if (xSemaphoreTake(rt.status_mutex, pdMS_TO_TICKS(20)) == pdTRUE) {
    q.target = rt.selected_target;
    q.capability = rt.selected_capability;
    q.tools = q.capability != "conversation";
    xSemaphoreGive(rt.status_mutex);
    return true;
  }
  return false;
}
void save_preferences() {
  UserPreferences prefs;
  prefs.routing = uint8_t(rt.preference.load());
  prefs.voice = rt.voice_enabled;
  prefs.pet = rt.pet_enabled;
  prefs.sounds = rt.pet_sounds;
  prefs.sensors = rt.pet_sensors;
  const auto &skin =
      rt.pending_skin_id.empty() ? rt.skins.current().id : rt.pending_skin_id;
  snprintf(prefs.skin, sizeof(prefs.skin), "%s", skin.c_str());
  if (xSemaphoreTake(rt.status_mutex, pdMS_TO_TICKS(5)) == pdTRUE) {
    snprintf(prefs.target, sizeof(prefs.target), "%s",
             rt.selected_target.c_str());
    snprintf(prefs.capability, sizeof(prefs.capability), "%s",
             rt.selected_capability.c_str());
    xSemaphoreGive(rt.status_mutex);
    xQueueOverwrite(rt.preferences, &prefs);
    rt.preferences_dirty = true;
  }
}
void save_focus() {
  const auto snapshot = rt.focus.snapshot(now_ms());
  xQueueOverwrite(rt.focus_saves, &snapshot);
}
static void imu_handler(void *, esp_event_base_t, int32_t id, void *data) {
  if (id != SENSOR_ACCE_DATA_READY)
    return;
  auto *s = static_cast<sensor_data_t *>(data);
  SensorSnapshot out;
  out.imu = true;
  out.at = now_ms();
  out.ax = s->acce.x;
  out.ay = s->acce.y;
  out.az = s->acce.z;
  out.heap = esp_get_free_heap_size();
  out.cpu = measured_cpu;
  out.battery = battery;
  out.light = ambient;
  out.proximity = proximity;
  out.environment_at = environment_at;
  out.environment = out.environment_at && now_ms() - out.environment_at < 250;
  wifi_ap_record_t ap{};
  if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK)
    out.rssi = ap.rssi;
  xQueueOverwrite(rt.sensors, &out);
}
void sensor_task(void *) {
  sensor_handle_t handle = nullptr;
  bsp_sensor_config_t cfg{};
  cfg.type = IMU_ID;
  cfg.mode = MODE_POLLING;
  cfg.period = 20;
  // The vendor hub helper asserts on allocation failure. Register through
  // its fallible public event API instead; absent IMU must not reboot UI.
  const bool imu_started =
      bsp_sensor_init(&cfg, &handle) == ESP_OK &&
      sensors_event_handler_instance_register(
          ESP_EVENT_ANY_BASE, ESP_EVENT_ANY_ID, imu_handler, nullptr,
          nullptr) == ESP_OK &&
      iot_sensor_start(handle) == ESP_OK;
  if (!imu_started)
    ESP_LOGW("sagwa", "IMU unavailable; environment and PWR retained");
  auto pmu = bsp_pmu_get_handle(); // BSP owns the sole PMU device.
  i2c_device_config_t ic{};
  ic.dev_addr_length = I2C_ADDR_BIT_LEN_7;
  ic.scl_speed_hz = 100000;
  auto read = [&](uint8_t reg, uint8_t &out) {
    return pmu &&
           i2c_master_transmit_receive(pmu, &reg, 1, &out, 1, 25) == ESP_OK;
  };
  auto write = [&](uint8_t reg, uint8_t value) {
    uint8_t bytes[] = {reg, value};
    return pmu && i2c_master_transmit(pmu, bytes, 2, 25) == ESP_OK;
  };
  i2c_master_dev_handle_t light_dev = nullptr;
  ic.device_address = 0x23;
  i2c_master_bus_add_device(bsp_i2c_get_handle(), &ic, &light_dev);
  uint8_t identity = 0, reg = 0x87;
  bool light_ok = light_dev &&
                  i2c_master_transmit_receive(light_dev, &reg, 1, &identity, 1,
                                              25) == ESP_OK &&
                  identity == 5;
  if (light_ok) {
    for (auto item :
         {std::pair<uint8_t, uint8_t>{0x80, 1}, {0x81, 3}, {0x82, 0x6b}}) {
      uint8_t bytes[] = {item.first, item.second};
      i2c_master_transmit(light_dev, bytes, 2, 25);
    }
  }
  uint32_t last_metrics = 0, last_environment = 0, dark_since = 0,
           bright_since = 0;
  bool near = false, dark = false;
  uint32_t prior_idle = 0, prior_total = 0;
  uint8_t irqs = 0;
  if (read(0x41, irqs))
    write(0x41, irqs | 3);
  float ax = 0, ay = 0, az = 1;
  uint32_t last_reaction = 0;
  bool key_down = false;
  for (;;) {
    uint32_t ms = now_ms();
    if (ms - last_metrics >= 1000) {
      last_metrics = ms;
      uint8_t bat = 0;
      if (read(0xA4, bat))
        battery = bat <= 100 ? bat : -1;
#if CONFIG_FREERTOS_GENERATE_RUN_TIME_STATS &&                                 \
    CONFIG_FREERTOS_USE_TRACE_FACILITY
      static TaskStatus_t tasks[64];
      configRUN_TIME_COUNTER_TYPE total = 0;
      auto count = uxTaskGetSystemState(tasks, 64, &total);
      for (auto &watermark : rt.stack_free_bytes)
        watermark = 0;
      for (UBaseType_t i = 0; i < count; ++i)
        for (size_t index = 0; index < measured_task_names.size(); ++index)
          if (!strcmp(tasks[i].pcTaskName, measured_task_names[index]))
            rt.stack_free_bytes[index] = tasks[i].usStackHighWaterMark;
      rt.stack_metrics_at = count ? ms : 0;
      uint32_t idle = 0;
      for (UBaseType_t i = 0; i < count; i++)
        if (tasks[i].xHandle == xTaskGetIdleTaskHandleForCore(0) ||
            tasks[i].xHandle == xTaskGetIdleTaskHandleForCore(1))
          idle += tasks[i].ulRunTimeCounter;
      if (count && prior_total && uint32_t(total) != prior_total) {
        float ratio =
            float(idle - prior_idle) / (2.f * uint32_t(total - prior_total));
        measured_cpu = std::max(0.f, std::min(100.f, 100 * (1 - ratio)));
      }
      prior_idle = idle;
      prior_total = total;
#endif
    }
    if (light_ok && ms - last_environment >= 100) {
      last_environment = ms;
      uint8_t raw[7]{};
      reg = 0x88;
      if (i2c_master_transmit_receive(light_dev, &reg, 1, raw, 7, 25) ==
          ESP_OK) {
        ambient = raw[2] + 256 * raw[3];
        proximity = raw[5] + 256 * (raw[6] & 7);
        environment_at = ms;
        bool conversation =
            rt.recording || rt.playing || !rt.pet_enabled || !rt.pet_sensors;
        if (proximity > 300 && !near) {
          near = true;
          if (!conversation && ms - last_reaction > 5000) {
            post(EventKind::wake);
            last_reaction = ms;
          }
        } else if (proximity < 180)
          near = false;
        if (ambient < 12) {
          bright_since = 0;
          if (!dark_since)
            dark_since = ms;
          if (!dark && !conversation && ms - dark_since > 20000) {
            post(EventKind::sleep);
            dark = true;
          }
        } else if (ambient > 35) {
          dark_since = 0;
          if (!bright_since)
            bright_since = ms;
          if (dark && ms - bright_since > 500) {
            post(EventKind::wake);
            dark = false;
          }
        }
      } else
        environment_at = 0;
    }
    SensorSnapshot s;
    if (xQueuePeek(rt.sensors, &s, 0) == pdTRUE && s.imu && ms - s.at < 250) {
      float delta = std::sqrt(std::pow(s.ax - ax, 2) + std::pow(s.ay - ay, 2) +
                              std::pow(s.az - az, 2));
      ax = ax * .85f + s.ax * .15f;
      ay = ay * .85f + s.ay * .15f;
      az = az * .85f + s.az * .15f;
      if (ms - last_reaction > 5000 && !rt.recording && !rt.playing &&
          rt.pet_enabled && rt.pet_sensors) {
        if (delta > 2.4f) {
          post(EventKind::shake);
          audio_send(
              new AudioCommand{AudioCommand::complaint, rt.generation, {}});
          last_reaction = ms;
        } else if (std::abs(ay) > .65f) {
          post(EventKind::tilt);
          last_reaction = ms;
        }
      }
    }
    // Telemetry remains useful when the IMU is absent. Its timestamp still
    // identifies only the last real accelerometer sample, never synthetic data.
    if (ms % 100 < 20) {
      SensorSnapshot snapshot;
      xQueuePeek(rt.sensors, &snapshot, 0);
      if (ms - snapshot.at >= 250)
        snapshot.imu = false;
      snapshot.heap = esp_get_free_heap_size();
      snapshot.cpu = measured_cpu;
      snapshot.battery = battery;
      snapshot.light = ambient;
      snapshot.proximity = proximity;
      snapshot.environment_at = environment_at;
      snapshot.environment =
          snapshot.environment_at && ms - snapshot.environment_at < 250;
      wifi_ap_record_t ap{};
      snapshot.rssi = esp_wifi_sta_get_ap_info(&ap) == ESP_OK ? ap.rssi : -127;
      xQueueOverwrite(rt.sensors, &snapshot);
    }
    uint8_t state = 0;
    if (read(0x49, state) && (state & 3)) {
      write(0x49,
            state & 3); // Clear only PWR edge IRQs; preserve other PMU status.
      if (rt.updating || rt.camera_open) {
        key_down = false;
        continue;
      }
      if (state & 2) {
        key_down = true;
        if (rt.recording) {
          audio_send(
              new AudioCommand{AudioCommand::record_end, rt.generation, {}});
          key_down = false;
          continue;
        }
        bool was_playing = rt.playing;
        if (was_playing) {
          // Interrupt only speech; preserve the task and its full result.
          stop_voice();
          post(EventKind::done);
          key_down = false;
        } else {
          rt.generation.fetch_add(1);
          audio_send(new AudioCommand{AudioCommand::stop, rt.generation, {}});
          audio_send(
              new AudioCommand{AudioCommand::record_begin, rt.generation, {}});
        }
      }
      if ((state & 1) && key_down) {
        key_down = false;
        audio_send(
            new AudioCommand{AudioCommand::record_end, rt.generation, {}});
      }
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}
void router_task(void *) {
  LLMRouter router;
  for (;;) {
    Routed *ptr = nullptr;
    xQueueReceive(rt.requests, &ptr, portMAX_DELAY);
    std::unique_ptr<Routed> job(ptr);
    const auto generation = job->request.generation;
    if (generation != rt.generation)
      continue;
    std::array<EndpointStatus, 7> status;
    if (xSemaphoreTake(rt.status_mutex, portMAX_DELAY) == pdTRUE) {
      status = rt.endpoints;
      xSemaphoreGive(rt.status_mutex);
    }
    job->route = router.decide(job->request, status, now_ms(), job->excluded);
    if (job->route.provider == Provider::local) {
      auto command = job->route.local_command;
      post_turn(EventKind::done, generation);
      if (command == 1) {
        post_turn(EventKind::sleep, generation);
        post_turn(EventKind::skin, generation, 0, 0, 3);
      } else if (command == 2 || command == 4) {
        post_turn(EventKind::wake, generation);
        post_turn(EventKind::skin, generation, 0, 0, 0);
      } else if (command == 3) {
        rt.sound_enabled = false;
        rt.pet_sounds = false;
        rt.remote_preferences_dirty = true;
      } else if (command == 6) {
        post_turn(EventKind::cancel_request, generation);
        continue;
      }
      ui_reply(new Reply{generation, job->route.local_reply,
                         job->route.local_reply, ""});
    } else if (job->route.provider == Provider::unavailable)
      ui_reply(new Reply{job->request.generation, "", "",
                         "Sin conexión disponible para esta consulta."});
    else {
      post_turn(EventKind::think, generation);
      auto *raw = job.release();
      if (xQueueSend(rt.network, &raw, 0) != pdTRUE) {
        delete raw;
        ui_reply(new Reply{generation, "", "",
                           "La cola está ocupada. Inténtalo de nuevo."});
      }
    }
  }
}
void console_task(void *) {
  std::string line;
  line.reserve(4096);
  for (;;) {
    int c = getchar();
    if (c < 0) {
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }
    if (c == '\n') {
      if (line.rfind("ask ", 0) == 0) {
        rt.generation.fetch_add(1);
        auto *q = new Request;
        q->text = line.substr(4);
        q->generation = rt.generation;
        q->preference = rt.preference;
        submit(q);
      } else if (line.rfind("profile ", 0) == 0) {
        auto *j = json_shape_safe(line.substr(8), 4096)
                      ? cJSON_Parse(line.c_str() + 8)
                      : nullptr;
        bool ok = false;
        if (j) {
          auto read = [&](const char *k) {
            auto *p = cJSON_GetStringValue(cJSON_GetObjectItem(j, k));
            return p ? std::string(p) : std::string();
          };
          auto provider = read("provider");
          Provider p = provider == "openrouter" ? Provider::openrouter
                       : provider == "openai"   ? Provider::openai
                       : provider == "xai"      ? Provider::xai
                       : provider == "gemini"   ? Provider::gemini
                       : provider == "opencode" ? Provider::opencode
                                                : Provider::unavailable;
          CloudProfile profile{
              cJSON_IsTrue(cJSON_GetObjectItem(j, "enabled")) != 0,
              cJSON_IsTrue(cJSON_GetObjectItem(j, "audio_input")) != 0,
              read("key"), read("small"), read("strong")};
          profile.responses_api =
              cJSON_IsTrue(cJSON_GetObjectItem(j, "responses_api"));
          if (xSemaphoreTake(rt.status_mutex, portMAX_DELAY) == pdTRUE) {
            ok = rt.credentials.install(p, profile);
            xSemaphoreGive(rt.status_mutex);
          }
          cJSON_Delete(j);
        }
        printf("profile.%s\n", ok ? "installed" : "rejected");
        std::fill(line.begin(), line.end(), 0);
      } else if (line.rfind("skin ", 0) ==
                 0) { // UI owns SkinManager; select via event index, never
                      // mutate LVGL here.
        const auto defaults = builtin_skins();
        for (size_t i = 0; i < defaults.size(); ++i)
          if (defaults[i].id == line.substr(5))
            post(EventKind::skin, 0, 0, i);
      }
      line.clear();
    } else if (c != '\r' && line.size() < 4096)
      line.push_back(char(c));
  }
}
void start(const RuntimeConfig &cfg) {
  rt.config = cfg;
  rt.events = xQueueCreate(24, sizeof(Event));
  rt.sensors = xQueueCreate(1, sizeof(SensorSnapshot));
  rt.requests = xQueueCreate(4, sizeof(Routed *));
  rt.network = xQueueCreate(4, sizeof(Routed *));
  rt.replies = xQueueCreate(8, sizeof(Reply *));
  rt.audio = xQueueCreate(16, sizeof(AudioCommand *));
  rt.decisions = xQueueCreate(4, sizeof(Decision *));
  rt.reloads = xQueueCreate(8, sizeof(Descriptor *));
  rt.camera_requests = xQueueCreate(1, sizeof(uint32_t));
  rt.camera_results = xQueueCreate(1, sizeof(CameraResult *));
  rt.updates = xQueueCreate(1, sizeof(UpdateOffer *));
  rt.preferences = xQueueCreate(1, sizeof(UserPreferences));
  rt.focus_saves = xQueueCreate(1, sizeof(FocusTimer::Snapshot));
  rt.flags = xEventGroupCreate();
  rt.bands_mutex = xSemaphoreCreateMutex();
  rt.status_mutex = xSemaphoreCreateMutex();
  configASSERT(rt.events && rt.sensors && rt.requests && rt.network &&
               rt.replies && rt.audio && rt.decisions && rt.reloads &&
               rt.camera_requests && rt.camera_results && rt.updates &&
               rt.preferences && rt.focus_saves && rt.flags && rt.bands_mutex &&
               rt.status_mutex);
  rt.credentials.load();
  // This named-partition API initializes plain NVS even when encryption
  // support is compiled. Only vault uses secure_init_partition. Never call
  // nvs_flash_init(), which auto-selects encryption for the default NVS.
  auto nvs_result = nvs_flash_init_partition("nvs");
  if (nvs_result != ESP_OK)
    ESP_LOGW("sagwa", "Provision NVS unavailable; local modes retained");
  nvs_handle_t preferences;
  if (nvs_open("sagwa_ui", NVS_READONLY, &preferences) == ESP_OK) {
    UserPreferences prefs;
    size_t size = sizeof(prefs);
    if (nvs_get_blob(preferences, "preferences", &prefs, &size) == ESP_OK &&
        size == sizeof(prefs) && valid_preferences(prefs)) {
      rt.preference = Preference(prefs.routing);
      rt.voice_enabled = prefs.voice;
      rt.pet_enabled = prefs.pet;
      rt.pet_sounds = prefs.sounds;
      rt.pet_sensors = prefs.sensors;
      rt.selected_target = prefs.target;
      rt.selected_capability = prefs.capability;
      if (!rt.skins.select(prefs.skin))
        rt.pending_skin_id = prefs.skin;
      rt.sound_enabled = prefs.sounds && prefs.pet && rt.skins.current().sounds;
    }
    FocusTimer::Snapshot saved_focus;
    size = sizeof(saved_focus);
    if (nvs_get_blob(preferences, "focus", &saved_focus, &size) == ESP_OK &&
        size == sizeof(saved_focus))
      rt.focus.restore(saved_focus); // Running sessions restore paused.
    nvs_close(preferences);
  }
  rt.provisioned = shell::load_provision(rt.provision);
  ESP_ERROR_CHECK(bsp_i2c_init());
  // Warm both shared BSP handles before UI/Audio/Sensor can race lazy init.
  ESP_ERROR_CHECK(bsp_pmu_init());
  esp_io_expander_handle_t expander = nullptr;
  for (unsigned attempt = 1; attempt <= 3; ++attempt) {
    expander = bsp_io_expander_init();
    if (expander)
      break;
    ESP_LOGW("sagwa", "IO expander initialization failed, attempt %u/3", attempt);
    if (attempt < 3) {
      // Startup still has a single bus owner. Recover the controller after a
      // failed transaction without removing the registered PMU device.
      const auto reset = i2c_master_bus_reset(bsp_i2c_get_handle());
      ESP_LOGW("sagwa", "I2C startup recovery: %s", esp_err_to_name(reset));
      vTaskDelay(pdMS_TO_TICKS(20));
    }
  }
  configASSERT(expander); // Refuse unhealthy boot; no workers use a null handle.

  esp_vfs_spiffs_conf_t fs{};
  fs.base_path = cfg.storage_root.c_str();
  fs.partition_label = "storage";
  fs.max_files = 8;
  fs.format_if_mount_failed = false;
  esp_vfs_spiffs_register(&fs);
#ifdef CONFIG_SAGWA_SD_ENABLED
  bsp_sdcard_mount();
#endif
  auto task = [](TaskFunction_t fn, const char *name, uint32_t stack,
                 int priority, int core) {
    ESP_LOGI("sagwa", "Task %s internal_free=%u largest=%u stack=%u", name,
             unsigned(heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
             unsigned(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
             unsigned(stack));
    configASSERT(xTaskCreatePinnedToCore(fn, name, stack, nullptr, priority,
                                         nullptr, core) == pdPASS);
  };
  task(ui_task, "UI_Task", 8192, 5, 1);
  task(audio_task, "Audio_Task", 16384, 10, 0);
  task(sensor_task, "Sensor_Task", 4096, 4, 0);
  task(router_task, "Router_Task", 6144, 4, 1);
  task(network_task, "Network_Task", 16384, 3, 0);
  task(console_task, "Console_Task", 4096, 1, 1);
  task(storage_task, "Storage_Task", 16384, 1, 0);
  task(camera_task, "Camera_Task", 8192, 2, 0);
  task(maintenance_task, "Maintenance_Task", 8192, 1, 0);
}
} // namespace sagwa
