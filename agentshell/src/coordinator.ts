import {sagwaReply} from './sagwa.js';
import { randomUUID } from 'node:crypto';
import type { Config } from './config.js';
import { TaskRequestSchema,type Task,type TaskRequest } from './protocol.js';
import type { Store } from './store.js';
import type { Leadership } from './leadership.js';
import { AgentRegistry,HttpAdapter,type AgentEvent,type AgentRun } from './adapters.js';
import { Policy,type Approval,type Action } from './policy.js';
import { PeerClient } from './http-client.js';
import { ObjectStorage } from './objects.js';
import { digest } from './security.js';
import {DelegateSchema,liveTask,requireMuseParent} from './delegation.js';

export interface DeviceEvent {sequence:number;type:string;task_id:string|null;payload:Record<string,unknown>}
interface TaskIndex {hash:string;updated_at:string;created_at?:string;state:Task['state'];requester:string;epoch:string}
export class Coordinator {
  readonly registry:AgentRegistry;
  readonly policy:Policy;
  readonly objects:ObjectStorage;
  private peers:PeerClient;
  private active=new Map<string,AgentRun>();
  private launching=new Set<string>();private photos=new Map<string,Buffer>();
  private delegating=new Set<string>();
  constructor(readonly cfg:Config,readonly store:Store,readonly leadership:Leadership) {
    this.registry=new AgentRegistry(cfg);this.policy=new Policy(store);this.objects=new ObjectStorage(cfg,store);this.peers=new PeerClient(cfg.tls);
  }
  async task(id:string):Promise<Task|null> {
    const index=await this.store.get<TaskIndex>('tasks/'+id);
    return index?JSON.parse((await this.objects.get(index.hash)).toString()):null;
  }
  async save(task:Task) {
    await this.leadership.assert(task.epoch);
    task.updated_at=new Date().toISOString();
    const ref=await this.objects.replicate(Buffer.from(JSON.stringify(task)));
    const next={hash:ref.hash,updated_at:task.updated_at,created_at:task.created_at,state:task.state,requester:task.requester,epoch:task.epoch} satisfies TaskIndex;
    for(let n=0;n<5;n++){
      const previous=await this.store.get<TaskIndex>('tasks/'+task.task_id);
      if(previous?.state==='canceled'&&task.state!=='canceled')throw new Error('task_canceled');
      await this.leadership.assert(task.epoch);
      if(await this.store.comparePut('tasks/'+task.task_id,previous,next))return;
    }
    throw new Error('quorum_unavailable');
  }
  async submit(raw:unknown,requester:string,session_id:string,id:string=randomUUID(),link?:{parent_task_id:string;execution_node:string}):Promise<Task> {
    const request=TaskRequestSchema.parse(raw);const authority=await this.leadership.assert();
    const existing=await this.task(id);
    if(existing){const original:TaskRequest={goal:existing.goal,target:existing.target,capability:existing.capability,preferred_agent:existing.preferred_agent,context_refs:existing.context_refs};
      if(existing.requester!==requester||digest(original)!==digest(request)||existing.parent_task_id!==link?.parent_task_id||(link&&existing.execution_node!==link.execution_node))throw new Error('invalid_task');return existing;}
    const task:Task={...request,...link,task_id:id,requester,session_id,agent:'',state:'queued',summary:'Tarea recibida.',epoch:authority.epoch,created_at:new Date().toISOString(),updated_at:new Date().toISOString()};
    await this.save(task);await this.publish(task,'task.state',{state:task.state,summary:task.summary});
    void this.launch(task);return task;
  }
  async submitPhoto(data:Buffer,request:unknown,requester:string,session:string,id:string):Promise<Task>{
    if(data.length!==153600||this.photos.size>=4)throw new Error('invalid_photo');
    this.photos.set(id,data);try{return await this.submit(request,requester,session,id);}catch(error){this.photos.delete(id);throw error;}
  }
  async tasks(requester?:string,limit?:number):Promise<Task[]> {
    const rows=await this.store.list<TaskIndex>('tasks/');const tasks:Task[]=[];
    let entries=Object.entries(rows).filter(([,index])=>Date.parse(index.updated_at)>Date.now()-30*86400000&&(!requester||index.requester===requester)).sort(([,a],[,b])=>(b.created_at??b.updated_at).localeCompare(a.created_at??a.updated_at));
    if(limit!==undefined){const recent=new Set(entries.slice(0,limit).map(([key])=>key));entries=entries.filter(([key,index])=>recent.has(key)||['queued','running','needs_approval','reconciling'].includes(index.state));}
    // Slow history reads must not exceed the device hello/recovery deadline.
    for(let at=0;at<entries.length;at+=8){
      const batch=await Promise.allSettled(entries.slice(at,at+8).map(([key])=>this.task(key.slice('tasks/'.length))));
      for(const result of batch)if(result.status==='fulfilled'&&result.value)tasks.push(result.value);
    }
    return tasks.sort((a,b)=>b.created_at.localeCompare(a.created_at));
  }
  async publish(task:Task,type:string,payload:Record<string,unknown>) {
    await this.leadership.assert(task.epoch);
    if(task.parent_task_id){
      const parent=await this.task(task.parent_task_id);if(!parent||!liveTask(parent))return;
      if(type==='speech.ready'||type==='task.state')return;
      if(type==='ui.state')payload={...payload,mode:'delegating',actor:'Muse',message:'Muse usa '+task.agent+' en '+task.execution_node+'. '+String(payload.message??'')};
    }
    const headKey='device-events/'+task.requester+'/head';
    for(let n=0;n<10;n++) {
      const head=await this.store.get<number>(headKey);const sequence=(head??0)+1;
      if(await this.store.compareBatch(headKey,head,sequence,'device-events/'+task.requester+'/'+String(sequence).padStart(16,'0'),{sequence,type,task_id:task.parent_task_id??task.task_id,payload} satisfies DeviceEvent)) {
        if(sequence>256)await this.store.delete('device-events/'+task.requester+'/'+String(sequence-256).padStart(16,'0'));return;
      }
    }
    throw new Error('quorum_unavailable');
  }
  async events(requester:string,after:number):Promise<DeviceEvent[]> {
    const head=await this.store.get<number>('device-events/'+requester+'/head');
    if((head??0)<=after)return [];
    const rows=await this.store.list<DeviceEvent>('device-events/'+requester+'/');
    return Object.values(rows).filter(e=>typeof e==='object'&&e.sequence>after).sort((a,b)=>a.sequence-b.sequence);
  }
  async snapshot(requester:string,selected?:string) {
    // Read the event boundary before task state: events emitted during recovery
    // remain available afterwards instead of being hidden by a later head.
    const recovery_sequence=await this.store.get<number>('device-events/'+requester+'/head')??0;
    const owned=await this.tasks(requester,40);
    const tasks=owned.filter(t=>!t.parent_task_id).slice(0,10);
    if(selected){
      const task=owned.find(t=>t.task_id===selected)??await this.task(selected);
      if(!task||task.requester!==requester||task.parent_task_id)throw Error('invalid_task');
      tasks.splice(0,tasks.length,task,...tasks.filter(t=>t.task_id!==selected));
      if(!owned.some(t=>t.task_id===selected))owned.push(task);
    }
    const approvals=Object.values(await this.store.list<Approval>('approvals/')).flatMap(a=>{
      const task=owned.find(t=>t.task_id===a.action.task_id);
      return !a.consumed&&!a.denied&&a.expires_at>Date.now()&&task
        ? [{...a,task_id:task.parent_task_id??task.task_id}] : [];
    });
    return {foreground_task_id:tasks[0]?.task_id??null,tasks:tasks.slice(0,5).map(t=>({...t,goal:t.goal.slice(0,256),summary:(t.brief??t.summary).slice(0,512),context_refs:[]})),approvals:approvals.filter(a=>a.task_id===tasks[0]?.task_id).slice(0,1),...await this.deviceSettings(),authority:await this.leadership.current(),sequence:recovery_sequence};
  }
  async deviceSettings(){
    const nodes=Object.values(await this.store.list<Record<string,unknown>>('nodes/')).map(n=>({node:n.node,available:typeof n.received_at==='string'&&Date.now()-Date.parse(n.received_at)<15000}));
    return {primary_agent:'muse',voice:{language:'es-419',style:'feminine_warm',monthly_api_limit_usd:5},pet:{local_sensors:true,offline_poses:true},nodes,agents:await this.registry.capabilities(),resources:this.cfg.resources.map(r=>({id:r.id,node:r.node,kind:r.kind}))};
  }
  async requireDeviceApprovalOwner(approval_id:string,foreground_id:string,requester:string){
    const pending=await this.store.get<Approval>('approvals/'+approval_id);
    const task=pending?await this.task(pending.action.task_id):null;
    if(!foreground_id||!task||!liveTask(task)||task.requester!==requester||
       (task.parent_task_id??task.task_id)!==foreground_id)throw Error('invalid_approval');
  }
  async delegate(parentId:string,raw:unknown){
    const request=DelegateSchema.parse(raw);await this.leadership.assert();
    const parent=requireMuseParent(await this.task(parentId));
    if(this.delegating.has(parentId))throw Error('delegation_busy');
    this.delegating.add(parentId);
    try{
      const children=(await this.tasks()).filter(t=>t.parent_task_id===parentId);
      if(!children.some(t=>t.task_id===request.request_id)&&(children.length>=16||children.filter(liveTask).length>=4))throw Error('queue_full');
      const resource=this.cfg.resources.find(r=>r.id===request.target);
      if(request.capability==='code.change'&&(!resource||resource.kind!=='repository'||resource.node!==request.node))throw Error('invalid_target');
      if(request.capability!=='conversation'&&request.target!==parent.target&&!(request.capability==='code.change'&&resource?.node===parent.target))throw Error('invalid_target');
      const child=await this.submit({goal:request.goal,target:request.target,capability:request.capability,preferred_agent:request.agent,context_refs:[]},parent.requester,parent.session_id,request.request_id,{parent_task_id:parentId,execution_node:request.node});
      // A cancellation during submission must also stop the new child.
      if(!liveTask((await this.task(parentId))!))await this.cancel(child.task_id,parent.requester);
      return child;
    }finally{this.delegating.delete(parentId);}
  }
  async delegatedTask(parentId:string,id:string,stop=false){
    const parent=await this.task(parentId),child=await this.task(id);
    if(!parent||parent.agent!=='muse'||!child||child.parent_task_id!==parentId)throw Error('invalid_task');
    if(stop)await this.cancel(id,parent.requester);
    const task=stop?(await this.task(id))!:child;
    return {task_id:task.task_id,agent:task.agent,node:task.execution_node,state:task.state,output:task.summary};
  }
  async museHostStatus(parentId:string,node:string){
    const parent=requireMuseParent(await this.task(parentId));
    const target=this.cfg.resources.find(r=>r.id===parent.target)?.node??parent.target;
    if(node!==target)throw Error('invalid_target');
    return this.action({action_id:randomUUID(),task_id:parentId,node,resource:'',operation:'host.status',params:{}});
  }
  async cancel(id:string,requester?:string) {
    const task=await this.task(id);if(!task||(requester&&task.requester!==requester))throw new Error('invalid_task');
    await this.leadership.assert();
    const live=this.active.get(id);
    if(live)await live.cancel();
    else if(task.run_id)await this.registry.adapter(task)?.cancel(task.run_id);
    task.epoch=(await this.leadership.assert()).epoch;task.state='canceled';task.summary='Cancelación solicitada.';
    await this.save(task);await this.publish(task,'task.state',{state:task.state,summary:task.summary});
    for(const child of (await this.tasks()).filter(t=>t.parent_task_id===id&&liveTask(t)))await this.cancel(child.task_id,task.requester);
  }
  async action(action:Action):Promise<{result?:unknown;approval?:Approval}> {
    const authority=await this.leadership.assert();
    const peer=this.cfg.peers.find(p=>p.id===action.node);if(!peer)throw new Error('invalid_target');
    if(action.operation!=='host.status'&&!this.cfg.resources.some(r=>r.node===action.node&&r.id===action.resource))throw new Error('resource_unavailable');
    const approved=await this.policy.automatic(action);
    if(!approved){const approval=await this.policy.request(action);const task=await this.task(action.task_id);if(task)await this.publish(task,'approval.request',approval as unknown as Record<string,unknown>);return {approval};}
    const result=await this.peers.json(peer.url+'/internal/actions','POST',{action,authority},650000);return {result};
  }
  async executeApproved(id:string):Promise<unknown> {
    const approval=await this.store.get<Approval>('approvals/'+id);if(!approval)throw new Error('invalid_approval');
    const authority=await this.leadership.assert();const peer=this.cfg.peers.find(p=>p.id===approval.action.node);if(!peer)throw new Error('invalid_target');
    return this.peers.json(peer.url+'/internal/actions','POST',{action:approval.action,authority,approval_id:id},650000);
  }
  async reconcileAction(action:Action){const authority=await this.leadership.assert();const peer=this.cfg.peers.find(p=>p.id===action.node);if(!peer)throw new Error('invalid_target');return this.peers.json(peer.url+'/internal/actions/reconcile','POST',{action,authority});}
  async requestAgentApproval(id:string,request:Record<string,unknown>):Promise<Approval>{
    const task=await this.task(id);if(!task)throw new Error('invalid_task');await this.leadership.assert(task.epoch);
    if(Buffer.byteLength(JSON.stringify(request))>16000)throw new Error('message_too_large');
    const action:Action={action_id:randomUUID(),task_id:task.task_id,node:this.cfg.node_id,resource:task.target,operation:'agent.request',params:{agent:task.agent,request}};
    const pending=await this.policy.request(action);task.state='needs_approval';await this.save(task);await this.publish(task,'approval.request',pending as unknown as Record<string,unknown>);return pending;
  }
  private async approval(task:Task,request:Record<string,unknown>):Promise<boolean> {
    const action:Action={action_id:randomUUID(),task_id:task.task_id,node:this.cfg.node_id,resource:task.target,operation:'agent.request',params:{agent:task.agent,request}};
    // Opaque native agent commands are never granted broad automatic infrastructure permission.
    const pending=await this.policy.request(action);task.state='needs_approval';await this.save(task);
    await this.publish(task,'approval.request',pending as unknown as Record<string,unknown>);
    while(Date.now()<pending.expires_at) {
      await this.leadership.assert(task.epoch);
      const current=await this.store.get<Approval>('approvals/'+pending.approval_id);
      if(current?.denied)return false;
      if(await this.policy.authorize(action,pending.approval_id)){task.state='running';await this.save(task);return true;}
      await new Promise(resolve=>setTimeout(resolve,500));
    }
    return false;
  }
  private async launch(task:Task) {
    if(this.launching.has(task.task_id)||this.active.has(task.task_id))return;
    this.launching.add(task.task_id);
    try {
      if(!task.execution_node&&task.preferred_agent!=='auto'&&task.preferred_agent!=='muse'){
        const node=this.cfg.resources.find(r=>r.id===task.target)?.node??task.target;
        if(this.cfg.agent_workers?.[node]?.[task.preferred_agent])task.execution_node=node;
      }
      const adapter=await this.registry.choose(task);task.agent=(await adapter.capabilities()).id;
      let cwd=this.cfg.state_dir;
      if(task.parent_task_id&&!liveTask((await this.task(task.parent_task_id))!))throw Error('task_canceled');
      if(task.capability==='code.change'&&task.agent!=='muse') {
        const resource=this.cfg.resources.find(r=>r.id===task.target&&r.kind==='repository');
        if(!resource)throw new Error('resource_unavailable');
        const existing=await this.store.get<{path:string}>('worktrees/'+task.task_id);
        if(existing)cwd=existing.path;
        else {
          const action:Action={action_id:randomUUID(),task_id:task.task_id,operation:'git.worktree',node:resource.node,resource:resource.id,params:{}};
          const reply=await this.action(action);
          if(reply.approval){task.state='needs_approval';await this.save(task);return;}
          cwd=(await this.store.get<{path:string}>('worktrees/'+task.task_id))?.path??'';
          if(!cwd)throw new Error('resource_unavailable');
        }
      }
      task.state='running';await this.save(task);await this.publish(task,'ui.state',{mode:'thinking',actor:task.agent,message:'Procesando tu solicitud.'});
      const run=await adapter.submit(task,{cwd,photo:this.photos.get(task.task_id),emit:event=>this.agentEvent(task,event),approve:request=>this.approval(task,request)});
      this.active.set(task.task_id,run);task.run_id=run.id;
      const current=await this.task(task.task_id);if(current?.state==='canceled'){await run.cancel();return;}await this.save(task);
      await run.done;
    }catch {
      try{if((await this.task(task.task_id))?.state!=='canceled'){task.state='failed';task.summary='Agente o recurso no disponible. No se ha cambiado de proveedor de pago.';await this.save(task);await this.publish(task,'task.state',{state:task.state,summary:task.summary});}}catch{}
    }finally{this.active.delete(task.task_id);this.launching.delete(task.task_id);this.photos.delete(task.task_id);}
  }
  private async agentEvent(task:Task,event:AgentEvent) {
    const current=await this.task(task.task_id);if(current?.state==='canceled')return;
    if(event.type==='delta')return; // Persist complete answers, not one object per token.
    if(event.type==='preview'){await this.publish(task,'ui.state',{mode:'thinking',actor:task.agent,message:'Respuesta en curso:\n'+(event.text??'').slice(0,1024)});return;}
    if(event.type==='stage'){await this.publish(task,'ui.state',{mode:'executing',actor:task.agent,message:event.text??''});return;}
    task.state=event.type==='completed'?'completed':event.type==='canceled'?'canceled':'failed';const reply=sagwaReply((event.text??'').slice(0,65536));task.summary=reply.detail;task.brief=reply.brief;
    await this.save(task);await this.publish(task,'task.state',{state:task.state,summary:reply.brief.slice(0,8192),agent:task.agent});
    // The completed parent is already durable and fences its delegates. Do not
    // hold the user's voice behind a full history scan and child cancellation.
    if(task.state==='completed')await this.publish(task,'speech.ready',{text:reply.brief.slice(0,8192),session_id:task.session_id,durable_reply_at:new Date().toISOString(),...(typeof event.data?.agent_finished_at==='string'&&event.data.agent_finished_at.length<64&&Number.isFinite(Date.parse(event.data.agent_finished_at))?{agent_finished_at:event.data.agent_finished_at}:{})});
    if(!task.parent_task_id)for(const child of (await this.tasks()).filter(t=>t.parent_task_id===task.task_id&&liveTask(t)))await this.cancel(child.task_id,task.requester);
  }
  async continueTask(id:string) {const task=await this.task(id);if(!task)throw new Error('invalid_task');task.epoch=(await this.leadership.assert()).epoch;if(task.state==='needs_approval'&&!this.active.has(id)){task.state='queued';await this.save(task);void this.launch(task);}}
  async reconcile() {
    const authority=await this.leadership.assert();
    for(const task of await this.tasks()) {
      if(task.epoch===authority.epoch||!['running','queued','reconciling','needs_approval'].includes(task.state))continue;
      task.epoch=authority.epoch;
      if(task.run_id) {
        task.state='reconciling';task.summary='Consultando la ejecución anterior antes de continuar.';
        await this.save(task);
        const adapter=this.registry.adapter(task);
        if(adapter instanceof HttpAdapter){
          void(async()=>{try{const run=await adapter.attach(task.run_id!,{cwd:this.cfg.state_dir,emit:event=>this.agentEvent(task,event),approve:request=>this.approval(task,request)});this.active.set(task.task_id,run);await run.done;}catch{try{task.state='interrupted';task.summary='No se puede confirmar la ejecución anterior. No se ha repetido la tarea.';await this.save(task);}catch{}}finally{this.active.delete(task.task_id);}})();
        }else{task.state='interrupted';task.summary='El adaptador no permite recuperar esta ejecución. Se requiere revisión.';await this.save(task);}
      }else if(task.state==='running'){
        // Submission may have reached the agent before run_id was persisted.
        task.state='interrupted';task.summary='Envío anterior incierto; revisar antes de repetir.';await this.save(task);
      }else{task.state='queued';await this.save(task);void this.launch(task);}
    }
  }
}
