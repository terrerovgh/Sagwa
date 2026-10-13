import test from 'node:test';
import assert from 'node:assert/strict';
import {ForegroundTurn} from '../src/foreground-turn.js';

test('recovery suppresses old speech even with a stale device cursor or no selected task',()=>{
 const turn=new ForegroundTurn();
 assert.equal(turn.accepts('historical'),false);assert.equal(turn.acceptsSpeech('historical',99),false);
 turn.recover('recent',100);
 assert.ok(turn.accepts('recent'));assert.equal(turn.accepts('older'),false);
 assert.equal(turn.acceptsSpeech('recent',0),false);assert.equal(turn.acceptsSpeech('recent',100),false);
 assert.ok(turn.acceptsSpeech('recent',101));assert.equal(turn.acceptsSpeech('older',101),false);
 turn.recover('recent',110);assert.equal(turn.acceptsSpeech('recent',101),false);
 turn.recover('recent',90);assert.equal(turn.acceptsSpeech('recent',109),false);
 turn.select('new');assert.ok(turn.acceptsSpeech('new',111));assert.equal(turn.acceptsSpeech('recent',111),false);
 turn.recover(null,120);assert.equal(turn.acceptsSpeech('new',121),false);assert.ok(turn.accepts(null));
 for(const invalid of [-1,NaN,Infinity,1.5])assert.throws(()=>turn.recover('recent',invalid),/sequence/);
});

