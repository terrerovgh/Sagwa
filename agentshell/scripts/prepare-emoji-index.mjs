// One-time local multilingual semantic index. No text or embeddings leave the host.
import {pipeline,env} from '@huggingface/transformers';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
const root=path.resolve(import.meta.dirname,'..');
const model=path.join(root,'.private/models/emoji-encoder');
const output=path.join(root,'.private/emoji-index');await mkdir(output,{recursive:true});
const raw=await readFile(path.join(root,'assets/noto/catalog.json'));const catalog=JSON.parse(raw);
env.allowRemoteModels=false;
const encoder=await pipeline('feature-extraction',model,{dtype:'q8',device:'cpu',session_options:{intraOpNumThreads:2,interOpNumThreads:1}});
const matrix=new Float32Array(catalog.length*384);
for(let at=0;at<catalog.length;at+=16) {
 const batch=catalog.slice(at,at+16).map(a=>[a.name,a.english,...a.keywords].join('. ').slice(0,420));
 const result=await encoder(batch,{pooling:'mean',normalize:true,truncation:true,max_length:96});
 matrix.set(result.data,at*384);
 if(at%256===0)console.log(JSON.stringify({indexed:at,total:catalog.length}));
}
const bytes=Buffer.from(matrix.buffer);await writeFile(path.join(output,'matrix.bin'),bytes);
await writeFile(path.join(output,'index.json'),JSON.stringify({rows:catalog.length,dimensions:384,catalog_sha256:createHash('sha256').update(raw).digest('hex'),matrix_sha256:createHash('sha256').update(bytes).digest('hex'),model:'Xenova/paraphrase-multilingual-MiniLM-L12-v2',revision:'2c4055b12046f11709e9df2c122e59ffbdc2f900'},null,2));
console.log(JSON.stringify({ready:true,rows:catalog.length,bytes:bytes.length}));
