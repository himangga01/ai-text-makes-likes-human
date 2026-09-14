import path from 'node:path';
import {expect,it} from 'vitest';
import {createApp} from '../../src/app.js';
import {loadConfig} from '../../src/config.js';
import {TransformQueue} from '../../src/queue/transform-queue.js';
import {listen,close} from '../helpers/http-app.js';
import {makeTestRoot,removeTestRoot} from '../helpers/test-root.js';

async function setup(prepare?:any) {
  const root=await makeTestRoot(),queue=new TransformQueue({maxActive:1,maxAccepted:3});let calls=0;
  const state={job:'job-'+'a'.repeat(32),kind:'document',format:'docx',name:'source.docx',preview:'preview',sourceChars:7,editableBlocks:1,preservedBlocks:0,totalChunks:1,warnings:[]};
  const documentEngine={root:path.join(root,'documents'),prepare:prepare??(async()=>({...state})),
    async cleanup(){},async transform(_s:any,_e:any,_o:any,signal:AbortSignal){calls++;signal.throwIfAborted();throw new Error('unexpected execution');}} as any;
  const app=createApp({config:{...loadConfig({},process.cwd()),runtimeRoot:root,minFreeBytes:1},queue,documentEngine,
    preflight:{ready:true,nodeVersion:process.version},engine:{async transform(){throw new Error('unused');}}});
  const server=await listen(app);
  return {...server,store:app.locals.documentStore,queue,calls:()=>calls,async cleanup(){await app.locals.documentStore.close();await queue.shutdown();await close(server.server);await removeTestRoot(root);}};
}

it('cancelled queued document requests immediately return their queue slot',async()=>{
  const t=await setup();let release!:()=>void;const blocked=new Promise<void>(r=>release=r);
  const busy=t.queue.reserve('blocker')!.submit(()=>blocked,()=>{});
  const controller=new AbortController();
  try {
    const uploaded=await fetch(t.baseUrl+'/api/documents',{method:'POST',headers:{'x-file-name':'source.docx'},body:'file'});
    const doc:any=await uploaded.json(),record=t.store.records.get(doc.id);
    const aborted=new Promise<void>(r=>record.controller.signal.addEventListener('abort',()=>r(),{once:true}));
    await fetch(`${t.baseUrl}/api/documents/${doc.id}/transform?engine=codex`,{method:'POST',headers:{authorization:`Bearer ${doc.token}`},signal:controller.signal});
    expect(t.queue.stats().queued).toBe(1);controller.abort();await aborted;await new Promise(r=>setImmediate(r));
    expect(t.queue.stats().queued).toBe(0);expect(t.calls()).toBe(0);
  } finally {controller.abort();release();await busy;await t.cleanup();}
});

it('disconnect after upload aborts parsing and removes an undisclosed document',async()=>{
  let started!:()=>void,aborted!:()=>void;const start=new Promise<void>(r=>started=r),abort=new Promise<void>(r=>aborted=r);
  const t=await setup(async(_file:string,signal:AbortSignal)=>{started();return new Promise((_resolve,reject)=>{
    signal.addEventListener('abort',()=>{aborted();reject(new Error('cancelled'));},{once:true});
  });});
  const controller=new AbortController();
  const upload=fetch(t.baseUrl+'/api/documents',{method:'POST',headers:{'x-file-name':'source.docx'},body:'file',signal:controller.signal}).catch(()=>undefined);
  try {
    await start;controller.abort();
    expect(await Promise.race([abort.then(()=>true),new Promise(r=>setTimeout(()=>r(false),250))])).toBe(true);
    await expect.poll(()=>t.store.records.size).toBe(0);
  } finally {controller.abort();for(const record of t.store.records.values())record.controller.abort();await upload;await t.cleanup();}
});
