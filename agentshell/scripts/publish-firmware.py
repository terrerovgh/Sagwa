"""Sign and replicate a firmware release; offer only when explicitly requested."""
import argparse,hashlib,json,subprocess,tempfile,base64,struct
from pathlib import Path
from admin import request

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('image',type=Path);parser.add_argument('--version',required=True);parser.add_argument('--offer',action='store_true');parser.add_argument('--gateway',default='https://192.168.4.82:9443')
args=parser.parse_args();image=args.image.read_bytes();hash=hashlib.sha256(image).hexdigest()
if len(image)<80 or image[0]!=0xe9 or struct.unpack_from('<I',image,32)[0]!=0xabcd5432:raise SystemExit('Invalid ESP-IDF application descriptor')
actual_version=image[48:80].split(b'\0',1)[0].decode('ascii')
if actual_version!=args.version:raise SystemExit('Firmware descriptor version differs from the requested release; rebuild with -D AGENTSHELL_RELEASE_VERSION='+args.version)
manifest=json.dumps({'target':'esp32s3','version':args.version,'sha256':hash,'size':len(image),'url':args.gateway+'/v1/device/firmware/'+hash},separators=(',',':'))
with tempfile.TemporaryDirectory() as temp:
    file=Path(temp)/'manifest.json';file.write_text(manifest)
    signature=subprocess.run(['openssl','dgst','-sha256','-sign',str(root/'.private/ota/signing-key.pem'),str(file)],check=True,capture_output=True).stdout
release={'manifest':manifest,'signature':base64.b64encode(signature).decode()}
request('/v1/firmware/'+hash,'PUT',image,binary=True)
request('/v1/firmware/releases','POST',release)
if args.offer:request('/v1/firmware/offer','POST',{'device_id':'device:cores3-80456b4d5f7c','sha256':hash})
print(json.dumps({'sha256':hash,'version':args.version,'size':len(image),'offered':args.offer}))
