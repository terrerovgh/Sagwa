"""Package generated alpha sprites, preserving original assets, for SAV1/PSRAM."""
import hashlib,json,struct
from pathlib import Path
import numpy as np
from PIL import Image
from collections import deque
root=Path(__file__).resolve().parents[1];src=root/'assets/sagwa/generated/atlas.png';im=Image.open(src).convert('RGBA');a=np.asarray(im)
# Group opaque connected characters; detached whiskers stay within each crop.
mask=a[:,:,3]>32;visited=np.zeros(mask.shape,dtype=bool);objects=[]
for sy,sx in np.argwhere(mask):
 if visited[sy,sx]:continue
 q=deque([(int(sy),int(sx))]);visited[sy,sx]=True;count=0;loy=hiy=int(sy);lox=hix=int(sx)
 while q:
  y,x=q.popleft();count+=1;loy=min(loy,y);hiy=max(hiy,y);lox=min(lox,x);hix=max(hix,x)
  for ny,nx in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
   if 0<=ny<mask.shape[0] and 0<=nx<mask.shape[1] and mask[ny,nx] and not visited[ny,nx]:visited[ny,nx]=True;q.append((ny,nx))
 if count>2500:objects.append((slice(loy,hiy+1),slice(lox,hix+1)))
assert len(objects)==48,f'expected 48 characters, found {len(objects)}'
objects.sort(key=lambda b:(b[0].start+b[0].stop)/2)
ordered=[]
for y in range(6):ordered.extend(sorted(objects[y*8:y*8+8],key=lambda b:b[1].start))
names=['idle','look','listen','think','speak','work','celebrate','purr','sleep','wake','stretch','tilt']
out=root/'assets/sagwa/packed';out.mkdir(parents=True,exist_ok=True);fallback=bytearray();manifest={'version':'sagwa-v2-1','origin':'imagegen; identity reference: original Muse Sagwa','source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'width':136,'height':136,'clips':[]}
fallback_entries=[]
frames=[]
for bounds in ordered:
 y,x=bounds;y0=max(0,y.start-4);y1=min(im.height,y.stop+4);x0=max(0,x.start-4);x1=min(im.width,x.stop+4)
 crop=im.crop((x0,y0,x1,y1));crop.thumbnail((128,128),Image.Resampling.LANCZOS)
 cell=Image.new('RGBA',(136,136));cell.alpha_composite(crop,((136-crop.width)//2,136-crop.height-4));frames.append(cell)
for state,name in enumerate(names):
 pcm=bytearray()
 for f in frames[state*4:state*4+4]:
  # Alpha composited only at packing onto the mandated LCD black, white fur retained.
  b=Image.new('RGBA',f.size,(0,0,0,255));b.alpha_composite(f);p=np.array(b.convert('RGB')).astype(np.uint16)
  rgb=((p[:,:,0]>>3)<<11)|((p[:,:,1]>>2)<<5)|(p[:,:,2]>>3);pcm.extend(rgb.astype('<u2').tobytes())
  f.save(out/f'{name}-{len(pcm)//(136*136*2)-1}.png')
 n=4 if state in (0,1,7,8,9,10,11) else 1
 fallback_entries.append((len(fallback),n));fallback.extend(pcm[:n*136*136*2]);raw=struct.pack('<4sHHHHHH',b'SAV1',136,136,4,250,state,0)+pcm
 sha=hashlib.sha256(raw).hexdigest();(out/f'{sha}.sav').write_bytes(raw)
 manifest['clips'].append({'state':state,'name':name,'frames':4,'frame_ms':250,'sha256':sha,'size':len(raw),'file':sha+'.sav'})
(out/'sagwa.bin').write_bytes(fallback);(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(out/'sagwa_assets.hpp').write_text('#pragma once\nnamespace shell {struct FallbackPose {unsigned offset,frames;};inline constexpr FallbackPose fallback_poses[]={'+','.join('{'+str(offset)+','+str(n)+'}' for offset,n in fallback_entries)+'};}\n')
# Exact static status emoji, taken from licensed Noto source with alpha.
icons=['1f60a','1f3a4','1f914','2699_fe0f','1f50a','1f6e1_fe0f','26a0_fe0f','1f4f5','1f4f7']
import urllib.request
icondata=bytearray()
for cp in icons:
 path=root/'assets/sagwa/generated'/f'status-{cp}.png'
 if not path.exists():urllib.request.urlretrieve(f'https://fonts.gstatic.com/s/e/notoemoji/latest/{cp}/512.png',path)
 f=Image.open(path).convert('RGBA');f.thumbnail((28,28),Image.Resampling.LANCZOS);b=Image.new('RGBA',(28,28),(0,0,0,255));b.alpha_composite(f,((28-f.width)//2,(28-f.height)//2));p=np.array(b.convert('RGB')).astype(np.uint16)
 rgb=((p[:,:,0]>>3)<<11)|((p[:,:,1]>>2)<<5)|(p[:,:,2]>>3);icondata.extend(rgb.astype('<u2').tobytes())
(out/'status.bin').write_bytes(icondata)
manifest['status_icons']=icons;(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'clips':len(names),'full_bytes':sum(c['size'] for c in manifest['clips']),'offline_bytes':len(fallback),'status_bytes':len(icondata)}))
