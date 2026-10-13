import { randomUUID } from 'node:crypto';
import { realpath,mkdir,open,readFile,rename } from 'node:fs/promises';
import { relative,isAbsolute,join } from 'node:path';
import { z } from 'zod';
import type { Config } from './config.js';
import type { Task } from './protocol.js';
import type { Store } from './store.js';
import { CodexAdapter,OpenCodeAdapter,type Adapter,type AgentRun,type AgentEvent } from './adapters.js';
import { Policy,type Approval } from './policy.js';
import { requireEpoch } from './leadership.js';
import { digest } from './security.js';
import {ProviderAdapter} from './provider-adapters.js';
import {liveTask} from './delegation.js';

interface Run {run_id:string;task_id:string;status:string;output:string;stage:string;created:number;request_hash:string;diagnostic?:string;handle?:AgentRun}
export class AgentBroker {
  private adapters=new Map<string,Adapter>();private runs=new Map<string,Run>();
  private submissions=new Map<string,Promise<unknown>>();
  constructor(private cfg:Config,private store:Store,private task:(id:string)=>Promise<Task|null>,private approval:(id:string,request:Record<string,unknown>)=>Promise<Approval>){
    for(const [id,settings] of Object.entries(cfg.agents))if(settings.enabled&&settings.broker){
      if(id==='codex')this.adapters.set(id,new CodexAdapter(settings));
      if(id==='opencode')this.adapters.set(id,new OpenCodeAdapter({...settings,url:settings.local_url}));
      if(['claude','grok'].includes(id)&&(cfg.paid_apis_enabled||cfg.paid_agents_allowed.includes(id)))this.adapters.set(id,new ProviderAdapter(id as 'claude'|'grok',settings));
    }
  }
  has(id:string){return this.adapters.has(id);}
  async shutdown(){
    for(const run of this.runs.values())if(run.status==='running'){run.status='uncertain';run.stage='El worker se reinició; revisar antes de repetir.';await this.persist(run);}
    for(const adapter of this.adapters.values())if(adapter instanceof CodexAdapter)adapter.shutdown();
  }
  async capabilities(id:string){const caps=await this.adapters.get(id)!.capabilities();return {features:{run_submission:caps.available,run_status:true,run_stop:caps.cancel,run_approval_response:false,run_events_sse:false},reason:caps.reason};}
  private async persist(run:Run){
    const dir=join(this.cfg.state_dir,'agent-runs');await mkdir(dir,{recursive:true,mode:0o700});
    const path=join(dir,run.run_id+'.json');const {handle,...record}=run;
    const file=await open(path+'.tmp','w',0o600);try{await file.writeFile(JSON.stringify(record));await file.sync();}finally{await file.close();}
    await rename(path+'.tmp',path);const directory=await open(dir,'r');try{await directory.sync();}finally{await directory.close();}
  }
  async status(id:string){
    if(!z.string().uuid().safeParse(id).success)throw new Error('invalid_run');
    let run=this.runs.get(id);
    if(!run){try{run=JSON.parse(await readFile(join(this.cfg.state_dir,'agent-runs',id+'.json'),'utf8')) as Run;}catch(e){if((e as NodeJS.ErrnoException).code==='ENOENT')throw new Error('invalid_run');throw e;}
      if(run.status==='running'){run.status='uncertain';run.stage='El gateway se reinició; no se repetirá la ejecución.';await this.persist(run);}
      this.runs.set(id,run);
    }const {handle,...publicRun}=run;return publicRun;
  }
  async stop(id:string){await this.status(id);const run=this.runs.get(id)!;if(!run.handle)throw new Error('run_uncertain');await run.handle.cancel();run.status='canceled';await this.persist(run);}
  async submit(agent:string,body:any):Promise<Omit<Run,'handle'>>{
    const id=z.string().uuid().parse(body.client_request_id);
    const pending=this.submissions.get(id);if(pending){await pending;return this.submit(agent,body);}
    const promise=this.start(agent,body,id);this.submissions.set(id,promise);try{return await promise;}finally{this.submissions.delete(id);}
  }
  private async start(agent:string,body:any,id:string){
    const hash=digest({agent,body});
    try{const existing=await this.status(id);if(existing.request_hash!==hash)throw new Error('invalid_run');return existing;}catch(e){if((e as Error).message!=='invalid_run')throw e;if(this.runs.has(id))throw e;}
    const task=await this.task(id);if(!task||task.agent!==agent||!liveTask(task)||(task.execution_node&&task.execution_node!==this.cfg.node_id))throw new Error('invalid_task');
    if(task.parent_task_id&&!liveTask(await this.task(task.parent_task_id)))throw new Error('invalid_parent_task');
    const authority=await this.store.get<any>('control/active');await requireEpoch(this.store,{...authority,epoch:task.epoch});
    let cwd:string;
    if(task.capability==='code.change'){
      const record=await this.store.get<{node:string;path:string}>('worktrees/'+id);if(!record||record.node!==this.cfg.node_id)throw new Error('invalid_worktree');
      cwd=await realpath(record.path);const root=await realpath(this.cfg.state_dir+'/worktrees'),rel=relative(root,cwd);if(!rel||rel.startsWith('..')||isAbsolute(rel))throw new Error('invalid_worktree');
    }else{
      cwd=join(this.cfg.state_dir,'agent-workspaces',id);await mkdir(cwd,{recursive:true,mode:0o700});
    }
    for(const [key,value] of this.runs)if(value.status!=='running'&&value.created<Date.now()-86400000)this.runs.delete(key);
    if(this.runs.size>=512)throw new Error('queue_full');
    const run:Run={run_id:id,task_id:id,status:'running',output:'',stage:'Procesando',created:Date.now(),request_hash:hash};await this.persist(run);this.runs.set(id,run);
    const emit=async(e:AgentEvent)=>{if(['canceled','uncertain'].includes(run.status))return;if(e.type==='stage')run.stage=e.text??'Procesando';if(e.type==='completed'){run.status='completed';run.output=(e.text??'').slice(0,24000);}if(['failed','canceled'].includes(e.type)){run.status=e.type;run.output=(e.text??'').slice(0,24000);}if(e.type!=='delta')await this.persist(run);};
    const approve=async(request:Record<string,unknown>)=>{
      const pending=await this.approval(id,request);const policy=new Policy(this.store);
      while(Date.now()<pending.expires_at&&run.status==='running'){
        await requireEpoch(this.store,authority);const current=await this.store.get<Approval>('approvals/'+pending.approval_id);if(current?.denied)return false;
        if(await policy.authorize(pending.action,pending.approval_id))return true;
        await new Promise(resolve=>setTimeout(resolve,500));
      }return false;
    };
    void(async()=>{
      let watcher:NodeJS.Timeout|undefined,checking=false;
      try{
        run.handle=await this.adapters.get(agent)!.submit(task,{cwd,emit,approve});
        watcher=setInterval(()=>void(async()=>{
          if(checking||run.status!=='running')return;checking=true;
          try{await requireEpoch(this.store,authority);if(task.parent_task_id&&!liveTask(await this.task(task.parent_task_id)))throw Error('invalid_parent_task');}
          catch{run.status='uncertain';run.stage='Autoridad o tarea principal no vigente; ejecución detenida.';await run.handle?.cancel().catch(()=>{});await this.persist(run);}
          finally{checking=false;}
        })().catch(()=>{}),5000);
        await run.handle.done;
      }catch(error){if(run.status==='running'){
        const code=error instanceof Error&&/^codex_(initialize|thread|turn)_(agent_unavailable|agent_rpc_-?\d+)$/.test(error.message)?error.message:undefined;
        run.diagnostic=code;run.status=code?.startsWith('codex_thread_')||code?.startsWith('codex_initialize_')?'failed':'uncertain';
        run.stage=run.status==='failed'?'No se pudo abrir la sesión local de Codex.':'El ejecutor no confirmó el resultado; revisar antes de repetir.';
      }}finally{if(watcher)clearInterval(watcher);await this.persist(run);}
    })().catch(()=>{});
    return this.status(id);
  }
}
