#include "context_format.hpp"
#include <cassert>
#include <vector>
#include <cstdio>
int main(){
 using namespace shell;
 std::vector<uint8_t> p(16+96*96*2);p[0]='A';p[1]='E';p[2]='M';p[3]='1';p[4]=96;p[6]=96;p[8]=1;p[12]=100;
 assert(emoji_image_valid(p.data(),p.size()));
 assert(!emoji_image_valid(p.data(),p.size()-1));p[8]=33;assert(!emoji_image_valid(p.data(),p.size()));p[8]=1;p[10]=1;assert(!emoji_image_valid(p.data(),p.size()));
 std::string hash(64,'a'),gateway="wss://192.168.4.82:9443/v1/device/ws";
 std::string url="https://192.168.4.82:9443/v1/device/emoji/"+hash;
 assert(emoji_url_valid(url,gateway,hash));
 assert(!emoji_url_valid(url+"/../other",gateway,hash));assert(!emoji_url_valid("https://evil.test/v1/device/emoji/"+hash,gateway,hash));
 assert(!emoji_url_valid(url+"?token=x",gateway,hash));assert(!emoji_hash_valid(std::string(64,'z')));
 puts("Emoji size, header, hash and exact gateway URL checks passed.");
}
