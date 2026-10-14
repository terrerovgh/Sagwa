"""Explicit app-only USB install of the exact N3a image for a manual user test.

Default prints a plan and never opens USB. Writes only inactive ota_0@0x20000
and OTA metadata sector0@0x1d000. Confirmed 0.2.0 in ota_1, metadata sector1,
bootloader, partition table and NVS are read back and must stay identical.

apply: the serial session that performs the only reset stays open to capture
the boot. Without --leave-installed the baseline selection is ALWAYS restored
(N2 behaviour). With --leave-installed the N3a selection is kept only when the
console shows one 0.3.0-dev boot, no panic/backtrace/0.2.0 boot, and a live
reader for at least VALIDATION_MARGIN_S after that boot (the app confirms or
rolls itself back at 30 s). On success USB is closed and never reopened.
Otherwise the baseline selection is restored and verified.

rollback: offline recovery from the private checkpoint alone. It needs neither
the candidate image, review, signed release nor the admin server; restoring
the baseline firmware offer is best effort and never blocks the local return.
Run with ESP-IDF's Python environment.
"""
import argparse
import binascii
import contextlib
import datetime
import hashlib
import json
import os
import queue
import re
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
N3A = '7bcd4a04d6990bf4b545c60694f527d46ef40fb1f9087222c2086fe0fa46c1ea'
N3A_SIZE = 2381072
N3A_VERSION = b'0.3.0-dev'
BASELINE = '88e9c70d2b1f521c48f928e146aa442a94b403ddb6227f94db2043fa3a9231ba'
BASELINE_SIZE = 2797472
MAC = '80456b4d5f7c'
DEVICE_ID = 'device:cores3-80456b4d5f7c'
BOOT_SHA = '2c7782c7fbcc14e36998ff1a622827d354d3a97ea78596d24351e356e4ea6674'
APP0, APP_SLOT, BASELINE_OFFSET = 0x20000, 0x400000, 0x420000
OTADATA, SECTOR = 0x1d000, 4096
BOOT, TABLE, NVS = (0, 0x10000), (0x10000, 0x1000), (0x11000, 0xc000)
CAPTURE_SECONDS = 45
VALIDATION_MARGIN_S = 33  # maintenance_task decides at 30 s after start
BASELINE_CAPTURE_SECONDS = 35
DEFAULT_IMAGE = ROOT.parent / 'build/edge/sagwa_edge.bin'
PROTECTED_FILES = ('boot-before.bin', 'table-before.bin', 'nvs-before.bin',
                   'metadata-before.bin')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def entries(data, allow_pending=False):
    if len(data) != 2 * SECTOR:
        raise ValueError('Expected two complete metadata sectors')
    result = []
    for bank in (0, 1):
        entry = data[bank * SECTOR:bank * SECTOR + 32]
        sequence, = struct.unpack_from('<I', entry)
        state, crc = struct.unpack_from('<II', entry, 24)
        valid = sequence not in (0, 0xffffffff) and crc == binascii.crc32(entry[:4], 0xffffffff)
        if valid and state not in (0, 1, 2, 3, 4):
            raise ValueError('Unexpected metadata state')
        if valid and (sequence >= 0xfffffff0 or (state in (0, 1) and not allow_pending)):
            raise ValueError('Pending or wrapped metadata requires reconciliation')
        result.append(dict(bank=bank, sequence=sequence, state=state, crc_valid=valid,
                           slot=(sequence - 1) % 2))
    return result


def baseline_bank_confirmed(data):
    row = entries(data, allow_pending=True)[1]
    return row['crc_valid'] and row['state'] == 2 and row['slot'] == 1


