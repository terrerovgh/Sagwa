#include "protocol.hpp"
#include "esp_random.h"
#include <cstdio>
#include <cstring>
namespace shell {
static std::string uuid_string(const uint8_t *b) {
  char s[37];
  snprintf(
      s, sizeof(s),
      "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
      b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[10], b[11],
      b[12], b[13], b[14], b[15]);
  return s;
}
static bool uuid_bytes(const std::string &s, uint8_t *b) {
  if (s.size() != 36)
    return false;
  unsigned i = 0;
  for (size_t n = 0; n < s.size();) {
    if (s[n] == '-') {
      n++;
      continue;
    }
    if (n + 1 >= s.size() || i >= 16)
      return false;
    unsigned value;
    if (sscanf(s.substr(n, 2).c_str(), "%2x", &value) != 1)
      return false;
    b[i++] = value;
    n += 2;
  }
  return i == 16;
}
std::string uuid() {
  uint8_t b[16];
  esp_fill_random(b, sizeof(b));
  b[6] = (b[6] & 15) | 64;
  b[8] = (b[8] & 63) | 128;
  return uuid_string(b);
}
std::string message(const std::string &session, uint64_t seq, const char *type,
                    const cJSON *payload, const std::string &task) {
  cJSON *root = cJSON_CreateObject();
  cJSON_AddNumberToObject(root, "version", 1);
  cJSON_AddStringToObject(root, "message_id", uuid().c_str());
  cJSON_AddStringToObject(root, "session_id", session.c_str());
  if (task.empty())
    cJSON_AddNullToObject(root, "task_id");
  else
    cJSON_AddStringToObject(root, "task_id", task.c_str());
  cJSON_AddStringToObject(root, "type", type);
  cJSON_AddNumberToObject(root, "sequence", seq);
  cJSON_AddItemToObject(root, "payload",
                        payload ? cJSON_Duplicate(payload, true)
                                : cJSON_CreateObject());
  char *text = cJSON_PrintUnformatted(root);
  std::string out = text ? text : "";
  cJSON_free(text);
  cJSON_Delete(root);
  return out;
}
std::vector<uint8_t> media_frame(const std::string &session,
                                 const std::string &task,
                                 const std::string &stream, uint32_t seq,
                                 uint8_t kind, const uint8_t *data,
                                 size_t bytes) {
  if (bytes > 8192)
    return {};
  std::vector<uint8_t> b(57 + bytes);
  memcpy(b.data(), "ASB1", 4);
  if (!uuid_bytes(session, b.data() + 4) || !uuid_bytes(task, b.data() + 20) ||
      !uuid_bytes(stream, b.data() + 36))
    return {};
  b[52] = seq >> 24;
  b[53] = seq >> 16;
  b[54] = seq >> 8;
  b[55] = seq;
  b[56] = kind;
  memcpy(b.data() + 57, data, bytes);
  return b;
}
bool media_header(const uint8_t *b, size_t bytes, std::string &session,
                  std::string &task, std::string &stream, uint32_t &seq,
                  uint8_t &kind) {
  if (bytes < 57 || bytes > 8249 || memcmp(b, "ASB1", 4) != 0 || b[56] != 3)
    return false;
  session = uuid_string(b + 4);
  task = uuid_string(b + 20);
  stream = uuid_string(b + 36);
  seq = (uint32_t(b[52]) << 24) | (uint32_t(b[53]) << 16) |
        (uint32_t(b[54]) << 8) | b[55];
  kind = b[56];
  return true;
}
} // namespace shell
