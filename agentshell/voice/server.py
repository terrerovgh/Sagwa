"""Offline Spanish voice service. Only loopback is accepted; bodies are never logged."""
import argparse,hashlib,hmac,json,os,threading,struct
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from tts_router import Router,Kokoro,Remote,LocalContainer,OpenRouter,remote_engine
from gpu_lease import GpuBroker
import numpy as np

class Voice:
    def __init__(self, whisper, piper, cfg=None):
        self.whisper_path=whisper;self.piper_path=piper
        self.whisper=None;self.piper=None;self.lock=threading.Lock();self.cfg=cfg or {};self.router=None;self.warm=False;self.container_worker=None
        engines=[]
        if self.cfg.get("primary"):engines.append(Remote(self.cfg["primary"]))
        if self.cfg.get("container"):
            worker=LocalContainer(self.cfg["container"])
            self.container_worker=worker
            engines.append(worker)
        if self.cfg.get("kokoro"):
            engine=Kokoro(self.cfg["kokoro"].get("model_dir"));engines.append(engine)
        if self.cfg.get("chatterbox"):
            from chatterbox_engine import Chatterbox
            engines.insert(0,Chatterbox(self.cfg["chatterbox"]))
        if self.cfg.get("api"):engines.append(OpenRouter(self.cfg["api"]))
        if self.cfg.get("fallback"):engines.append(Remote(self.cfg["fallback"],"mac-mini-fallback"))
        if self.container_worker and self.cfg.get('container_first',False):
            engines.remove(self.container_worker);engines.insert(0,self.container_worker)
        if engines:self.router=Router(engines)
        if self.cfg.get("kokoro"):
            def warmup(engine=engine):
                try:engine.load();self.warm=True
                except Exception:self.warm=False
            threading.Thread(target=warmup,daemon=True).start()
    def stt(self, pcm):
        if not pcm or len(pcm)%2 or len(pcm)>1920000: raise ValueError('invalid_pcm')
        worker=self.container_worker
        if worker:
            # The same fixed loopback worker owns STT. If it fails, retain native STT.
            try:
                return worker.transcribe(pcm)
            except Exception:pass
        audio=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
        with self.lock:
            if self.whisper is None:
                from faster_whisper import WhisperModel
                self.whisper=WhisperModel(self.whisper_path,device='cpu',compute_type='int8',cpu_threads=2,local_files_only=True)
            segments,info=self.whisper.transcribe(audio,language='es',vad_filter=True,beam_size=5,initial_prompt='Conversación en español. AgentShell, Muse, Hermes, Codex, OpenCode, CoreS3, Tailscale, tuf-infra, lenlab y Mac mini.')
            return {'text':' '.join(s.text.strip() for s in segments),'language':info.language,'duration_s':len(audio)/16000}
    def stream(self,text,stop=None,local_only=False):
        if not self.router:yield self.tts(text);return
        yield from self.router.stream(text,stop,local_only)
    def tts(self, text):
        if self.router:return b"".join(self.router.stream(text))
        if not isinstance(text,str) or not text.strip() or len(text)>8192: raise ValueError('invalid_text')
        with self.lock:
            if self.piper is None:
                from piper import PiperVoice
                self.piper=PiperVoice.load(self.piper_path)
            chunks=[]
            for chunk in self.piper.synthesize(text):
                raw=np.frombuffer(chunk.audio_int16_bytes,dtype='<i2')
                if chunk.sample_rate!=16000:
                    positions=np.arange(int(len(raw)*16000/chunk.sample_rate))*chunk.sample_rate/16000
                    raw=np.interp(positions,np.arange(len(raw)),raw).astype('<i2')
                chunks.append(raw.tobytes())
                if sum(map(len,chunks))>8*1024*1024: raise ValueError('response_too_large')
            return b''.join(chunks)

