"""Use public compiled images to simulate a backup; no device reads or writes."""
import binascii
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

root = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('trial', root / 'agentshell/edge-firmware/tools/audit_app_trial.py')
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class TrialAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (root / 'build/agentshell.bin').read_bytes()
        cls.boot = (root / 'build/bootloader/bootloader.bin').read_bytes()
        cls.candidate = (root / 'build/edge/sagwa_edge.bin').read_bytes()
        cls.parser = trial.partition_parser(Path.home() / 'esp/esp-idf-v6.0.1')
        fake = bytearray(b'\xff' * trial.FLASH_SIZE)
        fake[:len(cls.boot)] = cls.boot
        partition = (root / 'build/partition_table/partition-table.bin').read_bytes()
        fake[0x10000:0x10000 + len(partition)] = partition
        fake[0x20000:0x20000 + len(cls.app)] = cls.app
        entry = bytearray(b'\xff' * 32)
        struct.pack_into('<I', entry, 0, 3)
        struct.pack_into('<II', entry, 24, 2, binascii.crc32(entry[:4], 0xffffffff))
        fake[0x1d000:0x1d020] = entry
        cls.flash = bytes(fake)

    def run_audit(self, first=None, second=None, app=None, boot=None, candidate=None):
        return trial.audit_bytes(first if first is not None else self.flash,
                                 second if second is not None else self.flash,
                                 app if app is not None else self.app,
                                 boot if boot is not None else self.boot,
                                 candidate if candidate is not None else self.candidate,
                                 self.parser, trial.digest(self.candidate))

    def test_matching_known_layout_and_confirmed_slot(self):
        result = self.run_audit()
        self.assertEqual(result['active_slot'], 'ota_0')
        self.assertEqual(result['inactive_slot'], 'ota_1')
        self.assertFalse(result['deployment_approved'])
        self.assertFalse(result['usb_opened'])

    def test_mismatch_and_incomplete_reads(self):
        changed = bytearray(self.flash); changed[-1] = 0
        with self.assertRaisesRegex(ValueError, 'matching'):
            self.run_audit(second=bytes(changed))
        with self.assertRaisesRegex(ValueError, 'matching'):
            self.run_audit(first=self.flash[:-1], second=self.flash[:-1])

    def test_changed_baselines_and_active_app(self):
        with self.assertRaisesRegex(ValueError, 'Baseline app'):
            self.run_audit(app=self.app[:-1])
        with self.assertRaisesRegex(ValueError, 'bootloader'):
            self.run_audit(boot=b'changed')
        changed = bytearray(self.flash); changed[0x20000 + 100] ^= 1
        with self.assertRaisesRegex(ValueError, 'Active slot'):
            self.run_audit(first=bytes(changed), second=bytes(changed))

    def test_pending_and_invalid_ota_metadata(self):
        for state in (0, 1, 3, 4):
            changed = bytearray(self.flash); struct.pack_into('<I', changed, 0x1d018, state)
            with self.assertRaises(ValueError):
                self.run_audit(first=bytes(changed), second=bytes(changed))
        changed = bytearray(self.flash); changed[0x1d01c] ^= 1
        with self.assertRaisesRegex(ValueError, 'No valid'):
            self.run_audit(first=bytes(changed), second=bytes(changed))

    def test_candidate_bounds_and_descriptor(self):
        for candidate in (b'', b'x' * 80, b'x' * 0x400000):
            with self.assertRaises(ValueError): self.run_audit(candidate=candidate)
        changed = bytearray(self.candidate); changed[48] = ord('9')
        with self.assertRaisesRegex(ValueError, 'version'):
            self.run_audit(candidate=bytes(changed))
        changed = bytearray(self.candidate); changed[150] ^= 1
        with self.assertRaisesRegex(ValueError, 'pinned'):
            self.run_audit(candidate=bytes(changed))

    def test_metadata_generated_by_official_otatool(self):
        # Run the real IDF tool with an in-memory target, without its constructor,
        # esptool, a serial port or device operations.
        idf = Path.home() / 'esp/esp-idf-v6.0.1'
        os.environ['IDF_PATH'] = str(idf)
        sys.path.insert(0, str(idf / 'components/partition_table'))
        spec = importlib.util.spec_from_file_location('sagwa_official_otatool',
                                                     idf / 'components/app_update/otatool.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        class MemoryTarget:
            partition_table = TrialAudit.parser.PartitionTable.from_binary(
                TrialAudit.flash[0x10000:0x11000])
            written = None
            def write_partition(self, partition, filename):
                self.written = Path(filename).read_bytes()
        target = MemoryTarget()
        tool = module.OtatoolTarget.__new__(module.OtatoolTarget)
        tool.target = target
        tool.spi_flash_sec_size = 0x2000
        tool.otadata = self.flash[0x1d000:0x1f000]
        tool.switch_ota_partition(0)
        self.assertIsNotNone(target.written)
        generated = bytearray(target.written)
        # Tool bases the new record on sector0 and writes sector1. Remove the
        # old record so it cannot conceal a bad CRC in the tool-generated one.
        generated[:4096] = b'\xff' * 4096
        struct.pack_into('<I', generated, 4096 + 24, 2) # separate app confirmation
        changed = bytearray(self.flash); changed[0x1d000:0x1f000] = generated
        self.assertEqual(self.run_audit(bytes(changed), bytes(changed))['active_slot'], 'ota_0')
        struct.pack_into('<I', changed, 0x1e01c,
                         binascii.crc32(changed[0x1e000:0x1e01c], 0xffffffff))
        with self.assertRaisesRegex(ValueError, 'No valid'):
            self.run_audit(bytes(changed), bytes(changed))

    def test_private_backup_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'synthetic.bin'
            p.write_bytes(self.flash); p.chmod(0o644)
            with self.assertRaisesRegex(ValueError, '0600'): trial.private_read(p)
            p.chmod(0o600)
            self.assertEqual(trial.private_read(p), self.flash)
            link = Path(folder) / 'link.bin'; link.symlink_to(p)
            with self.assertRaisesRegex(ValueError, 'regular'): trial.private_read(link)


if __name__ == '__main__':
    unittest.main()
