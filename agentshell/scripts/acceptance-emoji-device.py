"""Verify contextual asset delivery on the physical Core using network telemetry.
Does not open USB or call a conversational agent. Leaves the first Noto smile visible.
"""
import argparse,json,time
from pathlib import Path
from admin import request
root=Path(__file__).resolve().parents[1];device='device:cores3-80456b4d5f7c';results=[]
parser=argparse.ArgumentParser();parser.add_argument('--firmware',default='0.1.12');args=parser.parse_args()
def telemetry():return request('/v1/devices')['devices/telemetry/'+device]
deadline=time.monotonic()+100
while telemetry()['capabilities']['firmware']!=args.firmware:
 if time.monotonic()>deadline:raise RuntimeError('Firmware update not observed')
 time.sleep(2)
for text,expected in [('Voy a preparar té con mi tetera.','1fad6'),('Quiero tomar una taza de café.','2615'),('Revisemos el código de mi aplicación.','1f4bb'),('Pasearemos en bicicleta.','1f6b2'),('😊','1f60a')]:
 began=time.monotonic();before=telemetry()['readings']['runtime']['uptime_s'];choice=request('/v1/emoji/display','POST',{'text':text,'device_id':device})['choices'][0]
 assert choice['entry']['id']==expected
 until=time.monotonic()+35
 while True:
  data=telemetry();visual=data['readings'].get('emoji',{});runtime=data['readings']['runtime']
  if visual.get('sha256')==choice['asset']['sha256'] and visual.get('codepoint')==expected:break
  if time.monotonic()>until:raise RuntimeError('Sprite not accepted: '+expected+' '+json.dumps(visual))
  time.sleep(1)
 assert runtime['uptime_s']>=before and visual['cached']<=3 and visual['failures']==0
 result={'id':expected,'sha256':visual['sha256'],'method':choice['method'],'elapsed_until_telemetry_s':round(time.monotonic()-began,2),'wire_bytes':visual['received_bytes'],'decoded_bytes':choice['asset']['size'],'cache_count':visual['cached'],'runtime':runtime,'gateway':data['gateway']}
 results.append(result);print(json.dumps(result),flush=True)
(root/'evidence/emoji-device.json').write_text(json.dumps({'firmware':args.firmware,'physical_network_delivery':results,'lcd_human_review':'pending'},indent=2)+'\n')
