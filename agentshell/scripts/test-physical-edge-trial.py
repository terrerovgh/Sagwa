"""Selection and power-interruption checks; never imports USB or opens a device."""
import binascii
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import json
import contextlib
import io

spec=importlib.util.spec_from_file_location('physical',Path(__file__).with_name('physical-edge-trial.py'))
trial=importlib.util.module_from_spec(spec);spec.loader.exec_module(trial)

def record(seq,state):
    data=bytearray(b'\xff'*4096)
    struct.pack_into('<I',data,0,seq)
    struct.pack_into('<II',data,24,state,binascii.crc32(data[:4],0xffffffff))
    return bytes(data)

def selected(data):
    rows=trial.entries(data,allow_pending=True)
    rows=[x for x in rows if x['crc_valid'] and x['state'] not in (3,4)]
    return max(rows,key=lambda x:x['sequence'])['slot'] if rows else None

class PhysicalTrial(unittest.TestCase):
    def test_actual_missing_tuf_readback_blocks_apply(self):
        published=json.loads((trial.ROOT/'evidence/sagwa-v2/edge-release-j-published-verified-missing-tuf.json').read_text())
        with self.assertRaisesRegex(ValueError,'unverified'):
            trial.verified_device_downloads(published,2290160)

    def test_two_distinct_exact_device_readbacks_required(self):
        from copy import deepcopy
        mac={'gateway':'https://192.168.4.82:9443','status':200,'bytes':2290160,'sha_matches':True}
        tuf={**mac,'gateway':'https://100.65.98.90:9443'}
        manifest={'sha256':trial.SHA,'size':2290160,'url':'https://192.168.4.82:9443/v1/device/firmware/'+trial.SHA}
        good={'both_downloads_verified':True,'releases':[{'manifest':manifest,'signature_verified':True,'device_certificate_downloads':[mac,tuf]}]}
        trial.verified_device_downloads(good,2290160)
        for mutation in ('duplicate','size','unreachable','hash','image','signature'):
            broken=deepcopy(good);release=broken['releases'][0];row=release['device_certificate_downloads'][1]
            if mutation=='duplicate':row['gateway']=mac['gateway']
            elif mutation=='size':row['bytes']=2290159
            elif mutation=='unreachable':row['status']='unreachable'
            elif mutation=='hash':row['sha_matches']=False
            elif mutation=='image':release['manifest']['sha256']='0'*64
            else:release['signature_verified']=False
            with self.assertRaises(ValueError,msg=mutation):
                trial.verified_device_downloads(broken,2290160)

    def test_real_aborted_layout_keeps_confirmed_bank(self):
        before=record(7,4)+record(6,2)
        sector,seq=trial.selection(before)
        self.assertEqual(seq,9)
        after=sector+before[4096:]
        self.assertEqual(after[4096:],before[4096:])
        self.assertEqual(selected(after),0)
        self.assertEqual(trial.entries(after,allow_pending=True)[0]['state'],0)
        aborted=bytearray(after);struct.pack_into('<I',aborted,24,4)
        self.assertEqual(selected(aborted),1)

    def test_interrupted_sector_never_erases_other_baseline(self):
        before=record(7,4)+record(6,2);sector,_=trial.selection(before)
        # Erasure and partial writes of sector0; no bytes of bank1 are changed.
        for length in (0,1,2,3,4,24,28,31,32,4096):
            incomplete=sector[:length]+b'\xff'*(4096-length)+before[4096:]
            rows=trial.entries(incomplete,allow_pending=True)
            self.assertTrue(rows[1]['crc_valid'])
            self.assertEqual(rows[1]['state'],2)
            self.assertEqual(incomplete[4096:],before[4096:])
            self.assertIn(selected(incomplete),(0,1))

    def test_pending_cannot_be_reapplied_but_can_be_inspected_for_rollback(self):
        pending=record(9,1)+record(6,2)
        with self.assertRaisesRegex(ValueError,'Pending'):trial.selection(pending)
        self.assertEqual(trial.entries(pending,allow_pending=True)[1]['state'],2)
        reverted=record(7,4)+pending[4096:]
        self.assertEqual(selected(reverted),1)

    def test_no_trial_when_baseline_slot_or_crc_is_wrong(self):
        for before in [record(7,2)+record(6,2),record(5,3)+record(6,3),record(5,2)+record(0xfffffff0,2)]:
            with self.assertRaises(ValueError):trial.selection(before)
        bad=bytearray(record(7,4)+record(6,2));bad[4096+28]^=1
        with self.assertRaisesRegex(ValueError,'baseline'):trial.selection(bad)

    def test_official_otatool_generates_the_same_sequence_crc(self):
        idf=Path.home()/'esp/esp-idf-v6.0.1';os.environ['IDF_PATH']=str(idf)
        sys.path.insert(0,str(idf/'components/partition_table'))
        spec=importlib.util.spec_from_file_location('official',idf/'components/app_update/otatool.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        import gen_esp32part
        class Memory:
            partition_table=gen_esp32part.PartitionTable.from_binary((trial.ROOT.parent/'build/partition_table/partition-table.bin').read_bytes())
            def write_partition(self,partition,filename):self.written=Path(filename).read_bytes()
        memory=Memory();tool=module.OtatoolTarget.__new__(module.OtatoolTarget)
        tool.target=memory;tool.spi_flash_sec_size=8192;tool.otadata=record(7,4)+record(8,2)
        tool.switch_ota_partition(0)
        # Use a confirmed highest sequence for the official tool; it ignores
        # aborted image state. Our separate actual-layout test retains bank1.
        sector,seq=trial.selection(tool.otadata)
        generated=memory.written[:32]
        self.assertEqual(struct.unpack_from('<I',generated)[0],seq)
        self.assertEqual(generated[28:32],sector[28:32])

    def test_actual_signed_image_and_dry_run_do_not_import_esptool(self):
        self.assertEqual(trial.sha(trial.signed_candidate()),trial.SHA)

    def exercise_real_main(self,failure=None,rollback=False,trace_kind='empty',already_exact=False,close_failure=False):
        # Run the real installer against a flash emulator, injecting write
        # failure. No serial device or service call exists in this emulator.
        baseline=(trial.ROOT.parent/'build/agentshell.bin').read_bytes()
        image=(trial.ROOT/'evidence/sagwa-v2/sagwa-edge-candidate-j.bin').read_bytes()
        memory=bytearray(b'\xff'*(16*1024*1024))
        memory[0x420000:0x420000+len(baseline)]=baseline
        memory[0x1d000:0x1f000]=record(7,4)+record(6,2)
        if already_exact:memory[0x20000:0x20000+len(image)]=image
        before=bytes(memory);writes=[];failed=False
        class Port:
            timeout=0
            def read(self,n):return b''
            def close(self):
                if close_failure:raise OSError('Injected close failure')
        class ESP:
            CHIP_NAME='ESP32-S3';secure_download_mode=False
            def __init__(self):self._port=Port();self.stage='download'
            def read_mac(self):return bytes.fromhex(trial.MAC)
            def get_flash_encryption_enabled(self):return False
            def get_secure_boot_enabled(self):return False
            def flash_id(self):return 24<<16
        def read_flash(esp,offset,size,output,**kw):
            self.assertEqual(esp.stage,'download','Flash read against stale application session')
            Path(output).write_bytes(memory[offset:offset+size])
        def write_flash(esp,rows,**kw):
            nonlocal failed
            self.assertEqual(esp.stage,'download','Flash write against stale application session')
            for offset,data in rows:
                writes.append((offset,len(data)))
                if failure=='metadata' and offset==0x1d000 and not failed:
                    failed=True;memory[offset:offset+16]=data[:16];raise OSError('Injected metadata interruption')
                memory[offset:offset+len(data)]=data
        connections=[]
        def detect(*a,**k):e=ESP();connections.append(e);return e
        def reset(esp,*a):esp.stage='application'
        captures=[0]
        def capture(port,path,seconds=95):
            captures[0]+=1
            if failure=='capture' and captures[0]==1:raise OSError('Injected post-reset read failure')
            if trace_kind=='valid' and captures[0]==1:struct.pack_into('<I',memory,0x1d000+24,2)
            return {'bytes':0 if trace_kind=='empty' else 20,'edge_boot_seen':trace_kind=='valid' and captures[0]==1,'baseline_boot_seen':False,'panic_seen':False,'backtrace_seen':False}
        cmds=types.SimpleNamespace(detect_chip=detect,run_stub=lambda e:e,
                                  read_flash=read_flash,write_flash=write_flash,reset_chip=reset)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);private=root/'.private/edge-hardware';private.mkdir(parents=True,mode=0o700)
            evidence=root/'evidence/sagwa-v2';evidence.mkdir(parents=True)
            reads=[]
            for i in (1,2):
                path=private/f'backup{i}.bin';path.write_bytes(before)
                reads.append({'path':str(path),'sha256':trial.sha(before)})
            (evidence/'physical-flash-reads.json').write_text(json.dumps({'status':'matching_reads','reads':reads}))
            (evidence/'soak-docker.json').write_text(json.dumps({'status':'interrupted'}))
            # Synthetic prerequisites for the flash emulator only. No actual
            # publication/review receipt is changed or invented by this test.
            (evidence/'edge-release-j-published-verified.json').write_text(json.dumps({
                'both_downloads_verified':True,
                'releases':[{'manifest':{'sha256':trial.SHA,'size':len(image),
                                        'url':'https://192.168.4.82:9443/v1/device/firmware/'+trial.SHA},
                             'signature_verified':True,
                             'device_certificate_downloads':[
                                 {'gateway':gateway,'status':200,'bytes':len(image),'sha_matches':True}
                                 for gateway in ('https://192.168.4.82:9443','https://100.65.98.90:9443')]}]}))
            review=root/'review.json';review.write_text(json.dumps({'verdict':'PASS','status':'terminal_pass','script_sha256':trial.sha(Path(trial.__file__).read_bytes())}))
            tick=[0]
            def monotonic():tick[0]+=50;return tick[0]
            with contextlib.redirect_stdout(io.StringIO()),patch.object(trial,'ROOT',root),patch.object(trial,'BOOT_SHA',trial.sha(before[:0x10000])),patch.object(trial,'signed_candidate',return_value=image),patch.object(trial,'capture_console',side_effect=capture),patch.object(trial,'offer_image'),patch.dict(sys.modules,{'esptool':types.SimpleNamespace(cmds=cmds)}),patch.object(trial.subprocess,'run',return_value=types.SimpleNamespace(returncode=113)),patch.object(trial.time,'monotonic',side_effect=monotonic),patch.object(sys,'argv',['trial','apply','--port','synthetic','--execute','--review',str(review)]):
                if failure:
                    with self.assertRaisesRegex(OSError,'Injected'):trial.main()
                else:
                    trial.main()
                    if rollback:
                        # Recovery must still work when distribution loses TUF.
                        (evidence/'edge-release-j-published-verified.json').write_text('{}')
                        checkpoint=json.loads(next(evidence.glob('physical-edge-apply-*.json')).read_text())['checkpoint']
                        struct.pack_into('<I',memory,0x1d000+24,1) # pending candidate
                        with patch.object(sys,'argv',['trial','rollback','--port','synthetic','--execute','--review',str(review),'--checkpoint',checkpoint]):trial.main()
            receipts=list(evidence.glob('physical-edge-apply-*.json'));self.assertEqual(len(receipts),1)
            receipt=json.loads((next(evidence.glob('physical-edge-rollback-*.json')) if rollback else receipts[0]).read_text())
            self.assertEqual(bytes(memory[0x1e000:]),before[0x1e000:0x20000]+image+before[0x20000+len(image):])
            self.assertEqual(bytes(memory[:0x1d000]),before[:0x1d000])
            self.assertTrue(all(offset in (0x20000,0x1d000) for offset,size in writes))
            self.assertTrue(all(size==4096 for offset,size in writes if offset==0x1d000))
            if failure=='capture' or not failure:self.assertGreaterEqual(len(connections),2)
            if already_exact:self.assertTrue(all(offset==0x1d000 for offset,size in writes))
            return receipt,bytes(memory)

    def test_real_installer_retains_protected_regions_and_baseline_bank(self):
        receipt,memory=self.exercise_real_main()
        self.assertEqual(receipt['status'],'capture_inconclusive_and_restored')
        self.assertTrue(receipt['read_back_verified'])
        self.assertTrue(receipt['baseline_selection_restored'])
        self.assertEqual(selected(memory[0x1d000:0x1f000]),1)

    def test_real_installer_recovers_interrupted_selection_write(self):
        receipt,memory=self.exercise_real_main('metadata')
        self.assertEqual(receipt['status'],'failed')
        self.assertTrue(receipt['metadata_recovered'])
        self.assertEqual(selected(memory[0x1d000:0x1f000]),1)

    def test_real_rollback_reselects_baseline_even_when_candidate_pending(self):
        receipt,memory=self.exercise_real_main(rollback=True)
        self.assertEqual(receipt['status'],'capture_inconclusive_and_restored')
        self.assertTrue(all(row['offset']==0x1d000 and row['size']==4096 for row in receipt['writes']))
        self.assertEqual(selected(memory[0x1d000:0x1f000]),1)

    def test_empty_capture_is_inconclusive_and_valid_image_is_still_restored(self):
        receipt,memory=self.exercise_real_main(trace_kind='valid')
        self.assertEqual(receipt['status'],'captured_and_restored')
        self.assertEqual(receipt['metadata_after_download_reentry'][0]['state'],2)
        self.assertEqual(selected(memory[0x1d000:0x1f000]),1)

    def test_post_reset_failure_recovers_via_fresh_download_session(self):
        receipt,memory=self.exercise_real_main('capture')
        self.assertTrue(receipt['metadata_recovered'])
        self.assertEqual(selected(memory[0x1d000:0x1f000]),1)

    def test_exact_installed_candidate_is_not_rewritten(self):
        receipt,memory=self.exercise_real_main(already_exact=True)
        self.assertTrue(receipt['candidate_already_exact'])
        self.assertEqual(selected(memory[0x1d000:0x1f000]),1)

    def test_close_error_cannot_hide_recovery_receipt(self):
        receipt,memory=self.exercise_real_main(close_failure=True)
        self.assertTrue(receipt['close_errors'])
        self.assertEqual(selected(memory[0x1d000:0x1f000]),1)

if __name__=='__main__':unittest.main()
