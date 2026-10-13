#!/usr/bin/env python3
"""Create an unfocused Sagwa workspace; inspect availability; start one chosen agent."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent.parent
PROFILES = json.loads((ROOT / "config/agents.json").read_text())["profiles"]
STATE = ROOT / ".coord/runtime/herdr.json"

def executable(command, fallbacks=()):
    found = shutil.which(command)
    if found:
        return found
    for path in [*(Path.home() / ".local/bin" / command, Path("/opt/homebrew/bin") / command, Path("/usr/local/bin") / command), *map(lambda p: Path(p).expanduser(), fallbacks)]:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None

def doctor():
    return {"herdr": executable("herdr"), "inside_herdr": os.environ.get("HERDR_ENV") == "1",
        "profiles": {k: {"executable": executable(v["command"], v["fallbacks"]),
                         "authentication": "not_checked", "kind": v["kind"]} for k, v in PROFILES.items()}}

def cli(*arguments):
    command = executable("herdr")
    if not command:
        raise ValueError("Herdr no está instalado.")
    response = subprocess.run([command, *arguments], text=True, capture_output=True, timeout=45)
    if response.returncode:
        raise ValueError(response.stderr.strip() or response.stdout.strip())
    payload = json.loads(response.stdout)
    return payload.get("result", payload)

def identity():
    server = cli("status", "--json")["server"]
    if not server.get("running") or not server.get("endpoint_compatible"):
        raise ValueError("Servidor Herdr no disponible o incompatible.")
    return {"socket": str(Path(server["socket"]).resolve()), "session": server.get("session")}

def project_cwd(candidate):
    if not candidate:
        return False
    path = Path(candidate).resolve()
    if path == ROOT or ROOT in path.parents:
        return True
    try:
        common = subprocess.check_output(["git", "-C", str(path), "rev-parse", "--git-common-dir"], text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
        return (path / common).resolve() == (ROOT / ".git").resolve()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False

def validate(state, target_role=None):
    if state.get("cwd") != str(ROOT) or state.get("scope") != identity():
        raise ValueError("Layout de otro checkout/socket/sesión; no se controla ningún pane.")
    workspace = cli("workspace", "get", state["workspace"])["workspace"]
    if workspace["workspace_id"] != state["workspace"] or workspace.get("label") != "Sagwa":
        raise ValueError("El workspace vivo no coincide con Sagwa.")
    for role, pane_id in state["panes"].items():
        pane = cli("pane", "get", pane_id)["pane"]
        if (pane.get("workspace_id") != state["workspace"] or pane.get("tab_id") != state["tabs"][role]
            or pane.get("terminal_id") != state.get("terminals", {}).get(role)):
            raise ValueError("Pane sustituido o movido; no se inicia ningún agente.")
        if role == target_role and not project_cwd(pane.get("foreground_cwd")):
            raise ValueError("El pane destino no está en Sagwa ni en un worktree del mismo repositorio.")

@contextlib.contextmanager
def layout_lock():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with (STATE.parent / "herdr-setup.lock").open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)

def require_context():
    if os.environ.get("HERDR_ENV") != "1":
        raise ValueError("Ejecute este comando desde una terminal de Herdr. No se modifica HERDR_ENV.")

def save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".herdr-", dir=STATE.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(json.dumps(state, indent=2) + "\n")
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, STATE)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

def setup():
    require_context()
    with layout_lock():
        return _setup()

def _setup():
    if STATE.exists():
        saved = json.loads(STATE.read_text())
        # Verify the recorded dedicated workspace; never select the focused one.
        validate(saved)
        return {"reused": True, **saved}
    inventory = doctor()
    directories = sorted({str(Path(v["executable"]).parent) for v in inventory["profiles"].values() if v["executable"]})
    path = os.pathsep.join([*directories, str(Path.home() / ".local/bin"), os.environ.get("PATH", "/usr/bin:/bin")])
    scope = identity()
    created = cli("workspace", "create", "--cwd", str(ROOT), "--label", "Sagwa", "--env", "PATH=" + path, "--no-focus")
    state = {"schema": 1, "workspace": created["workspace"]["workspace_id"], "cwd": str(ROOT),
             "panes": {"orchestrator": created["root_pane"]["pane_id"]},
             "tabs": {"orchestrator": created["tab"]["tab_id"]}, "scope": scope,
             "terminals": {"orchestrator": created["root_pane"]["terminal_id"]}}
    # Persist each returned ID; interrupted setup cannot silently duplicate a workspace.
    save(state)
    cli("tab", "rename", state["tabs"]["orchestrator"], "Orquestación")
    return complete_setup(state, path)

def complete_setup(state, path=None):
    validate(state)
    for kind in PROFILES:
        if kind in state["panes"]:
            continue
        args = ["tab", "create", "--workspace", state["workspace"], "--cwd", str(ROOT), "--label", kind.upper(), "--no-focus"]
        if path:
            args += ["--env", "PATH=" + path]
        tab = cli(*args)
        state["panes"][kind] = tab["root_pane"]["pane_id"]
        state["tabs"][kind] = tab["tab"]["tab_id"]
        state["terminals"][kind] = tab["root_pane"]["terminal_id"]
        save(state)
    return state

def start(kind, role):
    require_context()
    with layout_lock():
        return _start(kind, role)

def _start(kind, role):
    inventory = doctor()
    if not inventory["profiles"][kind]["executable"]:
        raise ValueError(f"{kind} no está instalado; complete su instalación/login oficial y vuelva a ejecutar doctor.")
    if not STATE.exists():
        raise ValueError("Ejecute primero setup dentro de Herdr.")
    state = json.loads(STATE.read_text())
    target_role = "orchestrator" if role == "orchestrator" else kind
    validate(state, target_role=target_role)
    pane = state["panes"][target_role]
    if os.environ.get("HERDR_PANE_ID") == pane:
        raise ValueError("El lanzador está ocupando el pane destino. Ejecute start desde otra pestaña de Herdr; para orquestador use la pestaña Codex vacía.")
    name = f"sagwa-{kind}" + ("-orch" if role == "orchestrator" else "") + "-" + uuid.uuid4().hex[:6]
    # Herdr validates that the pane is at a shell; never answers approval dialogs.
    result = cli("agent", "start", name, "--kind", kind, "--pane", pane)
    return {"started": result, "name": name, "next":
        f'herdr agent prompt {name} "Lee {ROOT}/AGENTS.md, {ROOT}/docs/STATUS.md y {ROOT}/coord/README.md. Regístrate como {name}, familia {kind}, rol {role}. Consulta bitácora, inbox y tablero. ' +
        ("Reclama la concesión de orquestador si está libre y continúa la hoja de ruta con criterios de aceptación. " if role == "orchestrator" else "Espera una tarea asignada antes de editar. ") +
        'Registra planes y resultados; preserva 0.2.0 y no despliegues candidatos rechazados." --wait --timeout 60000'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("setup")
    commands.add_parser("resume-setup")
    p = commands.add_parser("start")
    p.add_argument("kind", choices=list(PROFILES))
    p.add_argument("--role", choices=["orchestrator", "worker", "reviewer"], default="worker")
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "setup":
            result = setup()
        elif args.command == "resume-setup":
            require_context()
            with layout_lock():
                state = json.loads(STATE.read_text())
                result = complete_setup(state)
        else:
            result = start(args.kind, args.role)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired, KeyError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
