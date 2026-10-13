#include "cJSON.h"
#include "edge.hpp"
#include <algorithm>
#include <cmath>
#include <complex>
#include <cstring>
#include <fstream>
#include <memory>
namespace sagwa {
bool transcript_request(const Request &captured, const std::string &text,
                        uint32_t generation, Request &out) {
  if (!captured.audio || captured.image || captured.generation != generation ||
      text.empty() || text.size() > 4096 ||
      text.find('\0') != std::string::npos ||
      std::all_of(text.begin(), text.end(), [](unsigned char c) {
        return c == ' ' || c == '\t' || c == '\n' || c == '\r';
      }))
    return false;
  out =
      captured; // Preserve the destination, capability and privacy at capture.
  out.audio = false;
  out.text = text;
  return true;
}
bool json_shape_safe(const std::string &text, size_t max_bytes,
                     size_t max_depth) {
  if (text.size() > max_bytes)
    return false;
  bool quoted = false, escape = false;
  size_t depth = 0;
  for (unsigned char c : text) {
    if (quoted) {
      if (escape)
        escape = false;
      else if (c == '\\')
        escape = true;
      else if (c == '"')
        quoted = false;
    } else if (c == '"')
      quoted = true;
    else if (c == '{' || c == '[') {
      if (++depth > max_depth)
        return false;
    } else if (c == '}' || c == ']') {
      if (!depth)
        return false;
      --depth;
    }
  }
  return !quoted && !depth;
}

bool valid_uuid(const std::string &text) {
  if (text.size() != 36)
    return false;
  for (size_t i = 0; i < text.size(); ++i) {
    if (i == 8 || i == 13 || i == 18 || i == 23) {
      if (text[i] != '-')
        return false;
    } else if (std::string("0123456789abcdefABCDEF").find(text[i]) ==
               std::string::npos)
      return false;
  }
  return true;
}
bool parse_recovery_snapshot(const std::string &text, uint64_t now_epoch_ms,
                             RecoverySnapshot &out) {
  out = {};
  if (!json_shape_safe(text, 32768, 24))
    return false;
  std::unique_ptr<cJSON, decltype(&cJSON_Delete)> root(
      cJSON_ParseWithLengthOpts(text.c_str(), text.size() + 1, nullptr, true),
      cJSON_Delete);
  if (!root || !cJSON_IsObject(root.get()))
    return false;
  auto field = [](const cJSON *object, const char *key) -> std::string {
    const char *value =
        cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(object, key));
    return value ? value : "";
  };
  auto *tasks = cJSON_GetObjectItemCaseSensitive(root.get(), "tasks");
  if (!cJSON_IsArray(tasks) || cJSON_GetArraySize(tasks) > 5)
    return false;
  const auto selected = field(root.get(), "foreground_task_id");
  if (!selected.empty() && !valid_uuid(selected))
    return false;
  const cJSON *task = nullptr;
  for (auto *item = tasks->child; item; item = item->next)
    if ((selected.empty() && item == tasks->child) ||
        field(item, "task_id") == selected) {
      task = item;
      break;
    }
  if (!task)
    return false;
  out.task_id = field(task, "task_id");
  out.state = field(task, "state");
  out.summary = field(task, "summary");
  const std::array<std::string, 8> states = {
      "queued", "running",  "needs_approval", "completed",
      "failed", "canceled", "interrupted",    "reconciling"};
  if (!valid_uuid(out.task_id) || out.summary.size() > 4096 ||
      std::find(states.begin(), states.end(), out.state) == states.end()) {
    out = {};
    return false;
  }
  auto *approvals = cJSON_GetObjectItemCaseSensitive(root.get(), "approvals");
  if (out.state != "queued" && out.state != "running" &&
      out.state != "needs_approval" && out.state != "reconciling")
    return true;
  if (!cJSON_IsArray(approvals) || cJSON_GetArraySize(approvals) > 5)
    return true;
  for (auto *item = approvals->child; item; item = item->next) {
    auto *action = cJSON_GetObjectItemCaseSensitive(item, "action");
    const auto task_id = field(item, "task_id");
    if ((!task_id.empty() ? task_id : field(action, "task_id")) !=
            out.task_id ||
        !cJSON_IsObject(action) ||
        !cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(item, "consumed")) ||
        !cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(item, "denied")))
      continue;
    auto *physical = cJSON_GetObjectItemCaseSensitive(item, "physical_by");
    if (physical && !cJSON_IsNull(physical))
      continue;
    auto aid = field(item, "approval_id"), hash = field(item, "action_hash");
    auto *expiry = cJSON_GetObjectItemCaseSensitive(item, "expires_at");
    if (!valid_uuid(aid) || hash.size() != 64 ||
        hash.find_first_not_of("0123456789abcdef") != std::string::npos ||
        !cJSON_IsNumber(expiry) || !std::isfinite(expiry->valuedouble) ||
        expiry->valuedouble != std::floor(expiry->valuedouble) ||
        expiry->valuedouble <= double(now_epoch_ms) ||
        expiry->valuedouble > double(now_epoch_ms) + 86400000)
      continue;
    auto *raw = cJSON_Print(action);
    if (!raw)
      continue;
    std::string serialized = raw;
    cJSON_free(raw);
    if (serialized.size() > 16000)
      continue;
    out.approval_id = std::move(aid);
    out.action_hash = std::move(hash);
    out.action = std::move(serialized);
    out.expires_at = uint64_t(expiry->valuedouble);
    break;
  }
  return true;
}

