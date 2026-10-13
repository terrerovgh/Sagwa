import concurrent.futures
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("coord", ROOT / "scripts/coord.py")
coord = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coord)

class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.board = coord.Board(self.root)
        self.run_cmd("orch", "register", "--kind", "agy", "--role", "orchestrator")
        self.run_cmd("worker", "register", "--kind", "claude")
        self.run_cmd("reviewer", "register", "--kind", "grok", "--role", "reviewer")
        self.run_cmd("orch", "orchestrator", "claim")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cmd(self, actor, *arguments):
        args = coord.parser().parse_args(["--root", str(self.root), "--agent", actor, *arguments])
        return self.board.run(args)

    def task(self, name="S-1", owner="worker", risk="R2"):
        self.run_cmd("orch", "task", "create", name, "--title", "Test", "--acceptance", "Observable", "--risk", risk)
        self.run_cmd("orch", "task", "assign", name, "--owner", owner)

    def deliver(self):
        self.run_cmd("worker", "task", "state", "S-1", "--state", "in_progress")
        self.run_cmd("worker", "task", "state", "S-1", "--state", "review", "--artifact", "sha1", "--note", "Tests passed")

    def test_orchestrator_any_family_and_exclusive(self):
        with self.assertRaises(ValueError):
            self.run_cmd("worker", "orchestrator", "claim")
        self.run_cmd("orch", "orchestrator", "release")
        self.run_cmd("worker", "orchestrator", "claim")
        self.assertEqual(self.board.lease()["kind"], "claude")

    def test_expired_requires_explicit_recovery(self):
        value = self.board.lease()
        value["expires_at_epoch"] = time.time() - 1
        coord.write_json(self.board.runtime / "orchestrator.json", value)
        with self.assertRaises(ValueError):
            self.run_cmd("worker", "orchestrator", "claim")
        with self.assertRaises(ValueError):
            self.run_cmd("worker", "orchestrator", "recover")
        self.run_cmd("worker", "orchestrator", "recover", "--confirm-stopped", "--note", "Previous worker stopped")
        self.run_cmd("worker", "orchestrator", "claim")

    def test_lock_owner_expiry_and_task_change(self):
        self.task()
        self.run_cmd("worker", "lock", "acquire", "edge-ui", "--task", "S-1")
        with self.assertRaises(ValueError):
            self.run_cmd("reviewer", "lock", "release", "edge-ui")
        with self.assertRaises(ValueError):
            self.run_cmd("orch", "task", "assign", "S-1", "--owner", "reviewer")
        path = self.board.runtime / "locks/edge-ui.json"
        value = json.loads(path.read_text()); value["expires_at_epoch"] = time.time() - 1
        coord.write_json(path, value)
        with self.assertRaises(ValueError):
            self.run_cmd("orch", "lock", "recover", "edge-ui", "--note", "Expired")
        self.run_cmd("orch", "lock", "recover", "edge-ui", "--confirm-stopped", "--note", "Stopped and checked")

    def test_review_exact_artifact_and_independence(self):
        self.task(); self.deliver()
        with self.assertRaises(ValueError):
            self.run_cmd("worker", "task", "review", "S-1", "--artifact", "sha1", "--verdict", "pass", "--note", "Self review")
        with self.assertRaises(ValueError):
            self.run_cmd("reviewer", "task", "review", "S-1", "--artifact", "other", "--verdict", "pass", "--note", "Wrong sha")
        with self.assertRaises(ValueError):
            self.run_cmd("orch", "task", "state", "S-1", "--state", "done", "--note", "No review")
        self.run_cmd("reviewer", "task", "review", "S-1", "--artifact", "sha1", "--verdict", "pass", "--note", "Exact review")
        result = self.run_cmd("orch", "task", "state", "S-1", "--state", "done", "--note", "Criteria accepted")
        self.assertEqual(result["state"], "done")

    def test_review_invalidated_by_rework(self):
        self.task(); self.deliver()
        self.run_cmd("reviewer", "task", "review", "S-1", "--artifact", "sha1", "--verdict", "pass", "--note", "Pass")
        result = self.run_cmd("worker", "task", "state", "S-1", "--state", "in_progress")
        self.assertEqual(result["reviews"], []); self.assertIsNone(result["artifact"])

    def test_cannot_close_while_resource_held(self):
        self.task(); self.run_cmd("worker", "lock", "acquire", "edge-ui", "--task", "S-1"); self.deliver()
        self.run_cmd("reviewer", "task", "review", "S-1", "--artifact", "sha1", "--verdict", "pass", "--note", "Pass")
        with self.assertRaises(ValueError):
            self.run_cmd("orch", "task", "state", "S-1", "--state", "done", "--note", "Close")

    def test_three_active_tasks_limit(self):
        for n in range(4): self.task("S-" + str(n))
        for n in range(3): self.run_cmd("worker", "task", "state", "S-" + str(n), "--state", "in_progress")
        with self.assertRaises(ValueError):
            self.run_cmd("worker", "task", "state", "S-3", "--state", "in_progress")

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError): self.run_cmd("../escape", "journal", "--kind", "plan", "--note", "Bad")
        with self.assertRaises(ValueError): self.run_cmd("worker", "message", "--to", "../../escape", "--note", "Bad")

    def test_messages_append_and_reply(self):
        one = self.run_cmd("worker", "message", "--to", "orch", "--note", "Ready")
        two = self.run_cmd("orch", "message", "--to", "worker", "--reply-to", one["id"], "--note", "Received")
        self.assertEqual(two["reply_to"], one["id"])
        self.assertEqual(self.run_cmd("orch", "inbox")[0]["id"], one["id"])
        self.assertEqual(len(list((self.root / "coord/messages/orch").glob("*.json"))), 1)

    def test_concurrent_processes_no_lost_events(self):
        def append(n):
            result = subprocess.run([sys.executable, str(ROOT / "scripts/coord.py"), "--root", str(self.root),
                "--agent", "worker", "message", "--to", "orch", "--note", str(n)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(append, range(18)))
        inbox = self.run_cmd("orch", "inbox")
        self.assertEqual(len(inbox), 18)
        self.assertEqual(len({e["id"] for e in inbox}), 18)
        self.assertEqual({e["note"] for e in inbox}, {str(n) for n in range(18)})

if __name__ == "__main__": unittest.main()
