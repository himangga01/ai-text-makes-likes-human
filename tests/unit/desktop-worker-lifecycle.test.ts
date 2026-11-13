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
    '../src/engine/model-policy.js':{parseEngineChoice:()=> 'codex',getModelOptions:()=>({}),getModelDefaults:()=>({})},
    '../src/runtime/model-catalog.js':{parseRequestModelSettings:async(_catalog:unknown,_engine:string,model='gpt-6.1-sol',effort='high')=>({model,effort})},
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
const engineError={'../src/engine/errors.js':{EngineError:class extends Error{constructor(readonly publicCode:string,readonly retryable:boolean,message:string){super(message);}}}};
it('validates a model selection against the worker list, which the main process never sees',async()=>{
  const rejecting={'../src/runtime/model-catalog.js':{parseRequestModelSettings:async()=>{throw new Error('선택한 CLI에서 지원하는 모델과 추론 레벨을 선택해 주세요.');}}};
  const p=await probe({...engineError,...rejecting});p.resume();p.send('transform');await tick();
  expect(p.executions).toEqual([]);
  expect(p.messages.find(m=>m.event?.type==='error')?.event).toMatchObject({code:'MODEL_UNAVAILABLE',retryable:true});
  const removed:unknown[]=[];const record={state:{},controller:new AbortController(),busy:false};let ran=false;
  const doc=await probe({...engineError,...rejecting,
    '../src/documents/artifact-store.js':{ArtifactStore:class{get(){return record;}async remove(r:unknown){removed.push(r);}}},
    '../src/runtime/create-runtime.js':{createProductionRuntime:async()=>({preflight:{ready:true,providers:{codex:{ready:true}}},documentEngine:{async transform(){ran=true;}}})}});
  doc.resume();doc.send('document-transform','job',{input:{id:'doc',token:'t',engine:'codex',commands:{}}});await tick();
  expect(doc.messages.find(m=>m.event?.type==='error')?.event).toMatchObject({code:'MODEL_UNAVAILABLE',retryable:true});
  expect(doc.messages.some(m=>m.event?.type==='accepted')).toBe(false);expect(ran).toBe(false);expect(removed).toEqual([]);
});
it('passes the validated selection to the engine and serves the live list from health',async()=>{
  const seen:unknown[]=[];let settled=false;
  const live={codex:[{id:'gpt-7-nova',label:'GPT-7 Nova',efforts:['high']}],claude:[]};
  const p=await probe({
    '../src/engine/model-policy.js':{parseEngineChoice:()=> 'codex',getModelOptions:()=>live,getModelDefaults:()=>({codex:{model:'gpt-7-nova',effort:'high'}})},
    '../src/runtime/model-catalog.js':{parseRequestModelSettings:async(catalog:any,_engine:string,model:string,effort:string)=>{seen.push(catalog);return {model,effort};}},
    '../src/runtime/create-runtime.js':{createProductionRuntime:async()=>({preflight:{ready:true,providers:{codex:{ready:true}}},
      modelCatalog:{async whenInitialized(){settled=true;},status:()=>({codex:{source:'live'}})},documentEngine:{health:async()=>true},
      engine:{async transform(req:any){seen.push(req.settings);return {finalPath:'result',sourceChars:1,outputChars:1,chunks:1};}}})}
  });
  p.resume();p.send('transform','job',{input:{text:'source',engine:'codex',commands:{},settings:{model:'gpt-7-nova',effort:'high'}}});await tick();
  expect(seen[1]).toEqual({model:'gpt-7-nova',effort:'high'});expect(seen[0]).toMatchObject({status:expect.any(Function)});
  p.send('health','health');await tick();
  const health=p.messages.find(m=>m.id==='health')?.value;
  expect(settled).toBe(true);
  expect(health).toMatchObject({modelOptions:live,modelDefaults:{codex:{model:'gpt-7-nova',effort:'high'}},modelCatalog:{codex:{source:'live'}}});
});
