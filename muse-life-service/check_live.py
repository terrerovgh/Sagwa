import os,requests,time,subprocess,pathlib
url='http://192.168.4.64:8765';h={'Authorization':'Bearer '+os.environ['MUSE_LIFE_TOKEN']}
for topic in ['weather','bitcoin','general','news']:
 r=requests.post(url+'/context',headers=h,json={'topic':topic},timeout=35)
 print(topic,r.status_code,{k:v for k,v in r.json().items() if k in ('error','detail','scene','source','data','stale','queried_at')})
t=time.monotonic();r=requests.post(url+'/tts',headers=h,json={'text':'Hola, soy Muse. Ahora puedo hablar y mostrar escenas en tu Core S tres.'},timeout=35)
print('TTS',r.status_code,r.headers.get('Content-Type'),'bytes',len(r.content),'seconds',round(time.monotonic()-t,2))
if r.status_code==200:
 p=pathlib.Path('/tmp/muse-test.mp3');p.write_bytes(r.content)
 subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_name,sample_rate,channels','-of','json',str(p)],check=True)
