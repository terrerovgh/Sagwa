"""Measure first PCM independently of Muse and device playback; never print credentials."""
import argparse,http.client,json,time,wave
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--config',type=Path,required=True)
parser.add_argument('--endpoint',choices=['/tts/stream','/tts/local-or-api'],default='/tts/stream')
parser.add_argument('--local-only',action='store_true')
parser.add_argument('--text',default='Hola, Josmar. Estoy aquí para ayudarte.')
parser.add_argument('--wav',type=Path,required=True)
args=parser.parse_args();cfg=json.loads(args.config.read_text())
client=http.client.HTTPConnection('127.0.0.1',cfg.get('port',9450),timeout=20)
started=time.monotonic();first=None;chunks=[];size=0
try:
    client.request('POST',args.endpoint,json.dumps({'text':args.text,'local_only':args.local_only}),headers={'Authorization':'Bearer '+Path(cfg['token_file']).read_text().strip(),'Content-Type':'application/json'})
    response=client.getresponse()
    if response.status!=200:raise RuntimeError('voice_unavailable:'+str(response.status))
    if response.getheader('X-Sample-Rate')!='16000' or response.getheader('X-Channels')!='1':raise RuntimeError('invalid_audio_headers')
    while True:
        part=response.read1(4096)
        if not part:break
        if first is None:first=time.monotonic()-started
        size+=len(part)
        if size>8*1024*1024:raise RuntimeError('audio_too_large')
        chunks.append(part)
    if not size or size%2:raise RuntimeError('invalid_pcm')
    args.wav.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(args.wav),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(b''.join(chunks))
    print(json.dumps({'first_pcm_s':round(first,4),'total_s':round(time.monotonic()-started,4),'pcm_bytes':size,'audio_duration_s':size/32000,'endpoint':args.endpoint,'local_only':args.local_only,'status':'passed'}))
finally:client.close()
