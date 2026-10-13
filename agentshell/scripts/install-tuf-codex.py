"""Install the matching, hash-verified Codex worker in the existing tuf-infra.
Authentication remains private and outside the agent's worktree permissions.
"""
import io,tarfile,subprocess,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[1];app=Path.home()/'Library/Application Support/AgentShell'
archive=root/'.private/runtime/codex-linux-0.162.0-alpha.17.2.tar.gz'
if hashlib.sha256(archive.read_bytes()).hexdigest()!='e537d5467761567f355f515187a6258c0e4c9d4039fbd23b7cff8c4048f2cdd1':raise SystemExit('Codex download hash mismatch')
with tarfile.open(archive) as files:
 binary=next(m for m in files.getmembers() if m.isfile());content=files.extractfile(binary).read()
profile=(app/'codex-home/.codex/config.toml').read_text().replace('/Users/terrerov/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin','/opt/agentshell/runtime/node/bin')
# The Linux sandbox re-executes Codex; /opt is outside :minimal. Permit the
# verified executable itself, not the application, configuration or credentials.
profile=profile.replace('[permissions.agentshell.filesystem.\":workspace_roots\"]','"/opt/agentshell/runtime/codex" = "read"\n\n[permissions.agentshell.filesystem.\":workspace_roots\"]')
data=io.BytesIO()
with tarfile.open(fileobj=data,mode='w:gz') as tar:
 for name,value,mode in [('runtime/codex',content,0o755),('worker-profile.toml',profile.encode(),0o600),('worker-auth.json',(app/'codex-home/.codex/auth.json').read_bytes(),0o600)]:
  info=tarfile.TarInfo(name);info.size=len(value);info.mode=mode;tar.addfile(info,io.BytesIO(value))
command='umask 077; tar -xzf - -C /opt/agentshell; install -d -o agentshell -g agentshell -m 700 /var/lib/agentshell/codex-home/.codex; install -o agentshell -g agentshell -m 600 /opt/agentshell/worker-profile.toml /var/lib/agentshell/codex-home/.codex/config.toml; if [ ! -f /var/lib/agentshell/codex-home/.codex/auth.json ]; then install -o agentshell -g agentshell -m 600 /opt/agentshell/worker-auth.json /var/lib/agentshell/codex-home/.codex/auth.json; fi; rm /opt/agentshell/worker-auth.json /opt/agentshell/worker-profile.toml; /opt/agentshell/runtime/codex --version'
subprocess.run(['ssh','-o','BatchMode=yes','-J','terrerov@tuf-1','-p','2222','root@172.22.25.125',command],input=data.getvalue(),check=True,timeout=120)
print('TUF Codex installed with private host authentication and isolated filesystem permissions.')
