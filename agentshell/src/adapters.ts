import { spawn,type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import {mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import { createOpencodeClient } from '@opencode-ai/sdk';
import type { Config } from './config.js';
import type { Task } from './protocol.js';
import { PeerClient } from './http-client.js';
import { run } from './executor.js';
import { ProviderAdapter } from './provider-adapters.js';

export interface AgentEvent {type:'delta'|'preview'|'stage'|'approval'|'completed'|'failed'|'canceled';text?:string;data?:Record<string,unknown>}
export interface AgentCapabilities {id:string;available:boolean;streaming:boolean;cancel:boolean;approvals:boolean;reason?:string}
export interface AgentContext {cwd:string;photo?:Buffer;emit:(event:AgentEvent)=>Promise<void>;approve:(request:Record<string,unknown>)=>Promise<boolean>}
export interface AgentRun {id:string;done:Promise<void>;cancel:()=>Promise<void>}
export interface Adapter {
  capabilities():Promise<AgentCapabilities>;
  submit(task:Task,ctx:AgentContext):Promise<AgentRun>;
  status(id:string):Promise<string>;
  cancel(id:string):Promise<void>;
}
class Rpc {
  private next=0;
  private pending=new Map<number,{resolve:(value:any)=>void;reject:(error:Error)=>void;timer:NodeJS.Timeout}>();
  onMessage:(message:any)=>void=()=>{};
  readonly child:ChildProcessWithoutNullStreams;
  constructor(command:string,args:string[],cwd:string,home?:string) {
    this.child=spawn(command,args,{cwd,shell:false,env:{PATH:process.env.PATH,HOME:home??process.env.HOME,...(home?{CODEX_HOME:join(home,'.codex')}:{ }),LANG:'C.UTF-8'},stdio:['pipe','pipe','pipe']});
    const lines=createInterface({input:this.child.stdout});
    lines.on('line',line=>{try {
      if(line.length>1024*1024)throw new Error('invalid_rpc');
      const message=JSON.parse(line);
      if(message.method)this.onMessage(message);
      else if(typeof message.id==='number') {
        const p=this.pending.get(message.id);if(!p)return;clearTimeout(p.timer);this.pending.delete(message.id);
        if(message.error)p.reject(new Error('agent_rpc_'+String(message.error.code??'unknown')));else p.resolve(message.result);
      }
    }catch{this.child.kill();}});
    this.child.stderr.on('data',()=>{});
    const rejectAll=()=>{for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(new Error('agent_unavailable'));}this.pending.clear();};
    this.child.on('error',rejectAll);this.child.on('exit',rejectAll);
  }
  request(method:string,params:unknown,timeout=60000):Promise<any> {
    const id=++this.next;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('agent_timeout'));},timeout);
      this.pending.set(id,{resolve,reject,timer});this.send({id,method,params});
    });
  }
  send(message:unknown){if(!this.child.stdin.destroyed)this.child.stdin.write(JSON.stringify(message)+'\n');}
  close(){this.child.kill('SIGTERM');}
}
export class CodexAdapter implements Adapter {
  private runs=new Map<string,{rpc:Rpc;thread:string;turn:string;state:string}>();
  private health?:Promise<boolean>;private checked=0;
  constructor(private settings:Config['agents'][string]){}
  async capabilities():Promise<AgentCapabilities> {
    if(!this.health||Date.now()-this.checked>60000){this.checked=Date.now();this.health=this.probe();}
    const available=await this.health;
    return {id:'codex',available,streaming:true,cancel:true,approvals:true,...(!available?{reason:'Autenticación, configuración o ejecutable local no disponible.'}:{})};
  }
  private async probe(){
    let rpc:Rpc|undefined;
    try{
      if(!this.settings.enabled)return false;
      const home=this.settings.agent_home;
      if((await run([this.settings.command??'codex',...this.settings.args,'login','status'],process.cwd(),10000,undefined,home,home?{CODEX_HOME:join(home,'.codex')}:{})).code!==0)return false;
      const cwd=home?join(home,'.codex','health-workspace'):process.cwd();if(home)await mkdir(cwd,{recursive:true,mode:0o700});
      rpc=new Rpc(this.settings.command??'codex',[...this.settings.args,'app-server','--listen','stdio://'],cwd,home);
      await rpc.request('initialize',{clientInfo:{name:'cores3_agentshell',version:'0.1.0'},capabilities:{}},10000);rpc.send({method:'initialized'});
      await rpc.request('config/read',{includeLayers:false,cwd},10000);
      await rpc.request('thread/start',{cwd,ephemeral:true,approvalPolicy:'on-request',...(this.settings.permission_profile?{config:{default_permissions:this.settings.permission_profile}}:{sandbox:'workspace-write'})},10000);return true;
    }catch{return false;}finally{rpc?.close();}
  }
  async submit(task:Task,ctx:AgentContext):Promise<AgentRun> {
    if(!this.settings.enabled)throw new Error('agent_unavailable');
    const rpc=new Rpc(this.settings.command??'codex',[...this.settings.args,'app-server','--listen','stdio://'],ctx.cwd,this.settings.agent_home);
    let resolveDone!:()=>void,rejectDone!:(e:Error)=>void;
    const done=new Promise<void>((resolve,reject)=>{resolveDone=resolve;rejectDone=reject;});done.catch(()=>{});
    const id=randomUUID();const state={rpc,thread:'',turn:'',state:'running'};this.runs.set(id,state);
    let text='';let eventChain=Promise.resolve();
    rpc.onMessage=message=>{
      eventChain=eventChain.then(async()=>{
        if(message.id!==undefined&&message.method) {
          let result:unknown;
          if(message.method.endsWith('requestApproval')) {
            const allowed=await ctx.approve({method:message.method,...message.params});
            result=message.method==='item/permissions/requestApproval'?{permissions:{},scope:'turn'}:{decision:allowed?'accept':'decline'};
          } else if(message.method==='item/tool/requestUserInput') result={answers:{}};
          else result={};
          rpc.send({id:message.id,result});return;
        }
        const params=message.params??{};
        if(message.method==='item/agentMessage/delta'){const delta=String(params.delta??'');text+=delta;await ctx.emit({type:'delta',text:delta});}
        if(message.method==='item/started')await ctx.emit({type:'stage',text:String(params.item?.type??'Procesando')});
        if(message.method==='turn/completed') {
          state.state=params.turn?.status??'failed';
          if(state.state==='completed'){await ctx.emit({type:'completed',text});resolveDone();}
          else{await ctx.emit({type:state.state==='interrupted'?'canceled':'failed',text:'El agente no completó la tarea.'});rejectDone(new Error('agent_request_failed'));}
          rpc.close();
        }
      }).catch(()=>{rejectDone(new Error('agent_request_failed'));rpc.close();});
    };
    rpc.child.on('exit',()=>{if(state.state==='running')rejectDone(new Error('agent_unavailable'));});
    let phase='initialize';
    try {
      await rpc.request('initialize',{clientInfo:{name:'cores3_agentshell',title:'AgentShell',version:'0.1.0'},capabilities:{}});
      rpc.send({method:'initialized'});
      phase='thread';
      const thread=await rpc.request('thread/start',{cwd:ctx.cwd,...(this.settings.permission_profile?{config:{default_permissions:this.settings.permission_profile}}:{sandbox:'workspace-write'}),approvalPolicy:'on-request',...(this.settings.model?{model:this.settings.model}:{})});
      state.thread=thread.thread.id;
      phase='turn';
      const turn=await rpc.request('turn/start',{threadId:state.thread,input:[{type:'text',text:task.goal}],cwd:ctx.cwd,approvalPolicy:'on-request',...(this.settings.permission_profile?{}:{sandboxPolicy:{type:'workspaceWrite',writableRoots:[ctx.cwd],networkAccess:false,excludeTmpdirEnvVar:true,excludeSlashTmp:true}})});
      state.turn=turn.turn.id;
    }catch(error){rpc.close();this.runs.delete(id);const code=error instanceof Error&&/^agent_rpc_-?\d+$/.test(error.message)?error.message:'agent_unavailable';throw new Error('codex_'+phase+'_'+code);}
    return {id,done,cancel:()=>this.cancel(id)};
  }
  async status(id:string){return this.runs.get(id)?.state??'unknown';}
  async cancel(id:string){const run=this.runs.get(id);if(!run)throw new Error('unsupported');await run.rpc.request('turn/interrupt',{threadId:run.thread,turnId:run.turn});}
  shutdown(){for(const run of this.runs.values())run.rpc.close();}
}
export class HttpAdapter implements Adapter {
  protected runs=new Map<string,{controller:AbortController;state:string}>();
  private peer?:PeerClient;
  private capabilityCache?:{until:number;value:AgentCapabilities};
  private capabilityPending?:Promise<AgentCapabilities>;
  constructor(readonly id:string,protected settings:Config['agents'][string],tls?:Config['tls']){if(tls)this.peer=new PeerClient(tls);}
  protected headers():Record<string,string>{return {...(this.settings.secret_file?{Authorization:'Bearer '+readFileSync(this.settings.secret_file,'utf8').trim()}:{}),'Content-Type':'application/json'};}
  protected async json(path:string,method='GET',body?:unknown,signal?:AbortSignal,extra:Record<string,string>={}):Promise<any> {
    if(!this.settings.url)throw new Error('agent_unavailable');
    if(this.settings.url.includes('/internal/agents/')&&this.peer)return JSON.parse((await this.peer.request(this.settings.url+path,method,body===undefined?undefined:Buffer.from(JSON.stringify(body)),{...this.headers(),...extra})).toString());
    const response=await fetch(this.settings.url+path,{method,headers:{...this.headers(),...extra},body:body===undefined?undefined:JSON.stringify(body),signal:signal??AbortSignal.timeout(10000),redirect:'error'});
    if(!response.ok){await response.body?.cancel();throw new Error('agent_unavailable');}return response.json();
  }
  async capabilities():Promise<AgentCapabilities> {
    if(!this.settings.enabled)return {id:this.id,available:false,streaming:false,cancel:false,approvals:false};
    if(this.capabilityCache&&this.capabilityCache.until>Date.now())return this.capabilityCache.value;
    if(this.capabilityPending)return this.capabilityPending;
    this.capabilityPending=this.readCapabilities();
    try{const value=await this.capabilityPending;this.capabilityCache={until:Date.now()+2000,value};return value;}finally{this.capabilityPending=undefined;}
  }
  private async readCapabilities():Promise<AgentCapabilities> {
    let available=false;let features:any={};
    if(this.settings.enabled)try{features=await this.json('/v1/capabilities');available=features.features?.run_submission===true;}catch{}
    return {id:this.id,available,streaming:false,cancel:features.features?.run_stop===true,approvals:(features.features?.run_approval_response===true||features.features?.run_approval===true),...(features.reason?{reason:String(features.reason).slice(0,256)}:{})};
  }
  async submit(task:Task,ctx:AgentContext):Promise<AgentRun> {
    const caps=await this.capabilities();if(!caps.available)throw new Error('agent_unavailable');
    const controller=new AbortController();
    if(ctx.photo){if(this.id!=='muse'||!this.peer||!this.settings.url)throw new Error('vision_unsupported');await this.peer.request(this.settings.url+'/v1/photos/'+task.task_id,'PUT',ctx.photo,{'content-type':'application/octet-stream'});}
    const created:any=await this.json('/v1/runs','POST',{input:task.goal,session_id:this.id==='hermes'?task.task_id:task.session_id,client_request_id:task.task_id,target:task.target,capability:task.capability,...(this.settings.model?{model:this.settings.model}:{}),...(ctx.photo?{photo_id:task.task_id}:{}),instructions:'Responde en español. Solicita autorización para cambios. Las acciones de infraestructura deben pasar por las herramientas MCP de AgentShell. El nodo destino de esta tarea es '+task.target+'. No inventes observaciones: consulta host_status para diagnosticar.'},undefined,{'Idempotency-Key':task.task_id});const id=String(created.run_id);if(!id||id==='undefined')throw new Error('invalid_run');
    return this.attach(id,ctx,controller,caps);
  }
  async attach(id:string,ctx:AgentContext,controller=new AbortController(),caps?:AgentCapabilities):Promise<AgentRun> {
    caps??=await this.capabilities();
    const state={controller,state:'running'};this.runs.set(id,state);
    let lastStage:string|undefined,lastPreview:string|undefined;
    const done=(async()=>{
      for(;;) {
        if(controller.signal.aborted){state.state='canceled';await ctx.emit({type:'canceled'});return;}
        const current=await this.json('/v1/runs/'+encodeURIComponent(id));
        if(current.status==='waiting_for_approval') {
          const allowed=await ctx.approve({agent:this.id,run_id:id,approval:current.approval??current.pending_approval??{}});
          if(!caps!.approvals)throw new Error('unsupported');
          await this.json('/v1/runs/'+encodeURIComponent(id)+'/approval','POST',{decision:allowed?'once':'deny'});
        } else if(['completed','failed','cancelled','canceled','interrupted','uncertain'].includes(current.status)) {
          const finished=this.id==='muse'&&typeof current.finished_at==='number'&&Number.isFinite(current.finished_at)&&current.finished_at>0&&current.finished_at<Date.now()/1000+60?new Date(current.finished_at*1000).toISOString():undefined;
          state.state=current.status;await ctx.emit({type:current.status==='completed'?'completed':['failed','uncertain'].includes(current.status)?'failed':'canceled',text:String(current.output||current.error||current.stage||'No se ha confirmado el resultado de la ejecución.'),...(finished?{data:{agent_finished_at:finished}}:{})});return;
        } else {
          if(this.id==='muse'&&typeof current.preview==='string'&&current.preview.trim()){
            const text=current.preview.slice(0,1024);
            if(text!==lastPreview){await ctx.emit({type:'preview',text});lastPreview=text;}
          } else {
          const text=typeof current.stage==='string'&&current.stage.trim()?current.stage:this.id==='muse'?'Esperando respuesta de Muse.':current.status==='running'?'Procesando tu solicitud.':'Esperando al agente.';
          if(text!==lastStage){await ctx.emit({type:'stage',text});lastStage=text;}
          }
        }
        await new Promise(resolve=>setTimeout(resolve,1000));
      }
    })();done.catch(()=>{});return {id,done,cancel:()=>this.cancel(id)};
  }
  async status(id:string){return this.runs.get(id)?.state??String((await this.json('/v1/runs/'+encodeURIComponent(id))).status);}
  async cancel(id:string){await this.json('/v1/runs/'+encodeURIComponent(id)+'/stop','POST',{});this.runs.get(id)?.controller.abort();}
}
export class OpenCodeAdapter implements Adapter {
  private client:ReturnType<typeof createOpencodeClient>;
  private runs=new Map<string,string>();
  constructor(private settings:Config['agents'][string]) {
    this.client=createOpencodeClient({baseUrl:settings.url,headers:settings.secret_file?{Authorization:'Basic '+Buffer.from('opencode:'+readFileSync(settings.secret_file,'utf8').trim()).toString('base64')}:{}});
  }
  async capabilities():Promise<AgentCapabilities>{let available=false;if(this.settings.enabled)try{available=!(await this.client.project.list()).error;}catch{}return {id:'opencode',available,streaming:false,cancel:true,approvals:false};}
  async submit(task:Task,ctx:AgentContext):Promise<AgentRun>{
    if(!this.settings.enabled)throw new Error('agent_unavailable');
    const created=await this.client.session.create({body:{title:task.goal.slice(0,80)},query:{directory:ctx.cwd}});
    if(created.error||!created.data)throw new Error('agent_unavailable');
    const id=created.data.id;this.runs.set(id,'running');
    const done=(async()=>{await ctx.emit({type:'stage',text:'OpenCode procesando'});
      const response=await this.client.session.prompt({path:{id},query:{directory:ctx.cwd},body:{parts:[{type:'text',text:task.goal}],tools:{bash:false}}});
      if(response.error||!response.data){this.runs.set(id,'failed');throw new Error('agent_request_failed');}
      const text=response.data.parts.filter(p=>p.type==='text').map(p=>(p as {text:string}).text).join('\n');this.runs.set(id,'completed');await ctx.emit({type:'completed',text});})();done.catch(()=>{});
    return {id,done,cancel:()=>this.cancel(id)};
  }
  async status(id:string){return this.runs.get(id)??'unknown';}
  async cancel(id:string){const response=await this.client.session.abort({path:{id}});if(response.error)throw new Error('unsupported');this.runs.set(id,'canceled');}
}
export class DisabledAdapter implements Adapter {
  constructor(readonly id:string,readonly reason:string){}
  async capabilities():Promise<AgentCapabilities>{return{id:this.id,available:false,streaming:false,cancel:false,approvals:false,reason:this.reason};}
  async submit():Promise<AgentRun>{throw new Error('agent_unavailable');}
  async status(){return 'unavailable';}
  async cancel(){throw new Error('unsupported');}
}
export class AgentRegistry {
  adapters=new Map<string,Adapter>();
  private workers=new Map<string,Adapter>();
  constructor(private cfg:Config) {
    const make=(id:string,settings:Config['agents'][string]):Adapter=>{
      if(!settings.enabled || ((settings.paid_api||['claude','grok'].includes(id))&&!cfg.paid_apis_enabled&&!cfg.paid_agents_allowed.includes(id)))return new DisabledAdapter(id,'Integración desactivada.');
      if(settings.url?.includes('/internal/agents/'))return new HttpAdapter(id,settings,cfg.tls);
      if(id==='codex')return new CodexAdapter(settings);
      if(id==='opencode')return new OpenCodeAdapter(settings);
      if(['hermes','muse'].includes(id))return new HttpAdapter(id,settings,cfg.tls);
      if(['claude','grok'].includes(id))return new ProviderAdapter(id as 'claude'|'grok',settings);
      return new DisabledAdapter(id,'Requiere un transporte compatible configurado.');
    };
    for(const [id,settings] of Object.entries(cfg.agents))this.adapters.set(id,make(id,settings));
    for(const [node,agents] of Object.entries(cfg.agent_workers??{}))
      for(const [id,settings] of Object.entries(agents))this.workers.set(node+':'+id,make(id,settings));
  }
  async capabilities(){return Promise.all([...this.adapters.values()].map(a=>a.capabilities()));}
  async delegates(){return Promise.all([...this.workers].map(async([key,a])=>({...await a.capabilities(),node:key.split(':')[0]})));}
  adapter(task:Task){return task.execution_node?this.workers.get(task.execution_node+':'+task.agent):this.adapters.get(task.agent);}
  async choose(task:Task):Promise<Adapter> {
    const id=task.preferred_agent==='auto'?'muse':task.preferred_agent;
    const a=task.execution_node?this.workers.get(task.execution_node+':'+id):this.adapters.get(id);
    if(a&&(await a.capabilities()).available)return a;
    throw new Error('agent_unavailable');
  }
}
