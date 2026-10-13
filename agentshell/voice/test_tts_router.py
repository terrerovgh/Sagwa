import concurrent.futures,tempfile,threading,time,unittest
from pathlib import Path
from tts_router import Budget,Router,Resampler,Remote,OpenRouter
class Engine:
    name='fake-local'
    def __init__(self,delay=0,fail=False):self.delay=delay;self.fail=fail
    def stream(self,text,cancel):
        time.sleep(self.delay)
        if self.fail:raise RuntimeError('offline')
        if not cancel.is_set():yield b'\0\0'*100
class RouterTests(unittest.TestCase):
    def test_local_only_never_visits_remote_or_paid_engines(self):
        def forbidden(*args):raise AssertionError('local-only visited another host or paid API')
        remote=object.__new__(Remote);remote.stream=forbidden
        paid=object.__new__(OpenRouter);paid.stream=forbidden
        self.assertEqual(b''.join(Router([remote,paid,Engine()]).stream('Hola',local_only=True)),b'\0\0'*100)
    def test_default_deadline_leaves_network_and_local_fallback_margin(self):
        self.assertEqual(Router([]).timeout,1.5)
    def test_primary_offline_and_slow_cancel(self):
        for bad in (Engine(fail=True),Engine(.1)):
            r=Router([bad,Engine()],timeout=.02)
            self.assertEqual(b''.join(r.stream('Hola')),b'\0\0'*100)
    def test_cancelled_turn_never_returns_audio(self):
        stop=threading.Event();stop.set();self.assertEqual(b''.join(Router([Engine()]).stream('Hola',stop)),b'')
    def test_no_voice_switch_after_first_audio(self):
        class Broken(Engine):
            def stream(self,text,cancel):yield b'\0\0';raise RuntimeError('interrupted')
        stream=Router([Broken(),Engine()]).stream('Hola');self.assertEqual(next(stream),b'\0\0')
        with self.assertRaises(RuntimeError):next(stream)
    def test_shared_budget_concurrency_and_month(self):
        with tempfile.TemporaryDirectory() as d:
            budget=Budget(Path(d)/'budget.db')
            def reserve(n):
                try:budget.reserve('1',str(n),month='2026-10');return True
                except ValueError:return False
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:self.assertEqual(sum(pool.map(reserve,range(20))),5)
            with self.assertRaises(ValueError):budget.reserve('.01','new',month='2026-10')
            budget.reserve('5','nov',month='2026-11')
            with self.assertRaises(ValueError):budget.reserve('0','invalid')
    def test_odd_chunks_and_resample_continuity(self):
        import numpy as np
        raw=(np.sin(np.arange(2400)*.03)*20000).astype('<i2').tobytes()
        a=Resampler(24000).feed(raw);r=Resampler(24000);b=b''.join(r.feed(raw[x:x+333]) for x in range(0,len(raw),333))
        self.assertEqual(a,b)
    def test_invalid_text(self):
        with self.assertRaises(ValueError):list(Router([Engine()]).stream(''))
if __name__=='__main__':unittest.main()