static float clamp(float x, float lo, float hi) {
  return std::max(lo, std::min(hi, x));
}
uint32_t AnimationFSM::random() {
  seed_ ^= seed_ << 13;
  seed_ ^= seed_ >> 17;
  seed_ ^= seed_ << 5;
  return seed_;
}
void AnimationFSM::transition(Emotion s, uint32_t ms, uint32_t hold) {
  if (s != state_) {
    state_ = s;
    since_ = ms;
    blend_ = 0;
  }
  until_ = hold ? ms + hold : 0;
}
void AnimationFSM::event(const Event &e) {
  switch (e.kind) {
  case EventKind::listen:
    transition(Emotion::listening, e.at);
    break;
  case EventKind::think:
    transition(Emotion::thinking, e.at);
    break;
  case EventKind::work:
    transition(Emotion::working, e.at);
    break;
  case EventKind::speak:
    transition(Emotion::speaking, e.at);
    break;
  case EventKind::offline:
    transition(Emotion::error, e.at, 2200);
    break;
  case EventKind::sleep:
    if (state_ == Emotion::idle || state_ == Emotion::purring ||
        state_ == Emotion::tilted)
      transition(Emotion::sleeping, e.at);
    break;
  case EventKind::stretch:
    transition(Emotion::stretching, e.at, 1600);
    break;
  case EventKind::celebrate:
    transition(Emotion::celebrating, e.at, 1800);
    break;
  case EventKind::wake:
    if (state_ == Emotion::idle || state_ == Emotion::sleeping ||
        state_ == Emotion::purring || state_ == Emotion::tilted)
      transition(Emotion::waking, e.at, 500);
    break;
  case EventKind::done:
  case EventKind::cancel:
    transition(Emotion::idle, e.at);
    break;
  case EventKind::stroke:
    if (state_ == Emotion::idle || state_ == Emotion::purring)
      transition(Emotion::purring, e.at, 1800);
    break;
  case EventKind::touch:
    target_x_ = clamp(e.x, -1, 1);
    target_y_ = clamp(e.y, -1, 1);
    break;
  case EventKind::shake:
    if (state_ == Emotion::idle)
      transition(Emotion::alert, e.at, 1400);
    break;
  case EventKind::tilt:
    if (state_ == Emotion::idle)
      transition(Emotion::tilted, e.at, 900);
    break;
  default:
    break;
  }
}
Pose AnimationFSM::step(uint32_t ms, const SensorSnapshot &s,
                        const std::array<float, 3> &bands, float breath_hz) {
  if (until_ && int32_t(ms - until_) >= 0)
    transition(Emotion::idle, ms);
  float dt =
      previous_ ? clamp(float(ms - previous_) / 1000, .001f, .05f) : .033f;
  previous_ = ms;
  if (!next_blink_)
    next_blink_ = ms + 1800 + random() % 4200;
  if (int32_t(ms - next_blink_) >= 0) {
    blink_at_ = ms;
    next_blink_ = ms + 2200 + random() % 4800;
  }
  float t = clamp(float(ms - since_) / 220, 0, 1);
  blend_ = t * t * (3 - 2 * t);
  gaze_x_ += (target_x_ - gaze_x_) * (1 - std::exp(-dt * 12));
  gaze_y_ += (target_y_ - gaze_y_) * (1 - std::exp(-dt * 12));
  if (state_ == Emotion::sleeping)
    breath_hz = .12f;
  Pose p;
  p.breath = 1 + .018f * std::sin(ms * .001f * 6.2831853f * breath_hz);
  p.blink = blink_at_ && ms - blink_at_ < 140
                ? std::abs(1 - float(ms - blink_at_) / 70)
                : 1;
  if (state_ == Emotion::sleeping)
    p.blink = .04f;
  p.gaze_x = gaze_x_ * .75f + std::sin(ms * .00025f) * .12f;
  p.gaze_y = gaze_y_ * .7f;
  bool fresh = s.imu && ms - s.at <= 250;
  p.lean = fresh ? clamp(s.ay * .1f, -.15f, .15f) : 0;
  float ears = state_ == Emotion::alert || state_ == Emotion::listening ? .18f
               : state_ == Emotion::purring                             ? -.13f
                                                                        : 0;
  ear_left_ += (ears + std::sin(ms * .0007f) * .035f - ear_left_) *
               (1 - std::exp(-dt * 10));
  ear_right_ += (ears - std::sin(ms * .0009f) * .025f - ear_right_) *
                (1 - std::exp(-dt * 10));
  p.ear_left = ear_left_;
  p.ear_right = ear_right_;
  float target = std::sin(ms * .0014f) * .18f +
                 (state_ == Emotion::speaking ? bands[0] * .2f : 0);
  velocity_ += (target - tail_) * 30 * dt;
  velocity_ *= std::exp(-8 * dt);
  tail_ += velocity_ * dt;
  p.tail = tail_;
  stretch_ +=
      ((state_ == Emotion::stretching ? 1 + .08f * blend_ : 1) - stretch_) *
      (1 - std::exp(-dt * 8));
  p.stretch = stretch_;
  p.mouth =
      state_ == Emotion::speaking ? clamp(bands[0] + bands[1], 0, .8f) : 0;
  return p;
}
std::array<Skin, 10> builtin_skins() {
  const char *ids[] = {"pet",      "focus",    "telemetry",  "night",
                       "sentinel", "terminal", "multimedia", "assistant",
                       "weather",  "recovery"};
  const char *names[] = {"Mascota",   "Enfoque",     "Telemetría", "Noche",
                         "Centinela", "Terminal",    "Multimedia", "Trabajo",
                         "Entorno",   "Recuperación"};
  const char *types[] = {"text",    "pomodoro", "telemetry", "status",
                         "status",  "terminal", "spectrum",  "text",
                         "weather", "status"};
  std::array<Skin, 10> out;
  for (size_t i = 0; i < out.size(); i++) {
    out[i].mode = SkinId(i);
    out[i].id = ids[i];
    out[i].title = names[i];
    out[i].widgets.push_back({"main", types[i], names[i], 16, 156, 288, 64});
  }
  out[3].brightness = 12;
  out[3].sounds = false;
  out[3].breath_hz = .12f;
  out[5].fur = 0xC8E6C9;
  out[5].patch = 0x376A3A;
  out[7].widgets[0].y = 80;
  out[7].widgets[0].h = 140;
  return out;
}
SkinManager::SkinManager() {
  auto defaults = builtin_skins();
  skins_.assign(defaults.begin(), defaults.end());
  types_ = {"text",    "telemetry", "pomodoro", "spectrum",
            "weather", "status",    "terminal"};
}
bool SkinManager::register_type(const std::string &type) {
  if (type.empty() || type.size() > 32 || types_.size() >= 32)
    return false;
  if (std::find(types_.begin(), types_.end(), type) == types_.end())
    types_.push_back(type);
  return true;
}
bool SkinManager::select(const std::string &id) {
  for (size_t i = 0; i < skins_.size(); i++)
    if (skins_[i].id == id) {
      selected_ = i;
      return true;
    }
  return false;
}
static bool identifier(const std::string &s) {
  return !s.empty() && s.size() <= 32 &&
         std::all_of(s.begin(), s.end(),
                     [](char c) { return (c >= 'a' && c <= 'z') || c == '_'; });
}
static bool bounded(const cJSON *p, int min, int max) {
  return cJSON_IsNumber(p) && p->valuedouble == p->valueint &&
         p->valueint >= min && p->valueint <= max;
}
bool SkinManager::parse(const std::string &text, Skin &candidate,
                        std::string &error) const {
  if (!json_shape_safe(text, 8192)) {
    error = "descriptor_too_large";
    return false;
  }
  using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
  Json json(
      cJSON_ParseWithLengthOpts(text.c_str(), text.size() + 1, nullptr, true),
      cJSON_Delete);
  if (!json || !cJSON_IsObject(json.get())) {
    error = "invalid_json";
    return false;
  }
  auto item = [&](const char *k) {
    return cJSON_GetObjectItemCaseSensitive(json.get(), k);
  };
  const char *id = cJSON_GetStringValue(item("id"));
  if (!id || !identifier(id)) {
    error = "invalid_id";
    return false;
  }
  auto known = std::find_if(skins_.begin(), skins_.end(),
                            [&](const Skin &s) { return s.id == id; });
  if (known == skins_.end()) {
    const char *base = cJSON_GetStringValue(item("base"));
    auto defaults = builtin_skins();
    auto original =
        std::find_if(defaults.begin(), defaults.end(),
                     [&](const Skin &s) { return base && s.id == base; });
    if (original == defaults.end() || skins_.size() >= 32) {
      error = "unknown_base_or_catalog_full";
      return false;
    }
    candidate = *original;
    candidate.id = id;
  } else
    candidate = *known;
  if (auto title = cJSON_GetStringValue(item("title")); title) {
    if (std::char_traits<char>::length(title) > 64) {
      error = "invalid_title";
      return false;
    }
    candidate.title = title;
  }
  if (auto p = item("breath_hz"); p) {
    if (!cJSON_IsNumber(p) || !std::isfinite(p->valuedouble) ||
        p->valuedouble < .08 || p->valuedouble > .6) {
      error = "invalid_breath";
      return false;
    }
    candidate.breath_hz = p->valuedouble;
  }
  for (auto pair : {std::pair<const char *, uint32_t *>{"fur", &candidate.fur},
                    {"patch", &candidate.patch},
                    {"eyes", &candidate.eyes}})
    if (auto p = item(pair.first); p) {
      if (!bounded(p, 0, 0xFFFFFF)) {
        error = "invalid_palette";
        return false;
      }
      *pair.second = p->valueint;
    }
  if (!bounded(item("schema"), 1, 1) ||
      !bounded(item("revision"), 1, INT32_MAX)) {
    error = "invalid_version";
    return false;
  }
  candidate.revision = item("revision")->valueint;
  if (auto p = item("brightness"); p) {
    if (!bounded(p, 5, 100)) {
      error = "invalid_brightness";
      return false;
    }
    candidate.brightness = p->valueint;
  }
  if (auto p = item("sounds"); p) {
    if (!cJSON_IsBool(p)) {
      error = "invalid_sounds";
      return false;
    }
    candidate.sounds = cJSON_IsTrue(p);
  }
  auto widgets = item("widgets");
  if (!cJSON_IsArray(widgets) || cJSON_GetArraySize(widgets) > 8) {
    error = "invalid_widgets";
    return false;
  }
  candidate.widgets.clear();
  for (auto p = widgets->child; p; p = p->next) {
    Widget w;
    auto get = [&](const char *k) {
      return cJSON_GetObjectItemCaseSensitive(p, k);
    };
    const char *type = cJSON_GetStringValue(get("type")),
               *name = cJSON_GetStringValue(get("id")),
               *label = cJSON_GetStringValue(get("label"));
    if (!type ||
        std::find(types_.begin(), types_.end(), type) == types_.end() ||
        !name || !identifier(name) || !label ||
        std::char_traits<char>::length(label) > 128) {
      error = "unknown_factory";
      return false;
    }
    w.id = name;
    w.type = type;
    w.label = label;
    if (auto page = cJSON_GetStringValue(get("page")); page) {
      if (!identifier(page) || std::string(page) == "approval" ||
          std::string(page) == "cancel") {
        error = "invalid_plugin_page";
        return false;
      }
      w.page = page;
    }
    if (!bounded(get("x"), 0, 319) || !bounded(get("y"), 0, 239) ||
        !bounded(get("w"), 44, 320) || !bounded(get("h"), 44, 240)) {
      error = "invalid_touch_bounds";
      return false;
    }
    w.x = get("x")->valueint;
    w.y = get("y")->valueint;
    w.w = get("w")->valueint;
    w.h = get("h")->valueint;
    if (w.x + w.w > 320 || w.y + w.h > 240) {
      error = "out_of_screen";
      return false;
    }
    candidate.widgets.push_back(w);
  }
  return true;
}
bool SkinManager::reload(const std::string &root, const std::string &id,
                         std::string &error) {
  if (!identifier(id)) {
    error = "invalid_path";
    return false;
  }
  std::ifstream in(root + "/" + id + ".json", std::ios::binary);
  if (!in) {
    error = "not_found";
    return false;
  }
  char buffer[8193];
  in.read(buffer, sizeof(buffer));
  if (in.gcount() > 8192) {
    error = "descriptor_too_large";
    return false;
  }
  return apply(std::string(buffer, in.gcount()), id, error);
}
bool SkinManager::apply(const std::string &json, const std::string &id,
                        std::string &error) {
  Skin next;
  if (!parse(json, next, error) || next.id != id) {
    error = "invalid_descriptor";
    return false;
  }
  for (auto &old : skins_)
    if (old.id == id) {
      old = std::move(next);
      return true;
    }
  if (skins_.size() < 32) {
    skins_.push_back(std::move(next));
    return true;
  }
  error = "catalog_full";
  return false;
}
Route LLMRouter::decide(const Request &r,
                        const std::array<EndpointStatus, 7> &s, uint32_t ms,
                        uint32_t excluded) const {
  std::string text = r.text;
  for (size_t i = 0; i < text.size(); ++i) {
    auto c = static_cast<unsigned char>(text[i]);
    if (c >= 'A' && c <= 'Z')
      text[i] = char(c + 32);
    else if (c == 0xc3 && i + 1 < text.size()) {
      auto d = static_cast<unsigned char>(text[i + 1]);
      if ((d >= 0x80 && d <= 0x96) || (d >= 0x98 && d <= 0x9e))
        text[++i] = char(d + 32);
    }
  }
  if (!r.audio && !r.image && !r.tools && !r.private_context &&
      r.capability == "conversation") {
    const std::pair<const char *, int> commands[] = {
        {"modo noche", 1}, {"modo mascota", 2}, {"silencio", 3},
        {"despierta", 4},  {"estado", 5},       {"cancelar", 6}};
    for (auto [word, command] : commands)
      if (text == word)
        return {Provider::local, "", "Listo. Estoy aquí contigo.", command};
  }
  bool private_input = r.private_context || r.image ||
                       text.find("password") != std::string::npos ||
                       text.find("contraseña") != std::string::npos ||
                       text.find("clave privada") != std::string::npos ||
                       text.find("token secreto") != std::string::npos;
  bool needs_tools = r.tools || r.capability != "conversation" ||
                     text.rfind("ejecuta ", 0) == 0 ||
                     text.rfind("reinicia ", 0) == 0 ||
                     text.rfind("instala ", 0) == 0;
  auto usable = [&](Provider p) {
    auto i = size_t(p);
    if (i >= s.size() || excluded & (1u << i))
      return false;
    auto &e = s[i];
    return e.enabled && e.reachable && e.has_credentials &&
           ms - e.checked_at < 30000 && (!r.audio || e.audio_input) &&
           (!needs_tools || e.tools);
  };
  if (r.preference == Preference::local_only)
    return {};
  if ((needs_tools || private_input ||
       r.preference == Preference::homelab_first) &&
      usable(Provider::homelab))
    return {Provider::homelab, "muse", "", 0};
  if (needs_tools || private_input)
    return {};
  bool complex = r.text.size() > 512 ||
                 text.find("código") != std::string::npos ||
                 text.find("analiza") != std::string::npos;
  for (auto p : {Provider::openrouter, Provider::openai, Provider::xai,
                 Provider::gemini, Provider::opencode})
    if (usable(p)) {
      auto &e = s[size_t(p)];
      auto model = complex ? e.strong_model : e.small_model;
      if (!model.empty())
        return {p, model, "", 0};
    }
  if (usable(Provider::homelab))
    return {Provider::homelab, "muse", "", 0};
  return {};
}
bool valid_preferences(const UserPreferences &p) {
  if (p.schema != 1 || p.routing > 2 || p.voice > 1 || p.pet > 1 ||
      p.sounds > 1 || p.sensors > 1 || !memchr(p.skin, 0, sizeof(p.skin)) ||
      !memchr(p.target, 0, sizeof(p.target)) ||
      !memchr(p.capability, 0, sizeof(p.capability)))
    return false;
  const std::string id = p.skin, target = p.target, capability = p.capability;
  return !id.empty() &&
         id.find_first_not_of("abcdefghijklmnopqrstuvwxyz_") ==
             std::string::npos &&
         (target == "mac-mini" || target == "tuf-infra") &&
         (capability == "conversation" || capability == "infra.diagnose" ||
          capability == "code.change");
}
int Navigation::open(int next) {
  if (next < 0 || next > 18 || next == current_)
    return current_;
  if (next == 0)
    depth_ = 0;
  else {
    if (depth_ == history_.size()) {
      std::move(history_.begin() + 1, history_.end(), history_.begin());
      --depth_;
    }
    history_[depth_++] = current_;
  }
  current_ = next;
  return current_;
}
int Navigation::back() {
  current_ = depth_ ? history_[--depth_] : 0;
  return current_;
}
void spectrum(const int16_t *pcm, size_t count, std::array<float, 3> &bands) {
  constexpr size_t N = 256;
  std::array<std::complex<float>, N> a{};
  for (size_t i = 0; i < N; i++)
    a[i] = float(i < count ? pcm[i] : 0) / 32768 *
           (.5f - .5f * std::cos(6.2831853f * i / (N - 1)));
  for (size_t i = 1, j = 0; i < N; i++) {
    size_t bit = N >> 1;
    for (; j & bit; bit >>= 1)
      j ^= bit;
    j ^= bit;
    if (i < j)
      std::swap(a[i], a[j]);
  }
  for (size_t len = 2; len <= N; len <<= 1) {
    auto root = std::polar(1.f, -6.2831853f / len);
    for (size_t i = 0; i < N; i += len) {
      std::complex<float> w = 1;
      for (size_t j = 0; j < len / 2; j++) {
        auto u = a[i + j], v = a[i + j + len / 2] * w;
        a[i + j] = u + v;
        a[i + j + len / 2] = u - v;
        w *= root;
      }
    }
  }
  std::array<float, 3> sums{};
  for (size_t i = 1; i < N / 2; i++)
    sums[i < 8 ? 0 : i < 40 ? 1 : 2] += std::norm(a[i]);
  for (size_t i = 0; i < 3; i++)
    bands[i] = bands[i] * .65f + clamp(std::sqrt(sums[i]) / N * 4, 0, 1) * .35f;
}
} // namespace sagwa
