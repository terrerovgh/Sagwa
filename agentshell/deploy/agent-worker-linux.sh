#!/usr/bin/env bash
set -euo pipefail
for attempt in $(seq 1 30); do
  worker_net_pid=$(docker inspect --format '{{.State.Pid}}' tuf-infra-tailnet-1 2>/dev/null || true)
  if [[ "$worker_net_pid" =~ ^[1-9][0-9]*$ ]]; then
    exec nsenter --net="/proc/$worker_net_pid/ns/net" --setgid="$(id -g agentshell)" --setuid="$(id -u agentshell)" \
      /opt/agentshell/runtime/node/bin/node /opt/agentshell/app/dist/agent-worker.js /opt/agentshell/private/config.json /opt/agentshell/private/codex-broker-token
  fi
  sleep 2
done
exit 1
