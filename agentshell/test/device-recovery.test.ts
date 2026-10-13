import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {randomUUID} from 'node:crypto';
import {AgentShellService} from '../src/main.js';
import {envelope} from '../src/protocol.js';
class DeviceSocket extends EventEmitter {
 readyState=1;bufferedAmount=0;sent:any[]=[];
 send(data:any){this.sent.push(Buffer.isBuffer(data)?data:JSON.parse(data));}
 close(){this.readyState=3;this.emit('close');}
}
async function until(check:()=>boolean){
 const end=Date.now()+4000;
 while(!check()){if(Date.now()>end)throw Error('test deadline');await new Promise(resolve=>setTimeout(resolve,10));}
}
test('real device handler waits for recovery and never synthesizes its historical speech',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'sagwa-voice-test-'));const token=join(dir,'token');
 await writeFile(token,'dummy-test-token-with-at-least-thirty-two-characters',{mode:0o600});
 const task=randomUUID(),session=randomUUID(),socket=new DeviceSocket();
 const polls:number[]=[],synthesized:string[]=[];let releaseSnapshot!:()=>void;
 const snapshotGate=new Promise<void>(resolve=>{releaseSnapshot=resolve;});
 const ctx:any={cfg:{node_id:'mac-mini',voice:{url:'http://local.invalid',token_file:token},peers:[]},
  store:{get:async()=>null,put:async()=>{}},
  coordinator:{task:async()=>({task_id:task,summary:'Estoy aquí contigo.'})},
  displays:new Map(),speechReplay:new Map(),deviceSpeech:new Map(),
  command:async(kind:string,payload:any)=>{
   if(kind==='snapshot'){await snapshotGate;return {sequence:100,foreground_task_id:task,tasks:[{task_id:task,state:'completed',summary:'Estoy aquí contigo.'}],approvals:[]};}
   if(kind==='settings')return {nodes:[],agents:[]};
   if(kind==='events'){
    polls.push(payload.after);
    return [{sequence:99,type:'speech.ready',task_id:task,payload:{text:'ANTIGUA NO REPRODUCIR',session_id:session}},
            {sequence:101,type:'speech.ready',task_id:task,payload:{text:'Estoy aquí contigo.',session_id:session}}];
   }
   throw Error('unexpected command '+kind);
  }};
 const originalFetch=globalThis.fetch;
 globalThis.fetch=(async(_url:any,options:any)=>{
  synthesized.push(JSON.parse(options.body).text);
  return new Response(new Uint8Array([0,0,0,0]),{status:200,headers:{'x-sample-rate':'16000','x-channels':'1'}});
 }) as typeof fetch;
 try{
  await (AgentShellService.prototype as any).device.call(ctx,socket,'device:test');
  socket.emit('message',Buffer.from(JSON.stringify(envelope(session,0,'device.hello',{last_sequence:0,capabilities:{firmware:'0.3.0-dev'}}))),false);
  // Let the real 500ms poll timer fire while hello/snapshot is unresolved.
  await new Promise(resolve=>setTimeout(resolve,650));
  assert.deepEqual(polls,[]);assert.deepEqual(synthesized,[]);
  releaseSnapshot();
  try { await until(()=>socket.sent.some(m=>m.type==='audio.end')); }
  catch { throw Error(JSON.stringify({polls,synthesized,events:socket.sent.filter(m=>!Buffer.isBuffer(m)),speech:[...ctx.deviceSpeech.values()]})); }
  assert.equal(polls[0],100);assert.deepEqual(synthesized,['Estoy aquí contigo.']);
  assert.ok(socket.sent.some(m=>m.type==='device.snapshot'&&m.sequence===100));
  assert.ok(socket.sent.some(m=>m.type==='audio.start'&&m.task_id===task&&m.sequence===101));
  await new Promise(resolve=>setTimeout(resolve,600));
  assert.equal(synthesized.length,1);assert.ok(polls.every(n=>n>=100));
 }finally{socket.close();globalThis.fetch=originalFetch;await rm(dir,{recursive:true,force:true});}
});

