import { z } from 'zod';
import { randomUUID } from 'node:crypto';

export const VERSION = 1;
export const MAX_JSON = 32 * 1024;
export const MAX_AUDIO = 16000 * 2 * 60;
export const MAX_PHOTO = 320 * 240 * 2;
export const modes = ['idle','presence','listening','thinking','delegating','executing','approval','speaking','warning','offline'] as const;
export const EnvelopeSchema = z.object({
  version: z.literal(VERSION), message_id: z.string().uuid(), session_id: z.string().uuid(),
  task_id: z.string().uuid().nullable(), type: z.string().min(1).max(64),
  sequence: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
  payload: z.record(z.unknown()),
}).strict();
export type Envelope = z.infer<typeof EnvelopeSchema>;
export const TaskRequestSchema = z.object({
  goal: z.string().trim().min(1).max(8192), target: z.string().max(128),
  capability: z.enum(['conversation','infra.diagnose','code.change']),
  preferred_agent: z.enum(['auto','codex','opencode','muse','hermes','claude','grok','grok-bot']),
  context_refs: z.array(z.string().max(256)).max(32).default([]),
}).strict();
export type TaskRequest = z.infer<typeof TaskRequestSchema>;
export type TaskState = 'queued'|'running'|'needs_approval'|'completed'|'failed'|'canceled'|'interrupted'|'reconciling';
export interface Task extends TaskRequest {
  task_id: string; requester: string; agent: string; state: TaskState;
  created_at: string; updated_at: string; summary: string; brief?:string; run_id?: string;
  epoch: string; session_id: string;
  parent_task_id?: string; execution_node?: string;
}
export function envelope(session: string, sequence: number, type: string, payload: Record<string,unknown>, task: string|null = null): Envelope {
  return { version: VERSION, message_id: randomUUID(), session_id: session, task_id: task, type, sequence, payload };
}
export function decodeEnvelope(raw: Buffer): Envelope {
  if (raw.length > MAX_JSON) throw new Error('message_too_large');
  return EnvelopeSchema.parse(JSON.parse(raw.toString('utf8')));
}
// Binary header: ASB1 + session UUID + task UUID + stream UUID + sequence u32 BE + kind u8.
// UUIDs are 16 bytes each. Kind 1 = microphone PCM, 2 = photo RGB565, 3 = speaker PCM.
export const BINARY_HEADER = 57;
export interface MediaFrame { session_id: string; task_id: string; stream_id: string; sequence: number; kind: 1|2|3; data: Buffer }
function uuidBytes(id: string): Buffer { if (!z.string().uuid().safeParse(id).success) throw new Error('invalid_uuid'); return Buffer.from(id.replaceAll('-',''),'hex'); }
function uuidString(buf: Buffer): string { const h=buf.toString('hex'); return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`; }
export function encodeMedia(f: MediaFrame): Buffer {
  const b=Buffer.alloc(BINARY_HEADER); b.write('ASB1'); uuidBytes(f.session_id).copy(b,4);
  uuidBytes(f.task_id).copy(b,20); uuidBytes(f.stream_id).copy(b,36); b.writeUInt32BE(f.sequence,52); b[56]=f.kind;
  return Buffer.concat([b,f.data]);
}
export function decodeMedia(b: Buffer): MediaFrame {
  if(b.length<BINARY_HEADER || b.length>BINARY_HEADER+8192 || b.subarray(0,4).toString()!=='ASB1' || ![1,2,3].includes(b[56]!)) throw new Error('invalid_media_frame');
  return {session_id:uuidString(b.subarray(4,20)),task_id:uuidString(b.subarray(20,36)),stream_id:uuidString(b.subarray(36,52)),sequence:b.readUInt32BE(52),kind:b[56] as 1|2|3,data:b.subarray(BINARY_HEADER)};
}
export class Deduplicator {
  private ids = new Map<string,number>();
  constructor(private limit=4096,private ttl=120000) {}
  accept(id: string, now=Date.now()): boolean {
    for(const [key,expiry] of this.ids) { if(expiry>now) break; this.ids.delete(key); }
    if(this.ids.has(id)) return false;
    this.ids.set(id,now+this.ttl);
    while(this.ids.size>this.limit) this.ids.delete(this.ids.keys().next().value!);
    return true;
  }
}
