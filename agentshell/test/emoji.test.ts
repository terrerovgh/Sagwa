import test from 'node:test';
import assert from 'node:assert/strict';
import {VercelEmojiSelector} from '../src/emoji-vercel.js';
import {speechSegments,selectSpeechEmoji,type EmojiEntry} from '../src/emoji.js';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
const entries=[{id:'1fad6',name:'tetera',english:'teapot',keywords:[]},{id:'1f4bb',name:'ordenador portátil',english:'laptop',keywords:[]}].map(e=>({...e,char:'',category:'objects',animated:true})) satisfies EmojiEntry[];
async function selector(http:typeof fetch,run:(s:VercelEmojiSelector)=>Promise<void>){
 const dir=await mkdtemp(path.join(os.tmpdir(),'emoji-test-'));
 try{await writeFile(dir+'/key','test-key',{mode:0o600});await run(new VercelEmojiSelector({key_file:dir+'/key',models:['typesafe-ai/jev','convaiinnovations/laya'],free_only:true},http));}finally{await rm(dir,{recursive:true,force:true});}
}
test('free model selection skips paid Jev and accepts only supplied Noto identifiers',async()=>{
 let requests=0;
 await selector(async(input,init)=>{
  requests++;
  if(String(input).endsWith('/models'))return Response.json({data:[{id:'typesafe-ai/jev',type:'evaluation',pricing:{input:'0.000000042',output:'0'}},{id:'convaiinnovations/laya',type:'evaluation',pricing:{input:'0',output:'0'}}]});
  const p=JSON.parse(String(init?.body));assert.equal(p.model,'convaiinnovations/laya');assert.equal(init?.redirect,'error');assert.equal(p.providerOptions,undefined);
  return Response.json({answers:{emoji:{choice:'1fad6',probabilities:{'1fad6':.9}}}});
 },async s=>{const r=await s.select('té',entries);assert.equal(r?.entry.id,'1fad6');assert.equal(r?.method,'vercel:convaiinnovations/laya');});
 assert.equal(requests,2);
});
test('nonzero or missing price prevents all inference calls',async()=>{
 let calls=0;await selector(async()=>{calls++;return Response.json({data:[{id:'typesafe-ai/jev',type:'evaluation',pricing:{input:'1',output:'0'}},{id:'convaiinnovations/laya',type:'evaluation'}]});},async s=>{assert.equal(await s.select('té',entries),null);assert.equal(s.status,'no_free_model');});assert.equal(calls,1);
});
test('invalid decision or account rejection falls back without propagating provider body',async()=>{
 for(const response of [Response.json({answers:{emoji:{choice:'https://evil.test/image'}}}),new Response('private provider detail',{status:403})]){
  let calls=0;await selector(async(input)=>{calls++;return String(input).endsWith('/models')?Response.json({data:[{id:'convaiinnovations/laya',type:'evaluation',pricing:{input:'0',output:'0'}}]}):response;},async s=>{assert.equal(await s.select('té',entries),null);assert.equal(await s.select('otro',entries),null);assert.notEqual(s.status,'ready');assert.ok(!s.status.includes('private'));});assert.equal(calls,2);
 }
});
test('long speech preserves all words with at most sixteen timed segments',()=>{
 const text=Array.from({length:1000},(_,i)=>'palabra'+i).join(' ');const spans=speechSegments(text);assert.ok(spans.length<=16);assert.equal(spans.join(' '),text.slice(0,8192));
});

test('visual decisions publish incrementally while another segment remains unresolved',async()=>{
 let finish!:(v:string)=>void;const delayed=new Promise<string>(resolve=>{finish=resolve;});const ready:{choice:string,index:number}[]=[];
 const all=selectSpeechEmoji(['first','second'],async text=>text==='first'?'figure':delayed,(choice,index)=>{ready.push({choice,index});});
 await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(ready,[{choice:'figure',index:0}]);
 finish('second figure');assert.deepEqual(await all,['figure','second figure']);assert.equal(ready[1]?.index,1);
});
