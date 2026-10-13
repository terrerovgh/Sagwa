"""Explicit app-only USB trial. Default prints a plan and never opens USB.

Writes only inactive ota_0 and its single OTA metadata sector. Confirmed ota_1,
the other metadata sector, bootloader, table, NVS and storage remain untouched.
The serial port stays open after reset to capture a pending-image failure without
an extra USB-open reset. Run with ESP-IDF's Python environment.
"""
import argparse
import base64
import binascii
import contextlib
import datetime
import hashlib
import json
import os
import queue
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SHA = 'c3a7070992e711a3a6fa3937ff93b2f232a1a80bae89db723b9d356e09f8c43a'
BASELINE = '88e9c70d2b1f521c48f928e146aa442a94b403ddb6227f94db2043fa3a9231ba'
MAC = '80456b4d5f7c'
BOOT_SHA = '2c7782c7fbcc14e36998ff1a622827d354d3a97ea78596d24351e356e4ea6674'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def verified_device_downloads(published, image_size):
    # Apply requires the actual device-certificate readbacks at BOTH gateways.
    # Rollback remains available offline and never calls this gate.
    if published.get('both_downloads_verified') is not True:
        raise ValueError('Both device-certificate downloads remain unverified')
    for release in published.get('releases', []):
        manifest = release.get('manifest', {})
        if (manifest.get('sha256') != SHA or manifest.get('size') != image_size or
                release.get('signature_verified') is not True):
            continue
        origin = urlsplit(manifest.get('url', ''))
        if origin.scheme != 'https' or origin.username or origin.password:
            continue
        expected = {'https://' + origin.netloc, 'https://100.65.98.90:9443'}
        verified = {row.get('gateway') for row in release.get('device_certificate_downloads', [])
                    if type(row.get('status')) is int and row['status'] == 200 and
                    row.get('bytes') == image_size and row.get('sha_matches') is True}
        if len(expected) == 2 and expected <= verified:
            return
    raise ValueError('Distinct gateway readbacks for the exact signed image required')

def entries(data, allow_pending=False):
    if len(data) != 8192:
        raise ValueError('Expected two complete metadata sectors')
    result = []
    for bank in (0, 1):
        entry = data[bank * 4096:bank * 4096 + 32]
        sequence, = struct.unpack_from('<I', entry)
        state, crc = struct.unpack_from('<II', entry, 24)
        valid = sequence not in (0, 0xffffffff) and crc == binascii.crc32(entry[:4], 0xffffffff)
        if valid and state not in (0,1,2,3,4):
            raise ValueError('Unexpected metadata state')
        if valid and (sequence >= 0xfffffff0 or (state in (0, 1) and not allow_pending)):
            raise ValueError('Pending or wrapped metadata requires reconciliation')
        result.append(dict(bank=bank, sequence=sequence, state=state, crc_valid=valid,
                           slot=(sequence - 1) % 2))
    return result

def selection(data):
    rows = entries(data)
    valid = [x for x in rows if x['crc_valid'] and x['state'] == 2]
    if not valid or max(valid, key=lambda x: x['sequence'])['slot'] != 1:
        raise ValueError('Confirmed ota_1 baseline must be active')
    baseline = max(valid, key=lambda x: x['sequence'])
    target = 1 - baseline['bank']
    # With this device's layout, ota_1 must be represented in bank1. This narrow
    # trial refuses other arrangements rather than guessing a recovery sector.
    if baseline['bank'] != 1 or target != 0:
        raise ValueError('Unexpected metadata bank arrangement')
    seq = max(x['sequence'] for x in rows if x['crc_valid']) + 1
    if seq % 2 == 0:
        seq += 1
    if seq >= 0xfffffff0:
        raise ValueError('Sequence too close to wrap')
    sector = bytearray(data[:4096])
    sector[:32] = b'\xff' * 32
    struct.pack_into('<I', sector, 0, seq)
    # NEW -> PENDING_VERIFY -> VALID/ABORTED is implemented by the installed
    # rollback-capable bootloader; the older confirmed sector is not erased.
    struct.pack_into('<II', sector, 24, 0, binascii.crc32(sector[:4], 0xffffffff))
    return bytes(sector), seq

