"""Idempotent, durable GPU fencing through the fixed Windows _coord helper."""
import base64,json,os,re,subprocess,threading,uuid,urllib.request,urllib.error,ssl
from pathlib import Path

def valid_lease(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',value))

class GpuBroker:
    def __init__(self,cfg):
        self.cfg=cfg;self.lock=threading.Lock();self.state=Path(cfg['state_file']);self.state.parent.mkdir(parents=True,exist_ok=True)
        if cfg.get('ssh_host')!='terrerov@tuf-1' or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}',cfg['owner']) or not re.fullmatch(r'T-\d{8}-\d{2}',cfg['task']):raise ValueError('invalid_gpu_broker')
    def save(self,state):
        temp=self.state.with_suffix('.next')
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump(state,f);f.flush();os.fsync(f.fileno())
        os.replace(temp,self.state)
        fd=os.open(self.state.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    def command(self,action,lease):
        owner=self.cfg['owner'];task=self.cfg['task']
        pre="$ErrorActionPreference='Stop'; $root='C:\\Users\\terrerov\\Projects\\_coord'; $path=Join-Path $root 'LOCKS\\gpu.lock'; $tool=Join-Path $root 'tools\\coord.ps1'; "
        match=f"$body -match '(?m)^owner: {owner}\\r?$' -and $body -match '(?m)^task: {task}\\r?$' -and $body -match '(?m)^scope: .*lease={lease}\\r?$'"
        if action=='lock':
            # The fencing ID is inside coord.ps1's atomic CreateNew body, not appended later.
            script=pre+f"if(Test-Path $path){{$body=[IO.File]::ReadAllText($path);if({match}){{& $tool renew -Resource gpu -Owner {owner} -Hours 0.033333;exit $LASTEXITCODE}}}}; & $tool lock -Resource gpu -Owner {owner} -Task {task} -Scope 'Sagwa Chatterbox VRAM, lease={lease}' -Hours 0.033333; exit $LASTEXITCODE"
        else:
            script=pre+f"if(!(Test-Path $path)){{exit {0 if action=='unlock' else 4}}}; $body=[IO.File]::ReadAllText($path);if(!({match})){{exit 4}}; & $tool {action} -Resource gpu -Owner {owner} "+('-Hours 0.033333; ' if action=='renew' else '; ')+"exit $LASTEXITCODE"
        result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','-o','StrictHostKeyChecking=yes',self.cfg['ssh_host'],'powershell','-NoProfile','-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode()],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8)
        if result.returncode:raise RuntimeError('gpu_busy' if result.returncode==3 else 'gpu_fenced')
    def handle(self,action,lease=None):
        if action not in ('lock','renew','unlock') or not valid_lease(lease):raise ValueError('invalid_gpu_request')
        with self.lock:
            state=json.loads(self.state.read_text()) if self.state.exists() else None
            if state and lease!=state['lease']:raise RuntimeError('gpu_busy')
            if action=='lock':
                if not state:self.save({'lease':lease})
                try:self.command('lock',lease)
                except RuntimeError as e:
                    if str(e)=='gpu_busy':self.state.unlink() # Confirmed CreateNew failure, no lease acquired.
                    raise
                # On SSH timeout, preserve fencing and allow this same request to retry.
                return {'lease':lease}
            if not state:raise RuntimeError('invalid_gpu_lease')
            self.command(action,lease)
            if action=='unlock':self.state.unlink()
            return {'ok':True}

class RemoteGpuLease:
    def __init__(self,cfg):
        self.cfg=cfg;self.path=Path(cfg['state_file']) if cfg.get('state_file') else None;self.lease=None;self.acquired=False
        if self.path and self.path.exists():
            self.lease=json.loads(self.path.read_text())['lease']
            if not valid_lease(self.lease):raise ValueError('invalid_saved_lease')
        if not cfg['url'].startswith('https://'):raise ValueError('invalid_gpu_url')
        self.context=ssl.create_default_context(cafile=cfg['ca_file']);self.context.load_cert_chain(cfg['cert_file'],cfg['key_file'])
    def call(self,action):
        req=urllib.request.Request(self.cfg['url']+'/'+action,json.dumps({'lease':self.lease}).encode(),headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,context=self.context,timeout=10) as r:return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code==409:raise RuntimeError(json.load(e).get('error','gpu_failed'))
            raise
    def acquire(self):
        if not self.lease:
            self.lease=str(uuid.uuid4())
            if self.path:
                fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
                with os.fdopen(fd,'w') as f:json.dump({'lease':self.lease},f);f.flush();os.fsync(f.fileno())
        self.call('renew' if self.acquired else 'lock');self.acquired=True
    def release(self):
        if self.lease:
            try:self.call('unlock')
            except RuntimeError as e:
                if str(e)!='invalid_gpu_lease':raise
            self.lease=None;self.acquired=False
            if self.path and self.path.exists():self.path.unlink()
