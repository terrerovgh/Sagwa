"""Reviewed NWS code and fixed-city Mac/TUF gateway deployment with private rollback archives.

Changes only the weather field in existing configs; preserves credentials, assets, dependencies, voice, Docker models,
etcd and lenlab. Apply/rollback require an explicit operation; prepare is default.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import ssl
import tarfile
import tempfile
import time
import urllib.request
import uuid
import zipfile

if sys.version_info < (3,12):
    raise RuntimeError('Python 3.12+ required for safe tar extraction; no deployment started')

ROOT = Path(__file__).resolve().parents[1]
APP = Path.home() / 'Library/Application Support/AgentShell'
NODE = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-J', 'terrerov@tuf-1', '-p', '2222', 'root@172.22.25.125']
REMOTE = r'''
import sys,json,hashlib,tarfile,pathlib,os,subprocess,tempfile
op,state=json.loads(sys.stdin.read())
base=pathlib.Path('/opt/agentshell/app');backup=pathlib.Path(state['tuf'])
assert backup.parent==pathlib.Path('/var/lib/agentshell/backups')
assert backup.name.startswith('edge-') and len(backup.name)==21
def hashes(folder):
 return {str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob('*')) if p.is_file()}
if op=='prepare':
 subprocess.run(['systemctl','is-active','--quiet','agentshell-gateway'],check=True)
 backup.mkdir(mode=0o700)
 with tarfile.open(backup/'dist-before.tar.gz','w:gz') as out:out.add(base/'dist',arcname='dist')
 os.chmod(backup/'dist-before.tar.gz',0o600)
 before=hashes(base/'dist')
 with tempfile.TemporaryDirectory(dir=backup) as test:
  with tarfile.open(backup/'dist-before.tar.gz') as archive:archive.extractall(test,filter='data')
  assert hashes(pathlib.Path(test)/'dist')==before,'Rollback archive does not restore exact code'
 (backup/'dist-before.sha.json').write_text(json.dumps(before))
 print(json.dumps({'files':len(before),'restore_hashes_equal':True,'archive_sha256':hashlib.sha256((backup/'dist-before.tar.gz').read_bytes()).hexdigest()}))
else:
 assert op in ('apply','rollback')
 if op=='apply':subprocess.run(['systemctl','is-active','--quiet','agentshell-gateway'],check=True)
 archive=backup/('dist-candidate.tar.gz' if op=='apply' else 'dist-before.tar.gz')
 expected=state['candidate_files'] if op=='apply' else json.loads((backup/'dist-before.sha.json').read_text())
 current=hashes(base/'dist');before=json.loads((backup/'dist-before.sha.json').read_text())
 assert current in (before,state['candidate_files']),'Gateway code changed outside this deployment'
 with tempfile.TemporaryDirectory(prefix='edge-stage-',dir=base) as stage:
  with tarfile.open(archive) as src:src.extractall(stage,filter='data')
  staged=pathlib.Path(stage)/'dist';assert hashes(staged)==expected,'Stage hashes differ'
  for p in staged.rglob('*'):os.chown(p,999,988)
  os.chown(staged,999,988)
  previous=None
  if hashes(base/'dist')!=expected:
   import uuid
   previous=base/('dist-retained-'+state['stamp']+'-'+op+'-'+uuid.uuid4().hex[:12])
   os.rename(base/'dist',previous)
   try:os.rename(staged,base/'dist')
   except BaseException:os.rename(previous,base/'dist');raise
 subprocess.run(['systemctl','restart','agentshell-gateway'],check=True,timeout=90)
 assert hashes(base/'dist')==expected
 print(json.dumps({'code_hashes_equal':True,'operation':op,'retained':str(previous) if previous else None}))
'''


def hashes(folder):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob('*')) if p.is_file()}


def remote(operation, state):
    import shlex
    result = subprocess.run(SSH + ['python3 -c ' + shlex.quote(REMOTE)],
                            input=json.dumps([operation, state]), text=True,
                            capture_output=True, timeout=120, check=True)
    return json.loads(result.stdout)


def restart_mac():
    result = subprocess.run(['launchctl', 'print', 'system/ai.agentshell.gateway'],
                            capture_output=True, text=True, check=True)
    match = re.search(r'\n\s*pid = (\d+)', result.stdout)
    if not match:
        raise RuntimeError('Existing Mac gateway has no running PID; no service activation')
    pid = int(match[1])
    uid = subprocess.check_output(['ps', '-o', 'uid=', '-p', str(pid)], text=True).strip()
    if uid != str(os.getuid()):
        raise RuntimeError('Mac gateway process is not owned by this user')
    os.kill(pid, signal.SIGTERM)  # Existing KeepAlive supervisor starts one replacement.


WEATHER = {'provider':'nws','city':'Ray City, GA','latitude':31.0728,'longitude':-83.1901}
CONFIG_REMOTE = r"""
import sys,json,pathlib,hashlib,os,stat,tempfile,shutil
op,backup_path,weather,expected=json.loads(sys.stdin.read())
backup=pathlib.Path(backup_path);cfg=pathlib.Path('/opt/agentshell/private/config.json')
assert backup.parent==pathlib.Path('/var/lib/agentshell/backups') and backup.name.startswith('edge-') and len(backup.name)==21
old=backup/'config-before.json';candidate=backup/'config-weather.json'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
if op=='prepare':
 st=cfg.stat();assert stat.S_ISREG(st.st_mode) and not cfg.is_symlink()
 data=json.loads(cfg.read_bytes());before=digest(cfg)
 data['weather']=weather;encoded=(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode()
 # Backups remain on their own host with restrictive access. No config body
 # or credential value leaves this process; transport contains public city only.
 for path,body in [(old,cfg.read_bytes()),(candidate,encoded)]:
  with path.open('xb') as f:f.write(body);f.flush();os.fsync(f.fileno())
  os.chmod(path,0o600)
 print(json.dumps({'before_sha256':before,'candidate_sha256':digest(candidate),'uid':st.st_uid,'gid':st.st_gid,'mode':stat.S_IMODE(st.st_mode)}))
else:
 assert op in ('apply','rollback')
 destination=candidate if op=='apply' else old
 wanted=expected['candidate_sha256'] if op=='apply' else expected['before_sha256']
 allowed={expected['before_sha256'],expected['candidate_sha256']}
 assert digest(cfg) in allowed and digest(destination)==wanted,'Config changed outside this weather deployment'
 if digest(cfg)!=wanted:
  fd,temp=tempfile.mkstemp(prefix='.sagwa-weather-',dir=cfg.parent)
  try:
   with os.fdopen(fd,'wb') as out:out.write(destination.read_bytes());out.flush();os.fsync(out.fileno())
   os.chmod(temp,expected['mode']);os.chown(temp,expected['uid'],expected['gid']);os.replace(temp,cfg)
   fd=os.open(cfg.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
  finally:
   if os.path.exists(temp):os.unlink(temp)
 assert digest(cfg)==wanted
 print(json.dumps({'operation':op,'hash_equal':True}))
"""

def config_remote(operation,state):
    import shlex
    result=subprocess.run(SSH+['python3 -c '+shlex.quote(CONFIG_REMOTE)],
        input=json.dumps([operation,state['tuf'],WEATHER,state.get('tuf_config')]),
        text=True,capture_output=True,check=True,timeout=30)
    return json.loads(result.stdout)

def prepare_weather_configs(state):
    cfg=APP/'private/config.json';backup=Path(state['mac'])
    if cfg.is_symlink():raise RuntimeError('Unexpected config symlink')
    st=cfg.stat();original=cfg.read_bytes();data=json.loads(original);data['weather']=WEATHER
    candidate=(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode()
    for name,body in [('config-before.json',original),('config-weather.json',candidate)]:
        path=backup/name
        with path.open('xb') as f:f.write(body);f.flush();os.fsync(f.fileno())
        path.chmod(0o600)
    state['mac_config']={'before_sha256':hashlib.sha256(original).hexdigest(),
        'candidate_sha256':hashlib.sha256(candidate).hexdigest(),'uid':st.st_uid,'gid':st.st_gid,'mode':st.st_mode&0o777}
    state['tuf_config']=config_remote('prepare',state)
    state['weather']=WEATHER

def set_weather_config(host,operation,state):
    if operation not in ('apply','rollback'):raise RuntimeError('Invalid config operation')
    if host=='tuf':return config_remote(operation,state)
    cfg=APP/'private/config.json';backup=Path(state['mac']);expected=state['mac_config']
    if cfg.is_symlink():raise RuntimeError('Unexpected config symlink')
    wanted=expected['candidate_sha256'] if operation=='apply' else expected['before_sha256']
    source=backup/('config-weather.json' if operation=='apply' else 'config-before.json')
    if hashlib.sha256(cfg.read_bytes()).hexdigest() not in {expected['candidate_sha256'],expected['before_sha256']}:
        raise RuntimeError('Config changed outside this weather deployment')
    if hashlib.sha256(source.read_bytes()).hexdigest()!=wanted:raise RuntimeError('Private config backup differs')
    if hashlib.sha256(cfg.read_bytes()).hexdigest()!=wanted:
        fd,temp=tempfile.mkstemp(prefix='.sagwa-weather-',dir=cfg.parent)
        try:
            with os.fdopen(fd,'wb') as out:out.write(source.read_bytes());out.flush();os.fsync(out.fileno())
            os.chmod(temp,expected['mode']);os.chown(temp,expected['uid'],expected['gid']);os.replace(temp,cfg)
            fd=os.open(cfg.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    if hashlib.sha256(cfg.read_bytes()).hexdigest()!=wanted:raise RuntimeError('Config install differs')
    return {'operation':operation,'hash_equal':True}

def wait_gateway_health():
    tls=ROOT/'.private/mac-mini/tls'
    context=ssl.create_default_context(cafile=str(tls/'ca.pem'))
    context.load_cert_chain(str(tls/'cert.pem'),str(tls/'key.pem'))
    for gateway in ('https://192.168.4.82:9443','https://100.65.98.90:9443'):
        deadline=time.monotonic()+25
        while True:
            try:
                with urllib.request.urlopen(gateway+'/health',context=context,timeout=3) as response:
                    if response.status==200 and json.load(response).get('status')=='ok':break
            except Exception:
                pass
            if time.monotonic()>=deadline:raise RuntimeError('Own gateway health timeout')
            time.sleep(1)


def prepare():
    receipt = json.loads((ROOT / 'evidence/sagwa-v2/edge-weather-l-review.json').read_text())
    if receipt.get('status') != 'terminal_pass' or receipt.get('verdict') != 'PASS':
        raise RuntimeError('Actual scoped weather L review has not passed')
    archive = ROOT / 'evidence/sagwa-v2/sagwa-weather-gateway-l-source.zip'
    archive_sha = '5cd439dfd22a9dcaafda0aaf9b98b2eea4b68d19c4151cd06bceac36302b2da8'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != archive_sha:
        raise RuntimeError('Frozen reviewed gateway L source archive differs')
    with zipfile.ZipFile(archive) as bundle:
        frozen = json.loads(bundle.read('source-manifest.json'))
        for name, expected in frozen.items():
            if hashlib.sha256(bundle.read(name)).hexdigest() != expected:
                raise RuntimeError('Frozen archive source digest differs: ' + name)
            if bundle.read(name) != (ROOT / name).read_bytes():
                raise RuntimeError('Current source differs from reviewed L: ' + name)
    if receipt['script_sha256'] != hashlib.sha256((ROOT/'src/weather.ts').read_bytes()).hexdigest():
        raise RuntimeError('Reviewed weather.ts differs')
    subprocess.run(['launchctl','print','system/ai.agentshell.gateway'],check=True,capture_output=True)
    subprocess.run([str(NODE), str(ROOT / 'node_modules/typescript/bin/tsc'), '-p', str(ROOT / 'tsconfig.json')], check=True)
    subprocess.run([str(NODE), '--check', str(ROOT / 'dist/main.js')], check=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = APP / 'state/backups' / ('edge-' + stamp)
    backup.mkdir(mode=0o700)
    before = hashes(APP / 'dist')
    with tarfile.open(backup / 'dist-before.tar.gz', 'w:gz') as tar:
        tar.add(APP / 'dist', arcname='dist')
    (backup / 'dist-before.tar.gz').chmod(0o600)
    with tempfile.TemporaryDirectory(dir=backup) as test:
        with tarfile.open(backup / 'dist-before.tar.gz') as tar:
            tar.extractall(test, filter='data')
        if hashes(Path(test) / 'dist') != before:
            raise RuntimeError('Mac rollback archive does not restore exact code')
    with tarfile.open(backup / 'dist-candidate.tar.gz', 'w:gz') as tar:
        tar.add(ROOT / 'dist', arcname='dist')
    (backup / 'dist-candidate.tar.gz').chmod(0o600)
    state = dict(stamp=stamp, mac=str(backup), tuf='/var/lib/agentshell/backups/edge-' + stamp,
                 previous_mac_files=before, candidate_files=hashes(ROOT / 'dist'),
                 mac_restore_hashes_equal=True, review_session=receipt['grok_session'], source_archive_sha256=archive_sha, procedure_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    state['tuf_backup'] = remote('prepare', state)
    subprocess.run(SSH + ['cat > ' + state['tuf'] + '/dist-candidate.tar.gz'],
                   input=(backup / 'dist-candidate.tar.gz').read_bytes(), check=True)
    subprocess.run(SSH + ['chmod 600 ' + state['tuf'] + '/dist-candidate.tar.gz'], check=True)
    path = backup / 'deployment.json'
    prepare_weather_configs(state)
    path.write_text(json.dumps(state, indent=2) + '\n'); path.chmod(0o600)
    print(json.dumps({'backup_state':str(path), 'mac_restore_hashes_equal':True,
                      'tuf_restore_hashes_equal':state['tuf_backup']['restore_hashes_equal'],
                      'candidate_files':len(state['candidate_files'])}, indent=2))


def install(operation, path):
    state = json.loads(path.read_text())
    backup = Path(state['mac'])
    if backup.parent != APP / 'state/backups' or not re.fullmatch(r'edge-\d{8}T\d{6}Z', backup.name):
        raise RuntimeError('Invalid private backup path')
    expected = state['candidate_files'] if operation == 'apply' else state['previous_mac_files']
    if hashes(APP / 'dist') not in (state['candidate_files'],state['previous_mac_files']):
        raise RuntimeError('Mac gateway code changed outside this deployment')
    archive = backup / ('dist-candidate.tar.gz' if operation == 'apply' else 'dist-before.tar.gz')
    with tempfile.TemporaryDirectory(prefix='edge-stage-', dir=APP) as stage:
        with tarfile.open(archive) as tar:
            tar.extractall(stage, filter='data')
        staged = Path(stage) / 'dist'
        if hashes(staged) != expected:
            raise RuntimeError('Mac staged code differs')
        if hashes(APP / 'dist') != expected:
            retained = APP / ('dist-retained-' + state['stamp'] + '-' + operation + '-' + uuid.uuid4().hex[:12])
            (APP / 'dist').rename(retained)
            try:
                staged.rename(APP / 'dist')
            except BaseException:
                retained.rename(APP / 'dist')
                raise
    set_weather_config('mac', operation, state)
    set_weather_config('tuf', operation, state)
    mac_error = None
    try:
        restart_mac()
    except Exception as error:
        mac_error = error
    # Always attempt TUF rollback even if Mac cannot be restarted.
    if mac_error is not None and operation == 'apply':
        raise mac_error
    result = remote(operation, state)
    if mac_error is not None:
        raise mac_error
    wait_gateway_health()
    print(json.dumps({'operation':operation, 'mac_hashes_equal':hashes(APP / 'dist') == expected,
                      'tuf':result, 'weather':WEATHER if operation=='apply' else 'restored',
                      'voice_changed':False, 'lenlab_changed':False}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'apply', 'rollback'])
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    if args.operation == 'prepare':
        prepare()
    else:
        if not args.backup:
            parser.error('--backup is required')
        if not args.review:
            parser.error('--review required for a live operation')
        review=json.loads(args.review.read_text())
        if (review.get('status')!='terminal_pass' or review.get('verdict')!='PASS' or
                review.get('script_sha256')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()):
            raise RuntimeError('Exact deployment procedure review missing')
        state=json.loads(args.backup.read_text())
        if state.get('procedure_sha256')!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            raise RuntimeError('Prepared state belongs to another procedure')
        if args.operation=='apply':
            try:
                install('apply',args.backup)
            except BaseException:
                # Preserve the failure and both backups; restore only own exact
                # candidate state. Config guards refuse unrelated edits.
                try:install('rollback',args.backup)
                except BaseException as error:
                    print(json.dumps({'rollback_error_type':type(error).__name__}))
                raise
        else:
            install('rollback',args.backup)
