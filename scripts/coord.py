#!/usr/bin/env python3
"""Shared, advisory development board. Python 3.9+, macOS/Linux, no services."""
import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

IDENT = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")
STATES = {"backlog", "planned", "in_progress", "review", "blocked", "done", "cancelled"}

def identifier(value):
    if not IDENT.fullmatch(value):
        raise ValueError("Identificador inválido; use letras, números, punto, guion o guion bajo.")
    return value

def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def project_root():
    # All worktrees on this host coordinate through the primary checkout.
    here = Path(__file__).resolve().parent.parent
    try:
        common = subprocess.check_output(["git", "-C", str(here), "rev-parse", "--git-common-dir"], text=True, stderr=subprocess.DEVNULL).strip()
        common = (here / common).resolve()
        if common.name == ".git":
            return common.parent
    except (OSError, subprocess.CalledProcessError):
        pass
    return here

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

class Board:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = self.root / "coord/board.json"
        self.runtime = self.root / ".coord/runtime"

    @contextlib.contextmanager
    def transaction(self):
        self.runtime.mkdir(parents=True, exist_ok=True)
        with (self.runtime / "board.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = json.loads(self.path.read_text()) if self.path.exists() else {
                "schema": 1, "max_workers": 3, "agents": {}, "tasks": {}}
            try:
                yield data
                write_json(self.path, data)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def lease(self):
        path = self.runtime / "orchestrator.json"
        return json.loads(path.read_text()) if path.exists() else None

    def require_orchestrator(self, actor):
        lease = self.lease()
        if not lease or lease["agent"] != actor or lease["expires_at_epoch"] <= time.time():
            raise ValueError("Se requiere la concesión vigente de orquestador.")

    def event(self, actor, kind, note, task=None, extra=None):
        event = {"schema": 1, "id": str(uuid.uuid4()), "at": utc(), "agent": actor,
                 "kind": kind, "task": task, "note": note, **(extra or {})}
        path = self.root / "coord/journal" / event["at"][:10] / actor / (event["id"] + ".json")
        write_json(path, event)
        return event

    def run(self, args):
        actor = identifier(args.agent)
        with self.transaction() as data:
            if args.command == "status":
                lease = self.lease()
                locks = []
                for path in (self.runtime / "locks").glob("*.json"):
                    value = json.loads(path.read_text())
                    locks.append({**value, "expired": value["expires_at_epoch"] <= time.time()})
                return {**data, "orchestrator": lease,
                        "orchestrator_active": bool(lease and lease["expires_at_epoch"] > time.time()),
                        "resource_locks": locks, "shared_root": str(self.root)}
            if args.command == "register":
                data["agents"][actor] = {"kind": args.kind, "role": args.role,
                    "status": "active", "host": args.host, "last_seen": utc()}
                return self.event(actor, "registered", args.note)
            if actor not in data["agents"]:
                raise ValueError("Registre primero el agente.")
            if args.command == "heartbeat":
                data["agents"][actor].update(status=args.status, last_seen=utc())
                return {"agent": actor, **data["agents"][actor]}
            if args.command == "orchestrator":
                current = self.lease()
                path = self.runtime / "orchestrator.json"
                if args.action == "claim":
                    if current and current["agent"] != actor:
                        raise ValueError("Otro agente conserva la concesión; incluso caducada requiere recuperación explícita.")
                    value = {"agent": actor, "kind": data["agents"][actor]["kind"],
                             "expires_at_epoch": time.time() + args.ttl, "updated_at": utc()}
                    write_json(path, value)
                    return self.event(actor, "orchestrator.claim", args.note, extra={"lease": value})
                if args.action == "recover":
                    if not current or current["expires_at_epoch"] > time.time():
                        raise ValueError("Solo puede recuperarse una concesión caducada.")
                    if not args.confirm_stopped or not args.note:
                        raise ValueError("Verifique que el anterior agente está detenido: --confirm-stopped y --note obligatorios.")
                    path.unlink()
                    return self.event(actor, "orchestrator.recovered", args.note, extra={"previous": current})
                if not current or current["agent"] != actor:
                    raise ValueError("Solo el propietario puede liberar su concesión.")
                path.unlink()
                return self.event(actor, "orchestrator.release", args.note)
            if args.command == "journal":
                if args.task:
                    identifier(args.task)
                return self.event(actor, args.kind, args.note, args.task)
            if args.command == "message":
                recipient = identifier(args.to)
                if recipient not in data["agents"]:
                    raise ValueError("Destinatario no registrado.")
                event = self.event(actor, "message", args.note, args.task,
                                   {"to": recipient, "reply_to": args.reply_to})
                write_json(self.root / "coord/messages" / recipient / (event["id"] + ".json"), event)
                return event
            if args.command == "inbox":
                return [json.loads(p.read_text()) for p in sorted((self.root / "coord/messages" / actor).glob("*.json"))]
            if args.command == "lock":
                resource = identifier(args.resource)
                path = self.runtime / "locks" / (resource + ".json")
                current = json.loads(path.read_text()) if path.exists() else None
                if args.action == "acquire":
                    if not args.task or args.task not in data["tasks"]:
                        raise ValueError("El bloqueo requiere una tarea existente.")
                    task = data["tasks"][args.task]
                    if task["owner"] != actor:
                        raise ValueError("El bloqueo debe pertenecer al responsable de la tarea.")
                    if task["state"] not in {"planned", "in_progress", "blocked", "review"}:
                        raise ValueError("La tarea ya está cerrada o no está asignada.")
                    if current and current["agent"] != actor:
                        raise ValueError("Recurso ocupado; no se roba un bloqueo caducado.")
                    if current and current["task"] != args.task:
                        raise ValueError("Libere el bloqueo anterior antes de cambiar de tarea.")
                    value = {"resource": resource, "agent": actor, "task": args.task,
                             "expires_at_epoch": time.time() + args.ttl, "at": utc()}
                    write_json(path, value)
                    return self.event(actor, "lock.acquire", args.note, args.task, {"lock": value})
                if args.action == "recover":
                    self.require_orchestrator(actor)
                    if not current or current["expires_at_epoch"] > time.time() or not args.confirm_stopped or not args.note:
                        raise ValueError("Recuperación requiere bloqueo caducado, propietario detenido y motivo.")
                elif not current or current["agent"] != actor:
                    raise ValueError("Solo el propietario puede liberar su bloqueo.")
                path.unlink()
                return self.event(actor, "lock." + args.action, args.note, extra={"previous": current})
            if args.command == "task":
                task_id = identifier(args.id)
                if args.action == "create":
                    self.require_orchestrator(actor)
                    if task_id in data["tasks"]:
                        raise ValueError("La tarea ya existe.")
                    if not args.title or not args.acceptance:
                        raise ValueError("Defina título y criterio de aceptación.")
                    task = {"id": task_id, "title": args.title, "acceptance": args.acceptance,
                            "risk": args.risk, "owner": None, "state": "backlog", "artifact": None,
                            "reviews": [], "updated_at": utc()}
                    data["tasks"][task_id] = task
                else:
                    if task_id not in data["tasks"]:
                        raise ValueError("Tarea inexistente.")
                    task = data["tasks"][task_id]
                    if args.action == "assign":
                        self.require_orchestrator(actor)
                        owner = identifier(args.owner or "")
                        if owner not in data["agents"]:
                            raise ValueError("Responsable no registrado.")
                        if task["state"] not in {"backlog", "planned", "blocked"}:
                            raise ValueError("No reasigne trabajo activo o cerrado.")
                        if any(json.loads(p.read_text())["task"] == task_id for p in (self.runtime / "locks").glob("*.json")):
                            raise ValueError("Libere los bloqueos antes de reasignar.")
                        task.update(owner=owner, state="planned", artifact=None, reviews=[])
                    elif args.action == "review":
                        if task["state"] != "review" or not task["artifact"]:
                            raise ValueError("La tarea debe estar en revisión con un artefacto.")
                        if task["owner"] == actor:
                            raise ValueError("La revisión requiere otro agente.")
                        if task["risk"] in {"R2", "R3"} and data["agents"][task["owner"]]["kind"] == data["agents"][actor]["kind"]:
                            raise ValueError("R2/R3 requiere una revisión de otra familia de agente.")
                        if args.artifact != task["artifact"] or not args.verdict or not args.note:
                            raise ValueError("La revisión debe vincular artefacto, dictamen y evidencia.")
                        task["reviews"].append({"agent": actor, "artifact": args.artifact,
                                                "verdict": args.verdict, "at": utc(), "note": args.note})
                    elif args.action == "state":
                        if args.state not in STATES:
                            raise ValueError("Estado inválido.")
                        if args.state in {"done", "cancelled", "planned"}:
                            self.require_orchestrator(actor)
                        elif task["owner"] != actor:
                            raise ValueError("Solo el responsable cambia el estado de trabajo.")
                        allowed = {"backlog": {"cancelled"}, "planned": {"in_progress", "blocked", "cancelled"},
                            "in_progress": {"review", "blocked", "cancelled"},
                            "blocked": {"in_progress", "planned", "cancelled"},
                            "review": {"in_progress", "done", "blocked", "cancelled"}, "done": set(), "cancelled": set()}
                        if args.state not in allowed[task["state"]]:
                            raise ValueError("Transición de tarea no permitida.")
                        if args.state == "in_progress":
                            active = [v for v in data["tasks"].values() if v["state"] == "in_progress"]
                            if len(active) >= data["max_workers"]:
                                raise ValueError("Límite de trabajos simultáneos alcanzado.")
                            if not task["owner"]:
                                raise ValueError("Asigne un responsable primero.")
                            task["artifact"] = None
                            task["reviews"] = []
                        if args.state == "review":
                            if not args.artifact or not args.note:
                                raise ValueError("La entrega requiere artefacto verificable y evidencia en --note.")
                            task["artifact"] = args.artifact
                            task["reviews"] = []
                        if args.state == "done":
                            matching = [r for r in task["reviews"] if r["artifact"] == task["artifact"]]
                            if task["state"] != "review" or not matching or matching[-1]["verdict"] != "pass" or not args.note:
                                raise ValueError("Cerrar requiere revisión vigente PASS y aceptación documentada.")
                        if args.state in {"done", "cancelled"} and any(json.loads(p.read_text())["task"] == task_id for p in (self.runtime / "locks").glob("*.json")):
                            raise ValueError("Libere los bloqueos de la tarea antes de cerrarla.")
                        task["state"] = args.state
                task["updated_at"] = utc()
                self.event(actor, "task." + args.action, args.note, task_id, {"task_snapshot": task.copy()})
                return task
            raise ValueError("Comando desconocido.")

