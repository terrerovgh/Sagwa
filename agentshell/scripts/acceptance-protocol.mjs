import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';
import assert from 'node:assert/strict';
import WebSocket from 'ws';
import {envelope} from '../dist/protocol.js';
import {PeerClient} from '../dist/http-client.js';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const cfg=JSON.parse(fs.readFileSync(root+'/.private/mac-mini/config.json'));
const tls={ca:fs.readFileSync(root+'/.private/device/ca.pem')};
const url='wss://192.168.4.82:9443/v1/device/ws';const results={};
async function rejected(extra={}){
  return new Promise((resolve,reject)=>{const ws=new WebSocket(url,{...tls,...extra});const timeout=setTimeout(()=>{ws.terminate();reject(Error('timeout'));},10000);
    ws.on('open',()=>{ws.close();clearTimeout(timeout);reject(Error('invalid_certificate_accepted'));});
    ws.on('unexpected-response',(_request,response)=>{response.resume();clearTimeout(timeout);resolve(response.statusCode);});
    ws.on('error',()=>{clearTimeout(timeout);resolve('tls_rejected');});});
}
results.missing_certificate=await rejected();assert.equal(results.missing_certificate,403);
results.wrong_role_certificate=await rejected({cert:fs.readFileSync(cfg.tls.cert),key:fs.readFileSync(cfg.tls.key)});assert.equal(results.wrong_role_certificate,403);
results.untrusted_certificate=await rejected({cert:fs.readFileSync(root+'/.private/mac-mini/etcd-tls/cert.pem'),key:fs.readFileSync(root+'/.private/mac-mini/etcd-tls/key.pem')});assert.equal(results.untrusted_certificate,403);
const ws=new WebSocket(url,{...tls,cert:fs.readFileSync(root+'/.private/device/cert.pem'),key:fs.readFileSync(root+'/.private/device/key.pem')});
const messages=[];ws.on('message',data=>{try{messages.push(JSON.parse(data));}catch{}});
async function waitFor(predicate){const until=Date.now()+15000;while(Date.now()<until){if(predicate())return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('protocol_timeout: '+JSON.stringify(messages.map(m=>({type:m.type,code:m.payload?.code}))));}
await new Promise((resolve,reject)=>{ws.once('open',resolve);ws.once('error',reject);});
const session=randomUUID(),task=randomUUID();ws.send(JSON.stringify(envelope(session,0,'device.hello',{last_sequence:0,capabilities:{acceptance_test:true}})));
await waitFor(()=>messages.some(m=>m.type==='device.snapshot'));
const request={goal:'Prueba de deduplicación del protocolo; no ejecutes herramientas ni uses proveedores alternativos.',target:'mac-mini',capability:'conversation',preferred_agent:'muse',context_refs:[]};
const message=JSON.stringify(envelope(session,1,'task.submit',request,task));ws.send(message);ws.send(message);
await waitFor(()=>messages.some(m=>m.type==='task.accepted'&&m.task_id===task));await new Promise(resolve=>setTimeout(resolve,200));
assert.equal(messages.filter(m=>m.type==='task.accepted'&&m.task_id===task).length,1);results.duplicate_message_accepted_once=true;
ws.send(JSON.stringify(envelope(session,2,'task.submit',{...request,goal:'Alteración de parámetros de la misma tarea.'},task)));
await waitFor(()=>messages.some(m=>m.type==='error'&&m.payload.code==='invalid_task'));results.duplicate_task_changed_parameters_rejected=true;
const canceled=randomUUID();ws.send(JSON.stringify(envelope(session,3,'task.cancel',{},canceled)));ws.send(JSON.stringify(envelope(session,4,'media.start',{stream_id:canceled,kind:1},canceled)));ws.send(JSON.stringify(envelope(session,5,'media.end',{stream_id:canceled},canceled)));
await new Promise(resolve=>setTimeout(resolve,500));assert(!messages.some(m=>m.type==='voice.transcript'&&m.task_id===canceled));results.canceled_audio_not_transcribed=true;
ws.close();
const client=new PeerClient(cfg.tls);const token=fs.readFileSync(cfg.admin_token_file,'utf8').trim();
const tasks=JSON.parse((await client.request('https://100.68.191.53:9443/v1/tasks','GET',undefined,{Authorization:'Bearer '+token})).toString());assert.equal(tasks.filter(t=>t.task_id===task).length,1);assert(!tasks.some(t=>t.task_id===canceled));results.duplicate_task_persisted_once=true;
fs.mkdirSync(root+'/evidence',{recursive:true});fs.writeFileSync(root+'/evidence/protocol.json',JSON.stringify(results,null,2)+'\n');console.log(JSON.stringify(results,null,2));
