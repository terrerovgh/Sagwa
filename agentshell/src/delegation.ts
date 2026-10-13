import {z} from 'zod';
import type {Task} from './protocol.js';

export const DelegateSchema=z.object({
  request_id:z.string().uuid(),agent:z.enum(['codex','opencode','claude','grok','grok-bot']),
  node:z.enum(['mac-mini','tuf-infra']),goal:z.string().trim().min(1).max(8192),
  capability:z.enum(['conversation','infra.diagnose','code.change']),target:z.string().min(1).max(128),
}).strict();
export const liveTask=(t:Task|null)=>!!t&&['queued','running','needs_approval','reconciling'].includes(t.state);
export function requireMuseParent(parent:Task|null):Task {
  if(!parent||parent.agent!=='muse'||parent.parent_task_id||!liveTask(parent))throw Error('invalid_parent_task');
  return parent;
}
