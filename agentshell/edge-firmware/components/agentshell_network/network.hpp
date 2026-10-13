#pragma once
#include "storage.hpp"
#include <cstdint>
#include <string>
#include <vector>
namespace shell {
struct Packet {
  bool binary = false;
  std::vector<uint8_t> data;
};
bool network_begin(const Provision &);
bool connected();
bool time_synchronized();
bool receive(Packet &);
bool send_json(const std::string &, bool control = true);
bool send_binary(const std::vector<uint8_t> &);
std::string session_id();
void last_sequence(uint64_t);
bool persist_sequence(); // Storage_Task only: coalesced cursor checkpoint.
} // namespace shell
