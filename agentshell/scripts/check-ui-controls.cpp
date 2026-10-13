#include "controls.hpp"
#include "pet.hpp"
#include "avatar_format.hpp"
#include <cassert>
#include <iostream>
#include <fstream>
using namespace shell;
int main(){View v;v.connected=v.settings_ready=true;v.agents={{"muse","Muse",true},{"codex","Codex",false}};v.nodes={{"mac-mini","Mac mini",true},{"tuf-infra","TUF",false}};Controls c;
auto tap=[&](int x,int y,unsigned ms=100){c.update(v,{x,y,true,true,false,false,ms});return c.update(v,{x,y,false,false,false,false,ms+10});};
auto swipe=[&](int x,int y,int dx,int dy){c.update(v,{x,y,true,true,false,false,100});auto a=c.update(v,{x+dx,y+dy,false,true,false,false,150});auto b=c.update(v,{x+dx,y+dy,false,false,false,false,200});return a==Control::none?b:a;};
assert(tap(150,60)==Control::pet_stroke&&v.page==Page::home);assert(tap(150,200)==Control::read_result&&v.page==Page::reader);
swipe(4,100,70,0);assert(v.page==Page::home);swipe(4,100,70,0);assert(v.page==Page::options);swipe(4,100,70,0);swipe(315,100,-70,0);assert(v.page==Page::activities);
assert(swipe(160,115,70,0)==Control::none);assert(v.page==Page::activities);assert(tap(160,115)==Control::photo);
v.page=Page::photo;v.photo_ready=true;assert(swipe(4,100,70,0)==Control::discard_photo&&v.page==Page::home);v.page=Page::photo;assert(tap(250,220)==Control::send_photo);assert(tap(70,220)==Control::discard_photo);
v.page=Page::home;swipe(160,4,0,60);assert(v.page==Page::settings);tap(100,65);assert(v.page==Page::voice);assert(tap(100,65)==Control::save_preferences&&!v.voice_enabled);
v.page=Page::agents;tap(100,157);assert(v.preferred=="muse");v.page=Page::home;
assert(c.update(v,{0,0,false,false,true,true,500})==Control::start_voice);v.microphone=true;assert(c.update(v,{0,0,false,false,false,true,700})==Control::none);assert(c.update(v,{0,0,false,false,false,false,800})==Control::end_voice);v.microphone=false;v.speaker=true;assert(c.update(v,{0,0,false,false,true,true,900})==Control::stop_voice);v.speaker=false;
v.approval_id="test";assert(swipe(4,110,250,100)==Control::none);assert(v.page==Page::home);assert(c.update(v,{250,220,true,true,false,false,1000})==Control::none);assert(c.update(v,{250,220,false,true,false,false,2499})==Control::none);assert(c.update(v,{250,220,false,true,false,false,2500})==Control::approve);assert(c.update(v,{250,220,false,true,false,false,4500})==Control::none);v.approval_id.clear();
v.page=Page::cancel;v.task_active=true;assert(swipe(160,210,-100,0)==Control::none);assert(tap(250,210)==Control::cancel_task);
v.page=Page::home;v.text=std::string(1200,'a');for(int n=0;n<100;n++)swipe(160,190,0,-50);assert(v.scroll==text_lines(v.text)-3);swipe(160,170,0,50);assert(v.scroll==text_lines(v.text)-6);
Frame f;v.text="Aquí, José. ¿Qué necesitas?";v.scroll=0;compose(f,v,0);assert(f.size()<4);for(auto &t:f)assert(t.y>=158&&t.size==16);assert(text_width("á")>0);assert(wrap_text("mañana",30).size()>1);
Pet pet;LocalSensors s;s.sampled_ms=100;s.light_ok=s.proximity_ok=s.accel_ok=true;s.light=50;s.proximity=0;s.az=1;assert(pet.update(s,100,true).pose==0);s.sampled_ms=300;s.proximity=800;auto r=pet.update(s,300,true);assert(r.pose==1&&r.sound==PetSound::meow);r=pet.stroke(400);assert(r.pose==7&&r.sound==PetSound::none);r=pet.stroke(5500);assert(r.sound==PetSound::purr);assert(pet.update(s,6000,false).pose==0);s.sampled_ms=7000;s.light=0;s.proximity=0;pet.update(s,7000,true);for(unsigned n=7200;n<=39000;n+=200){s.sampled_ms=n;pet.update(s,n,true);}assert(pet.update(s,39000,true).pose==8);assert(pet.update(s,41000,true).pose==0);s.sampled_ms=41200;s.light=80;assert(pet.update(s,41200,true).pose!=8);
Pet tilt;LocalSensors t;t.accel_ok=true;t.az=1;t.sampled_ms=2000;tilt.update(t,2000,true);for(unsigned n=1;n<=3;n++){t.sampled_ms=2000+n*200;t.ay=.1f*n;r=tilt.update(t,t.sampled_ms,true);}assert(r.pose==11);tilt.update(t,5000,true);t.sampled_ms=5200;t.ay=-1;t.az=0;assert(tilt.update(t,5200,true).pose!=11);
std::cout<<"Gestures, consent, Inter layout and local pet sensors passed\n";
}
