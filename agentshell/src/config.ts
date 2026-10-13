import { readFileSync } from 'node:fs';
import { z } from 'zod';
import {WeatherConfigSchema} from './weather.js';

const TLS = z.object({ca:z.string(),cert:z.string(),key:z.string()}).strict();
const Peer = z.object({id:z.string(),url:z.string().url()}).strict();
const Agent = z.object({enabled:z.boolean().default(false),url:z.string().url().optional(),
  broker:z.boolean().default(false),agent_home:z.string().optional(),permission_profile:z.string().optional(),local_url:z.string().url().optional(),secret_file:z.string().optional(),command:z.string().optional(),args:z.array(z.string()).default([]),
  version:z.string().optional(),model:z.string().optional(),paid_api:z.boolean().default(false)}).strict();
const Resource = z.object({id:z.string(),node:z.string(),kind:z.enum(['service','repository']),
  path:z.string(),compose_service:z.string().optional(),health_url:z.string().url().optional(),
  container_name:z.string().regex(/^[a-zA-Z0-9][a-zA-Z0-9_.-]+$/).optional(),
  test_argv:z.array(z.string()).optional(),test_image:z.string().optional(),
  test_sandbox_argv:z.array(z.string()).min(1).optional(),test_sandbox_home:z.string().optional(),
  source_repository:z.string().optional(),deploy_argv:z.array(z.string()).optional(),rollback_argv:z.array(z.string()).optional()}).strict();
const Schema = z.object({
  node_id:z.string().regex(/^[a-z0-9-]{1,64}$/), roles:z.array(z.enum(['gateway','coordinator','executor','objects'])),
  listen:z.object({host:z.string(),port:z.number().int().min(1).max(65535)}), tls:TLS,
  state_dir:z.string(),
  emoji:z.object({catalog:z.string(),model:z.string(),index:z.string(),cache:z.string(),vercel:z.object({key_file:z.string(),models:z.array(z.enum(['typesafe-ai/jev','convaiinnovations/laya'])).min(1).max(2),free_only:z.literal(true).default(true)}).strict().optional(),openrouter:z.object({key_file:z.string(),models:z.array(z.literal('inception/mercury-decide:free')).min(1).max(1),free_only:z.literal(true).default(true)}).strict().optional()}).strict().refine(v=>!(v.vercel&&v.openrouter),'choose_one_emoji_provider').optional(),
  etcd:z.object({hosts:z.array(z.string().url()).min(3).max(3),...TLS.shape}),
  coordinator_candidates:z.array(z.string()).min(2).max(2), peers:z.array(Peer).min(3).max(3),
  device_ids:z.array(z.string()), admin_token_file:z.string(),
  avatar:z.object({directory:z.string()}).strict().optional(),
  weather:WeatherConfigSchema.optional(),
  voice:z.object({url:z.string().url(),token_file:z.string()}),
  agents:z.record(Agent), resources:z.array(Resource).default([]),
  agent_workers:z.record(z.record(Agent)).default({}),
  tools_token_file:z.string().optional(),paid_agents_allowed:z.array(z.string()).default([]),retention_days:z.literal(30).default(30),paid_apis_enabled:z.boolean().default(false),
  ota_public_key_file:z.string().optional(),device_gateway_urls:z.array(z.string().url()).length(2).optional(),
}).strict();
export type Config = z.infer<typeof Schema>;
export type ResourceConfig = z.infer<typeof Resource>;
export function loadConfig(path: string): Config {
  const cfg=Schema.parse(JSON.parse(readFileSync(path,'utf8')));
  if(!cfg.peers.some(p=>p.id===cfg.node_id)) throw new Error('node_missing_from_peers');
  for(const peer of cfg.peers) if(new URL(peer.url).protocol!=='https:') throw new Error('peer_requires_https');
  for(const host of cfg.etcd.hosts) if(new URL(host).protocol!=='https:') throw new Error('etcd_requires_https');
  if(new Set(cfg.peers.map(p=>p.id)).size!==3) throw new Error('duplicate_peer');
  return cfg;
}
