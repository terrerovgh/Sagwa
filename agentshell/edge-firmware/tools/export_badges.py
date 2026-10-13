"""Derive fixed 28px status emoji from already licensed Noto GIF originals."""
from pathlib import Path
from PIL import Image
root=Path(__file__).resolve().parents[1]
source=root.parent/'assets/noto'
names=['cat','listening','thinking','executing','speaking','approval','warning','sleeping','camera']
s='#include "lvgl.h"\n// Google Noto Emoji, CC BY 4.0. Resized, first frame, black background.\n'
for name in names:
 im=Image.open(source/(name+'.gif')).convert('RGBA').resize((28,28),Image.Resampling.LANCZOS)
 bg=Image.new('RGBA',im.size,(0,0,0,255));bg.alpha_composite(im)
 data=[]
 for red,green,blue,alpha in bg.getdata():
  v=((red>>3)<<11)|((green>>2)<<5)|(blue>>3);data.extend([v&255,v>>8])
 s+='static const uint8_t '+name+'_pixels[]={'+','.join(map(str,data))+'};\n'
 s+='const lv_image_dsc_t badge_'+name+'={.header={.magic=LV_IMAGE_HEADER_MAGIC,.cf=LV_COLOR_FORMAT_RGB565,.flags=0,.w=28,.h=28,.stride=56},.data_size=sizeof('+name+'_pixels),.data='+name+'_pixels};\n'
(root/'components/sagwa_edge/badges.c').write_text(s)
