#include "network.hpp"
#include "weather_json.hpp"
#include "audio_start_gate.hpp"
#include "cJSON.h"
#include "esp_wifi.h"
#include "platform.hpp"
#include "protocol.hpp"
#include <cmath>
#include <cstring>
#include <ctime>
#include <memory>
#include <optional>
namespace sagwa {
static std::string field(const cJSON *j, const char *k) {
  auto *s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(j, k));
  return s ? s : "";
}
static uint64_t sequence = 0;
static bool emit(const char *t, cJSON *p, const std::string &id = {},
                 bool control = true) {
  bool ok = shell::send_json(
      shell::message(shell::session_id(), ++sequence, t, p, id), control);
  cJSON_Delete(p);
  return ok;
}
static bool send_request(const Routed &job, std::string &task) {
  const auto candidate = shell::uuid();
  if (!job.request.audio && !job.request.image) {
    auto *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "goal", job.request.text.c_str());
    cJSON_AddStringToObject(p, "target", job.request.target.c_str());
    cJSON_AddStringToObject(p, "preferred_agent", "muse");
    cJSON_AddStringToObject(p, "capability", job.request.capability.c_str());
    cJSON_AddItemToObject(p, "context_refs", cJSON_CreateArray());
    if (!emit("task.submit", p, candidate))
      return false;
    task = candidate;
    return true;
  }
  const uint8_t kind = job.request.image ? 2 : 1;
  if (job.request.image ? job.audio.size() != 320 * 240 * 2
                        : job.audio.size() < 44 || job.audio.size() > 320044)
    return false;
  auto stream = shell::uuid();
  auto *p = cJSON_CreateObject();
  cJSON_AddStringToObject(p, "stream_id", stream.c_str());
  cJSON_AddNumberToObject(p, "kind", kind);
  if (!emit("media.start", p, candidate, false))
    return false;
  auto abort = [&] {
    // Ordered with media.start/frames so it cannot overtake them.
    emit("task.cancel", cJSON_CreateObject(), candidate, false);
    return false;
  };
  for (size_t offset = 0, n = 0; offset < job.audio.size();
       offset += 4096, n++) {
    if (job.request.generation != runtime().generation)
      return abort();
    auto frame =
        shell::media_frame(shell::session_id(), candidate, stream, n, kind,
                           job.audio.data() + offset,
                           std::min<size_t>(4096, job.audio.size() - offset));
    if (!shell::send_binary(frame))
      return abort();
  }
  p = cJSON_CreateObject();
  cJSON_AddStringToObject(p, "stream_id", stream.c_str());
  cJSON_AddStringToObject(p, "target", job.request.target.c_str());
  cJSON_AddStringToObject(p, "preferred_agent", "muse");
  cJSON_AddStringToObject(p, "capability", job.request.capability.c_str());
  if (job.request.image)
    cJSON_AddStringToObject(p, "goal", "Describe esta foto brevemente.");
  if (job.request.generation != runtime().generation) {
    cJSON_Delete(p);
    return abort();
  }
  if (!emit("media.end", p, candidate, false))
    return abort();
  task = candidate;
  return true;
}
void network_task(void *) {
  auto &r = runtime();
  bool transport = r.provisioned && shell::network_begin(r.provision);
  sequence = shell::load_sequence();
  std::array<uint32_t, 7> retry_after{};
  std::string task, speaker;
  uint32_t turn = 0, speaker_seq = 0, canceled_audio_revision = 0,
           cleared_audio_revision = 0;
  uint64_t incoming = 0;
  std::string full_text, last_brief;
  std::string resume_requested_session;
  bool snapshot_waits_clock = false;
  AudioStartGate audio_start_gate;
  std::string audio_control_session;
  bool client_transcripts =
      false; // Explicit gateway negotiation, false for0.2.
  bool muse_available = false;
  uint32_t settings_at = 0, telemetry_at = 0;
  std::unique_ptr<AudioCommand> blocked_audio;
  std::optional<Request> awaiting_transcript;
  uint32_t transcript_started_at = 0;
  for (;;) {
    uint32_t ms = now_ms();
    const uint32_t stop_revision = r.audio_stop_revision;
    if (turn && r.stopped_audio_generation == turn) {
      if (cleared_audio_revision != stop_revision) {
        cleared_audio_revision = stop_revision;
        if (blocked_audio && blocked_audio->generation == turn)
          blocked_audio.reset();
        speaker.clear();
      }
      if (transport && shell::connected() &&
          canceled_audio_revision != stop_revision &&
          emit("audio.cancel", cJSON_CreateObject(), task))
        canceled_audio_revision = stop_revision;
    }
    if (r.audio_fault.exchange(false)) {
      const uint32_t failed = r.failed_audio_generation;
      if (blocked_audio && blocked_audio->generation == failed)
        blocked_audio.reset();
      if (transport && !task.empty() && turn == failed)
        emit("audio.cancel", cJSON_CreateObject(), task);
      if (turn == failed)
        speaker.clear();
      audio_send(new AudioCommand{AudioCommand::stop, failed, {}});
    }
    wifi_ap_record_t ap{};
    bool wifi = transport && esp_wifi_sta_get_ap_info(&ap) == ESP_OK,
         wss = transport && shell::connected();
    if (wss && audio_control_session != shell::session_id()) {
      audio_control_session = shell::session_id();
      audio_start_gate.reset();
      speaker.clear();
    }
    if (awaiting_transcript &&
        (!wss || awaiting_transcript->generation != r.generation ||
         ms - transcript_started_at > 15000)) {
      const auto generation = awaiting_transcript->generation;
      if (wss && !task.empty())
        emit("task.cancel", cJSON_CreateObject(), task);
      awaiting_transcript.reset();
      task.clear();
      turn = 0;
      if (generation == r.generation)
        ui_reply(new Reply{generation, "", "",
                           "No pude escucharte. Inténtalo de nuevo."});
    }
    if (wifi)
      xEventGroupSetBits(r.flags, wifi_bit);
    else
      xEventGroupClearBits(r.flags, wifi_bit);
    if (wss)
      xEventGroupSetBits(r.flags, wss_bit);
    else
      xEventGroupClearBits(r.flags, wss_bit);
    if (wss && snapshot_waits_clock && shell::time_synchronized() &&
        turn == r.generation && !task.empty() &&
        emit("device.resume", cJSON_CreateObject(), task))
      snapshot_waits_clock = false;
    if (wss && ms - telemetry_at >= 5000) {
      if (emit("device.telemetry", telemetry(), {}, false))
        telemetry_at = ms;
    }
    if (wss && r.preferences_dirty.exchange(false)) {
      auto *preferences = cJSON_CreateObject();
      cJSON_AddBoolToObject(preferences, "voice_enabled", r.voice_enabled);
      cJSON_AddBoolToObject(preferences, "pet_enabled", r.pet_enabled);
      cJSON_AddBoolToObject(preferences, "pet_sounds", r.pet_sounds);
      cJSON_AddBoolToObject(preferences, "pet_sensors", r.pet_sensors);
      if (!emit("device.preferences", preferences))
        r.preferences_dirty = true;
    }
    if (xSemaphoreTake(r.status_mutex, portMAX_DELAY) == pdTRUE) {
      bool destination_available = false;
      for (const auto &node : r.device_status.nodes)
        if (node.id == r.selected_target && node.available)
          destination_available = true;
      r.endpoints[1] = {r.provisioned,
                        wss && muse_available && destination_available &&
                            ms - settings_at < 45000,
                        r.provisioned,
                        true,
                        true,
                        ms,
                        "muse",
                        "muse"};
      for (size_t i = 2; i < 7; i++) {
        CloudProfile profile;
        bool enabled = r.credentials.profile(Provider(i), profile);
        bool cooling = retry_after[i] && int32_t(ms - retry_after[i]) < 0;
        r.endpoints[i] = {enabled,
                          wifi && !cooling,
                          enabled,
                          profile.audio_input,
                          false,
                          ms,
                          profile.small_model,
                          profile.strong_model};
      }
      xSemaphoreGive(r.status_mutex);
    }
    Decision *decision = nullptr;
    while (xQueueReceive(r.decisions, &decision, 0) == pdTRUE) {
      std::unique_ptr<Decision> own(decision);
      auto failed_decision = [&] {
        auto *reply = new Reply{decision->generation};
        reply->decision_id = decision->approval_id;
        reply->error = "No pude confirmar. Revisa la tarea.";
        ui_reply(reply);
      };
      if (decision->generation != turn || turn != r.generation || !wss ||
          !shell::time_synchronized() ||
          decision->expires_at <= uint64_t(time(nullptr)) * 1000) {
        failed_decision();
        continue;
      }
      auto *p = cJSON_CreateObject();
      cJSON_AddStringToObject(p, "approval_id", decision->approval_id.c_str());
      cJSON_AddStringToObject(p, "action_hash", decision->action_hash.c_str());
      cJSON_AddStringToObject(p, "decision",
                              decision->approve ? "approve" : "deny");
      if (!emit("approval.decision", p, task))
        failed_decision();
    }
    if (turn && turn != r.generation) {
      if (wss && !task.empty()) {
        emit("audio.cancel", cJSON_CreateObject(), task);
        emit("task.cancel", cJSON_CreateObject(), task);
      }
      task.clear();
      speaker.clear();
      turn = 0;
    }
    if (blocked_audio && blocked_audio->generation != r.generation)
      blocked_audio.reset();
    Routed *ptr = nullptr;
    if (xQueueReceive(r.network, &ptr, pdMS_TO_TICKS(10)) == pdTRUE) {
      std::unique_ptr<Routed> job(ptr);
      if (job->request.generation == r.generation) {
        if (job->route.provider == Provider::homelab) {
          if (wss && send_request(*job, task)) {
            turn = job->request.generation;
            if (client_transcripts && job->request.audio &&
                !job->request.image) {
              awaiting_transcript = job->request;
              transcript_started_at = now_ms();
            }
          } else
            ui_reply(new Reply{job->request.generation, "", "",
                               "Se perdió la conexión con Muse."});
        } else {
          CloudProfile profile;
          bool loaded = false;
          if (xSemaphoreTake(r.status_mutex, portMAX_DELAY) == pdTRUE) {
            loaded = r.credentials.profile(job->route.provider, profile);
            xSemaphoreGive(r.status_mutex);
          }
          Reply reply{job->request.generation, "", "", ""};
          if (loaded && cloud_query(*job, profile, reply))
            ui_reply(new Reply(std::move(reply)));
          else if (job->request.generation == r.generation) {
            auto index = size_t(job->route.provider);
            retry_after[index] = ms + 30000;
            job->excluded |= 1u << index;
            if (xSemaphoreTake(r.status_mutex, portMAX_DELAY) == pdTRUE) {
              r.endpoints[index].reachable = false;
              xSemaphoreGive(r.status_mutex);
            }
            auto *retry = job.release();
            if (xQueueSend(r.requests, &retry, 0) != pdTRUE) {
              auto generation = retry->request.generation;
              delete retry;
              ui_reply(new Reply{generation, "", "",
                                 "No hay proveedores disponibles."});
            }
          }
        }
      }
    }
    if (!transport)
      continue;
    // Preserve exactly one unqueued frame, including audio.end, and retry.
    // Do not read newer packets until the audio task accepts it.
    if (blocked_audio) {
      auto *q = blocked_audio.get();
      if (xQueueSend(r.audio, &q, 0) != pdTRUE)
        continue;
      blocked_audio.release();
    }
    auto deliver_audio = [&](AudioCommand *q) {
      if (xQueueSend(r.audio, &q, 0) == pdTRUE)
        return true;
      blocked_audio.reset(q);
      return false;
    };
    shell::Packet packet;
    while (shell::receive(packet)) {
      if (packet.binary) {
        std::string session, id, stream;
        uint32_t n = 0;
        uint8_t kind = 0;
        if (packet.data.size() <= 57 ||
            !shell::media_header(packet.data.data(), packet.data.size(),
                                 session, id, stream, n, kind) ||
            session != shell::session_id() || id != task || stream != speaker ||
            turn != r.generation || kind != 3 || n != speaker_seq)
          continue;
        ++speaker_seq;
        if (!r.voice_enabled)
          continue;
        auto *q = new AudioCommand{AudioCommand::pcm, turn, {}};
        q->bytes.assign(packet.data.begin() + 57, packet.data.end());
        if (!deliver_audio(q))
          break;
        continue;
      }
      if (packet.data.size() > 32768)
        continue;
      if (!json_shape_safe(std::string(packet.data.begin(), packet.data.end()),
                           32768, 24))
        continue;
      packet.data.push_back(0);
      auto *m = cJSON_Parse(reinterpret_cast<const char *>(packet.data.data()));
      if (!m)
        continue;
      std::unique_ptr<cJSON, decltype(&cJSON_Delete)> json(m, cJSON_Delete);
      if (field(m, "session_id") != shell::session_id())
        continue;
      auto *seq = cJSON_GetObjectItem(m, "sequence");
      uint64_t message_sequence = 0;
      bool valid_sequence = false;
      if (cJSON_IsNumber(seq) && std::isfinite(seq->valuedouble) &&
          seq->valuedouble >= 0 && seq->valuedouble <= 9007199254740991.0 &&
          seq->valuedouble == std::floor(seq->valuedouble)) {
        auto n = uint64_t(seq->valuedouble);
        message_sequence = n;
        valid_sequence = true;
        if (n > incoming) {
          incoming = n;
          shell::last_sequence(n);
        }
      }
      auto id = field(m, "task_id");
      if (!id.empty() && (id != task || turn != r.generation))
        continue;
      auto type = field(m, "type");
      auto *p = cJSON_GetObjectItem(m, "payload");
      if (type == "ota.offer" && id.empty()) {
        auto *raw = cJSON_PrintUnformatted(p);
        if (raw) {
          if (strlen(raw) <= 6144) {
            auto *offer = new UpdateOffer{raw};
            if (xQueueSend(r.updates, &offer, 0) != pdTRUE)
              delete offer;
          }
          cJSON_free(raw);
        }
        continue;
      }
      if (type != "device.settings" && type != "device.snapshot" &&
          (id.empty() || !turn || turn != r.generation))
        continue;
      if (type == "device.settings" || type == "device.snapshot") {
        client_transcripts = field(p, "transcript_routing") == "client";
        settings_at = ms;
        muse_available = false;
        auto *agents = cJSON_GetObjectItem(p, "agents");
        for (auto *a = agents ? agents->child : nullptr; a; a = a->next)
          if (field(a, "id") == "muse")
            muse_available = cJSON_IsTrue(cJSON_GetObjectItem(a, "available"));
        DeviceStatus status;
        status.weather = weather_packet(p, ms);
        status.received_at = ms;
        auto choices = [&](const char *key, const char *name,
                           std::vector<DeviceChoice> &out) {
          auto *list = cJSON_GetObjectItem(p, key);
          if (!cJSON_IsArray(list))
            return;
          for (auto *item = list->child; item && out.size() < 16;
               item = item->next) {
            auto value = field(item, name);
            if (!strcmp(key, "nodes") && value != "mac-mini" &&
                value != "tuf-infra")
              continue;
            if (!value.empty() && value.size() <= 32 &&
                value.find_first_not_of(
                    "abcdefghijklmnopqrstuvwxyz0123456789-_") ==
                    std::string::npos)
              out.push_back({value, cJSON_IsTrue(cJSON_GetObjectItem(
                                        item, "available")) != 0});
          }
        };
        choices("agents", "id", status.agents);
        choices("nodes", "node", status.nodes);
        auto *tasks = cJSON_GetObjectItem(p, "tasks");
        if (cJSON_IsArray(tasks) && tasks->child) {
          status.task_id = field(tasks->child, "task_id");
          status.task_state = field(tasks->child, "state");
          status.task_summary = field(tasks->child, "summary").substr(0, 1024);
        }
        if (xSemaphoreTake(r.status_mutex, portMAX_DELAY) == pdTRUE) {
          if (type == "device.settings") {
            status.task_id = r.device_status.task_id;
            status.task_state = r.device_status.task_state;
            status.task_summary = r.device_status.task_summary;
          }
          r.device_status = std::move(status);
          r.status_revision.fetch_add(1);
          xSemaphoreGive(r.status_mutex);
        }
        auto *preferences = cJSON_GetObjectItem(p, "preferences");
        bool changed = false;
        auto set = [&](const char *key, std::atomic<bool> &value) {
          auto *entry = cJSON_GetObjectItem(preferences, key);
          if (cJSON_IsBool(entry)) {
            const bool enabled = cJSON_IsTrue(entry);
            const bool altered = value.exchange(enabled) != enabled;
            changed |= altered;
            if (altered && !strcmp(key, "voice_enabled")) {
              if (enabled)
                resume_voice();
              else
                stop_voice();
            }
          }
        };
        set("voice_enabled", r.voice_enabled);
        set("pet_enabled", r.pet_enabled);
        set("pet_sounds", r.pet_sounds);
        set("pet_sensors", r.pet_sensors);
        if (changed)
          r.remote_preferences_dirty = true;
        if (type == "device.snapshot") {
          auto *head = cJSON_GetObjectItem(p, "sequence");
          if (!cJSON_IsNumber(head) || !std::isfinite(head->valuedouble) ||
              head->valuedouble < 0 || head->valuedouble > 9007199254740991.0 ||
              head->valuedouble != std::floor(head->valuedouble))
            continue;
          const auto recovery_audio_floor = uint64_t(head->valuedouble);
          audio_start_gate.recover(recovery_audio_floor);
          shell::last_sequence(recovery_audio_floor);
          snapshot_waits_clock = !shell::time_synchronized();
          auto *raw = cJSON_PrintUnformatted(p);
          RecoverySnapshot recovered;
          const bool valid =
              raw && parse_recovery_snapshot(
                         raw, uint64_t(time(nullptr)) * 1000, recovered);
          cJSON_free(raw);
          // Reconnection retains the foreground turn selected on this Core.
          // A reboot may restore recent owned history, but a new local voice,
          // camera or offline turn must never be overwritten by old history.
          if (valid && !task.empty() && turn == r.generation &&
              recovered.task_id != task) {
            if (resume_requested_session != shell::session_id() &&
                emit("device.resume", cJSON_CreateObject(), task))
              resume_requested_session = shell::session_id();
          } else if (valid &&
                     ((turn == r.generation && recovered.task_id == task) ||
                      (task.empty() && r.generation == 1 && !r.recording &&
                       !r.camera_open && !r.camera_capturing))) {
            task = recovered.task_id;
            turn = r.generation;
            speaker.clear();
            speaker_seq = 0;
            full_text.clear();
            last_brief = recovered.summary;
            if (!recovered.approval_id.empty() && shell::time_synchronized()) {
              ui_reply(new Reply{
                  turn, "Autorización pendiente. Revisa la solicitud.",
                  recovered.action + "\nHash: " + recovered.action_hash, "",
                  recovered.approval_id, recovered.action_hash,
                  recovered.expires_at});
              post_turn(EventKind::approval, turn);
            } else {
              auto *reply =
                  new Reply{turn, recovered.summary, recovered.summary, ""};
              reply->clear_approval = true;
              ui_reply(reply);
              post_turn(recovered.state == "running" ||
                                recovered.state == "queued" ||
                                recovered.state == "reconciling"
                            ? EventKind::work
                        : recovered.state == "failed" ||
                                recovered.state == "interrupted"
                            ? EventKind::offline
                            : EventKind::done,
                        turn);
              if (recovered.state == "completed")
                emit("task.read", cJSON_CreateObject(), task);
            }
          }
        }
      } else if (type == "approval.result") {
        const auto aid = field(p, "approval_id");
        if (!valid_uuid(aid))
          continue;
        auto *reply = new Reply{turn};
        reply->decision_id = aid;
        reply->decision_ok = field(p, "status") == "accepted";
        ui_reply(reply);
      } else if (type == "error") {
        ui_reply(
            new Reply{turn, "", "",
                      "El gateway rechazó la solicitud. Revisa la conexión."});
        post_turn(EventKind::offline, turn);
      } else if (type == "task.state") {
        auto summary = field(p, "summary"), state = field(p, "state");
        if (xSemaphoreTake(r.status_mutex, portMAX_DELAY) == pdTRUE) {
          r.device_status.task_id = id;
          r.device_status.task_state = state.substr(0, 32);
          r.device_status.task_summary = summary.substr(0, 1024);
          r.status_revision.fetch_add(1);
          xSemaphoreGive(r.status_mutex);
        }
        if (!summary.empty()) {
          last_brief = summary;
          full_text.clear();
        }
        if (!summary.empty()) {
          auto *reply = new Reply{turn, summary, summary, ""};
          reply->clear_approval = state == "completed" || state == "failed" ||
                                  state == "canceled" || state == "interrupted";
          ui_reply(reply);
        }
        if (state == "completed") {
          emit("task.read", cJSON_CreateObject(), task);
          post_turn(EventKind::done, turn);
        } else if (state == "failed")
          post_turn(EventKind::offline, turn);
      } else if (type == "ui.result") {
        auto *offset = cJSON_GetObjectItem(p, "offset");
        auto text = field(p, "text");
        if (!cJSON_IsNumber(offset) || offset->valueint < 0 ||
            offset->valuedouble != offset->valueint)
          continue;
        if (offset->valueint == 0)
          full_text.clear();
        if (size_t(offset->valueint) != full_text.size() ||
            full_text.size() + text.size() > 32768)
          continue;
        full_text += text;
        ui_reply(new Reply{turn, last_brief, full_text, ""});
      } else if (type == "ui.state")
        post_turn(field(p, "mode") == "executing" ? EventKind::work
                                                  : EventKind::think,
                  turn);
      else if (type == "approval.request") {
        auto *action = cJSON_GetObjectItem(p, "action");
        auto *raw = cJSON_Print(action);
        std::string text = raw ? raw : "Acción pendiente";
        cJSON_free(raw);
        auto hash = field(p, "action_hash"), aid = field(p, "approval_id");
        auto *expiry = cJSON_GetObjectItem(p, "expires_at");
        const uint64_t epoch_ms = uint64_t(time(nullptr)) * 1000;
        if (!cJSON_IsObject(action) || text.size() > 16000 ||
            hash.size() != 64 ||
            hash.find_first_not_of("0123456789abcdef") != std::string::npos ||
            !valid_uuid(aid) || !shell::time_synchronized() ||
            !cJSON_IsNumber(expiry) || !std::isfinite(expiry->valuedouble) ||
            expiry->valuedouble != std::floor(expiry->valuedouble) ||
            expiry->valuedouble <= double(epoch_ms) ||
            expiry->valuedouble > double(epoch_ms) + 86400000)
          continue;
        uint64_t expires = uint64_t(expiry->valuedouble);
        ui_reply(new Reply{turn, "Autorización pendiente. Revisa la solicitud.",
                           text + "\nHash: " + hash, "", aid, hash, expires});
        post_turn(EventKind::approval, turn);
      } else if (type == "voice.transcript") {
        if (!awaiting_transcript)
          continue;
        Request request;
        if (!transcript_request(*awaiting_transcript, field(p, "text"),
                                r.generation, request))
          continue;
        awaiting_transcript.reset();
        // The upload UUID is only an ephemeral STT request; no remote task was
        // created. Re-route once on this Core. A homelab decision submits a new
        // durable UUID; a local decision never invokes Muse/tools.
        task.clear();
        turn = 0;
        if (!submit(new Request(std::move(request))))
          ui_reply(new Reply{r.generation, "", "",
                             "Cola ocupada. Inténtalo de nuevo."});
      } else if (type == "audio.start") {
        if (id.empty() || !valid_sequence || !r.voice_enabled ||
            r.stopped_audio_generation == turn)
          continue;
        auto *rate = cJSON_GetObjectItem(p, "sample_rate"),
             *channels = cJSON_GetObjectItem(p, "channels");
        if ((rate && rate->valueint != 16000) ||
            (channels && channels->valueint != 1))
          continue;
        const auto candidate = field(p, "stream_id");
        if (!valid_uuid(candidate))
          continue;
        auto *control = cJSON_GetObjectItem(p, "control_sequence");
        const bool has_control = control != nullptr;
        if (has_control &&
            (!cJSON_IsNumber(control) || !std::isfinite(control->valuedouble) ||
             control->valuedouble < 1 ||
             control->valuedouble > 9007199254740991.0 ||
             control->valuedouble != std::floor(control->valuedouble)))
          continue;
        const bool explicit_replay =
            cJSON_IsTrue(cJSON_GetObjectItem(p, "explicit_replay"));
        if (!audio_start_gate.accept(
                message_sequence, explicit_replay, has_control,
                has_control ? uint64_t(control->valuedouble) : 0))
          continue;
        speaker = candidate;
        speaker_seq = 0;
      } else if (type == "audio.end") {
        if (field(p, "stream_id") == speaker)
          if (!deliver_audio(
                  new AudioCommand{AudioCommand::end_stream, turn, {}}))
            break;
      } else if (type == "audio.stop") {
        speaker.clear();
        audio_send(new AudioCommand{AudioCommand::stop, turn, {}});
        post_turn(EventKind::done, turn);
      }
    }
  }
}
} // namespace sagwa
