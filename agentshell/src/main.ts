import { createServer,type Server } from 'node:https';
import type { IncomingMessage,ServerResponse } from 'node:http';
import { readFileSync } from 'node:fs';
import { mkdir } from 'node:fs/promises';
import {SagwaAssets,sagwaReply} from './sagwa.js';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { WebSocketServer,WebSocket } from 'ws';
import { loadConfig,type Config } from './config.js';
import { ClusterStore } from './store.js';
import { ClusterLeadership } from './leadership.js';
import { Coordinator,type DeviceEvent } from './coordinator.js';
import { AgentBroker } from './broker.js';
import { Executor } from './executor.js';
import { PeerClient } from './http-client.js';
import { ActionSchema,RuleSchema,type Approval } from './policy.js';
import { certificateIdentity,bearer,readSecret,scrub } from './security.js';
import { decodeEnvelope,envelope,decodeMedia,encodeMedia,Deduplicator,MAX_JSON,MAX_AUDIO,MAX_PHOTO } from './protocol.js';
import { dashboard } from './panel.js';
import { handleA2A,handleMcp } from './standards.js';
import { validateRelease,firmwareHash,firmwareVersion } from './releases.js';
import {EmojiService,speechSegments,selectSpeechEmoji,type EmojiChoice} from './emoji.js';
import {ForegroundTurn} from './foreground-turn.js';
import {WeatherService,type WeatherPacket} from './weather.js';
import {deflateSync} from 'node:zlib';

