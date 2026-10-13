"""Mac/TUF-only Sagwa installation; independent review is required before apply. Existing service supervisors are retained.
Run prepare, apply, or rollback BACKUP. Never resets the shared paid-voice ledger.
"""
import argparse,datetime,io,json,os,plistlib,re,shutil,signal,subprocess,tarfile,sys
from pathlib import Path
if sys.version_info<(3,12):raise SystemExit('Use bundled Python3.12 or newer for safe tar recovery')
root=Path(__file__).resolve().parents[1];app=Path.home()/'Library/Application Support/AgentShell'
ssh=['ssh','-J','terrerov@tuf-1','-p','2222','root@172.22.25.125']
node='/Users/terrerov/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'

def restart_mac(label):
    result=subprocess.run(['launchctl','print','system/'+label],capture_output=True,text=True,check=True)
    match=re.search(r'\n\s*pid = (\d+)',result.stdout)
    if not match:raise RuntimeError('service_not_running:'+label)
    pid=int(match.group(1))
    if subprocess.check_output(['ps','-o','uid=','-p',str(pid)],text=True).strip()!=str(os.getuid()):raise RuntimeError('wrong_service_owner')
    os.kill(pid,signal.SIGTERM) # Existing KeepAlive daemon relaunches under the same account.

def archive_mac(backup):
    backup.mkdir(parents=True,mode=0o700);backup.chmod(0o700)
    with tarfile.open(backup/'mac-before.tar.gz','w:gz') as out:
        for rel in ['dist','voice','muse-bridge','private/config.json','private/voice.json']:
            out.add(app/rel,arcname=rel)
    (backup/'mac-before.tar.gz').chmod(0o600)

def bundle():
    data=io.BytesIO()
    with tarfile.open(fileobj=data,mode='w:gz') as out:
        out.add(root/'dist',arcname='app/dist')
        out.add(root/'assets/sagwa/packed',arcname='assets/sagwa-v2')
        out.add(root/'voice',arcname='candidates/sagwa-v2/voice')
    return data.getvalue()

def prepare():
    subprocess.run([node,str(root/'node_modules/typescript/bin/tsc'),'-p',str(root/'tsconfig.json')],check=True)
    subprocess.run([node,'--check',str(root/'dist/main.js')],check=True)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=app/'state/backups'/('sagwa-'+stamp);archive_mac(backup)
    # Validate the recovery archive before any service/config mutation.
    with tarfile.open(backup/'mac-before.tar.gz') as src:
        for member in src.getmembers():
            if member.isfile() and src.extractfile(member).read()!=(app/member.name).read_bytes():raise RuntimeError('backup_mismatch')
    remote='/var/lib/agentshell/backups/sagwa-'+stamp
    subprocess.run(ssh+[f"mkdir -p '{remote}' && chmod 700 '{remote}' && tar -czf '{remote}/before.tar.gz' -C /opt/agentshell app/dist private/config.json private/voice.json && cp /etc/systemd/system/agentshell-voice.service '{remote}/voice.service' && chmod 600 '{remote}'/*"],check=True)
    state={'mac':str(backup),'tuf':remote,'stamp':stamp}
    (backup/'deployment.json').write_text(json.dumps(state,indent=2));(backup/'deployment.json').chmod(0o600)
    print(json.dumps(state));return state

