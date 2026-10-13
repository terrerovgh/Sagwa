"""Create private host PKI/config; never writes credentials to source or stdout."""
import argparse,json,os,secrets,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1];private=root/'.private';private.mkdir(exist_ok=True,mode=0o700)
hosts={'tuf-infra':'100.65.98.90','mac-mini':'100.68.191.53','lenlab':'100.70.149.102'}
lan={'tuf-infra':'192.168.4.64','mac-mini':'192.168.4.82','lenlab':'127.0.0.1'}
def openssl(*args): subprocess.run(['openssl',*map(str,args)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def authority(name):
 p=private/name;p.mkdir(exist_ok=True,mode=0o700)
 if not (p/'ca.pem').exists(): openssl('req','-x509','-newkey','rsa:3072','-nodes','-days','3650','-subj','/CN=AgentShell '+name,'-keyout',p/'ca-key.pem','-out',p/'ca.pem')
 return p
def cert(ca,folder,cn,addresses,clientonly=False):
 folder.mkdir(exist_ok=True,parents=True,mode=0o700)
 if (folder/'cert.pem').exists(): return
 openssl('req','-newkey','rsa:2048','-nodes','-subj','/CN='+cn,'-keyout',folder/'key.pem','-out',folder/'request.csr')
 ext=folder/'extensions.cnf';ext.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage='+('clientAuth' if clientonly else 'serverAuth,clientAuth')+'\n'+('subjectAltName='+','.join('IP:'+x for x in addresses)+'\n' if addresses else ''))
 openssl('x509','-req','-in',folder/'request.csr','-CA',ca/'ca.pem','-CAkey',ca/'ca-key.pem','-CAcreateserial','-days','730','-extfile',ext,'-out',folder/'cert.pem');ext.unlink();(folder/'request.csr').unlink()
 (folder/'ca.pem').write_bytes((ca/'ca.pem').read_bytes())
app=authority('application-ca');etcd=authority('etcd-ca')
cert(app,private/'device','device:cores3-80456b4d5f7c',[],True)
parser=argparse.ArgumentParser();parser.add_argument('--allow-existing-hermes-provider',action='store_true');options=parser.parse_args()
for name in ['admin-token','voice-token','muse-token','tools-token','hermes-token']:
 p=private/name
 if not p.exists(): p.write_text(secrets.token_urlsafe(48)+'\n')
for node,ip in hosts.items():
 d=private/node;cert(app,d/'tls','node:'+node,[ip,lan[node],'127.0.0.1']);cert(etcd,d/'etcd-tls','etcd:'+node,[ip,'127.0.0.1'])
 base=str(Path.home()/'Library/Application Support/AgentShell/private') if node=='mac-mini' else '/opt/agentshell/private'
 state=str(Path.home()/'Library/Application Support/AgentShell/state') if node=='mac-mini' else '/var/lib/agentshell'
 for name in ['admin-token','voice-token','muse-token','tools-token','hermes-token']: (d/name).write_bytes((private/name).read_bytes())
 cfg={'node_id':node,'roles':['gateway','coordinator','executor','objects'] if node=='tuf-infra' else ['coordinator','executor','objects'] if node=='lenlab' else ['gateway','executor','objects'], 'listen':{'host':'0.0.0.0','port':9443},'tls':{k:base+'/tls/'+f for k,f in [('ca','ca.pem'),('cert','cert.pem'),('key','key.pem')]},'state_dir':state,'etcd':{'hosts':['https://'+v+':2379' for v in hosts.values()],**{k:base+'/etcd-tls/'+f for k,f in [('ca','ca.pem'),('cert','cert.pem'),('key','key.pem')]}},'coordinator_candidates':['tuf-infra','lenlab'],'peers':[{'id':n,'url':'https://'+v+':9443'} for n,v in hosts.items()],'device_ids':['device:cores3-80456b4d5f7c'],'admin_token_file':base+'/admin-token','voice':{'url':'http://127.0.0.1:9450','token_file':base+'/voice-token'},'agents':{'muse':{'enabled':True,'url':'https://'+hosts['mac-mini']+':9443/internal/agents/muse',**({'local_url':'http://127.0.0.1:9451'} if node=='mac-mini' else {}),'secret_file':base+'/muse-token'},'hermes':{'enabled':True,'url':'https://'+hosts['lenlab']+':9443/internal/agents/hermes',**({'local_url':'http://127.0.0.1:18790','secret_file':base+'/hermes-token'} if node=='lenlab' else {})},'codex':{'enabled':False},'opencode':{'enabled':False},'claude':{'enabled':False},'grok':{'enabled':False,'paid_api':True},'grok-bot':{'enabled':False}},'resources':[],'retention_days':30,'paid_apis_enabled':False}
 previous=json.loads((d/'config.json').read_text()) if (d/'config.json').exists() else {}
 for field in ['resources','paid_agents_allowed','paid_apis_enabled','ota_public_key_file','device_gateway_urls','emoji','agent_workers']:
  if field in previous: cfg[field]=previous[field]
 for agent,settings in previous.get('agents',{}).items(): cfg['agents'].setdefault(agent,{}).update(settings)
 cfg['tools_token_file']=base+'/tools-token'
 cfg['agents']['hermes'].update({'paid_api':True,'model':'agentshell-hermes'})
 if node=='lenlab': cfg['agents']['hermes'].update({'local_url':'http://127.0.0.1:9453','secret_file':base+'/hermes-token'})
 if options.allow_existing_hermes_provider: cfg['paid_agents_allowed']=sorted(set(cfg.get('paid_agents_allowed',[]))|{'hermes'})
 (d/'config.json').write_text(json.dumps(cfg,indent=2)+'\n')
 cfg_etcd={'name':node,'data-dir':state+'/etcd','listen-client-urls':'https://0.0.0.0:2379','advertise-client-urls':'https://'+ip+':2379','listen-peer-urls':'https://0.0.0.0:2380','initial-advertise-peer-urls':'https://'+ip+':2380','initial-cluster':','.join(n+'=https://'+v+':2380' for n,v in hosts.items()),'initial-cluster-token':'agentshell-v1','initial-cluster-state':'new','client-transport-security':{'cert-file':base+'/etcd-tls/cert.pem','key-file':base+'/etcd-tls/key.pem','trusted-ca-file':base+'/etcd-tls/ca.pem','client-cert-auth':True},'peer-transport-security':{'cert-file':base+'/etcd-tls/cert.pem','key-file':base+'/etcd-tls/key.pem','trusted-ca-file':base+'/etcd-tls/ca.pem','client-cert-auth':True},'auto-compaction-mode':'periodic','auto-compaction-retention':'24h','quota-backend-bytes':134217728}
 # JSON is YAML 1.2, accepted by etcd's configuration parser.
 (d/'etcd.json').write_text(json.dumps(cfg_etcd,indent=2)+'\n')
 models=str(Path.home()/'Library/Application Support/AgentShell/models') if node=='mac-mini' else '/opt/agentshell/models'
 (d/'voice.json').write_text(json.dumps({'token_file':base+'/voice-token','whisper_path':models+'/whisper-base','piper_path':models+'/es_MX-ald-medium.onnx','port':9450},indent=2)+'\n')
for p in private.rglob('*'):
 if p.is_file() and 'runtime' not in p.relative_to(private).parts: p.chmod(0o600)
print('Private configurations prepared for three nodes. CA signing keys stay on the Mac mini.')
