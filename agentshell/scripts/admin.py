"""Private authenticated admin client; credentials are read only from local files."""
import argparse,json,ssl,urllib.request
from pathlib import Path

root=Path(__file__).resolve().parents[1]
def request(path,method='GET',data=None,base='https://100.68.191.53:9443',binary=False):
    tls=root/'.private/mac-mini/tls'
    context=ssl.create_default_context(cafile=str(tls/'ca.pem'))
    context.load_cert_chain(str(tls/'cert.pem'),str(tls/'key.pem'))
    token=(root/'.private/admin-token').read_text().strip()
    encoded=data if binary else None if data is None else json.dumps(data).encode()
    req=urllib.request.Request(base+path,data=encoded,method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/octet-stream' if binary else 'application/json'})
    with urllib.request.urlopen(req,context=context,timeout=60) as response:
        return json.load(response)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('path');parser.add_argument('--method',default='GET');parser.add_argument('--body-file');parser.add_argument('--base',default='https://100.68.191.53:9443')
    args=parser.parse_args();data=json.loads(Path(args.body_file).read_text()) if args.body_file else None
    print(json.dumps(request(args.path,args.method,data,args.base),ensure_ascii=False,indent=2))
