// Read-only UI settings exchange on the secondary gateway, without creating tasks.
import fs from 'node:fs';
import {randomUUID} from 'node:crypto';
import assert from 'node:assert/strict';
import WebSocket from 'ws';
import {envelope} from '../dist/protocol.js';
const root=new URL('../',import.meta.url).pathname;
const ws=new WebSocket('wss://192.168.4.82:9443/v1/device/ws',{ca:fs.readFileSync(root+'.private/device/ca.pem'),cert:fs.readFileSync(root+'.private/device/cert.pem'),key:fs.readFileSync(root+'.private/device/key.pem')});
const replies=[];ws.on('message',data=>{try{replies.push(JSON.parse(data.toString()));}catch{}});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(count){const deadline=Date.now()+15000;while(replies.filter(r=>r.type==='device.settings').length<count&&Date.now()<deadline)await sleep(50);assert.ok(replies.filter(r=>r.type==='device.settings').length>=count);}
try{
 await new Promise((resolve,reject)=>{ws.once('open',resolve);ws.once('error',reject);});
 const session=randomUUID();ws.send(JSON.stringify(envelope(session,0,'device.hello',{last_sequence:0,capabilities:{ui_settings_read_test:true}})));
 await wait(1);await sleep(2100);ws.send(JSON.stringify(envelope(session,1,'device.refresh',{})));await wait(2);
 const data=replies.filter(r=>r.type==='device.settings').at(-1).payload;
 assert.equal(data.nodes.length,3);assert.ok(data.nodes.every(n=>typeof n.available==='boolean'));
 assert.ok(data.agents.some(a=>a.id==='codex'&&a.available));
 assert.ok(data.resources.every(r=>Object.keys(r).sort().join(',')==='id,kind,node'));
 const report={nodes:data.nodes,agents:data.agents.map(a=>({id:a.id,available:a.available})),resources:data.resources,settings_refresh:true,tasks_created:0,private_paths_exposed:false};
 fs.writeFileSync(root+'evidence/device-settings.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
}finally{ws.close();}
