"""Download and prepare the entire Noto catalog locally; safe to stop and resume."""
import concurrent.futures,hashlib,io,json,os,struct,time,urllib.request
from pathlib import Path
import numpy as np
from PIL import Image
root=Path(__file__).resolve().parents[1];cache=root/'.private/noto-cache';cache.mkdir(parents=True,exist_ok=True)
entries=[e for e in json.loads((root/'assets/noto/catalog.json').read_text()) if e.get('renderable',True)];began=time.time();failed=[];done=0

def fetch(url):
 with urllib.request.urlopen(url,timeout=30) as response:
  data=response.read(16*1024*1024+1)
  if len(data)>16*1024*1024:raise ValueError('source_too_large')
  return data

def prepare(entry):
 file=cache/(entry['id']+'.json')
 if file.exists():
  meta=json.loads(file.read_text())
  if (cache/(meta['sha256']+'.aem')).exists():return meta
 base='https://fonts.gstatic.com/s/e/notoemoji/latest/'+entry.get('asset_id',entry['id'])+'/'
 animated=entry['animated']
 try:data=fetch(base+('512.gif' if animated else '512.png'))
 except Exception:
  animated=False;data=fetch(base+'512.png')
 im=Image.open(io.BytesIO(data));assert im.width<=1024 and im.height<=1024 and im.n_frames<=512
 delays=[];timeline=[];total=0
 for i in range(im.n_frames):im.seek(i);timeline.append(total);delays.append(im.info.get('duration',100));total+=delays[-1]
 total=min(16000,max(100,total));count=min(32,max(2,round(total/100))) if animated else 1
 blob=bytearray(struct.pack('<4sHHHHI',b'AEM1',96,96,count,0,total))
 for i in range(count):
  at=total*i/count;page=max(j for j,t in enumerate(timeline) if t<=at);im.seek(page)
  frame=im.convert('RGBA');frame.thumbnail((96,96),Image.Resampling.LANCZOS)
  canvas=Image.new('RGBA',(96,96),(8,19,31,255));canvas.alpha_composite(frame,((96-frame.width)//2,(96-frame.height)//2))
  rgb=np.asarray(canvas.convert('RGB'),dtype=np.uint16)
  values=((rgb[:,:,0]>>3)<<11)|((rgb[:,:,1]>>2)<<5)|(rgb[:,:,2]>>3)
  blob+=values.astype('<u2').tobytes()
 hash=hashlib.sha256(blob).hexdigest();target=cache/(hash+'.aem');tmp=cache/(entry['id']+'.aem.tmp');tmp.write_bytes(blob);tmp.replace(target)
 meta={'id':entry['id'],'name':entry['name'],'sha256':hash,'size':len(blob),'animated':count>1,'frames':count,'duration_ms':total}
 tmp=Path(str(file)+'.tmp');tmp.write_text(json.dumps(meta,ensure_ascii=False));tmp.replace(file)
 return meta

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
 futures={pool.submit(prepare,e):e for e in entries}
 for future in concurrent.futures.as_completed(futures):
  entry=futures[future]
  try:future.result();done+=1
  except Exception as error:failed.append({'id':entry['id'],'error':type(error).__name__})
  if (done+len(failed))%100==0:
   report={'status':'running','prepared':done,'total':len(entries),'failed':len(failed),'elapsed_s':round(time.time()-began)}
   (cache/'progress.json').write_text(json.dumps(report));print(json.dumps(report),flush=True)
report={'status':'complete','prepared':done,'total':len(entries),'failed':failed,'elapsed_s':round(time.time()-began)}
(cache/'progress.json').write_text(json.dumps(report,indent=2));print(json.dumps({'status':'complete','prepared':done,'failed':len(failed),'elapsed_s':round(time.time()-began)}))
