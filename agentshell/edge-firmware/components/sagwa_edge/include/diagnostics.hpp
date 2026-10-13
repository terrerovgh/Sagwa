#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string>

namespace sagwa {
// UI-owned, volatile history. Producers already enter through FreeRTOS queues
// or atomic state; never write this ring from a worker or interrupt handler.
// Only fixed event codes are accepted: no prompts, transcripts or credentials.
enum class DiagnosticKind : uint8_t {
  started, gateway_connected, gateway_disconnected, listening, mic_stopped,
  speaking, voice_stopped, wake, working, completed, query_failed, cancelled,
  approval_required, decision_received, decision_failed, skin_loaded,
  skin_rejected, camera_ready, camera_failed, shake
};
inline const char *diagnostic_label(DiagnosticKind kind) {
  switch (kind) {
  case DiagnosticKind::started: return "Interfaz iniciada";
  case DiagnosticKind::gateway_connected: return "Canal conectado";
  case DiagnosticKind::gateway_disconnected: return "Canal sin conexión";
  case DiagnosticKind::listening: return "Micrófono activo";
  case DiagnosticKind::mic_stopped: return "Micrófono apagado";
  case DiagnosticKind::speaking: return "Reproduciendo voz";
  case DiagnosticKind::voice_stopped: return "Voz detenida";
  case DiagnosticKind::wake: return "Mascota despierta";
  case DiagnosticKind::working: return "Procesando solicitud";
  case DiagnosticKind::completed: return "Respuesta recibida";
  case DiagnosticKind::query_failed: return "Solicitud fallida";
  case DiagnosticKind::cancelled: return "Conversación cancelada";
  case DiagnosticKind::approval_required: return "Autorización pendiente";
  case DiagnosticKind::decision_received: return "Decisión confirmada";
  case DiagnosticKind::decision_failed: return "Decisión sin confirmar";
  case DiagnosticKind::skin_loaded: return "Apariencia cargada";
  case DiagnosticKind::skin_rejected: return "Apariencia rechazada";
  case DiagnosticKind::camera_ready: return "Foto local preparada";
  case DiagnosticKind::camera_failed: return "Captura fallida";
  case DiagnosticKind::shake: return "Sacudida detectada";
  }
  return "Evento desconocido";
}
class DiagnosticHistory {
public:
  static constexpr size_t capacity = 64;
  struct Entry { DiagnosticKind kind{}; uint32_t at = 0; };
  bool push(DiagnosticKind kind, uint32_t at) {
    // Coalesce repeated notifications, including across millis() wrap.
    if (count_ && entries_[(head_ + capacity - 1) % capacity].kind == kind &&
        at - entries_[(head_ + capacity - 1) % capacity].at < 250)
      return false;
    entries_[head_] = {kind, at};
    head_ = (head_ + 1) % capacity;
    if (count_ < capacity) ++count_;
    return true;
  }
  size_t size() const { return count_; }
  const Entry *newest(size_t offset = 0) const {
    return offset < count_ ? &entries_[(head_ + capacity - 1 - offset) % capacity]
                           : nullptr;
  }
  std::string text(size_t limit = capacity) const {
    std::string result;
    for (size_t i = 0; i < count_ && i < limit; ++i) {
      const auto &entry = *newest(i);
      const auto seconds = entry.at / 1000;
      char stamp[32];
      snprintf(stamp, sizeof stamp, "%02lu:%02lu:%02lu  ",
               (unsigned long)(seconds / 3600),
               (unsigned long)(seconds / 60 % 60),
               (unsigned long)(seconds % 60));
      if (i) result += '\n';
      result += stamp;
      result += diagnostic_label(entry.kind);
    }
    return result.empty() ? "Sin eventos locales." : result;
  }
private:
  std::array<Entry, capacity> entries_{};
  size_t head_ = 0, count_ = 0;
};
} // namespace sagwa
