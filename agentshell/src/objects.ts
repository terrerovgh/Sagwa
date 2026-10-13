import { createHash,randomUUID } from 'node:crypto';
import { mkdir,open,readFile,rename,unlink,readdir,stat } from 'node:fs/promises';
import { join } from 'node:path';
import type { Config } from './config.js';
import type { Store } from './store.js';
import { PeerClient } from './http-client.js';

export interface ObjectRef {hash:string;bytes:number;replicas:string[];created_at:string;expires_at:string|null}
export class ObjectStorage {
  private root:string;
  private client:Pick<PeerClient,'request'>;
  constructor(private cfg:Config,private store:Store,client:Pick<PeerClient,'request'>=new PeerClient(cfg.tls)) {this.root=join(cfg.state_dir,'objects');this.client=client;}
  async putLocal(hash:string,data:Buffer) {
    if(!/^[a-f0-9]{64}$/.test(hash)||data.length>16*1024*1024||createHash('sha256').update(data).digest('hex')!==hash)throw new Error('invalid_object');
    await mkdir(this.root,{recursive:true,mode:0o700});
    const temp=join(this.root,'.'+randomUUID());
    const file=await open(temp,'wx',0o600);
    try {await file.writeFile(data);await file.sync();}finally{await file.close();}
    await rename(temp,join(this.root,hash));
    const dir=await open(this.root,'r');try{await dir.sync();}finally{await dir.close();}
  }
  async local(hash:string) {if(!/^[a-f0-9]{64}$/.test(hash))throw new Error('invalid_object');return readFile(join(this.root,hash));}
  async replicate(data:Buffer,retained=false):Promise<ObjectRef> {
    const hash=createHash('sha256').update(data).digest('hex');
    const results=await Promise.allSettled(this.cfg.peers.map(async peer=>{
      if(peer.id===this.cfg.node_id)await this.putLocal(hash,data);
      else await this.client.request(peer.url+'/internal/objects/'+hash,'PUT',data,{'content-type':'application/octet-stream'});
      return peer.id;
    }));
    const replicas=results.flatMap(r=>r.status==='fulfilled'?[r.value]:[]);
    if(replicas.length<2)throw new Error('quorum_unavailable');
    for(let n=0;n<5;n++) {
      const previous=await this.store.get<ObjectRef>('objects/'+hash);
      const ref:ObjectRef={hash,bytes:data.length,replicas:[...new Set([...replicas,...(previous?.replicas??[])])],created_at:previous?.created_at??new Date().toISOString(),expires_at:retained||previous?.expires_at===null?null:new Date(Date.now()+this.cfg.retention_days*86400000).toISOString()};
      if(await this.store.comparePut('objects/'+hash,previous,ref))return ref;
    }
    throw new Error('quorum_unavailable');
  }
  async get(hash:string):Promise<Buffer> {
    const ref=await this.store.get<ObjectRef>('objects/'+hash);
    if(!ref||ref.expires_at!==null&&Date.parse(ref.expires_at)<=Date.now())throw new Error('invalid_object');
    // Read a verified local copy before opening a cross-node TLS connection.
    // Metadata still comes from quorum and every copy must match its hash.
    const replicas=[...ref.replicas].sort((a,b)=>Number(b===this.cfg.node_id)-Number(a===this.cfg.node_id));
    for(const id of replicas) {
      try {const peer=this.cfg.peers.find(p=>p.id===id)!;const data=id===this.cfg.node_id?await this.local(hash):await this.client.request(peer.url+'/internal/objects/'+hash);
        if(createHash('sha256').update(data).digest('hex')===hash)return data;
      }catch{}
    }
    throw new Error('resource_unavailable');
  }
  async repairAndPrune() {
    const refs=await this.store.list<ObjectRef>('objects/');
    for(const ref of Object.values(refs)) {
      if(ref.expires_at!==null&&Date.parse(ref.expires_at)<=Date.now()) {
        // Metadata is removed by CAS; a concurrent retention upgrade wins.
        await this.store.compareDelete('objects/'+ref.hash,ref);
        continue;
      }
      if(!ref.replicas.includes(this.cfg.node_id)) {
        try {await this.putLocal(ref.hash,await this.get(ref.hash));await this.store.comparePut('objects/'+ref.hash,ref,{...ref,replicas:[...ref.replicas,this.cfg.node_id]});}catch{}
      }
    }
    for(const prefix of ['tasks/','actions/','approvals/']) {
      const rows=await this.store.list<{updated_at?:string;expires_at?:number}>(prefix);
      for(const [key,value] of Object.entries(rows)) {
        const at=value.updated_at?Date.parse(value.updated_at):value.expires_at;
        if(at!==undefined&&at<Date.now()-30*86400000)await this.store.compareDelete(key,value);
      }
    }
    // Remove expired orphan files only after the retention window, never during quorum loss.
    for(const name of await readdir(this.root).catch(()=>[])) {
      if(/^[a-f0-9]{64}$/.test(name)&&!refs['objects/'+name]) {
        const file=join(this.root,name);const s=await stat(file);if(s.mtimeMs<Date.now()-30*86400000)await unlink(file);
      }
    }
  }
}
