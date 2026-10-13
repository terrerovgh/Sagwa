import { Etcd3 } from 'etcd3';
import { readFileSync } from 'node:fs';
import type { Config } from './config.js';

export interface Store {
  get<T>(key:string):Promise<T|null>;
  put(key:string,value:unknown):Promise<void>;
  list<T>(prefix:string):Promise<Record<string,T>>;
  comparePut(key:string,expected:unknown|null,value:unknown):Promise<boolean>;
  compareBatch(key:string,expected:unknown|null,value:unknown,extraKey:string,extraValue:unknown):Promise<boolean>;
  delete(key:string):Promise<void>;
  compareDelete(key:string,expected:unknown):Promise<boolean>;
  healthy():Promise<boolean>;
}
export class ClusterStore implements Store {
  readonly client: Etcd3;
  constructor(cfg:Config) {
    this.client=new Etcd3({hosts:cfg.etcd.hosts,credentials:{rootCertificate:readFileSync(cfg.etcd.ca),certChain:readFileSync(cfg.etcd.cert),privateKey:readFileSync(cfg.etcd.key)},
      defaultCallOptions:context=>context.isStream?{}:{deadline:Date.now()+8000},grpcOptions:{'grpc.keepalive_time_ms':10000,'grpc.keepalive_timeout_ms':5000}});
  }
  private key(key:string) { return '/agentshell/v1/'+key; }
  async get<T>(key:string):Promise<T|null> { const value=await this.client.get(this.key(key)).string();return value===null?null:JSON.parse(value) as T; }
  async put(key:string,value:unknown) { await this.client.put(this.key(key)).value(JSON.stringify(value)); }
  async list<T>(prefix:string):Promise<Record<string,T>> { const rows=await this.client.getAll().prefix(this.key(prefix)).strings();return Object.fromEntries(Object.entries(rows).map(([k,v])=>[k.slice('/agentshell/v1/'.length),JSON.parse(v) as T])); }
  async comparePut(key:string,expected:unknown|null,value:unknown):Promise<boolean> {
    const tx=expected===null?this.client.if(this.key(key),'Version','==',0):this.client.if(this.key(key),'Value','==',JSON.stringify(expected));
    return (await tx.then(this.client.put(this.key(key)).value(JSON.stringify(value))).commit()).succeeded;
  }
  async compareBatch(key:string,expected:unknown|null,value:unknown,extraKey:string,extraValue:unknown):Promise<boolean> {
    const tx=expected===null?this.client.if(this.key(key),'Version','==',0):this.client.if(this.key(key),'Value','==',JSON.stringify(expected));
    return (await tx.then(this.client.put(this.key(key)).value(JSON.stringify(value)),this.client.put(this.key(extraKey)).value(JSON.stringify(extraValue))).commit()).succeeded;
  }
  async delete(key:string) { await this.client.delete().key(this.key(key)); }
  async compareDelete(key:string,expected:unknown):Promise<boolean> {
    return (await this.client.if(this.key(key),'Value','==',JSON.stringify(expected)).then(this.client.delete().key(this.key(key))).commit()).succeeded;
  }
  async healthy() {try {await this.client.get('/agentshell/v1/health').string();return true;}catch{return false;} }
  close() {this.client.close();}
}
