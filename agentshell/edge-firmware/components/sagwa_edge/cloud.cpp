#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "mbedtls/base64.h"
#include "platform.hpp"
#include <cstring>
#include <memory>
namespace sagwa {
using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
static std::string field(const cJSON *j, const char *k) {
  auto *s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(j, k));
  return s ? s : "";
}
static std::string b64(const std::vector<uint8_t> &v) {
  size_t n = 0;
  mbedtls_base64_encode(nullptr, 0, &n, v.data(), v.size());
  std::string s(n, '\0');
  if (mbedtls_base64_encode(reinterpret_cast<unsigned char *>(s.data()),
                            s.size(), &n, v.data(), v.size()))
    return {};
  s.resize(n);
  return s;
}
struct Download {
  uint32_t generation, start;
  std::string body;
  bool valid = true;
};
static esp_err_t event(esp_http_client_event_t *e) {
  auto *d = static_cast<Download *>(e->user_data);
  if (d->generation != runtime().generation || now_ms() - d->start > 15000)
    return ESP_FAIL;
  if (e->event_id == HTTP_EVENT_ON_DATA) {
    if (d->body.size() + e->data_len > 65536) {
      d->valid = false;
      return ESP_FAIL;
    }
    d->body.append(static_cast<char *>(e->data), e->data_len);
  }
  return ESP_OK;
}
bool cloud_query(const Routed &job, const CloudProfile &profile, Reply &out) {
  // Separate input/output limits; bound audio before base64/JSON allocation.
  constexpr size_t max_audio = 160044; // Five seconds WAV, PCM mono 16 kHz.
  constexpr size_t max_request = 224 * 1024;
  if (job.request.text.size() > 8192 ||
      (job.request.audio &&
       (job.audio.size() < 44 || job.audio.size() > max_audio)))
    return false;
  if (job.request.tools || job.request.private_context) {
    out.error = "Esta consulta requiere el equipo autorizado.";
    return false;
  }
  const char *instruction =
      "Eres Sagwa, una mascota asistente. Responde en español. Devuelve JSON "
      "con brief (5–10 palabras cuando sea suficiente) y detail (respuesta "
      "completa). Conserva cifras y advertencias necesarias. No afirmes "
      "ejecutar herramientas que no tienes.";
  auto p = job.route.provider;
  std::string url;
  Json body(cJSON_CreateObject(), cJSON_Delete);
  bool responses = p == Provider::openai || p == Provider::xai ||
                   (p == Provider::opencode && profile.responses_api);
  if (p == Provider::gemini) {
    if (job.request.audio)
      return false;
    url = "https://generativelanguage.googleapis.com/v1beta/models/" +
          job.route.model + ":generateContent";
    auto *contents = cJSON_AddArrayToObject(body.get(), "contents");
    auto *m = cJSON_CreateObject();
    cJSON_AddStringToObject(m, "role", "user");
    auto *parts = cJSON_AddArrayToObject(m, "parts");
    auto *t = cJSON_CreateObject();
    cJSON_AddStringToObject(
        t, "text",
        (std::string(instruction) + "\n" + job.request.text).c_str());
    cJSON_AddItemToArray(parts, t);
    cJSON_AddItemToArray(contents, m);
    auto *generation = cJSON_AddObjectToObject(body.get(), "generationConfig");
    cJSON_AddNumberToObject(generation, "maxOutputTokens", 512);
  } else {
    url = p == Provider::openrouter
              ? "https://openrouter.ai/api/v1/chat/completions"
          : p == Provider::openai ? "https://api.openai.com/v1/responses"
          : p == Provider::xai    ? "https://api.x.ai/v1/responses"
          : p == Provider::opencode
              ? (responses ? "https://opencode.ai/zen/v1/responses"
                           : "https://opencode.ai/zen/v1/chat/completions")
              : "";
    if (url.empty())
      return false;
    cJSON_AddStringToObject(body.get(), "model", job.route.model.c_str());
    if (responses) {
      if (job.request.audio)
        return false;
      cJSON_AddStringToObject(body.get(), "instructions", instruction);
      cJSON_AddStringToObject(body.get(), "input", job.request.text.c_str());
      cJSON_AddBoolToObject(body.get(), "store", false);
      cJSON_AddNumberToObject(body.get(), "max_output_tokens", 512);
    } else {
      auto *messages = cJSON_AddArrayToObject(body.get(), "messages");
      auto *sys = cJSON_CreateObject();
      cJSON_AddStringToObject(sys, "role", "system");
      cJSON_AddStringToObject(sys, "content", instruction);
      cJSON_AddItemToArray(messages, sys);
      auto *user = cJSON_CreateObject();
      cJSON_AddStringToObject(user, "role", "user");
      if (job.request.audio) {
        if (p != Provider::openrouter || !profile.audio_input ||
            job.audio.size() > max_audio)
          return false;
        auto *content = cJSON_AddArrayToObject(user, "content");
        auto *item = cJSON_CreateObject();
        cJSON_AddStringToObject(item, "type", "input_audio");
        auto *a = cJSON_AddObjectToObject(item, "input_audio");
        auto encoded = b64(job.audio);
        if (encoded.empty())
          return false;
        cJSON_AddStringToObject(a, "data", encoded.c_str());
        cJSON_AddStringToObject(a, "format", "wav");
        cJSON_AddItemToArray(content, item);
      } else
        cJSON_AddStringToObject(user, "content", job.request.text.c_str());
      cJSON_AddItemToArray(messages, user);
      cJSON_AddBoolToObject(body.get(), "stream", false);
      cJSON_AddNumberToObject(body.get(), "max_tokens", 512);
    }
  }
  auto *serialized = cJSON_PrintUnformatted(body.get());
  if (!serialized)
    return false;
  std::unique_ptr<char, decltype(&cJSON_free)> encoded(serialized, cJSON_free);
  if (strlen(serialized) > max_request)
    return false;
  body.reset(); // Release JSON/base64 copies before HTTP.
  Download download{job.request.generation, now_ms(), {}, true};
  esp_http_client_config_t cfg{};
  cfg.url = url.c_str();
  cfg.crt_bundle_attach = esp_crt_bundle_attach;
  cfg.method = HTTP_METHOD_POST;
  cfg.timeout_ms = 10000;
  cfg.disable_auto_redirect = true;
  cfg.buffer_size = 2048;
  cfg.event_handler = event;
  cfg.user_data = &download;
  auto client = esp_http_client_init(&cfg);
  if (!client)
    return false;
  esp_http_client_set_header(client, "Content-Type", "application/json");
  std::string auth;
  if (p == Provider::gemini)
    esp_http_client_set_header(client, "x-goog-api-key", profile.key.c_str());
  else {
    auth = "Bearer " + profile.key;
    esp_http_client_set_header(client, "Authorization", auth.c_str());
  }
  esp_http_client_set_post_field(client, serialized, strlen(serialized));
  auto error = esp_http_client_perform(client);
  auto status = esp_http_client_get_status_code(client);
  esp_http_client_cleanup(client);
  if (error != ESP_OK || status < 200 || status >= 300 || !download.valid ||
      job.request.generation != runtime().generation) {
    out.error = status == 429
                    ? "El proveedor alcanzó su límite. Intenta después."
                    : "No pude conectar con ese proveedor.";
    return false;
  }
  if (!json_shape_safe(download.body, 65536, 32))
    return false;
  Json result(cJSON_ParseWithLength(download.body.data(), download.body.size()),
              cJSON_Delete);
  if (!result)
    return false;
  std::string text;
  if (p == Provider::gemini) {
    auto *candidate =
        cJSON_GetArrayItem(cJSON_GetObjectItem(result.get(), "candidates"), 0);
    auto *content = cJSON_GetObjectItem(candidate, "content");
    auto *parts = cJSON_GetObjectItem(content, "parts");
    for (auto *t = parts ? parts->child : nullptr; t; t = t->next)
      text += field(t, "text");
  } else if (responses) {
    auto *output = cJSON_GetObjectItem(result.get(), "output");
    for (auto *m = output ? output->child : nullptr; m; m = m->next) {
      auto *content = cJSON_GetObjectItem(m, "content");
      for (auto *t = content ? content->child : nullptr; t; t = t->next)
        if (field(t, "type") == "output_text")
          text += field(t, "text");
    }
  } else {
    auto *choice =
        cJSON_GetArrayItem(cJSON_GetObjectItem(result.get(), "choices"), 0);
    text = field(cJSON_GetObjectItem(choice, "message"), "content");
  }
  if (text.empty() || text.size() > 32768)
    return false;
  Json reply(json_shape_safe(text, 32768) ? cJSON_Parse(text.c_str()) : nullptr,
             cJSON_Delete);
  out.brief = reply ? field(reply.get(), "brief") : "";
  out.detail = reply ? field(reply.get(), "detail") : "";
  if (out.detail.empty())
    out.detail = text;
  if (out.brief.empty() || out.brief.size() > 512)
    out.brief = "La respuesta está lista. Toca para leerla.";
  out.error.clear();
  return true;
}
} // namespace sagwa