def selection(data):
    """New sector0 selecting ota_0 as NEW; bank1 (confirmed ota_1) is kept."""
    rows = entries(data)
    valid = [x for x in rows if x['crc_valid'] and x['state'] == 2]
    if not valid or max(valid, key=lambda x: x['sequence'])['slot'] != 1:
        raise ValueError('Confirmed ota_1 baseline must be active')
    baseline = max(valid, key=lambda x: x['sequence'])
    if baseline['bank'] != 1:
        raise ValueError('Unexpected metadata bank arrangement')
    seq = max(x['sequence'] for x in rows if x['crc_valid']) + 1
    if seq % 2 == 0:
        seq += 1
    if seq >= 0xfffffff0:
        raise ValueError('Sequence too close to wrap')
    sector = bytearray(data[:SECTOR])
    sector[:32] = b'\xff' * 32
    struct.pack_into('<I', sector, 0, seq)
    struct.pack_into('<II', sector, 24, 0, binascii.crc32(sector[:4], 0xffffffff))
    return bytes(sector), seq


def candidate(path):
    image = Path(path).read_bytes()
    if len(image) != N3A_SIZE or sha(image) != N3A:
        raise ValueError('Image is not the exact pinned N3a build')
    if image[0] != 0xe9 or image[48:80].split(b'\0')[0] != N3A_VERSION:
        raise ValueError('Unexpected app descriptor')
    return image


def check_review(path):
    review = json.loads(Path(path).read_text())
    if (review.get('verdict') != 'PASS' or review.get('status') != 'terminal_pass' or
            review.get('script_sha256') != sha(Path(__file__).read_bytes()) or
            review.get('firmware_sha256') != N3A):
        raise ValueError('Exact procedure/firmware review missing')


def check_offer_gate(path):
    # Read-only receipt prepared by the orchestrator: the Core-only offer can
    # point at the exact signed N3a. No dual-gateway download gate here.
    gate = json.loads(Path(path).read_text())
    if (gate.get('status') != 'ready' or gate.get('sha256') != N3A or
            gate.get('size') != N3A_SIZE or gate.get('signature_verified') is not True or
            gate.get('device_id') != DEVICE_ID):
        raise ValueError('Exact N3a offer gate missing')


def check_services():
    soak = json.loads((ROOT / 'evidence/sagwa-v2/soak-docker.json').read_text())
    if soak.get('status') == 'running':
        raise ValueError('Stability window running; no USB intervention')
    if subprocess.run(['launchctl', 'print', f'gui/{os.getuid()}/ai.agentshell.sagwa-docker-soak'],
                      capture_output=True).returncode == 0:
        raise ValueError('Own soak supervisor remains registered')


def check_backups():
    acquisitions = json.loads((ROOT / 'evidence/sagwa-v2/physical-flash-reads.json').read_text())
    reads = acquisitions.get('reads', [])
    if acquisitions.get('status') != 'matching_reads' or len(reads) != 2:
        raise ValueError('Two preserved physical backups required')
    for backup in reads:
        data = Path(backup['path']).read_bytes()
        if len(data) != 16 * 1024 * 1024 or sha(data) != backup['sha256']:
            raise ValueError('Physical backup differs')
    if reads[0]['sha256'] != reads[1]['sha256']:
        raise ValueError('Physical backups do not match')
    return Path(reads[0]['path']).read_bytes()


def private_dir():
    return ROOT / '.private/edge-hardware'


def load_checkpoint(path):
    """Validate an offline rollback checkpoint before any USB access."""
    path = Path(path).resolve()
    checkpoint = json.loads(path.read_text())
    directory = Path(checkpoint['directory']).resolve()
    if (directory.parent != private_dir().resolve() or not directory.name.startswith('physical-n3a-')
            or path != directory / 'checkpoint.json'):
        raise ValueError('Checkpoint outside private N3a trial directory')
    if checkpoint.get('baseline_sha256') != BASELINE or checkpoint.get('candidate_sha256') != N3A:
        raise ValueError('Checkpoint for another baseline/candidate')
    files = {}
    for name in PROTECTED_FILES:
        data = (directory / name).read_bytes()
        if sha(data) != checkpoint['files'].get(name):
            raise ValueError(f'Checkpoint file changed: {name}')
        files[name] = data
    selection(files['metadata-before.bin'])  # original confirmed baseline in bank1
    return checkpoint, files


