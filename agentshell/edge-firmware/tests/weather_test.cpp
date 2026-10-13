#include "weather_json.hpp"
#include <cassert>
#include <string>
#include <iostream>
#include <vector>
using namespace sagwa;
static WeatherSnapshot decode(const std::string &json,uint32_t at=1000) {
  cJSON *root=cJSON_Parse(json.c_str());
  auto out=weather_packet(root,at);cJSON_Delete(root);return out;
}
int main() {
  const std::string packet=R"({"weather":{"schema":1,"available":true,"source":"nws","kind":"forecast","city":"Ray City, GA","temperature_centi_c":-50,"condition":"rain","ttl_seconds":900}})";
  auto weather=decode(packet);assert(weather.fresh(1000));assert(weather.fresh(900999));assert(!weather.fresh(901000));
  char text[256];weather.text(text,sizeof text,1000);assert(std::string(text).find("-0.5 °C")!=std::string::npos);
  assert(std::string(text).find("pronóstico NWS")!=std::string::npos);
  weather.text(text,sizeof text,901000);assert(std::string(text).find("sin dato reciente")!=std::string::npos);
  const auto wrap=decode(packet,UINT32_MAX-50);assert(wrap.fresh(10));assert(!wrap.fresh(899950));
  for(const auto &change:std::vector<std::pair<std::string,std::string>>{
      {"\"nws\"","\"fake\""},{"\"forecast\"","\"ambient\""},{"900","901"},
      {"900","0"},{"900","1.5"},{"-50","6001"},{"\"rain\"","\"arbitrary\""},
      {"Ray City, GA","fake\\nstatus"},{"Ray City, GA",std::string(41,'a')},
      {"true","false"},{"true","1"}}) {
    auto altered=packet;auto index=altered.find(change.first);assert(index!=std::string::npos);
    altered.replace(index,change.first.size(),change.second);assert(!decode(altered).available);
  }
  assert(!decode("{}").available);assert(!decode("null").available);
  assert(!decode("{\"weather\":true}").available);
  char small[8];weather.text(small,sizeof small,1000);assert(small[7]=='\0');
  std::cout<<"PASS: weather decoding, bounded fields, stale/offline data, forecast label and monotonic wrap\n";
}
