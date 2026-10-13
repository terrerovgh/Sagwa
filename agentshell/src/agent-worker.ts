import {createServer} from 'node:http';
import {fileURLToPath} from 'node:url';
import {loadConfig} from './config.js';
import {ClusterStore} from './store.js';
import {ClusterLeadership} from './leadership.js';
import {Coordinator} from './coordinator.js';
import {AgentBroker} from './broker.js';
import {PeerClient} from './http-client.js';
import {bearer,readSecret,scrub} from './security.js';

// A supervised worker keeps its OS authentication context independent of the
// gateway. Only loopback accepts traffic; callers need a dedicated host token.
async function start(path:string,tokenFile:string){
 if(process.getuid?.()===0)throw Error('worker_must_be_unprivileged');
 const cfg=loadConfig(path);cfg.agents.codex={...cfg.agents.codex!,broker:true};
 const store=new ClusterStore(cfg),leadership=new ClusterLeadership(store,cfg),coordinator=new Coordinator(cfg,store,leadership),client=new PeerClient(cfg.tls);
 const broker=new AgentBroker(cfg,store,id=>coordinator.task(id),async(id,request)=>{
  const active=await leadership.current(),peer=cfg.peers.find(p=>p.id===active?.node);
  if(!peer)throw Error('not_leader');return client.json(peer.url+'/internal/coordinator','POST',{kind:'agent.approval',payload:{task_id:id,request}});
 });
 const server=createServer((req,res)=>void(async()=>{
  const reply=(status:number,value:unknown)=>{res.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(value));};
  try{
   if(!bearer(req,readSecret(tokenFile))){reply(401,{error:'unauthorized'});return;}
   const route=(req.url??'').match(/^\/v1\/(capabilities|runs(?:\/([a-f0-9-]{36})(\/stop)?)?)$/);
   if(!route){reply(404,{error:'not_found'});return;}
   if(route[1]==='capabilities'&&req.method==='GET'){reply(200,await broker.capabilities('codex'));return;}
   if(route[2]&&req.method==='GET'){reply(200,await broker.status(route[2]));return;}
   if(route[3]&&req.method==='POST'){await broker.stop(route[2]!);reply(200,{ok:true});return;}
   if(route[1]==='runs'&&req.method==='POST'){
    const chunks:Buffer[]=[];let size=0;req.setTimeout(15000,()=>req.destroy());
    for await(const chunk of req){size+=chunk.length;if(size>32768)throw Error('message_too_large');chunks.push(chunk);}
    reply(202,await broker.submit('codex',JSON.parse(Buffer.concat(chunks).toString())));return;
   }reply(404,{error:'not_found'});
  }catch(error){reply(503,{error:scrub(error)});}
 })().catch(()=>res.destroy()));
 await new Promise<void>(resolve=>server.listen(9454,'127.0.0.1',resolve));
 const stop=()=>void broker.shutdown().finally(()=>{server.close();store.close();process.exit(0);});
 process.on('SIGTERM',stop);process.on('SIGINT',stop);
}
if(process.argv[1]===fileURLToPath(import.meta.url))await start(process.argv[2]!,process.argv[3]!);
