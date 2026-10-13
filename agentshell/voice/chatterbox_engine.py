"""Official pinned LATAM loader; cold loads fail over immediately, GPU work is fenced."""
import re,threading,time
import numpy as np
from tts_router import Resampler
class Cancelled(RuntimeError):pass

def sentences(text):
    for sentence in re.split(r'(?<=[.!?])\s+',text):
        words=sentence.split()
        for at in range(0,len(words),20):yield ' '.join(words[at:at+20])

class Chatterbox:
    name='chatterbox-es-mx-latam'
    def __init__(self,cfg):
        from gpu_lease import RemoteGpuLease
        self.gpu=RemoteGpuLease(cfg['gpu_broker']);self.cfg=cfg;self.model=None;self.lock=threading.Lock();self.warm_lock=threading.Lock();self.used=0;self.renewed=0;self.last_error=None
        threading.Thread(target=self.reaper,daemon=True).start();self.start_warmup()
    def unload(self):
        if self.model is not None:
            import torch
            self.model=None;torch.cuda.empty_cache()
        self.gpu.release()
    def reaper(self):
        while True:
            time.sleep(5)
            if self.lock.acquire(blocking=False):
                try:
                    if self.gpu.lease and time.monotonic()-self.used>60:self.unload()
                    elif self.model is not None and self.gpu.acquired and time.monotonic()-self.renewed>45:self.gpu.acquire();self.renewed=time.monotonic()
                except Exception:self.last_error='gpu_release_retry' # Keep fencing and retry, never kill reaper.
                finally:self.lock.release()
    def start_warmup(self):
        if not self.warm_lock.acquire(blocking=False):return
        def warm():
            failed=False;model=None;primer=None
            try:
                with self.lock:
                    if self.model is not None:return
                    self.gpu.acquire();self.renewed=time.monotonic()
                    from chatterbox.tts import ChatterboxTTS
                    model=ChatterboxTTS.from_local(self.cfg['model_dir'],'cuda')
                    model.prepare_conditionals(self.cfg['reference_wav'],exaggeration=.4)
                    primer=model.generate('Hola.',language_id='es',exaggeration=.4,cfg_weight=.5,temperature=.7)
                    # Fixed synthetic primer warms CUDA/vocoder; it is never sent to the device.
                    raw=primer.detach().cpu().numpy() if hasattr(primer,'detach') else np.asarray(primer)
                    pcm=np.clip(raw.flatten()*32767,-32768,32767).astype('<i2').tobytes()
                    from pathlib import Path
                    Path('/tmp/sagwa-primer.pcm').write_bytes(Resampler(model.sr).feed(pcm))
                    self.model=model;self.used=time.monotonic();self.last_error=None
            except Exception:
                self.last_error='chatterbox_warm_failed';failed=True
            finally:
                if failed:
                    # Leave the exception handler first: its traceback can retain CUDA tensors.
                    model=None;primer=None
                    try:
                        with self.lock:
                            import torch
                            torch.cuda.empty_cache();self.unload()
                    except Exception:self.last_error='gpu_release_retry'
                self.warm_lock.release()
        threading.Thread(target=warm,daemon=True).start()
    def synthesize(self,text,cancel):
        def check(module,args):
            if cancel.is_set():raise Cancelled()
        modules=[self.model.t3.tfmr,self.model.s3gen.flow.decoder]
        estimator=getattr(self.model.s3gen.flow.decoder,'estimator',None)
        if estimator is not None:modules.append(estimator)
        hooks=[m.register_forward_pre_hook(check) for m in modules]
        try:
            if cancel.is_set():return None
            return self.model.generate(text,language_id='es',exaggeration=.4,cfg_weight=.5,temperature=.7)
        except Cancelled:return None
        finally:
            for hook in hooks:hook.remove()
    def stream(self,text,cancel):
        if cancel.is_set():return
        if self.model is None:self.start_warmup();raise RuntimeError('chatterbox_warming')
        if not self.lock.acquire(blocking=False):raise RuntimeError('chatterbox_busy')
        try:
            if cancel.is_set():return
            if self.model is None:self.start_warmup();raise RuntimeError('chatterbox_warming')
            if not self.gpu.acquired:raise RuntimeError('gpu_not_leased')
            resample=Resampler(self.model.sr)
            for sentence in sentences(text):
                if cancel.is_set():
                    if getattr(cancel,'reason',None)!='first_audio_timeout':self.unload()
                    return
                audio=self.synthesize(sentence,cancel)
                if audio is None or cancel.is_set():
                    if getattr(cancel,'reason',None)!='first_audio_timeout':self.unload()
                    return
                if hasattr(audio,'detach'):audio=audio.detach().cpu().numpy()
                pcm=np.clip(np.asarray(audio).flatten()*32767,-32768,32767).astype('<i2').tobytes()
                for at in range(0,len(pcm),4096):
                    if cancel.is_set():
                        if getattr(cancel,'reason',None)!='first_audio_timeout':self.unload()
                        return
                    chunk=resample.feed(pcm[at:at+4096])
                    if chunk:yield chunk
        except Exception:
            try:self.unload()
            except Exception:self.last_error='gpu_release_retry'
            raise
        finally:self.used=time.monotonic();self.lock.release()
