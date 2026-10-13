import threading,time,unittest,sys
from types import SimpleNamespace,ModuleType
from unittest.mock import patch
from chatterbox_engine import Chatterbox,sentences
from tts_router import AttemptCancel
class Gpu:
    lease='saved';acquired=True
    def __init__(self):self.releases=0
    def acquire(self):pass
    def release(self):self.releases+=1;self.lease=None
class ChatterboxTests(unittest.TestCase):
    def fake(self):
        e=object.__new__(Chatterbox);e.gpu=Gpu();e.lock=threading.Lock();e.warm_lock=threading.Lock();e.model=None;e.used=0;e.renewed=0;e.last_error=None;return e
    def test_cold_request_fails_over_immediately(self):
        e=self.fake();warm=[];e.start_warmup=lambda:warm.append(True);t=time.monotonic()
        with self.assertRaisesRegex(RuntimeError,'warming'):list(e.stream('Hola',threading.Event()))
        self.assertLess(time.monotonic()-t,.1);self.assertEqual(warm,[True])
    def test_warmup_failure_drops_local_model_before_unlock(self):
        e=self.fake();e.cfg={'model_dir':'unused','reference_wav':'unused'};destroyed=[];module=ModuleType('chatterbox.tts')
        class Model:
            @classmethod
            def from_local(cls,*args):return cls()
            def prepare_conditionals(self,*args,**kwargs):pass
            def generate(self,*args,**kwargs):raise RuntimeError('warmup failed')
            def __del__(self):destroyed.append(True)
        module.ChatterboxTTS=Model
        original=e.gpu.release
        def release():self.assertTrue(destroyed,'GPU unlocked while local model survived');original()
        e.gpu.release=release
        with patch.dict(sys.modules,{'chatterbox':ModuleType('chatterbox'),'chatterbox.tts':module}):
            e.start_warmup();self.assertTrue(e.warm_lock.acquire(timeout=5));e.warm_lock.release()
        self.assertEqual(e.gpu.releases,1);self.assertIsNone(e.model)
    def test_token_cancellation_unwinds_hooks_and_gpu(self):
        import torch
        e=self.fake();stop=threading.Event();layer=torch.nn.Identity();decoder=torch.nn.Identity()
        class Model:
            sr=24000;t3=SimpleNamespace(tfmr=layer);s3gen=SimpleNamespace(flow=SimpleNamespace(decoder=decoder))
            def generate(self,*args,**kwargs):
                layer(torch.zeros(1));stop.set();layer(torch.zeros(1));raise AssertionError('cancel hook missed')
        e.model=Model()
        self.assertEqual(list(e.stream('Hola, Josmar.',stop)),[]);self.assertEqual(e.gpu.releases,1);self.assertIsNone(e.model);self.assertEqual(len(layer._forward_pre_hooks),0)
    def test_reaper_survives_unlock_failure(self):
        e=self.fake();calls=[]
        def unload():calls.append(1);raise OSError('ssh unavailable')
        e.unload=unload
        with patch('chatterbox_engine.time.sleep',side_effect=[None,None,StopIteration()]):
            with self.assertRaises(StopIteration):e.reaper()
        self.assertEqual(len(calls),2);self.assertEqual(e.last_error,'gpu_release_retry')
    def test_first_audio_timeout_keeps_hot_model_without_ssh(self):
        e=self.fake();e.model=SimpleNamespace(sr=24000);cancel=AttemptCancel()
        def synth(text,stop):stop.set('first_audio_timeout');return None
        e.synthesize=synth;e.gpu.acquire=lambda:(_ for _ in ()).throw(AssertionError('SSH in request'))
        self.assertEqual(list(e.stream('Hola',cancel)),[]);self.assertIsNotNone(e.model);self.assertEqual(e.gpu.releases,0)
        cancel.set('client_cancel');self.assertEqual(cancel.reason,'first_audio_timeout')
    def test_client_cancel_drops_hot_model(self):
        e=self.fake();e.model=SimpleNamespace(sr=24000);cancel=AttemptCancel()
        def synth(text,stop):stop.set('client_cancel');return None
        e.synthesize=synth
        self.assertEqual(list(e.stream('Hola',cancel)),[]);self.assertIsNone(e.model);self.assertEqual(e.gpu.releases,1)
    def test_renewal_is_outside_request(self):
        e=self.fake();e.model=object();e.used=time.monotonic();e.renewed=e.used-50;calls=[];e.gpu.acquire=lambda:calls.append(1)
        with patch('chatterbox_engine.time.sleep',side_effect=[None,StopIteration()]):
            with self.assertRaises(StopIteration):e.reaper()
        self.assertEqual(calls,[1])
    def test_sentence_bounds(self):
        self.assertEqual(list(sentences('Hola. Estoy aquí.')),['Hola.','Estoy aquí.']);self.assertTrue(all(len(x.split())<=20 for x in sentences('palabra '*100)))
if __name__=='__main__':unittest.main()
