"""N3a installer checks against a flash emulator; never imports USB or opens a device."""
import binascii
import contextlib
import importlib.util
import io
import json
import struct
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('n3a', Path(__file__).with_name('physical-edge-trial-n3a.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


def record(seq, state):
    data = bytearray(b'\xff' * 4096)
    struct.pack_into('<I', data, 0, seq)
    struct.pack_into('<II', data, 24, state, binascii.crc32(data[:4], 0xffffffff))
    return bytes(data)


def selected(data):
    rows = trial.entries(data, allow_pending=True)
    rows = [x for x in rows if x['crc_valid'] and x['state'] not in (3, 4)]
    return max(rows, key=lambda x: x['sequence'])['slot'] if rows else None


def synthetic_image(size, version, fill):
    image = bytearray(bytes([fill]) * size)
    image[0] = 0xe9
    image[48:80] = version.ljust(32, b'\0')
    return bytes(image)


IMAGE = synthetic_image(trial.N3A_SIZE, b'0.3.0-dev', 0x33)
BASELINE_IMAGE = synthetic_image(trial.BASELINE_SIZE, b'0.2.0', 0x22)


def trace(kind):
    base = {'bytes': 20, 'capture_s': 45.0, 'alive_until_end': True, 'edge_boot_seen': True,
            'edge_boot_count': 1, 'edge_boot_at_s': 3.0, 'baseline_boot_seen': False,
            'panic_seen': False, 'backtrace_seen': False}
    if kind == 'empty':
        base.update(bytes=0, edge_boot_seen=False, edge_boot_count=0, edge_boot_at_s=None)
    elif kind == 'panic':
        base.update(panic_seen=True, backtrace_seen=True)
    elif kind == 'auto_rollback':
        base.update(baseline_boot_seen=True)
    elif kind == 'short':
        base.update(edge_boot_at_s=20.0)
    elif kind == 'reader_lost':
        base.update(alive_until_end=False, capture_s=12.0)
    elif kind == 'reboot_loop':
        base.update(edge_boot_count=2)
    elif kind == 'baseline':
        base.update(edge_boot_seen=False, edge_boot_count=0, edge_boot_at_s=None, baseline_boot_seen=True)
    return base


class Emulator:
    """Flash emulator plus synthetic private/evidence tree; no device or service."""

    def __init__(self, test, failure=None, already_exact=False, close_failure=False):
        self.test, self.failure, self.close_failure = test, failure, close_failure
        memory = bytearray(b'\xff' * (16 * 1024 * 1024))
        memory[0:0x10000] = b'\xb0' * 0x10000
        memory[0x10000:0x11000] = b'\x7a' * 0x1000
        memory[0x11000:0x1d000] = b'\x4e' * 0xc000
        memory[trial.BASELINE_OFFSET:trial.BASELINE_OFFSET + len(BASELINE_IMAGE)] = BASELINE_IMAGE
        memory[0x1d000:0x1f000] = record(7, 4) + record(6, 2)
        if already_exact:
            memory[0x20000:0x20000 + len(IMAGE)] = IMAGE
        self.memory, self.before = memory, bytes(memory)
        self.writes, self.connections, self.offers, self.captures = [], [], [], []
        self.traces, self.failed, self.offer_failure = [], False, None
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        (root / '.private/edge-hardware').mkdir(parents=True, mode=0o700)
        self.evidence = root / 'evidence/sagwa-v2'
        self.evidence.mkdir(parents=True)
        reads = []
        for i in (1, 2):
            path = root / '.private/edge-hardware' / f'backup{i}.bin'
            path.write_bytes(self.before)
            reads.append({'path': str(path), 'sha256': trial.sha(self.before)})
        (self.evidence / 'physical-flash-reads.json').write_text(
            json.dumps({'status': 'matching_reads', 'reads': reads}))
        (self.evidence / 'soak-docker.json').write_text(json.dumps({'status': 'interrupted'}))
        self.image = root / 'n3a.bin'
        self.image.write_bytes(IMAGE)
        self.review = root / 'review.json'
        self.review.write_text(json.dumps({'verdict': 'PASS', 'status': 'terminal_pass',
                                           'script_sha256': trial.sha(Path(trial.__file__).read_bytes()),
                                           'firmware_sha256': trial.sha(IMAGE)}))
        self.gate = root / 'offer-gate.json'
        self.gate.write_text(json.dumps({'status': 'ready', 'sha256': trial.sha(IMAGE), 'size': len(IMAGE),
                                         'signature_verified': True, 'device_id': trial.DEVICE_ID}))

    def cmds(self):
        test, emu = self.test, self

        class Port:
            def close(self):
                if emu.close_failure:
                    raise OSError('Injected close failure')

        class ESP:
            CHIP_NAME = 'ESP32-S3'
            secure_download_mode = False

            def __init__(self):
                self._port, self.stage = Port(), 'download'

            def read_mac(self):
                return bytes.fromhex(trial.MAC)

            def get_flash_encryption_enabled(self):
                return False

            def get_secure_boot_enabled(self):
                return False

            def flash_id(self):
                return 24 << 16

        def detect(*a, **k):
            esp = ESP()
            emu.connections.append(esp)
            return esp

        def read_flash(esp, offset, size, output, **kw):
            test.assertEqual(esp.stage, 'download', 'Flash read against application session')
            Path(output).write_bytes(emu.memory[offset:offset + size])

        def write_flash(esp, rows, **kw):
            test.assertEqual(esp.stage, 'download', 'Flash write against application session')
            for offset, data in rows:
                emu.writes.append((offset, len(data)))
                if emu.failure == 'metadata' and offset == 0x1d000 and not emu.failed:
                    emu.failed = True
                    emu.memory[offset:offset + 16] = data[:16]
                    raise OSError('Injected metadata interruption')
                emu.memory[offset:offset + len(data)] = data

        def reset(esp, *a):
            esp.stage = 'application'

        return types.SimpleNamespace(detect_chip=detect, run_stub=lambda e: e, read_flash=read_flash,
                                     write_flash=write_flash, reset_chip=reset)

    def capture(self, port, path, seconds=45):
        self.captures.append(seconds)
        if self.failure == 'capture' and len(self.captures) == 1:
            raise OSError('Injected post-reset read failure')
        kind = self.traces.pop(0) if self.traces else 'baseline'
        # Emulate what the bootloader/app would do to sector0 during the boot.
        if kind == 'valid':
            struct.pack_into('<I', self.memory, 0x1d000 + 24, 2)
        elif kind in ('panic', 'auto_rollback'):
            struct.pack_into('<I', self.memory, 0x1d000 + 24, 4)
        return trace(kind)

    def offer(self, digest):
        self.offers.append(digest)
        if self.offer_failure and self.offer_failure(digest):
            raise OSError('Injected admin API failure')

    def run(self, argv):
        patches = [
            patch.object(trial, 'ROOT', self.root),
            patch.object(trial, 'N3A', trial.sha(IMAGE)),
            patch.object(trial, 'BASELINE', trial.sha(BASELINE_IMAGE)),
            patch.object(trial, 'BOOT_SHA', trial.sha(self.before[:0x10000])),
            patch.object(trial, 'capture_console', side_effect=self.capture),
            patch.object(trial, 'offer_image', side_effect=self.offer),
            patch.dict(sys.modules, {'esptool': types.SimpleNamespace(cmds=self.cmds())}),
            patch.object(trial.subprocess, 'run', return_value=types.SimpleNamespace(returncode=113)),
        ]
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            return trial.main(argv)

    def apply(self, *extra):
        return self.run(['apply', '--port', 'synthetic', '--execute', '--image', str(self.image),
                         '--review', str(self.review), '--offer-gate', str(self.gate), *extra])

    def receipt(self, operation):
        found = sorted(self.evidence.glob(f'physical-n3a-{operation}-*.json'))
        self.test.assertEqual(len(found), 1)
        return json.loads(found[0].read_text())

    def checkpoint(self):
        return self.receipt('apply')['checkpoint']

    def assert_protected(self):
        m, b = self.memory, self.before
        self.test.assertEqual(bytes(m[:0x1d000]), b[:0x1d000])  # boot, table, NVS
        self.test.assertEqual(bytes(m[0x1e000:0x20000]), b[0x1e000:0x20000])  # metadata bank1
        self.test.assertEqual(bytes(m[trial.BASELINE_OFFSET:]), b[trial.BASELINE_OFFSET:])
        self.test.assertTrue(all(o in (0x20000, 0x1d000) for o, _ in self.writes))
        self.test.assertTrue(all(s == 4096 for o, s in self.writes if o == 0x1d000))


class N3aTrial(unittest.TestCase):
    def emulator(self, **kw):
        emu = Emulator(self, **kw)
        self.addCleanup(emu.tmp.cleanup)
        return emu

    def test_selection_keeps_confirmed_bank_through_partial_writes(self):
        before = record(7, 4) + record(6, 2)
        sector, seq = trial.selection(before)
        self.assertEqual((seq, selected(sector + before[4096:])), (9, 0))
        for length in (0, 1, 4, 24, 28, 31, 32, 4096):
            partial = sector[:length] + b'\xff' * (4096 - length) + before[4096:]
            self.assertTrue(trial.baseline_bank_confirmed(partial))
            self.assertIn(selected(partial), (0, 1))
        for bad in (record(7, 2) + record(6, 2), record(9, 1) + record(6, 2)):
            with self.assertRaises(ValueError):
                trial.selection(bad)

    def test_console_validation_is_conservative(self):
        self.assertTrue(trial.validated_on_console(trace('valid')))
        for kind in ('empty', 'panic', 'auto_rollback', 'short', 'reader_lost', 'reboot_loop'):
            self.assertFalse(trial.validated_on_console(trace(kind)), kind)
        summary = trial.summarize(b'App version:      0.3.0-dev\nok\n', 45.0, True, 2.5)
        self.assertTrue(trial.validated_on_console(summary))
        summary = trial.summarize(b'App version:      0.3.0-dev\nGuru Meditation Error\n', 45.0, True, 2.5)
        self.assertFalse(trial.validated_on_console(summary))

    def test_dry_run_never_imports_esptool_or_opens_usb(self):
        emu = self.emulator()
        out = io.StringIO()
        with patch.dict(sys.modules, {'esptool': None}), contextlib.redirect_stdout(out), \
                patch.object(trial, 'N3A', trial.sha(IMAGE)):
            trial.main(['apply', '--port', 'synthetic', '--image', str(emu.image), '--leave-installed'])
        plan = json.loads(out.getvalue())
        self.assertEqual((plan['usb_opened'], plan['leave_installed'], plan['capture_seconds']), (False, True, 45))
        self.assertFalse(plan['usb_reopened_after_validated_boot'])

    def test_leave_installed_keeps_validated_n3a_without_reopening_usb(self):
        emu = self.emulator()
        emu.traces = ['valid']
        emu.apply('--leave-installed')
        receipt = emu.receipt('apply')
        self.assertEqual(receipt['status'], 'installed_left_for_manual_trial')
        self.assertFalse(receipt['usb_reopened_after_success'])
        self.assertEqual(len(emu.connections), 1)  # no USB reopen after success
        self.assertEqual(emu.captures, [45])
        self.assertEqual(emu.offers, [trial.sha(IMAGE)])  # N3a offer stays to block OTA
        self.assertEqual(selected(bytes(emu.memory[0x1d000:0x1f000])), 0)
        self.assertEqual(bytes(emu.memory[0x20000:0x20000 + len(IMAGE)]), IMAGE)
        emu.assert_protected()

    def test_not_validated_boots_return_verified_baseline(self):
        for kind in ('empty', 'panic', 'auto_rollback', 'short', 'reader_lost', 'reboot_loop'):
            with self.subTest(kind):
                emu = self.emulator()
                emu.traces = [kind, 'baseline']
                emu.apply('--leave-installed')
                receipt = emu.receipt('apply')
                self.assertEqual(receipt['status'], 'not_validated_returned_baseline')
                self.assertTrue(receipt['baseline_selection_restored'])
                self.assertTrue(receipt['baseline_offer_acknowledged'])
                self.assertEqual(len(emu.connections), 2)
                self.assertEqual(emu.offers, [trial.sha(IMAGE), trial.sha(BASELINE_IMAGE)])
                self.assertEqual(selected(bytes(emu.memory[0x1d000:0x1f000])), 1)
                emu.assert_protected()

    def test_diagnostic_mode_always_restores_even_valid_image(self):
        emu = self.emulator()
        emu.traces = ['valid', 'baseline']
        emu.apply()
        receipt = emu.receipt('apply')
        self.assertEqual(receipt['status'], 'captured_and_restored')
        self.assertEqual(emu.captures, [95, 35])
        self.assertEqual(selected(bytes(emu.memory[0x1d000:0x1f000])), 1)
        emu.assert_protected()

    def test_interrupted_metadata_write_is_recovered(self):
        emu = self.emulator(failure='metadata')
        with self.assertRaisesRegex(OSError, 'Injected'):
            emu.apply('--leave-installed')
        receipt = emu.receipt('apply')
        self.assertEqual(receipt['status'], 'failed')
        self.assertTrue(receipt['metadata_recovered'])
        self.assertEqual(selected(bytes(emu.memory[0x1d000:0x1f000])), 1)
        self.assertEqual(emu.offers[-1], trial.sha(BASELINE_IMAGE))
        emu.assert_protected()

    def test_post_reset_failure_recovers_via_fresh_download_session(self):
        emu = self.emulator(failure='capture')
        with self.assertRaisesRegex(OSError, 'Injected'):
            emu.apply('--leave-installed')
        receipt = emu.receipt('apply')
        self.assertTrue(receipt['metadata_recovered'])
        self.assertEqual(len(emu.connections), 2)
        self.assertEqual(selected(bytes(emu.memory[0x1d000:0x1f000])), 1)

    def test_offer_failure_writes_nothing(self):
        emu = self.emulator()
        emu.offer_failure = lambda digest: True
        with self.assertRaisesRegex(OSError, 'admin'):
            emu.apply('--leave-installed')
        self.assertEqual(emu.writes, [])
        self.assertEqual(bytes(emu.memory), emu.before)
        self.assertEqual(emu.receipt('apply')['status'], 'failed')

    def test_gates_fail_before_usb(self):
        cases = {
            'review': lambda e: e.review.write_text(json.dumps({'verdict': 'PASS', 'status': 'terminal_pass',
                                                                'script_sha256': '0' * 64,
                                                                'firmware_sha256': trial.sha(IMAGE)})),
            'review_firmware': lambda e: e.review.write_text(json.dumps({
                **json.loads(e.review.read_text()), 'firmware_sha256': '0' * 64})),
            'gate': lambda e: e.gate.write_text(json.dumps({**json.loads(e.gate.read_text()), 'sha256': '0' * 64})),
            'gate_status': lambda e: e.gate.write_text(json.dumps({**json.loads(e.gate.read_text()), 'status': 'draft'})),
            'image': lambda e: e.image.write_bytes(IMAGE[:-1] + b'\0'),
            'backups': lambda e: Path(json.loads((e.evidence / 'physical-flash-reads.json').read_text())
                                      ['reads'][1]['path']).write_bytes(b'\0'),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                emu = self.emulator()
                mutate(emu)
                with self.assertRaises(ValueError):
                    emu.apply('--leave-installed')
                self.assertEqual(emu.connections, [])
                self.assertEqual(bytes(emu.memory), emu.before)

    def test_offline_rollback_after_leave_needs_only_checkpoint(self):
        emu = self.emulator()
        emu.traces = ['valid']
        emu.apply('--leave-installed')
        checkpoint = emu.checkpoint()
        # Offline: no image, review, gate or admin server is required.
        emu.image.unlink()
        emu.review.unlink()
        emu.gate.unlink()
        emu.offer_failure = lambda digest: True
        emu.traces = ['baseline']
        emu.run(['rollback', '--port', 'synthetic', '--execute', '--checkpoint', checkpoint])
        receipt = emu.receipt('rollback')
        self.assertEqual(receipt['status'], 'returned_baseline')
        self.assertFalse(receipt['baseline_offer_acknowledged'])
        self.assertTrue(all(o == 0x1d000 for o, _ in emu.writes[-1:]))
        self.assertEqual(selected(bytes(emu.memory[0x1d000:0x1f000])), 1)
        emu.assert_protected()

    def test_rollback_rejects_tampered_or_foreign_checkpoints_before_usb(self):
        emu = self.emulator()
        emu.traces = ['valid']
        emu.apply('--leave-installed')
        checkpoint = Path(emu.checkpoint())
        connections = len(emu.connections)
        original = checkpoint.read_text()
        mutations = {
            'file': lambda: (checkpoint.parent / 'nvs-before.bin').write_bytes(b'\0'),
            'baseline': lambda: checkpoint.write_text(original.replace(trial.sha(BASELINE_IMAGE), '0' * 64)),
            'outside': lambda: checkpoint.write_text(json.dumps({**json.loads(original),
                                                                 'directory': str(emu.root)})),
        }
        nvs = (checkpoint.parent / 'nvs-before.bin').read_bytes()
        for name, mutate in mutations.items():
            with self.subTest(name):
                mutate()
                with self.assertRaises(ValueError):
                    emu.run(['rollback', '--port', 'synthetic', '--execute', '--checkpoint', str(checkpoint)])
                self.assertEqual(len(emu.connections), connections)
                checkpoint.write_text(original)
                (checkpoint.parent / 'nvs-before.bin').write_bytes(nvs)

    def test_exact_installed_candidate_is_not_rewritten(self):
        emu = self.emulator(already_exact=True)
        emu.traces = ['valid']
        emu.apply('--leave-installed')
        self.assertTrue(emu.receipt('apply')['candidate_already_exact'])
        self.assertTrue(all(o == 0x1d000 for o, _ in emu.writes))

    def test_close_error_cannot_hide_receipt(self):
        emu = self.emulator(close_failure=True)
        emu.traces = ['valid']
        emu.apply('--leave-installed')
        receipt = emu.receipt('apply')
        self.assertTrue(receipt['close_errors'])
        self.assertEqual(receipt['status'], 'installed_left_for_manual_trial')

    @unittest.skipUnless(trial.DEFAULT_IMAGE.is_file(), 'pinned N3a build not present in this checkout')
    def test_pinned_image_matches_exact_build(self):
        self.assertEqual(trial.sha(trial.candidate(trial.DEFAULT_IMAGE)), trial.N3A)


if __name__ == '__main__':
    unittest.main()