def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=project_root())
    p.add_argument("--agent", default=os.environ.get("SAGWA_AGENT", "codex-docs"))
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    c = commands.add_parser("register")
    c.add_argument("--kind", required=True, choices=["codex", "claude", "grok", "agy", "human", "other"])
    c.add_argument("--role", default="worker", choices=["worker", "reviewer", "orchestrator"])
    c.add_argument("--host", default="mac-mini")
    c.add_argument("--note", default="")
    c = commands.add_parser("heartbeat")
    c.add_argument("--status", default="active", choices=["active", "idle", "inactive"])
    c = commands.add_parser("orchestrator")
    c.add_argument("action", choices=["claim", "release", "recover"])
    c.add_argument("--ttl", type=int, default=7200)
    c.add_argument("--confirm-stopped", action="store_true")
    c.add_argument("--note", default="")
    c = commands.add_parser("journal")
    c.add_argument("--kind", required=True, choices=["plan", "progress", "result", "decision", "handoff", "incident"])
    c.add_argument("--task")
    c.add_argument("--note", required=True)
    c = commands.add_parser("message")
    c.add_argument("--to", required=True)
    c.add_argument("--task")
    c.add_argument("--reply-to")
    c.add_argument("--note", required=True)
    commands.add_parser("inbox")
    c = commands.add_parser("lock")
    c.add_argument("action", choices=["acquire", "release", "recover"])
    c.add_argument("resource")
    c.add_argument("--task")
    c.add_argument("--ttl", type=int, default=7200)
    c.add_argument("--confirm-stopped", action="store_true")
    c.add_argument("--note", default="")
    c = commands.add_parser("task")
    c.add_argument("action", choices=["create", "assign", "state", "review"])
    c.add_argument("id")
    c.add_argument("--title")
    c.add_argument("--acceptance")
    c.add_argument("--risk", choices=["R0", "R1", "R2", "R3"], default="R1")
    c.add_argument("--owner")
    c.add_argument("--state", choices=sorted(STATES))
    c.add_argument("--artifact")
    c.add_argument("--verdict", choices=["pass", "changes"])
    c.add_argument("--note", default="")
    return p

def main():
    args = parser().parse_args()
    try:
        if hasattr(args, "ttl") and not 30 <= args.ttl <= 7200:
            raise ValueError("TTL debe estar entre 30 y 7200 segundos.")
        print(json.dumps(Board(args.root).run(args), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
