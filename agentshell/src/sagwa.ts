import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
export interface AvatarClip {state:number;name:string;frames:number;frame_ms:number;sha256:string;size:number;file:string}
export class SagwaAssets {
 readonly version:string;readonly clips:AvatarClip[];
 constructor(private directory:string){
  const m=JSON.parse(readFileSync(join(directory,'manifest.json'),'utf8'));
  if(typeof m.version!=='string'||m.version.length>64||m.width!==136||m.height!==136||!Array.isArray(m.clips)||m.clips.length!==12)throw Error('invalid_avatar_manifest');
  this.version=m.version;this.clips=m.clips;
  const states=new Set<number>();
  for(const c of this.clips){if(!Number.isInteger(c.state)||c.state<0||c.state>=12||states.has(c.state)||!/^([a-f0-9]{64})\.sav$/.test(c.file)||c.file!==c.sha256+'.sav'||!Number.isInteger(c.size)||c.size>1183760||c.size<16)throw Error('invalid_avatar_clip');states.add(c.state);this.get(c.sha256);}
 }
 get(hash:string){const c=this.clips.find(c=>c.sha256===hash);if(!c)throw Error('avatar_not_found');const data=readFileSync(join(this.directory,c.file));if(data.length!==c.size||createHash('sha256').update(data).digest('hex')!==hash||data.subarray(0,4).toString()!=='SAV1'||data.readUInt16LE(4)!==136||data.readUInt16LE(6)!==136||data.readUInt16LE(12)!==c.state||data.readUInt16LE(14)!==0||data.readUInt16LE(8)!==c.frames||data.readUInt16LE(10)!==c.frame_ms||c.frames<1||c.frames>32||c.frame_ms<67||c.frame_ms>2000||data.length!==16+c.frames*136*136*2)throw Error('invalid_avatar_data');return data;}
 offer(gateway:string){const origin=new URL(gateway.replace(/^wss:/,'https:')).origin;return {state:0,version:this.version,source:'imagegen_sagwa',clips:this.clips.map(({state,name,sha256,size})=>({state,name,sha256,size,url:origin+'/v1/device/avatar/'+sha256}))};}
}
// Structured compact replies preserve the full result; prose is never blindly cut.
export function sagwaReply(text:string):{brief:string;detail:string}{
 try{const m=JSON.parse(text.replace(/^```(?:json)?\s*([\s\S]*?)\s*```$/i,'$1'));if(typeof m.brief==='string'&&m.brief.trim()&&m.brief.length<=512&&typeof m.detail==='string'&&m.detail.length<=65536)return {brief:m.brief.trim(),detail:m.detail.trim()||m.brief.trim()};}catch{}
 return {brief:text,detail:text};
}
