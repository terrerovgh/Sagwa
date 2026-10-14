import importlib.util
import os
import concurrent.futures
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

herdr = load("sagwa_herdr", "scripts/sagwa-herdr.py")
guard = load("publication", "scripts/check-publication.py")

class BoundaryTests(unittest.TestCase):
    def test_no_control_outside_herdr(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(herdr, "cli") as cli:
            with self.assertRaises(ValueError): herdr.setup()
            with self.assertRaises(ValueError): herdr.start("codex", "worker")
            cli.assert_not_called()

    def test_missing_agent_does_not_start_or_change_provider(self):
        with patch.dict(os.environ, {"HERDR_ENV": "1"}), patch.object(herdr, "doctor", return_value={"profiles": {"claude": {"executable": None}}}), patch.object(herdr, "cli") as cli:
            with self.assertRaises(ValueError): herdr.start("claude", "worker")
            cli.assert_not_called()

    def test_publication_secrets_and_private_paths(self):
        self.assertTrue(guard.inspect("agentshell/.private/x.json", b"{}"))
        self.assertTrue(guard.inspect("x.env", b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----"))
        self.assertTrue(guard.inspect(".env", b"{}"))
        self.assertFalse(guard.inspect("docs/evidence/edge-n2.json", b'{"promoted":false}'))
        self.assertFalse(guard.inspect("release-public.pem", b"-----BEGIN PUBLIC KEY-----"))

    def test_private_cannot_hide_under_public_receipts(self):
        self.assertTrue(guard.inspect("docs/evidence/.private/auth.json", b"{}"))
        self.assertTrue(guard.inspect("docs/evidence/backups/flash-full.bin", b"fake"))
        self.assertTrue(guard.inspect("docs/evidence/unreviewed.json", b"{}"))
        for prefix in [b"sk-" + b"proj-", b"xai-", b"AIza", b"tskey-" + b"auth-"]:
            self.assertTrue(guard.inspect("config/test.json", prefix + b"A" * 40))

    def test_n3a_receipt_allows_only_exact_path_and_keeps_secret_filter(self):
        content = (ROOT / "docs/evidence/n3a-rig.json").read_bytes()
        self.assertFalse(guard.inspect("docs/evidence/n3a-rig.json", content))
        self.assertTrue(guard.inspect("docs/evidence/raw/n3a-rig.json", content))
        self.assertTrue(guard.inspect("docs/evidence/n3a-raw.json", content))
        fake_secret = b"sk-" + b"proj-" + b"A" * 40
        self.assertTrue(guard.inspect("docs/evidence/n3a-rig.json", fake_secret))

    def test_wrong_session_or_replaced_pane_never_started(self):
        scope = {"socket": "/tmp/herdr.sock", "session": None}
        state = {"cwd": str(ROOT), "scope": scope, "workspace": "w2", "panes": {"codex": "w2:p2"},
                 "tabs": {"codex": "w2:t2"}, "terminals": {"codex": "terminal-original"}}
        workspace = {"workspace": {"workspace_id": "w2", "label": "Sagwa"}}
        pane = {"pane": {"workspace_id": "w2", "tab_id": "w2:t2", "terminal_id": "terminal-original",
                          "cwd": str(ROOT), "foreground_cwd": str(ROOT)}}
        with patch.object(herdr, "identity", return_value={"socket": "/tmp/other.sock", "session": "other"}), patch.object(herdr, "cli") as cli:
            with self.assertRaises(ValueError): herdr.validate(state)
            cli.assert_not_called()
        for field, bad in [("terminal_id", "replaced"), ("foreground_cwd", "/tmp/other-project"), ("workspace_id", "w3")]:
            bad_pane = {"pane": {**pane["pane"], field: bad}}
            with patch.object(herdr, "identity", return_value=scope), patch.object(herdr, "cli", side_effect=[workspace, bad_pane]):
                with self.assertRaises(ValueError): herdr.validate(state, target_role="codex")

    def test_other_worker_cwd_does_not_block_valid_target(self):
        scope = {"socket": "/tmp/herdr.sock", "session": None}
        state = {"cwd": str(ROOT), "scope": scope, "workspace": "w2", "panes": {"codex": "w2:p2", "agy": "w2:p3"},
                 "tabs": {"codex": "w2:t2", "agy": "w2:t3"}, "terminals": {"codex": "term2", "agy": "term3"}}
        workspace = {"workspace": {"workspace_id": "w2", "label": "Sagwa"}}
        panes = [{"pane": {"workspace_id": "w2", "tab_id": "w2:t2", "terminal_id": "term2", "foreground_cwd": str(ROOT)}},
                 {"pane": {"workspace_id": "w2", "tab_id": "w2:t3", "terminal_id": "term3", "foreground_cwd": "/tmp/another-worktree"}}]
        with patch.object(herdr, "identity", return_value=scope), patch.object(herdr, "cli", side_effect=[workspace, *panes]):
            herdr.validate(state, target_role="codex")

    def test_setup_concurrent_single_workspace_and_reuse(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(herdr, "STATE", Path(temp) / "herdr.json"), patch.dict(os.environ, {"HERDR_ENV": "1"}), patch.object(herdr, "identity", return_value={"socket": "/tmp/test.sock", "session": None}), patch.object(herdr, "validate"):
            created = []
            def cli(*args):
                if args[:2] == ("workspace", "create"):
                    created.append(1); time.sleep(0.02)
                    return {"workspace": {"workspace_id": "w9"}, "tab": {"tab_id": "w9:t1"}, "root_pane": {"pane_id": "w9:p1", "terminal_id": "term1"}}
                if args[:2] == ("tab", "create"):
                    label = args[args.index("--label") + 1]
                    return {"tab": {"tab_id": "t-" + label}, "root_pane": {"pane_id": "p-" + label, "terminal_id": "term-" + label}}
                return {}
            with patch.object(herdr, "cli", side_effect=cli), concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: herdr.setup(), range(2)))
            self.assertEqual(len(created), 1)
            self.assertTrue(all(len(r["panes"]) == 5 for r in results))
            self.assertEqual(sum(bool(r.get("reused")) for r in results), 1)

    def test_launcher_never_starts_its_own_occupied_pane(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "herdr.json"
            state.write_text('{"panes":{"orchestrator":"w2:p1"}}')
            with patch.object(herdr, "STATE", state), patch.dict(os.environ, {"HERDR_ENV":"1", "HERDR_PANE_ID":"w2:p1"}), patch.object(herdr, "doctor", return_value={"profiles":{"codex":{"executable":"/tmp/codex"}}}), patch.object(herdr, "validate"), patch.object(herdr, "cli") as cli:
                with self.assertRaisesRegex(ValueError, "pane destino"): herdr.start("codex", "orchestrator")
                cli.assert_not_called()
