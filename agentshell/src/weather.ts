import {z} from 'zod';

// Fixed, explicitly configured location. No device location, account identity,
// microphone, or business contact is sent to the weather provider.
export const WeatherConfigSchema=z.object({
  provider:z.literal('nws'),
  city:z.string().min(1).max(40).regex(/^[A-Za-z0-9 .,'()-]+$/),
  latitude:z.number().finite().min(-90).max(90),
  longitude:z.number().finite().min(-180).max(180),
}).strict();
export type WeatherConfig=z.infer<typeof WeatherConfigSchema>;
export type WeatherCondition='clear'|'cloudy'|'rain'|'storm'|'snow'|'fog'|'night'|'unknown';
export type WeatherPacket={schema:1;available:false;reason:'unconfigured'|'unavailable'}|
  {schema:1;available:true;source:'nws';kind:'forecast';city:string;temperature_centi_c:number;condition:WeatherCondition;ttl_seconds:number};
type Cached={city:string;temperature_centi_c:number;condition:WeatherCondition;expires:number};
type Fetcher=(url:string,signal:AbortSignal)=>Promise<unknown>;

function nwsURL(value:unknown):string {
  if(typeof value!=='string')throw Error('invalid_weather_url');
  const u=new URL(value);
  if(u.protocol!=='https:'||u.hostname!=='api.weather.gov'||u.port||u.username||u.password||u.search||u.hash||
    !/^\/gridpoints\/[A-Z]{3}\/\d{1,4},\d{1,4}\/forecast\/hourly$/.test(u.pathname))throw Error('invalid_weather_url');
  return u.href;
}
async function fetchNWS(url:string,signal:AbortSignal):Promise<unknown> {
  const response=await fetch(url,{signal,redirect:'error',headers:{'User-Agent':'SagwaCoreS3/0.3-weather','Accept':'application/geo+json'}});
  if(!response.ok||!response.body)throw Error('weather_unavailable');
  const reader=response.body.getReader();const parts:Uint8Array[]=[];let bytes=0;
  try {for(;;){const next=await reader.read();if(next.done)break;bytes+=next.value.byteLength;
    if(bytes>512*1024)throw Error('weather_too_large');parts.push(next.value);}
    return JSON.parse(Buffer.concat(parts).toString('utf8'));
  } finally {await reader.cancel().catch(()=>{});}
}
function condition(icon:unknown,day:unknown):WeatherCondition {
  if(typeof icon!=='string')return 'unknown';
  const u=new URL(icon);
  if(u.protocol!=='https:'||u.hostname!=='api.weather.gov')return 'unknown';
  const token=u.pathname.split('/').at(-1)?.split(',')[0];
  if(!token)return 'unknown';
  if(/^(tsra|tsra_sct|tsra_hi)$/.test(token))return 'storm';
  if(/^(snow|rain_snow|rain_sleet|snow_sleet|fzra|sleet|blizzard)$/.test(token))return 'snow';
  if(/^(rain|rain_showers|rain_showers_hi)$/.test(token))return 'rain';
  if(/^(fog|haze|smoke|dust)$/.test(token))return 'fog';
  if(/^(skc|few)$/.test(token))return day===false?'night':'clear';
  if(/^(sct|bkn|ovc)$/.test(token))return 'cloudy';
  return 'unknown';
}
export function parseNWS(raw:unknown,cfg:WeatherConfig,now:number):Cached {
  const data=z.object({properties:z.object({updateTime:z.string(),periods:z.array(z.object({
    startTime:z.string(),endTime:z.string(),temperature:z.number().finite(),temperatureUnit:z.enum(['C','F']),
    icon:z.string().optional(),isDaytime:z.boolean().optional(),
  })).max(200)})}).parse(raw);
  const updated=Date.parse(data.properties.updateTime);
  // Forecast publication time is not an observation timestamp. Limit upstream
  // age to six hours as well as requiring a currently valid hourly period.
  if(!Number.isFinite(updated)||updated>now+60000||now-updated>6*3600000)throw Error('weather_stale');
  const period=data.properties.periods.find(p=>Date.parse(p.startTime)<=now&&Date.parse(p.endTime)>now);
  if(!period)throw Error('weather_no_current_period');
  const end=Date.parse(period.endTime),start=Date.parse(period.startTime);
  if(!Number.isFinite(end)||!Number.isFinite(start)||end-start>2*3600000||end-start<=0)throw Error('weather_invalid_period');
  const c=period.temperatureUnit==='F'?(period.temperature-32)*5/9:period.temperature;
  if(c< -90||c>60)throw Error('weather_invalid_temperature');
  return {city:cfg.city,temperature_centi_c:Math.round(c*100),condition:condition(period.icon,period.isDaytime),
    expires:Math.min(now+900000,end,updated+6*3600000)};
}
// One bounded in-flight request for all device connections. snapshot() never
// awaits weather I/O; voice, task polling and reconnects remain independent.
export class WeatherService {
  private cache?:Cached;private next=0;private pending?:Promise<void>;private controller?:AbortController;
  private stopped=false;
  constructor(private cfg:WeatherConfig,private fetcher:Fetcher=fetchNWS,private clock=Date.now){WeatherConfigSchema.parse(cfg);}
  snapshot():WeatherPacket {
    const now=this.clock();
    if(!this.stopped&&now>=this.next&&!this.pending){
      this.next=now+60000;
      this.controller=new AbortController();
      const controller=this.controller;
      const timeout=setTimeout(()=>controller.abort(),5000);timeout.unref();
      this.pending=this.refresh(now,controller.signal).catch(()=>{}).finally(()=>{clearTimeout(timeout);this.pending=undefined;});
    }
    const ttl=this.cache?Math.floor((this.cache.expires-now)/1000):0;
    if(!this.cache||ttl<1||ttl>900)return {schema:1,available:false,reason:'unavailable'};
    return {schema:1,available:true,source:'nws',kind:'forecast',city:this.cache.city,
      temperature_centi_c:this.cache.temperature_centi_c,condition:this.cache.condition,ttl_seconds:ttl};
  }
  private async refresh(now:number,signal:AbortSignal){
    const points=await this.fetcher(`https://api.weather.gov/points/${this.cfg.latitude.toFixed(4)},${this.cfg.longitude.toFixed(4)}`,signal);
    const link=z.object({properties:z.object({forecastHourly:z.string()})}).parse(points);
    const raw=await this.fetcher(nwsURL(link.properties.forecastHourly),signal);
    if(signal.aborted||this.stopped)return;
    this.cache=parseNWS(raw,this.cfg,this.clock());this.next=now+600000;
  }
  async settle(){await this.pending;}
  async stop(){this.stopped=true;this.controller?.abort();await this.pending;}
}
