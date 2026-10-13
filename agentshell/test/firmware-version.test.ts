import test from 'node:test';
import assert from 'node:assert/strict';
import {firmwareVersion} from '../src/releases.js';
test('release version comes from the signed application descriptor, rejecting missing or malformed metadata',()=>{
 const image=Buffer.alloc(256);image[0]=0xe9;image.writeUInt32LE(0xabcd5432,32);image.write('0.1.13',48);
 assert.equal(firmwareVersion(image),'0.1.13');
 for(const bad of [Buffer.alloc(20),Buffer.alloc(256)])assert.throws(()=>firmwareVersion(bad),/invalid_firmware/);
 image[48]=0xb0;assert.throws(()=>firmwareVersion(image),/invalid_firmware/);
 image.fill(0,48,80);image.write('not-a-release',48);assert.throws(()=>firmwareVersion(image),/invalid_firmware/);
});
