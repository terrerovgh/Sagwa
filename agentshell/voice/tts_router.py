"""First-audio failover. One Mac ledger owns all paid TTS reservations."""
import datetime,decimal,json,queue,re,sqlite3,ssl,threading,time,urllib.request
from pathlib import Path
import numpy as np
D=decimal.Decimal
MODEL='elevenlabs/eleven-flash-v2.5'

class Budget:
    def __init__(self,path,limit='5'):
        self.path=str(path);self.limit=D(str(limit))
        if not 0<self.limit<=5:raise ValueError('invalid_budget')
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS spend (id TEXT PRIMARY KEY, month TEXT NOT NULL, amount TEXT NOT NULL, created REAL NOT NULL)')
        Path(path).chmod(0o600)
    def reserve(self,amount,request_id,month=None):
        amount=D(str(amount));month=month or datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m')
        if not amount.is_finite() or amount<=0:raise ValueError('invalid_price')
        with sqlite3.connect(self.path,timeout=5,isolation_level=None) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM spend WHERE id=?',(request_id,)).fetchone():raise ValueError('duplicate_reservation')
            used=sum((D(x[0]) for x in db.execute('SELECT amount FROM spend WHERE month=?',(month,))),D(0))
            if used+amount>self.limit:raise ValueError('budget_exhausted')
            db.execute('INSERT INTO spend VALUES (?,?,?,?)',(request_id,month,str(amount),time.time()));db.commit()
        # Charge the full upper bound even when the provider fails or disconnects.
        return amount

