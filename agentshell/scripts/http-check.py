"""Authenticated host checks without printing tokens."""
import json,ssl,sys,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1];tls=root/'.private/mac-mini/tls';context=ssl.create_default_context(cafile=str(tls/'ca.pem'));context.load_cert_chain(str(tls/'cert.pem'),str(tls/'key.pem'));token=(root/'.private/admin-token').read_text().strip()
url=sys.argv[1] if len(sys.argv)>1 else 'https://100.68.191.53:9443/v1/state'
r=urllib.request.Request(url,headers={'Authorization':'Bearer '+token})
with urllib.request.urlopen(r,context=context,timeout=20) as response:print(json.dumps(json.load(response),ensure_ascii=False,indent=2))
