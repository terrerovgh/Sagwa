import type { IncomingMessage,ServerResponse } from 'node:http';
import { randomUUID } from 'node:crypto';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { z } from 'zod';
import type { Coordinator } from './coordinator.js';
import { Operations,risk } from './policy.js';
import { body } from './main.js';
import { scrub } from './security.js';
import type { Task } from './protocol.js';

export async function handleMcp(req:IncomingMessage,res:ServerResponse,coordinator:Pick<Coordinator,'action'>) {
  const server=new McpServer({name:'agentshell-infrastructure',version:'0.1.0'});
  for(const operation of Operations.filter(op=>!['agent.request','storage.delete','credentials.rotate','firewall.change'].includes(op))) {
    server.registerTool(operation.replaceAll('.','_'),{
      description:`${operation}: operación tipada sobre un recurso configurado. La política del servidor determina autorización y riesgo.`,
      inputSchema:{task_id:z.string().uuid(),node:z.string().max(64),resource:z.string().max(128),params:z.record(z.unknown()).default({})},
      annotations:{readOnlyHint:risk(operation)==='read',destructiveHint:risk(operation)==='destructive',idempotentHint:risk(operation)==='read'},
    },async args=>{
      try {
        const reply=await coordinator.action({action_id:randomUUID(),operation,...args});
        return {content:[{type:'text' as const,text:JSON.stringify(reply)}]};
      }catch(error){return{isError:true,content:[{type:'text' as const,text:scrub(error)}]};}
    });
  }
  const transport=new StreamableHTTPServerTransport({sessionIdGenerator:undefined,enableJsonResponse:true});
  await server.connect(transport);
  res.on('close',()=>{void transport.close();void server.close();});
  await transport.handleRequest(req,res,req.method==='POST'?JSON.parse((await body(req)).toString()):undefined);
}
// Explicitly pinned A2A JSON-RPC binding v0.3.0; no undocumented protocol guesses.
function a2aTask(task:Task) {
  const states:Record<Task['state'],string>={queued:'submitted',running:'working',needs_approval:'input-required',completed:'completed',failed:'failed',canceled:'canceled',interrupted:'failed',reconciling:'working'};
  return {kind:'task',id:task.task_id,contextId:task.session_id,status:{state:states[task.state],timestamp:task.updated_at,message:{kind:'message',role:'agent',messageId:randomUUID(),parts:[{kind:'text',text:task.summary}]}},
    ...(task.state==='completed'?{artifacts:[{artifactId:task.task_id,parts:[{kind:'text',text:task.summary}]}]}:{})};
}
export async function handleA2A(req:IncomingMessage,res:ServerResponse,coordinator:Pick<Coordinator,'cfg'|'submit'|'task'|'cancel'>) {
  res.setHeader('content-type','application/json');res.setHeader('cache-control','no-store');
  if(req.url==='/.well-known/agent-card.json') {
    res.end(JSON.stringify({name:'AgentShell',description:'Orquestador privado de agentes e infraestructura.',url:'/a2a',version:'0.1.0',protocolVersion:'0.3.0',preferredTransport:'JSONRPC',capabilities:{streaming:false,pushNotifications:false},defaultInputModes:['text'],defaultOutputModes:['text'],securitySchemes:{bearer:{type:'http',scheme:'bearer'}},security:[{bearer:[]}],skills:[{id:'infra.diagnose',name:'Diagnóstico',description:'Consulta infraestructura mediante política central.',tags:['infra']},{id:'code.change',name:'Código',description:'Modifica código en una rama aislada.',tags:['code']},{id:'conversation',name:'Conversación',description:'Conversación con Muse.',tags:['chat']}]}));return;
  }
  const message=JSON.parse((await body(req)).toString());const id=message.id??null;
  try {
    if(message.jsonrpc!=='2.0')throw new Error('invalid_rpc');let result:unknown;
    if(message.method==='message/send') {
      const parts=message.params?.message?.parts;if(!Array.isArray(parts))throw new Error('invalid_message');
      const text=parts.filter((p:any)=>p.kind==='text').map((p:any)=>String(p.text)).join('\n');
      const meta=message.params?.message?.metadata??{};
      const session=z.string().uuid().safeParse(message.params?.message?.contextId);
      const task=await coordinator.submit({goal:text,target:meta.target??coordinator.cfg.node_id,capability:meta.capability??'conversation',preferred_agent:meta.preferred_agent??'auto',context_refs:[]},'a2a:authenticated',session.success?session.data:randomUUID());result=a2aTask(task);
    }else if(message.method==='tasks/get'){const task=await coordinator.task(z.string().uuid().parse(message.params?.id));if(!task)throw new Error('invalid_task');result=a2aTask(task);}
    else if(message.method==='tasks/cancel'){const taskId=z.string().uuid().parse(message.params?.id);await coordinator.cancel(taskId,'a2a:authenticated');result=a2aTask((await coordinator.task(taskId))!);}
    else {res.end(JSON.stringify({jsonrpc:'2.0',id,error:{code:-32601,message:'Method not found'}}));return;}
    res.end(JSON.stringify({jsonrpc:'2.0',id,result}));
  }catch(error){res.end(JSON.stringify({jsonrpc:'2.0',id,error:{code:-32602,message:scrub(error)}}));}
}
