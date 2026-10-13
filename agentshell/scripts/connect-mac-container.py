"""Promote/roll back only the supervised Mac voice router, never gateway or TUF."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import urllib.request

root = Path(__file__).resolve().parents[1]
home = Path.home() / 'Library/Application Support/AgentShell'
config = home / 'private/voice.json'
runtime_python = home / 'venv-sagwa/bin/python'
targets = [home / 'voice-sagwa/server.py', home / 'voice-sagwa/tts_router.py', config]
parser = argparse.ArgumentParser()
parser.add_argument('--rollback', type=Path)
parser.add_argument('--review', type=Path)
args = parser.parse_args()
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def health(port):
    with opener.open(f'http://127.0.0.1:{port}/health', timeout=2) as response:
        body = response.read(8193)
        if len(body) > 8192:
            raise RuntimeError('invalid_health')
        return json.loads(body)


def listener():
    result = subprocess.run(['lsof', '-t', '-iTCP:9450', '-sTCP:LISTEN'],
                            capture_output=True, text=True)
    pids = result.stdout.split()
    if not pids:
        return None
    if len(pids) != 1:
        raise RuntimeError('ambiguous_voice_pid')
    pid = int(pids[0])
    process = subprocess.check_output(['ps', '-ww', '-p', str(pid), '-o', 'uid=,command='], text=True)
    fields = process.strip().split(maxsplit=1)
    expected = f'{runtime_python} {targets[0]} --config {config}'
    if len(fields) != 2 or fields[0] != str(os.getuid()) or fields[1] != expected:
        raise RuntimeError('unexpected_voice_process')
    return pid


def restart():
    pid = listener()
    if pid is not None:
        os.kill(pid, signal.SIGTERM)  # KeepAlive starts the same user-scoped worker.
        for _ in range(40):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(.5)
        else:
            raise RuntimeError('old_voice_still_running')
    # If a bad candidate died before binding, restored files are enough for
    # KeepAlive. Wait for its fresh, verified listener instead of aborting rollback.
    desired = json.loads(config.read_text())
    for _ in range(40):
        time.sleep(.5)
        try:
            new_pid = listener()
            if new_pid is None or new_pid == pid:
                continue
            state = health(9450)
            engines = state.get('tts_engines', [])
            if state.get('kokoro_warm') is not True or not isinstance(engines, list):
                continue
            if desired.get('container'):
                if 'kokoro-docker-mac' not in engines:
                    continue
                if desired.get('container_first') and engines[0] != 'kokoro-docker-mac':
                    continue
                if not desired.get('container_first') and desired.get('primary') and engines[0] != 'chatterbox-tuf':
                    continue
            return {'pid': new_pid, **state}
        except Exception:
            pass
    raise RuntimeError('voice_restart_failed')


def atomic_copy(source, target):
    temporary = target.with_name(target.name + '.docker-next')
    shutil.copy2(source, temporary)
    os.replace(temporary, target)


def rollback(directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    if not isinstance(manifest.get('files'), list) or len(manifest['files']) != len(targets):
        raise RuntimeError('invalid_backup_manifest')
    for entry, target in zip(manifest['files'], targets):
        if entry['path'] != str(target):
            raise RuntimeError('invalid_backup_target')
        source = directory / entry['backup']
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry['sha256']:
            raise RuntimeError('invalid_backup_hash')
    for entry, target in zip(manifest['files'], targets):
        atomic_copy(directory / entry['backup'], target)
    return restart()


if args.rollback:
    print(json.dumps({'rollback': str(args.rollback), 'health': rollback(args.rollback)}))
    raise SystemExit(0)

# A persisted independent PASS for this exact promotion is required.
if not args.review:
    raise SystemExit('review_receipt_required')
receipt = json.loads(args.review.read_text())
if receipt.get('docker_promotion') != 'PASS':
    raise SystemExit('independent_review_not_passed')
for name in ('voice/server.py', 'voice/tts_router.py', 'voice/container_entry.py',
             'voice/compose.mac.yml', 'voice/Dockerfile.mac',
             'voice/requirements-mac.lock.txt', 'scripts/prepare-mac-container.py',
             'scripts/connect-mac-container.py'):
    expected = receipt.get('source_sha256', {}).get(name)
    if expected != hashlib.sha256((root / name).read_bytes()).hexdigest():
        raise SystemExit('review_source_mismatch')
state = health(9493)
if state.get('kokoro_warm') is not True or state.get('models_present') is not True:
    raise SystemExit('container_not_ready')
token = (home / 'private/sagwa-docker/token').read_text().strip()
request = urllib.request.Request('http://127.0.0.1:9493/tts/stream',
    json.dumps({'text': 'Hola.', 'local_only': True}).encode(),
    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
with opener.open(request, timeout=5) as response:
    pcm = response.read(4096)
    if (response.status != 200 or response.headers.get('X-Sample-Rate') != '16000'
        or response.headers.get('X-Channels') != '1' or not pcm or len(pcm) % 2):
        raise SystemExit('container_pcm_probe_failed')
# Validate the actual launcher-exec runtime before touching any installed file.
if listener() is None:
    raise SystemExit('voice_listener_missing')
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup = home / 'state/backups' / ('sagwa-docker-' + stamp)
backup.mkdir(parents=True, mode=0o700)
files = []
for index, target in enumerate(targets):
    name = str(index) + '-' + target.name
    shutil.copy2(target, backup / name)
    files.append({'path': str(target), 'backup': name,
                  'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
(backup / 'manifest.json').write_text(json.dumps({'files': files}, indent=2) + '\n')
(backup / 'manifest.json').chmod(0o600)
try:
    for name in ('server.py', 'tts_router.py'):
        atomic_copy(root / 'voice' / name, home / 'voice-sagwa' / name)
    cfg = json.loads(config.read_text())
    cfg['container'] = {'url': 'http://127.0.0.1:9493/tts/stream',
                        'token_file': str(home / 'private/sagwa-docker/token')}
    cfg['container_first'] = False  # Preserve the user's Chatterbox primary choice.
    temporary = config.with_suffix('.docker-next')
    temporary.write_text(json.dumps(cfg, indent=2) + '\n')
    temporary.chmod(0o600)
    os.replace(temporary, config)
    restarted = restart()
except Exception:
    rollback(backup)
    raise
print(json.dumps({'backup': str(backup), 'health': restarted}))
