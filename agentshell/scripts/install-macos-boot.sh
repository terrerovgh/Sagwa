#!/bin/bash
# Run once with sudo on the Mac mini to make startup independent of user login.
set -euo pipefail
base=$(cd "$(dirname "$0")/.." && pwd)
user=${SUDO_USER:?Run with sudo from your normal account}
uid=$(id -u "$user")
for file in "$base"/deploy/launchd/ai.agentshell.*.plist; do
 label=$(basename "$file" .plist)
 launchctl bootout "gui/$uid/$label" 2>/dev/null || true
 install -m 0644 -o root -g wheel "$file" "/Library/LaunchDaemons/$label.plist"
 launchctl bootout "system/$label" 2>/dev/null || true
 launchctl bootstrap system "/Library/LaunchDaemons/$label.plist"
done