def apply(state):
    backup=Path(state['mac'])
    if not (backup/'mac-before.tar.gz').is_file():raise RuntimeError('missing_backup')
    # Stage immutable runtime/model additions. Previous Python environment remains available.
    shutil.copytree(root/'voice',app/'voice-sagwa',dirs_exist_ok=True)
    if not (app/'venv-sagwa').exists():shutil.copytree(root/'.private/sagwa/voice-venv',app/'venv-sagwa',symlinks=True)
    shutil.copytree(root/'.private/sagwa/models/kokoro',app/'models/sagwa/kokoro',dirs_exist_ok=True)
    shutil.copytree(root/'assets/sagwa/packed',app/'assets/sagwa-v2',dirs_exist_ok=True)
    shutil.copy2(root/'.private/avatar-tools/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1',app/'runtime/ffmpeg-sagwa');(app/'runtime/ffmpeg-sagwa').chmod(0o755)
    cfg=json.loads((app/'private/config.json').read_text());tls=cfg['tls']
    voice=json.loads((app/'private/voice.json').read_text())
    voice.update(port=9450,primary={'url':'https://100.65.98.90:9443/internal/voice/tts/stream','ca_file':tls['ca'],'cert_file':tls['cert'],'key_file':tls['key']},kokoro={'model_dir':str(app/'models/sagwa/kokoro')},api={'key_file':str(app/'private/openrouter-emoji-key'),'ledger_file':str(app/'state/voice-budget.sqlite3'),'monthly_limit_usd':5,'ffmpeg':str(app/'runtime/ffmpeg-sagwa')},gpu_lease={'ssh_host':'terrerov@tuf-1','owner':'agentshell-sagwa-voice','task':'T-20261012-03','state_file':str(app/'state/sagwa-gpu-lease.json')})
    if not (app/'private/openrouter-emoji-key').exists():raise RuntimeError('missing_existing_api_credential')
    (app/'private/voice.json').write_text(json.dumps(voice,indent=2));(app/'private/voice.json').chmod(0o600)
    launcher='import os\nfrom pathlib import Path\nbase=Path(__file__).resolve().parents[1]\npython=str(base/"venv-sagwa/bin/python")\nos.execv(python,[python,str(base/"voice-sagwa/server.py"),"--config",str(base/"private/voice.json")])\n'
    (app/'voice/server.py').write_text(launcher)
    cfg['avatar']={'directory':str(app/'assets/sagwa-v2')};(app/'private/config.json').write_text(json.dumps(cfg,indent=2));(app/'private/config.json').chmod(0o600)
    shutil.copytree(root/'dist',app/'dist',dirs_exist_ok=True)
    shutil.copy2(root/'muse-bridge/server.py',app/'muse-bridge/server.py')
    subprocess.run(ssh+['tar -xzf - -C /opt/agentshell && chown -R 999:988 /opt/agentshell/app/dist /opt/agentshell/assets/sagwa-v2 /opt/agentshell/candidates/sagwa-v2/voice'],input=bundle(),check=True)
    # Remote configs are derived from their current installed values, never copied across hosts.
    remote_script=backup/'apply-tuf.py';remote_script.write_text(TUF_APPLY)
    subprocess.run(ssh+['python3 -'],input=TUF_APPLY.encode(),check=True)
    restart_mac('ai.agentshell.voice');restart_mac('ai.agentshell.gateway');restart_mac('ai.agentshell.muse')
    print('Applied Mac mini and TUF only. Voice/OTA validation is still required.')

def validate_backup(state):
    backup=Path(state['mac']);remote=state['tuf']
    if backup.parent!=app/'state/backups' or not re.fullmatch(r'/var/lib/agentshell/backups/sagwa-\d{8}T\d{6}Z',remote):raise RuntimeError('invalid_backup_path')
    with tarfile.open(backup/'mac-before.tar.gz') as src:
        names=set(src.getnames())
        if not {'private/config.json','private/voice.json','voice/server.py'}.issubset(names):raise RuntimeError('incomplete_backup')
        for item in src.getmembers():
            if item.isfile():src.extractfile(item).read() # Verify gzip integrity before stopping a service.
    subprocess.run(ssh+[f"tar -tzf '{remote}/before.tar.gz' >/dev/null && test -s '{remote}/voice.service'"],check=True)
    return backup,remote

def rollback(state):
    backup,remote=validate_backup(state);warnings=[];stopped=False
    try:subprocess.run(ssh+['systemctl stop agentshell-voice && ! docker inspect agentshell-voice >/dev/null 2>&1'],check=True);stopped=True
    except Exception:warnings.append('TUF voice stop could not be confirmed; GPU fencing retained')
    gpu_state=app/'state/sagwa-gpu-lease.json'
    if stopped and gpu_state.exists():
        try:
            import sys;sys.path.insert(0,str(root/'voice'))
            from gpu_lease import GpuBroker
            cfg=json.loads((app/'private/voice.json').read_text()).get('gpu_lease') or {'ssh_host':'terrerov@tuf-1','owner':'agentshell-sagwa-voice','task':'T-20261012-03','state_file':str(gpu_state)}
            GpuBroker(cfg).handle('unlock',json.loads(gpu_state.read_text())['lease'])
        except Exception:warnings.append('GPU unlock pending; persisted UUID retained')
    try:
        subprocess.run(ssh+[f"tar -xzf '{remote}/before.tar.gz' -C /opt/agentshell && cp '{remote}/voice.service' /etc/systemd/system/agentshell-voice.service && systemctl daemon-reload && systemctl restart agentshell-voice agentshell-gateway"],check=True)
    except Exception:warnings.append('TUF restoration needs retry')
    try:
        with tarfile.open(backup/'mac-before.tar.gz') as src:src.extractall(app,filter='data')
        for label in ['ai.agentshell.voice','ai.agentshell.gateway','ai.agentshell.muse']:restart_mac(label)
    except Exception:warnings.append('Mac restoration needs retry')
    print(json.dumps({'restored':not warnings,'warnings':warnings,'paid_voice_ledger_retained':True}))
    if warnings:raise RuntimeError('rollback_requires_reconciliation')

