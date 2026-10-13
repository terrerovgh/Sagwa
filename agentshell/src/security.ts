import { createHash, timingSafeEqual } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { TLSSocket } from 'node:tls';
import type { IncomingMessage } from 'node:http';

export function canonical(value: unknown): string {
  if(value===null || typeof value!=='object') return JSON.stringify(value);
  if(Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
  return '{'+Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>JSON.stringify(k)+':'+canonical(v)).join(',')+'}';
}
export function digest(value: unknown): string { return createHash('sha256').update(canonical(value)).digest('hex'); }
export function readSecret(file: string): string {
  const secret=readFileSync(file,'utf8').trim();
  if(secret.length<32) throw new Error('secret_too_short');
  return secret;
}
export function bearer(req: IncomingMessage, secret: string): boolean {
  const value=req.headers.authorization;
  if(typeof value!=='string' || !value.startsWith('Bearer ')) return false;
  const a=Buffer.from(value.slice(7)),b=Buffer.from(secret);
  return a.length===b.length && timingSafeEqual(a,b);
}
export function certificateIdentity(req: IncomingMessage): string|null {
  const socket=req.socket;
  if(!(socket instanceof TLSSocket) || !socket.authorized) return null;
  const cert=socket.getPeerCertificate();
  const identity=cert.subject?.CN;
  return typeof identity==='string' ? identity : null;
}
export function scrub(error: unknown): string {
  // Never expose upstream response bodies or SDK errors: they can contain prompts and credentials.
  if(error instanceof Error && /^(quorum_unavailable|not_leader|stale_epoch|unsupported|agent_unavailable|approval_required|policy_denied|resource_unavailable|action_uncertain|rollback_unconfirmed|invalid_[a-z_]+|message_too_large)$/.test(error.message)) return error.message;
  return 'operation_failed';
}
