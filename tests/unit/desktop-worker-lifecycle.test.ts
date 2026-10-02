import {readFile} from 'node:fs/promises';
import {transform as compile} from 'esbuild';
import {runInNewContext} from 'node:vm';
import path from 'node:path';
import {expect,it} from 'vitest';

async function probe(overrides:Record<string,any>={}) {
  const compiled=await compile(await readFile('desktop/worker.ts','utf8'),{loader:'ts',format:'cjs',platform:'node'});
  let receive!:(message:any)=>void, resume!:()=>void;
  const gate=new Promise<void>(resolve=>resume=resolve);const messages:any[]=[],executions:boolean[]=[];
  const modules:Record<string,any>={
    '../src/engine/rewrite-policy.js':{REWRITE_OPTIONS:[],parseRewriteOptions:()=>undefined},
    'node:fs/promises':{mkdir:()=>gate,readFile:async()=> 'result',writeFile:async()=>{}},
    '../src/config.js':{loadConfig:()=>({})},
    '../src/runtime/create-runtime.js':{createProductionRuntime:async()=>({preflight:{ready:true,providers:{codex:{ready:true}}},engine:{async transform(req:any){executions.push(req.signal.aborted);return {finalPath:'result',sourceChars:1,outputChars:1,chunks:1};}}})},
    '../src/process/command-runner.js':{SpawnCommandRunner:class{}},
    '../src/engine/workspace.js':{JobWorkspace:{create:async()=>({path:()=> 'input',cleanup:async()=>{}})}},
    '../src/engine/errors.js':{EngineError:class extends Error{}},
    '../src/transport/public-error.js':{PUBLIC_MESSAGES:{}},
    '../src/engine/model-policy.js':{parseEngineChoice:()=> 'codex',MODEL_OPTIONS:[]},
    '../src/engine/input-limits.js':{INPUT_LIMITS:{},MAX_INPUT_CHARS:100000,inputChars:(text:string)=>Array.from(text).length},
    'node:path':path,'../src/documents/artifact-store.js':{ArtifactStore:class{}},
    ...overrides,
  };
  runInNewContext(compiled.code,{require:(name:string)=>{if(!(name in modules))throw new Error('Unexpected import '+name);return modules[name];},
    process:{env:{HUMANIZE_RESOURCE_ROOT:'root',HUMANIZE_JOBS_ROOT:'jobs'},parentPort:{on(_name:string,fn:any){receive=fn;},postMessage(value:any){messages.push(value);}}},AbortController,AbortSignal,console});
  return {messages,executions,resume,send:(kind:string,id='job',extra:Record<string,unknown>={})=>receive({data:{kind,id,input:{text:'source',engine:'codex',commands:{}},...extra}})};
}
async function tick(){for(let n=0;n<5;n++)await new Promise(resolve=>setImmediate(resolve));}

it.each(['cancel','shutdown'])('honors %s before worker initialization completes',async interruption=>{
  const p=await probe();p.send('transform');p.send(interruption,interruption==='cancel'?'job':'shutdown');await tick();
  expect(p.messages.some(m=>m.id==='shutdown'&&m.kind==='response')).toBe(false);
  p.resume();await tick();expect(p.executions).toEqual([]);expect(p.messages.some(m=>m.event?.type==='done')).toBe(false);
});
it('reserves the worker slot before initialization and still completes a normal job',async()=>{
  const p=await probe();p.send('transform');p.send('transform','second');p.resume();await tick();
  expect(p.executions).toEqual([false]);expect(p.messages.some(m=>m.id==='second'&&m.error)).toBe(true);
  expect(p.messages.some(m=>m.id==='job'&&m.event?.type==='done')).toBe(true);
});
it('forwards Korean document errors and hides internal English ones',async()=>{
  const store=(error:Error)=>({'../src/documents/artifact-store.js':{ArtifactStore:class{async importFile(){throw error;}}}});
  const korean=await probe(store(new Error('매크로가 포함된 문서는 지원하지 않습니다.')));korean.resume();korean.send('document-import','import',{file:'a.docx'});await tick();
  expect(korean.messages.find(m=>m.id==='import')?.error).toBe('매크로가 포함된 문서는 지원하지 않습니다.');
  const english=await probe(store(new Error('ENOENT: /private/path/a.docx')));english.resume();english.send('document-import','import',{file:'a.docx'});await tick();
  expect(english.messages.find(m=>m.id==='import')?.error).toBe('엔진 작업을 처리하지 못했습니다.');
});
it('keeps a document the CLI preflight rejected before accepting the job',async()=>{
  const removed:unknown[]=[];const record={state:{},controller:new AbortController(),busy:false};
  const p=await probe({
    '../src/documents/artifact-store.js':{ArtifactStore:class{get(){return record;}async remove(r:unknown){removed.push(r);}}},
    '../src/runtime/create-runtime.js':{createProductionRuntime:async()=>({preflight:{ready:true,providers:{codex:{ready:false}}},documentEngine:{}})}
  });
  p.resume();p.send('document-transform','job',{input:{id:'doc',token:'t',engine:'codex',commands:{}}});await tick();
  const error=p.messages.find(m=>m.event?.type==='error')?.event;
  expect(error).toMatchObject({retryable:true});expect(p.messages.some(m=>m.event?.type==='accepted')).toBe(false);
  expect(removed).toEqual([]);expect(record.busy).toBe(false);
});