def private_file(path, data):
    path.write_bytes(data)
    path.chmod(0o600)


def capture_console(port, path, seconds=CAPTURE_SECONDS):
    # The official reader handles disconnect/re-enumeration with reset=False.
    from esp_idf_monitor.base.serial_reader import SerialReader
    events = queue.Queue()
    reader = SerialReader(port, events, reset=False, open_port_attempts=1, target='esp32s3')
    reader.start()
    started = time.monotonic()
    edge_at = None
    buffer = b''
    elapsed = 0.0
    try:
        with path.open('wb') as out:
            while True:
                elapsed = time.monotonic() - started
                if elapsed >= seconds:
                    break
                try:
                    _, data = events.get(timeout=.25)
                except queue.Empty:
                    if not reader.alive:
                        break
                    continue
                if isinstance(data, bytes):
                    out.write(data)
                    out.flush()
                    buffer += data
                    if edge_at is None and re.search(rb'App version:\s+0\.3\.0-dev', buffer):
                        edge_at = time.monotonic() - started
        alive = bool(reader.alive) and elapsed >= seconds
    finally:
        reader.stop()
    return summarize(path.read_bytes(), elapsed, alive, edge_at)


def summarize(raw, elapsed, alive, edge_at):
    text = raw.decode('utf-8', 'replace')
    return {'bytes': len(raw), 'capture_s': round(elapsed, 3), 'alive_until_end': alive,
            'edge_boot_seen': bool(re.search(r'App version:\s+0\.3\.0-dev', text)),
            'edge_boot_count': len(re.findall(r'App version:\s+0\.3\.0-dev', text)),
            'edge_boot_at_s': None if edge_at is None else round(edge_at, 3),
            'baseline_boot_seen': bool(re.search(r'App version:\s+0\.2\.0', text)),
            'panic_seen': bool(re.search(r'Guru Meditation|assert failed|abort\(\)|panic', text, re.I)),
            'backtrace_seen': 'Backtrace:' in text,
            'scope': 'Console observation only; excludes human LCD/audio/gesture acceptance'}


def validated_on_console(trace):
    """Conservative: one N3a boot, nothing else, observed past the 30 s check."""
    return (trace.get('edge_boot_seen') is True and trace.get('edge_boot_count') == 1 and
            not trace.get('panic_seen') and not trace.get('backtrace_seen') and
            not trace.get('baseline_boot_seen') and trace.get('alive_until_end') is True and
            trace.get('edge_boot_at_s') is not None and
            trace['capture_s'] - trace['edge_boot_at_s'] >= VALIDATION_MARGIN_S)


def offer_image(digest):
    # Core-only firmware offer through the Mac admin API, changed only while
    # ROM/stub owns the device so the running app cannot act on it meanwhile.
    from admin import request
    result = request('/v1/firmware/offer', 'POST', {'device_id': DEVICE_ID, 'sha256': digest})
    if result.get('ok') is not True:
        raise RuntimeError('Firmware offer not acknowledged')


def restore_baseline_offer(receipt):
    # Best effort: an unreachable admin server never blocks the local return.
    try:
        offer_image(BASELINE)
        receipt['baseline_offer_acknowledged'] = True
    except Exception as error:
        receipt.update(baseline_offer_acknowledged=False,
                       baseline_offer_error_type=type(error).__name__)


def connect_download(cmds, port):
    esp = cmds.detect_chip(port, connect_attempts=3)
    if (esp.CHIP_NAME != 'ESP32-S3' or bytes(esp.read_mac()).hex() != MAC or
            esp.get_flash_encryption_enabled() or esp.get_secure_boot_enabled() or
            esp.secure_download_mode):
        with contextlib.suppress(Exception):
            esp._port.close()
        raise ValueError('Device identity/security differs')
    esp = cmds.run_stub(esp)
    if ((esp.flash_id() >> 16) & 0xff) != 24:
        with contextlib.suppress(Exception):
            esp._port.close()
        raise ValueError('Expected 16MiB flash')
    return esp


