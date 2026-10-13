"""Install supervised services outside macOS protected Documents, with boot manifests."""
import os,pathlib,plistlib,shutil,subprocess
source=pathlib.Path(__file__).resolve().parents[1]
root=pathlib.Path.home()/'Library/Application Support/AgentShell';root.mkdir(exist_ok=True,parents=True,mode=0o700)
for folder in ['dist','node_modules','voice']:
 shutil.copytree(source/folder,root/folder,dirs_exist_ok=True,symlinks=True)
shutil.copy2(source/'package.json',root/'package.json')
for origin,destination in [(source/'.private/mac-mini',root/'private'),(source/'.private/models',root/'models'),(source/'.private/runtime/darwin-arm64',root/'runtime')]: shutil.copytree(origin,destination,dirs_exist_ok=True)
python='/Users/terrerov/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3'
if not (root/'venv/bin/python').exists():
 subprocess.run([python,'-m','venv',str(root/'venv')],check=True)
 subprocess.run([str(root/'venv/bin/python'),'-m','pip','install','-r',str(root/'voice/requirements.txt')],check=True,stdout=subprocess.DEVNULL)
state=root/'state';(state/'logs').mkdir(parents=True,exist_ok=True,mode=0o700)
node='/Users/terrerov/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
programs={'etcd':[str(root/'runtime/etcd'),'--config-file='+str(root/'private/etcd.json')],'gateway':[node,str(root/'dist/main.js'),str(root/'private/config.json')],'voice':[str(root/'venv/bin/python'),str(root/'voice/server.py'),'--config',str(root/'private/voice.json')]}
folder=pathlib.Path.home()/'Library/LaunchAgents';folder.mkdir(parents=True,exist_ok=True)
boot=source/'deploy/launchd';boot.mkdir(exist_ok=True,parents=True)
for name,argv in programs.items():
 label='ai.agentshell.'+name
 data={'Label':label,'ProgramArguments':argv,'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'WorkingDirectory':str(root),'EnvironmentVariables':{'PATH':str(pathlib.Path(node).parent)+':/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin','HOME':str(pathlib.Path.home())},'StandardOutPath':str(state/'logs'/ (name+'.out.log')),'StandardErrorPath':str(state/'logs'/(name+'.err.log'))}
 p=folder/(label+'.plist');p.write_bytes(plistlib.dumps(data));subprocess.run(['launchctl','bootout','gui/'+str(os.getuid())+'/'+label],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(p)],check=True)
 data['UserName']=pathlib.Path.home().name;(boot/(label+'.plist')).write_bytes(plistlib.dumps(data))
print('Services installed outside Documents and supervised by launchd.')