class Resampler:
    """Linear continuous PCM conversion; odd transport boundaries are preserved."""
    def __init__(self,rate):
        if rate not in (16000,22050,24000,44100,48000):raise ValueError('unknown_sample_rate')
        self.rate=rate;self.pending=b'';self.last=None;self.total=0;self.next=0.0
    def feed(self,data):
        data=self.pending+data;self.pending=data[-1:] if len(data)%2 else b'';data=data[:len(data)//2*2]
        if self.rate==16000:return data
        samples=np.frombuffer(data,dtype='<i2')
        if not len(samples):return b''
        start=self.total;self.total+=len(samples)
        values=samples.astype(np.float32)
        if self.last is not None:values=np.concatenate(([self.last],values));start-=1
        self.last=float(samples[-1]);stop=self.total-1
        if self.next>stop:return b''
        positions=np.arange(self.next,stop+1e-8,self.rate/16000);self.next=float(positions[-1]+self.rate/16000)
        return np.interp(positions,np.arange(start,start+len(values)),values).astype('<i2').tobytes()

class Kokoro:
    name='kokoro-ef_dora'
    def __init__(self,model_dir=None):self.pipeline=None;self.lock=threading.Lock();self.model_dir=model_dir
    def load(self):
        if self.pipeline is None:
            from kokoro import KPipeline,KModel
            model=KModel(repo_id='hexgrad/Kokoro-82M',**({'config':str(Path(self.model_dir)/'config.json'),'model':str(Path(self.model_dir)/'kokoro-v1_0.pth')} if self.model_dir else {}))
            import espeakng_loader
            from phonemizer.backend.espeak.wrapper import EspeakWrapper
            import os
            os.environ['ESPEAK_DATA_PATH']=espeakng_loader.get_data_path()
            EspeakWrapper.set_library(espeakng_loader.get_library_path())
            self.pipeline=KPipeline(lang_code='e',model=model,device='cpu')
    def stream(self,text,cancel):
        if not self.lock.acquire(blocking=False):raise RuntimeError('kokoro_busy')
        try:
            self.load();resample=Resampler(24000)
            voice=str(Path(self.model_dir)/'ef_dora.pt') if self.model_dir else 'ef_dora'
            for segment in speech_segments(text):
                if cancel.is_set():return
                for result in self.pipeline(segment,voice=voice,speed=1.0):
                    if cancel.is_set():return
                    audio=result.audio.detach().cpu().numpy() if hasattr(result.audio,'detach') else np.asarray(result.audio)
                    pcm=np.clip(audio*32767,-32768,32767).astype('<i2').tobytes()
                    for at in range(0,len(pcm),4096):
                        if cancel.is_set():return
                        chunk=resample.feed(pcm[at:at+4096])
                        if chunk:yield chunk
        finally:self.lock.release()

def speech_segments(text):
    """Keep all words/numbers; bound inference so cancellation can be observed."""
    sentences=re.split(r'(?<=[.!?])\s+|\n+',text.strip())
    if any(len(word)>120 for sentence in sentences for word in sentence.split()):
        raise ValueError('unpronounceable_token')
    result=[]
    for sentence in sentences:
        chunk=''
        for word in sentence.split():
            if chunk and len(chunk)+1+len(word)>120:
                result.append(chunk);chunk=''
            chunk=(chunk+' '+word).strip()
        if chunk:result.append(chunk)
    return result

class Remote:
    def __init__(self,cfg,name='chatterbox-tuf'):
        self.name=name;self.cfg=cfg
        self.context=ssl.create_default_context(cafile=cfg.get('ca_file'))
        if cfg.get('cert_file'):self.context.load_cert_chain(cfg['cert_file'],cfg['key_file'])
        url=cfg['url']
        if not (url.startswith('https://') or url.startswith('http://127.0.0.1:')):raise ValueError('insecure_voice_url')
    def open(self,request):
        return urllib.request.urlopen(request,context=self.context,timeout=2)
    def stream(self,text,cancel):
        req=urllib.request.Request(self.cfg['url'],json.dumps({'text':text,'local_only':self.cfg.get('local_only',self.cfg['url'].endswith('/tts/stream'))}).encode(),headers={'Content-Type':'application/json'})
        if self.cfg.get('token_file'):req.add_header('Authorization','Bearer '+Path(self.cfg['token_file']).read_text().strip())
        with self.open(req) as response:
            if response.headers.get('X-Sample-Rate')!='16000' or response.headers.get('X-Channels')!='1':raise ValueError('unsupported_audio')
            while not cancel.is_set():
                data=response.read1(4096)
                if not data:return
                yield data

class LocalContainer(Remote):
    """Only this fixed authenticated loopback worker counts as local inference."""
    def __init__(self,cfg):
        if cfg.get('url')!='http://127.0.0.1:9493/tts/stream' or not cfg.get('token_file'):
            raise ValueError('invalid_container_url')
        super().__init__({**cfg,'local_only':True},'kokoro-docker-mac')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def open(self,request):return self.opener.open(request,timeout=2)
    def transcribe(self,pcm):
        request=urllib.request.Request('http://127.0.0.1:9493/stt',pcm,headers={'Content-Type':'application/octet-stream','Authorization':'Bearer '+Path(self.cfg['token_file']).read_text().strip()})
        with self.opener.open(request,timeout=8) as response:
            body=response.read(32769)
            if len(body)>32768:raise ValueError('invalid_transcript')
            result=json.loads(body)
            if not isinstance(result.get('text'),str) or len(result['text'])>8192:raise ValueError('invalid_transcript')
            return result

def remote_engine(engine):
    return isinstance(engine,Remote) and not isinstance(engine,LocalContainer)

class OpenRouter:
    name='openrouter-bella'
    def __init__(self,cfg):
        self.cfg=cfg;self.budget=Budget(cfg['ledger_file'],cfg.get('monthly_limit_usd',5));self.price=None;self.price_at=0;self.lock=threading.Lock()
    def verified_price(self):
        with self.lock:
            with urllib.request.urlopen('https://openrouter.ai/api/v1/models?output_modalities=speech',timeout=3) as r:models=json.load(r)['data']
            m=next(x for x in models if x['id']==MODEL)
            if m['architecture']['modality']!='text->speech' or 'bella' not in m.get('supported_voices',[]):raise ValueError('unverified_model')
            p=m['pricing'];rate=D(p['prompt'])
            if D(p.get('completion','0'))!=0 or any(D(v)!=0 for k,v in p.items() if k not in ('prompt','completion')) or not rate.is_finite() or not 0<rate<=D('0.00002'):raise ValueError('unverified_price')
            with urllib.request.urlopen('https://openrouter.ai/api/v1/models/'+MODEL+'/endpoints',timeout=3) as r:endpoints=json.load(r)['data']['endpoints']
            # Models pricing can be a minimum across providers. Only the verified single provider is allowed.
            if len(endpoints)!=1 or endpoints[0].get('provider_name')!='ElevenLabs':raise ValueError('unverified_provider')
            ep=endpoints[0]['pricing']
            if D(str(ep['prompt']))!=rate or D(str(ep.get('completion',0)))!=0 or any(D(str(v))!=0 for k,v in ep.items() if k not in ('prompt','completion','discount')) or not 0<=D(str(ep.get('discount',0)))<=1:raise ValueError('unverified_provider_price')
            self.price=rate;self.price_at=time.time();return rate
    def stream(self,text,cancel):
        if cancel.is_set():return
        import uuid
        price=self.verified_price()
        # UTF-8 byte count is a conservative upper bound on character billing.
        self.budget.reserve(price*len(text.encode('utf8'))*D('1.1'),str(uuid.uuid4()))
        if cancel.is_set():return
        req=urllib.request.Request('https://openrouter.ai/api/v1/audio/speech',json.dumps({'model':MODEL,'input':text,'voice':'bella','response_format':'mp3'}).encode(),headers={'Authorization':'Bearer '+Path(self.cfg['key_file']).read_text().strip(),'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=8) as r:
            if not r.headers.get('Content-Type','').startswith('audio/mpeg'):raise ValueError('invalid_api_audio')
            import subprocess
            proc=subprocess.Popen([self.cfg['ffmpeg'],'-v','error','-i','pipe:0','-ar','16000','-ac','1','-f','s16le','pipe:1'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            def pump():
                try:
                    total=0
                    while not cancel.is_set():
                        data=r.read1(4096)
                        if not data:break
                        total+=len(data)
                        if total>8*1024*1024:break
                        proc.stdin.write(data);proc.stdin.flush()
                except (OSError,ValueError):pass
                finally:
                    try:proc.stdin.close()
                    except OSError:pass
            threading.Thread(target=pump,daemon=True).start()
            try:
                while not cancel.is_set():
                    chunk=proc.stdout.read1(4096)
                    if not chunk:break
                    yield chunk
                if not cancel.is_set() and proc.wait(timeout=2)!=0:raise ValueError('invalid_api_audio')
            finally:
                if proc.poll() is None:proc.kill()
                proc.wait(timeout=2)

class AttemptCancel(threading.Event):
    def __init__(self):super().__init__();self.reason=None;self.reason_lock=threading.Lock()
    def set(self,reason='client_cancel'):
        with self.reason_lock:
            if not self.is_set():self.reason=reason;super().set()

class Router:
    def __init__(self,engines,timeout=1.5):self.engines=engines;self.timeout=timeout;self.local=threading.local()
    def stream(self,text,stop=None,local_only=False):
        if not isinstance(text,str) or not text.strip() or len(text)>8192:raise ValueError('invalid_text')
        stop=stop or threading.Event()
        if stop.is_set():return
        for engine in self.engines:
            if local_only and (isinstance(engine,OpenRouter) or remote_engine(engine)):continue
            q=queue.Queue(maxsize=8);cancel=AttemptCancel()
            def produce(e=engine,q=q,cancel=cancel):
                try:
                    for chunk in e.stream(text,cancel):
                        if stop.is_set():cancel.set('client_cancel');break
                        if cancel.is_set():break
                        while not cancel.is_set() and not stop.is_set():
                            try:q.put(chunk,timeout=.1);break
                            except queue.Full:pass
                    if not cancel.is_set():q.put(None,timeout=.1)
                except Exception as exc:
                    try:q.put(exc,timeout=.1)
                    except queue.Full:pass
            threading.Thread(target=produce,daemon=True).start()
            try:
                committed=False
                first=q.get(timeout=8 if isinstance(engine,OpenRouter) else self.timeout)
                if first is None or isinstance(first,Exception) or not first:cancel.set('unavailable');continue
                self.local.engine=engine.name
                total=0
                while first is not None:
                    if stop.is_set():cancel.set('client_cancel');return
                    if isinstance(first,Exception):raise RuntimeError('tts_interrupted')
                    total+=len(first)
                    if total>8*1024*1024:raise ValueError('response_too_large')
                    committed=True
                    yield first
                    first=q.get(timeout=15)
                return
            except queue.Empty:
                cancel.set('stream_timeout' if committed else 'first_audio_timeout')
                if committed:raise RuntimeError('tts_interrupted')
                continue
            finally:cancel.set('client_cancel' if stop.is_set() else 'complete')
        raise RuntimeError('tts_unavailable')
