import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {AgentRegistry,type Adapter} from '../src/adapters.js';
import {Coordinator} from '../src/coordinator.js';
import {DelegateSchema,requireMuseParent} from '../src/delegation.js';
import type {Config} from '../src/config.js';
import type {Task} from '../src/protocol.js';

function task(extra:Partial<Task>={}):Task{return {task_id:randomUUID(),goal:'Revisa',target:'mac-mini',capability:'conversation',preferred_agent:'auto',context_refs:[],requester:'device:test',session_id:randomUUID(),agent:'muse',state:'running',summary:'',epoch:'1',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),...extra};}
function adapter(id:string,available=true):Adapter{return {capabilities:async()=>({id,available,streaming:false,cancel:true,approvals:false}),submit:async()=>{throw Error('unused');},status:async()=>'',cancel:async()=>{}};}
test('Muse receives every automatic activity; unavailable Muse never starts a delegate or paid fallback',async()=>{
 const registry=new AgentRegistry({agents:{},paid_apis_enabled:false,paid_agents_allowed:[],agent_workers:{}} as unknown as Config);
 registry.adapters.set('muse',adapter('muse'));registry.adapters.set('codex',adapter('codex'));registry.adapters.set('hermes',adapter('hermes'));
 for(const capability of ['conversation','code.change','infra.diagnose'] as const)assert.equal((await (await registry.choose(task({capability}))).capabilities()).id,'muse');
 registry.adapters.set('muse',adapter('muse',false));await assert.rejects(()=>registry.choose(task({capability:'code.change'})),/agent_unavailable/);
 assert.equal((await (await registry.choose(task({preferred_agent:'codex'}))).capabilities()).id,'codex');
});
test('Muse delegation rejects unsupported nodes, forged risk/permission fields and recursive parents',()=>{
 const input={request_id:randomUUID(),agent:'codex',node:'mac-mini',goal:'Revisa',capability:'conversation',target:'mac-mini'};
 assert.ok(DelegateSchema.safeParse(input).success);
 for(const bad of [{...input,node:'lenlab'},{...input,agent:'muse'},{...input,risk:'read'},{...input,permissions:['all']}])assert.ok(!DelegateSchema.safeParse(bad).success);
 for(const parent of [null,task({agent:'codex'}),task({state:'canceled'}),task({parent_task_id:randomUUID()})])assert.throws(()=>requireMuseParent(parent),/invalid_parent_task/);
});
test('delegation links a child to its Muse parent, preserves ownership and limits parallel work',async()=>{
 const parent=task(),children:Task[]=[];let recorded:any;
 const context={leadership:{assert:async()=>({epoch:'1'})},delegating:new Set(),cfg:{resources:[{id:'repo',kind:'repository',node:'mac-mini'}]},task:async(id:string)=>id===parent.task_id?parent:null,tasks:async()=>children,submit:async(raw:any,requester:string,session_id:string,id:string,link:any)=>{recorded={raw,requester,session_id,id,link};return task({...raw,task_id:id,...link});}};
 const input={request_id:randomUUID(),agent:'codex',node:'mac-mini',goal:'Revisa',capability:'code.change',target:'repo'};
 const result=await Coordinator.prototype.delegate.call(context as any,parent.task_id,input);
 assert.equal(result.parent_task_id,parent.task_id);assert.equal(recorded.requester,parent.requester);assert.equal(recorded.session_id,parent.session_id);assert.equal(result.execution_node,'mac-mini');
 await assert.rejects(()=>Coordinator.prototype.delegate.call(context as any,parent.task_id,{...input,node:'tuf-infra'}),/invalid_target/);
 await assert.rejects(()=>Coordinator.prototype.delegate.call(context as any,parent.task_id,{...input,target:'unknown'}),/invalid_target/);
 for(let n=0;n<4;n++)children.push(task({parent_task_id:parent.task_id}));
 await assert.rejects(()=>Coordinator.prototype.delegate.call(context as any,parent.task_id,input),/queue_full/);
 assert.equal(context.delegating.size,0);
});
test('Muse cannot read or cancel another parent’s child',async()=>{
 const parent=task(),child=task({parent_task_id:randomUUID()});let canceled=false;
 const context={task:async(id:string)=>id===parent.task_id?parent:child,cancel:async()=>{canceled=true;}};
 await assert.rejects(()=>Coordinator.prototype.delegatedTask.call(context as any,parent.task_id,child.task_id,true),/invalid_task/);assert.equal(canceled,false);
 child.parent_task_id=parent.task_id;assert.equal((await Coordinator.prototype.delegatedTask.call(context as any,parent.task_id,child.task_id)).task_id,child.task_id);
});
test('canceling a Muse parent stops its running delegates and keeps their task ownership',async()=>{
 const parent=task(),child=task({parent_task_id:parent.task_id,agent:'codex'}),calls:string[]=[];
 const context={task:async(id:string)=>id===parent.task_id?parent:child,leadership:{assert:async()=>({epoch:'1'})},active:new Map([[parent.task_id,{cancel:async()=>{calls.push('Muse stopped');}}]]),registry:{adapter:()=>null},save:async()=>{},publish:async()=>{},tasks:async()=>[parent,child],cancel:async(id:string,owner:string)=>{calls.push(id+':'+owner);}};
 await Coordinator.prototype.cancel.call(context as any,parent.task_id,parent.requester);
 assert.equal(parent.state,'canceled');assert.deepEqual(calls,['Muse stopped',child.task_id+':'+parent.requester]);
});
test('Muse host observations are typed, read-only and bound to the requested target',async()=>{
 const parent=task(),calls:any[]=[];
 const context={task:async()=>parent,cfg:{resources:[]},action:async(value:any)=>{calls.push(value);return {result:{}};}};
 await assert.rejects(()=>Coordinator.prototype.museHostStatus.call(context as any,parent.task_id,'lenlab'),/invalid_target/);
 await Coordinator.prototype.museHostStatus.call(context as any,parent.task_id,'mac-mini');
 assert.equal(calls[0].operation,'host.status');assert.equal(calls[0].task_id,parent.task_id);assert.deepEqual(calls[0].params,{});
});
