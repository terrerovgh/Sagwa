"""Install native macOS Muse transport bridge with its existing private pairing."""
import json,os,plistlib,shutil,subprocess
from pathlib import Path
source=Path(__file__).resolve().parents[1]
root=Path.home()/'Library/Application Support/AgentShell'
shutil.copytree(source/'muse-bridge',root/'muse-bridge',dirs_exist_ok=True)
path=root/'private/muse.json'
config=json.loads(path.read_text()) if path.exists() else {'state_dir':str(root/'muse-host-state'),'token_file':str(root/'private/muse-token')}
path.write_text(json.dumps(config,indent=2)+'\n');path.chmod(0o600)
label='ai.agentshell.muse'
data={'Label':label,'ProgramArguments':[str(root/'venv/bin/python'),str(root/'muse-bridge/server.py'),'--config',str(path)],'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'WorkingDirectory':str(root),'EnvironmentVariables':{'PATH':'/usr/bin:/bin','HOME':str(Path.home())},'StandardOutPath':str(root/'state/logs/muse.out.log'),'StandardErrorPath':str(root/'state/logs/muse.err.log')}
p=Path.home()/'Library/LaunchAgents'/ (label+'.plist');p.write_bytes(plistlib.dumps(data))
subprocess.run(['launchctl','bootout','gui/'+str(os.getuid())+'/'+label],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(p)],check=True)
data['UserName']=Path.home().name
(source/'deploy/launchd'/(label+'.plist')).write_bytes(plistlib.dumps(data))
print('Muse macOS bridge supervised by launchd; no shell tool is registered.')
