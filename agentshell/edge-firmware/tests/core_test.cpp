#include "audio_start_gate.hpp"
#include "edge.hpp"
#include <cassert>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
using namespace sagwa;
int main(int argc, char **argv) {
  assert(argc == 3);
  AudioStartGate audio_gate;
  audio_gate.recover(100);
  assert(!audio_gate.accept(99, false, true, 1));
  assert(!audio_gate.accept(100, false, true, 1));
  assert(!audio_gate.accept(100, true, false, 0));
  assert(audio_gate.accept(100, true, true, 1));
  assert(!audio_gate.accept(100, true, true, 1));
  assert(audio_gate.accept(101, false, true, 2));
  assert(!audio_gate.accept(101, true, true, 1));
  audio_gate.recover(105);
  audio_gate.recover(103); // Recovery never lowers the boundary.
  assert(!audio_gate.accept(104, false, true, 3));
  assert(audio_gate.accept(105, true, true, 3));
  assert(audio_gate.accept(106, false, false, 0)); // Legacy fresh start.
  audio_gate.reset();
  audio_gate.recover(106);
  assert(audio_gate.accept(106, true, true, 1)); // New transport namespace.
  RecoverySnapshot recovered;
  const std::string task_id = "11111111-1111-4111-8111-111111111111";
  const std::string approval_id = "22222222-2222-4222-8222-222222222222";
  const std::string hash(64, 'a');
  const auto snapshot =
      std::string("{\"foreground_task_id\":\"") + task_id +
      "\",\"tasks\":[{\"task_id\":\"" + task_id +
      "\",\"state\":\"needs_approval\",\"summary\":\"Necesito tu "
      "autorización.\"}]," +
      "\"approvals\":[{\"task_id\":\"" + task_id + "\",\"approval_id\":\"" +
      approval_id + "\",\"action_hash\":\"" + hash +
      "\",\"expires_at\":2000,\"consumed\":false," +
      "\"denied\":false,\"physical_by\":null,\"action\":{\"task_id\":\"" +
      "33333333-3333-4333-8333-333333333333\",\"operation\":\"test.read\"}}]}";
  assert(parse_recovery_snapshot(snapshot, 1000, recovered));
  assert(recovered.task_id == task_id && recovered.approval_id == approval_id);
  assert(recovered.action_hash == hash &&
         recovered.action.find("test.read") != std::string::npos);
  assert(parse_recovery_snapshot(snapshot, 2000, recovered) &&
         recovered.approval_id.empty());
  assert(!parse_recovery_snapshot(snapshot + "trailing", 1000, recovered));
  assert(!parse_recovery_snapshot(
      "{\"tasks\":[{\"task_id\":\"invalid\",\"state\":\"running\"}]}", 1000,
      recovered));
  auto changed = [](std::string value, const std::string &from,
                    const std::string &to) {
    auto at = value.find(from);
    assert(at != std::string::npos);
    value.replace(at, from.size(), to);
    return value;
  };
  assert(parse_recovery_snapshot(
             changed(snapshot, "\"denied\":false", "\"denied\":true"), 1000,
             recovered) &&
         recovered.approval_id.empty());
  assert(parse_recovery_snapshot(
             changed(snapshot, "\"consumed\":false", "\"consumed\":true"), 1000,
             recovered) &&
         recovered.approval_id.empty());
  assert(parse_recovery_snapshot(changed(snapshot, "\"physical_by\":null",
                                         "\"physical_by\":\"device\""),
                                 1000, recovered) &&
         recovered.approval_id.empty());
  assert(parse_recovery_snapshot(changed(snapshot, "2000", "1e400"), 1000,
                                 recovered) &&
         recovered.approval_id.empty());
  assert(parse_recovery_snapshot(
             changed(snapshot, "\"needs_approval\"", "\"completed\""), 1000,
             recovered) &&
         recovered.approval_id.empty());
  assert(
      parse_recovery_snapshot(
          changed(snapshot, "\"task_id\":\"" + task_id + "\",\"approval_id\"",
                  "\"task_id\":\"" + approval_id + "\",\"approval_id\""),
          1000, recovered) &&
      recovered.approval_id.empty());
  assert(!parse_recovery_snapshot(
      changed(snapshot, "foreground_task_id\":\"" + task_id,
              "foreground_task_id\":\"" + approval_id),
      1000, recovered));
  Navigation navigation;
  assert(navigation.back() == 0);
  assert(navigation.open(9) == 9);
  assert(navigation.open(3) == 3);
  assert(navigation.open(15) == 15);
  assert(navigation.open(15) == 15);
  assert(navigation.back() == 3);
  assert(navigation.back() == 9);
  assert(navigation.back() == 0);
  assert(navigation.open(18) == 18);
  assert(navigation.back() == 0);
  assert(navigation.open(19) == 0);
  for (int page = 1; page <= 17; ++page)
    navigation.open(page);
  for (int i = 0; i < 9; ++i)
    navigation.back();
  assert(navigation.current() == 0);
  navigation.open(3);
  navigation.open(15);
  assert(navigation.open(0) == 0 && navigation.back() == 0);
  UserPreferences prefs;
  assert(valid_preferences(prefs));
  prefs.voice = 255;
  assert(!valid_preferences(prefs));
  prefs.voice = 1;
  prefs.routing = 3;
  assert(!valid_preferences(prefs));
  prefs.routing = 0;
  std::fill(std::begin(prefs.skin), std::end(prefs.skin), 'a');
  assert(!valid_preferences(prefs));
  prefs = {};
  strcpy(prefs.skin, "../secret");
  assert(!valid_preferences(prefs));
  prefs = {};
  strcpy(prefs.target, "lenlab");
  assert(!valid_preferences(prefs));
  prefs = {};
  strcpy(prefs.capability, "exec");
  assert(!valid_preferences(prefs));
  prefs = {};
  strcpy(prefs.skin, "custom_pet");
  strcpy(prefs.target, "tuf-infra");
  strcpy(prefs.capability, "code.change");
  assert(valid_preferences(prefs));
  SkinManager skins;
  assert(skins.catalog().size() == 10);
  std::string error;
  Skin s;
  for (auto &skin : builtin_skins()) {
    assert(skins.reload(argv[2], skin.id, error));
  }
  assert(!json_shape_safe(std::string(40, '[') + std::string(40, ']'), 8192));
  assert(json_shape_safe(R"({"braces":"{[\""})", 8192));
  const std::string custom =
      R"({"schema":1,"revision":2,"id":"custom_pet","base":"pet","title":"Mi Sagwa","brightness":70,"widgets":[{"id":"main","type":"text","label":"¡Aquí estoy!","x":16,"y":156,"w":288,"h":64}]})";
  assert(skins.parse(custom, s, error) && s.id == "custom_pet");
  assert(!skins.parse(custom + "oops", s, error));
  auto path = std::string(argv[1]) + "/custom_pet.json";
  {
    std::ofstream out(path);
    out << custom;
  }
  assert(skins.reload(argv[1], "custom_pet", error));
  assert(skins.select("custom_pet"));
  assert(skins.current().revision == 2);
  {
    std::ofstream out(path);
    out << "{}";
  }
  assert(!skins.reload(argv[1], "custom_pet", error));
  assert(skins.current().revision == 2);
  assert(!skins.reload(argv[1], "../secret", error));
  assert(!skins.parse(std::string(8193, 'a'), s, error));
  auto replace = [](std::string text, const std::string &from,
                    const std::string &to) {
    auto n = text.find(from);
    assert(n != std::string::npos);
    text.replace(n, from.size(), to);
    return text;
  };
  assert(!skins.parse(replace(custom, "288", "310"), s, error));
  assert(!skins.parse(replace(custom, "text", "shell"), s, error));
  assert(!skins.parse(replace(custom, "70", "101"), s, error));
  assert(
      !skins.parse(replace(custom, "\"schema\":1", "\"schema\":2"), s, error));
  assert(skins.register_type("clock"));
  assert(skins.parse(replace(custom, "text", "clock"), s, error));
  LLMRouter router;
  std::array<EndpointStatus, 7> status{};
  auto enable = [&](Provider p, uint32_t now) {
    status[size_t(p)] = {true,  true, true,    false,
                         false, now,  "small", "strong"};
  };
  Request q;
  q.text = "modo noche";
  q.preference = Preference::local_only;
  assert(router.decide(q, status, 100).provider == Provider::local);
  q.text = "Explícame la luna";
  assert(router.decide(q, status, 100).provider == Provider::unavailable);
  q.preference = Preference::homelab_first;
  enable(Provider::homelab, 100);
  enable(Provider::openrouter, 100);
  assert(router.decide(q, status, 200).provider == Provider::homelab);
  q.preference = Preference::cloud_first;
  assert(router.decide(q, status, 200).provider == Provider::openrouter);
  q.text = "analiza este código";
  assert(router.decide(q, status, 200).model == "strong");
  q.private_context = true;
  assert(router.decide(q, status, 200).provider == Provider::homelab);
  status[1].reachable = false;
  assert(router.decide(q, status, 200).provider == Provider::unavailable);
  q.private_context = false;
  q.text = "Mi CONTRASEÑA es privada";
  assert(router.decide(q, status, 200).provider == Provider::unavailable);
  q.text = "Explícame la luna";
  status[2].has_credentials = false;
  assert(router.decide(q, status, 200).provider == Provider::unavailable);
  status[2].has_credentials = true;
  q.tools = true;
  assert(router.decide(q, status, 200).provider == Provider::unavailable);
  q.tools = false;
  q.audio = true;
  assert(router.decide(q, status, 200).provider == Provider::unavailable);
  status[2].audio_input = true;
  assert(router.decide(q, status, 200).provider == Provider::openrouter);
  q.audio = false;
  q.image = true;
  // A confirmed camera photo always requires a private homelab route.
  assert(router.decide(q, status, 200).provider == Provider::unavailable);
  enable(Provider::homelab, 100);
  assert(router.decide(q, status, 200).provider == Provider::homelab);
  q.image = false;
  status[1].reachable = false;
  assert(router.decide(q, status, 30200).provider == Provider::unavailable);
  enable(Provider::xai, 100);
  assert(router.decide(q, status, 200, 1u << 2).provider == Provider::xai);
  AnimationFSM fsm(11);
  SensorSnapshot sensors{};
  std::array<float, 3> bands{};
  float low = 2, high = 0;
  bool blink = false;
  for (unsigned t = 1; t < 10000; t += 33) {
    auto pose = fsm.step(t, sensors, bands);
    assert(std::isfinite(pose.tail) && std::abs(pose.tail) < 1);
    low = std::min(low, pose.breath);
    high = std::max(high, pose.breath);
    blink |= pose.blink < .5;
  }
  assert(high - low > .03 && blink);
  fsm.event({EventKind::listen, 10000});
  fsm.event({EventKind::stroke, 10001});
  assert(fsm.state() == Emotion::listening);
  fsm.event({EventKind::sleep, 10002});
  fsm.event({EventKind::wake, 10003});
  assert(fsm.state() == Emotion::listening);
  fsm.event({EventKind::work, 10004});
  fsm.event({EventKind::sleep, 10005});
  assert(fsm.state() == Emotion::working);
  fsm.event({EventKind::done, 10010});
  fsm.event({EventKind::stroke, 10011});
  assert(fsm.state() == Emotion::purring);
  fsm.step(12000, sensors, bands);
  assert(fsm.state() == Emotion::idle);
  sensors.imu = true;
  sensors.at = 12000;
  sensors.ay = 1;
  assert(fsm.step(12001, sensors, bands).lean > .09);
  assert(fsm.step(13000, sensors, bands).lean == 0);
  fsm.event({EventKind::speak, 13001});
  bands[0] = .6;
  assert(fsm.step(13100, sensors, bands).mouth > .5);
  std::array<int16_t, 256> pcm{};
  bands = {};
  spectrum(pcm.data(), pcm.size(), bands);
  assert(bands[0] == 0 && bands[1] == 0 && bands[2] == 0);
  for (size_t i = 0; i < pcm.size(); i++)
    pcm[i] = 16000 * std::sin(6.2831853 * i * 4 / 256);
  for (int i = 0; i < 10; i++)
    spectrum(pcm.data(), pcm.size(), bands);
  assert(bands[0] > .4 && bands[0] > bands[2] * 10);
  Request stt_capture;
  stt_capture.audio = true;
  stt_capture.generation = 9;
  stt_capture.target = "tuf-infra";
  stt_capture.preference = Preference::local_only;
  Request stt_routed;
  assert(transcript_request(stt_capture, "modo noche", 9, stt_routed));
  assert(!stt_routed.audio && stt_routed.target == "tuf-infra" &&
         stt_routed.preference == Preference::local_only);
  std::array<EndpointStatus, 7> stt_offline{};
  assert(LLMRouter().decide(stt_routed, stt_offline, 0).provider ==
         Provider::local);
  stt_capture.tools = true;
  stt_capture.capability = "code.change";
  assert(transcript_request(stt_capture, "modo noche", 9, stt_routed));
  assert(stt_routed.tools && stt_routed.capability == "code.change");
  assert(LLMRouter().decide(stt_routed, stt_offline, 0).provider ==
         Provider::unavailable);
  assert(!transcript_request(stt_capture, "modo noche", 10, stt_routed));
  assert(!transcript_request(stt_capture, " \n\t", 9, stt_routed));
  assert(
      !transcript_request(stt_capture, std::string(4097, 'a'), 9, stt_routed));
  assert(!transcript_request(stt_capture, std::string("hola\0mundo", 10), 9,
                             stt_routed));
  stt_capture.image = true;
  assert(!transcript_request(stt_capture, "modo noche", 9, stt_routed));
  std::cout << "PASS: descriptor bounds/hot-reload, "
               "routing/privacy/staleness/failover, transcript local routing "
               "and tools privacy, FSM/FFT\n";
}
