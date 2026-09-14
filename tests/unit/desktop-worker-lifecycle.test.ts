import {readFile} from 'node:fs/promises';
import {transform as compile} from 'esbuild';
import {runInNewContext} from 'node:vm';
import path from 'node:path';
import {expect,it} from 'vitest';

async function probe() {
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
    '../src/engine/model-policy.js':{parseEngineChoice:()=> 'codex',MODEL_OPTIONS:[]},
    'node:path':path,'../src/documents/artifact-store.js':{ArtifactStore:class{}},
  };
  runInNewContext(compiled.code,{require:(name:string)=>{if(!(name in modules))throw new Error('Unexpected import '+name);return modules[name];},
    process:{env:{HUMANIZE_RESOURCE_ROOT:'root',HUMANIZE_JOBS_ROOT:'jobs'},parentPort:{on(_name:string,fn:any){receive=fn;},postMessage(value:any){messages.push(value);}}},AbortController,AbortSignal,console});
  return {messages,executions,resume,send:(kind:string,id='job')=>receive({data:{kind,id,input:{text:'source',engine:'codex',commands:{}}}})};
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
