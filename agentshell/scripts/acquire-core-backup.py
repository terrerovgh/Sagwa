"""Two physical flash reads in one ROM/stub session. Never writes flash/eFuses.

Run with the ESP-IDF Python environment. Default is a plan without opening USB.
The containing directory and binary/log files are private: flash has credentials.
"""
import argparse
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MAC = '80456b4d5f7c'
FLASH_SIZE = 16 * 1024 * 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    review = json.loads(args.review.read_text())
    candidate_sha = hashlib.sha256(args.candidate.read_bytes()).hexdigest()
    if review.get('status') != 'terminal_pass' or review.get('verdict') != 'PASS':
        raise SystemExit('Candidate independent review has not passed')
    if candidate_sha != review.get('firmware_sha256'):
        raise SystemExit('Candidate differs from the reviewed image')
    plan = dict(port=args.port, expected_mac=EXPECTED_MAC, bytes_per_read=FLASH_SIZE,
                reads=2, reset_between_reads=False, flash_writes=False,
                efuse_writes=False, execute=args.execute)
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return
    # The deliberate reset must not be counted as a valid uninterrupted soak.
    soak = json.loads((ROOT / 'evidence/sagwa-v2/soak-docker.json').read_text())
    if soak.get('status') != 'interrupted' or not soak.get('interrupted_at'):
        raise SystemExit('Preserve and mark the previous soak interrupted first')
    label = f'gui/{os.getuid()}/ai.agentshell.sagwa-docker-soak'
    if subprocess.run(['launchctl', 'print', label], capture_output=True).returncode == 0:
        raise SystemExit('Own soak supervisor remains registered: stop it first')
    from esptool import cmds
    private = ROOT / '.private/edge-hardware'
    private.mkdir(mode=0o700, exist_ok=True)
    if private.is_symlink() or private.stat().st_uid != os.getuid():
        raise SystemExit('Invalid private backup directory')
    os.chmod(private, 0o700)
    directory = Path(tempfile.mkdtemp(prefix='flash-', dir=private))
    os.umask(0o077)
    receipt = {**plan, 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'private_directory': str(directory), 'status': 'started', 'reads': [],
               'deployment_approved': False}
    esp = None
    try:
        with (directory / 'acquisition.log').open('w') as log, \
                contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                esp = cmds.detect_chip(args.port, connect_attempts=3)
                if esp.CHIP_NAME != 'ESP32-S3':
                    raise RuntimeError('Unexpected chip; no flash read')
                mac = bytes(esp.read_mac()).hex()
                if mac != EXPECTED_MAC:
                    raise RuntimeError('Unexpected device identity; no flash read')
                encrypted = esp.get_flash_encryption_enabled()
                secure_boot = esp.get_secure_boot_enabled()
                receipt.update(mac=mac, chip=esp.CHIP_NAME,
                               flash_encryption=encrypted, secure_boot=secure_boot)
                if encrypted or secure_boot or esp.secure_download_mode:
                    raise RuntimeError('Protected flash needs a separate recovery procedure')
                esp = cmds.run_stub(esp)
                if ((esp.flash_id() >> 16) & 0xff) != 24:
                    raise RuntimeError('Unexpected flash capacity; no flash read')
                for index in (1, 2):
                    target = directory / f'flash-read-{index}.bin'
                    start = time.monotonic()
                    cmds.read_flash(esp, 0, FLASH_SIZE, output=str(target),
                                    flash_size='16MB', no_progress=True)
                    os.chmod(target, 0o600)
                    if target.stat().st_size != FLASH_SIZE:
                        raise RuntimeError('Incomplete flash read')
                    receipt['reads'].append(dict(path=str(target), bytes=FLASH_SIZE,
                        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                        seconds=round(time.monotonic() - start, 3)))
                if receipt['reads'][0]['sha256'] != receipt['reads'][1]['sha256']:
                    raise RuntimeError('Flash reads differ; do not deploy')
                receipt['status'] = 'matching_reads'
            finally:
                if esp is not None:
                    try:
                        cmds.reset_chip(esp, 'hard-reset')
                        receipt['return_to_application_reset'] = True
                    finally:
                        esp._port.close()
    except Exception as error:
        receipt.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        receipt['ended_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        path = ROOT / 'evidence/sagwa-v2/physical-flash-reads.json'
        path.write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