def safe_close(esp, receipt):
    if esp is None:
        return
    try:
        esp._port.close()
    except Exception as error:
        receipt.setdefault('close_errors', []).append(type(error).__name__)


def plan(a):
    return {'operation': a.operation, 'usb_opened': False,
            'app_write_offset': APP0 if a.operation == 'apply' else None,
            'metadata_write_offset': OTADATA, 'metadata_write_size': SECTOR,
            'leave_installed': bool(a.leave_installed),
            'capture_seconds': CAPTURE_SECONDS if a.leave_installed else 95,
            'usb_reopened_after_validated_boot': False if a.leave_installed else True,
            'efuse_writes': False, 'partition_table_writes': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('operation', choices=['apply', 'rollback'])
    p.add_argument('--port', required=True)
    p.add_argument('--image', type=Path, default=DEFAULT_IMAGE)
    p.add_argument('--review', type=Path, help='terminal_pass review of this script and image')
    p.add_argument('--offer-gate', type=Path, help='read-only exact N3a offer receipt')
    p.add_argument('--checkpoint', type=Path, help='private checkpoint.json for rollback')
    p.add_argument('--leave-installed', action='store_true',
                   help='authorized: keep N3a selected after a console-validated boot')
    p.add_argument('--execute', action='store_true')
    a = p.parse_args(argv)
    if a.operation == 'rollback':
        if a.leave_installed:
            p.error('--leave-installed applies only to apply')
        if not a.checkpoint:
            p.error('--checkpoint required for rollback')
        checkpoint, saved = load_checkpoint(a.checkpoint)
        image = None
    else:
        image = candidate(a.image)
    if not a.execute:
        print(json.dumps(plan(a), indent=2))
        return 0
    if a.operation == 'apply':
        if not a.review or not a.offer_gate:
            p.error('--review and --offer-gate required for apply --execute')
        check_review(a.review)
        check_offer_gate(a.offer_gate)
        check_services()
    backup = check_backups()
    from esptool import cmds
    os.umask(0o077)
    directory = Path(tempfile.mkdtemp(prefix='physical-n3a-', dir=private_dir()))
    receipt = {'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'operation': a.operation, 'candidate_sha256': N3A, 'baseline_sha256': BASELINE,
               'script_sha256': sha(Path(__file__).read_bytes()),
               'leave_installed_requested': bool(a.leave_installed),
               'private_directory': str(directory), 'writes': [], 'status': 'started',
               'efuses_written': False, 'partition_table_written': False,
               'product_acceptance': False}
    esp = None
    metadata_started = reset_started = False
    before = recovery_sector = None
    try:
        with (directory / 'operations.log').open('w') as log, \
                contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            esp = connect_download(cmds, a.port)

            def read(offset, size, name):
                file = directory / name
                cmds.read_flash(esp, offset, size, output=str(file), flash_size='16MB', no_progress=True)
                file.chmod(0o600)
                data = file.read_bytes()
                if len(data) != size:
                    raise ValueError('Incomplete physical read')
                return data

            boot = read(*BOOT, 'boot-before.bin')
            table = read(*TABLE, 'table-before.bin')
            if sha(boot) != BOOT_SHA or table != backup[TABLE[0]:TABLE[0] + TABLE[1]]:
                raise ValueError('Boot/table changed since audited backups')
            if sha(read(BASELINE_OFFSET, BASELINE_SIZE, 'baseline-before.bin')) != BASELINE:
                raise ValueError('ota_1 baseline changed')
            provision = read(*NVS, 'nvs-before.bin')
            before = read(OTADATA, 2 * SECTOR, 'metadata-before.bin')
            if a.operation == 'apply':
                sector, seq = selection(before)
                # Checkpoint first: rollback must work even if the offer or a
                # later step fails. It records hashes of the protected reads.
                checkpoint = {'directory': str(directory), 'sequence': seq,
                              'baseline_sha256': BASELINE, 'candidate_sha256': N3A,
                              'files': {n: sha((directory / n).read_bytes()) for n in PROTECTED_FILES}}
                private_file(directory / 'checkpoint.json', (json.dumps(checkpoint, indent=2) + '\n').encode())
                receipt['checkpoint'] = str(directory / 'checkpoint.json')
                offer_image(N3A)  # no write has happened if this fails
                receipt['self_offer_acknowledged'] = True
                inactive = read(APP0, APP_SLOT, 'inactive-before.bin')
                if inactive[:len(image)] != image:
                    cmds.write_flash(esp, [(APP0, image)], no_progress=True, compress=True)
                    receipt['writes'].append({'offset': APP0, 'size': len(image)})
                else:
                    receipt['candidate_already_exact'] = True
                if sha(read(APP0, len(image), 'candidate-after.bin')) != N3A:
                    raise ValueError('Candidate read-back differs; selection unchanged')
                recovery_sector = before[:SECTOR]
            else:
                if provision != saved['nvs-before.bin'] or boot != saved['boot-before.bin'] or \
                        table != saved['table-before.bin']:
                    raise ValueError('Protected bytes differ from checkpoint')
                if not baseline_bank_confirmed(before):
                    raise ValueError('Rollback baseline record unavailable')
                original = saved['metadata-before.bin']
                sector = original[:SECTOR]
                target = entries(original)[0]
                if target['crc_valid'] and target['state'] == 2 and \
                        target['sequence'] >= entries(before, allow_pending=True)[1]['sequence']:
                    raise ValueError('Restore sector could override confirmed baseline')
                recovery_sector = sector
            # Only sector0 is written; confirmed bank1 survives an interrupted write.
            metadata_started = True
            cmds.write_flash(esp, [(OTADATA, sector)], no_progress=True, compress=True)
            receipt['writes'].append({'offset': OTADATA, 'size': SECTOR})
            if read(OTADATA, 2 * SECTOR, 'metadata-after.bin') != sector + before[SECTOR:]:
                raise ValueError('Metadata read-back differs')
            if read(*BOOT, 'boot-after.bin') != boot or read(*TABLE, 'table-after.bin') != table:
                raise ValueError('Protected boot/table bytes changed')
            if read(*NVS, 'nvs-after.bin') != provision or \
                    sha(read(BASELINE_OFFSET, BASELINE_SIZE, 'baseline-after.bin')) != BASELINE:
                raise ValueError('Protected provisioning/baseline changed')
            receipt['read_back_verified'] = True
            if a.operation == 'rollback':
                selection(read(OTADATA, 2 * SECTOR, 'metadata-returned.bin'))
                restore_baseline_offer(receipt)
                reset_started = True
                cmds.reset_chip(esp, 'hard-reset')
                trace = capture_console(esp._port, directory / 'baseline-boot-capture.log',
                                        seconds=BASELINE_CAPTURE_SECONDS)
                receipt['baseline_console'] = trace
                receipt['baseline_selection_restored'] = True
                seen = trace['baseline_boot_seen'] and not trace['panic_seen']
                receipt['status'] = 'returned_baseline' if seen else 'returned_baseline_boot_unobserved'
                return 0
            # Keep the existing USB session open across the only reset:
            # opening another monitor while PENDING_VERIFY resets again.
            reset_started = True
            cmds.reset_chip(esp, 'hard-reset')
            trace = capture_console(esp._port, directory / 'boot-capture.log',
                                    seconds=CAPTURE_SECONDS if a.leave_installed else 95)
            receipt['console'] = trace
            if a.leave_installed and validated_on_console(trace):
                safe_close(esp, receipt)
                esp = None
                receipt.update(status='installed_left_for_manual_trial',
                               usb_reopened_after_success=False,
                               installed_scope='Console-observed boot past the 30 s self-check; '
                                               'otadata VALID not read back to avoid a USB reset')
                return 0
            # Diagnostic run, or N3a not validated: return the baseline selection.
            safe_close(esp, receipt)
            esp = None
            esp = connect_download(cmds, a.port)  # new ROM/stub, never the app fd
            observed = read(OTADATA, 2 * SECTOR, 'metadata-after-observation.bin')
            receipt['metadata_after_download_reentry'] = entries(observed, allow_pending=True)
            if not baseline_bank_confirmed(observed) or \
                    sha(read(BASELINE_OFFSET, BASELINE_SIZE, 'baseline-after-observation.bin')) != BASELINE:
                raise ValueError('Confirmed baseline changed during observation')
            cmds.write_flash(esp, [(OTADATA, before[:SECTOR])], no_progress=True, compress=True)
            receipt['writes'].append({'offset': OTADATA, 'size': SECTOR, 'purpose': 'return_baseline'})
            restored = read(OTADATA, 2 * SECTOR, 'metadata-returned.bin')
            if restored != before[:SECTOR] + observed[SECTOR:]:
                raise ValueError('Baseline selection read-back differs')
            selection(restored)
            receipt['baseline_selection_restored'] = True
            restore_baseline_offer(receipt)
            cmds.reset_chip(esp, 'hard-reset')
            receipt['baseline_console'] = capture_console(
                esp._port, directory / 'baseline-boot-capture.log', seconds=BASELINE_CAPTURE_SECONDS)
            if a.leave_installed:
                receipt['status'] = 'not_validated_returned_baseline'
            else:
                conclusive = trace['edge_boot_seen'] or trace['backtrace_seen']
                receipt['status'] = 'captured_and_restored' if conclusive else 'capture_inconclusive_and_restored'
            return 0
    except BaseException as error:
        receipt.update(status='failed', error_type=type(error).__name__)
        # Never leave an unobserved new selection: restore sector0 only.
        if metadata_started and before is not None:
            try:
                with (directory / 'recovery.log').open('w') as log, \
                        contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    if reset_started or esp is None:
                        safe_close(esp, receipt)
                        esp = None
                        esp = connect_download(cmds, a.port)
                    live_file = directory / 'metadata-recovery-before.bin'
                    cmds.read_flash(esp, OTADATA, 2 * SECTOR, output=str(live_file),
                                    flash_size='16MB', no_progress=True)
                    live = live_file.read_bytes()
                    base_file = directory / 'baseline-recovery.bin'
                    cmds.read_flash(esp, BASELINE_OFFSET, BASELINE_SIZE, output=str(base_file),
                                    flash_size='16MB', no_progress=True)
                    if not baseline_bank_confirmed(live) or sha(base_file.read_bytes()) != BASELINE:
                        raise ValueError('Recovery baseline not confirmed')
                    cmds.write_flash(esp, [(OTADATA, recovery_sector)], no_progress=True, compress=True)
                    done_file = directory / 'metadata-recovered.bin'
                    cmds.read_flash(esp, OTADATA, 2 * SECTOR, output=str(done_file),
                                    flash_size='16MB', no_progress=True)
                    restored = done_file.read_bytes()
                    if restored != recovery_sector + live[SECTOR:]:
                        raise ValueError('Recovery read-back differs')
                    selection(restored)
                    receipt['metadata_recovered'] = True
                    restore_baseline_offer(receipt)
                    cmds.reset_chip(esp, 'hard-reset')
            except BaseException as recovery:
                receipt.update(metadata_recovered=False, recovery_error_type=type(recovery).__name__)
        if receipt.get('self_offer_acknowledged') and 'baseline_offer_acknowledged' not in receipt:
            restore_baseline_offer(receipt)
        raise
    finally:
        # A close error must never prevent the durable recovery receipt.
        safe_close(esp, receipt)
        receipt['ended_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        path = ROOT / 'evidence/sagwa-v2' / f'physical-n3a-{a.operation}-{directory.name}.json'
        path.write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    sys.exit(main())
