import { createHash,verify } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { z } from 'zod';
import type { Config } from './config.js';

export const SignedReleaseSchema=z.object({manifest:z.string().max(4096),signature:z.string().max(1024)}).strict();
export const FirmwareManifestSchema=z.object({target:z.literal('esp32s3'),version:z.string().max(31).regex(/^\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9.-]+)?$/),sha256:z.string().regex(/^[a-f0-9]{64}$/),size:z.number().int().positive().max(4*1024*1024-1),url:z.string().url()}).strict();
export function validateRelease(cfg:Config,raw:unknown){
  const release=SignedReleaseSchema.parse(raw);
  if(!cfg.ota_public_key_file||!verify('sha256',Buffer.from(release.manifest),readFileSync(cfg.ota_public_key_file),Buffer.from(release.signature,'base64')))throw new Error('invalid_signature');
  const manifest=FirmwareManifestSchema.parse(JSON.parse(release.manifest));
  const url=new URL(manifest.url);
  const allowed=cfg.device_gateway_urls?.map(value=>new URL(value).origin.replace('wss:','https:'))??[];
  if(!allowed.includes(url.origin)||url.pathname!=='/v1/device/firmware/'+manifest.sha256||url.search||url.hash)throw new Error('invalid_firmware_url');
  return {release,manifest};
}
export function firmwareHash(data:Buffer){return createHash('sha256').update(data).digest('hex');}
export function firmwareVersion(data:Buffer){
  if(data.length<80||data[0]!==0xe9||data.readUInt32LE(32)!==0xabcd5432)throw Error('invalid_firmware');
  const field=data.subarray(48,80),end=field.indexOf(0);
  if(end<1||field.subarray(0,end).some(b=>b>127))throw Error('invalid_firmware');
  const version=field.subarray(0,end).toString('ascii');
  if(!FirmwareManifestSchema.shape.version.safeParse(version).success)throw Error('invalid_firmware');
  return version;
}