for(const clientRoutes of [false,true])test(`real media/STT handshake preserves ${clientRoutes?'Core-owned routing':'legacy automatic Muse routing'}`,async()=>{
 const dir=await mkdtemp(join(tmpdir(),'sagwa-stt-test-'));const token=join(dir,'token');
 await writeFile(token,'dummy-test-token-with-at-least-thirty-two-characters',{mode:0o600});
 const task=randomUUID(),stream=randomUUID(),session=randomUUID(),socket=new DeviceSocket(),submissions:any[]=[];
 const ctx:any={cfg:{node_id:'mac-mini',voice:{url:'http://local.invalid',token_file:token},peers:[]},
  store:{get:async()=>null,put:async()=>{}},coordinator:{task:async()=>null},displays:new Map(),speechReplay:new Map(),deviceSpeech:new Map(),
  command:async(kind:string,payload:any)=>{
   if(kind==='snapshot')return {sequence:0,foreground_task_id:null,tasks:[],approvals:[]};
   if(kind==='settings')return {};if(kind==='events')return [];
   if(kind==='submit'){submissions.push(payload);return {task_id:payload.task_id};}
   throw Error('unexpected command '+kind);
  }};
 const originalFetch=globalThis.fetch;
 globalThis.fetch=(async()=>new Response(JSON.stringify({text:'modo noche'}),{headers:{'content-type':'application/json'}})) as typeof fetch;
 try{
  await (AgentShellService.prototype as any).device.call(ctx,socket,'device:test');
  socket.emit('message',Buffer.from(JSON.stringify(envelope(session,0,'device.hello',{last_sequence:0,capabilities:{...(clientRoutes?{client_routes_transcripts:true}:{})}}))),false);
  await until(()=>socket.sent.some(m=>m.type==='device.settings'));
  assert.ok(socket.sent.some(m=>m.type==='device.settings'&&m.payload.transcript_routing===(clientRoutes?'client':'gateway')));
  socket.emit('message',Buffer.from(JSON.stringify(envelope(session,0,'media.start',{stream_id:stream,kind:1},task))),false);
  const {encodeMedia}=await import('../src/protocol.js');
  socket.emit('message',encodeMedia({session_id:session,task_id:task,stream_id:stream,sequence:0,kind:1,data:Buffer.alloc(44)}),true);
  socket.emit('message',Buffer.from(JSON.stringify(envelope(session,0,'media.end',{stream_id:stream,target:'mac-mini',capability:'conversation'},task))),false);
  await until(()=>socket.sent.some(m=>m.type==='voice.transcript'));
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(submissions.length,clientRoutes?0:1);
  assert.ok(socket.sent.some(m=>m.type==='voice.transcript'&&m.task_id===task&&m.payload.text==='modo noche'));
  if(clientRoutes){
   const durable=randomUUID();
   socket.emit('message',Buffer.from(JSON.stringify(envelope(session,0,'task.submit',{goal:'Explícita desde el Core',target:'mac-mini',capability:'conversation',preferred_agent:'muse',context_refs:[]},durable))),false);
   await until(()=>submissions.length===1);assert.equal(submissions[0].task_id,durable);
  }else assert.equal(submissions[0].request.goal,'modo noche');
 }finally{socket.close();globalThis.fetch=originalFetch;await rm(dir,{recursive:true,force:true});}
});

for(const delayedStage of ['events','task'])test(`resume discards an in-flight ${delayedStage} poll and blocks speech during its snapshot`,async()=>{
 const dir=await mkdtemp(join(tmpdir(),'sagwa-resume-test-'));const token=join(dir,'token');
 await writeFile(token,'dummy-test-token-with-at-least-thirty-two-characters',{mode:0o600});
 const task=randomUUID(),session=randomUUID(),socket=new DeviceSocket();
 let resume=false,pollStarted=false,snapshotStarted=false,releasePoll!:()=>void,releaseSnapshot!:()=>void;
 const pollGate=new Promise<void>(resolve=>{releasePoll=resolve;});
 const snapshotGate=new Promise<void>(resolve=>{releaseSnapshot=resolve;});
 const synthesized:string[]=[];let polls=0,hold=true;
 const ctx:any={cfg:{node_id:'mac-mini',voice:{url:'http://local.invalid',token_file:token},peers:[]},
  store:{get:async()=>null,put:async()=>{}},displays:new Map(),speechReplay:new Map(),deviceSpeech:new Map(),
  coordinator:{task:async()=>{if(hold&&delayedStage==='task'&&!resume){pollStarted=true;await pollGate;}return {summary:'Respuesta vieja para descartar.'};}},
  command:async(kind:string)=>{
   if(kind==='snapshot'){if(resume){snapshotStarted=true;await snapshotGate;}return {sequence:100,foreground_task_id:task,tasks:[],approvals:[]};}
   if(kind==='settings')return {};
   if(kind==='events'){
    polls++;if(!hold)return [];
    if(delayedStage==='events'){pollStarted=true;await pollGate;}
    return [{sequence:101,type:'task.state',task_id:task,payload:{state:'completed'}},
            {sequence:102,type:'speech.ready',task_id:task,payload:{text:'ANTIGUA NO REPRODUCIR'}}];
   }
   throw Error('unexpected command '+kind);
  }};
 const originalFetch=globalThis.fetch;
 globalThis.fetch=(async(_url:any,options:any)=>{synthesized.push(JSON.parse(options.body).text);return new Response(new Uint8Array([0,0]),{headers:{'x-sample-rate':'16000','x-channels':'1'}});}) as typeof fetch;
 try{
  await (AgentShellService.prototype as any).device.call(ctx,socket,'device:test');
  socket.emit('message',Buffer.from(JSON.stringify(envelope(session,0,'device.hello',{}))),false);
  await until(()=>pollStarted);resume=true;
  socket.emit('message',Buffer.from(JSON.stringify(envelope(session,0,'device.resume',{},task))),false);
  await until(()=>snapshotStarted);
  assert.throws(()=>ctx.speechReplay.get('device:test')(task,'No durante recuperación.'));
  const before=polls;hold=false;releasePoll();
  await new Promise(resolve=>setTimeout(resolve,650));
  assert.equal(polls,before);assert.deepEqual(synthesized,[]);
  assert.equal(socket.sent.filter(m=>m.type==='task.state').length,0);
  releaseSnapshot();await until(()=>socket.sent.filter(m=>m.type==='device.snapshot').length===2);
  await until(()=>polls>before);assert.deepEqual(synthesized,[]);
 }finally{hold=false;releasePoll();releaseSnapshot();socket.close();globalThis.fetch=originalFetch;await rm(dir,{recursive:true,force:true});}
});

