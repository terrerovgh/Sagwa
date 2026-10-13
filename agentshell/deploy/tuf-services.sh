#!/usr/bin/env bash
# Docker provides the existing tuf-infra Tailscale namespace; systemd supervises it.
set -euo pipefail
image='python:3.13-slim@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c'
agent_uid=$(id -u agentshell)
agent_gid=$(id -g agentshell)
for name in etcd gateway; do
 case "$name" in
 etcd) command='/opt/agentshell/runtime/etcd --config-file=/opt/agentshell/private/etcd.json';;
 gateway) command='/opt/agentshell/runtime/node/bin/node /opt/agentshell/app/dist/main.js /opt/agentshell/private/config.json';;
 esac
 cat >"/etc/systemd/system/agentshell-${name}.service" <<UNIT
[Unit]
Description=AgentShell ${name} in existing tuf-infra network
Requires=docker.service
After=docker.service network-online.target
[Service]
ExecStartPre=-/usr/bin/docker rm -f agentshell-${name}
ExecStart=/usr/bin/docker run --rm --name agentshell-${name} --network container:tuf-infra-tailnet-1 --user ${agent_uid}:${agent_gid} --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --env HOME=/var/lib/agentshell/home --env PATH=/opt/agentshell/runtime/node/bin:/usr/local/bin:/usr/bin:/bin --mount type=bind,src=/opt/agentshell,dst=/opt/agentshell,readonly --mount type=bind,src=/var/lib/agentshell,dst=/var/lib/agentshell ${image} ${command}
ExecStop=/usr/bin/docker stop -t 10 agentshell-${name}
Restart=always
RestartSec=10
TimeoutStartSec=0
[Install]
WantedBy=multi-user.target
UNIT
done
systemctl disable --now agentshell.service
systemctl daemon-reload
systemctl enable --now agentshell-etcd agentshell-gateway
