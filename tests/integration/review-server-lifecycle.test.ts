import {request as httpRequest} from 'node:http';
import {readFile,writeFile,readdir} from 'node:fs/promises';
import path from 'node:path';
import {expect,it} from 'vitest';
import {createApp} from '../../src/app.js';
import {loadConfig} from '../../src/config.js';
import {TransformQueue} from '../../src/queue/transform-queue.js';
import {listen,close} from '../helpers/http-app.js';
import {makeTestRoot,removeTestRoot} from '../helpers/test-root.js';

async function setup() {
  const root=await makeTestRoot(), queue=new TransformQueue({maxActive:1,maxAccepted:3});
  let calls=0;
  const app=createApp({config:{...loadConfig({},process.cwd()),runtimeRoot:root,minFreeBytes:1},queue,
    preflight:{ready:true,nodeVersion:process.version},logger:{info(){},error(){}},
    engine:{async transform(req){calls++;const file=req.workspace.path('final.txt');
      await writeFile(file,await readFile(req.workspace.path('01_input.txt')));
      return {finalPath:file,sourceChars:6,outputChars:6,chunks:1,warnings:[],diagnostics:{} as any};}}});
  const server=await listen(app);
  return {...server,root,queue,calls:()=>calls,async cleanup(){await queue.shutdown();await close(server.server);await removeTestRoot(root);}};
}

it('uses the same Origin contract for text as for document requests',async()=>{
  const t=await setup();
  try {
    const denied=await fetch(t.baseUrl+'/api/transform',{method:'POST',headers:{'content-type':'text/plain',origin:'https://other.example'},body:'source'});
    await denied.text();expect(denied.status).toBe(403);expect(t.calls()).toBe(0);
    for(const origin of [undefined,t.baseUrl]) {
      const accepted=await fetch(t.baseUrl+'/api/transform',{method:'POST',headers:{'content-type':'text/plain',...(origin?{origin}:{})},body:'source'});
      expect((await accepted.text())).toContain('"type":"done"');
    }
    expect(t.calls()).toBe(2);
  } finally {await t.cleanup();}
});

it('queue shutdown closes an unfinished text upload and removes its workspace',async()=>{
  const t=await setup();let accepted!:()=>void,closed!:()=>void;
  const acceptedEvent=new Promise<void>(r=>accepted=r),closedEvent=new Promise<void>(r=>closed=r);
  const client=httpRequest(t.baseUrl+'/api/transform',{method:'POST',headers:{'content-type':'text/plain'}},res=>{
    res.on('data',chunk=>{if(chunk.toString().includes('accepted'))accepted();});res.on('error',()=>{});res.on('close',closed);
  });client.on('error',()=>{});client.on('close',closed);client.flushHeaders();client.write('partial');
  try {
    await acceptedEvent;await t.queue.shutdown();
    expect(await Promise.race([closedEvent.then(()=>true),new Promise(r=>setTimeout(()=>r(false),1000))])).toBe(true);
    await expect.poll(async()=>(await readdir(t.root)).length).toBe(0);expect(t.calls()).toBe(0);
  } finally {client.destroy();await t.cleanup();}
});
