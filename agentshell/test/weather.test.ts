import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {WeatherConfigSchema,WeatherService,parseNWS} from '../src/weather.js';
const now=Date.parse('2026-10-13T14:30:00Z');
const cfg={provider:'nws' as const,city:'Ray City, GA',latitude:31.0749,longitude:-83.1999};
const link='https://api.weather.gov/gridpoints/TAE/75,169/forecast/hourly';
test('captured official NWS response uses updateTime and matches a valid hourly forecast',()=>{
  const fixture=JSON.parse(readFileSync(new URL('./fixtures/nws-hourly-20261013.json',import.meta.url),'utf8'));
  assert.equal(fixture.http_status,200);
  const parsed=parseNWS(fixture.subset,cfg,Date.parse(fixture.at));
  assert.equal(parsed.condition,'cloudy');assert.equal(parsed.temperature_centi_c,1444);
});
function forecast(overrides:Record<string,unknown>={},updated=new Date(now-60000).toISOString()){
  return {properties:{updateTime:updated,periods:[{startTime:'2026-10-13T14:00:00Z',endTime:'2026-10-13T15:00:00Z',
    temperature:77,temperatureUnit:'F',isDaytime:true,icon:'https://api.weather.gov/icons/land/day/skc',...overrides}]}};
}
test('forecast converts units and carries a finite validity window, not ambient readings',()=>{
  const value=parseNWS(forecast(),cfg,now);assert.equal(value.temperature_centi_c,2500);
  assert.equal(value.expires,now+900000);assert.equal(value.condition,'clear');
  assert.equal(parseNWS(forecast({temperature:-.5,temperatureUnit:'C'}),cfg,now).temperature_centi_c,-50);
  assert.equal(parseNWS(forecast({isDaytime:false}),cfg,now).condition,'night');
  assert.equal(parseNWS(forecast({icon:'https://api.weather.gov/icons/land/day/tsra,70'}),cfg,now).condition,'storm');
});
test('invalid units, unbounded temperatures, old/future forecasts and missing current periods fail closed',()=>{
  for(const change of [{temperatureUnit:'K'},{temperature:null},{temperature:1000},{endTime:'2026-10-13T14:10:00Z'},
    {startTime:'2026-10-13T10:00:00Z'},{endTime:'garbage'}])assert.throws(()=>parseNWS(forecast(change),cfg,now));
  for(const updated of ['garbage',new Date(now-6*3600000-1).toISOString(),new Date(now+60001).toISOString()])
    assert.throws(()=>parseNWS(forecast({},updated),cfg,now));
  assert.throws(()=>WeatherConfigSchema.parse({...cfg,city:'city\nfake status'}));
});
test('one shared asynchronous fetch leaves settings immediately available and expires offline cache',async()=>{
  let clock=now,calls=0;let release!:()=>void;
  const gate=new Promise<void>(resolve=>release=resolve);
  const service=new WeatherService(cfg,async(url)=>{calls++;await gate;return url.includes('/points/')?{properties:{forecastHourly:link}}:forecast();},()=>clock);
  for(let i=0;i<30;i++)assert.equal(service.snapshot().available,false);
  assert.equal(calls,1);release();await service.settle();assert.equal(calls,2);
  const packet=service.snapshot();assert.equal(packet.available,true);
  if(packet.available){assert.equal(packet.kind,'forecast');assert.equal(packet.ttl_seconds,900);}
  clock+=900000;assert.equal(service.snapshot().available,false);await service.stop();
});
test('linked forecast cannot redirect to private hosts, alternative schemes, credentials or query URLs',async()=>{
  for(const bad of ['http://api.weather.gov/gridpoints/TAE/75,169/forecast/hourly',
    'https://127.0.0.1/secret','https://api.weather.gov.evil/secret',
    'https://user:secret@api.weather.gov/gridpoints/TAE/75,169/forecast/hourly',link+'?token=no',link+'#x']){
    let calls=0;const service=new WeatherService(cfg,async()=>{calls++;return {properties:{forecastHourly:bad}};},()=>now);
    service.snapshot();await service.settle();assert.equal(service.snapshot().available,false);assert.equal(calls,1);await service.stop();
  }
});
test('outage retries are throttled; shutdown cannot publish delayed weather',async()=>{
  let calls=0;const service=new WeatherService(cfg,async()=>{calls++;throw Error('offline');},()=>now);
  service.snapshot();await service.settle();for(let i=0;i<100;i++)service.snapshot();assert.equal(calls,1);await service.stop();
  const delayed=new WeatherService(cfg,async(url,signal)=>{if(url.includes('/points/'))return {properties:{forecastHourly:link}};
    return new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(Error('aborted')),{once:true}));},()=>now);
  delayed.snapshot();await new Promise(resolve=>setImmediate(resolve));await delayed.stop();assert.equal(delayed.snapshot().available,false);
});
