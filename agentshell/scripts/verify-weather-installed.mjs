// Isolated installed-module smoke: no WSS hello, tasks, voice or live cache reads.
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const [modulePath,configPath]=process.argv.slice(2);
const cfg=JSON.parse(fs.readFileSync(configPath,'utf8')).weather;
assert.deepEqual(cfg,{provider:'nws',city:'Ray City, GA',latitude:31.0728,longitude:-83.1901});
const {WeatherService}=await import(pathToFileURL(modulePath).href);
const service=new WeatherService(cfg);const start=Date.now();let snapshot;
try {
 snapshot=service.snapshot();
 while(!snapshot.available&&Date.now()-start<8000){await new Promise(resolve=>setTimeout(resolve,100));snapshot=service.snapshot();}
 assert.equal(snapshot.available,true,'NWS not available in bounded installed-module smoke');
 assert.equal(snapshot.city,'Ray City, GA');assert.equal(snapshot.kind,'forecast');assert.equal(snapshot.source,'nws');
 console.log(JSON.stringify({at:new Date().toISOString(),scope:'Installed module and fixed config under service host/container; isolated weather cache, not WSS/Core display acceptance',configured:cfg,weather:snapshot,first_valid_ms:Date.now()-start,tasks_created:0,voice_requests:0,credentials_emitted:false}));
} finally {await service.stop();}
