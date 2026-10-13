#!/usr/bin/env python3
"""Use the existing Sagwa-only Mac deploy key; never read or print private key bytes."""
from pathlib import Path
import shlex
import subprocess
import sys

def configure(root):
    root = Path(root).resolve()
    remote = subprocess.check_output(["git", "-C", str(root), "remote", "get-url", "origin"], text=True).strip()
    if remote not in {"https://github.com/terrerovgh/Sagwa.git", "git@github.com:terrerovgh/Sagwa.git"}:
        raise ValueError("El origin no es el repositorio Sagwa autorizado.")
    private = Path.home() / "Library/Application Support/AgentShell/private/development"
    key = private / "github-sagwa-ed25519"
    hosts = private / "github-known-hosts"
    if not key.is_file() or not hosts.is_file():
        raise ValueError("Esta Mac no tiene la llave local Sagwa preparada; no se copian claves entre hosts.")
    config = private / "sagwa-git-ssh.conf"
    # OpenSSH quotes paths itself; shell quoting alone is insufficient for -o paths with spaces.
    config.write_text('Host github.com\n  HostName github.com\n  User git\n  IdentityFile "' + str(key) +
        '"\n  IdentitiesOnly yes\n  BatchMode yes\n  StrictHostKeyChecking yes\n  UserKnownHostsFile "' + str(hosts) + '"\n')
    config.chmod(0o600)
    command = "ssh -F " + shlex.quote(str(config))
    subprocess.run(["git", "-C", str(root), "config", "--local", "core.sshCommand", command], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "set-url", "--push", "origin", "git@github.com:terrerovgh/Sagwa.git"], check=True)
    return command

if __name__ == "__main__":
    try:
        configure(Path(__file__).resolve().parent.parent)
        print("Acceso Git local configurado únicamente para Sagwa; llave privada fuera del repositorio.")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
