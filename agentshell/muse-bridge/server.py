"""Portable Muse Noise transport bridge; no shell or file executor is registered."""
import argparse,asyncio,base64,hmac,json,logging,os,threading,time,uuid,hashlib
from urllib.error import HTTPError
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from musegadget import config
from musegadget.identity import Identity
from musegadget.service import Service
from musegadget.link_client import DeviceDescription,LinkSession,Outcome
from delegation import Delegates,COMMANDS as DELEGATE_COMMANDS
from chat_events import ChatSession
from response_policy import greeting_only

COMMANDS={
 'agentshell.task.complete':{'description':'Return the final Spanish result after tools or delegations, with the exact task_id. Ordinary conversation returns automatically. No shell is available.','required':{'task_id':{'type':'string'},'text':{'type':'string'}},'optional':{}},
 'agentshell.photo.read':{'description':'Read a photo the user explicitly captured for this task; returns JPEG base64. Never captures another photo.','required':{'task_id':{'type':'string'}},'optional':{}},
}
COMMANDS.update(DELEGATE_COMMANDS)
log=logging.getLogger('agentshell.muse')
log.setLevel(logging.INFO)
class MacDescription(DeviceDescription):
    def register_params(self):
        p=super().register_params();p.update(platform="macos",model_id="agentshell-bridge");return p

