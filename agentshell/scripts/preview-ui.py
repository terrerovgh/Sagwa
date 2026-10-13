"""Pixel-accurate previews: compile LCD layout, render the actual Inter bitmap/SAV1."""
import json,shlex,subprocess,tempfile
from pathlib import Path
from PIL import Image,ImageDraw
root=Path(__file__).resolve().parents[1];ui=root/'firmware/components/agentshell_ui';out=root/'evidence/sagwa-v2';out.mkdir(exist_ok=True,parents=True)
assets=root/'assets/sagwa/packed';manifest=json.loads((assets/'manifest.json').read_text());font=json.loads((root/'assets/fonts/glyphs.json').read_text());glyphs={(g['size'],g['code']):g for g in font['glyphs']}
harness='''#include "scene.hpp"
#include <iostream>
#include <iomanip>
int main(int n,char **a){shell::View v;v.page=shell::Page(std::stoi(a[1]));v.mode=a[2];v.connected=v.mode!="offline";v.settings_ready=true;v.microphone=v.mode=="listening";v.speaker=v.mode=="speaking";v.audio_level=.1;v.task_active=v.mode=="executing";v.text="Estoy aquí, Josmar. ¿Qué necesitas hoy?";v.full_text="Sagwa está aquí para ayudarte.\\nPuedes acariciarla, hablar con PWR y consultar herramientas con un gesto.\\nLas acciones necesitan confirmación. La cámara envía fotos solo cuando tú lo decides.";v.agents={{"muse","Muse",true},{"codex","Codex",true},{"claude","Claude",false}};v.nodes={{"mac-mini","Mac mini",true},{"tuf-infra","TUF",true}};v.repositories={{"ejemplo","Proyecto",true}};v.photo_ready=true;v.sensor_text="Luz: 84 ADC\\nProximidad: 320 relativa\\nMovimiento: disponible\\nGiroscopio: disponible\\nBatería: 97 %";if(v.mode=="approval"){v.approval_id="demo";v.text="Reiniciar servicio de prueba.\\nDestino: Mac mini\\nAlcance: servicio autorizado\\nConfirma después de leer la acción.";}if(v.mode=="offline")v.text="Sin conexión. Sagwa sigue contigo.";if(v.mode=="warning")v.text="No pude conectarme. Puedes intentarlo de nuevo.";shell::Frame f;shell::compose(f,v,700);auto g=shell::select_sagwa_graphic(v,700);std::cout<<g.avatar<<' '<<g.frame<<' '<<shell::status_icon(v)<<'\\n';for(auto &t:f)std::cout<<t.x<<' '<<t.y<<' '<<t.size<<' '<<std::quoted(t.text)<<'\\n';}'''
def rgb(raw,w,h):
 import numpy as np
 p=np.frombuffer(raw,dtype='<u2').reshape(h,w).astype(np.uint32);a=np.stack((((p>>11)&31)*255//31,((p>>5)&63)*255//63,(p&31)*255//31),axis=2).astype('uint8');return Image.fromarray(a)
def writeglyph(im,x,y,size,char):
 g=glyphs.get((size,ord(char)),glyphs[(size,63)]);o=g['offset'];values=font['pixels'][o:o+g['w']*g['h']]
 for sy in range(g['h']):
  for sx in range(g['w']):
   px=x+g['x']+sx;py=y+g['y']+sy;c=values[sy*g['w']+sx]
   if 0<=px<320 and 0<=py<240:im.putpixel((px,py),((c>>3)*255//31,(c>>2)*255//63,(c>>3)*255//31))
 return g['advance']
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'main.cpp').write_text(harness);subprocess.run(['c++','-std=c++17','-O2','-I'+str(ui),str(p/'main.cpp'),str(ui/'scene.cpp'),'-o',str(p/'render')],check=True)
 def render(page,mode):
  text=subprocess.check_output([str(p/'render'),str(page),mode],text=True).splitlines();pose,frame,icon=map(int,text.pop(0).split());im=Image.new('RGB',(320,240),'black')
  for line in text:
   x,y,size,s=shlex.split(line);x,y,size=int(x),int(y),int(size)
   for char in s:x+=writeglyph(im,x,y,size,char)
  if page==0 and mode!='approval':
   clip=manifest['clips'][pose];raw=(assets/clip['file']).read_bytes();im.paste(rgb(raw[16+frame*136*136*2:16+(frame+1)*136*136*2],136,136),(84,8));im.paste(rgb((assets/'status.bin').read_bytes()[icon*28*28*2:(icon+1)*28*28*2],28,28),(280,12))
  if page==5:
   photo=Image.open(root/'.private/sagwa/originals/avatar-1791734962388088417-2.webp').convert('RGB');photo.thumbnail((160,120));im.paste(photo,(80+(160-photo.width)//2,46))
  return im
 pages=['home','menu','agents','destinations','tools','camera','cancel','reader','settings','sensors','voice','pet','tasks','credits','error']
 scenes=[]
 for page,name in enumerate(pages):
  im=render(page,'warning' if page==14 else 'idle');im.save(out/(name+'.png'));scenes.append((name,im))
 for mode in ('listening','thinking','executing','speaking','approval','warning','offline'):
  im=render(0,mode);im.save(out/(mode+'.png'));scenes.append((mode,im))
 sheet=Image.new('RGB',(4*352,((len(scenes)+3)//4)*284),'black');draw=ImageDraw.Draw(sheet)
 for i,(name,im) in enumerate(scenes):x=i%4*352+16;y=i//4*284+28;draw.text((x,y-20),name,fill='white');sheet.paste(im,(x,y))
 sheet.save(out/'all-screens.png')
 frames=[]
 for pose,clip in enumerate(manifest['clips']):
  raw=(assets/clip['file']).read_bytes()
  for f in range(4):
   im=render(0,'idle');im.paste(rgb(raw[16+f*136*136*2:16+(f+1)*136*136*2],136,136),(84,8));frames.append(im.resize((640,480)))
 frames[0].save(out/'pet-states.gif',save_all=True,append_images=frames[1:],duration=250,loop=0)
 html='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Sagwa · CoreS3</title><style>body{background:#000;color:#fff;font:16px Inter,system-ui;margin:32px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:32px}img{width:320px;height:240px}h1{font-size:24px}p{max-width:800px;color:#fff}figure{margin:0}figcaption{margin-bottom:10px}audio{display:block;margin:24px 0}</style><h1>Sagwa · CoreS3</h1><p>Vistas del compositor del firmware. Izquierda: menú · derecha: herramientas · arriba: configuración. PWR para hablar. Acaricia el avatar; toca el texto para ampliar.</p><audio controls src="voz-kokoro.wav"></audio><main>'+''.join('<figure><figcaption>'+n+'</figcaption><img src="'+n+'.png"></figure>' for n,_ in scenes)+'</main><p>Doce animaciones nuevas, creadas con Imagegen a partir de Sagwa. Los originales de Muse se conservaron intactos.</p><img src="pet-states.gif" style="width:640px;height:480px">'
 (out/'index.html').write_text(html)
 print('Rendered '+str(len(scenes))+' exact screens')
