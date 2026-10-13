import {parentPort,workerData} from 'node:worker_threads';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {pipeline,env} from '@huggingface/transformers';
import type {EmojiEntry} from './emoji.js';
const raw=await readFile(workerData.catalog);const catalog:EmojiEntry[]=JSON.parse(raw.toString());
const info=JSON.parse((await readFile(workerData.index+'/index.json')).toString());
const bytes=await readFile(workerData.index+'/matrix.bin');
if(info.catalog_sha256!==createHash('sha256').update(raw).digest('hex')||info.matrix_sha256!==createHash('sha256').update(bytes).digest('hex')||info.rows!==catalog.length||info.dimensions!==384||bytes.length!==catalog.length*384*4)throw new Error('invalid_emoji_index');
const matrix=new Float32Array(bytes.buffer,bytes.byteOffset,bytes.byteLength/4);
env.allowRemoteModels=false;
const encoder:any=await pipeline('feature-extraction',workerData.model,{dtype:'q8',device:'cpu',session_options:{intraOpNumThreads:2,interOpNumThreads:1}});
const normalize=(s:string)=>s.toLowerCase().normalize('NFD').replace(/\p{Diacritic}/gu,'');
const docs=catalog.map(a=>new Set(normalize([a.name,a.english,...a.keywords].join(' ')).split(/[^a-z0-9]+/)));
const phrases=catalog.map(a=>a.keywords.map(normalize).filter(s=>s.includes(' ')&&s.length>6));
const frequency=new Map<string,number>();for(const doc of docs)for(const word of doc)frequency.set(word,(frequency.get(word)??0)+1);
let chain=Promise.resolve();
parentPort!.postMessage({ready:true});
parentPort!.on('message',({id,text,context=''}:{id:number;text:string;context?:string})=>{chain=chain.then(async()=>{
 const explicit=catalog.filter(e=>e.renderable!==false&&text.includes(e.char)).sort((a,b)=>b.char.length-a.char.length)[0];
 if(explicit){parentPort!.postMessage({id,entry:explicit,score:1,method:'explicit'});return;}
 const input=context&&/\b(eso|esto|aquello|también|lo mismo|esa|ese)\b/i.test(text)&&text.split(/\s+/).length<14?context.slice(-240)+' '+text:text;
 const vector=await encoder(input.slice(0,1024),{pooling:'mean',normalize:true,truncation:true,max_length:128});
 const words=normalize(text).match(/[a-z0-9]{3,}/g)??[];
 const stop=new Set(['que','para','con','una','por','del','los','las','estoy','quiero','puedes','como','esto','sobre','tengo','ahora','vamos','hablar','ayuda','need','want','about','with','the']);
 const query=[...new Set(words.filter(w=>!stop.has(w)))];
 const ranked:{row:number;score:number;cosine:number}[]=[];const normalized=normalize(text);
 for(let row=0;row<catalog.length;row++) {
  if(catalog[row]!.renderable===false)continue;
  let similarity=0;for(let n=0;n<384;n++)similarity+=matrix[row*384+n]!*vector.data[n];
  const exact=query.filter(w=>docs[row]!.has(w));
  const lexical=exact.reduce((sum,w)=>sum+Math.min(.13,.022*Math.log(catalog.length/(frequency.get(w)??1))),0);
  const phrase=phrases[row]!.some(p=>normalized.includes(p))?.22:0;
  const domain=catalog[row]!.id==='1f4bb'&&query.some(w=>['codigo','programacion','programar','software','codex','opencode'].includes(w))?.25:0;
  const score=similarity+Math.min(.25,lexical)+phrase+domain;
  ranked.push({row,score,cosine:similarity});
 }
 ranked.sort((a,b)=>b.score-a.score);const best=ranked[0]!;const neutral=best.cosine<.20&&best.score<.30;
 parentPort!.postMessage({id,entry:neutral?catalog.find(e=>e.id==='1f60a'):catalog[best.row],score:best.cosine,method:neutral?'neutral':'semantic',candidates:ranked.slice(0,20).map(r=>catalog[r.row])});
 }).catch(()=>parentPort!.postMessage({id,error:'emoji_inference_failed'}));});
