import hashlib,io,json,sys,tarfile,urllib.request,zipfile
from pathlib import Path
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'.private'/'runtime';root.mkdir(exist_ok=True,parents=True)
version='v3.6.15';base='https://github.com/etcd-io/etcd/releases/download/'+version+'/'
def fetch(url):
 with urllib.request.urlopen(url,timeout=60) as r:return r.read()
sums=fetch(base+'SHA256SUMS').decode()
for platform in (['darwin-arm64','linux-amd64'] if sys.platform=='darwin' else ['linux-amd64']):
 name='etcd-'+version+'-'+platform+('.zip' if platform.startswith('darwin') else '.tar.gz');target=root/platform;target.mkdir(exist_ok=True)
 if (target/'etcd').exists():continue
 data=fetch(base+name);expected=next(line.split()[0] for line in sums.splitlines() if line.split()[-1].lstrip('*')==name)
 if hashlib.sha256(data).hexdigest()!=expected:raise RuntimeError('etcd checksum mismatch')
 if name.endswith('.zip'):
  z=zipfile.ZipFile(io.BytesIO(data))
  for tool in ['etcd','etcdctl','etcdutl']:
   item=next(x for x in z.namelist() if x.endswith('/'+tool));(target/tool).write_bytes(z.read(item));(target/tool).chmod(0o755)
 else:
  t=tarfile.open(fileobj=io.BytesIO(data),mode='r:gz')
  for tool in ['etcd','etcdctl','etcdutl']:
   item=next(x for x in t.getmembers() if x.name.endswith('/'+tool));(target/tool).write_bytes(t.extractfile(item).read());(target/tool).chmod(0o755)
 print('Verified etcd',version,platform)
base='https://nodejs.org/dist/v24.19.0/';name='node-v24.19.0-linux-x64.tar.xz';target=root/'linux-node'
if not (target/'bin/node').exists():
 data=fetch(base+name);sums=fetch(base+'SHASUMS256.txt').decode();expected=next(x.split()[0] for x in sums.splitlines() if x.split()[-1]==name)
 if hashlib.sha256(data).hexdigest()!=expected:raise RuntimeError('Node checksum mismatch')
 target.mkdir(exist_ok=True);t=tarfile.open(fileobj=io.BytesIO(data),mode='r:xz')
 for item in t.getmembers():
  if item.name.endswith('/bin/node'):
   (target/'bin').mkdir(exist_ok=True);(target/'bin/node').write_bytes(t.extractfile(item).read());(target/'bin/node').chmod(0o755)
 print('Verified Node 24.19.0 linux-x64')
