"""Offline synthetic Spanish TTS/STT acceptance; no recorded user speech."""
import json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
code='''import json,urllib.request
from pathlib import Path
cfg=json.loads(Path(CONFIG).read_text());token=Path(cfg['token_file']).read_text().strip()
def call(path,body,kind):
 req=urllib.request.Request('http://127.0.0.1:9450'+path,data=body,headers={'Authorization':'Bearer '+token,'Content-Type':kind})
 with urllib.request.urlopen(req,timeout=180) as r:return r.read()
text='La infraestructura está disponible. Esta es una prueba de voz en español.'
pcm=call('/tts',json.dumps({'text':text}).encode(),'application/json')
result=json.loads(call('/stt',pcm,'application/octet-stream'));assert result['text'].strip() and result['language']=='es'
print(json.dumps({'language':result['language'],'transcript':result['text'],'pcm_bytes':len(pcm),'duration_s':result['duration_s']}))
'''
configs={'mac-mini':str(Path.home()/'Library/Application Support/AgentShell/private/voice.json'),'lenlab':'/opt/agentshell/private/voice.json','tuf-infra':'/opt/agentshell/private/voice.json'}
commands={'mac-mini':[sys.executable,'-'],'lenlab':['ssh','terrerov@lenlab','sudo -n python3 -'],'tuf-infra':['ssh','-J','terrerov@tuf-1','-p','2222','root@172.22.25.125','docker exec -i agentshell-voice python -']}
out={}
for node,command in commands.items():
 result=subprocess.run(command,input=('CONFIG='+repr(configs[node])+'\n'+code).encode(),capture_output=True,timeout=240)
 if result.returncode:raise RuntimeError(node+': voice test failed; check the local service log')
 out[node]=json.loads(result.stdout);print(json.dumps({node:out[node]}),flush=True)
 (root/'evidence/voice.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
