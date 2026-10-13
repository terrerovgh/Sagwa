import Anthropic from '@anthropic-ai/sdk';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import type { Config } from './config.js';
import type { Task } from './protocol.js';
import type { Adapter,AgentCapabilities,AgentContext,AgentRun } from './adapters.js';

// Explicit API integrations. They expose conversation only and receive no host
// tools, deployment credentials, filesystem access or automatic provider fallback.
export class ProviderAdapter implements Adapter {
  private runs=new Map<string,{state:string;controller:AbortController}>();
  constructor(readonly id:'claude'|'grok',private settings:Config['agents'][string]){}
  private key(){if(!this.settings.secret_file)throw Error('agent_unavailable');const value=readFileSync(this.settings.secret_file,'utf8').trim();if(!value||value.length>8192)throw Error('agent_unavailable');return value;}
  async capabilities():Promise<AgentCapabilities>{
    let available=false;try{available=this.settings.enabled&&!!this.settings.model&&!!this.key();}catch{}
    return{id:this.id,available,streaming:this.id==='claude',cancel:true,approvals:false,...(!available?{reason:'Requiere modelo y credencial API compatible configurados en el host.'}:{})};
  }
  async submit(task:Task,ctx:AgentContext):Promise<AgentRun>{
    if(!(await this.capabilities()).available)throw Error('agent_unavailable');
    if(task.capability!=='conversation'||ctx.photo)throw Error('unsupported');
    for(const [id,run] of this.runs)if(run.state!=='running')this.runs.delete(id);
    if(this.runs.size>=64)throw Error('queue_full');
    const id=randomUUID(),controller=new AbortController();const state={state:'running',controller};this.runs.set(id,state);
    const done=(async()=>{
      const timeout=setTimeout(()=>controller.abort(),120000);
      try{
        await ctx.emit({type:'stage',text:this.id+' procesando la conversación.'});let text='';
        if(this.id==='claude'){
          const client=new Anthropic({apiKey:this.key(),maxRetries:0,timeout:120000});
          const stream=await client.messages.create({model:this.settings.model!,max_tokens:2048,system:'Responde en español. No tienes herramientas de infraestructura; no afirmes haber ejecutado acciones.',messages:[{role:'user',content:task.goal}],stream:true},{signal:controller.signal});
          for await(const event of stream)if(event.type==='content_block_delta'&&event.delta.type==='text_delta'){
            text+=event.delta.text;if(Buffer.byteLength(text)>65536){controller.abort();throw Error('message_too_large');}await ctx.emit({type:'delta',text:event.delta.text});
          }
        }else{
          const response=await fetch('https://api.x.ai/v1/responses',{method:'POST',headers:{Authorization:'Bearer '+this.key(),'Content-Type':'application/json'},body:JSON.stringify({model:this.settings.model,input:[{role:'system',content:'Responde en español. No tienes herramientas de infraestructura; no afirmes haber ejecutado acciones.'},{role:'user',content:task.goal}],max_output_tokens:2048,store:false}),signal:controller.signal,redirect:'error'});
          if(!response.ok){await response.body?.cancel();throw Error('agent_request_failed');}
          const chunks:Uint8Array[]=[];let size=0;for await(const chunk of response.body!){size+=chunk.length;if(size>1024*1024){await response.body?.cancel();throw Error('message_too_large');}chunks.push(chunk);}
          const data=JSON.parse(Buffer.concat(chunks).toString());
          text=(data.output??[]).filter((part:any)=>part.type==='message').flatMap((part:any)=>part.content??[]).filter((part:any)=>part.type==='output_text').map((part:any)=>String(part.text)).join('\n');
          if(!text||Buffer.byteLength(text)>65536)throw Error('agent_request_failed');
        }
        if(state.state==='canceled')return;state.state='completed';await ctx.emit({type:'completed',text});
      }catch{
        if(state.state!=='canceled'){state.state='failed';await ctx.emit({type:'failed',text:'El proveedor no completó la solicitud. No se ha llamado a otro proveedor.'});}
      }finally{clearTimeout(timeout);}
    })();done.catch(()=>{});return{id,done,cancel:()=>this.cancel(id)};
  }
  async status(id:string){return this.runs.get(id)?.state??'unknown';}
  async cancel(id:string){const run=this.runs.get(id);if(!run)throw Error('unsupported');run.state='canceled';run.controller.abort();}
}