TUF_APPLY=r"""
import json,subprocess
from pathlib import Path
base=Path('/opt/agentshell');p=base/'private/config.json';cfg=json.loads(p.read_text());cfg['avatar']={'directory':str(base/'assets/sagwa-v2')};p.write_text(json.dumps(cfg,indent=2));p.chmod(0o600)
voice=json.loads((base/'private/voice.json').read_text())
for key in ['api','primary','kokoro']:voice.pop(key,None)
tls=cfg['tls'];voice.update(port=9450,chatterbox={'model_dir':'/models/chatterbox','reference_wav':'/models/reference-ef_dora.wav','gpu_broker':{'url':'https://100.68.191.53:9443/internal/voice/gpu','ca_file':tls['ca'],'cert_file':tls['cert'],'key_file':tls['key'],'state_file':'/voice-state/gpu-lease.json'}},fallback={'url':'https://100.68.191.53:9443/internal/voice/fallback','ca_file':tls['ca'],'cert_file':tls['cert'],'key_file':tls['key']})
p=base/'private/voice.json';p.write_text(json.dumps(voice,indent=2));p.chmod(0o600)
for p in [base/'private/config.json',base/'private/voice.json']:
 import os;os.chown(p,999,988)
Path('/var/lib/agentshell/voice-state').mkdir(exist_ok=True);os.chown('/var/lib/agentshell/voice-state',999,988)
unit='''[Unit]
Description=AgentShell Sagwa LATAM GPU voice
After=docker.service
Requires=docker.service
[Service]
ExecStartPre=-/usr/bin/docker rm -f agentshell-voice
ExecStart=/usr/bin/docker run --rm --name agentshell-voice --network container:tuf-infra-tailnet-1 --user 999:988 --gpus all --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,nosuid,size=512m --env HOME=/tmp --mount type=bind,src=/opt/agentshell/models,dst=/opt/agentshell/models,readonly --mount type=bind,src=/opt/agentshell/models/sagwa,dst=/models,readonly --mount type=bind,src=/opt/agentshell/private,dst=/opt/agentshell/private,readonly --mount type=bind,src=/var/lib/agentshell/voice-state,dst=/voice-state agentshell-sagwa-voice:0.2.0-candidate python /app/server.py --config /opt/agentshell/private/voice.json
ExecStop=/usr/bin/docker stop -t 30 agentshell-voice
Restart=always
RestartSec=10
TimeoutStartSec=0
[Install]
WantedBy=multi-user.target
'''
image_id=subprocess.check_output(['docker','image','inspect','agentshell-sagwa-voice:0.2.0-candidate','--format','{{.Id}}'],text=True).strip()
if not image_id.startswith('sha256:') or len(image_id)!=71:raise RuntimeError('invalid_image_digest')
unit=unit.replace('agentshell-sagwa-voice:0.2.0-candidate',image_id)
Path('/etc/systemd/system/agentshell-voice.service').write_text(unit)
subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','restart','agentshell-voice','agentshell-gateway'],check=True)
"""
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('operation',choices=['prepare','apply','rollback']);parser.add_argument('--backup',type=Path);args=parser.parse_args()
    if args.operation=='prepare':prepare()
    else:
        if not args.backup:parser.error('--backup deployment.json is required')
        state=json.loads(args.backup.read_text())
        if args.operation=='apply':
            validate_backup(state)
            try:apply(state)
            except Exception:
                rollback(state);raise
        else:rollback(state)
