#!/usr/bin/env bash
set -euo pipefail
node=${1:?node required}
base=/opt/agentshell
if [ "$node" = tuf-infra ]; then
 dockerfile=$base/app/voice/Dockerfile
 docker build -t agentshell-voice:0.1.0 -f "$dockerfile" "$base/app/voice" > /var/log/agentshell-voice-build.log 2>&1
 docker run --rm --user 0 --network container:tuf-infra-tailnet-1 --mount type=bind,src=$base/models,dst=/models agentshell-voice:0.1.0 python /app/download_models.py /models > /var/log/agentshell-model-download.log 2>&1
 cat >/etc/systemd/system/agentshell-voice.service <<UNIT
[Unit]
Description=AgentShell local voice
After=docker.service
Requires=docker.service
[Service]
ExecStartPre=-/usr/bin/docker rm -f agentshell-voice
ExecStart=/usr/bin/docker run --rm --name agentshell-voice --network container:tuf-infra-tailnet-1 --user $(id -u agentshell):$(id -g agentshell) --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --mount type=bind,src=/opt/agentshell/models,dst=/opt/agentshell/models,readonly --mount type=bind,src=/opt/agentshell/private,dst=/opt/agentshell/private,readonly agentshell-voice:0.1.0 python /app/server.py --config /opt/agentshell/private/voice.json
ExecStop=/usr/bin/docker stop -t 10 agentshell-voice
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
else
 python3 -m venv "$base/venv"
 "$base/venv/bin/python" -m pip install -r "$base/app/voice/requirements.txt" > /tmp/agentshell-voice-pip.log 2>&1
 "$base/venv/bin/python" "$base/app/voice/download_models.py" "$base/models" > /tmp/agentshell-model-download.log 2>&1
 cat >/etc/systemd/system/agentshell-voice.service <<UNIT
[Unit]
Description=AgentShell offline Spanish voice
After=network-online.target
[Service]
User=agentshell
Group=agentshell
ExecStart=/opt/agentshell/venv/bin/python /opt/agentshell/app/voice/server.py --config /opt/agentshell/private/voice.json
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/agentshell
[Install]
WantedBy=multi-user.target
UNIT
fi
chown -R agentshell:agentshell "$base/models"
chmod -R go-rwx "$base/models"
systemctl daemon-reload
systemctl enable --now agentshell-voice
systemctl is-active agentshell-voice
