import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {OpenRouterEmojiSelector} from '../src/emoji-openrouter.js';
import {selectSpeechEmoji,type EmojiEntry} from '../src/emoji.js';
const model='inception/mercury-decide:free' as const;
const entries=[{id:'1fad6',name:'tetera',english:'teapot',keywords:[]},{id:'1f4bb',name:'ordenador',english:'laptop',keywords:[]}].map(e=>({...e,char:'',category:'objects',animated:true})) satisfies EmojiEntry[];
const listing=(pricing:unknown={prompt:'0',completion:'0'})=>Response.json({data:[{id:model,pricing,architecture:{output_modalities:['decisions']}}]});
async function run(http:typeof fetch,body:(s:OpenRouterEmojiSelector)=>Promise<void>){
 const dir=await mkdtemp(path.join(os.tmpdir(),'emoji-openrouter-'));
 try{await writeFile(dir+'/key','test-key',{mode:0o600});await body(new OpenRouterEmojiSelector({key_file:dir+'/key',models:[model],free_only:true},http));}finally{await rm(dir,{recursive:true,force:true});}
}
test('OpenRouter decisions use the free decision catalog and bounded quoted context',async()=>{
 let calls=0;
 await run(async(url,init)=>{
  calls++;if(String(url).endsWith('/models?output_modalities=decisions'))return listing();
  assert.equal(String(url),'https://openrouter.ai/api/alpha/decisions');assert.equal(init?.redirect,'error');
  const p=JSON.parse(String(init?.body));assert.equal(p.model,model);assert.equal(p.state.utterance.length,1024);assert.equal(p.state.recent_context.length,1024);assert.equal(p.tools,undefined);assert.equal(p.models,undefined);
  assert.deepEqual(Object.keys(p.questions.emoji.criteria),['1fad6','1f4bb']);
  return Response.json({answers:{emoji:{type:'choice',choice:'1fad6',probabilities:{'1fad6':.95}}},usage:{cost:0}});
 },async s=>{const choice=await s.select('a'.repeat(2000),entries,'b'.repeat(2000));assert.equal(choice?.entry.id,'1fad6');assert.equal(choice?.method,'openrouter:'+model);assert.equal(s.health.cost_usd,0);assert.equal(s.health.requests,1);});
 assert.equal(calls,2);
});
test('changed, missing, negative, empty or auxiliary pricing stops inference',async()=>{
 for(const pricing of [{prompt:'0.01',completion:'0'},{completion:'0'},{prompt:null,completion:'0'},{prompt:'',completion:'0'},{prompt:'-1',completion:'0'},{prompt:'0',completion:'0',request:'.001'}]){
  let calls=0;await run(async()=>{calls++;return listing(pricing);},async s=>{assert.equal(await s.select('té',entries),null);assert.equal(s.status,'no_free_model');});assert.equal(calls,1);
 }
});
test('invalid identifiers, wrong answer type, charged responses and 429 use local fallback and backoff',async()=>{
 for(const response of [Response.json({answers:{emoji:{type:'choice',choice:'evil'}},usage:{cost:0}}),Response.json({answers:{emoji:{type:'score',choice:'1fad6'}},usage:{cost:0}}),Response.json({answers:{emoji:{type:'choice',choice:'1fad6'}},usage:{cost:.1}}),new Response('private conversation and key',{status:429})]){
  let calls=0;await run(async url=>{calls++;return String(url).includes('/models?')?listing():response;},async s=>{assert.equal(await s.select('té',entries),null);assert.equal(await s.select('café',entries),null);assert.equal(s.requests,1);if(s.status==='openrouter_unexpected_cost')assert.equal(s.cost_usd,.1);assert.ok(!s.status.includes('private'));});assert.equal(calls,2);
 }
});
test('parallel selection shares catalog fetch and bounds outstanding provider requests',async()=>{
 let calls=0;let release!:()=>void;const gate=new Promise<void>(r=>release=r);
 await run(async url=>{calls++;if(String(url).includes('/models?')){await gate;return listing();}return Response.json({answers:{emoji:{type:'choice',choice:'1fad6'}},usage:{cost:0}});},async s=>{
  const a=s.select('uno',entries),b=s.select('dos',entries);assert.equal(await s.select('tres',entries),null);release();assert.ok(await a);assert.ok(await b);
 });assert.equal(calls,3);
});
test('all voice segments receive a decision with at most two in flight and ordered recent context',async()=>{
 let active=0,peak=0;const seen:string[]=[];
 const results=await selectSpeechEmoji(['té','código','copias','triste'],async(text,context)=>{
  active++;peak=Math.max(peak,active);seen.push(context);await new Promise(r=>setImmediate(r));active--;return text;
 });
 assert.equal(peak,2);assert.deepEqual(results,['té','código','copias','triste']);assert.deepEqual(seen,['','té','té código','código copias']);
 await assert.rejects(selectSpeechEmoji(Array(17).fill('té'),async()=>''),/queue_full/);
});
