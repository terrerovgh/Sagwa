"""Bounded, read-only physical telemetry capture; no resets or device commands."""
import argparse
import datetime
import json
from pathlib import Path
import time
from admin import request

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--version',default='0.3.0-dev')
parser.add_argument('--seconds',type=int,default=60)
parser.add_argument('--wait-seconds',type=int,default=180)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
if not 10<=args.seconds<=300 or not 5<=args.wait_seconds<=300:
    raise SystemExit('Invalid bounded observation window')
rows=[];errors=[];start=time.monotonic();collect=None
while True:
    try:
        device=request('/v1/devices').get('devices/telemetry/device:cores3-80456b4d5f7c',{})
    except Exception as error:
        errors.append({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'type':type(error).__name__})
        if time.monotonic()-start>=args.wait_seconds:break
        time.sleep(5)
        continue
    now=datetime.datetime.now(datetime.timezone.utc)
    received=device.get('received_at')
    age=(now-datetime.datetime.fromisoformat(received.replace('Z','+00:00'))).total_seconds() if received else None
    firmware=device.get('capabilities',{}).get('firmware')
    if firmware==args.version and age is not None and 0<=age<20:
        if collect is None:collect=time.monotonic()
        readings=device.get('readings',{})
        rows.append({'at':now.isoformat(),'received_at':received,'age_s':round(age,2),
                     'firmware':firmware,'gateway':device.get('gateway'),
                     **{key:readings.get(key) for key in ['runtime','ui','reaction_timing','audio','camera','boot_verified','acceleration','ambient_light','proximity','power']}})
        if time.monotonic()-collect>=args.seconds:break
    elif time.monotonic()-start>=args.wait_seconds:
        break
    time.sleep(5)
fps=[r['ui']['completed_fps'] for r in rows if isinstance(r.get('ui'),dict) and isinstance(r['ui'].get('completed_fps'),(int,float))]
result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope':'Physical telemetry only; no optical LCD, acoustic recording, physical touch/PWR or camera confirmation claim',
        'expected_version':args.version,'samples':rows,'sample_count':len(rows),
        'request_errors':errors,
        'fresh_expected_firmware_observed':bool(rows),'boot_verified_observed':any(r.get('boot_verified') is True for r in rows),
        'completed_fps_min':min(fps) if fps else None,'completed_fps_max':max(fps) if fps else None,
        'completed_fps_target_all_samples':bool(fps) and min(fps)>=30,
        'window_seconds':round(time.monotonic()-collect,1) if collect else 0,
        'product_acceptance':False,'device_commands_sent':False,'valid_24h':False}
args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='samples'},ensure_ascii=False,indent=2))
