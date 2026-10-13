"""Install the full local catalog, multilingual model and offline sprite cache.
Private credentials stay on the hosts, outside source and firmware.
"""
import json,os,re,shutil,signal,subprocess,tarfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];app=Path.home()/'Library/Application Support/AgentShell'
items=[(root/'assets/noto/catalog.json','app/noto/catalog.json'),(root/'.private/models/emoji-encoder','app/noto/model'),(root/'.private/emoji-index','app/noto/index'),(root/'.private/noto-cache','state/noto-cache'),(root/'voice','app/voice')]
for name in ['mac-mini','lenlab','tuf-infra']:
 p=root/'.private'/name/'config.json';cfg=json.loads(p.read_text());base=str(app) if name=='mac-mini' else '/opt/agentshell/app'
 remote={k:v for k,v in cfg.get('emoji',{}).items() if k in ['openrouter','vercel']}
 cfg['emoji']={'catalog':base+'/noto/catalog.json','model':base+'/noto/model','index':base+'/noto/index','cache':cfg['state_dir']+'/noto-cache',**remote}
 p.write_text(json.dumps(cfg,indent=2)+'\n');p.chmod(0o600)
for source,target in items:
 dest=app/target.removeprefix('app/') if target.startswith('app/') else app/target
 dest.parent.mkdir(parents=True,exist_ok=True)
 if source.is_dir():shutil.copytree(source,dest,dirs_exist_ok=True)
 else:shutil.copy2(source,dest)
# Restart only our own existing voice daemon.
out=subprocess.check_output(['launchctl','print','system/ai.agentshell.voice'],text=True)
pid=int(re.search(r'\n\s*pid = (\d+)',out)[1]);uid=subprocess.check_output(['ps','-o','uid=','-p',str(pid)],text=True).strip()
if uid!=str(os.getuid()):raise RuntimeError('Unexpected voice daemon owner')
os.kill(pid,signal.SIGTERM);print('Mac mini catalog, model and voice installed',flush=True)
archive=root/'.private/emoji-runtime.tgz'
with tarfile.open(archive,'w:gz',compresslevel=1) as tar:
 for source,target in items:tar.add(source,arcname=target)
print('Private runtime archive prepared',flush=True)
for name,ssh in [('lenlab',['ssh','terrerov@lenlab']),('tuf-infra',['ssh','-J','terrerov@tuf-1','-p','2222','root@172.22.25.125'])]:
 command='sudo -n mkdir -p /opt/agentshell/emoji-stage && sudo -n tar -xzf - -C /opt/agentshell/emoji-stage && sudo -n cp -a /opt/agentshell/emoji-stage/app/. /opt/agentshell/app/ && sudo -n cp -a /opt/agentshell/emoji-stage/state/noto-cache /var/lib/agentshell/ && sudo -n chown -R agentshell:agentshell /opt/agentshell/app/noto /var/lib/agentshell/noto-cache && sudo -n rm -rf /opt/agentshell/emoji-stage'
 with archive.open('rb') as stream:subprocess.run(ssh+[command],stdin=stream,check=True,timeout=600)
 if name=='tuf-infra':subprocess.run(ssh+['docker build -t agentshell-voice:0.1.0 /opt/agentshell/app/voice >/var/log/agentshell-voice-build.log 2>&1'],check=True,timeout=300)
 subprocess.run(ssh+['sudo -n systemctl restart agentshell-voice'],check=True,timeout=30)
 print(name+' catalog, model and voice installed',flush=True)
archive.unlink()
