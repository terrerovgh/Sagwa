#include "scene.hpp"
#include "inter.hpp"
#include <algorithm>
namespace shell {
unsigned next_codepoint(const std::string &s, size_t &i) {
  unsigned c = uint8_t(s[i++]);
  if (c < 128)
    return c;
  unsigned n = (c & 0xe0) == 0xc0 ? 1 : (c & 0xf0) == 0xe0 ? 2 : 3;
  c &= n == 1 ? 31 : n == 2 ? 15 : 7;
  while (n-- && i < s.size())
    c = (c << 6) | (uint8_t(s[i++]) & 63);
  return c;
}
unsigned text_width(const std::string &s, unsigned size) {
  unsigned w = 0;
  for (size_t i = 0; i < s.size();)
    w += glyph(next_codepoint(s, i), size).advance;
  return w;
}
const std::vector<std::string> &wrap_text(const std::string &s, unsigned width,
                                          unsigned size) {
  static std::string cached_text;
  static unsigned cached_width = 0, cached_size = 0;
  static std::vector<std::string> lines;
  if (s == cached_text && width == cached_width && size == cached_size)
    return lines;
  cached_text = s;
  cached_width = width;
  cached_size = size;
  lines.clear();
  std::string row;
  unsigned w = 0;
  size_t break_at = std::string::npos;
  for (size_t i = 0; i < s.size();) {
    size_t begin = i;
    unsigned c = next_codepoint(s, i);
    if (c == '\r')
      continue;
    if (c == '\n') {
      lines.push_back(row);
      row.clear();
      w = 0;
      break_at = std::string::npos;
      continue;
    }
    unsigned a = glyph(c, size).advance;
    if (w + a > width && !row.empty()) {
      if (break_at != std::string::npos) {
        lines.push_back(row.substr(0, break_at));
        row.erase(0, break_at + 1);
        w = text_width(row, size);
      } else {
        lines.push_back(row);
        row.clear();
        w = 0;
      }
      break_at = std::string::npos;
    }
    if (c == ' ' && row.empty())
      continue;
    if (c == ' ')
      break_at = row.size();
    row += s.substr(begin, i - begin);
    w += a;
  }
  if (!row.empty() || lines.empty())
    lines.push_back(row);
  return lines;
}
unsigned text_lines(const std::string &s, unsigned width, unsigned size) {
  return wrap_text(s, width, size).size();
}
bool agent_available(const View &v, const std::string &id) {
  return std::any_of(v.agents.begin(), v.agents.end(), [&](const Choice &a) {
    return a.id == id && a.available;
  });
}
bool auto_available(const View &v) { return agent_available(v, "muse"); }
bool voice_available(const View &v) {
  return v.connected && v.settings_ready &&
         (v.preferred == "auto" ? auto_available(v)
                                : agent_available(v, v.preferred));
}
std::string agent_label(const std::string &s) {
  return s == "auto"       ? "Muse · automático"
         : s == "muse"     ? "Sagwa · Muse"
         : s == "codex"    ? "Codex"
         : s == "opencode" ? "OpenCode"
         : s == "claude"   ? "Claude"
         : s == "grok"     ? "Grok"
         : s == "hermes"   ? "Hermes"
                           : s;
}
std::string node_label(const std::string &s) {
  return s == "mac-mini"    ? "Mac mini"
         : s == "tuf-infra" ? "TUF"
         : s == "lenlab"    ? "Lenovo"
                            : s;
}
std::string activity_label(const std::string &s) {
  return s == "conversation"     ? "Conversación"
         : s == "infra.diagnose" ? "Diagnóstico"
                                 : "Código";
}
const char *page_name(Page p) {
  const char *n[] = {"home",  "options", "agents", "destinations", "activities",
                     "photo", "cancel",  "reader", "settings",     "sensors",
                     "voice", "pet",     "tasks",  "credits",      "error"};
  return n[unsigned(p)];
}
std::vector<Row> page_rows(const View &v) {
  switch (v.page) {
  case Page::options:
    return {{"home", "Conversación", "Sagwa está aquí"},
            {"tasks", "Tareas",
             v.task_active ? "Una tarea en curso" : "Sin tareas activas"},
            {"agents", "Agentes", agent_label(v.preferred)},
            {"destinations", "Destino", node_label(v.target)},
            {"settings", "Configuración", "Voz y mascota"}};
  case Page::settings:
    return {{"voice", "Voz", "Femenina · español"},
            {"pet", "Mascota", "Gestos y sensores"},
            {"sensors", "Sensores", "Lecturas locales"},
            {"credits", "Acerca de Sagwa", "Origen y licencias"}};
  case Page::agents: {
    std::vector<Row> r;
    for (const auto &id :
         {"muse", "auto", "codex", "opencode", "claude", "grok", "hermes"}) {
      bool a = std::string(id) == "auto" ? auto_available(v)
                                         : agent_available(v, id);
      r.push_back({id, agent_label(id),
                   a ? (v.preferred == id ? "Seleccionado" : "Disponible")
                     : "No disponible",
                   a});
    }
    return r;
  }
  case Page::destinations: {
    std::vector<Row> r;
    for (const auto &a :
         (v.capability == "code.change" ? v.repositories : v.nodes))
      r.push_back({a.id, a.label,
                   a.available
                       ? (v.target == a.id ? "Seleccionado" : "Disponible")
                       : "Sin conexión",
                   a.available});
    return r;
  }
  case Page::activities:
    return {{"conversation", "Conversación", "Hablar con Sagwa",
             voice_available(v)},
            {"camera", "Cámara", "Vista previa antes de enviar"},
            {"sensors", "Sensores", "Luz, proximidad y movimiento"},
            {"infra.diagnose", "Diagnóstico",
             v.connected ? "Equipos autorizados" : "Sin conexión", v.connected},
            {"code.change", "Código",
             v.repositories.empty() ? "Sin repositorios"
                                    : "Repositorios autorizados",
             v.connected && !v.repositories.empty()}};
  case Page::voice:
    return {{"voice_enabled", "Leer respuestas",
             v.voice_enabled ? "Activado" : "Desactivado"},
            {"voice_sample", "Escuchar muestra", "Voz femenina en español",
             v.connected},
            {"voice_info", "Motores", "TUF → Mac mini → API"},
            {"voice_budget", "Presupuesto API", "Máximo US$5 al mes"}};
  case Page::pet:
    return {{"pet_enabled", "Reacciones",
             v.pet_enabled ? "Activadas" : "Desactivadas"},
            {"pet_sounds", "Sonidos",
             v.pet_sounds ? "Suaves · activados" : "Desactivados"},
            {"pet_sensors", "Responder a sensores",
             v.pet_sensors ? "Activado" : "Desactivado"},
            {"pet_demo", "Acariciar a Sagwa", "Ronroneo"}};
  case Page::tasks:
    return {
        {"reader", "Leer resultado",
         v.task_active ? "En curso" : "Última respuesta"},
        {"cancel", "Cancelar tarea",
         v.task_active ? "Confirmar antes de cancelar" : "Sin tareas activas",
         v.task_active}};
  default:
    return {};
  }
}
std::string reading_text(const View &v) {
  if (v.page == Page::reader)
    return v.full_text.empty() ? v.text : v.full_text;
  if (v.page == Page::sensors)
    return v.sensor_text;
  if (v.page == Page::credits)
    return "Sagwa · tu mascota\nSprites: Imagegen\nOriginales: Muse\nInter: "
           "SIL OFL\nEmoji: Google Noto · CC BY 4\nRonroneo: Peter Hull\nCC "
           "BY-SA 4.0 · recortado\nMaullido: Dan Crosby\nCC BY-SA 3.0 · "
           "recortado\nFuentes y enlaces: proyecto";
  return v.text;
}
void compose(Frame &f, const View &v, uint32_t, const std::string &) {
  f.clear();
  auto put = [&](int x, int y, unsigned size, const std::string &s) {
    if (!s.empty())
      f.push_back({x, y, size, s});
  };
  auto lines = [&](const std::string &s, int y, unsigned size, unsigned count,
                   unsigned scroll) {
    const auto &rows = wrap_text(s, 288, size);
    unsigned start = std::min(
        scroll, rows.size() > count ? unsigned(rows.size() - count) : 0u);
    for (unsigned n = 0; n < count && start + n < rows.size(); n++)
      put(16, y + n * (size + 6), size, rows[start + n]);
  };
  if (!v.approval_id.empty()) {
    put(16, 12, 20, "Autorizar acción");
    lines(v.text, 44, 16, 6, v.scroll);
    put(16, 202, 16, "Denegar");
    put(172, 202, 16, v.approval_hold_ms ? "Mantén…" : "Mantén 1,5 s");
    return;
  }
  if (v.page == Page::home) {
    lines(v.text, 158, 16, 3, v.scroll);
    return;
  }
  const char *titles[] = {
      "",       "Menú",           "Agentes",   "Destino",       "Herramientas",
      "Cámara", "Cancelar tarea", "Respuesta", "Configuración", "Sensores",
      "Voz",    "Mascota",        "Tareas",    "Sagwa",         "Atención"};
  put(16, 12, 20, titles[unsigned(v.page)]);
  if (v.camera)
    put(224, 16, 12, "Cámara activa");
  else if (v.microphone)
    put(224, 16, 12, "Micrófono");
  if (v.page == Page::reader) {
    lines(v.full_text.empty() ? v.text : v.full_text, 48, 20, 7, v.scroll);
    return;
  }
  if (v.page == Page::photo) {
    put(16, 174, 12,
        v.photo_ready ? "Solo se envía al tocar Enviar" : "Capturando…");
    put(16, 206, 16, "Descartar");
    put(204, 206, 16, v.photo_ready ? "Enviar foto" : "Reintentar");
    return;
  }
  if (v.page == Page::cancel) {
    lines("¿Quieres cancelar la tarea?", 58, 20, 3, 0);
    put(16, 154, 12, "Se detendrá también la voz.");
    put(16, 206, 16, "Volver");
    put(208, 206, 16, "Cancelar");
    return;
  }
  if (v.page == Page::sensors) {
    lines(v.sensor_text.empty() ? "Sensores no disponibles" : v.sensor_text, 48,
          16, 8, v.scroll);
    return;
  }
  if (v.page == Page::credits) {
    lines(reading_text(v), 48, 16, 8, v.scroll);
    return;
  }
  if (v.page == Page::error) {
    lines(v.text, 48, 20, 6, v.scroll);
    return;
  }
  auto rows = page_rows(v);
  unsigned start =
      std::min(v.menu_scroll, rows.size() > 4 ? unsigned(rows.size() - 4) : 0u);
  for (unsigned i = 0; i < 4 && start + i < rows.size(); i++) {
    const auto &r = rows[start + i];
    put(16, 51 + i * 44, 16, r.label);
    put(16, 73 + i * 44, 12, r.detail);
  }
  if (!v.notice.empty())
    put(16, 225, 12, v.notice.substr(0, 48));
}
unsigned status_icon(const View &v) {
  if (v.camera)
    return 8;
  if (v.microphone || v.mode == "listening")
    return 1;
  if (!v.approval_id.empty() || v.mode == "approval")
    return 5;
  if (v.mode == "warning")
    return 6;
  if (!v.connected || v.mode == "offline")
    return 7;
  if (v.speaker || v.mode == "speaking")
    return 4;
  if (v.mode == "thinking")
    return 2;
  if (v.task_active || v.mode == "working" || v.mode == "executing" ||
      v.mode == "delegating")
    return 3;
  return 0;
}
Graphic select_sagwa_graphic(const View &v, uint32_t ms) {
  unsigned p = v.pet_pose;
  if (v.microphone)
    p = 2;
  else if (v.speaker)
    p = 4;
  else if (v.mode == "thinking")
    p = 3;
  else if (v.task_active)
    p = 5;
  else if (v.mode == "milestone")
    p = 6;
  return {p, unsigned(ms / 250) % 4, -1, 0};
}
Graphic select_graphic(const View &v, uint32_t ms) {
  return select_sagwa_graphic(v, ms);
}
} // namespace shell