test('snapshot reads its event boundary before tasks so a completion during recovery is not swallowed',async()=>{
 let head=50;const calls:string[]=[];
 const ctx={store:{get:async()=>{calls.push('head');return head;},list:async()=>({})},tasks:async()=>{calls.push('tasks');head=51;return [];},deviceSettings:async()=>({}),leadership:{current:async()=>({})}};
 const snapshot=await Coordinator.prototype.snapshot.call(ctx as any,'device');
 assert.equal(snapshot.sequence,50);assert.deepEqual(calls,['head','tasks']);
});
import {HttpAdapter} from '../src/adapters.js';
import {Coordinator} from '../src/coordinator.js';
import type {Config} from '../src/config.js';
test('idle event polling skips full history, while new events stay ordered and recover sequence gaps',async()=>{
 let lists=0;const context={store:{get:async()=>12,list:async()=>{lists++;return {head:12,a:{sequence:11},b:{sequence:12},old:{sequence:10}};}}};
 assert.deepEqual(await Coordinator.prototype.events.call(context as any,'device',12),[]);assert.equal(lists,0);
 assert.deepEqual((await Coordinator.prototype.events.call(context as any,'device',10)).map(e=>e.sequence),[11,12]);assert.equal(lists,1);
 context.store.get=async()=>{throw Error('quorum_unavailable');};await assert.rejects(()=>Coordinator.prototype.events.call(context as any,'device',12),/quorum_unavailable/);
});
test('capability checks share concurrent requests and disabled adapters bypass cached availability',async()=>{
 const settings={enabled:true} as Config['agents'][string];let reads=0;
 class Muse extends HttpAdapter {protected override async json(){reads++;await new Promise(resolve=>setImmediate(resolve));return {features:{run_submission:true,run_stop:true}};}}
 const adapter=new Muse('muse',settings);const caps=await Promise.all([adapter.capabilities(),adapter.capabilities(),adapter.capabilities()]);
 assert.ok(caps.every(c=>c.available));assert.equal(reads,1);await adapter.capabilities();assert.equal(reads,1);
 settings.enabled=false;assert.equal((await adapter.capabilities()).available,false);
});
test('old task expiry and speech cannot replace a newer voice turn; device controls still arrive',()=>{
 const turn=new ForegroundTurn();turn.select('old');assert.ok(turn.accepts('old'));
 turn.select('recording');assert.equal(turn.accepts('old'),false);assert.ok(turn.accepts('recording'));assert.ok(turn.accepts(null));
 turn.select('recovered');assert.equal(turn.accepts('recording'),false);assert.ok(turn.accepts('recovered'));
 assert.equal(turn.selected('recording'),false);assert.ok(turn.selected('recovered'));turn.select(null);assert.equal(turn.selected('recovered'),false);
});
test('device recovery reads recent owned history with bounded concurrency and retains older active tasks',async()=>{
 const indexes:Record<string,any>={};const read:string[]=[];let active=0,peak=0;
 for(let n=0;n<100;n++)indexes['tasks/'+n]={requester:n%2?'other':'device',state:n===0?'needs_approval':'completed',created_at:new Date(Date.now()-(100-n)*1000).toISOString(),updated_at:new Date().toISOString()};
 const context={store:{list:async()=>indexes},task:async(id:string)=>{read.push(id);active++;peak=Math.max(peak,active);await new Promise(resolve=>setImmediate(resolve));active--;if(id==='96')throw Error('unavailable');return {task_id:id,created_at:indexes['tasks/'+id].created_at};}};
 const tasks=await Coordinator.prototype.tasks.call(context as any,'device',10);
 assert.equal(read.length,11);assert.ok(peak<=8&&peak>1);assert.ok(read.includes('0'));assert.equal(read.some(id=>Number(id)%2===1),false);assert.equal(tasks[0]?.task_id,'98');assert.equal(tasks.some(t=>t.task_id==='96'),false);
});
test('Muse waiting stage is Spanish and polling still delivers the real terminal result',async()=>{
 class Muse extends HttpAdapter {
  private reads=0;
  protected override async json(){return this.reads++?{status:'completed',output:'Buenos días.'}:{status:'running',stage:'Esperando respuesta de Muse.'};}
 }
 const adapter=new Muse('muse',{} as Config['agents'][string]);const events:any[]=[];
 const run=await adapter.attach('test',{cwd:'',emit:async e=>{events.push(e);},approve:async()=>false},undefined,{id:'muse',available:true,streaming:false,cancel:true,approvals:false});
 await run.done;assert.deepEqual(events,[{type:'stage',text:'Esperando respuesta de Muse.'},{type:'completed',text:'Buenos días.'}]);
});
test('Muse partial text reaches the display before the final result and never completes the task',async()=>{
 class Muse extends HttpAdapter {private reads=0;protected override async json(){return this.reads++?{status:'completed',output:'Respuesta completa.'}:{status:'running',preview:'Respuesta parcial.'};}}
 const events:any[]=[];const adapter=new Muse('muse',{} as Config['agents'][string]);
 const run=await adapter.attach('test',{cwd:'',emit:async e=>{events.push(e);},approve:async()=>false},undefined,{id:'muse',available:true,streaming:false,cancel:true,approvals:false});
 await run.done;assert.deepEqual(events,[{type:'preview',text:'Respuesta parcial.'},{type:'completed',text:'Respuesta completa.'}]);
});
test('a correlated preview changes only the display; task persistence and speech wait for completion',async()=>{
 const emitted:any[]=[];const task={task_id:'task',agent:'muse',state:'running'};
 const context={task:async()=>task,publish:async(...args:any[])=>{emitted.push(args);},save:async()=>assert.fail('preview cannot persist a completed task')};
 await (Coordinator.prototype as any).agentEvent.call(context,task,{type:'preview',text:'Respuesta parcial.'});
 assert.equal(task.state,'running');assert.equal(emitted.length,1);assert.equal(emitted[0][1],'ui.state');assert.equal(emitted[0][2].mode,'thinking');
});
test('a durable completed reply starts speech before slow history cleanup; delegates still get canceled',async()=>{
 let release!:(value:any[])=>void;const history=new Promise<any[]>(resolve=>{release=resolve;});const emitted:string[]=[],canceled:string[]=[];let durable=false;
 const task={task_id:'parent',agent:'muse',state:'running',session_id:'session',requester:'device'};
 const context={task:async()=>({...task}),save:async()=>{durable=true;},publish:async(_task:any,type:string)=>{assert.ok(durable);emitted.push(type);},tasks:async()=>history,cancel:async(id:string)=>{canceled.push(id);}};
 const done=(Coordinator.prototype as any).agentEvent.call(context,task,{type:'completed',text:'Respuesta.'});
 await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(emitted,['task.state','speech.ready']);assert.equal(task.state,'completed');assert.deepEqual(canceled,[]);
 release([{task_id:'child',parent_task_id:'parent',state:'running'},{task_id:'other',parent_task_id:'other-parent',state:'running'}]);await done;assert.deepEqual(canceled,['child']);
});