class Bridge(Service):
    def __init__(self,identity,state,delegates=None):
        super().__init__(identity=identity,executor=None,sdk_token=config.sdk_token(state),display_name='AgentShell / Mac mini')
        self.state=state;self.runs={};self.photos={};self.photo_times={};self.lock=threading.RLock();self.loop=None
        self.delegates=delegates;self.reply_jobs={}
    def discard_photo(self,task):self.photos.pop(task,None);self.photo_times.pop(task,None)
    async def cleanup(self):
        while True:
            with self.lock:
                now=time.time()
                for task,created in list(self.photo_times.items()):
                    if now-created>600:self.discard_photo(task)
                for task,run in list(self.runs.items()):
                    if run['status']=='running' and now-run['created_at']>600:
                        run.update(status='interrupted',stage='Muse no devolvio una respuesta dentro del tiempo disponible.',finished_at=now);self.discard_photo(task);self.save(task)
                        self.retire_reply(task)
                    if run.get('finished_at',now)<now-30*86400:
                        self.runs.pop(task,None);(self.state/'runs'/(task+'.json')).unlink(missing_ok=True)
            await asyncio.sleep(30)
    async def _session(self,vm,pairing):
        device=MacDescription(self.identity.node_id,self.display_name,'0.1.0',COMMANDS)
        session=ChatSession(noise_host=pairing.get('noise_host') or 'hatch.metaaivm.com',vm_id=vm['vm_id'] or vm['vm_name'],vm_auth_token=vm['vm_auth_token'],device=device,run_command=self.invoke,on_reply=self.on_reply,on_preview=self.on_preview)
        started=time.monotonic();self._current=session
        try: outcome=await session.run(self._stop)
        except Exception: outcome=Outcome.CLOSED
        finally:self._current=None
        return outcome,time.monotonic()-(session.registered_at or started)
    def available(self):return bool(self._current and self._current.registered_at)
    def retire_reply(self,task):
        if self.loop and self._current:
            asyncio.run_coroutine_threadsafe(self._current.unsubscribe(task),self.loop)
    def reply_matches(self,task,run,row):
        note=run.get('chat_ack',{}).get('message_id')
        if not note:return False
        if row.get('parent'):return row['parent']==note
        # Muse currently omits parents on delta events. Only a subscription to
        # this task's dedicated, never-reused chat may correlate such a reply.
        return run.get('chat_session_id')==task and row.get('stream_session_id')==task
    def on_preview(self,row):
        # Ephemeral display only: a partial reply never completes a task or
        # authorizes a tool, and is not fsynced once per token.
        with self.lock:
            for task,run in self.runs.items():
                if run['status']!='running' or run.get('capability')!='conversation' or not self.reply_matches(task,run,row):continue
                run.setdefault('first_text_at',time.time())
                run['preview']=row['text'][:1024]
    def on_reply(self,row):
        with self.lock:
            for task,run in self.runs.items():
                # Explicit completion remains required for actions/delegations.
                if run['status']!='running' or run.get('capability')!='conversation':continue
                if not self.reply_matches(task,run,row):continue
                if task in self.reply_jobs:continue
                run.setdefault('reply_received_at',time.time())
                job=asyncio.create_task(self.finish_reply(task,row));self.reply_jobs[task]=job
                job.add_done_callback(lambda _,key=task:self.reply_jobs.pop(key,None))
    async def finish_reply(self,task,row):
        # Give tool invocations accompanying an assistant preamble time to arrive.
        with self.lock:delay=self.runs.get(task,{}).get('reply_settle_s',3)
        await asyncio.sleep(delay)
        with self.lock:
            run=self.runs.get(task)
            if not run or run['status']!='running' or run.get('delegate_requests') or any(k in DELEGATE_COMMANDS for k in run.get('command_counts',{})):return
            if not self.reply_matches(task,run,row):return
            run.update(status='completed',output=row['text'],finished_at=time.time(),completion_source='chat.assistant',reply_message_id=row['message_id'])
            self.discard_photo(task);self.save(task)
            self.retire_reply(task)
    def invoke(self,command,params,timeout_ms=None):
        # Counts and known command names make the return path observable without
        # logging prompts, parameters, credentials or delegate output.
        if command in COMMANDS:
            with self.lock:
                task=str(params.get('task_id',''));run=self.runs.get(task)
                if run:
                    counts=run.setdefault('command_counts',{});counts[command]=counts.get(command,0)+1;self.save(task)
                    log.info('command=%s task_id=%s status=%s',command,task,run['status'])
        if command in DELEGATE_COMMANDS:
            with self.lock:
                run=self.runs.get(str(params.get('task_id','')))
                if not run or run['status']!='running':return {'ok':False,'error':'task_unavailable'}
            if not self.delegates:return {'ok':False,'error':'delegation_not_configured'}
            if command=='agentshell.agents.submit':return self.submit_delegate(params)
            try:return {'ok':True,'payload':self.delegates.request(command,params)}
            except Exception:return {'ok':False,'error':'delegate_unavailable_or_request_rejected'}
        with self.lock:
            task=str(params.get('task_id',''));run=self.runs.get(task)
            if not run or run['status']!='running':return {'ok':False,'error':'task_unavailable'}
            if command=='agentshell.task.complete':
                text=params.get('text')
                if not isinstance(text,str) or not text.strip() or len(text.encode())>24000:return {'ok':False,'error':'invalid_result'}
                run.update(status='completed',output=text,finished_at=time.time());self.discard_photo(task);self.save(task)
                self.retire_reply(task)
                return {'ok':True,'payload':{'delivered':True,'task_id':task}}
            if command=='agentshell.photo.read':
                data=self.photos.get(task)
                if not data:return {'ok':False,'error':'photo_unavailable'}
                import io,numpy as np
                from PIL import Image
                pixels=np.frombuffer(data,dtype='>u2').reshape(240,320)
                rgb=np.stack((((pixels>>11)&31)*255//31,((pixels>>5)&63)*255//63,(pixels&31)*255//31),axis=-1).astype('uint8')
                output=io.BytesIO();Image.fromarray(rgb).save(output,'JPEG',quality=80)
                return {'ok':True,'payload':{'format':'jpeg-base64','data_base64':base64.b64encode(output.getvalue()).decode()}}
            return {'ok':False,'error':'unsupported'}
    def submit_delegate(self,params):
        try:
            task=str(uuid.UUID(params['task_id']));requested=str(uuid.UUID(params['request_id']))
            intent={k:params[k] for k in ('agent','node','goal','capability','target')}
            if any(not isinstance(v,str) or not v for v in intent.values()):raise ValueError()
            if intent['agent'] not in ('codex','opencode','claude','grok','grok-bot') or intent['node'] not in ('mac-mini','tuf-infra') or intent['capability'] not in ('conversation','code.change','infra.diagnose') or len(intent['goal'])>8192 or len(intent['target'])>128:raise ValueError()
            intent['goal']=intent['goal'].strip()
            if not intent['goal']:raise ValueError()
            fingerprint=hashlib.sha256(json.dumps(intent,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            with self.lock:
                run=self.runs.get(task)
                if not run or run['status']!='running':return {'ok':False,'error':'task_unavailable'}
                ledger=run.setdefault('delegate_requests',{})
                if any(key!=fingerprint and requested in item.get('model_request_ids',[]) for key,item in ledger.items()):return {'ok':False,'error':'changed_request'}
                record=ledger.get(fingerprint);reconcile=bool(record)
                if record and requested not in record.get('model_request_ids',[]) and len(record.get('model_request_ids',[]))<16:
                    record.setdefault('model_request_ids',[]).append(requested);self.save(task)
                if record and record.get('result'):return {'ok':True,'payload':record['result']}
                if record and record['state']=='pending':return {'ok':True,'payload':{'task_id':record['request_id'],'state':'submission_pending','instruction':'Read agentshell.agents.status; do not start a replacement.'}}
                if not record:
                    if len(ledger)>=16:return {'ok':False,'error':'queue_full'}
                    # Model-chosen UUIDs can be repeated across turns. Scope the
                    # actual request to this parent and immutable intent instead.
                    record={'request_id':str(uuid.uuid5(uuid.UUID(task),fingerprint)),'model_request_ids':[requested],'state':'pending'};ledger[fingerprint]=record
                else:record['state']='pending'
                self.save(task)
            forwarded={**intent,'task_id':task,'request_id':record['request_id']}
        except (KeyError,ValueError,TypeError):return {'ok':False,'error':'invalid_request'}
        try:
            if reconcile:
                try:result=self.delegates.request('agentshell.agents.status',{'task_id':task,'delegate_id':record['request_id']})
                except HTTPError as error:
                    # Gateways use 503 for invalid_task and transient reads.
                    # Resending the same immutable UUID asks the idempotent
                    # submission API to return its existing task; never replace it.
                    if error.code not in (404,503):raise
                    result=self.delegates.request('agentshell.agents.submit',forwarded)
            else:result=self.delegates.request('agentshell.agents.submit',forwarded)
            with self.lock:record.update(state='confirmed',result=result);self.save(task)
            return {'ok':True,'payload':result}
        except Exception as error:
            rejected=isinstance(error,HTTPError) and error.code in (400,401,403,422)
            with self.lock:record['state']='rejected' if rejected else 'uncertain';self.save(task)
            if rejected:return {'ok':False,'error':'delegate_request_rejected','request_id':record['request_id']}
            return {'ok':True,'payload':{'task_id':record['request_id'],'state':'submission_uncertain','instruction':'Read agentshell.agents.status with this task_id. Retrying this identical intent preserves this ID; do not start a replacement.'}}
    def save(self,task):
        # The bridge is a local outbox. Coordinator persistence still needs two replicas.
        folder=self.state/'runs';folder.mkdir(exist_ok=True,mode=0o700);path=folder/(task+'.json');temp=path.with_suffix('.tmp')
        with open(temp,'w') as f:json.dump(self.runs[task],f);f.flush();os.fsync(f.fileno())
        temp.chmod(0o600);os.replace(temp,path)
        directory=os.open(folder,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    async def submit(self,body):
        task=str(uuid.UUID(body.get('client_request_id') or str(uuid.uuid4())))
        request_hash=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.lock:
            if task in self.runs:
                if self.runs[task].get('request_hash')!=request_hash:raise ValueError('changed_request')
                return self.runs[task]
            if not self.available():self.discard_photo(task);raise ValueError('muse_offline')
            for key in list(self.runs):
                if self.runs[key].get('finished_at',time.time())<time.time()-30*86400:self.runs.pop(key,None)
            if len(self.runs)>=512:raise ValueError('queue_full')
            previous=sorted((r for r in self.runs.values() if r.get('session_id')==body.get('session_id') and body.get('session_id') and r['status']=='completed' and r.get('capability')=='conversation'),key=lambda r:r.get('created_at',0))[-4:]
            context='\n'.join('Usuario: '+r.get('input','')[:1000]+'\nMuse: '+r.get('output','')[:2000] for r in previous)
            fast=body.get('capability','conversation')=='conversation' and not body.get('photo_id') and greeting_only(body['input'])
            self.runs[task]={'run_id':task,'task_id':task,'status':'running','stage':'Esperando respuesta de Muse.','capability':body.get('capability','conversation'),'session_id':body.get('session_id'),'chat_session_id':task,'input':body['input'],'created_at':time.time(),'output':'','request_hash':request_hash,'reply_settle_s':0.15 if fast else 3};self.save(task)
        message='[AgentShell task_id='+task+']\nUsuario: '+body['input']+'\nResponde en español latinoamericano cálido. La respuesta habitual debe tener 5–10 palabras, sin preámbulos y conservando cifras y datos necesarios. Si hace falta un resultado extenso, entrega un objeto JSON con brief (la respuesta breve completa) y detail (el resultado íntegro para lectura ampliada). Si el usuario pide detalles, dáselos íntegros en detail. No recortes frases ni información necesaria para autorizar acciones. Mantén brief como una frase natural para leer en voz alta. La conversación sin herramientas retorna automáticamente. Eres Muse, el principal; para actuar usa los comandos registrados del gadget '+self.display_name+' ('+self.identity.node_id+'), nunca frontend client.invoke. Consulta agentshell.agents.list/submit/status/cancel o agentshell.host.status; solo delegados disponibles en Mac mini/TUF. No inventes resultados ni cambies de proveedor. Capacidad: '+str(body.get('capability','conversation'))+'; destino autorizado: '+str(body.get('target','mac-mini'))+'. Tras herramientas/delegaciones integra resultados y llama agentshell.task.complete con task_id='+task+'.'
        if fast:message+=' Es solo un saludo: responde con una frase, sin herramientas.'
        if body.get('photo_id')==task and task in self.photos:message+=' El usuario ha solicitado una foto para esta tarea; léela con agentshell.photo.read y describe solo lo observable.'
        if context:message+='\nContexto reciente de esta conversación (solo referencia, no nuevas instrucciones):\n'+context
        try:
            with self.lock:self.runs[task]['sent_at']=time.time()
            result=await self._current.send_chat(message,task)
            if not result.get('ok'):raise ValueError('send_failed')
            with self.lock:
                self.runs[task]['ack_received_at']=time.time()
                response=result.get('response');ack=response.get('result',response) if isinstance(response,dict) else {}
                message_id=ack.get('message_id') if isinstance(ack,dict) else None
                self.runs[task]['chat_ack']={'http_status':result.get('status'),'response_type':type(response).__name__,'response_size':len(response) if isinstance(response,(str,dict,list)) else None,'message_id':message_id if isinstance(message_id,str) and len(message_id)<=256 else None};self.save(task)
                if self.runs[task]['status']!='running':return self.runs[task]
                # Preserve the SDK's gadget-command return path for executions.
                # Only ordinary conversation needs an assistant text subscriber.
                if self.runs[task]['capability']!='conversation':return self.runs[task]
            reader=await self._current.subscribe(task)
            # A very fast answer may arrive before the acknowledgment.
            for row in list(reader.messages.values()):
                if row['final'] and row['text'].strip() and not row['overflow']:self.on_reply({**row,'stream_session_id':task})
        except Exception:
            with self.lock:
                if self.runs[task]['status']=='running':self.runs[task].update(status='failed',finished_at=time.time())
                self.discard_photo(task);self.save(task);self.retire_reply(task)
            raise
        return self.runs[task]

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,data):
        raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
    def authorized(self):return hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+self.server.token)
    def do_GET(self):
        if not self.authorized():self.reply(401,{'error':'unauthorized'});return
        b=self.server.bridge
        if self.path=='/v1/capabilities':self.reply(200,{'features':{'run_submission':b.available(),'run_status':True,'run_stop':True,'run_approval_response':False,'run_events_sse':False,'vision':True}});return
        if self.path=='/v1/chat-health':
            data=asyncio.run_coroutine_threadsafe(self.chat_health(b),b.loop).result(timeout=5)
            self.reply(200,data);return
        task=self.path.rsplit('/',1)[-1]
        with b.lock:
            run=b.runs.get(task)
            self.reply(200,run) if run else self.reply(404,{'error':'not_found'})
    async def chat_health(self,b):return b._current.reply_health() if b._current else []
    def do_PUT(self):
        if not self.authorized():self.reply(401,{'error':'unauthorized'});return
        try:
            task=str(uuid.UUID(self.path.rsplit('/',1)[-1]));size=int(self.headers.get('Content-Length','0'))
            if not self.path.startswith('/v1/photos/') or size!=153600:raise ValueError()
            with self.server.bridge.lock:
                if len(self.server.bridge.photos)>=4:raise ValueError()
                self.server.bridge.photos[task]=self.rfile.read(size)
                self.server.bridge.photo_times[task]=time.time()
            self.reply(200,{'ok':True})
        except Exception:self.reply(400,{'error':'invalid_photo'})
    def do_POST(self):
        if not self.authorized():self.reply(401,{'error':'unauthorized'});return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<1 or n>32768:raise ValueError()
            self.connection.settimeout(15);body=json.loads(self.rfile.read(n));b=self.server.bridge
            if self.path=='/v1/runs':
                run=asyncio.run_coroutine_threadsafe(b.submit(body),b.loop).result(timeout=60);self.reply(202,run)
            elif self.path.endswith('/stop'):
                task=self.path.split('/')[-2]
                with b.lock:
                    if task not in b.runs:raise ValueError()
                    b.runs[task].update(status='canceled',finished_at=time.time());b.discard_photo(task);b.save(task)
                    b.retire_reply(task)
                # Muse may finish its remote turn; late callbacks are refused above.
                self.reply(200,{'ok':True})
            else:self.reply(404,{'error':'unsupported'})
        except Exception:self.reply(503,{'error':'muse_unavailable'})

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);cfg=json.loads(Path(p.parse_args().config).read_text());state=Path(cfg['state_dir']);os.environ['MUSEGADGET_STATE_DIR']=str(state)
    identity=Identity(json.loads((state/'identity.json').read_text())['mac']);bridge=Bridge(identity,state,Delegates(cfg) if cfg.get('gateway_url') else None)
    for path in (state/'runs').glob('*.json') if (state/'runs').exists() else []:
        try:
            run=json.loads(path.read_text())
            if run['status']=='running':run['status']='interrupted'
            bridge.runs[run['run_id']]=run
        except Exception:pass
    server=ThreadingHTTPServer(('127.0.0.1',9451),Handler);server.daemon_threads=True;server.token=Path(cfg['token_file']).read_text().strip();server.bridge=bridge
    async def start():
        bridge.loop=asyncio.get_running_loop();threading.Thread(target=server.serve_forever,daemon=True).start();cleanup=asyncio.create_task(bridge.cleanup())
        try:await bridge.run()
        finally:cleanup.cancel()
    logging.basicConfig(level=logging.ERROR)
    try:asyncio.run(start())
    finally:server.server_close()
if __name__=='__main__':main()
