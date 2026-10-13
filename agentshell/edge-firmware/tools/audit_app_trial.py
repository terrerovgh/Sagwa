"""Read-only audit of supplied private flash backups. Never opens USB or writes flash.

The inputs contain device secrets: require a private directory and mode 0600.
This validates bytes, not their hardware origin or permission to deploy.
"""
import argparse
import binascii
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import stat
import struct

FLASH_SIZE = 16 * 1024 * 1024
GOLDEN_SHA = '88e9c70d2b1f521c48f928e146aa442a94b403ddb6227f94db2043fa3a9231ba'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def partition_parser(idf_path):
    path = Path(idf_path) / 'components/partition_table/gen_esp32part.py'
    spec = importlib.util.spec_from_file_location('sagwa_partition_parser', path)
    if not spec or not spec.loader:
        raise ValueError('Official ESP-IDF partition parser unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def private_read(path):
    path = Path(path)
    info = path.lstat()
    parent = path.parent.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('Backup must be a regular file owned by this user')
    if stat.S_IMODE(info.st_mode) != 0o600 or stat.S_IMODE(parent.st_mode) != 0o700:
        raise ValueError('Backup requires mode 0600 in a directory with mode 0700')
    if info.st_size != FLASH_SIZE:
        raise ValueError('Backup must contain exactly 16 MiB')
    return path.read_bytes()


def audit_bytes(first, second, baseline_app, baseline_bootloader, candidate, parser,
                expected_candidate_sha):
    if len(first) != FLASH_SIZE or len(second) != FLASH_SIZE or first != second:
        raise ValueError('Two complete matching flash reads are required')
    if digest(baseline_app) != GOLDEN_SHA:
        raise ValueError('Baseline app differs from the verified 0.2.0 release')
    if not baseline_bootloader or len(baseline_bootloader) > 0x10000:
        raise ValueError('Invalid baseline bootloader size')
    if first[:len(baseline_bootloader)] != baseline_bootloader:
        raise ValueError('Installed bootloader differs from the baseline: investigate before OTA')
    table = parser.PartitionTable.from_binary(first[0x10000:0x11000])
    table.verify()
    rows = {p.name: (p.type, p.subtype, p.offset, p.size,
                    sum(1 << p.FLAGS[flag] for flag in p.get_flags_list())) for p in table}
    expected = {'nvs': (1, 2, 0x11000, 0xC000, 0),
                'otadata': (1, 0, 0x1D000, 0x2000, 0),
                'phy_init': (1, 1, 0x1F000, 0x1000, 0),
                'ota_0': (0, 0x10, 0x20000, 0x400000, 0),
                'ota_1': (0, 0x11, 0x420000, 0x400000, 0),
                'storage': (1, 0x82, 0x820000, 0x7DE000, 0)}
    if rows != expected:
        raise ValueError('Installed partition layout differs from 0.2.0; no app-only trial')
    selections = []
    metadata = []
    for sector in range(2):
        entry = first[0x1D000 + sector * 4096:0x1D000 + sector * 4096 + 32]
        sequence = struct.unpack_from('<I', entry)[0]
        state, crc = struct.unpack_from('<II', entry, 24)
        # Official IDF6.0.1 bootloader_common_ota_select_crc hashes ota_seq only
        # (4 bytes). ota_state is checked separately, not included in that CRC.
        valid = sequence not in (0, 0xffffffff) and crc == binascii.crc32(entry[:4], 0xffffffff)
        metadata.append(dict(sector=sector, sequence=sequence, state=state, crc_valid=valid))
        if valid and (sequence >= 0xfffffff0 or state in (0, 1)):
            raise ValueError('Pending/new or wrapped OTA metadata requires manual reconciliation')
        if valid and state == 2:
            selections.append((sequence, (sequence - 1) % 2))
    if not selections:
        raise ValueError('No valid, confirmed OTA image in the supplied backup')
    _, active = max(selections)
    active_offset = expected['ota_' + str(active)][2]
    if digest(first[active_offset:active_offset + len(baseline_app)]) != GOLDEN_SHA:
        raise ValueError('Active slot does not contain the verified 0.2.0 release')
    if len(candidate) < 80 or len(candidate) >= 0x400000 or candidate[0] != 0xe9:
        raise ValueError('Candidate app does not fit a 4 MiB OTA slot')
    if struct.unpack_from('<I', candidate, 32)[0] != 0xabcd5432:
        raise ValueError('Candidate ESP-IDF app descriptor missing')
    version = candidate[48:80].split(b'\0', 1)[0].decode('ascii')
    if version != '0.3.0-dev':
        raise ValueError('Unexpected candidate version')
    if not re.fullmatch(r'[0-9a-f]{64}', expected_candidate_sha or '') or digest(candidate) != expected_candidate_sha:
        raise ValueError('Candidate SHA differs from the pinned reviewed image')
    return dict(scope='Read-only byte audit; hardware origin, signature and rollback trial remain separate',
                matching_flash_reads=True, flash_sha256=digest(first), partition_table_matches_0_2=True,
                active_slot='ota_' + str(active), inactive_slot='ota_' + str(1 - active),
                baseline_sha256=GOLDEN_SHA, bootloader_sha256=digest(baseline_bootloader),
                ota_metadata=metadata, candidate_sha256=digest(candidate), candidate_size=len(candidate),
                candidate_version=version, deployment_approved=False, usb_opened=False,
                partition_table_written=False, efuses_written=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--first-backup', type=Path, required=True)
    p.add_argument('--second-backup', type=Path, required=True)
    p.add_argument('--baseline-app', type=Path, required=True)
    p.add_argument('--baseline-bootloader', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--candidate-sha256', required=True,
                   help='Pinned SHA-256 from the exact candidate review receipt; not a signature')
    p.add_argument('--idf-path', type=Path, required=True)
    a = p.parse_args()
    if a.first_backup.resolve() == a.second_backup.resolve() or os.path.samefile(a.first_backup, a.second_backup):
        raise ValueError('Two separate backup files are required')
    result = audit_bytes(private_read(a.first_backup), private_read(a.second_backup),
                         a.baseline_app.read_bytes(), a.baseline_bootloader.read_bytes(),
                         a.candidate.read_bytes(), partition_parser(a.idf_path),
                         a.candidate_sha256)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