def signed_candidate():
    image = (ROOT / 'evidence/sagwa-v2/sagwa-edge-candidate-j.bin').read_bytes()
    receipt = json.loads((ROOT / 'edge-firmware/review-product-j.json').read_text())
    if receipt.get('verdict') != 'PASS' or sha(image) != SHA or receipt['firmware_sha256'] != SHA:
        raise ValueError('Candidate no longer equals static-reviewed J')
    published = json.loads((ROOT / 'evidence/sagwa-v2/edge-release-j-published-verified.json').read_text())
    if not any(x['manifest']['sha256'] == SHA and x['signature_verified'] for x in published['releases']):
        raise ValueError('Verified signed release missing')
    if len(image) != 2290160 or image[0] != 0xe9 or image[48:80].split(b'\0')[0] != b'0.3.0-dev':
        raise ValueError('Unexpected app descriptor')
    signed = json.loads((ROOT / 'evidence/sagwa-v2/edge-signed-release-j-prepared.json').read_text())
    manifest = json.loads(signed['manifest'])
    if manifest['sha256'] != SHA or manifest['size'] != len(image) or manifest['version'] != '0.3.0-dev' or manifest['target'] != 'esp32s3':
        raise ValueError('Signed manifest differs from candidate')
    with tempfile.TemporaryDirectory() as folder:
        m=Path(folder)/'manifest';m.write_text(signed['manifest'])
        s=Path(folder)/'signature';s.write_bytes(base64.b64decode(signed['signature'],validate=True))
        subprocess.run(['openssl','dgst','-sha256','-verify',str(ROOT/'edge-firmware/components/agentshell_ota/release-public.pem'),'-signature',str(s),str(m)],capture_output=True,check=True)
    return image

def private_file(path, data):
    path.write_bytes(data)
    path.chmod(0o600)

def capture_console(port,path,seconds=95):
    # The official reader handles disconnect/re-enumeration using reset=False,
    # including the correct DTR/RTS open order. Plain pyserial is insufficient.
    from esp_idf_monitor.base.serial_reader import SerialReader
    events=queue.Queue();reader=SerialReader(port,events,reset=False,open_port_attempts=1,target='esp32s3')
    reader.start();started=time.monotonic()
    try:
        with path.open('wb') as out:
            while time.monotonic()-started<seconds:
                try:tag,data=events.get(timeout=.25)
                except queue.Empty:
                    if not reader.alive:break
                    continue
                if isinstance(data,bytes):out.write(data);out.flush()
    finally:
        reader.stop()
    text=path.read_bytes().decode('utf-8','replace')
    return {'bytes':path.stat().st_size,
            'edge_boot_seen':bool(re.search(r'App version:\s+0\.3\.0-dev',text)),
            'baseline_boot_seen':bool(re.search(r'App version:\s+0\.2\.0',text)),
            'panic_seen':bool(re.search(r'Guru Meditation|assert failed|abort\(\)|panic',text,re.I)),
            'backtrace_seen':'Backtrace:' in text,
            'scope':'Console observation only; excludes human LCD/audio/gesture acceptance'}

def offer_image(digest):
    # Only the already-reviewed Core's own firmware offer changes. The running
    # F image must see its own offer during the debug window, not an automatic
    # baseline OTA that could write ota_1 while we preserve that slot.
    from admin import request
    result=request('/v1/firmware/offer','POST',{'device_id':'device:cores3-80456b4d5f7c','sha256':digest})
    if result.get('ok') is not True:raise RuntimeError('Firmware offer not acknowledged')

def connect_download(cmds,port):
    esp=cmds.detect_chip(port,connect_attempts=3)
    if esp.CHIP_NAME!='ESP32-S3' or bytes(esp.read_mac()).hex()!=MAC or esp.get_flash_encryption_enabled() or esp.get_secure_boot_enabled() or esp.secure_download_mode:
        try:esp._port.close()
        except Exception:pass
        raise ValueError('Device identity/security differs')
    esp=cmds.run_stub(esp)
    if ((esp.flash_id()>>16)&0xff)!=24:
        try:esp._port.close()
        except Exception:pass
        raise ValueError('Expected16MiB flash')
    return esp

