import { z } from 'zod';
import { randomUUID } from 'node:crypto';
import { digest } from './security.js';
import type { Store } from './store.js';

export const Operations = ['host.status','docker.status','docker.logs','backup.status','git.status','git.diff','git.worktree','git.commit','git.test','artifact.build','docker.restart','deploy.register','deploy.release','agent.request','storage.delete','credentials.rotate','firewall.change'] as const;
export const ActionSchema=z.object({
  action_id:z.string().uuid(),task_id:z.string().uuid(),operation:z.enum(Operations),
  node:z.string().max(64),resource:z.string().max(128),params:z.record(z.unknown()),
}).strict();
export type Action=z.infer<typeof ActionSchema>;
export type Risk='read'|'reversible'|'destructive';
export function risk(operation: Action['operation']):Risk {
  if(['host.status','docker.status','docker.logs','backup.status','git.status','git.diff'].includes(operation))return 'read';
  if(['git.worktree','git.commit','git.test','artifact.build','docker.restart','deploy.register','deploy.release'].includes(operation))return 'reversible';
  return 'destructive';
}
export const RuleSchema=z.object({
  rule_id:z.string().uuid(),node:z.string().min(1).max(64),resource:z.string().min(1).max(128),
  operations:z.array(z.enum(['docker.restart','git.worktree','git.commit','git.test','artifact.build','deploy.register','deploy.release'])).min(1),
  enabled:z.boolean(),expires_at:z.string().datetime().nullable(),
}).strict();
export type Rule=z.infer<typeof RuleSchema>;
export interface Approval {
  approval_id:string;action_hash:string;action:Action;risk:Risk;expires_at:number;
  physical_by:string|null;admin_by:string|null;denied:boolean;consumed:boolean;
}
export class Policy {
  constructor(private store:Store){}
  async automatic(action:Action):Promise<boolean> {
    const r=risk(action.operation);
    if(r==='read')return true;
    if(r==='destructive')return false;
    const rules=await this.store.list<Rule>('policy/rules/');
    return Object.values(rules).some(rule=>rule.enabled&&rule.node===action.node&&rule.resource===action.resource&&rule.operations.includes(action.operation as Rule['operations'][number])&&(!rule.expires_at||Date.parse(rule.expires_at)>Date.now()));
  }
  async request(action:Action):Promise<Approval> {
    const approval:Approval={approval_id:randomUUID(),action_hash:digest(action),action,risk:risk(action.operation),expires_at:Date.now()+120000,physical_by:null,admin_by:null,denied:false,consumed:false};
    await this.store.put('approvals/'+approval.approval_id,approval);return approval;
  }
  async decide(id:string,hash:string,origin:'device'|'admin',identity:string,decision:'approve'|'deny'):Promise<Approval> {
    if(!z.string().uuid().safeParse(id).success)throw new Error('invalid_approval');
    for(let attempts=0;attempts<5;attempts++) {
      const previous=await this.store.get<Approval>('approvals/'+id);
      if(!previous||previous.action_hash!==hash||previous.expires_at<=Date.now()||previous.consumed||previous.denied)throw new Error('invalid_approval');
      const next={...previous,denied:decision==='deny'};
      if(decision==='approve') {if(origin==='device')next.physical_by=identity;else next.admin_by=identity;}
      if(await this.store.comparePut('approvals/'+id,previous,next))return next;
    }
    throw new Error('invalid_approval');
  }
  async authorize(action:Action,id?:string):Promise<boolean> {
    if(await this.automatic(action))return true;
    if(!id)return false;
    const a=await this.store.get<Approval>('approvals/'+id);
    if(!a||a.action_hash!==digest(action)||a.denied||a.consumed||a.expires_at<=Date.now()||!a.physical_by)return false;
    if(risk(action.operation)==='destructive'&&!a.admin_by)return false;
    return this.store.comparePut('approvals/'+id,a,{...a,consumed:true});
  }
}
