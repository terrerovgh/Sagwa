#!/usr/bin/env bash
set -euo pipefail
node=${1:?node id required}
case "$node" in lenlab|tuf-infra) ;; *) exit 2;; esac
getent passwd agentshell >/dev/null || useradd --system --create-home --home-dir /var/lib/agentshell/home --shell /usr/sbin/nologin agentshell
install -d -m 0700 -o agentshell -g agentshell /var/lib/agentshell /var/lib/agentshell/logs /opt/agentshell/private
chown -R agentshell:agentshell /opt/agentshell/private
chmod -R go-rwx /opt/agentshell/private
if getent group docker >/dev/null; then usermod -aG docker agentshell; fi
cat >/etc/systemd/system/agentshell-etcd.service <<UNIT
[Unit]
Description=AgentShell etcd 3.6.15
After=network-online.target docker.service
Wants=network-online.target
[Service]
User=agentshell
Group=agentshell
ExecStart=/opt/agentshell/runtime/etcd --config-file=/opt/agentshell/private/etcd.json
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/agentshell
[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/systemd/system/agentshell.service <<UNIT
[Unit]
Description=AgentShell coordinator executor and object storage
After=network-online.target agentshell-etcd.service
Wants=network-online.target agentshell-etcd.service
[Service]
User=agentshell
Group=agentshell
Environment=PATH=/opt/agentshell/runtime/node/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/var/lib/agentshell/home
WorkingDirectory=/opt/agentshell/app
ExecStart=/opt/agentshell/runtime/node/bin/node /opt/agentshell/app/dist/main.js /opt/agentshell/private/config.json
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/var/lib/agentshell
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable agentshell-etcd agentshell
if [ "$node" = lenlab ]; then systemctl start agentshell-etcd agentshell; fi
