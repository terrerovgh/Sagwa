"""Install local workers; gateways keep their existing boot services and PKI."""
import io,os,json,plistlib,shutil,subprocess,tarfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];app=Path.home()/'Library/Application Support/AgentShell'
label='ai.agentshell.codex-worker';node=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
p=Path.home()/'Library/LaunchAgents'/(label+'.plist')
unit={'Label':label,'ProgramArguments':[str(node),str(app/'dist/agent-worker.js'),str(app/'private/config.json'),str(app/'private/codex-broker-token')],'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'WorkingDirectory':str(app),'EnvironmentVariables':{'HOME':str(Path.home()),'PATH':str(node.parent)+':/usr/bin:/bin'},'StandardOutPath':str(app/'state/logs/codex-worker.out.log'),'StandardErrorPath':str(app/'state/logs/codex-worker.err.log')}
p.write_bytes(plistlib.dumps(unit));p.chmod(0o600)
subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/'+label],capture_output=True)
subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(p)],check=True)
worker_unit='''[Unit]
Description=AgentShell local Codex worker
Requires=docker.service
After=docker.service network-online.target
[Service]
ExecStart=/opt/agentshell/runtime/agent-worker-linux.sh
Environment=HOME=/var/lib/agentshell/home
Environment=PATH=/opt/agentshell/runtime/node/bin:/usr/local/bin:/usr/bin:/bin
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/agentshell
PrivateTmp=true
UMask=0077
[Install]
WantedBy=multi-user.target
'''
data=io.BytesIO()
with tarfile.open(fileobj=data,mode='w:gz') as tar:
 tar.add(root/'deploy/agent-worker-linux.sh',arcname='runtime/agent-worker-linux.sh')
 info=tarfile.TarInfo('agentshell-codex-worker.service');raw=worker_unit.encode();info.size=len(raw);info.mode=0o600;tar.addfile(info,io.BytesIO(raw))
command='tar -xzf - -C /opt/agentshell && chmod 755 /opt/agentshell/runtime/agent-worker-linux.sh && apt-get install -y bubblewrap=0.9.0-1ubuntu0.3 >/dev/null && install -m 644 /opt/agentshell/agentshell-codex-worker.service /etc/systemd/system/agentshell-codex-worker.service && systemctl daemon-reload && systemctl enable --now agentshell-codex-worker && systemctl restart agentshell-codex-worker'
subprocess.run(['ssh','-o','BatchMode=yes','-J','terrerov@tuf-1','-p','2222','root@172.22.25.125',command],input=data.getvalue(),check=True,timeout=180)
print('Mac mini GUI worker and native TUF worker installed; Codex permissions retained.')
