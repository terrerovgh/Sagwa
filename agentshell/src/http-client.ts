import type {IncomingMessage} from 'node:http';
import { request } from 'node:https';
import { readFileSync } from 'node:fs';
import { isIP } from 'node:net';
import type { Config } from './config.js';
import { scrub } from './security.js';
export class PeerClient {
  constructor(private tls:Config['tls']){}
  async request(url:string,method='GET',body?:Buffer,headers:Record<string,string>={},timeout=10000):Promise<Buffer> {
    if(new URL(url).protocol!=='https:')throw new Error('invalid_peer');
    return new Promise((resolve,reject)=>{
      const req=request(url,{method,servername:isIP(new URL(url).hostname)?'':new URL(url).hostname,ca:readFileSync(this.tls.ca),cert:readFileSync(this.tls.cert),key:readFileSync(this.tls.key),rejectUnauthorized:true,
        headers:{...headers,...(body?{'content-length':String(body.length)}:{})},timeout},res=>{
        const chunks:Buffer[]=[];let size=0;
        res.on('data',(b:Buffer)=>{size+=b.length;if(size>16*1024*1024){res.destroy();reject(new Error('message_too_large'));}else chunks.push(b);});
        res.on('end',()=>{const data=Buffer.concat(chunks);if((res.statusCode??500)>=300){let code='operation_failed';try{code=scrub(new Error(JSON.parse(data.toString()).error));}catch{}reject(new Error(code));}else resolve(data);});res.on('error',reject);
      });req.on('error',reject);req.on('timeout',()=>req.destroy(new Error('peer_timeout')));req.end(body);
    });
  }
  async stream(url:string,body:Buffer,signal:AbortSignal):Promise<IncomingMessage>{
    if(new URL(url).protocol!=='https:')throw Error('invalid_peer');
    return new Promise((resolve,reject)=>{
      const req=request(url,{method:'POST',signal,servername:isIP(new URL(url).hostname)?'':new URL(url).hostname,ca:readFileSync(this.tls.ca),cert:readFileSync(this.tls.cert),key:readFileSync(this.tls.key),rejectUnauthorized:true,headers:{'content-type':'application/json','content-length':String(body.length)},timeout:15000},res=>{
        if(res.statusCode!==200){res.destroy();reject(Error('voice_unavailable'));return;}resolve(res);
      });req.on('error',reject);req.on('timeout',()=>req.destroy(Error('peer_timeout')));req.end(body);
    });
  }
  async json<T>(url:string,method='GET',value?:unknown,timeout=10000):Promise<T> {return JSON.parse((await this.request(url,method,value===undefined?undefined:Buffer.from(JSON.stringify(value)),{'content-type':'application/json'},timeout)).toString()) as T;}
}
