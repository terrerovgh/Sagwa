"""Import existing device pairing into a private host bridge. Never prints values."""
import argparse,json,os,struct,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
if sys.version_info<(3,10):raise SystemExit('Use the ESP-IDF Python environment: source ./activar-muse.sh; python3 agentshell/scripts/import-muse-backup.py')
parser=argparse.ArgumentParser();parser.add_argument('--backup',type=Path,default=root/'.private/recovery/muse-before-agentshell.bin');parser.add_argument('--import-wifi',action='store_true');options=parser.parse_args()
sys.path.insert(0,'/Users/terrerov/esp/esp-idf-v6.0.1/components/nvs_flash/nvs_partition_tool')
from nvs_parser import NVS_Partition
raw=options.backup.read_bytes()
partitions=[]
for at in range(0x10000,0x11000,32):
 magic,typ,sub,offset,size,name,flags=struct.unpack('<HBBII16sI',raw[at:at+32])
 if magic!=0x50aa:break
 partitions.append((name.rstrip(b'\0').decode(),offset,size))
offset,size=next((o,s) for n,o,s in partitions if n=='nvs')
p=NVS_Partition('nvs',bytearray(raw[offset:offset+size]));names={};values={}
for page in sorted(p.pages,key=lambda x:x.header['page_index']):
 for entry in page.entries:
  if entry.state!='Written':continue
  if entry.metadata['namespace']==0 and entry.metadata['type']=='uint8_t':names[entry.data['value']]=entry.key
for page in sorted(p.pages,key=lambda x:x.header['page_index']):
 for entry in page.entries:
  if entry.state!='Written' or entry.metadata['type']!='string':continue
  val=b''.join(e.raw for e in entry.children)[:entry.data['size']].rstrip(b'\0').decode()
  values[(names.get(entry.metadata['namespace']),entry.key)]=val
state=Path.home()/'Library/Application Support/AgentShell/muse-state';state.mkdir(exist_ok=True,parents=True,mode=0o700)
keys=['access_token','refresh_token','api_url_v2','noise_host']
pair={k:values.get(('homehub',k),'') for k in keys}
if not pair['access_token'] or not pair['refresh_token']:raise SystemExit('Pairing absent; original Muse backup preserved')
pair['access_token_saved_at']=int(time.time())
(state/'pairing.json').write_text(json.dumps(pair))
(state/'identity.json').write_text(json.dumps({'mac':'80:45:6b:4d:5f:7c'}))
sdk=root.parent/'muse-gadget-sdk/.sdk-token'
if sdk.exists(): (state/'sdk_token').write_text(sdk.read_text().strip())
# Network data is used for USB provisioning only; credentials stay outside source.
wifi={k:values.get(('homehub',k),'') for k in ['wifi_ssid','wifi_password','ssid','password']}
if options.import_wifi:(root/'.private/wifi-import.json').write_text(json.dumps(wifi))
for f in state.iterdir():f.chmod(0o600)
(root/'.private/wifi-import.json').chmod(0o600)
print('Private pairing imported. Wi-Fi changed:',options.import_wifi)
