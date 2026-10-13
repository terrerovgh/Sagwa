import tempfile
import threading
import unittest
import types
from pathlib import Path
from unittest.mock import patch

from tts_router import LocalContainer, Remote, Router, remote_engine, speech_segments


class ContainerTests(unittest.TestCase):
    def test_voice_constructor_honors_final_container_preference(self):
        from server import Voice
        class Chatterbox:
            name='chatterbox-local'
            def __init__(self,cfg):pass
        cfg={'primary':{'url':'http://127.0.0.1:9493/tts/stream'},
             'container':{'url':'http://127.0.0.1:9493/tts/stream','token_file':'/unused'},
             'chatterbox':{}, 'container_first':True}
        # Nonempty config activates the production constructor branch.
        cfg['chatterbox']={'fixture':True}
        with patch.dict('sys.modules',{'chatterbox_engine':types.SimpleNamespace(Chatterbox=Chatterbox)}):
            voice=Voice('/unused','/unused',cfg)
            self.assertEqual([e.name for e in voice.router.engines],
                             ['kokoro-docker-mac','chatterbox-local','chatterbox-tuf'])
            cfg['container_first']=False
            voice=Voice('/unused','/unused',cfg)
            self.assertEqual([e.name for e in voice.router.engines],
                             ['chatterbox-local','chatterbox-tuf','kokoro-docker-mac'])
    def test_long_speech_retains_numbers_and_words(self):
        text='Cuesta US$14.50 por unidad. ' + 'Estoy aquí contigo. '*20
        parts=speech_segments(text)
        self.assertEqual(' '.join(parts),text.strip())
        self.assertTrue(all(len(part)<=120 for part in parts))
        with self.assertRaises(ValueError):speech_segments('x'*121)
    def test_fixed_loopback_only(self):
        for url in ('http://localhost:9493/tts/stream',
                    'http://127.0.0.1:9493@evil.test/tts/stream',
                    'https://example.com/tts/stream',
                    'http://127.0.0.1:9493/stt'):
            with self.assertRaises(ValueError):
                LocalContainer({'url': url, 'token_file': '/unused'})

    def test_local_only_uses_container_and_keeps_native_fallback(self):
        class Native:
            name = 'native-backup'
            def stream(self, text, cancel):
                yield b'\x01\x00' * 20
        cfg = {'url': 'http://127.0.0.1:9493/tts/stream', 'token_file': '/unused'}
        local = LocalContainer(cfg)
        remote = Remote(cfg, 'remote-excluded')
        self.assertFalse(remote_engine(local))
        self.assertTrue(remote_engine(remote))
        with patch.object(LocalContainer, 'stream', side_effect=OSError('down')):
            router = Router([remote, local, Native()])
            self.assertEqual(b''.join(router.stream('Estoy aquí.', threading.Event(), True)), b'\x01\x00' * 20)
            self.assertEqual(router.local.engine, 'native-backup')


if __name__ == '__main__':
    unittest.main()
