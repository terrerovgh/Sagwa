"""Update the three existing gateways without restarting etcd or voice services."""
import io,tarfile,subprocess,shutil,os,re,signal,sys,json,plistlib
from pathlib import Path
root=Path(__file__).resolve().parents[1];app=Path.home()/'Library/Application Support/AgentShell'
# Compile and validate before copying files or touching a running service.
manifest=root/'deploy/launchd/ai.agentshell.gateway.plist'
node=os.environ.get('AGENTSHELL_NODE') or (plistlib.loads(manifest.read_bytes())['ProgramArguments'][0] if manifest.exists() else shutil.which('node'))
if not node:raise RuntimeError('Node.js 24 is required before deployment')
subprocess.run([node,str(root/'node_modules/typescript/bin/tsc'),'-p',str(root/'tsconfig.json')],check=True,cwd=root)
subprocess.run([node,'--check',str(root/'dist/main.js')],check=True,cwd=root)
shutil.copytree(root/'dist',app/'dist',dirs_exist_ok=True)
code_only='--code-only' in sys.argv
if not code_only:
 staged=app/'node_modules.next';previous=app/'node_modules.previous'
 if staged.exists():shutil.rmtree(staged)
 shutil.copytree(root/'node_modules',staged,symlinks=True)
 if previous.exists():shutil.rmtree(previous)
 os.rename(app/'node_modules',previous)
 try:os.rename(staged,app/'node_modules')
 except Exception:os.rename(previous,app/'node_modules');raise
 shutil.rmtree(previous)
for file in ['config.json','release-public.pem']:shutil.copyfile(root/'.private/mac-mini'/file,app/'private'/file)
# Install a provider credential before activating the configuration; never print it.
def provider_files(name):
 cfg=json.loads((root/'.private'/name/'config.json').read_text())
 return [provider+'-emoji-key' if provider=='openrouter' else 'vercel-ai-gateway-key' for provider in ['openrouter','vercel'] if cfg.get('emoji',{}).get(provider)]
for file in provider_files('mac-mini'):
 shutil.copyfile(root/'.private'/file,app/'private'/file);(app/'private'/file).chmod(0o600)
(app/'private/config.json').chmod(0o600)
if (root/'.private/mac-mini/codex-broker-token').exists():
 shutil.copyfile(root/'.private/mac-mini/codex-broker-token',app/'private/codex-broker-token');(app/'private/codex-broker-token').chmod(0o600)
system=subprocess.run(['launchctl','print','system/ai.agentshell.gateway'],capture_output=True,text=True)
if system.returncode==0:
    match=re.search(r'\n\s*pid = (\d+)',system.stdout)
    if not match:raise RuntimeError('Gateway daemon has no running PID')
    pid=int(match.group(1));owner=subprocess.check_output(['ps','-o','uid=','-p',str(pid)],text=True).strip()
    if owner!=str(os.getuid()):raise RuntimeError('Gateway daemon is not owned by this account')
    os.kill(pid,signal.SIGTERM) # KeepAlive restarts the existing boot daemon.
else:subprocess.run(['launchctl','kickstart','-k',f'gui/{os.getuid()}/ai.agentshell.gateway'],check=True)
for name,ssh in [('lenlab',['ssh','terrerov@lenlab']),('tuf-infra',['ssh','-J','terrerov@tuf-1','-p','2222','root@172.22.25.125'])]:
    data=io.BytesIO()
    with tarfile.open(fileobj=data,mode='w:gz') as tar:
        tar.add(root/'dist',arcname='app/dist')
        if not code_only:tar.add(root/'node_modules',arcname='app/node_modules')
        for file in ['config.json','release-public.pem']:tar.add(root/'.private'/name/file,arcname='private/'+file)
        for file in provider_files(name):tar.add(root/'.private'/file,arcname='private/'+file)
        if (root/'.private'/name/'codex-broker-token').exists():tar.add(root/'.private'/name/'codex-broker-token',arcname='private/codex-broker-token')
    private_files=' '.join('/opt/agentshell/private/'+file for file in ['config.json','release-public.pem']+provider_files(name))
    if (root/'.private'/name/'codex-broker-token').exists():private_files+=' /opt/agentshell/private/codex-broker-token'
    command='sudo -n tar -xzf - -C /opt/agentshell && sudo -n chown agentshell:agentshell '+private_files+' && sudo -n chmod 600 '+private_files+' && sudo -n systemctl restart '+('agentshell' if name=='lenlab' else 'agentshell-gateway')
    subprocess.run(ssh+[command],input=data.getvalue(),check=True,timeout=600);print(name+' gateway updated',flush=True)
print('Three gateways updated; etcd retained its running state.')
