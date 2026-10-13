"""Prepare isolated credentials/config; never copy paid API or SSH credentials."""
import json
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
existing = Path.home() / 'Library/Application Support/AgentShell/private/voice.json'
cfg = json.loads(existing.read_text())
models = Path(cfg['whisper_path']).parent
if Path(cfg['kokoro']['model_dir']) != models / 'sagwa/kokoro':
    raise SystemExit('unsupported_model_layout')
required = ['whisper-base/model.bin', 'sagwa/kokoro/config.json',
            'sagwa/kokoro/kokoro-v1_0.pth', 'sagwa/kokoro/ef_dora.pt']
if any(not (models / name).is_file() for name in required):
    raise SystemExit('models_missing')
private = existing.parent / 'sagwa-docker'
evidence = root / '.private/sagwa/docker-mac'
evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
private.mkdir(parents=True, exist_ok=True, mode=0o700)
token = private / 'token'
if not token.exists():
    token.write_text(secrets.token_urlsafe(48))
token.chmod(0o600)
worker = {'token_file': '/run/sagwa/token', 'port': 9450,
          'whisper_path': '/models/whisper-base', 'piper_path': '/models/unused.onnx',
          'kokoro': {'model_dir': '/models/sagwa/kokoro'}}
(private / 'voice.json').write_text(json.dumps(worker, indent=2) + '\n')
(private / 'voice.json').chmod(0o600)
# A host-only benchmark config contains paths, not the token value.
(evidence / 'benchmark.json').write_text(json.dumps({'port': 9493, 'token_file': str(token)}) + '\n')
(evidence / 'benchmark.json').chmod(0o600)
for path in (models, private):
    if any(ch in str(path) for ch in '\n\r"$'):
        raise SystemExit('unsupported_path')
(evidence / 'compose.env').write_text(
    f'SAGWA_MODELS_DIR="{models}"\nSAGWA_CONTAINER_PRIVATE="{private}"\n'
    f'SAGWA_UID={os.getuid()}\nSAGWA_GID={os.getgid()}\n')
(evidence / 'compose.env').chmod(0o600)
print('Prepared dedicated Sagwa worker; credentials remain private.')
