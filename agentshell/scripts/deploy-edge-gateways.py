"""Code-only Mac/TUF gateway trial with private, verified rollback archives.

Preserves configs, credentials, assets, dependencies, voice, Docker models,
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
import tarfile
import tempfile
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP = Path.home() / 'Library/Application Support/AgentShell'
NODE = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
SSH = ['ssh', '-o', 'BatchMode=yes', '-J', 'terrerov@tuf-1', '-p', '2222', 'root@172.22.25.125']
REMOTE = r'''
import sys,json,hashlib,tarfile,pathlib,os,subprocess,tempfile
op,state=json.loads(sys.stdin.read())
base=pathlib.Path('/opt/agentshell/app');backup=pathlib.Path(state['tuf'])
assert backup.parent==pathlib.Path('/var/lib/agentshell/backups')
assert backup.name.startswith('edge-') and len(backup.name)==21
def hashes(folder):
 return {str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob('*')) if p.is_file()}
if op=='prepare':
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
 archive=backup/('dist-candidate.tar.gz' if op=='apply' else 'dist-before.tar.gz')
 expected=state['candidate_files'] if op=='apply' else json.loads((backup/'dist-before.sha.json').read_text())
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
        # Restore the code before asking the existing supervisor to restart a
        # crashed gateway. Never let this failure prevent rollback on TUF.
        subprocess.run(['launchctl', 'kickstart', '-k', 'system/ai.agentshell.gateway'], check=True)
        return
    pid = int(match[1])
    uid = subprocess.check_output(['ps', '-o', 'uid=', '-p', str(pid)], text=True).strip()
    if uid != str(os.getuid()):
        raise RuntimeError('Mac gateway process is not owned by this user')
    os.kill(pid, signal.SIGTERM)  # Existing KeepAlive supervisor starts one replacement.


def prepare():
    receipt = json.loads((ROOT / 'edge-firmware/review-product-e.json').read_text())
    if receipt.get('verdict') != 'PASS':
        raise RuntimeError('Independent E review has not passed')
    archive_receipt = json.loads((ROOT / 'evidence/sagwa-v2/edge-source-candidate-e.json').read_text())
    archive = ROOT / 'evidence/sagwa-v2' / archive_receipt['archive']
    if hashlib.sha256(archive.read_bytes()).hexdigest() != archive_receipt['archive_sha256']:
        raise RuntimeError('Frozen E source archive differs')
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if name.startswith('gateway/src/'):
                if bundle.read(name) != (ROOT / name.removeprefix('gateway/')).read_bytes():
                    raise RuntimeError('Prepared gateway source differs from E: ' + name)
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
                 mac_restore_hashes_equal=True, review_firmware_sha256=receipt['firmware_sha256'])
    state['tuf_backup'] = remote('prepare', state)
    subprocess.run(SSH + ['cat > ' + state['tuf'] + '/dist-candidate.tar.gz'],
                   input=(backup / 'dist-candidate.tar.gz').read_bytes(), check=True)
    subprocess.run(SSH + ['chmod 600 ' + state['tuf'] + '/dist-candidate.tar.gz'], check=True)
    path = backup / 'deployment.json'
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
    print(json.dumps({'operation':operation, 'mac_hashes_equal':hashes(APP / 'dist') == expected,
                      'tuf':result, 'voice_changed':False, 'lenlab_changed':False}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'apply', 'rollback'])
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if args.operation == 'prepare':
        prepare()
    else:
        if not args.backup:
            parser.error('--backup is required')
        install(args.operation, args.backup)
