"""Run on lenlab as its Hermes owner after copying app/config updates."""
import json, os, shutil, subprocess
from pathlib import Path
import yaml
from dotenv import dotenv_values

home=Path.home(); source=home/'.hermes'; state=home/'.local/state/agentshell/hermes'
state.mkdir(parents=True,exist_ok=True,mode=0o700)
current=yaml.safe_load((source/'config.yaml').read_text())
route=current['platforms']['api_server']['extra']['model_routes']['hermes']
if route.get('provider')!='openrouter': raise RuntimeError('Existing approved OpenRouter route missing')
allowed={k:route[k] for k in ['model','provider','base_url','api_key'] if k in route}
secrets=dotenv_values(source/'.env')
# The dedicated profile holds only the approved provider secret.
if not secrets.get('OPENROUTER_API_KEY') and not allowed.get('api_key'):
 raise RuntimeError('Existing OpenRouter authentication missing')
(state/'.env').write_text('OPENROUTER_API_KEY='+json.dumps(secrets.get('OPENROUTER_API_KEY',''))+'\n')
(state/'config.yaml').write_text(yaml.safe_dump({'model':{'default':route['model'],'provider':'openrouter'},'agent':{'max_iterations':12},'auxiliary':{'title_generation':{'enabled':False}},'platforms':{'api_server':{'enabled':True}}}))
for name in ['tools-token','hermes-token']:
 shutil.copyfile('/tmp/agentshell-private-update/'+name,state/name)
shutil.copyfile('/tmp/agentshell-private-update/tls/ca.pem',state/'ca.pem')
config={'hermes_path':str(source/'hermes-agent'),'approved_route':allowed,
        'state_dir':str(state),'port':9453,'ca_file':str(state/'ca.pem'),
        'tools_token_file':str(state/'tools-token'),'api_token_file':str(state/'hermes-token'),
        'mcp_url':'https://127.0.0.1:9443/mcp'}
(state/'bridge.json').write_text(json.dumps(config,indent=2)+'\n')
for p in state.iterdir():
 if p.is_file(): p.chmod(0o600)
shutil.copytree('/tmp/agentshell-hermes-bridge',state/'app',dirs_exist_ok=True)
unit=f'''[Unit]
Description=AgentShell restricted Hermes API (existing approved OpenRouter route)
After=network-online.target agentshell.service
[Service]
User={home.name}
WorkingDirectory={state}
Environment=HERMES_HOME={state}
ExecStart={source}/hermes-agent/venv/bin/python {state}/app/server.py --config {state}/bridge.json
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths={state}
[Install]
WantedBy=multi-user.target
'''
path=Path('/tmp/agentshell-hermes.service');path.write_text(unit)
subprocess.run(['sudo','install','-m','644',str(path),'/etc/systemd/system/agentshell-hermes.service'],check=True)
subprocess.run(['sudo','systemctl','daemon-reload'],check=True)
subprocess.run(['sudo','systemctl','enable','--now','agentshell-hermes'],check=True)
print('Dedicated Hermes API installed; existing Hermes gateway unchanged.')
