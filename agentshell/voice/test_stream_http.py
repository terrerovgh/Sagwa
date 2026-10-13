import http.client,json,threading,unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from server import Handler
from tts_router import Router,OpenRouter
class Voice:
    def __init__(self):self.more=threading.Event();self.router=None
    def stream(self,text,stop,local_only):
        yield b'\x01\x02'*32
        self.more.wait(2)
        if not stop.is_set():yield b'\x03\x04'*32
class HttpTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True;self.server.token='x'*40;self.server.slots=threading.BoundedSemaphore(2);self.server.voice=Voice();self.server.gpu_broker=None
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
    def tearDown(self):self.server.voice.more.set();self.server.shutdown();self.server.server_close()
    def test_progressive_chunk_and_auth(self):
        client=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        client.request('POST','/tts/stream',json.dumps({'text':'Hola'}),headers={'Authorization':'Bearer '+self.server.token,'Content-Type':'application/json'})
        r=client.getresponse();self.assertEqual(r.status,200);self.assertEqual(r.getheader('Transfer-Encoding'),'chunked');self.assertEqual(r.getheader('X-Sample-Rate'),'16000');self.assertEqual(r.read1(64),b'\x01\x02'*32)
        self.server.voice.more.set();self.assertEqual(r.read(),b'\x03\x04'*32);client.close()
        client=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3);client.request('POST','/tts/stream','{}');r=client.getresponse();self.assertEqual(r.status,401);r.read();client.close()
    def test_partial_failure_closes_stream(self):
        class Bad:
            def stream(self,*args):yield b'\0\0';raise RuntimeError('bad')
        self.server.voice=Bad();self.server.voice.more=threading.Event();self.server.voice.router=None
        client=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3);client.request('POST','/tts/stream','{"text":"Hola"}',headers={'Authorization':'Bearer '+self.server.token});r=client.getresponse();self.assertEqual(r.read1(2),b'\0\0')
        with self.assertRaises(http.client.IncompleteRead):r.read()
        client.close()
class PriceTests(unittest.TestCase):
    def test_unknown_charges_fail_closed(self):
        import io
        model={'id':'elevenlabs/eleven-flash-v2.5','architecture':{'modality':'text->speech'},'supported_voices':['bella'],'pricing':{'prompt':'0.00002','completion':'0','request':'0.01'}}
        engine=object.__new__(OpenRouter);engine.lock=threading.Lock();engine.price=None;engine.price_at=0
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps({'data':[model]}).encode())):
            with self.assertRaises(ValueError):engine.verified_price()
        model['pricing']['request']='0'
        with patch('urllib.request.urlopen',side_effect=[io.BytesIO(json.dumps({'data':[model]}).encode()),io.BytesIO(json.dumps({'data':{'endpoints':[{'provider_name':'ElevenLabs','pricing':{'prompt':'0.00002','completion':'0','discount':.5}}]}}).encode())]):self.assertEqual(str(engine.verified_price()),'0.00002')
        # A previous verified price must not bypass the fresh query.
        with patch('urllib.request.urlopen',side_effect=OSError('offline')):
            with self.assertRaises(OSError):engine.verified_price()
if __name__=='__main__':unittest.main()
