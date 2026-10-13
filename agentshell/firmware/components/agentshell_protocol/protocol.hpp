#pragma once
#include <cstdint>
#include "cJSON.h"
#include <string>
#include <vector>
namespace shell {
std::string uuid();
std::string message(const std::string &session, uint64_t seq, const char *type,
                    const cJSON *payload, const std::string &task = "");
std::vector<uint8_t> media_frame(const std::string &session,
                                 const std::string &task,
                                 const std::string &stream, uint32_t seq,
                                 uint8_t kind, const uint8_t *data,
                                 size_t bytes);
bool media_header(const uint8_t *, size_t, std::string &session,
                  std::string &task, std::string &stream, uint32_t &seq,
                  uint8_t &kind);
} // namespace shell
