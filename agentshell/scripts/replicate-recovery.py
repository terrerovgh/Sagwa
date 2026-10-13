"""Keep private USB recovery images in three hosts, verify every remote hash."""
import argparse,hashlib,re,shlex,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1];parser=argparse.ArgumentParser();parser.add_argument('image',type=Path);args=parser.parse_args()
path=args.image.resolve();private=(root/'.private/recovery').resolve()
if path.parent!=private or not re.fullmatch(r'[a-zA-Z0-9._-]+\.bin',path.name):raise SystemExit('Expected a private recovery image')
data=path.read_bytes();path.chmod(0o600);expected=hashlib.sha256(data).hexdigest();destination='/opt/agentshell/private/recovery/'+path.name
for node,ssh in [('lenlab',['ssh','-C','terrerov@lenlab']),('tuf-infra',['ssh','-C','-J','terrerov@tuf-1','-p','2222','root@172.22.25.125'])]:
    check=subprocess.run(ssh+['sudo -n sha256sum '+shlex.quote(destination)],capture_output=True,timeout=30)
    if check.returncode==0:
        if check.stdout.decode().split()[0]!=expected:raise RuntimeError('Existing backup hash differs: '+node)
    else:
        command='sudo -n install -d -m 700 /opt/agentshell/private/recovery && sudo -n tee '+shlex.quote(destination)+' >/dev/null && sudo -n chmod 600 '+shlex.quote(destination)+' && sudo -n sha256sum '+shlex.quote(destination)
        check=subprocess.run(ssh+[command],input=data,capture_output=True,timeout=120)
        if check.returncode or check.stdout.decode().split()[0]!=expected:raise RuntimeError('Backup replication failed: '+node)
    print(node+': verified '+expected,flush=True)
