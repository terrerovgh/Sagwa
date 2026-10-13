#pragma once
#include <cstdint>
#include <cstddef>
#include <string>
namespace shell {
inline constexpr size_t emoji_max_bytes=16+32*96*96*2;
inline bool emoji_hash_valid(const std::string &s) {
 if(s.size()!=64)return false;
 for(char c:s)if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;
 return true;
}
inline uint16_t emoji_u16(const uint8_t *p){return p[0]|uint16_t(p[1])<<8;}
inline uint32_t emoji_u32(const uint8_t *p){return emoji_u16(p)|uint32_t(emoji_u16(p+2))<<16;}
inline bool emoji_image_valid(const uint8_t *p,size_t n) {
 if(n<16||n>emoji_max_bytes||p[0]!='A'||p[1]!='E'||p[2]!='M'||p[3]!='1')return false;
 unsigned frames=emoji_u16(p+8),duration=emoji_u32(p+12);
 return emoji_u16(p+4)==96&&emoji_u16(p+6)==96&&frames>=1&&frames<=32&&emoji_u16(p+10)==0&&duration>=100&&duration<=16000&&n==16+frames*96*96*2;
}
inline std::string emoji_gateway_origin(std::string gateway) {
 if(gateway.rfind("wss://",0)!=0)return "";
 auto end=gateway.find("/v1/device/ws",6);
 if(end==std::string::npos||end+13!=gateway.size())return "";
 gateway.resize(end);gateway.replace(0,3,"https");return gateway;
}
inline bool emoji_url_valid(const std::string &url,const std::string &gateway,const std::string &hash) {
 auto origin=emoji_gateway_origin(gateway);
 return emoji_hash_valid(hash)&&!origin.empty()&&url==origin+"/v1/device/emoji/"+hash;
}
}
