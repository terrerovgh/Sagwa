import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID,generateKeyPairSync,sign,createHash } from 'node:crypto';
import { mkdtemp,rm,mkdir,writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Policy,type Action,type Rule } from '../src/policy.js';
import { digest,canonical } from '../src/security.js';
import { decodeEnvelope,envelope,encodeMedia,decodeMedia,Deduplicator } from '../src/protocol.js';
import type { Store } from '../src/store.js';
import { requireEpoch } from '../src/leadership.js';
import { Executor } from '../src/executor.js';
import type { Config } from '../src/config.js';
import { AgentBroker } from '../src/broker.js';
import { validateRelease } from '../src/releases.js';
import { ObjectStorage,type ObjectRef } from '../src/objects.js';
import { AgentRegistry } from '../src/adapters.js';

class MemoryStore implements Store {
  values=new Map<string,string>();available=true;
  check(){if(!this.available)throw Error('quorum_unavailable');}
  async get<T>(k:string){this.check();const value=this.values.get(k);return value?JSON.parse(value) as T:null;}
  async put(k:string,v:unknown){this.check();this.values.set(k,JSON.stringify(v));}
  async list<T>(prefix:string){this.check();return Object.fromEntries([...this.values].filter(([k])=>k.startsWith(prefix)).map(([k,v])=>[k,JSON.parse(v) as T]));}
  async comparePut(k:string,e:unknown|null,v:unknown){this.check();const current=this.values.get(k);if(e===null?current!==undefined:current!==JSON.stringify(e))return false;this.values.set(k,JSON.stringify(v));return true;}
  async compareBatch(key:string,expected:unknown|null,value:unknown,extraKey:string,extraValue:unknown){const ok=await this.comparePut(key,expected,value);if(ok)await this.put(extraKey,extraValue);return ok;}
  async delete(k:string){this.check();this.values.delete(k);}
  async compareDelete(k:string,e:unknown){this.check();if(this.values.get(k)!==JSON.stringify(e))return false;this.values.delete(k);return true;}
  async healthy(){return this.available;}
}
test('history reads verified local replicas first and falls back when the local copy is corrupt',async()=>{
  const root=await mkdtemp(join(tmpdir(),'agentshell-local-first-'));try{
    const data=Buffer.from('durable answer'),hash=createHash('sha256').update(data).digest('hex'),store=new MemoryStore();
    const cfg={node_id:'b',state_dir:root,peers:[{id:'a',url:'https://a'},{id:'b',url:'https://b'}]} as Config;
    await store.put('objects/'+hash,{hash,replicas:['a','b'],expires_at:null});let remoteReads=0;
    const objects=new ObjectStorage(cfg,store,{async request(){remoteReads++;return data;}});
    await objects.putLocal(hash,data);assert.deepEqual(await objects.get(hash),data);assert.equal(remoteReads,0);
    await writeFile(join(root,'objects',hash),'corrupt');assert.deepEqual(await objects.get(hash),data);assert.equal(remoteReads,1);
    store.available=false;await assert.rejects(()=>objects.get(hash),/quorum_unavailable/);
  }finally{await rm(root,{recursive:true,force:true});}
});
function action(operation:Action['operation']='docker.restart'):Action{return{action_id:randomUUID(),task_id:randomUUID(),operation,node:'tuf-infra',resource:'api',params:{}};}
test('protocol rejects extra fields, invalid versions and oversized JSON',()=>{
  const value=envelope(randomUUID(),1,'task.submit',{});
  assert.deepEqual(decodeEnvelope(Buffer.from(JSON.stringify(value))),value);
  for(const bad of [{...value,version:2},{...value,api_key:'secret'},{...value,sequence:-1}])assert.throws(()=>decodeEnvelope(Buffer.from(JSON.stringify(bad))));
  assert.throws(()=>decodeEnvelope(Buffer.alloc(32769)));
});
test('binary frames preserve identity and reject malformed headers',()=>{
  const frame={session_id:randomUUID(),task_id:randomUUID(),stream_id:randomUUID(),sequence:19,kind:1 as const,data:Buffer.from([2,3])};
  assert.deepEqual(decodeMedia(encodeMedia(frame)),frame);
  const bad=encodeMedia(frame);bad[56]=4;assert.throws(()=>decodeMedia(bad));
  assert.throws(()=>decodeMedia(Buffer.alloc(20)));
});
test('message replay window is bounded and expires',()=>{
  const dedupe=new Deduplicator(2,10);assert(dedupe.accept('a',0));assert(!dedupe.accept('a',1));assert(dedupe.accept('b',1));assert(dedupe.accept('c',2));assert(dedupe.accept('a',3));assert(dedupe.accept('a',20));
});
test('action hash is independent of object field insertion order',()=>{
  assert.equal(digest({a:1,b:{y:2,x:3}}),digest({b:{x:3,y:2},a:1}));assert.notEqual(digest({a:1}),digest({a:2}));assert.equal(canonical([1,2]),'[1,2]');
});
test('empty allowlist reads automatically and requires approval for writes',async()=>{
  const policy=new Policy(new MemoryStore());assert(await policy.automatic(action('host.status')));assert(!await policy.automatic(action()));assert(!await policy.authorize(action('storage.delete')));
});
test('paid providers stay unavailable unless specifically authorized, even when paid_api was omitted',async()=>{
  const cfg={agents:{claude:{enabled:true,args:[],model:'configured',paid_api:false},grok:{enabled:true,args:[],model:'configured',paid_api:false}},paid_apis_enabled:false,paid_agents_allowed:['hermes']} as unknown as Config;
  const capabilities=await new AgentRegistry(cfg).capabilities();assert(capabilities.every(c=>!c.available));
});
test('allowlist matches exact node, resource, operation, expiry and enabled flag',async()=>{
  const store=new MemoryStore(),policy=new Policy(store),a=action();
  const rule:Rule={rule_id:randomUUID(),node:a.node,resource:a.resource,operations:['docker.restart'],enabled:true,expires_at:null};await store.put('policy/rules/'+rule.rule_id,rule);
  assert(await policy.automatic(a));assert(!await policy.automatic({...a,node:'lenlab'}));assert(!await policy.automatic({...a,resource:'api-prod'}));assert(!await policy.automatic({...a,operation:'deploy.release'}));
  await store.put('policy/rules/'+rule.rule_id,{...rule,expires_at:new Date(0).toISOString()});assert(!await policy.automatic(a));
});
test('approval binds parameters, requires physical origin and is consumed once',async()=>{
  const policy=new Policy(new MemoryStore()),a=action(),approval=await policy.request(a);
  await policy.decide(approval.approval_id,approval.action_hash,'admin','admin:mac-mini','approve');assert(!await policy.authorize(a,approval.approval_id));
  await policy.decide(approval.approval_id,approval.action_hash,'device','device:cores3','approve');
  assert(!await policy.authorize({...a,params:{different:true}},approval.approval_id));
  const attempts=await Promise.all([policy.authorize(a,approval.approval_id),policy.authorize(a,approval.approval_id)]);assert.equal(attempts.filter(Boolean).length,1);
});
test('destructive action requires two origins; deny and expiry never authorize',async()=>{
  const store=new MemoryStore(),policy=new Policy(store),a=action('storage.delete');let approval=await policy.request(a);
  await policy.decide(approval.approval_id,approval.action_hash,'device','device:cores3','approve');assert(!await policy.authorize(a,approval.approval_id));
  await policy.decide(approval.approval_id,approval.action_hash,'admin','admin:mini','approve');assert(await policy.authorize(a,approval.approval_id));
  approval=await policy.request(a);await policy.decide(approval.approval_id,approval.action_hash,'device','device:cores3','deny');assert(!await policy.authorize(a,approval.approval_id));
  approval=await policy.request(a);await store.put('approvals/'+approval.approval_id,{...approval,expires_at:0});assert(!await policy.authorize(a,approval.approval_id));
});
test('executor fencing rejects old epochs and unavailable quorum',async()=>{
  const store=new MemoryStore(),authority={node:'tuf-infra',epoch:'12',lease_id:'1'};await store.put('control/active',authority);await requireEpoch(store,authority);
  await assert.rejects(()=>requireEpoch(store,{...authority,epoch:'11'}),/stale_epoch/);store.available=false;await assert.rejects(()=>requireEpoch(store,authority),/quorum_unavailable/);
});
test('executor restart replays durable result and never reruns uncertain action',async()=>{
  const root=await mkdtemp(join(tmpdir(),'agentshell-'));try{
    const store=new MemoryStore(),authority={node:'tuf-infra',epoch:'1',lease_id:'l'};await store.put('control/active',authority);
    const cfg={node_id:'tuf-infra',state_dir:root,resources:[]} as unknown as Config;
    const replicas={async replicate(data:Buffer){return{hash:digest(data.toString()),bytes:data.length,replicas:['a','b'],created_at:new Date().toISOString(),expires_at:null};}};
    const a=action('host.status');a.resource='';const first=await new Executor(cfg,store,replicas).execute(a,authority);
    assert.equal(first.state,'completed');assert.deepEqual(await new Executor(cfg,store,replicas).execute(a,authority),first);
    assert((await store.get<{audit_hash:string}>('actions/'+a.action_id))?.audit_hash);
    await assert.rejects(()=>new Executor(cfg,store,replicas).execute({...a,params:{changed:true}},authority),/invalid_action/);
    store.available=false;await assert.rejects(()=>new Executor(cfg,store).execute(action('host.status'),authority));
  }finally{await rm(root,{recursive:true,force:true});}
});
test('retained artifacts survive history expiry and cannot be downgraded by a repeated upload',async()=>{
  const root=await mkdtemp(join(tmpdir(),'agentshell-objects-'));try{
    const store=new MemoryStore();const cfg={node_id:'a',state_dir:root,retention_days:30,peers:[{id:'a',url:'https://a'},{id:'b',url:'https://b'},{id:'c',url:'https://c'}]} as Config;
    const remote=new Map<string,Buffer>();const client={async request(url:string,method='GET',body?:Buffer){if(url.startsWith('https://c'))throw Error('offline');if(method==='PUT'){remote.set(url,body!);return Buffer.from('{}');}return remote.get(url)!;}};
    const objects=new ObjectStorage(cfg,store,client),data=Buffer.from('firmware');let ref=await objects.replicate(data,true);
    assert.equal(ref.replicas.length,2);assert.equal(ref.expires_at,null);
    ref=await objects.replicate(data);assert.equal(ref.expires_at,null);
    await objects.repairAndPrune();assert.deepEqual(await objects.get(ref.hash),data);
    const history=await objects.replicate(Buffer.from('conversation'));await store.put('objects/'+history.hash,{...history,expires_at:new Date(0).toISOString()});
    await objects.repairAndPrune();assert.equal(await store.get<ObjectRef>('objects/'+history.hash),null);assert.deepEqual(await objects.get(ref.hash),data);
    store.available=false;await assert.rejects(()=>objects.repairAndPrune());
  }finally{await rm(root,{recursive:true,force:true});}
});
test('a result with failed audit replication can be recovered without repeating execution',async()=>{
  const root=await mkdtemp(join(tmpdir(),'agentshell-audit-'));try{
    const store=new MemoryStore(),authority={node:'tuf-infra',epoch:'1',lease_id:'l'};await store.put('control/active',authority);
    const cfg={node_id:'tuf-infra',state_dir:root,resources:[]} as Config;const a=action('host.status');a.resource='';
    await assert.rejects(()=>new Executor(cfg,store,{async replicate(){throw Error('replication_failed');}}).execute(a,authority),/replication_failed/);
    const durable=await new Executor(cfg,store).status(a.action_id);assert.equal(durable?.state,'completed');
    let copies=0;const replay=await new Executor(cfg,store,{async replicate(data:Buffer){copies++;return{hash:digest(data.toString()),bytes:data.length,replicas:['a','b'],created_at:new Date().toISOString(),expires_at:null};}}).execute(a,authority);
    assert.deepEqual(replay,durable);assert.equal(copies,1);
  }finally{await rm(root,{recursive:true,force:true});}
});
test('broker restart exposes uncertain submissions without starting a replacement',async()=>{
  const root=await mkdtemp(join(tmpdir(),'agentshell-broker-'));
  try{
    const id=randomUUID();await mkdir(join(root,'agent-runs'));
    const body={client_request_id:id,input:'test'};const record={run_id:id,task_id:id,status:'running',output:'',stage:'Procesando',created:Date.now(),request_hash:digest({agent:'codex',body})};
    await writeFile(join(root,'agent-runs',id+'.json'),JSON.stringify(record));
    const cfg={state_dir:root,agents:{}} as Config;
    const broker=new AgentBroker(cfg,new MemoryStore(),async()=>{throw Error('must_not_resubmit');},async()=>{throw Error('must_not_approve');});
    assert.equal((await broker.status(id)).status,'uncertain');
    assert.equal((await broker.submit('codex',body)).status,'uncertain');
    await assert.rejects(()=>broker.submit('codex',{...body,input:'changed'}),/invalid_run/);
    assert.equal((await new AgentBroker(cfg,new MemoryStore(),async()=>null,async()=>{throw Error();}).status(id)).status,'uncertain');
  }finally{await rm(root,{recursive:true,force:true});}
});
test('OTA validates signed bytes and rejects altered images, foreign URLs and signatures',async()=>{
  const root=await mkdtemp(join(tmpdir(),'agentshell-ota-'));
  try{
    const {publicKey,privateKey}=generateKeyPairSync('rsa',{modulusLength:3072});
    const key=join(root,'release.pem');await writeFile(key,publicKey.export({type:'spki',format:'pem'}));
    const cfg={ota_public_key_file:key,device_gateway_urls:['wss://192.168.4.64:9443/v1/device/ws','wss://192.168.4.82:9443/v1/device/ws']} as Config;
    const hash='a'.repeat(64),manifest={target:'esp32s3',version:'0.1.0',size:1400000,sha256:hash,url:'https://192.168.4.64:9443/v1/device/firmware/'+hash};
    const signed=(value:unknown)=>{const text=JSON.stringify(value);return{manifest:text,signature:sign('sha256',Buffer.from(text),privateKey).toString('base64')};};
    assert.equal(validateRelease(cfg,signed(manifest)).manifest.sha256,hash);
    const release=signed(manifest);assert.throws(()=>validateRelease(cfg,{...release,manifest:JSON.stringify({...manifest,size:1500000})}),/invalid_signature/);
    assert.throws(()=>validateRelease(cfg,signed({...manifest,url:'https://untrusted.example/v1/device/firmware/'+hash})),/invalid_firmware_url/);
    assert.throws(()=>validateRelease(cfg,signed({...manifest,url:manifest.url+'?token=bad'})),/invalid_firmware_url/);
    assert.throws(()=>validateRelease(cfg,signed({...manifest,size:4*1024*1024})));
  }finally{await rm(root,{recursive:true,force:true});}
});