def safe_close(esp,receipt):
    if esp is None:return
    try:esp._port.close()
    except Exception as error:receipt.setdefault('close_errors',[]).append(type(error).__name__)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['apply', 'rollback'])
    p.add_argument('--port', required=True)
    p.add_argument('--review', type=Path)
    p.add_argument('--checkpoint', type=Path)
    p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    image = signed_candidate()
    if a.operation == 'rollback' and not a.checkpoint:
        p.error('--checkpoint required for rollback')
    if not a.execute:
        print(json.dumps({'operation':a.operation, 'usb_opened':False, 'app_write_offset':0x20000 if a.operation=='apply' else None,
                          'metadata_write_offset':0x1d000, 'metadata_write_size':4096, 'efuse_writes':False}, indent=2))
        return
    if not a.review:
        p.error('--review required for execute')
    review = json.loads(a.review.read_text())
    if review.get('verdict') != 'PASS' or review.get('status') != 'terminal_pass' or review.get('script_sha256') != sha(Path(__file__).read_bytes()):
        raise ValueError('Exact physical procedure review missing')
    if a.operation == 'apply':
        verified_device_downloads(json.loads((ROOT / 'evidence/sagwa-v2/edge-release-j-published-verified.json').read_text()), len(image))
    soak = json.loads((ROOT / 'evidence/sagwa-v2/soak-docker.json').read_text())
    if soak.get('status') != 'interrupted':
        raise ValueError('Preserve interrupted soak before USB intervention')
    if subprocess.run(['launchctl','print',f'gui/{os.getuid()}/ai.agentshell.sagwa-docker-soak'],capture_output=True).returncode == 0:
        raise ValueError('Own soak supervisor remains registered')
    acquisitions = json.loads((ROOT / 'evidence/sagwa-v2/physical-flash-reads.json').read_text())
    if acquisitions.get('status') != 'matching_reads' or len(acquisitions.get('reads',[])) != 2:
        raise ValueError('Two preserved physical backups required')
    for backup in acquisitions['reads']:
        file = Path(backup['path'])
        if file.stat().st_size != 16*1024*1024 or sha(file.read_bytes()) != backup['sha256']:
            raise ValueError('Physical backup differs')
    if acquisitions['reads'][0]['sha256'] != acquisitions['reads'][1]['sha256']:
        raise ValueError('Physical backups do not match')
    from esptool import cmds
    os.umask(0o077)
    private = ROOT / '.private/edge-hardware'
    directory = Path(tempfile.mkdtemp(prefix='physical-trial-',dir=private))
    receipt = {'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'operation':a.operation,
               'candidate_sha256':SHA,'private_directory':str(directory),'writes':[], 'status':'started',
               'efuses_written':False,'partition_table_written':False,'product_acceptance':False}
    esp = None
    metadata_started=False
    reset_started=False
    before=None
    recovery_sector=None
    try:
        with (directory/'operations.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            esp = connect_download(cmds,a.port)
            def read(offset,size,name):
                file=directory/name
                cmds.read_flash(esp,offset,size,output=str(file),flash_size='16MB',no_progress=True)
                file.chmod(0o600)
                data=file.read_bytes()
                if len(data)!=size:raise ValueError('Incomplete physical read')
                return data
            boot = read(0,0x10000,'boot-before.bin')
            table = read(0x10000,0x1000,'table-before.bin')
            backup = Path(acquisitions['reads'][0]['path']).read_bytes()
            if sha(boot)!=BOOT_SHA or table!=backup[0x10000:0x11000]:
                raise ValueError('Boot/table changed since audited backups')
            baseline = read(0x420000,2797472,'baseline-before.bin')
            if sha(baseline)!=BASELINE:
                raise ValueError('ota_1 baseline changed')
            provision = read(0x11000,0xc000,'nvs-before.bin')
            before = read(0x1d000,8192,'metadata-before.bin')
            if a.operation=='apply':
                sector, seq = selection(before)
                offer_image(SHA) # ROM/stub owns device; G will skip its own offer.
                receipt['self_offer_acknowledged']=True
                inactive=read(0x20000,0x400000,'inactive-before.bin')
                checkpoint={'directory':str(directory),'sequence':seq,'baseline_sha256':BASELINE,'candidate_sha256':SHA}
                private_file(directory/'checkpoint.json',(json.dumps(checkpoint,indent=2)+'\n').encode())
                receipt['checkpoint']=str(directory/'checkpoint.json')
                if inactive[:len(image)]!=image:
                    cmds.write_flash(esp,[(0x20000,image)],no_progress=True,compress=True)
                    receipt['writes'].append({'offset':0x20000,'size':len(image)})
                else:
                    receipt['candidate_already_exact']=True
                if sha(read(0x20000,len(image),'candidate-after.bin'))!=SHA:
                    raise ValueError('Candidate read-back differs; selection unchanged')
            else:
                checkpoint=json.loads(a.checkpoint.read_text())
                source=Path(checkpoint['directory'])
                if source.parent!=private or not source.name.startswith('physical-trial-'):
                    raise ValueError('Checkpoint outside private trial directory')
                original=(source/'metadata-before.bin').read_bytes()
                selection(original) # original confirmed baseline in bank1
                rows=entries(before,allow_pending=True)
                if not(rows[1]['crc_valid'] and rows[1]['state']==2 and rows[1]['slot']==1):
                    raise ValueError('Rollback baseline record unavailable')
                sector=original[:4096]
                original_target=entries(original)[0]
                if original_target['crc_valid'] and original_target['state']==2 and original_target['sequence']>=rows[1]['sequence']:
                    raise ValueError('Restore sector could override confirmed baseline')
            # Do not erase/write both banks: the confirmed bank1 survives even
            # interrupted metadata-sector0 programming.
            metadata_started=True
            recovery_sector=before[:4096] if a.operation=='apply' else sector
            cmds.write_flash(esp,[(0x1d000,sector)],no_progress=True,compress=True)
            receipt['writes'].append({'offset':0x1d000,'size':4096})
            after=read(0x1d000,8192,'metadata-after.bin')
            if after!=sector+before[4096:]:
                raise ValueError('Metadata read-back differs')
            if read(0,0x10000,'boot-after.bin')!=boot or read(0x10000,0x1000,'table-after.bin')!=table:
                raise ValueError('Protected boot/table bytes changed')
            if read(0x11000,0xc000,'nvs-after.bin')!=provision or sha(read(0x420000,2797472,'baseline-after.bin'))!=BASELINE:
                raise ValueError('Protected provisioning/baseline changed')
            receipt['read_back_verified']=True
            # Keep the exact existing USB session open across the only reset.
            # Opening another monitor while PENDING_VERIFY causes a second reset.
            reset_started=True
            cmds.reset_chip(esp,'hard-reset')
            trace=capture_console(esp._port,directory/'boot-capture.log')
            receipt['console']=trace
            # This is a diagnostic trial: ALWAYS restore the baseline selection,
            # even if G became VALID at30s. Never leave an unaccepted image live.
            safe_close(esp,receipt);esp=None
            esp=connect_download(cmds,a.port) # new ROM/stub, never old application fd
            observed=read(0x1d000,8192,'metadata-after-observation.bin')
            receipt['metadata_after_download_reentry']=entries(observed,allow_pending=True)
            rows=entries(observed,allow_pending=True)
            if not(rows[1]['crc_valid'] and rows[1]['state']==2 and rows[1]['slot']==1) or sha(read(0x420000,2797472,'baseline-after-observation.bin'))!=BASELINE:
                raise ValueError('Confirmed baseline changed during observation')
            restore=before[:4096] if a.operation=='apply' else sector
            cmds.write_flash(esp,[(0x1d000,restore)],no_progress=True,compress=True)
            receipt['writes'].append({'offset':0x1d000,'size':4096,'purpose':'return_baseline'})
            restored=read(0x1d000,8192,'metadata-returned.bin')
            if restored!=restore+observed[4096:]:raise ValueError('Baseline selection read-back differs')
            selection(restored)
            offer_image(BASELINE)
            receipt['baseline_offer_acknowledged']=True
            receipt['baseline_selection_restored']=True
            cmds.reset_chip(esp,'hard-reset')
            receipt['baseline_console']=capture_console(esp._port,directory/'baseline-boot-capture.log',seconds=35)
            conclusive=trace['edge_boot_seen'] or trace['backtrace_seen'] or (a.operation=='rollback' and trace['baseline_boot_seen'])
            receipt['status']='captured_and_restored' if conclusive else 'capture_inconclusive_and_restored'
    except BaseException as error:
        receipt.update(status='failed',error_type=type(error).__name__)
        # A write failure must not leave an unobserved new boot selection.
        # Restore only sector0, retaining the confirmed baseline sector1.
        if metadata_started and before is not None:
            try:
                with (directory/'recovery.log').open('w') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
                    if reset_started or esp is None:
                        safe_close(esp,receipt);esp=None
                        esp=connect_download(cmds,a.port)
                    live=read(0x1d000,8192,'metadata-recovery-before.bin')
                    rows=entries(live,allow_pending=True)
                    if not(rows[1]['crc_valid'] and rows[1]['state']==2 and rows[1]['slot']==1) or sha(read(0x420000,2797472,'baseline-recovery.bin'))!=BASELINE:
                        raise ValueError('Recovery baseline not confirmed')
                    cmds.write_flash(esp,[(0x1d000,recovery_sector)],no_progress=True,compress=True)
                    cmds.read_flash(esp,0x1d000,8192,output=str(directory/'metadata-recovered.bin'),flash_size='16MB',no_progress=True)
                    restored=(directory/'metadata-recovered.bin').read_bytes()
                    if restored!=recovery_sector+live[4096:]:
                        raise ValueError('Recovery read-back differs')
                    selection(restored)
                    receipt['metadata_recovered']=True
                    offer_image(BASELINE)
                    receipt['baseline_offer_acknowledged']=True
                    cmds.reset_chip(esp,'hard-reset')
            except BaseException as recovery:
                receipt.update(metadata_recovered=False,recovery_error_type=type(recovery).__name__)
        if receipt.get('self_offer_acknowledged') and not receipt.get('baseline_offer_acknowledged'):
            try:
                offer_image(BASELINE)
                receipt['baseline_offer_acknowledged']=True
            except Exception as control:
                receipt.update(baseline_offer_acknowledged=False,control_restore_error_type=type(control).__name__)
        raise
    finally:
        # A close error must never prevent the durable recovery receipt.
        safe_close(esp,receipt)
        receipt['ended_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        path=ROOT/'evidence/sagwa-v2'/('physical-edge-'+a.operation+'-'+directory.name+'.json')
        path.write_text(json.dumps(receipt,indent=2)+'\n')
        print(json.dumps(receipt,indent=2))

if __name__=='__main__':main()
