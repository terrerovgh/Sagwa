#pragma once
#include <cstdint>
#include "storage.hpp"
#include <string>
#include <vector>
namespace shell {
struct Packet {
  bool binary = false;
  std::vector<uint8_t> data;
};
bool network_begin(const Provision &);
bool connected();
bool receive(Packet &);
bool send_json(const std::string &, bool control = true);
bool send_binary(const std::vector<uint8_t> &);
std::string session_id();
void last_sequence(uint64_t);
} // namespace shell
