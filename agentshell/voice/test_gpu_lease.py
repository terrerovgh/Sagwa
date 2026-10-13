import json,subprocess,tempfile,unittest,uuid
from pathlib import Path
from gpu_lease import GpuBroker
class Broker(GpuBroker):
    def __init__(self,path):
        super().__init__({'ssh_host':'terrerov@tuf-1','owner':'codex-infra-sagwa','task':'T-20261012-03','state_file':str(path)});self.remote=None;self.timeout=False
    def command(self,action,lease):
        if action=='lock':
            if self.remote and self.remote!=lease:raise RuntimeError('gpu_busy')
            self.remote=lease
            if self.timeout:self.timeout=False;raise subprocess.TimeoutExpired('ssh',8)
        elif self.remote!=lease:raise RuntimeError('gpu_fenced')
        elif action=='unlock':self.remote=None
class LeaseTests(unittest.TestCase):
    def test_timeout_retry_fencing_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'lease.json';b=Broker(p);lease=str(uuid.uuid4());b.timeout=True
            with self.assertRaises(subprocess.TimeoutExpired):b.handle('lock',lease)
            self.assertEqual(json.loads(p.read_text())['lease'],lease)
            self.assertEqual(b.handle('lock',lease)['lease'],lease)
            with self.assertRaises(RuntimeError):b.handle('unlock',str(uuid.uuid4()))
            restarted=Broker(p);restarted.remote=lease
            restarted.handle('renew',lease);restarted.handle('unlock',lease);self.assertFalse(p.exists())
    def test_other_owner_never_removed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'lease.json';b=Broker(p);b.remote='someone-else'
            with self.assertRaises(RuntimeError):b.handle('lock',str(uuid.uuid4()))
            self.assertEqual(b.remote,'someone-else');self.assertFalse(p.exists())
    def test_rejects_shell_input(self):
        with tempfile.TemporaryDirectory() as d:
            b=Broker(Path(d)/'lease.json')
            for action,lease in [('unlock','x; rm'),('anything',str(uuid.uuid4())),('lock',None)]:
                with self.assertRaises(ValueError):b.handle(action,lease)
if __name__=='__main__':unittest.main()
