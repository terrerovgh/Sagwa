#include "diagnostics.hpp"
#include <cassert>
#include <iostream>
using namespace sagwa;
int main() {
  DiagnosticHistory history;
  assert(history.text() == "Sin eventos locales.");
  assert(history.push(DiagnosticKind::started, 0xfffffff0u));
  assert(!history.push(DiagnosticKind::started, 10));
  assert(history.push(DiagnosticKind::started, 500));
  for (uint32_t i = 0; i < 1000; ++i)
    history.push(i % 2 ? DiagnosticKind::listening : DiagnosticKind::mic_stopped,
                 1000 + i * 300);
  assert(history.size() == 64 && history.newest(64) == nullptr);
  assert(history.newest()->at == 300700);
  assert(history.newest(63)->at == 281800);
  const auto brief = history.text(2);
  assert(brief.find("00:05:00  Micrófono activo") == 0);
  assert(brief.find("00:05:00  Micrófono apagado") != std::string::npos);
  assert(history.text().size() < 4096);
  // The input contract accepts no free-form data at all; these are fixed codes.
  assert(history.push(DiagnosticKind::query_failed, 301000));
  assert(history.text(1) == "00:05:01  Solicitud fallida");
  std::cout << "PASS: bounded diagnostic history, wrap, coalescing, timestamps\n";
}
