import path from 'node:path';
import {expect,it} from 'vitest';
import {createApp} from '../../src/app.js';
import {loadConfig} from '../../src/config.js';
import {TransformQueue} from '../../src/queue/transform-queue.js';
import {listen,close} from '../helpers/http-app.js';
import {makeTestRoot,removeTestRoot} from '../helpers/test-root.js';
import {EngineError} from '../../src/engine/errors.js';
import {writeFile} from 'node:fs/promises';

async function setup(prepare?:any,overrides:{transform?:any;preflight?:any}={}) {
  const root=await makeTestRoot(),queue=new TransformQueue({maxActive:1,maxAccepted:3});let calls=0;
  const state={job:'job-'+'a'.repeat(32),kind:'document',format:'docx',name:'source.docx',preview:'preview',sourceChars:7,editableBlocks:1,preservedBlocks:0,totalChunks:1,warnings:[]};
  const documentEngine={root:path.join(root,'documents'),prepare:prepare??(async()=>({...state})),
    async cleanup(){},async transform(...args:any[]){calls++;if(overrides.transform)return overrides.transform(...args);args[3].throwIfAborted();throw new Error('unexpected execution');}} as any;
  const app=createApp({config:{...loadConfig({},process.cwd()),runtimeRoot:root,minFreeBytes:1},queue,documentEngine,
    preflight:overrides.preflight??{ready:true,nodeVersion:process.version},engine:{async transform(){throw new Error('unused');}}});
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

async function upload(t:any) {
  const uploaded=await fetch(t.baseUrl+'/api/documents',{method:'POST',headers:{'x-file-name':'source.docx'},body:'file'});
  return await uploaded.json() as any;
}
const events=async(response:Response)=>(await response.text()).trim().split('\n').map(line=>JSON.parse(line));

it('reports document engine failures with the public code and message, not internal text',async()=>{
  for(const [thrown,expected] of [
    [new EngineError('ENGINE_TIMEOUT',true,'Codex timed out'),{code:'ENGINE_TIMEOUT',message:'한 구간의 처리 시간이 초과되었습니다.'}],
    [new EngineError('MODEL_UNAVAILABLE',false,'Claude rejected the selected model (api_error_status 404)'),{code:'MODEL_UNAVAILABLE',message:expect.stringContaining('선택한 모델을 사용할 수 없습니다')}],
    [new Error('보호된 서식이 바뀌어 저장하지 않았습니다.'),{code:'VALIDATION_FAILED',message:'보호된 서식이 바뀌어 저장하지 않았습니다.'}]
  ] as const) {
    const t=await setup(undefined,{transform:async()=>{throw thrown;}});
    try {
      const doc=await upload(t);
      const run=await fetch(`${t.baseUrl}/api/documents/${doc.id}/transform?engine=codex`,{method:'POST',headers:{authorization:`Bearer ${doc.token}`}});
      const last=(await events(run)).at(-1);
      // The record is removed after a failure, so the same document cannot be retried.
      expect(last).toEqual({type:'error',...expected,retryable:false});
      expect(JSON.stringify(last)).not.toMatch(/timed out|rejected the selected/);
      expect(t.store.records.size).toBe(0);
    } finally {await t.cleanup();}
  }
});

it('refuses document work while the engine preflight is not ready',async()=>{
  const t=await setup(undefined,{preflight:{ready:false,nodeVersion:process.version,errorCode:'ENGINE_UNAVAILABLE',message:'Python 3.11 이상이 필요합니다.'}});
  try {
    const doc=await upload(t);
    const run=await fetch(`${t.baseUrl}/api/documents/${doc.id}/transform?engine=codex`,{method:'POST',headers:{authorization:`Bearer ${doc.token}`}});
    expect(run.status).toBe(503);expect(await run.json()).toMatchObject({code:'ENGINE_UNAVAILABLE'});expect(t.calls()).toBe(0);
  } finally {await t.cleanup();}
});

it('gives every pre-stream rejection a code and keeps the uploaded document',async()=>{
  const t=await setup(undefined,{preflight:{ready:true,nodeVersion:process.version,providers:{
    codex:{ready:true,installed:true,authenticated:true,message:'ok'},
    claude:{ready:false,installed:true,authenticated:false,message:'Claude Code 로그인이 필요합니다.'}}}});
  try {
    const doc=await upload(t);const headers={authorization:`Bearer ${doc.token}`};
    const attempt=async(query:string,auth=headers)=>{const r=await fetch(`${t.baseUrl}/api/documents/${doc.id}/transform?${query}`,{method:'POST',headers:auth});return {status:r.status,body:await r.json() as any};};
    expect(await attempt('engine=codex&model=gpt-5.5&effort=low')).toMatchObject({status:400,body:{code:'INVALID_MODEL_SETTINGS'}});
    expect(await attempt('engine=other')).toMatchObject({status:400,body:{code:'INVALID_ENGINE'}});
    expect(await attempt('engine=claude')).toMatchObject({status:503,body:{code:'ENGINE_UNAVAILABLE'}});
    expect(await attempt('engine=codex',{authorization:`Bearer ${'0'.repeat(64)}`})).toMatchObject({status:404,body:{code:'DOCUMENT_NOT_FOUND'}});
    t.queue.reserve('one');t.queue.reserve('two');t.queue.reserve('three');
    expect(await attempt('engine=codex')).toMatchObject({status:429,body:{code:'QUEUE_FULL'}});
    await t.queue.shutdown();
    expect(await attempt('engine=codex')).toMatchObject({status:503,body:{code:'SERVER_SHUTDOWN'}});
    // None of these started a job, so the client may retry with the same document.
    expect(t.store.records.has(doc.id)).toBe(true);expect(t.calls()).toBe(0);
  } finally {await t.cleanup();}
});

it('a DELETE during a busy transform is not undone when the transform completes',async()=>{
  let entered!:()=>void,finish!:()=>void;const inside=new Promise<void>(r=>entered=r),done=new Promise<void>(r=>finish=r);
  const t=await setup(undefined,{transform:async(state:any,_engine:any,dir:string)=>{
    entered();await done;const output=path.join(dir,'out.docx');await writeFile(output,'PK');
    return {state:{...state,status:'done'},output,bytes:2,sha256:'0'.repeat(64),elapsedMs:1};
  }});
  try {
    const doc=await upload(t);const headers={authorization:`Bearer ${doc.token}`};
    const run=fetch(`${t.baseUrl}/api/documents/${doc.id}/transform?engine=codex`,{method:'POST',headers});
    await inside;
    expect((await fetch(`${t.baseUrl}/api/documents/${doc.id}`,{method:'DELETE',headers})).status).toBe(200);
    finish();
    const last=(await events(await run)).at(-1);
    expect(last.type).toBe('error');
    expect((await fetch(`${t.baseUrl}/api/documents/${doc.id}/result`,{headers})).status).toBe(404);
    await expect.poll(()=>t.store.records.size).toBe(0);
  } finally {finish();await t.cleanup();}
});