class Handler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    def log_message(self,*args): pass
    def reply(self,status,data,kind='application/json'):
        if kind=='application/json': data=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.path=='/health': self.reply(200,{'status':'ok','language':'es','models_present':Path(self.server.voice.whisper_path).is_dir(), 'kokoro_warm':self.server.voice.warm, 'tts_engines':[e.name for e in self.server.voice.router.engines] if self.server.voice.router else ['piper']})
        else: self.reply(404,{'error':'not_found'})
    def do_POST(self):
        started=False;stop=threading.Event()
        if not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+self.server.token): self.reply(401,{'error':'unauthorized'});return
        if not self.server.slots.acquire(blocking=False): self.reply(429,{'error':'busy'});return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<1 or length>(1920000 if self.path=='/stt' else 32768): self.reply(413,{'error':'invalid_size'});return
            self.connection.settimeout(15);data=self.rfile.read(length)
            if len(data)!=length: raise ValueError('incomplete_body')
            if self.path.startswith('/gpu/') and self.server.gpu_broker:
                action=self.path.split('/')[-1];request=json.loads(data)
                try:self.reply(200,self.server.gpu_broker.handle(action,request.get('lease')))
                except RuntimeError as e:self.reply(409,{'error':str(e) if str(e) in ('gpu_busy','gpu_fenced','invalid_gpu_lease') else 'gpu_failed'})
            elif self.path=='/stt': self.reply(200,self.server.voice.stt(data))
            elif self.path in ('/tts/stream','/tts/local-or-api'):
                request=json.loads(data);text=request['text']
                if self.path=='/tts/local-or-api' and self.server.voice.router:
                    router=Router([e for e in self.server.voice.router.engines if not remote_engine(e)])
                    stream=router.stream(text,stop,bool(request.get('local_only',False)))
                else:stream=self.server.voice.stream(text,stop,bool(request.get('local_only',False)))
                first=next(stream)
                self.send_response(200);self.send_header('Content-Type','audio/pcm');self.send_header('X-Sample-Rate','16000');self.send_header('X-Channels','1');self.send_header('Cache-Control','no-store');self.send_header('Transfer-Encoding','chunked');self.end_headers();started=True
                def chunked(chunk):
                    self.wfile.write(('%x\r\n'%len(chunk)).encode()+chunk+b'\r\n');self.wfile.flush()
                chunked(first)
                for chunk in stream:chunked(chunk)
                self.wfile.write(b'0\r\n\r\n');self.wfile.flush()
            elif self.path=='/tts': self.reply(200,self.server.voice.tts(json.loads(data)['text']),'application/octet-stream')
            elif self.path=='/tts/contextual':
                segments=json.loads(data).get('segments')
                if not isinstance(segments,list) or not 1<=len(segments)<=16 or any(not isinstance(s,str) for s in segments) or sum(map(len,segments))>8192: raise ValueError('invalid_segments')
                pcm=[];timing=[];samples=0;selected=None
                contextual_router=Router([e for e in self.server.voice.router.engines if not remote_engine(e)]) if self.server.voice.router else None
                for text in segments:
                    if contextual_router:
                        audio=b''.join(contextual_router.stream(text,stop))
                        if selected is None:
                            selected=next(e for e in contextual_router.engines if e.name==contextual_router.local.engine);contextual_router=Router([selected])
                    else:audio=self.server.voice.tts(text)
                    timing.append({'start_sample':samples,'samples':len(audio)//2});samples+=len(audio)//2;pcm.append(audio)
                    if samples*2>8*1024*1024:raise ValueError('response_too_large')
                metadata=json.dumps({'segments':timing,'sample_rate':16000},separators=(',',':')).encode()
                self.reply(200,b'AVS1'+struct.pack('<I',len(metadata))+metadata+b''.join(pcm),'application/octet-stream')
            else: self.reply(404,{'error':'not_found'})
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception:
            if not started:self.reply(503,{'error':'voice_failed'})
            else:self.close_connection=True
        finally: stop.set();self.server.slots.release()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);args=p.parse_args();cfg=json.loads(Path(args.config).read_text())
    token=Path(cfg['token_file']).read_text().strip()
    if len(token)<32: raise SystemExit('invalid_token')
    server=ThreadingHTTPServer(('127.0.0.1',cfg.get('port',9450)),Handler);server.daemon_threads=True;server.slots=threading.BoundedSemaphore(2);server.token=token;server.gpu_broker=GpuBroker(cfg['gpu_lease']) if cfg.get('gpu_lease') else None;server.voice=Voice(cfg['whisper_path'],cfg['piper_path'],cfg);server.serve_forever()
