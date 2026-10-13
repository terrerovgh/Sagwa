import type { Lease } from 'etcd3';
import type { ClusterStore, Store } from './store.js';
import type { Config } from './config.js';

export interface Authority { node: string; epoch: string; lease_id: string }
export interface Leadership {
  current(): Promise<Authority|null>;
  assert(epoch?: string): Promise<Authority>;
}
export class ClusterLeadership implements Leadership {
  private lease?: Lease;
  private mine?: Authority;
  private timer?: NodeJS.Timeout;
  private ticking=false;
  private stopping=false;
  // Standby is deliberately sticky. The preferred host never takes over a live lease.
  constructor(private store: ClusterStore, private cfg: Config) {}
  async current() { return this.store.get<Authority>('control/active'); }
  async assert(epoch?:string) {
    const current=await this.current().catch(()=>{throw new Error('quorum_unavailable');});
    if(!current || current.epoch==='pending' || current.node!==this.cfg.node_id) throw new Error('not_leader');
    if(epoch && current.epoch!==epoch) throw new Error('stale_epoch');
    return current;
  }
  start() {this.timer=setInterval(()=>void this.tick(),5000);void this.tick();}
  private async tick() {
    if(this.ticking||this.stopping) return;
    this.ticking=true;
    try {
      if(this.mine && this.lease) {
        await this.lease.keepaliveOnce({deadline:Date.now()+4000});
        const now=await this.current();
        if(now?.epoch!==this.mine.epoch) await this.release();
      } else if(this.cfg.coordinator_candidates.includes(this.cfg.node_id)) {
        const current=await this.current();
        if(!current) {
          const handoff=await this.store.get<{target:string;expires_at:number}>('control/handoff');
          if(handoff&&handoff.expires_at>Date.now()&&handoff.target!==this.cfg.node_id)return;
          // Election is one etcd transaction. Its revision is the fencing epoch.
          const lease=this.store.client.lease(45,{autoKeepAlive:false});
          const id=await lease.grant();
          const prefix='/agentshell/v1/control/';
          const response=await this.store.client.if(prefix+'active','Version','==',0)
            .then(lease.put(prefix+'active').value(JSON.stringify({node:this.cfg.node_id,epoch:'pending',lease_id:id}))).commit();
          if(response.succeeded) {
            const epoch=String(response.header.revision);
            const pending={node:this.cfg.node_id,epoch:'pending',lease_id:id};
            const mine={...pending,epoch};
            const finish=await this.store.client.if(prefix+'active','Value','==',JSON.stringify(pending))
              .then(lease.put(prefix+'active').value(JSON.stringify(mine))).commit();
            if(finish.succeeded){this.mine=mine;this.lease=lease;lease.on('lost',()=>{this.mine=undefined;this.lease=undefined;});}
            else await lease.revoke();
          } else await lease.revoke();
        }
      }
    } catch {
      // Never continue claiming local leadership after a failed renewal.
      this.mine=undefined;
      if(this.lease){this.lease.release();this.lease=undefined;}
    } finally {this.ticking=false;}
  }
  async yieldTo(target:string) {
    await this.assert();
    if(!this.cfg.coordinator_candidates.includes(target) || target===this.cfg.node_id) throw new Error('invalid_target');
    await this.store.put('control/handoff',{target,expires_at:Date.now()+60000});
    await this.release();
  }
  async enable() {await this.tick();}
  private async release() {const lease=this.lease;this.mine=undefined;this.lease=undefined;if(lease) await lease.revoke().catch(()=>{});}
  async stop() {this.stopping=true;if(this.timer)clearInterval(this.timer);await this.release();}
}
export async function requireEpoch(store:Store,authority:Authority):Promise<void> {
  const live=await store.get<Authority>('control/active').catch(()=>{throw new Error('quorum_unavailable');});
  if(!live || live.epoch==='pending' || live.node!==authority.node || live.epoch!==authority.epoch) throw new Error('stale_epoch');
}
