import { spawn } from 'node:child_process';
import { mkdir,open,readFile,rename,realpath,unlink } from 'node:fs/promises';
import { join,relative,isAbsolute } from 'node:path';
import os from 'node:os';
import { z } from 'zod';
import type { Config,ResourceConfig } from './config.js';
import type { Store } from './store.js';
import { requireEpoch,type Authority } from './leadership.js';
import { ActionSchema,Policy,type Action } from './policy.js';
import { digest,scrub } from './security.js';
import { ObjectStorage } from './objects.js';

export interface ActionResult {action_id:string;state:'completed'|'failed'|'uncertain';summary:string;data?:unknown}
interface JournalEntry {action_hash:string;epoch:string;state:'started'|'completed'|'failed';result?:ActionResult}
interface Evidence {task_id:string;repository:string;node:string;commit:string;passed:boolean;artifact?:string;created_at:string}
interface Deployment {artifact:string;previous:string|null;task_id:string;healthy:boolean}
export async function run(argv:string[],cwd:string,timeout=120000,signal?:AbortSignal,home?:string,extraEnv:Record<string,string>={}):Promise<{code:number;output:string}> {
  if(!argv.length)throw new Error('invalid_command');
  return new Promise((resolve,reject)=>{
    const child=spawn(argv[0]!,argv.slice(1),{cwd,shell:false,detached:process.platform!=='win32',
      env:{PATH:process.env.PATH,HOME:home??process.env.HOME,LANG:'C.UTF-8',GIT_TERMINAL_PROMPT:'0',...extraEnv},stdio:['ignore','pipe','pipe']});
    let output='';let finished=false;
    const collect=(b:Buffer)=>{if(output.length<65536)output+=b.toString().slice(0,65536-output.length);};
    child.stdout.on('data',collect);child.stderr.on('data',collect);
    const stop=()=>{try{if(process.platform!=='win32'&&child.pid)process.kill(-child.pid,'SIGKILL');else child.kill('SIGKILL');}catch{}};
    const timer=setTimeout(stop,timeout);signal?.addEventListener('abort',stop,{once:true});
    child.on('error',e=>{if(!finished){finished=true;clearTimeout(timer);signal?.removeEventListener('abort',stop);reject(e);}});
    child.on('close',code=>{if(!finished){finished=true;clearTimeout(timer);signal?.removeEventListener('abort',stop);resolve({code:code??-1,output});}});
    if(signal?.aborted)stop();
  });
}
export class Executor {
  private locks=new Map<string,Promise<unknown>>();
  private journalDir:string;
  private policy:Policy;
  constructor(private cfg:Config,private store:Store,private auditObjects:Pick<ObjectStorage,'replicate'>=new ObjectStorage(cfg,store)){this.journalDir=join(cfg.state_dir,'actions');this.policy=new Policy(store);}
  private async audit(action:Action,epoch:string,result:ActionResult) {
    const updated_at=new Date().toISOString();
    const record={action,epoch,result,updated_at};
    const ref=await this.auditObjects.replicate(Buffer.from(JSON.stringify(record)));
    await this.store.put('actions/'+action.action_id,{action_id:action.action_id,state:result.state,node:this.cfg.node_id,task_id:action.task_id,action_hash:digest(action),audit_hash:ref.hash,updated_at});
  }
  private async persist(id:string,entry:JournalEntry) {
    await mkdir(this.journalDir,{recursive:true,mode:0o700});
    const target=join(this.journalDir,id+'.json');const temporary=target+'.tmp';const file=await open(temporary,'w',0o600);
    try{await file.writeFile(JSON.stringify(entry));await file.sync();}finally{await file.close();}
    await rename(temporary,target);const directory=await open(this.journalDir,'r');try{await directory.sync();}finally{await directory.close();}
  }
  async status(id:string):Promise<ActionResult|null> {
    if(!z.string().uuid().safeParse(id).success)throw new Error('invalid_action');
    try{const entry:JournalEntry=JSON.parse(await readFile(join(this.journalDir,id+'.json'),'utf8'));
      return entry.result??{action_id:id,state:'uncertain',summary:'Operación iniciada; reconciliar antes de repetir.'};
    }catch(e){if((e as NodeJS.ErrnoException).code==='ENOENT')return null;throw e;}
  }
  async reconcile(raw:unknown,authority:Authority):Promise<ActionResult>{
    const action=ActionSchema.parse(raw);if(action.node!==this.cfg.node_id)throw new Error('invalid_target');await requireEpoch(this.store,authority);
    if(this.locks.has(action.resource||'host'))throw new Error('action_uncertain');
    const entry:JournalEntry=JSON.parse(await readFile(join(this.journalDir,action.action_id+'.json'),'utf8'));if(entry.action_hash!==digest(action))throw new Error('invalid_action');
    if(entry.result?.state==='completed')return entry.result;
    if(action.operation!=='deploy.release')throw new Error('unsupported');
    const resource=this.cfg.resources.find(r=>r.node===this.cfg.node_id&&r.id===action.resource);
    if(!resource?.container_name||!resource.health_url)throw new Error('invalid_resource');
    const inspected=await run(['docker','inspect','--format','{{.Image}}',resource.container_name],resource.path,10000);if(inspected.code!==0)throw new Error('action_uncertain');
    const image=inspected.output.trim(),requested=z.string().regex(/^sha256:[a-f0-9]{64}$/).parse(action.params.artifact);
    const deployed=await this.store.get<Deployment>('deployments/'+resource.id);
    const response=await fetch(resource.health_url,{signal:AbortSignal.timeout(3000),redirect:'error'});const healthy=response.ok;await response.body?.cancel();
    if(!healthy||image!==requested&&image!==deployed?.artifact)throw new Error('action_uncertain');
    const data=image===requested?{artifact:requested,healthy:true,reconciled:true}:{artifact:requested,previous:image,healthy:false,rolled_back:true,rollback_healthy:true,reconciled:true};
    await requireEpoch(this.store,authority);
    const result:ActionResult={action_id:action.action_id,state:'completed',summary:'Resultado reconciliado con el artefacto instalado y su salud.',data};
    await this.persist(action.action_id,{...entry,state:'completed',result});await this.audit(action,authority.epoch,result);return result;
  }
  async execute(raw:unknown,authority:Authority,approval_id?:string):Promise<ActionResult> {
    const action=ActionSchema.parse(raw);
    if(action.node!==this.cfg.node_id)throw new Error('invalid_target');
    const key=action.resource||'host';
    const previous=this.locks.get(key)??Promise.resolve();
    const promise=previous.catch(()=>{}).then(()=>this.perform(action,authority,approval_id));
    this.locks.set(key,promise);try{return await promise;}finally{if(this.locks.get(key)===promise)this.locks.delete(key);}
  }
  private async perform(action:Action,authority:Authority,approval_id?:string):Promise<ActionResult> {
    await requireEpoch(this.store,authority);
    const existing=await this.status(action.action_id);
    if(existing){const entry:JournalEntry=JSON.parse(await readFile(join(this.journalDir,action.action_id+'.json'),'utf8'));if(entry.action_hash!==digest(action))throw new Error('invalid_action');await this.audit(action,entry.epoch,existing);return existing;}
    if(!await this.policy.authorize(action,approval_id))throw new Error('approval_required');
    const resource=this.cfg.resources.find(r=>r.node===this.cfg.node_id&&r.id===action.resource);
    if(action.operation!=='host.status'&&!resource)throw new Error('resource_unavailable');
    // A durable started record survives a crash. Replayed ids never execute again.
    await this.persist(action.action_id,{action_hash:digest(action),epoch:authority.epoch,state:'started'});
    let result:ActionResult;
    const controller=new AbortController();let checking=false;
    const fencing=setInterval(()=>{if(checking)return;checking=true;void requireEpoch(this.store,authority).catch(()=>controller.abort()).finally(()=>{checking=false;});},5000);
    try {
      await requireEpoch(this.store,authority);
      const data=await this.dispatch(action,resource,authority,controller.signal);
      await requireEpoch(this.store,authority);
      result={action_id:action.action_id,state:'completed',summary:'Operación completada.',data};
    }catch(error) {
      result={action_id:action.action_id,state:'uncertain',summary:'No se ha confirmado el resultado; requiere reconciliación.',data:{reason:scrub(error)}};
    }
    clearInterval(fencing);
    await this.persist(action.action_id,{action_hash:digest(action),epoch:authority.epoch,state:result.state==='completed'?'completed':'started',result});
    await this.audit(action,authority.epoch,result);
    return result;
  }
  async worktree(task:string,resource:ResourceConfig):Promise<string> {
    if(!z.string().uuid().safeParse(task).success)throw new Error('invalid_task');
    const worktree=join(this.cfg.state_dir,'worktrees',task);
    const parent=join(this.cfg.state_dir,'worktrees');await mkdir(parent,{recursive:true,mode:0o700});
    const base_commit=(await this.checked(['git','rev-parse','HEAD'],resource.path)).trim();
    const result=await run(['git','worktree','add','-b','codex/agentshell-'+task,worktree,'HEAD'],resource.path);
    if(result.code!==0)throw new Error('resource_unavailable');
    await this.store.put('worktrees/'+task,{path:worktree,repository:resource.id,node:this.cfg.node_id,base_commit});return worktree;
  }
  private async tree(action:Action,resource:ResourceConfig):Promise<string> {
    const record=await this.store.get<{path:string;repository:string;node:string}>('worktrees/'+action.task_id);
    if(!record||record.repository!==resource.id||record.node!==this.cfg.node_id)throw new Error('invalid_worktree');
    const actual=await realpath(record.path),root=await realpath(join(this.cfg.state_dir,'worktrees'));
    const rel=relative(root,actual);if(!rel||rel.startsWith('..')||isAbsolute(rel))throw new Error('invalid_worktree');
    return actual;
  }
  private async checked(argv:string[],cwd:string,timeout=120000):Promise<string> {const result=await run(argv,cwd,timeout);if(result.code!==0)throw new Error('resource_unavailable');return result.output;}
  private async dispatch(action:Action,r:ResourceConfig|undefined,authority:Authority,signal:AbortSignal):Promise<unknown> {
    const checked=async(argv:string[],cwd:string,timeout=120000)=>{const result=await run(argv,cwd,timeout,signal);if(result.code!==0)throw new Error("resource_unavailable");return result.output;};
    if(action.operation==='host.status')return {node:this.cfg.node_id,uptime_s:os.uptime(),load:os.loadavg(),memory:{free:os.freemem(),total:os.totalmem()},platform:process.platform};
    if(!r)throw new Error('resource_unavailable');
    switch(action.operation) {
      case 'git.status':return {text:await checked(['git','status','--short'],r.path)};
      case 'git.diff': {
        if(r.kind!=='repository')throw new Error('invalid_resource');
        const tree=await this.tree(action,r);
        const record=await this.store.get<{base_commit?:string}>('worktrees/'+action.task_id);
        const base=record?.base_commit??(await checked(['git','rev-parse','HEAD'],r.path)).trim();
        if(!/^[a-f0-9]{40,64}$/.test(base))throw new Error('invalid_worktree');
        const committed=await checked(['git','diff','--no-ext-diff','--no-textconv',base,'HEAD','--'],tree);
        const pending=await checked(['git','diff','--no-ext-diff','--no-textconv','HEAD','--'],tree);
        return {text:committed+pending,commit:(await checked(['git','rev-parse','HEAD'],tree)).trim(),truncated:committed.length+pending.length>=65536};
      }
      case 'backup.status':return {configured:true,path_available:await realpath(r.path).then(()=>true).catch(()=>false)};
      case 'docker.status':return {text:await checked(['docker','compose','ps','--format','json'],r.path)};
      case 'docker.logs':return {text:await checked(['docker','compose','logs','--no-color','--tail','100',r.compose_service!],r.path)};
      case 'docker.restart':if(!r.compose_service)throw new Error('invalid_resource');return {text:await checked(['docker','compose','restart',r.compose_service],r.path)};
      case 'git.worktree':if(r.kind!=='repository')throw new Error('invalid_resource');return {path:await this.worktree(action.task_id,r)};
      case 'git.commit': {
        if(r.kind!=='repository')throw new Error('invalid_resource');
        const tree=await this.tree(action,r);const message=z.string().min(1).max(1024).parse(action.params.message);
        await checked(['git','add','--all'],tree);
        await requireEpoch(this.store,authority);
        await checked(['git','-c','user.name=AgentShell','-c','user.email=agentshell@localhost','commit','-m',message],tree);
        return {commit:(await checked(['git','rev-parse','HEAD'],tree)).trim()};
      }
      case 'git.test': {
        if((!r.test_image&&!r.test_sandbox_argv?.length)||!r.test_argv?.length)throw new Error('invalid_resource');
        const tree=await this.tree(action,r);
        const argv=r.test_sandbox_argv?[...r.test_sandbox_argv,...r.test_argv]:['docker','run','--rm','--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=256','--memory=2g','--cpus=2','--tmpfs','/tmp:rw,noexec,nosuid,size=512m','--mount',`type=bind,src=${tree},dst=/workspace`,'--workdir','/workspace',r.test_image!,...r.test_argv];
        const result=await run(argv,tree,600000,signal,r.test_sandbox_home);
        await requireEpoch(this.store,authority);
        const commit=(await checked(['git','rev-parse','HEAD'],tree)).trim();
        const dirty=(await checked(['git','status','--porcelain'],tree)).trim();
        // Deployment evidence requires a committed, immutable source tree.
        const evidence:Evidence={task_id:action.task_id,repository:r.id,node:this.cfg.node_id,commit,passed:result.code===0&&dirty==='',created_at:new Date().toISOString()};
        await this.store.put('evidence/'+action.task_id,evidence);
        return {passed:result.code===0,deployable:evidence.passed,output:result.output,commit};
      }
      case 'artifact.build': {
        const evidence=await this.store.get<Evidence>('evidence/'+action.task_id);
        if(!evidence?.passed||evidence.repository!==r.id||evidence.node!==this.cfg.node_id)throw new Error('invalid_evidence');
        const tree=await this.tree(action,r);
        if((await checked(['git','rev-parse','HEAD'],tree)).trim()!==evidence.commit||(await checked(['git','status','--porcelain'],tree)).trim())throw new Error('invalid_evidence');
        const tag=`agentshell/${r.id}:${evidence.commit}`;
        await checked(['docker','build','--tag',tag,'.'],tree,600000);
        const artifact=(await checked(['docker','image','inspect','--format','{{.Id}}',tag],tree)).trim();
        if(!/^sha256:[a-f0-9]{64}$/.test(artifact))throw new Error('invalid_artifact');
        const dir=join(this.cfg.state_dir,'artifact-staging');await mkdir(dir,{recursive:true,mode:0o700});const archive=join(dir,action.action_id+'.tar');
        const objects=new ObjectStorage(this.cfg,this.store);const chunks:string[]=[];let total_bytes=0;
        try{
          await checked(['docker','save','--output',archive,artifact],tree,600000);
          const file=await open(archive,'r');try{const buffer=Buffer.alloc(4*1024*1024);for(;;){const {bytesRead}=await file.read(buffer,0,buffer.length,null);if(!bytesRead)break;total_bytes+=bytesRead;if(total_bytes>1024*1024*1024)throw new Error('message_too_large');await requireEpoch(this.store,authority);chunks.push((await objects.replicate(buffer.subarray(0,bytesRead),true)).hash);}}finally{await file.close();}
          const descriptor=await objects.replicate(Buffer.from(JSON.stringify({artifact,total_bytes,chunks})),true);
          await requireEpoch(this.store,authority);await this.store.put('artifacts/'+artifact,{...evidence,artifact,descriptor_hash:descriptor.hash});
        }finally{await unlink(archive).catch(()=>{});}
        return {artifact,total_bytes,descriptor_hash:(await this.store.get<{descriptor_hash:string}>('artifacts/'+artifact))!.descriptor_hash};
      }
      case 'deploy.register': {
        if(!r.container_name||!r.health_url)throw new Error('invalid_resource');
        const existing=await this.store.get<Deployment>('deployments/'+r.id);
        const artifact=(await checked(['docker','inspect','--format','{{.Image}}',r.container_name],r.path)).trim();
        if(!/^sha256:[a-f0-9]{64}$/.test(artifact))throw new Error('invalid_artifact');
        const response=await fetch(r.health_url,{signal:AbortSignal.timeout(3000),redirect:'error'});const healthy=response.ok;await response.body?.cancel();if(!healthy)throw new Error('invalid_health');
        if(existing){if(existing.artifact!==artifact)throw new Error('invalid_deployment');return {artifact,healthy:true,already_registered:true};}
        await requireEpoch(this.store,authority);await this.store.put('deployments/'+r.id,{artifact,previous:null,task_id:action.task_id,healthy:true} satisfies Deployment);return {artifact,healthy:true};
      }
      case 'deploy.release': {
        const artifact=z.string().regex(/^sha256:[a-f0-9]{64}$/).parse(action.params.artifact);
        const evidence=await this.store.get<Evidence>('artifacts/'+artifact);
        const previous=await this.store.get<Deployment>('deployments/'+r.id);
        if(!evidence?.passed||evidence.node!==this.cfg.node_id||evidence.repository!==r.source_repository||!previous?.healthy||!r.deploy_argv?.length||!r.rollback_argv?.length||!r.health_url)throw new Error('invalid_evidence');
        const argv=(template:string[],image:string)=>template.map(s=>s.replaceAll('{artifact}',image));
        const ensureImage=async(image:string)=>{
          if((await run(['docker','image','inspect',image],r.path,10000,signal)).code===0)return;
          const record=await this.store.get<{descriptor_hash:string}>('artifacts/'+image);if(!record?.descriptor_hash)throw new Error('invalid_artifact');
          const objects=new ObjectStorage(this.cfg,this.store);
          const descriptor=z.object({artifact:z.literal(image),total_bytes:z.number().int().positive().max(1024*1024*1024),chunks:z.array(z.string().regex(/^[a-f0-9]{64}$/)).min(1).max(256)}).strict().parse(JSON.parse((await objects.get(record.descriptor_hash)).toString()));
          const dir=join(this.cfg.state_dir,'artifact-staging');await mkdir(dir,{recursive:true,mode:0o700});const path=join(dir,action.action_id+'-restore.tar');
          try{const file=await open(path,'w',0o600);let size=0;try{for(const hash of descriptor.chunks){await requireEpoch(this.store,authority);const chunk=await objects.get(hash);size+=chunk.length;if(size>descriptor.total_bytes)throw new Error('invalid_artifact');await file.writeFile(chunk);}if(size!==descriptor.total_bytes)throw new Error('invalid_artifact');await file.sync();}finally{await file.close();}
            await checked(['docker','load','--input',path],r.path,600000);await checked(['docker','image','inspect',image],r.path);
          }finally{await unlink(path).catch(()=>{});}
        };
        // Recover the previous immutable image before touching the running service.
        await ensureImage(previous.artifact);await ensureImage(artifact);
        await requireEpoch(this.store,authority);
        await checked(argv(r.deploy_argv,artifact),r.path,600000);
        let healthy=false;
        for(let i=0;i<10;i++) {try{const res=await fetch(r.health_url,{signal:AbortSignal.timeout(3000),redirect:'error'});healthy=res.ok;await res.body?.cancel();if(healthy)break;}catch{}await new Promise(resolve=>setTimeout(resolve,1000));}
        if(!healthy){
          await requireEpoch(this.store,authority);
          await ensureImage(previous.artifact);
          await checked(argv(r.rollback_argv,previous.artifact),r.path,600000);
          for(let i=0;i<10;i++){try{const res=await fetch(r.health_url,{signal:AbortSignal.timeout(3000),redirect:'error'});healthy=res.ok;await res.body?.cancel();if(healthy)break;}catch{}await new Promise(resolve=>setTimeout(resolve,1000));}
          if(!healthy)throw new Error('rollback_unconfirmed');
          return {artifact,previous:previous.artifact,healthy:false,rolled_back:true,rollback_healthy:true};
        }
        await requireEpoch(this.store,authority);
        await this.store.put('deployments/'+r.id,{artifact,previous:previous.artifact,task_id:action.task_id,healthy:true} satisfies Deployment);
        return {artifact,previous:previous.artifact,healthy:true};
      }
      default:throw new Error('unsupported');
    }
  }
}
