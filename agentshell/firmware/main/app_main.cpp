#include "M5Unified.h"
#include "audio.hpp"
#include "avatar.hpp"
#include "context.hpp"
#include "controls.hpp"
#include "driver/usb_serial_jtag.h"
#include "esp_heap_caps.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "hal.hpp"
#include "network.hpp"
#include "nvs_flash.h"
#include "ota.hpp"
#include "pet.hpp"
#include "protocol.hpp"
#include "storage.hpp"
#include "ui.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <ctime>
using namespace shell;
static View view;
static Provision provision;
static uint64_t outgoing_sequence, received_sequence;
static std::string current_task, speaker_stream, speaker_task, record_task,
    record_stream, canceled_task, voice_sample_task;
static uint32_t speaker_sequence;
static bool speaker_finished;
static uint32_t speaker_starts, speaker_frames, speaker_rejected_frames;
static std::string &target = view.target, &preferred = view.preferred,
                   &capability = view.capability;
static Controls controls;
static std::vector<uint8_t> photo_buffer;
static unsigned touch_actions;
static bool emit(const char *type, cJSON *p, const std::string &task = "",
                 bool control = true) {
  bool sent = send_json(
      message(session_id(), ++outgoing_sequence, type, p, task), control);
  cJSON_Delete(p);
  return sent;
}
static bool transfer(const std::vector<uint8_t> &bytes, uint8_t kind,
                     const std::string &task) {
  auto stream = uuid();
  auto *p = cJSON_CreateObject();
  cJSON_AddStringToObject(p, "stream_id", stream.c_str());
  cJSON_AddNumberToObject(p, "kind", kind);
  if (!emit("media.start", p, task, false))
    return false;
  for (size_t n = 0, seq = 0; n < bytes.size(); n += 4096, seq++) {
    auto frame =
        media_frame(session_id(), task, stream, seq, kind, bytes.data() + n,
                    std::min(size_t(4096), bytes.size() - n));
    if (!send_binary(frame)) {
      view.mode = "warning";
      view.text = "Conexión interrumpida. Vuelve a intentar.";
      return false;
    }
  }
  p = cJSON_CreateObject();
  cJSON_AddStringToObject(p, "stream_id", stream.c_str());
  cJSON_AddStringToObject(p, "target", kind == 2 ? "mac-mini" : target.c_str());
  cJSON_AddStringToObject(p, "preferred_agent",
                          kind == 2 ? "muse" : preferred.c_str());
  cJSON_AddStringToObject(p, "capability", capability.c_str());
  if (kind == 2) {
    cJSON_AddStringToObject(p, "format", "rgb565");
    cJSON_AddNumberToObject(p, "width", 320);
    cJSON_AddNumberToObject(p, "height", 240);
    cJSON_AddStringToObject(p, "goal",
                            "Describe esta foto solicitada desde el CoreS3.");
  }
  return emit("media.end", p, task, false);
}
static std::string field(const cJSON *p, const char *name) {
  const char *s =
      cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(p, name));
  return s ? s : "";
}
static cJSON *audio_diagnostic() {
  const auto s = audio_status();
  auto *p = cJSON_CreateObject();
  cJSON_AddBoolToObject(p, "speaker_ready", s.speaker_ready);
  cJSON_AddBoolToObject(p, "last_play_ok", s.last_play_ok);
  cJSON_AddBoolToObject(p, "playing", speaking());
  cJSON_AddBoolToObject(p, "recording", listening());
  cJSON_AddNumberToObject(p, "received_chunks", s.received_chunks);
  cJSON_AddNumberToObject(p, "rejected_chunks", s.rejected_chunks);
  cJSON_AddNumberToObject(p, "received_pcm_bytes", double(s.received_bytes));
  cJSON_AddNumberToObject(p, "queued_samples", double(s.queued_samples));
  cJSON_AddNumberToObject(p, "play_failures", s.play_failures);
  cJSON_AddNumberToObject(p, "stream_starts", speaker_starts);
  cJSON_AddNumberToObject(p, "accepted_media_frames", speaker_frames);
  cJSON_AddNumberToObject(p, "rejected_media_frames", speaker_rejected_frames);
  return p;
}
static void usb_tick() {
  static std::string line;
  uint8_t bytes[256];
  int n = usb_serial_jtag_read_bytes(bytes, sizeof(bytes), 0);
  for (int i = 0; i < n; i++) {
    if (bytes[i] == '\n') {
      cJSON *p = cJSON_Parse(line.c_str());
      if (p) {
        auto command = field(p, "command");
        bool ok = false;
        if (command == "provision")
          ok = install_provision(cJSON_GetObjectItemCaseSensitive(p, "config"),
                                 provision);
        else if (command == "sensors") {
          auto *readings = sensors();
          char *text = cJSON_PrintUnformatted(readings);
          if (text) {
            usb_serial_jtag_write_bytes(text, strlen(text), pdMS_TO_TICKS(100));
            usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(100));
            cJSON_free(text);
          }
          cJSON_Delete(readings);
          ok = true;
        } else if (command == "calibrate") {
          calibrate(true);
          ok = true;
        } else if (command == "camera.test" && !listening()) {
          if (view.connected)
            emit("audio.cancel", cJSON_CreateObject(), current_task);
          voice_stop();
          speaker_stream.clear();
          view.camera = true;
          view.text = "Prueba de cámara solicitada por USB.";
          ui_draw(view, esp_timer_get_time() / 1000);
          std::vector<uint8_t> photo;
          ok = capture(photo);
          auto *result = cJSON_CreateObject();
          cJSON_AddBoolToObject(result, "camera_capture", ok);
          cJSON_AddNumberToObject(result, "bytes", photo.size());
          if (ok) {
            unsigned sum = 0;
            for (auto value : photo)
              sum += value;
            cJSON_AddNumberToObject(result, "mean_byte",
                                    double(sum) / photo.size());
          }
          char *text = cJSON_PrintUnformatted(result);
          if (text) {
            usb_serial_jtag_write_bytes(text, strlen(text), pdMS_TO_TICKS(100));
            usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(100));
            cJSON_free(text);
          }
          cJSON_Delete(result);
          view.camera = false;
        } else if (command == "display.test" && view.page == Page::home &&
                   view.approval_id.empty() && !listening() && !speaking()) {
          auto pixels = static_cast<uint8_t *>(heap_caps_calloc(
              320 * 240, 3, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
          if (pixels) {
            M5.Display.readRectRGB(0, 0, 320, 240, pixels);
            unsigned background = 0, ink = 0, character = 0, emoji = 0;
            for (unsigned y = 0; y < 240; y++)
              for (unsigned x = 0; x < 320; x++) {
                auto at = (y * 320 + x) * 3;
                bool colored = pixels[at] || pixels[at + 1] || pixels[at + 2];
                if (x >= 84 && x < 220 && y >= 8 && y < 144)
                  character += colored;
                else if (x >= 280 && x < 308 && y >= 12 && y < 40)
                  emoji += colored;
                else if (y >= 150) {
                  ink += pixels[at] >= 240 && pixels[at + 1] >= 240 &&
                         pixels[at + 2] >= 240;
                } else
                  background += colored;
              }
            auto result = cJSON_CreateObject();
            cJSON_AddNumberToObject(result, "background_nonblack_pixels",
                                    background);
            cJSON_AddNumberToObject(result, "avatar_nonblack_pixels",
                                    character);
            cJSON_AddNumberToObject(result, "emoji_nonblack_pixels", emoji);
            cJSON_AddNumberToObject(result, "white_text_pixels", ink);
            cJSON_AddBoolToObject(result, "lcd_readback_usable",
                                  character > 100 && emoji > 20 && ink > 10);
            char *text = cJSON_PrintUnformatted(result);
            if (text) {
              usb_serial_jtag_write_bytes(text, strlen(text),
                                          pdMS_TO_TICKS(100));
              usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(100));
              cJSON_free(text);
            }
            cJSON_Delete(result);
            free(pixels);
            ok = true;
          }
        } else if (command == "audio.status") {
          auto *result = audio_diagnostic();
          char *text = cJSON_PrintUnformatted(result);
          if (text) {
            usb_serial_jtag_write_bytes(text, strlen(text), pdMS_TO_TICKS(100));
            usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(100));
            cJSON_free(text);
          }
          cJSON_Delete(result);
          ok = true;
        } else if (command == "speaker.test" && !listening()) {
          if (view.connected)
            emit("audio.cancel", cJSON_CreateObject(), current_task);
          voice_stop();
          speaker_stream.clear();
          speaker_finished = false;
          view.mode = "speaking";
          view.text = "Prueba local del altavoz (1 segundo).";
          std::vector<int16_t> tone(16000);
          for (size_t i = 0; i < tone.size(); i++)
            tone[i] = int16_t(
                8000 * std::sin(2 * 3.141592653589793 * 440 * i / 16000));
          ok = true;
          auto *data = reinterpret_cast<uint8_t *>(tone.data());
          for (size_t offset = 0; offset < tone.size() * 2; offset += 4096)
            ok = speaker_chunk(
                     data + offset,
                     std::min(size_t(4096), tone.size() * 2 - offset)) &&
                 ok;
        } else if (command == "microphone.test" && !listening()) {
          ok = record_start();
          if (ok) {
            view.microphone = true;
            view.text = "Prueba de micrófono solicitada por USB.";
            ui_draw(view, esp_timer_get_time() / 1000);
            const int64_t until = esp_timer_get_time() + 2000000;
            while (esp_timer_get_time() < until) {
              record_tick();
              vTaskDelay(pdMS_TO_TICKS(10));
            }
            auto pcm = record_finish();
            view.microphone = false;
            auto *result = cJSON_CreateObject();
            cJSON_AddNumberToObject(result, "pcm_bytes", pcm.size());
            char *text = cJSON_PrintUnformatted(result);
            if (text) {
              usb_serial_jtag_write_bytes(text, strlen(text),
                                          pdMS_TO_TICKS(100));
              usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(100));
              cJSON_free(text);
            }
            cJSON_Delete(result);
          }
        }
        const char *reply = ok ? "{\"ok\":true}\n" : "{\"ok\":false}\n";
        usb_serial_jtag_write_bytes(reply, strlen(reply), pdMS_TO_TICKS(100));
        cJSON_Delete(p);
        if (ok && command == "provision") {
          vTaskDelay(pdMS_TO_TICKS(200));
          esp_restart();
        }
      }
      line.clear();
    } else if (line.size() < 24576)
      line += char(bytes[i]);
    else
      line.clear();
  }
}
extern "C" void app_main() {
  bool storage = nvs_flash_init() == ESP_OK;
  bool display = hal_begin();
  bool audio = audio_begin();
  ui_begin();
  ui_load_preferences(view);
  const bool card = sd_begin();
  usb_serial_jtag_driver_config_t usb = {};
  usb.rx_buffer_size = 32768;
  usb.tx_buffer_size = 4096;
  usb_serial_jtag_driver_install(&usb);
  bool local_healthy = storage && display && audio;
#ifdef AGENTSHELL_TEST_BOOT_FAILURE
  local_healthy = false;
#endif
  confirm_local_boot(local_healthy);
  const bool configured = storage && load_provision(provision);
  if (configured) {
    ui_context_begin(provision);
    ui_avatar_begin(provision);
    network_begin(provision);
    view.text = "Conectando a los gateways...";
  }
  received_sequence = load_sequence();
  uint32_t last_sensor = 0, last_saved = 0;
  Pet pet;
  extern const uint8_t purr_start[] asm("_binary_purr_pcm_start"),
      purr_end[] asm("_binary_purr_pcm_end"),
      meow_start[] asm("_binary_meow_pcm_start"),
      meow_end[] asm("_binary_meow_pcm_end");
  auto pet_audio = [&](PetSound sound) {
    if (view.pet_sounds && sound == PetSound::purr)
      pet_play(purr_start, purr_end - purr_start);
    else if (view.pet_sounds && sound == PetSound::meow)
      pet_play(meow_start, meow_end - meow_start);
  };
  bool was_online = false;
  for (;;) {
    hal_update();
    usb_tick();
    record_tick();
    speaker_tick();
    const uint32_t ms = esp_timer_get_time() / 1000;
    view.battery = battery();
    view.connected = connected();
    if (view.connected != was_online) {
      ui_context_clear();
      view.settings_ready = false;
      was_online = view.connected;
      voice_stop();
      speaker_stream.clear();
      if (listening())
        record_finish();
      view.mode = view.connected ? "idle" : "offline";
      view.text = view.connected ? "Estoy aquí. Mantén PWR para hablar."
                                 : "Sin conexión. Sagwa sigue contigo.";
    }
    view.microphone = listening();
    view.speaker = speaking() || !speaker_stream.empty();
    int x = 0, y = 0;
    bool held = false;
    bool pressed = touch(x, y, held);
    Input input{x, y, pressed, held, key_pressed(), key_held(), ms};
    if (pressed || key_pressed())
      touch_actions++;
    if (view.approval_expires_ms && !view.approval_id.empty() &&
        uint64_t(time(nullptr)) * 1000 >= view.approval_expires_ms) {
      view.approval_id.clear();
      view.action_hash.clear();
      view.mode = "warning";
      view.page = Page::home;
      view.text = "Esta autorización ha caducado.";
    }
    const auto action = controls.update(view, input);
    static uint32_t pet_touch_pending = 0, pet_sensor_pending = 0,
                    pet_touch_ms = 0, pet_sensor_ms = 0;
    auto old_pose = view.pet_pose;
    auto local = local_sensors();
    bool pet_allowed = view.pet_enabled && view.page == Page::home &&
                       !view.microphone && !view.speaker && !view.task_active &&
                       view.approval_id.empty() && view.mode != "warning";
    auto reaction =
        pet.update(view.pet_sensors ? local : LocalSensors{}, ms, pet_allowed);
    view.pet_pose = reaction.pose;
    if (pet_allowed && reaction.pose != old_pose && local.sampled_ms &&
        ms - local.sampled_ms <= 600)
      pet_sensor_pending = local.sampled_ms;
    view.audio_level = audio_level();
    if (pet_allowed)
      pet_audio(reaction.sound);
    if (view.page == Page::sensors) {
      view.sensor_text =
          "Luz: " +
          (local.light_ok ? std::to_string(int(local.light)) + " ADC"
                          : "no disponible") +
          "\nProximidad: " +
          (local.proximity_ok
               ? std::to_string(int(local.proximity)) + " relativa"
               : "no disponible") +
          "\nMovimiento: " + (local.accel_ok ? "disponible" : "no disponible") +
          "\nGiroscopio: " + (local.gyro_ok ? "disponible" : "no disponible") +
          "\nBatería: " + std::to_string(view.battery) + " %";
    }
    auto stop_output = [&] {
      if (view.connected)
        emit("audio.cancel", cJSON_CreateObject(), current_task);
      voice_stop();
      voice_sample_task.clear();
      speaker_stream.clear();
      speaker_finished = false;
      view.speaker = false;
    };
    if (action == Control::pet_stroke && pet_allowed) {
      pet_touch_pending = ms;
      auto r = pet.stroke(ms);
      view.pet_pose = r.pose;
      pet_audio(r.sound);
    } else if (action == Control::save_preferences) {
      ui_save_preferences(view);
      if (view.connected) {
        auto *p = cJSON_CreateObject();
        cJSON_AddBoolToObject(p, "voice_enabled", view.voice_enabled);
        cJSON_AddBoolToObject(p, "pet_enabled", view.pet_enabled);
        cJSON_AddBoolToObject(p, "pet_sounds", view.pet_sounds);
        cJSON_AddBoolToObject(p, "pet_sensors", view.pet_sensors);
        emit("device.preferences", p);
      }
    } else if (action == Control::read_result && view.connected &&
               !current_task.empty()) {
      emit("task.read", cJSON_CreateObject(), current_task);
    } else if (action == Control::voice_sample && view.connected) {
      stop_output();
      voice_sample_task = uuid();
      emit("voice.sample", cJSON_CreateObject(), voice_sample_task);
    } else if (action == Control::start_voice) {
      stop_output();
      ui_context_clear();
      record_task = uuid();
      current_task = record_task;
      view.task = record_task;
      if (record_start()) {
        view.microphone = true;
        view.task_active = true;
        view.mode = "listening";
        view.text = "Escuchando. Suelta para enviar.";
        view.scroll = 0;
      } else {
        view.mode = "warning";
        view.text = "No se pudo activar el micrófono.";
      }
    } else if (action == Control::end_voice && listening()) {
      auto bytes = record_finish();
      view.microphone = false;
      current_task = record_task;
      view.mode = "thinking";
      view.text = "Transcribiendo voz...";
      if (bytes.size() >= 3200) {
        if (!transfer(bytes, 1, record_task)) {
          view.task_active = false;
          view.mode = "warning";
          view.text = "No se pudo enviar el audio. Intenta otra vez.";
        }
      } else {
        view.task_active = false;
        view.mode = "idle";
        view.text = "Manten el boton mientras hablas.";
      }
    } else if (action == Control::stop_voice) {
      stop_output();
      view.mode = "idle";
      view.text = "Voz detenida. La tarea sigue activa.";
      if (!view.task_active)
        view.text = "Voz detenida.";
    } else if (action == Control::refresh) {
      if (view.connected)
        emit("device.refresh", cJSON_CreateObject());
    } else if (action == Control::photo && !listening()) {
      stop_output();
      view.page = Page::photo;
      view.camera = true;
      view.photo_ready = false;
      view.notice.clear();
      ui_draw(view, ms);
      photo_buffer.clear();
      if (capture(photo_buffer) && ui_photo(photo_buffer))
        view.photo_ready = true;
      else {
        view.page = Page::home;
        view.mode = "warning";
        view.text = "No se pudo capturar la foto.";
        std::vector<uint8_t>().swap(photo_buffer);
      }
      view.camera = false;
    } else if (action == Control::discard_photo) {
      std::vector<uint8_t>().swap(photo_buffer);
    } else if (action == Control::send_photo && view.photo_ready &&
               view.connected && agent_available(view, "muse")) {
      current_task = uuid();
      view.task = current_task;
      view.task_active = true;
      view.mode = "thinking";
      if (transfer(photo_buffer, 2, current_task)) {
        std::vector<uint8_t>().swap(photo_buffer);
        view.photo_ready = false;
        view.page = Page::home;
        view.text = "Foto enviada a Muse para procesar.";
      } else {
        view.task_active = false;
        view.notice = "No se pudo enviar la foto.";
      }
    } else if (action == Control::cancel_task && !current_task.empty()) {
      ui_context_clear();
      stop_output();
      bool sent = emit("task.cancel", cJSON_CreateObject(), current_task);
      if (sent) {
        view.task_active = false;
        canceled_task = current_task;
        view.approval_id.clear();
      }
      view.mode = sent ? "idle" : "warning";
      view.text =
          sent ? "Cancelación enviada." : "No se pudo enviar la cancelación.";
    } else if (action == Control::approve || action == Control::deny) {
      auto *p = cJSON_CreateObject();
      cJSON_AddStringToObject(p, "approval_id", view.approval_id.c_str());
      cJSON_AddStringToObject(p, "action_hash", view.action_hash.c_str());
      cJSON_AddStringToObject(p, "decision",
                              action == Control::approve ? "approve" : "deny");
      if (emit("approval.decision", p, current_task)) {
        view.approval_id.clear();
        view.action_hash.clear();
        view.mode = action == Control::approve ? "executing" : "idle";
        view.text = action == Control::approve ? "Autorización enviada."
                                               : "Accion denegada.";
      } else
        view.text = "Sin conexion. No se envio la decision.";
    }
    Packet packet;
    while (receive(packet)) {
      if (packet.binary) {
        std::string s, t, stream;
        uint32_t seq;
        uint8_t kind;
        if (media_header(packet.data.data(), packet.data.size(), s, t, stream,
                         seq, kind) &&
            s == session_id() && stream == speaker_stream &&
            t == speaker_task && t != canceled_task && kind == 3 &&
            seq == speaker_sequence++) {
          speaker_frames++;
          if (!speaker_chunk(packet.data.data() + 57,
                             packet.data.size() - 57)) {
            voice_stop();
            speaker_stream.clear();
            emit("audio.cancel", cJSON_CreateObject(), current_task);
          }
        } else
          speaker_rejected_frames++;
        continue;
      }
      packet.data.push_back(0);
      auto *m = cJSON_Parse(reinterpret_cast<char *>(packet.data.data()));
      if (!m)
        continue;
      if (field(m, "session_id") != session_id()) {
        cJSON_Delete(m);
        continue;
      }
      auto type = field(m, "type");
      auto task = field(m, "task_id");
      auto *p = cJSON_GetObjectItemCaseSensitive(m, "payload");
      auto *sequence = cJSON_GetObjectItemCaseSensitive(m, "sequence");
      if (cJSON_IsNumber(sequence) &&
          sequence->valuedouble > received_sequence) {
        received_sequence = sequence->valuedouble;
        last_sequence(received_sequence);
      }
      if (type == "ui.result" &&
          (task != current_task || view.page != Page::reader)) {
        cJSON_Delete(m);
        continue;
      }
      if (task.empty() || task != canceled_task) {
        if (!task.empty() && type != "ui.emoji" &&
            type.rfind("audio.", 0) != 0) {
          current_task = task;
          view.task = task;
        }
        if (type == "ui.avatar") {
          ui_avatar_offer(p);
        } else if (type == "ui.emoji") {
          if (task.empty() || task == current_task)
            ui_context_offer(p);
        } else if (type == "audio.start") {
          speaker_starts++;
          if (listening() || !view.voice_enabled ||
              (task != current_task && task != voice_sample_task)) {
            emit("audio.cancel", cJSON_CreateObject(), task);
            cJSON_Delete(m);
            continue;
          }
          voice_stop();
          speaker_stream = field(p, "stream_id");
          speaker_task = task;
          speaker_sequence = 0;
          speaker_finished = false;
          view.mode = "speaking";
        } else if (type == "audio.end" &&
                   field(p, "stream_id") == speaker_stream) {
          speaker_finished = true;
        } else if (type == "audio.stop") {
          voice_stop();
          speaker_stream.clear();
          view.mode = "idle";
        } else if (type == "ota.offer" && !listening() && !speaking()) {
          if (ota_is_current(p) || ota_attempted(p)) {
            cJSON_Delete(m);
            continue;
          }
          view.text = "Verificando actualización firmada...";
          ui_draw(view, ms);
          if (install_ota(p, provision))
            esp_restart();
          else {
            view.mode = "warning";
            view.text = "Actualización rechazada. Firmware conservado.";
          }
        } else if (type == "device.snapshot") {
          ui_context_clear();
          ui_event(view, type.c_str(), p);
          current_task = view.task;
        } else
          ui_event(view, type.c_str(), p);
      }
      cJSON_Delete(m);
    }
    if (view.connected && ms - last_sensor > 5000) {
      auto *readings = sensors();
      cJSON_AddItemToObject(readings, "emoji", ui_context_status());
      cJSON_AddItemToObject(readings, "avatar", ui_avatar_status());
      auto *timing = cJSON_AddObjectToObject(readings, "reaction_timing");
      cJSON_AddNumberToObject(timing, "touch_to_lcd_ms", pet_touch_ms);
      cJSON_AddNumberToObject(timing, "sensor_sample_to_lcd_ms", pet_sensor_ms);
      auto *ui = cJSON_AddObjectToObject(readings, "ui");

      cJSON_AddStringToObject(ui, "page", page_name(view.page));
      cJSON_AddStringToObject(ui, "preferred_agent", preferred.c_str());
      cJSON_AddStringToObject(ui, "target", target.c_str());
      cJSON_AddStringToObject(ui, "capability", capability.c_str());
      cJSON_AddBoolToObject(ui, "task_active", view.task_active);
      cJSON_AddBoolToObject(ui, "voice_available", voice_available(view));
      cJSON_AddStringToObject(ui, "mode", view.mode.c_str());
      cJSON_AddStringToObject(ui, "current_task", current_task.c_str());
      cJSON_AddItemToObject(readings, "audio", audio_diagnostic());
      cJSON_AddBoolToObject(ui, "settings_ready", view.settings_ready);
      cJSON_AddNumberToObject(ui, "touch_actions", touch_actions);
      auto *agents = cJSON_AddArrayToObject(ui, "available_agents");
      for (const auto &a : view.agents)
        if (a.available)
          cJSON_AddItemToArray(agents, cJSON_CreateString(a.id.c_str()));
      emit("device.telemetry", readings, "", false);
      last_sensor = ms;
    }
    if (ms - last_saved > 60000) {
      save_sequence(received_sequence);
      last_saved = ms;
    }
    if (view.mode == "idle" && presence())
      view.mode = "presence";
    if (view.mode == "presence" && !presence())
      view.mode = "idle";
    if (view.mode == "speaking" && !speaking() && speaker_stream.empty())
      view.mode = "idle";
    if (speaker_finished && !speaking()) {
      speaker_stream.clear();
      speaker_finished = false;
      if (view.mode == "speaking")
        view.mode = "idle";
    }
    ui_draw(view, ms);
    if (pet_touch_pending && ui_last_draw_ms() >= pet_touch_pending) {
      pet_touch_ms = ui_last_draw_ms() - pet_touch_pending;
      pet_touch_pending = 0;
    }
    if (pet_sensor_pending && ui_last_draw_ms() >= pet_sensor_pending) {
      pet_sensor_ms = ui_last_draw_ms() - pet_sensor_pending;
      pet_sensor_pending = 0;
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}
