// Exercise the real gateway speech path with synthetic Spanish text and local Piper.
// Mock coordination only: no agents, host actions or retained user conversation.
import {EventEmitter} from 'node:events';
import {randomUUID} from 'node:crypto';
import {writeFile} from 'node:fs/promises';
import {loadConfig} from '../dist/config.js';
import {AgentShellService} from '../dist/main.js';
import {envelope} from '../dist/protocol.js';
const cfg=loadConfig(new URL('../.private/mac-mini/config.json',import.meta.url).pathname);
// Timing/cancellation acceptance is deterministic and independent of provider latency.
const remote=process.argv.includes('--openrouter');
if(!remote){delete cfg.emoji.vercel;delete cfg.emoji.openrouter;}
const service=new AgentShellService(cfg);
const session=randomUUID(),task=randomUUID();
service.store.get=async()=>null;service.store.put=async()=>{};
let speechPending=false;let stage='full',started=0;const cues=[];let binary=0,lateFrames=0,canceledAt=0;
service.command=async(kind)=>{
 if(kind==='snapshot')return {tasks:[],approvals:[]};
 if(kind==='events'&&speechPending){speechPending=false;return [{sequence:1,task_id:task,type:'speech.ready',payload:{session_id:session,text:'Voy a preparar té con mi tetera. Revisemos el código de tu aplicación. Guardaremos una copia de seguridad.'}}];}
 return [];
};
class Socket extends EventEmitter {
 readyState=1;bufferedAmount=0;
 send(data){
  if(Buffer.isBuffer(data)){binary++;if(canceledAt)lateFrames++;return;}
  const e=JSON.parse(data);
  if(e.type==='audio.start')started=Date.now();
  if(e.type==='ui.emoji')cues.push({id:e.payload.codepoint,at_ms:Date.now()-started});
  if(e.type==='audio.end'&&stage==='full')this.emit('completed');
 }
}
const ws=new Socket();await service.device(ws,cfg.device_ids[0]);
ws.emit('message',Buffer.from(JSON.stringify(envelope(session,0,'device.hello',{last_sequence:0,capabilities:{}}))),false);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
try {
 const deadline=Date.now()+15000;while(!service.emoji.ready&&Date.now()<deadline)await sleep(100);
 if(!service.emoji.ready)throw Error('local_selector_unavailable');
 speechPending=true;const until=Date.now()+25000;while(cues.length<3&&Date.now()<until)await sleep(100);
 if(cues.map(c=>c.id).join(',')!=='1fad6,1f4bb,1f4be'||binary===0)throw Error('contextual_cues_failed');
 for(let n=1;n<cues.length;n++)if(cues[n].at_ms-cues[n-1].at_ms<1700)throw Error('cue_changes_too_fast');
 await sleep(1000);stage='cancel';speechPending=true;started=0;
 const end=Date.now()+20000;while(!started&&Date.now()<end)await sleep(25);
 if(!started)throw Error('speech_not_started');
 ws.emit('message',Buffer.from(JSON.stringify(envelope(session,2,'audio.cancel',{},task))),false);canceledAt=Date.now();const before=cues.length;
 await sleep(2500);if(lateFrames||cues.length!==before)throw Error('canceled_turn_replayed');
 if(remote&&(service.emoji.openrouter?.status!=='ready'||service.emoji.openrouter.requests<3||service.emoji.openrouter.cost_usd!==0))throw Error('remote_decisions_not_confirmed: '+JSON.stringify(service.emoji.openrouter?.health));
 const report={source:'synthetic Spanish phrases, real '+(remote?'OpenRouter decisions':'local selector')+' and Piper, mocked coordination',remote:service.emoji.openrouter?.health,cues:cues.slice(0,3),binary_frames:binary,canceled_late_frames:lateFrames,canceled_late_cues:cues.length-before,paid_agent_calls:0};
 await writeFile(new URL('../evidence/'+(remote?'emoji-openrouter-cues.json':'emoji-cues.json'),import.meta.url),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
}finally{ws.readyState=3;ws.emit('close');await service.emoji.stop();service.store.close();service.server.close();}