test('authorized replay uses its own control cursor and preserves the next durable speech event',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'sagwa-replay-test-'));const token=join(dir,'token');
 await writeFile(token,'dummy-test-token-with-at-least-thirty-two-characters',{mode:0o600});
 const task=randomUUID(),session=randomUUID(),socket=new DeviceSocket();
 const synthesized:string[]=[];let fresh=false;const polls:number[]=[];
 const ctx:any={cfg:{node_id:'mac-mini',voice:{url:'http://local.invalid',token_file:token},peers:[]},
  store:{get:async()=>null,put:async()=>{}},coordinator:{task:async()=>({summary:'Estoy aquí contigo.'})},
  displays:new Map(),speechReplay:new Map(),deviceSpeech:new Map(),
  command:async(kind:string,p:any)=>{
   if(kind==='snapshot')return {sequence:100,foreground_task_id:task,tasks:[],approvals:[]};
   if(kind==='settings')return {};
   if(kind==='events'){polls.push(p.after);return fresh?[{sequence:101,type:'speech.ready',task_id:task,payload:{text:'Nueva respuesta para ti.'}}]:[];}
   throw Error('unexpected command '+kind);
  }};
 const originalFetch=globalThis.fetch;
 globalThis.fetch=(async(_url:any,options:any)=>{synthesized.push(JSON.parse(options.body).text);return new Response(new Uint8Array([0,0]),{headers:{'x-sample-rate':'16000','x-channels':'1'}});}) as typeof fetch;
 try{
  await (AgentShellService.prototype as any).device.call(ctx,socket,'device:test');
  socket.emit('message',Buffer.from(JSON.stringify(envelope(session,0,'device.hello',{}))),false);
  await until(()=>socket.sent.some(m=>m.type==='device.settings'));
  ctx.speechReplay.get('device:test')(task,'Repite esta respuesta para mí.');
  await until(()=>socket.sent.some(m=>m.type==='audio.end'));
  let starts=socket.sent.filter(m=>m.type==='audio.start');
  assert.equal(starts[0].sequence,100);assert.equal(starts[0].payload.control_sequence,1);assert.equal(starts[0].payload.explicit_replay,true);
  fresh=true;await until(()=>socket.sent.filter(m=>m.type==='audio.end').length===2);
  starts=socket.sent.filter(m=>m.type==='audio.start');
  assert.equal(starts[1].sequence,101);assert.equal(starts[1].payload.control_sequence,2);assert.equal(starts[1].payload.explicit_replay,false);
  assert.equal(synthesized.length,2);assert.equal(polls[0],100);
  socket.emit('message',Buffer.from(JSON.stringify(envelope(session,0,'voice.sample',{},task))),false);
  await until(()=>socket.sent.filter(m=>m.type==='audio.end').length===3);
  starts=socket.sent.filter(m=>m.type==='audio.start');
  assert.equal(starts[2].sequence,101);assert.equal(starts[2].payload.control_sequence,3);assert.equal(starts[2].payload.explicit_replay,true);
 }finally{socket.close();globalThis.fetch=originalFetch;await rm(dir,{recursive:true,force:true});}
});
