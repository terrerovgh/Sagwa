"""Configure the installed ChatGPT-authenticated Codex in a separate host profile."""
import json,shutil
from pathlib import Path
source=Path(__file__).resolve().parents[1];private=source/'.private'
root=Path.home()/'Library/Application Support/AgentShell'
home=root/'codex-home';config_dir=home/'.codex';config_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
auth=Path.home()/'.codex/auth.json'
if not auth.exists():raise SystemExit('Installed Codex authentication missing')
shutil.copyfile(auth,config_dir/'auth.json');(config_dir/'auth.json').chmod(0o600)
binary='/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'
node='/Users/terrerov/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin'
config_dir.joinpath('config.toml').write_text('''cli_auth_credentials_store = "file"
approval_policy = "on-request"
default_permissions = "agentshell"
web_search = "disabled"
[permissions.agentshell]
extends = ":workspace"
[permissions.agentshell.filesystem]
":root" = "deny"
":minimal" = "read"
":tmpdir" = "deny"
":slash_tmp" = "deny"
'''+json.dumps(node)+' = "read"\n'+'''
[permissions.agentshell.filesystem.":workspace_roots"]
"." = "write"
"**/.env" = "deny"
"**/.env.*" = "deny"
"**/*.pem" = "deny"
"**/*.key" = "deny"
[permissions.agentshell.network]
enabled = false
''')
config_dir.joinpath('config.toml').chmod(0o600)
for name in ['mac-mini','tuf-infra','lenlab']:
 file=private/name/'config.json';c=json.loads(file.read_text())
 # A configured native worker has host-specific paths and a private proxy token.
 # Re-running this bootstrap must not replace it with the Mac-only broker.
 if c.get('agents',{}).get('codex',{}).get('enabled'):continue
 c['agents']['codex']={'enabled':True,'url':'https://100.68.191.53:9443/internal/agents/codex',
                       'broker':name=='mac-mini','command':binary,'args':[],
                       'agent_home':str(home),'permission_profile':'agentshell'}
 file.write_text(json.dumps(c,indent=2)+'\n');file.chmod(0o600)
print('Codex configured: isolated home, worktree filesystem profile, no command network.')
