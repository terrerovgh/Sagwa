import test from 'node:test';
import assert from 'node:assert/strict';
import {Coordinator} from '../src/coordinator.js';
test('physical approval is bound to the authenticated device and foreground parent before recording consent',async()=>{
 const instance={store:{get:async()=>({action:{task_id:'child'}})},task:async()=>({task_id:'child',parent_task_id:'parent',requester:'device',state:'needs_approval'})};
 await Coordinator.prototype.requireDeviceApprovalOwner.call(instance as any,'approval','parent','device');
 await assert.rejects(()=>Coordinator.prototype.requireDeviceApprovalOwner.call(instance as any,'approval','other-parent','device'),/invalid_approval/);
 await assert.rejects(()=>Coordinator.prototype.requireDeviceApprovalOwner.call(instance as any,'approval','parent','other-device'),/invalid_approval/);
 await assert.rejects(()=>Coordinator.prototype.requireDeviceApprovalOwner.call(instance as any,'approval','','device'),/invalid_approval/);
 instance.task=async()=>({task_id:'child',parent_task_id:'parent',requester:'device',state:'canceled'});
 await assert.rejects(()=>Coordinator.prototype.requireDeviceApprovalOwner.call(instance as any,'approval','parent','device'),/invalid_approval/);
 instance.store.get=async()=>null as any;
 await assert.rejects(()=>Coordinator.prototype.requireDeviceApprovalOwner.call(instance as any,'missing','parent','device'),/invalid_approval/);
});
test('device resume keeps an owned foreground task and maps child approvals to its parent',async()=>{
 const task=(id:string,parent?:string)=>({task_id:id,parent_task_id:parent,requester:'device',goal:'test',summary:'test',context_refs:[]});
 const owned=[task('new'),task('old'),task('child','old')];
 const approval=(id:string,consumed=false)=>({approval_id:id,action:{task_id:id},expires_at:Date.now()+60000,consumed,denied:false});
 const instance={tasks:async()=>[...owned],task:async(id:string)=>id==='foreign'?{...task(id),requester:'other'}:id==='historic'?task(id):null,store:{list:async()=>({child:approval('child'),foreign:approval('foreign'),old:approval('old',true)}),get:async()=>12},deviceSettings:async()=>({}),leadership:{current:async()=>({})}};
 const result=await Coordinator.prototype.snapshot.call(instance as any,'device','old');
 assert.equal(result.foreground_task_id,'old');assert.equal(result.tasks[0]?.task_id,'old');
 assert.deepEqual(result.approvals.map(a=>a.task_id),['old']);
 assert.equal((await Coordinator.prototype.snapshot.call(instance as any,'device','historic')).foreground_task_id,'historic');
 await assert.rejects(()=>Coordinator.prototype.snapshot.call(instance as any,'device','foreign'),/invalid_task/);
 await assert.rejects(()=>Coordinator.prototype.snapshot.call(instance as any,'device','child'),/invalid_task/);
 await assert.rejects(()=>Coordinator.prototype.snapshot.call(instance as any,'device','missing'),/invalid_task/);
});
test('device menus receive fresh availability and resource identifiers without host paths or credentials',async()=>{
 const instance={store:{list:async()=>({a:{node:'mac-mini',received_at:new Date().toISOString(),private:'not exposed'},b:{node:'lenlab',received_at:new Date(Date.now()-60000).toISOString()},c:{node:'tuf-infra',received_at:'invalid'}})},registry:{capabilities:async()=>[{id:'codex',available:true},{id:'muse',available:false}]},cfg:{resources:[{id:'demo',node:'mac-mini',kind:'repository',path:'/private/path'}]}};
 const result=await Coordinator.prototype.deviceSettings.call(instance as unknown as Coordinator);
 assert.deepEqual(result.nodes,[{node:'mac-mini',available:true},{node:'lenlab',available:false},{node:'tuf-infra',available:false}]);
 assert.deepEqual(result.resources,[{id:'demo',node:'mac-mini',kind:'repository'}]);assert.equal(result.agents[1]?.available,false);
 assert.ok(!JSON.stringify(result).includes('/private/path'));assert.ok(!JSON.stringify(result).includes('not exposed'));
});
