"""Provision/test CoreS3 through USB without printing Wi-Fi or client credentials."""
import argparse,json,time
from pathlib import Path
import serial
parser=argparse.ArgumentParser()
parser.add_argument('--port',default='/dev/cu.usbmodem21101')
parser.add_argument('command',choices=['provision','sensors','camera.test','microphone.test','speaker.test','audio.status','display.test','calibrate','monitor'])
parser.add_argument('--seconds',type=int,default=10)
options=parser.parse_args();root=Path(__file__).resolve().parents[1];private=root/'.private'
request={'command':options.command}
if options.command=='provision':
 wifi=json.loads((private/'wifi-import.json').read_text());device=private/'device'
 request['config']={'wifi_ssid':wifi.get('ssid') or wifi.get('wifi_ssid'),
                    'wifi_password':wifi.get('password') or wifi.get('wifi_password'),
                    'gateways':['wss://192.168.4.64:9443/v1/device/ws','wss://192.168.4.82:9443/v1/device/ws'],
                    'device_id':'device:cores3-80456b4d5f7c','epoch':int(time.time()),
                    'ca':(device/'ca.pem').read_text(), 'certificate':(device/'cert.pem').read_text(),
                    'key':(device/'key.pem').read_text()}
 if not request['config']['wifi_ssid']:raise SystemExit('Private Wi-Fi configuration missing')
port=serial.Serial(port=None,baudrate=115200,timeout=.1)
port.dtr=False;port.rts=False;port.port=options.port
with port:
 time.sleep(.5);port.reset_input_buffer()
 if options.command!='monitor':port.write(json.dumps(request,separators=(',',':')).encode()+b'\n');port.flush()
 until=time.monotonic()+options.seconds;buffer=b'';json_count=0;error_count=0
 while time.monotonic()<until:
  buffer+=port.read(port.in_waiting or 1)
  while b'\n' in buffer:
   line,buffer=buffer.split(b'\n',1)
   try:
    result=json.loads(line.decode())
    if isinstance(result,dict) and not any(k in result for k in ['key','wifi_password','config']):
     print(json.dumps(result,ensure_ascii=False));json_count+=1
   except (UnicodeDecodeError,ValueError):
    if any(v in line for v in [b'Guru Meditation',b'panic',b'assert failed',b'ERROR']):error_count+=1
 print(json.dumps({'usb_json_responses':json_count,'firmware_error_lines':error_count}))