export async function body(req:IncomingMessage,limit=MAX_JSON):Promise<Buffer> {
  const chunks:Buffer[]=[];let size=0;
  for await(const chunk of req){size+=chunk.length;if(size>limit)throw new Error('message_too_large');chunks.push(Buffer.from(chunk));}
  return Buffer.concat(chunks);
}
function json(res:ServerResponse,status:number,value:unknown){res.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(value));}
function nodeAllowed(req:IncomingMessage,cfg:Config):boolean {const id=certificateIdentity(req);return cfg.peers.some(p=>'node:'+p.id===id);}
export class AgentShellService {
  readonly store:ClusterStore;
  readonly leadership:ClusterLeadership;
  readonly coordinator:Coordinator;
  readonly executor:Executor;readonly broker:AgentBroker;
  readonly client:PeerClient;
  readonly server:Server;
  private ws=new WebSocketServer({noServer:true,maxPayload:MAX_JSON});
  private intervals:NodeJS.Timeout[]=[];
  private sockets=new Set<WebSocket>();
  private lastEpoch='';
  readonly emoji?:EmojiService;
  readonly avatar?:SagwaAssets;
  readonly weather?:WeatherService;
  private displays=new Map<string,(choice:EmojiChoice)=>void>();
  private deviceSpeech=new Map<string,Record<string,unknown>>();
  private speechReplay=new Map<string,(task_id:string,text:string)=>void>();
  constructor(readonly cfg:Config) {
    if(cfg.emoji)this.emoji=new EmojiService(cfg.emoji);
    if(cfg.avatar)this.avatar=new SagwaAssets(cfg.avatar.directory);
    if(cfg.weather&&cfg.roles.includes('gateway'))this.weather=new WeatherService(cfg.weather);
    this.store=new ClusterStore(cfg);this.leadership=new ClusterLeadership(this.store,cfg);
    this.coordinator=new Coordinator(cfg,this.store,this.leadership);this.executor=new Executor(cfg,this.store);this.client=new PeerClient(cfg.tls);
    this.broker=new AgentBroker(cfg,this.store,id=>this.coordinator.task(id),(id,request)=>this.command('agent.approval',{task_id:id,request}));
    this.server=createServer({ca:readFileSync(cfg.tls.ca),cert:readFileSync(cfg.tls.cert),key:readFileSync(cfg.tls.key),requestCert:true,rejectUnauthorized:false,minVersion:'TLSv1.2'},(req,res)=>void this.handle(req,res));
    this.server.on('upgrade',(req,socket,head)=>void(async()=>{
      try {
        const id=certificateIdentity(req);
        if(req.url!=='/v1/device/ws'||!cfg.roles.includes('gateway')||!id?.startsWith('device:')||!cfg.device_ids.includes(id)||await this.store.get('devices/revoked/'+id))throw new Error('unauthorized');
        this.ws.handleUpgrade(req,socket,head,ws=>{this.sockets.add(ws);ws.on('close',()=>this.sockets.delete(ws));void this.device(ws,id);});
      }catch{socket.write('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');socket.destroy();}
    })());
  }
  async leaderURL():Promise<string> {const active=await this.leadership.current().catch(()=>{throw new Error('quorum_unavailable');});const peer=this.cfg.peers.find(p=>p.id===active?.node);if(!peer||active?.epoch==='pending')throw new Error('not_leader');return peer.url;}
  async command(kind:string,payload:Record<string,unknown>):Promise<any> {
    const url=await this.leaderURL();return this.client.json(url+'/internal/coordinator','POST',{kind,payload},kind==='action'||kind==='approve'?650000:10000);
  }
  private async handle(req:IncomingMessage,res:ServerResponse) {
    try {
      const url=new URL(req.url??'/', 'https://agentshell.local');
      if(url.pathname==='/health'&&req.method==='GET'){json(res,200,{status:'ok',version:'0.1.0'});return;}
      if(url.pathname==='/'&&req.method==='GET') {res.writeHead(200,{'content-type':'text/html; charset=utf-8','content-security-policy':"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'",'x-content-type-options':'nosniff'});res.end(dashboard);return;}
      if(url.pathname.startsWith('/internal/')) {
        if(!nodeAllowed(req,this.cfg)){json(res,403,{error:'unauthorized'});return;}
        await this.internal(req,res,url);return;
      }
      const download=url.pathname.match(/^\/v1\/device\/firmware\/([a-f0-9]{64})$/);
      if(download&&req.method==='GET') {
        const device=certificateIdentity(req);
        if(!device||!this.cfg.device_ids.includes(device)||await this.store.get('devices/revoked/'+device)){json(res,403,{error:'unauthorized'});return;}
        if(!await this.store.get('firmware/releases/'+download[1]))throw new Error('invalid_firmware');
        const data=await this.coordinator.objects.get(download[1]!);
        res.writeHead(200,{'content-type':'application/octet-stream','content-length':data.length,'cache-control':'no-store'});res.end(data);return;
      }
      const avatarDownload=url.pathname.match(/^\/v1\/device\/avatar\/([a-f0-9]{64})$/);
      if(avatarDownload&&req.method==='GET'){
        const device=certificateIdentity(req);
        if(!device||!this.cfg.device_ids.includes(device)||await this.store.get('devices/revoked/'+device)){json(res,403,{error:'unauthorized'});return;}
        if(!this.avatar)throw Error('avatar_unavailable');const data=this.avatar.get(avatarDownload[1]!);
        res.writeHead(200,{'content-type':'application/octet-stream','content-length':data.length,'cache-control':'private, max-age=86400'});res.end(data);return;
      }
      const emojiDownload=url.pathname.match(/^\/v1\/device\/emoji\/([a-f0-9]{64})$/);
      if(emojiDownload&&req.method==='GET') {
        const device=certificateIdentity(req);
        if(!device||!this.cfg.device_ids.includes(device)||await this.store.get('devices/revoked/'+device)){json(res,403,{error:'unauthorized'});return;}
        if(!this.emoji)throw new Error('emoji_unavailable');
        const raw=await this.emoji.get(emojiDownload[1]!);
        const compressed=String(req.headers['accept-encoding']??'').split(',').some(s=>s.trim()==='deflate');
        const data=compressed?deflateSync(raw):raw;
        res.writeHead(200,{'content-type':'application/octet-stream','content-length':data.length,'cache-control':'private, max-age=86400','vary':'accept-encoding',...(compressed?{'content-encoding':'deflate'}:{})});res.end(data);return;
      }
      if(url.pathname==='/mcp'&&this.cfg.tools_token_file&&bearer(req,readSecret(this.cfg.tools_token_file))){await handleMcp(req,res,{action:action=>this.command('action',{action})});return;}
      if(url.pathname.startsWith('/v1/muse/')){
        const secret=this.cfg.agents.muse?.secret_file;
        if(!nodeAllowed(req,this.cfg)||!secret||!bearer(req,readSecret(secret))){json(res,403,{error:'unauthorized'});return;}
        if(url.pathname==='/v1/muse/delegates'&&req.method==='GET'){json(res,200,{primary_agent:'muse',delegates:await this.coordinator.registry.delegates()});return;}
        const host=url.pathname.match(/^\/v1\/muse\/tasks\/([a-f0-9-]{36})\/host-status$/);
        if(host&&req.method==='POST'){const p=JSON.parse((await body(req)).toString());json(res,200,await this.command('muse.host-status',{parent_task_id:host[1],node:p.node}));return;}
        const parent=url.pathname.match(/^\/v1\/muse\/tasks\/([a-f0-9-]{36})\/delegates$/);
        if(parent&&req.method==='POST'){json(res,202,await this.command('delegate',{parent_task_id:parent[1],request:JSON.parse((await body(req)).toString())}));return;}
        const child=url.pathname.match(/^\/v1\/muse\/tasks\/([a-f0-9-]{36})\/delegates\/([a-f0-9-]{36})(\/cancel)?$/);
        if(child&&(req.method==='GET'||(child[3]&&req.method==='POST'))){json(res,200,await this.command('delegate.status',{parent_task_id:child[1],task_id:child[2],stop:!!child[3]}));return;}
        json(res,404,{error:'not_found'});return;
      }
      if(!bearer(req,readSecret(this.cfg.admin_token_file))){json(res,401,{error:'unauthorized'});return;}
      const identity='admin:'+this.cfg.node_id;
      if(url.pathname==='/v1/emoji/catalog'&&req.method==='GET'){json(res,200,{ready:!!this.emoji?.ready,provider:this.emoji?.provider??'local',remote_status:this.emoji?.remote?.status??'disabled',openrouter:this.emoji?.openrouter?.health,vercel:this.emoji?.vercel?.status??'disabled',entries:this.emoji?.catalog??[]});return;}
      if(['/v1/emoji/preview','/v1/emoji/display'].includes(url.pathname)&&req.method==='POST') {
        if(!this.emoji)throw new Error('emoji_unavailable');const p=JSON.parse((await body(req)).toString());
        if(typeof p.text!=='string'||p.text.length>8192)throw new Error('invalid_text');
        if(url.pathname.endsWith('/display')) {
          if(!this.cfg.device_ids.includes(p.device_id))throw new Error('device_unavailable');
          const telemetry=await this.store.get<{gateway:string}>('devices/telemetry/'+p.device_id);
          const peer=this.cfg.peers.find(peer=>peer.id===telemetry?.gateway&&peer.id!==this.cfg.node_id);
          if(peer) {
          if(req.headers['x-emoji-forwarded'])throw new Error('device_unavailable');
          const reply=await this.client.request(peer.url+'/v1/emoji/display','POST',Buffer.from(JSON.stringify(p)),{'content-type':'application/json','Authorization':'Bearer '+readSecret(this.cfg.admin_token_file),'x-emoji-forwarded':'1'},30000);
          res.writeHead(200,{'content-type':'application/json','cache-control':'no-store'});res.end(reply);return;
          }
        }
        const spans=speechSegments(p.text);const choices=await selectSpeechEmoji(spans,(text,context)=>this.emoji!.choice(text,context));
        if(url.pathname.endsWith('/display')) {
          if(!this.cfg.device_ids.includes(p.device_id)||!this.displays.has(p.device_id))throw new Error('device_unavailable');
          this.displays.get(p.device_id)!(choices[0]!);
        }
        json(res,200,{choices});return;
      }

      const firmware=url.pathname.match(/^\/v1\/firmware\/([a-f0-9]{64})$/);
      if(firmware&&req.method==='PUT') {
        const data=await body(req,4*1024*1024-1);
        if(firmwareHash(data)!==firmware[1]||data[0]!==0xe9)throw new Error('invalid_firmware');
        const ref=await this.coordinator.objects.replicate(data,true);json(res,201,ref);return;
      }
      if(url.pathname==='/v1/firmware/releases'&&req.method==='POST') {
        const {manifest,release}=validateRelease(this.cfg,JSON.parse((await body(req)).toString()));
        const data=await this.coordinator.objects.get(manifest.sha256);
        if(data.length!==manifest.size||firmwareVersion(data)!==manifest.version)throw new Error('invalid_firmware');
        const ref=await this.coordinator.objects.replicate(Buffer.from(JSON.stringify(release)),true);
        await this.store.put('firmware/releases/'+manifest.sha256,{...release,descriptor_hash:ref.hash});json(res,201,{sha256:manifest.sha256});return;
      }
      if(url.pathname==='/v1/firmware/offer'&&req.method==='POST') {
        const p=JSON.parse((await body(req)).toString());
        if(!this.cfg.device_ids.includes(p.device_id))throw new Error('invalid_device');
        if(!await this.store.get('firmware/releases/'+p.sha256))throw new Error('invalid_firmware');
        await this.store.put('firmware/offers/'+p.device_id,{sha256:p.sha256,attempt_id:randomUUID()});json(res,200,{ok:true});return;
      }
      if(url.pathname==='/mcp'){await handleMcp(req,res,{action:action=>this.command('action',{action})});return;}
      if(url.pathname.startsWith('/a2a')||url.pathname==='/.well-known/agent-card.json'){await handleA2A(req,res,{cfg:this.cfg,task:id=>this.coordinator.task(id),submit:(request,requester,session_id,task_id)=>this.command('submit',{request,requester,session_id,task_id}) as Promise<import('./protocol.js').Task>,cancel:async(task_id,requester)=>{await this.command('cancel',{task_id,requester});}});return;}
      if(url.pathname==='/v1/state'&&req.method==='GET'){json(res,200,{nodes:await this.store.list('nodes/'),agents:await this.coordinator.registry.capabilities(),authority:await this.leadership.current()});return;}
      if(url.pathname==='/v1/nodes'&&req.method==='GET'){json(res,200,Object.values(await this.store.list('nodes/')));return;}
      if(url.pathname==='/v1/agents'&&req.method==='GET'){json(res,200,await this.coordinator.registry.capabilities());return;}
      if(url.pathname==='/v1/orchestration'&&req.method==='GET'){json(res,200,{primary_agent:'muse',delegates:await this.coordinator.registry.delegates()});return;}
      if(url.pathname==='/v1/resources'&&req.method==='GET'){json(res,200,this.cfg.resources.map(r=>({id:r.id,node:r.node,kind:r.kind,tests_configured:!!r.test_argv?.length,deployment_configured:!!r.deploy_argv?.length,health_configured:!!r.health_url})));return;}
      if(url.pathname==='/v1/artifacts'&&req.method==='GET'){json(res,200,{artifacts:Object.values(await this.store.list('artifacts/')),firmware:Object.values(await this.store.list('firmware/releases/')),deployments:await this.store.list('deployments/')});return;}
      if(url.pathname==='/v1/actions'&&req.method==='GET'){json(res,200,Object.values(await this.store.list('actions/')));return;}
      const audit=url.pathname.match(/^\/v1\/actions\/([a-f0-9-]{36})$/);
      if(audit&&req.method==='GET'){const index=await this.store.get<{audit_hash?:string}>('actions/'+audit[1]);if(!index?.audit_hash)throw new Error('resource_unavailable');json(res,200,JSON.parse((await this.coordinator.objects.get(index.audit_hash)).toString()));return;}
      const diff=url.pathname.match(/^\/v1\/tasks\/([a-f0-9-]{36})\/changes$/);
      if(diff&&req.method==='GET'){
        const tree=await this.store.get<{node:string;repository:string}>('worktrees/'+diff[1]);if(!tree)throw new Error('resource_unavailable');
        json(res,200,await this.command('action',{action:{action_id:randomUUID(),task_id:diff[1],node:tree.node,resource:tree.repository,operation:'git.diff',params:{}}}));return;
      }
      if(url.pathname==='/v1/devices'&&req.method==='GET'){json(res,200,await this.store.list('devices/telemetry/'));return;}
      if(url.pathname==='/v1/device-speech'&&req.method==='GET'){json(res,200,Object.fromEntries(this.deviceSpeech));return;}
      if(url.pathname==='/v1/device-speech/replay'&&req.method==='POST'){
        const p=JSON.parse((await body(req)).toString());
        if(!this.cfg.device_ids.includes(p.device_id))throw Error('invalid_device');
        const task=await this.coordinator.task(p.task_id);
        if(!task||task.requester!==p.device_id||task.state!=='completed'||task.parent_task_id)throw Error('invalid_task');
        const play=this.speechReplay.get(p.device_id);if(!play)throw Error('resource_unavailable');
        play(task.task_id,task.summary.slice(0,8192));json(res,202,{accepted:true});return;
      }
      if(url.pathname==='/v1/tasks') {
        if(req.method==='GET'){json(res,200,await this.coordinator.tasks());return;}
        if(req.method==='POST'){json(res,202,await this.command('submit',{request:JSON.parse((await body(req)).toString()),requester:identity,session_id:randomUUID()}));return;}
      }
      const cancel=url.pathname.match(/^\/v1\/tasks\/([a-f0-9-]{36})\/cancel$/);
      if(cancel&&req.method==='POST'){json(res,200,await this.command('cancel',{task_id:cancel[1]}));return;}
      if(url.pathname==='/v1/actions'&&req.method==='POST'){json(res,200,await this.command('action',{action:ActionSchema.parse(JSON.parse((await body(req)).toString()))}));return;}
      if(url.pathname==='/v1/actions/reconcile'&&req.method==='POST'){json(res,200,await this.command('action.reconcile',{action:ActionSchema.parse(JSON.parse((await body(req)).toString()))}));return;}
      if(url.pathname==='/v1/approvals'&&req.method==='GET'){json(res,200,Object.values(await this.store.list<Approval>('approvals/')).filter(a=>!a.consumed&&!a.denied&&a.expires_at>Date.now()));return;}
      const approve=url.pathname.match(/^\/v1\/approvals\/([a-f0-9-]{36})$/);
      if(approve&&req.method==='POST'){const p=JSON.parse((await body(req)).toString());json(res,200,await this.command('approve',{...p,approval_id:approve[1],origin:'admin',identity}));return;}
      if(url.pathname==='/v1/policy/rules') {
        if(req.method==='GET'){json(res,200,Object.values(await this.store.list('policy/rules/')));return;}
        if(req.method==='PUT'){const rule=RuleSchema.parse(JSON.parse((await body(req)).toString()));await this.command('rule',{rule});json(res,200,rule);return;}
      }
      if(url.pathname==='/v1/devices/revoke'&&req.method==='POST'){const p=JSON.parse((await body(req)).toString());if(!this.cfg.device_ids.includes(p.device_id))throw new Error('invalid_device');await this.store.put('devices/revoked/'+p.device_id,{revoked_at:new Date().toISOString()});json(res,200,{ok:true});return;}
      if(url.pathname==='/v1/control/handoff'&&req.method==='POST'){const p=JSON.parse((await body(req)).toString());json(res,200,await this.command('handoff',{target:p.target}));return;}
      const object=url.pathname.match(/^\/v1\/objects\/([a-f0-9]{64})$/);
      if(object&&req.method==='GET'){const data=await this.coordinator.objects.get(object[1]!);res.writeHead(200,{'content-type':'application/octet-stream','cache-control':'no-store'});res.end(data);return;}
      json(res,404,{error:'not_found'});
    }catch(error){if(res.headersSent)res.destroy();else json(res,503,{error:scrub(error)});}
  }
  private async internal(req:IncomingMessage,res:ServerResponse,url:URL) {
    if(/^\/internal\/voice\/gpu\/(lock|renew|unlock)$/.test(url.pathname)&&req.method==='POST'){
      if(this.cfg.node_id!=='mac-mini'||certificateIdentity(req)!=='node:tuf-infra'){json(res,403,{error:'unauthorized'});return;}
      const response=await fetch(this.cfg.voice.url+'/gpu/'+url.pathname.split('/').at(-1),{method:'POST',headers:{Authorization:'Bearer '+readSecret(this.cfg.voice.token_file),'Content-Type':'application/json'},body:(await body(req,4096)).toString(),signal:AbortSignal.timeout(15000),redirect:'error'});
      const raw=await response.text();if(Buffer.byteLength(raw)>4096)throw Error('invalid_gpu_lease');res.writeHead(response.status,{'content-type':'application/json','cache-control':'no-store'});res.end(raw);return;
    }
    if(['/internal/voice/tts/stream','/internal/voice/fallback'].includes(url.pathname)&&req.method==='POST'){
      const controller=new AbortController();res.on('close',()=>controller.abort());
      const response=await fetch(this.cfg.voice.url+(url.pathname.endsWith('/fallback')?'/tts/local-or-api':'/tts/stream'),{method:'POST',headers:{Authorization:'Bearer '+readSecret(this.cfg.voice.token_file),'Content-Type':'application/json'},body:(await body(req)).toString(),signal:controller.signal,redirect:'error'});
      if(!response.ok||response.headers.get('x-sample-rate')!=='16000'||!response.body){json(res,503,{error:'voice_unavailable'});return;}
      res.writeHead(200,{'content-type':'audio/pcm','x-sample-rate':'16000','x-channels':'1','cache-control':'no-store'});
      let total=0;for await(const part of response.body){total+=part.length;if(total>8*1024*1024)throw Error('voice_too_large');if(!res.write(part))await new Promise<void>(resolve=>{res.once('drain',resolve);res.once('close',resolve);});if(res.destroyed)break;}res.end();return;
    }
    const agent=url.pathname.match(/^\/internal\/agents\/(muse|hermes|codex|opencode|claude|grok|grok-bot)(\/v1\/(?:photos\/[a-f0-9-]{36}|capabilities|runs(?:\/[a-zA-Z0-9_-]+(?:\/(?:stop|approval))?)?))$/);
    if(agent&&this.broker.has(agent[1]!)){
      const path=agent[2]!;const id=path.split('/')[3];
      if(path==='/v1/capabilities'&&req.method==='GET')json(res,200,await this.broker.capabilities(agent[1]!));
      else if(path==='/v1/runs'&&req.method==='POST')json(res,202,await this.broker.submit(agent[1]!,JSON.parse((await body(req)).toString())));
      else if(id&&path.endsWith('/stop')&&req.method==='POST'){await this.broker.stop(id);json(res,200,{ok:true});}
      else if(id&&req.method==='GET')json(res,200,await this.broker.status(id));else throw new Error('unsupported');return;
    }
    if(agent){
      const settings=this.cfg.agents[agent[1]!];
      if(!settings?.enabled||!settings.local_url)throw new Error('agent_unavailable');
      const endpoint=new URL(settings.local_url);
      if(!['127.0.0.1','localhost','[::1]'].includes(endpoint.hostname))throw new Error('invalid_peer');
      const response=await fetch(settings.local_url+agent[2],{method:req.method,headers:{'content-type':req.method==='PUT'?'application/octet-stream':'application/json',...(settings.secret_file?{Authorization:'Bearer '+readSecret(settings.secret_file)}:{}),...(req.method==='POST'?{'Idempotency-Key':String(req.headers['idempotency-key']??randomUUID())}:{})},...(req.method==='PUT'?{body:new Uint8Array(await body(req,MAX_PHOTO))}:req.method==='POST'?{body:(await body(req)).toString()}:{}),signal:AbortSignal.timeout(15000),redirect:'error'});
      if(!response.ok)throw new Error('agent_unavailable');const data=await response.text();if(Buffer.byteLength(data)>MAX_JSON)throw new Error('message_too_large');res.writeHead(response.status,{'content-type':'application/json','cache-control':'no-store'});res.end(data);return;
    }
    const photo=url.pathname.match(/^\/internal\/photos\/([a-f0-9-]{36})$/);
    if(photo&&req.method==='PUT'&&this.cfg.roles.includes('coordinator')){
      await this.leadership.assert();const requester=String(req.headers['x-requester']??'');
      if(!this.cfg.device_ids.includes(requester))throw new Error('invalid_device');
      const metadata=JSON.parse(Buffer.from(String(req.headers['x-photo-request']??''),'base64').toString());
      json(res,202,await this.coordinator.submitPhoto(await body(req,MAX_PHOTO),metadata.request,requester,metadata.session_id,photo[1]!));return;
    }
    const object=url.pathname.match(/^\/internal\/objects\/([a-f0-9]{64})$/);
    if(object&&this.cfg.roles.includes('objects')) {
      if(req.method==='PUT'){await this.coordinator.objects.putLocal(object[1]!,await body(req,16*1024*1024));json(res,200,{ok:true});return;}
      if(req.method==='GET'){res.writeHead(200,{'content-type':'application/octet-stream'});res.end(await this.coordinator.objects.local(object[1]!));return;}
    }
    if(url.pathname==='/internal/actions'&&req.method==='POST'&&this.cfg.roles.includes('executor')) {const p=JSON.parse((await body(req)).toString());json(res,200,await this.executor.execute(p.action,p.authority,p.approval_id));return;}
    if(url.pathname==='/internal/actions/reconcile'&&req.method==='POST'&&this.cfg.roles.includes('executor')) {const p=JSON.parse((await body(req)).toString());json(res,200,await this.executor.reconcile(p.action,p.authority));return;}
    const action=url.pathname.match(/^\/internal\/actions\/([a-f0-9-]{36})$/);
    if(action&&req.method==='GET'){json(res,200,await this.executor.status(action[1]!));return;}
    if(url.pathname==='/internal/coordinator'&&req.method==='POST'&&this.cfg.roles.includes('coordinator')) {
      await this.leadership.assert();const {kind,payload:p}=JSON.parse((await body(req)).toString());let result:unknown;
      if(kind==='agent.approval')result=await this.coordinator.requestAgentApproval(p.task_id,p.request);
      else if(kind==='submit')result=await this.coordinator.submit(p.request,p.requester,p.session_id,p.task_id);
      else if(kind==='delegate')result=await this.coordinator.delegate(p.parent_task_id,p.request);
      else if(kind==='delegate.status')result=await this.coordinator.delegatedTask(p.parent_task_id,p.task_id,p.stop);
      else if(kind==='muse.host-status')result=await this.coordinator.museHostStatus(p.parent_task_id,p.node);
      else if(kind==='cancel'){await this.coordinator.cancel(p.task_id,p.requester);result={ok:true};}
      else if(kind==='snapshot')result=await this.coordinator.snapshot(p.requester,p.task_id);
      else if(kind==='settings')result=await this.coordinator.deviceSettings();
      else if(kind==='events')result=await this.coordinator.events(p.requester,p.after);
      else if(kind==='action')result=await this.coordinator.action(ActionSchema.parse(p.action));
      else if(kind==='action.reconcile')result=await this.coordinator.reconcileAction(ActionSchema.parse(p.action));
      else if(kind==='rule'){const rule=RuleSchema.parse(p.rule);await this.store.put('policy/rules/'+rule.rule_id,rule);result={ok:true};}
      else if(kind==='approve') {
        if(!['device','admin'].includes(p.origin)||!['approve','deny'].includes(p.decision))throw new Error('invalid_approval');
        if(p.origin==='device'&&!this.cfg.device_ids.includes(p.identity))throw new Error('invalid_device');
        if(p.origin==='device'){
          await this.coordinator.requireDeviceApprovalOwner(p.approval_id,p.task_id,p.identity);
        }
        const approval=await this.coordinator.policy.decide(p.approval_id,p.action_hash,p.origin,p.identity,p.decision);
        if(!approval.denied&&approval.physical_by&&(approval.risk!=='destructive'||approval.admin_by)&&approval.action.operation!=='agent.request') {
          await this.coordinator.executeApproved(approval.approval_id);await this.coordinator.continueTask(approval.action.task_id);
        }
        result=approval;
      } else if(kind==='handoff'){await this.leadership.yieldTo(p.target);result={ok:true};}
      else throw new Error('unsupported');
      json(res,200,result);return;
    }
    json(res,404,{error:'not_found'});
  }
  private async device(ws:WebSocket,id:string) {
    let session='';let sessionReady=false;let sequence=0;let canceledSpeech=0;let polling=false;let offered='';let capabilities:unknown={};
    let recovering=0;let recoveryEpoch=0;let audioControlSequence=0;
    let settingsAt=0;let speechController:AbortController|null=null;let avatarOffered=false;let preferences:Record<string,boolean>={};
    const foreground=new ForegroundTurn();
    const clientRoutesTranscripts=()=>!!capabilities&&typeof capabilities==='object'&&(capabilities as Record<string,unknown>).client_routes_transcripts===true;
    const weatherSnapshot=():WeatherPacket=>this.weather?.snapshot()??{schema:1,available:false,reason:'unconfigured'};
    const sendSettings=async()=>{const now=Date.now();if(now-settingsAt<2000)return;settingsAt=now;send('device.settings',{...await this.command('settings',{}),preferences,weather:weatherSnapshot(),transcript_routing:clientRoutesTranscripts()?'client':'gateway',...(this.avatar?{voice:{style:'feminine-es-latam',engines:['chatterbox','kokoro','openrouter'],monthly_api_limit_usd:5},pet:{local:true,states:12,sounds:true,sensors:true},response_words:{min:5,max:10}}:{})});
      if(this.avatar&&!avatarOffered){const base=this.cfg.device_gateway_urls?.[this.cfg.node_id==='tuf-infra'?0:1];if(base){send('ui.avatar',this.avatar.offer(base));avatarOffered=true;}}};
    const dedupe=new Deduplicator();
    let media:{id:string;task:string;kind:1|2;next:number;size:number;chunks:Buffer[]}|null=null;
    let chain=Promise.resolve();let pending=0;const canceledTurns=new Set<string>();
    const send=(type:string,payload:Record<string,unknown>,task:string|null=null,seq?:number)=>{if(ws.readyState===WebSocket.OPEN&&ws.bufferedAmount<256*1024)ws.send(JSON.stringify(envelope(session,seq??sequence,type,payload,task)));};
    const sendSnapshot=async(task_id?:string)=>{
      recovering++;recoveryEpoch++;
      try {
      canceledSpeech++;speechController?.abort();
      const snapshot=await this.command('snapshot',{requester:id,...(task_id?{task_id}:{})});
      for(const item of snapshot.tasks??[]){const task=await this.coordinator.task(item.task_id);if(task){const reply=sagwaReply(task.summary);item.summary=task.brief??reply.brief;if(Buffer.byteLength(item.summary)>512)item.summary='El resultado está listo. Toca el texto para leerlo.';delete item.full_text;}}
      if(!Number.isSafeInteger(snapshot.sequence)||snapshot.sequence<0)throw Error('invalid_sequence');
      // A poll already awaiting I/O must also fail its epoch check. Cancel any
      // synthesis again immediately before installing the recovery frontier.
      canceledSpeech++;speechController?.abort();
      sequence=Math.max(sequence,snapshot.sequence);
      foreground.recover(snapshot.foreground_task_id??snapshot.tasks?.[0]?.task_id??null,snapshot.sequence);
      send('device.snapshot',{...snapshot,weather:weatherSnapshot(),transcript_routing:clientRoutesTranscripts()?'client':'gateway'});
      } finally { recovering--; }
    };
    let emojiGeneration=0;
    const showEmoji=(choice:EmojiChoice,task:string|null=null)=>{
      const base=this.cfg.device_gateway_urls?.[this.cfg.node_id==='tuf-infra'?0:1];
      if(!base)return;
      send('ui.emoji',{codepoint:choice.entry.id,name:choice.entry.name,sha256:choice.asset.sha256,size:choice.asset.size,url:new URL(base.replace(/^wss:/,'https:')).origin+'/v1/device/emoji/'+choice.asset.sha256},task);
    };
    const contextual=(text:unknown,task:string|null)=>{
      if(this.avatar||typeof text!=='string'||!text.trim()||!this.emoji)return;
      const generation=++emojiGeneration;
      void this.emoji.choice(text).then(choice=>{
        if(generation===emojiGeneration&&(!task||!canceledTurns.has(task)))showEmoji(choice,task);
      }).catch(()=>{});
    };
    const speech=async(event:DeviceEvent,explicitReplay=false)=>{
      const trace:Record<string,unknown>={event_received_at:new Date().toISOString(),agent_finished_at:event.payload.agent_finished_at,durable_reply_at:event.payload.durable_reply_at};
      const report=(stage:string,extra:Record<string,unknown>={})=>this.deviceSpeech.set(id,{task_id:event.task_id,session_id:session,source_session_id:event.payload.session_id,stage,at:new Date().toISOString(),...trace,...extra});
      if(!sessionReady||recovering||preferences.voice_enabled===false)return;
      speechController?.abort();speechController=new AbortController();const controller=speechController;
      emojiGeneration++;const generation=++canceledSpeech;const text=sagwaReply(String(event.payload.text??'')).brief.trim();
      if(!text||!event.task_id)return;
      report('synthesizing');trace.tts_started_at=new Date().toISOString();
      const timeout=setTimeout(()=>controller.abort(),120000);let sent=0,n=0,carry=Buffer.alloc(0);
      const stream=randomUUID();let began=0;
      try{
        let response:{headers:Headers;body:AsyncIterable<Uint8Array>};
        try{
          const localStop=new AbortController();
          const abortLocal=()=>localStop.abort();controller.signal.addEventListener('abort',abortLocal,{once:true});if(controller.signal.aborted)abortLocal();
          // TUF requests only its GPU engine. The gateway owns Mac failover, including a frozen daemon.
          const headerDeadline=this.cfg.node_id==='tuf-infra'?setTimeout(abortLocal,1900):undefined;
          let local:Response;
          try{local=await fetch(this.cfg.voice.url+'/tts/stream',{method:'POST',headers:{Authorization:'Bearer '+readSecret(this.cfg.voice.token_file),'Content-Type':'application/json'},body:JSON.stringify({text,local_only:this.cfg.node_id==='tuf-infra'}),signal:localStop.signal,redirect:'error'});}
          finally{clearTimeout(headerDeadline);}
          if(!local.ok||!local.body||local.headers.get('x-sample-rate')!=='16000'||local.headers.get('x-channels')!=='1'){await local.body?.cancel();throw Error('tts_unavailable');}
          response={headers:local.headers,body:local.body as AsyncIterable<Uint8Array>};
        }catch(error){
          const mac=this.cfg.peers.find(p=>p.id==='mac-mini');if(this.cfg.node_id!=='tuf-infra'||!mac||controller.signal.aborted)throw error;
          const remote=await this.client.stream(mac.url+'/internal/voice/fallback',Buffer.from(JSON.stringify({text})),controller.signal);
          if(remote.headers['x-sample-rate']!=='16000'||remote.headers['x-channels']!=='1'){remote.destroy();throw Error('invalid_audio');}
          response={headers:new Headers({'x-sample-rate':'16000','x-channels':'1'}),body:remote};trace.tts_fallback_host='mac-mini';
        }
        if(generation!==canceledSpeech||canceledTurns.has(event.task_id)||!foreground.selected(event.task_id)){controller.abort();return;}
        trace.tts_ready_at=new Date().toISOString();report('sending');
        // This transport-local counter never advances the durable event cursor.
        send('audio.start',{stream_id:stream,sample_rate:16000,streaming:true,control_sequence:++audioControlSequence,explicit_replay:explicitReplay},event.task_id);began=Date.now();
        for await(const part of response.body){
          if(generation!==canceledSpeech||!foreground.selected(event.task_id)||ws.readyState!==WebSocket.OPEN)break;
          carry=Buffer.concat([carry,Buffer.from(part)]);if(sent+carry.length>8*1024*1024)throw Error('voice_too_large');
          while(carry.length>=2){const length=Math.min(4096,carry.length-carry.length%2);const data=carry.subarray(0,length);carry=carry.subarray(length);
            while((sent/32>Date.now()-began+300||ws.bufferedAmount>32768)&&generation===canceledSpeech&&ws.readyState===WebSocket.OPEN)await new Promise(resolve=>setTimeout(resolve,10));
            if(generation!==canceledSpeech||!foreground.selected(event.task_id)||ws.readyState!==WebSocket.OPEN)break;
            if(!sent)trace.first_audio_frame_at=new Date().toISOString();
            ws.send(encodeMedia({session_id:session,task_id:event.task_id,stream_id:stream,sequence:n++,kind:3,data}));sent+=data.length;
          }
        }
        if(generation===canceledSpeech){if(carry.length)throw Error('invalid_pcm');send('audio.end',{stream_id:stream},event.task_id);report('sent',{pcm_bytes:sent,duration_ms:sent/32});}
      }catch{if(generation===canceledSpeech){send('audio.stop',{},event.task_id);report(controller.signal.aborted?'canceled':'tts_rejected');}}
      finally{clearTimeout(timeout);controller.abort();if(speechController===controller)speechController=null;}

    };
    const timer=setInterval(()=>void(async()=>{
      if(!sessionReady||recovering||!session||polling||ws.readyState!==WebSocket.OPEN)return;polling=true;
      const epoch=recoveryEpoch;
      const stale=()=>recovering>0||epoch!==recoveryEpoch||!sessionReady||ws.readyState!==WebSocket.OPEN;
      try {
        if(await this.store.get('devices/revoked/'+id)){ws.close(1008,'revoked');return;}
        const offer=await this.store.get<{sha256:string;attempt_id:string}>('firmware/offers/'+id);
        if(offer&&offered!==offer.attempt_id){const release=await this.store.get<Record<string,unknown>>('firmware/releases/'+offer.sha256);if(release){send('ota.offer',{...release,attempt_id:offer.attempt_id});offered=offer.attempt_id;}}
        if(Date.now()-settingsAt>30000)await sendSettings();
        const events:DeviceEvent[]=await this.command('events',{requester:id,after:sequence});
        if(stale())return;
        // The transport session changes on gateway failover. Authorization and
        // turn freshness belong to the device's task, not that old socket UUID.
        for(const event of events){
          if(stale())return;
          if(event.sequence<=sequence)continue;
          if(!foreground.accepts(event.task_id)||(event.task_id&&canceledTurns.has(event.task_id))){sequence=event.sequence;continue;}
          let payload=event.payload;
          if(event.type==='task.state'&&event.task_id){
            const task=await this.coordinator.task(event.task_id);
            if(stale())return;
            if(task){const reply=sagwaReply(task.summary);const brief=task.brief??reply.brief;payload={...payload,summary:Buffer.byteLength(brief)>8192?'El resultado está listo. Toca el texto para leerlo.':brief};delete payload.full_text;}
          }
          sequence=Math.max(sequence,event.sequence);
          send(event.type,payload,event.task_id,event.sequence);
          if(event.type==='speech.ready'&&foreground.acceptsSpeech(event.task_id,event.sequence))void speech(event).catch(error=>{this.deviceSpeech.set(id,{stage:'failed',task_id:event.task_id,session_id:session,error:scrub(error),at:new Date().toISOString()});});
          else if(event.type==='task.state'&&event.payload.state==='completed')contextual(event.payload.summary,event.task_id);
        }
      }catch{if(!stale())send('ui.state',{mode:'offline',message:'Coordinador no disponible.'});}finally{polling=false;}
    })(),500);
    const display=(choice:EmojiChoice)=>showEmoji(choice);
    const replay=(task_id:string,text:string)=>{
      if(!sessionReady||recovering||!foreground.selected(task_id)||ws.readyState!==WebSocket.OPEN||canceledTurns.has(task_id)||['selecting_visuals','synthesizing','sending'].includes(String(this.deviceSpeech.get(id)?.stage)))throw Error('invalid_task');
      canceledSpeech++;
      void speech({sequence,type:'speech.ready',task_id,payload:{text,session_id:session}},true).catch(error=>{this.deviceSpeech.set(id,{stage:'failed',task_id,session_id:session,error:scrub(error),at:new Date().toISOString()});});
    };
    ws.on('close',()=>{clearInterval(timer);media=null;canceledSpeech++;speechController?.abort();emojiGeneration++;if(this.displays.get(id)===display)this.displays.delete(id);if(this.speechReplay.get(id)===replay)this.speechReplay.delete(id);});
    ws.on('message',(raw,binary)=>{
      if(!binary){try{const control=decodeEnvelope(Buffer.from(raw as Buffer));
        if(session&&control.session_id===session&&['audio.cancel','task.cancel'].includes(control.type)){
          if(!dedupe.accept(control.message_id))return;
          canceledSpeech++;speechController?.abort();emojiGeneration++;send('audio.stop',{});
          if(control.type==='task.cancel'&&control.task_id){if(media?.task===control.task_id)media=null;canceledTurns.add(control.task_id);while(canceledTurns.size>64)canceledTurns.delete(canceledTurns.values().next().value!);void this.command('cancel',{task_id:control.task_id,requester:id}).catch(()=>{});}return;
        }
      }catch{ws.close(1008,'invalid_message');return;}}
      if(++pending>64){ws.close(1013,'queue_full');return;}
      let responseTask:string|null=null;
      chain=chain.then(async()=>{
      if(binary){const f=decodeMedia(Buffer.from(raw as Buffer));responseTask=f.task_id;if(f.session_id===session&&canceledTurns.has(f.task_id))return;if(!media)throw new Error('invalid_media');
        if(f.session_id!==session||f.stream_id!==media.id||f.task_id!==media.task||f.kind!==media.kind||f.sequence!==media.next++)throw new Error('invalid_media');
        media.size+=f.data.length;if(media.size>(media.kind===1?MAX_AUDIO:MAX_PHOTO))throw new Error('message_too_large');media.chunks.push(f.data);return;}
      const msg=decodeEnvelope(Buffer.from(raw as Buffer));responseTask=msg.task_id;if(!dedupe.accept(msg.message_id))return;
      if(msg.type==='device.hello') {
        sessionReady=false;canceledSpeech++;speechController?.abort();
        audioControlSequence=0;
        session=msg.session_id;sequence=Number(msg.payload.last_sequence??0);if(!Number.isSafeInteger(sequence)||sequence<0)throw new Error('invalid_sequence');
        this.displays.set(id,display);
        this.speechReplay.set(id,replay);
        capabilities=msg.payload.capabilities??{};
        await this.store.put('devices/capabilities/'+id,{capabilities:msg.payload.capabilities,gateway:this.cfg.node_id,received_at:new Date().toISOString()});
        await sendSnapshot();preferences=await this.store.get<Record<string,boolean>>('devices/preferences/'+id)??{};settingsAt=0;await sendSettings();sessionReady=true;return;
      }
      if(!session||msg.session_id!==session)throw new Error('invalid_session');
      if(msg.task_id&&canceledTurns.has(msg.task_id))return;
      if(msg.type==='device.resume'){
        if(!msg.task_id)throw Error('invalid_task');
        await sendSnapshot(msg.task_id);return;
      }
      if(msg.type==='device.preferences'){
        const keys=['voice_enabled','pet_enabled','pet_sounds','pet_sensors'];if(Object.keys(msg.payload).some(k=>!keys.includes(k))||keys.some(k=>typeof msg.payload[k]!=='boolean'))throw Error('invalid_preferences');preferences=msg.payload as Record<string,boolean>;await this.store.put('devices/preferences/'+id,preferences);if(preferences.voice_enabled===false){canceledSpeech++;speechController?.abort();send('audio.stop',{});}return;
      }
      if(msg.type==='task.read'){
        const task=await this.coordinator.task(msg.task_id??'');if(!task||task.requester!==id)throw Error('invalid_task');
        const raw=Buffer.from(sagwaReply(task.summary).detail);let offset=0;
        while(offset<raw.length&&ws.readyState===WebSocket.OPEN){while(ws.bufferedAmount>32768&&ws.readyState===WebSocket.OPEN)await new Promise(resolve=>setTimeout(resolve,10));let end=Math.min(raw.length,offset+4096);while(end<raw.length&&(raw[end]!&0xc0)===0x80)end--;send('ui.result',{offset,text:raw.subarray(offset,end).toString('utf8'),complete:end===raw.length},task.task_id);offset=end;}return;
      }
      if(msg.type==='voice.sample'){if(!msg.task_id)throw Error('invalid_task');replay(msg.task_id,'Hola, Josmar. Estoy aquí para ayudarte.');return;}
      if(msg.type==='device.refresh'){await sendSettings();}
      else if(msg.type==='task.submit'){const taskId=msg.task_id??randomUUID();foreground.select(taskId);const task=await this.command('submit',{request:msg.payload,requester:id,session_id:session,task_id:taskId});send('task.accepted',task,task.task_id);contextual(msg.payload.goal,task.task_id);}
      else if(msg.type==='task.cancel'){await this.command('cancel',{task_id:msg.task_id,requester:id});}
      else if(msg.type==='approval.decision'){
        if(!msg.task_id)throw Error('invalid_task');
        try{
          await this.command('approve',{...msg.payload,task_id:msg.task_id,origin:'device',identity:id});
          send('approval.result',{approval_id:msg.payload.approval_id,status:'accepted',decision:msg.payload.decision},msg.task_id);
        }catch{
          send('approval.result',{approval_id:msg.payload.approval_id,status:'failed'},msg.task_id);
        }
      }
      else if(msg.type==='audio.cancel'){canceledSpeech++;speechController?.abort();send('audio.stop',{});}
      else if(msg.type==='device.telemetry'){await this.store.put('devices/telemetry/'+id,{readings:msg.payload,capabilities,session_id:session,gateway:this.cfg.node_id,received_at:new Date().toISOString()});}
      else if(msg.type==='media.start') {
        canceledSpeech++;speechController?.abort();emojiGeneration++;send('audio.stop',{});
        if(media||!msg.task_id||typeof msg.payload.stream_id!=='string'||![1,2].includes(Number(msg.payload.kind)))throw new Error('invalid_media');
        foreground.select(msg.task_id);
        media={id:msg.payload.stream_id,task:msg.task_id,kind:Number(msg.payload.kind) as 1|2,next:0,size:0,chunks:[]};
      } else if(msg.type==='media.end') {
        if(!media||media.id!==msg.payload.stream_id)throw new Error('invalid_media');const finished=media;media=null;
        if(canceledTurns.has(finished.task))return;
        if(finished.kind===1){const response=await fetch(this.cfg.voice.url+'/stt',{method:'POST',headers:{Authorization:'Bearer '+readSecret(this.cfg.voice.token_file),'Content-Type':'application/octet-stream'},body:Buffer.concat(finished.chunks),signal:AbortSignal.timeout(120000)});
          if(!response.ok)throw new Error('agent_unavailable');const transcript:any=await response.json();if(typeof transcript.text!=='string'||!transcript.text.trim()||Buffer.byteLength(transcript.text)>4096)throw new Error('invalid_audio');if(canceledTurns.has(finished.task)||ws.readyState!==WebSocket.OPEN)return;
          send('voice.transcript',{text:transcript.text},finished.task);
          // New Core firmware routes the transcript once on-device; 0.2 keeps
          // its existing automatic Muse submission when the capability is absent.
          if(clientRoutesTranscripts())return;
          contextual(transcript.text,finished.task);
          await this.command('submit',{request:{goal:transcript.text,target:String(msg.payload.target??this.cfg.node_id),capability:msg.payload.capability??'conversation',preferred_agent:msg.payload.preferred_agent??'auto',context_refs:[]},requester:id,session_id:session,task_id:finished.task});
        }else {if(canceledTurns.has(finished.task))return;const metadata={session_id:session,request:{goal:String(msg.payload.goal??'Describe la foto solicitada desde el CoreS3.'),target:String(msg.payload.target??'mac-mini'),capability:'conversation',preferred_agent:msg.payload.preferred_agent??'auto',context_refs:['ephemeral-photo:'+finished.task]}};await this.client.request((await this.leaderURL())+'/internal/photos/'+finished.task,'PUT',Buffer.concat(finished.chunks),{'content-type':'application/octet-stream','x-requester':id,'x-photo-request':Buffer.from(JSON.stringify(metadata)).toString('base64')});send('camera.received',{bytes:finished.size,message:'Foto enviada a Muse para procesar.'},finished.task);}
      }else throw new Error('unsupported');
    }).catch(error=>{media=null;send('error',{code:scrub(error)},responseTask);}).finally(()=>{pending--;});});
  }
  async start() {
    await mkdir(this.cfg.state_dir,{recursive:true,mode:0o700});
    await new Promise<void>(resolve=>this.server.listen(this.cfg.listen.port,this.cfg.listen.host,resolve));
    if(this.cfg.roles.includes('coordinator'))this.leadership.start();
    this.intervals.push(setInterval(()=>void(async()=>{
      try{
        await this.store.put('nodes/'+this.cfg.node_id,{node:this.cfg.node_id,roles:this.cfg.roles,received_at:new Date().toISOString(),uptime_s:process.uptime(),memory_bytes:process.memoryUsage().rss});
        const authority=await this.leadership.current();if(authority?.node===this.cfg.node_id&&authority.epoch!==this.lastEpoch){this.lastEpoch=authority.epoch;await this.coordinator.reconcile();}
      }catch{}
    })(),5000));
    this.intervals.push(setInterval(()=>void this.coordinator.objects.repairAndPrune().catch(()=>{}),60000));
  }
  async stop(){await this.weather?.stop();await this.emoji?.stop();for(const timer of this.intervals)clearInterval(timer);for(const ws of this.sockets)ws.close();await this.leadership.stop();this.store.close();await new Promise<void>(resolve=>this.server.close(()=>resolve()));}
}
if(process.argv[1]===fileURLToPath(import.meta.url)) {
  const cfg=loadConfig(process.argv[2]??'config.json');const service=new AgentShellService(cfg);
  await service.start();console.log(JSON.stringify({event:'started',node:cfg.node_id,port:cfg.listen.port}));
  for(const signal of ['SIGINT','SIGTERM'] as const)process.on(signal,()=>void service.stop().then(()=>process.exit(0)));
}
