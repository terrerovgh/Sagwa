"""Exercise real remote decisions through each authenticated gateway.
Uses synthetic Spanish phrases only; never calls a conversational agent.
"""
import json,time
from pathlib import Path
from admin import request
root=Path(__file__).resolve().parents[1]
hosts=[('mac-mini','https://100.68.191.53:9443'),('lenlab','https://100.70.149.102:9443'),('tuf-infra','https://100.65.98.90:9443')]
cases=[('Voy a preparar té con mi tetera.','1fad6'),('Quiero tomar una taza de café.','2615'),('Revisemos el código de mi aplicación.','1f4bb'),('Guardaremos una copia de seguridad.','1f4be'),('Estoy triste y necesito hablar.','1f622'),('Pasearemos en bicicleta.','1f6b2')]
results=[]
for name,base in hosts:
 selected=[]
 for text,expected in cases if name=='mac-mini' else cases[:1]:
  start=time.monotonic();reply=request('/v1/emoji/preview','POST',{'text':text},base=base)
  choice=reply['choices'][0]
  result={'text':text,'expected':expected,'id':choice['entry']['id'],'name':choice['entry']['name'],'method':choice['method'],'elapsed_ms':round((time.monotonic()-start)*1000)}
  selected.append(result);print(name,json.dumps(result,ensure_ascii=False),flush=True)
  assert result['method']=='openrouter:inception/mercury-decide:free','Remote decision not confirmed'
  assert result['id']==expected,'Unexpected semantic choice'
 status=request('/v1/emoji/catalog',base=base)
 assert status['provider']=='openrouter' and status['remote_status']=='ready'
 assert status['openrouter']['cost_usd']==0
 results.append({'node':name,'health':status['openrouter'],'cases':selected,'catalog_entries':len(status['entries'])})
(root/'evidence/emoji-openrouter.json').write_text(json.dumps({'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'provider':'openrouter','model':'inception/mercury-decide:free','free_only':True,'hosts':results,'scope':'Real gateway decisions with synthetic Spanish; no conversational agents or host actions'},indent=2,ensure_ascii=False)+'\n')
