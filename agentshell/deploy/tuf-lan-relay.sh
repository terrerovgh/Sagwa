#!/usr/bin/env bash
# WSL host socket forwards only the new gateway port into the existing tailnet namespace.
set -euo pipefail
install -d /opt/agentshell/scripts
cat >/opt/agentshell/scripts/lan-relay.py <<'PY'
import json,os,subprocess
info=json.loads(subprocess.check_output(['docker','inspect','tuf-infra-tailnet-1']))[0]
address=info['NetworkSettings']['Networks']['tuf-frontend']['IPAddress']
os.execv('/usr/lib/systemd/systemd-socket-proxyd',['systemd-socket-proxyd',address+':9443'])
PY
cat >/etc/systemd/system/agentshell-lan.socket <<'UNIT'
[Unit]
Description=AgentShell WSL gateway LAN socket
[Socket]
ListenStream=9443
NoDelay=true
[Install]
WantedBy=sockets.target
UNIT
cat >/etc/systemd/system/agentshell-lan.service <<'UNIT'
[Unit]
Description=AgentShell relay into existing Tailscale container network
Requires=docker.service
After=docker.service
[Service]
ExecStart=/usr/bin/python3 /opt/agentshell/scripts/lan-relay.py
NoNewPrivileges=true
ProtectSystem=strict
UNIT
systemctl daemon-reload
systemctl enable --now agentshell-lan.socket
