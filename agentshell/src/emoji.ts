import {Worker} from 'node:worker_threads';
import {readFileSync} from 'node:fs';
import {mkdir,readFile,writeFile,rename,readdir,stat,unlink} from 'node:fs/promises';
import {createHash,randomUUID} from 'node:crypto';
import path from 'node:path';
import sharp from 'sharp';
import type {Config} from './config.js';
import {VercelEmojiSelector} from './emoji-vercel.js';
import {OpenRouterEmojiSelector} from './emoji-openrouter.js';
export interface EmojiEntry {id:string;char:string;name:string;english:string;keywords:string[];category:string;animated:boolean;renderable?:boolean;asset_id?:string}
export interface EmojiAsset {id:string;name:string;sha256:string;size:number;animated:boolean;frames:number;duration_ms:number}
export interface EmojiChoice {entry:EmojiEntry;score:number;method:string;asset:EmojiAsset}
export function speechSegments(text:string):string[] {
 const sentences=(text.slice(0,8192).match(/[^.!?;\n]+[.!?;\n]*/g)??[text]).map(s=>s.trim()).filter(Boolean);
 const result:string[]=[];
 for(const sentence of sentences){const words=sentence.split(/\s+/);for(let at=0;at<words.length;at+=32)result.push(words.slice(at,at+32).join(' '));}
 // Preserve all spoken text while keeping semantic/timing work bounded.
 return result.length<=16?result:[...result.slice(0,15),result.slice(15).join(' ')];
}
export async function selectSpeechEmoji<T>(segments:string[],select:(text:string,context:string)=>Promise<T>,onChoice?:(choice:T,index:number)=>void):Promise<T[]> {
 if(segments.length>16)throw new Error('emoji_queue_full');
 const choices:T[]=[];
 // Keep the provider's two slots available to every segment of one voice turn.
 for(let at=0;at<segments.length;at+=2){
  choices.push(...await Promise.all(segments.slice(at,at+2).map(async(text,n)=>{const i=at+n;const choice=await select(text,segments.slice(Math.max(0,i-2),i).join(' '));onChoice?.(choice,i);return choice;})));
 }
 return choices;
}
export class EmojiService {
 readonly catalog:EmojiEntry[];
 private worker:Worker;private counter=0;ready=false;
 private pending=new Map<number,{resolve:(v:any)=>void;reject:(e:Error)=>void;timer:NodeJS.Timeout}>();
 private selected=new Map<string,{at:number;value:any}>();
 private preparing=new Map<string,Promise<EmojiAsset>>();
 private creating=Promise.resolve();
 readonly vercel?:VercelEmojiSelector;
 readonly openrouter?:OpenRouterEmojiSelector;
 get remote(){return this.openrouter??this.vercel;}
 get provider(){return this.openrouter?'openrouter':this.vercel?'vercel':'local';}
 constructor(readonly cfg:NonNullable<Config['emoji']>){
  this.catalog=JSON.parse(readFileSync(cfg.catalog,'utf8'));
  if(cfg.vercel)this.vercel=new VercelEmojiSelector(cfg.vercel);
  if(cfg.openrouter)this.openrouter=new OpenRouterEmojiSelector(cfg.openrouter);
  this.worker=new Worker(new URL('./emoji-worker.js',import.meta.url),{workerData:cfg});
  this.worker.on('message',v=>{if(v.ready){this.ready=true;return;}const p=this.pending.get(v.id);if(!p)return;clearTimeout(p.timer);this.pending.delete(v.id);v.error?p.reject(new Error(v.error)):p.resolve(v);});
  this.worker.on('error',()=>{this.ready=false;this.fail();});this.worker.on('exit',()=>{this.ready=false;this.fail();});
 }
 private fail(){for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(new Error('emoji_unavailable'));}this.pending.clear();}
 async select(text:string,context=''):Promise<any>{
  const key=createHash('sha256').update(JSON.stringify([text,context])).digest('hex');const prior=this.selected.get(key);if(prior&&Date.now()-prior.at<(this.remote&&!prior.value.method.startsWith(this.provider+':')?60000:30*60000))return prior.value;
  if(!this.ready||this.pending.size>=16)throw new Error('emoji_unavailable');
  let value=await new Promise<any>((resolve,reject)=>{const id=++this.counter;const timer=setTimeout(()=>{this.ready=false;this.fail();void this.worker.terminate();reject(new Error('emoji_timeout'));},15000);this.pending.set(id,{resolve,reject,timer});this.worker.postMessage({id,text:text.slice(0,1024),context:context.slice(-1024)});});
  if(value.method!=='explicit'&&this.remote){const decision=await this.remote.select(text,value.candidates??[value.entry],context);if(decision)value=decision;}
  delete value.candidates;
  this.selected.set(key,{at:Date.now(),value});while(this.selected.size>256)this.selected.delete(this.selected.keys().next().value!);return value;
 }
 async choice(text:string,context=''):Promise<EmojiChoice>{const selected=await this.select(text,context);return {...selected,asset:await this.asset(selected.entry.id)};}
 async get(hash:string):Promise<Buffer>{if(!/^[a-f0-9]{64}$/.test(hash))throw new Error('invalid_emoji');const data=await readFile(path.join(this.cfg.cache,hash+'.aem'));if(createHash('sha256').update(data).digest('hex')!==hash)throw new Error('invalid_emoji');return data;}
 async asset(id:string):Promise<EmojiAsset>{
  const entry=this.catalog.find(e=>e.id===id);if(!entry)throw new Error('invalid_emoji');
  try {const meta:EmojiAsset=JSON.parse(await readFile(path.join(this.cfg.cache,id+'.json'),'utf8'));await stat(path.join(this.cfg.cache,meta.sha256+'.aem'));return meta;}catch{}
  const prior=this.preparing.get(id);if(prior)return prior;
  if(this.preparing.size>=16)throw new Error('emoji_queue_full');
  const promise=this.creating.then(()=>this.prepare(entry));this.creating=promise.then(()=>{},()=>{});this.preparing.set(id,promise);
  try{return await promise;}finally{this.preparing.delete(id);}
 }
 private async download(url:string):Promise<Buffer>{
  const response=await fetch(url,{redirect:'error',signal:AbortSignal.timeout(20000)});if(!response.ok||!response.body)throw new Error('emoji_asset_unavailable');
  const parts:Buffer[]=[];let size=0;for await(const chunk of response.body){size+=chunk.length;if(size>16*1024*1024){await response.body.cancel().catch(()=>{});throw new Error('invalid_emoji');}parts.push(Buffer.from(chunk));}return Buffer.concat(parts);
 }
 private async prepare(entry:EmojiEntry):Promise<EmojiAsset>{
  await mkdir(this.cfg.cache,{recursive:true,mode:0o700});
  const assetId=entry.asset_id??entry.id;if(!/^[a-f0-9_]{4,128}$/.test(assetId)||entry.renderable===false)throw new Error('invalid_emoji');
  const base='https://fonts.gstatic.com/s/e/notoemoji/latest/'+assetId+'/';let source:Buffer;let animated=entry.animated;
  try{source=await this.download(base+(animated?'512.gif':'512.png'));}catch{animated=false;source=await this.download(base+'512.png');}
  const meta=await sharp(source,{limitInputPixels:1024*1024}).metadata();if(!meta.width||!meta.height||meta.width>1024||meta.height>1024||(meta.pages??1)>512)throw new Error('invalid_emoji');
  const delays=meta.delay??[100];const total=Math.min(16000,Math.max(100,delays.reduce((a,b)=>a+b,0)));
  const count=animated?Math.min(32,Math.max(2,Math.round(total/100))):1;
  const bytes=Buffer.alloc(16+count*96*96*2);bytes.write('AEM1');bytes.writeUInt16LE(96,4);bytes.writeUInt16LE(96,6);bytes.writeUInt16LE(count,8);bytes.writeUInt16LE(0,10);bytes.writeUInt32LE(total,12);
  for(let frame=0;frame<count;frame++){
   let page=0,elapsed=0;const target=frame*total/count;
   while(page<delays.length-1&&elapsed+delays[page]!<=target){elapsed+=delays[page]!;page++;}
   const raw=await sharp(source,{page,pages:1,limitInputPixels:1024*1024}).resize(96,96,{fit:'contain',background:'#08131f'}).flatten({background:'#08131f'}).removeAlpha().toColourspace('srgb').raw().toBuffer();
   if(raw.length!==96*96*3)throw new Error('invalid_emoji');
   for(let p=0;p<96*96;p++)bytes.writeUInt16LE(((raw[p*3]!>>3)<<11)|((raw[p*3+1]!>>2)<<5)|(raw[p*3+2]!>>3),16+(frame*96*96+p)*2);
  }
  const hash=createHash('sha256').update(bytes).digest('hex');const result={id:entry.id,name:entry.name,sha256:hash,size:bytes.length,animated:count>1,frames:count,duration_ms:total};
  const temp=path.join(this.cfg.cache,randomUUID()+'.tmp');await writeFile(temp,bytes);await rename(temp,path.join(this.cfg.cache,hash+'.aem'));
  const desc=path.join(this.cfg.cache,entry.id+'.json');await writeFile(desc+'.tmp',JSON.stringify(result));await rename(desc+'.tmp',desc);
  return result;
 }
 async stop(){this.fail();await this.worker.terminate();}
}
