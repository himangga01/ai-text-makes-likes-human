import { readFileSync, writeFileSync } from 'node:fs';
import { createApp } from '../../src/app.js';
import { loadConfig } from '../../src/config.js';
import { TransformQueue } from '../../src/queue/transform-queue.js';
import { listen, close } from '../helpers/http-app.js';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { expect, it } from 'vitest';
import { HumanizeEngine } from '../../src/engine/humanize-engine.js';
import { PythonEngine } from '../../src/engine/python-engine.js';
import { CodexRunner } from '../../src/engine/codex-runner.js';
import { ClaudeRunner } from '../../src/engine/claude-runner.js';
import { JobWorkspace } from '../../src/engine/workspace.js';
import { SpawnCommandRunner, type CommandRequest } from '../../src/process/command-runner.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';

async function run(source: string, rewrite: (source:string,attempt:number)=>string, kind:'codex'|'claude'='codex', options:any={inputKind:'direct-text',strength:'very-strong'}, viaWeb=false, beforeAssembly?: (workspace:JobWorkspace)=>void) {
  const outer=await makeTestRoot();const workspace=await JobWorkspace.create(outer,'strength');const calls:CommandRequest[]=[];
  try {
    await writeFile(workspace.path('01_input.txt'),source,'utf8');
    const runner={async run(request:CommandRequest) {
      calls.push(request);
      const source=request.stdin!.match(/BEGIN_SOURCE_([a-f0-9]+)\n([\s\S]*)\nEND_SOURCE_\1/)![2]!;
      const payload={rewrittenText:rewrite(source,calls.length),edits:[],warnings:[]};
      if(kind==='codex')await writeFile(request.args[request.args.indexOf('--output-last-message')+1]!,JSON.stringify(payload));
      return {exitCode:0,termination:'exit' as const,stdout:JSON.stringify({is_error:false,subtype:'success',structured_output:payload}),stderr:''};
    }};
    const settings={schemaPath:path.resolve('src/engine/output-schema.json'),quickRulesPath:path.resolve('vendor/humanize-engine/skills/humanize-korean/references/quick-rules.md'),timeoutMs:1000,runner,permitPool:{maxObserved:1,run:async<T>(_signal:AbortSignal,task:()=>Promise<T>)=>task()}};
    const codex=kind==='codex'?new CodexRunner({...settings,codexCommand:'codex'}):new ClaudeRunner({...settings,claudeCommand:'claude'});
    const engine=new HumanizeEngine({python:new PythonEngine({pythonCommand:path.resolve('build-resources/python/python.exe'),vendorRoot:path.resolve('vendor/humanize-engine'),runner:new SpawnCommandRunner()}),codex,chunkConcurrency:1});
    let result;
    if (viaWeb) {
      const service={async transform(request:any){result=await engine.transform(request);return result;}};
      const app=createApp({config:{...loadConfig({},process.cwd()),runtimeRoot:outer},queue:new TransformQueue({maxActive:1,maxAccepted:3}),engine:service,claudeEngine:service,preflight:{ready:true,nodeVersion:process.version},logger:{info(){},error(){}}});
      const server=await listen(app);
      try {
        const query=new URLSearchParams({engine:kind,inputKind:options.inputKind,...(options.strength?{strength:options.strength}:{})});
        const response=await fetch(`${server.baseUrl}/api/transform?${query}`,{method:'POST',headers:{'content-type':'text/plain'},body:source});
        const events=(await response.text()).trim().split('\n').map(line=>JSON.parse(line));
        expect(events.at(-1)?.type).toBe('done');
        return {output:events.filter(event=>event.type==='result-delta').map(event=>event.text).join(''),result:result!,calls};
      } finally {await close(server.server);}
    }
    result=await engine.transform({jobId:workspace.jobId,workspace,signal:new AbortController().signal,onEvent:(event:any)=>{if(event.phase==='assemble')beforeAssembly?.(workspace);},rewriteOptions:options} as any);
    return {output:await readFile(result.finalPath,'utf8'),result,calls};
  } finally {await workspace.cleanup();await removeTestRoot(outer);}
}

for(const kind of ['codex','claude'] as const)it(`${kind} carries strength into both native prompts and rolls back persistent relation swaps`,async()=>{
  const source='민수는 사과를 샀고 지수는 배를 샀다. 오늘 장터는 조용하다.\n';
  const {output,result,calls}=await run(source,s=>s.replace('민수는 사과를 샀고 지수는 배를 샀다','지수는 사과를 샀고 민수는 배를 샀다'),kind);
  expect(output).toBe(source);
  expect(calls).toHaveLength(2);
  expect(calls[0]!.stdin).toContain('많은 문장');
  expect(calls[1]!.stdin).toContain('요청 강도: very-strong');
  expect(calls[1]!.stdin).toContain('보수적 재시도');
  expect(result.diagnostics).toMatchObject({requestedStrength:'very-strong',conservativeRetries:1,fidelityGuardFailures:2,rolledBackChunks:1});
  expect(result.warnings).toContainEqual(expect.objectContaining({code:'DIRECT_TEXT_FIDELITY_RESTRICTED'}));
},30000);

it.each([
  ['team values','가팀은 12건을 처리했고 나팀은 20건을 처리했다.','가팀은 20건을 처리했고 나팀은 12건을 처리했다.'],
  ['possibility and split','결과를 왜곡할 수 있다.','결과를 왜곡한다. 조심한다.'],
  ['obligation','내용을 확인해야 한다.','내용을 확인했다.'],
  ['condition','회의가 끝나면 자료를 보낸다.','자료를 보내고 회의를 끝낸다.'],
  ['core concept','자료의 정확성이 중요하다.','자료의 안전성이 중요하다.']
])('blocks %s changes with real restoration and gates',async(_label,before,after)=>{
  const source=before+' 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.\n';
  const {output}=await run(source,s=>s.replace(before,after));
  expect(output).toBe(source);
},30000);
it('accepts real broad syntax restructuring of eligible sentences without changing default model',async()=>{
  const source='이번 검토에서 중요한 것은 자료의 정확성이다. 담당자는 자료의 정리 작업을 수행한다. 이 방안은 강한 경쟁력을 가지고 있다.\n';
  const rewritten='자료의 정확성이 이번 검토에서 중요하다. 담당자는 자료를 정리한다. 이 방안은 경쟁력이 강하다.\n';
  const {output,calls}=await run(source,()=>rewritten);
  expect(output).toBe(rewritten);
  expect(calls[0]!.args).toContain('gpt-5.6-sol');
},30000);
it('normal eligible unchanged text is accepted without artificial edits or retry',async()=>{
  const source='오늘 하늘은 맑다. 바람은 조용하다.\n';
  const {output,result,calls}=await run(source,s=>s,'codex',{inputKind:'direct-text',strength:'normal'});
  expect(output).toBe(source);expect(calls).toHaveLength(1);
  expect(result.diagnostics).toMatchObject({requestedStrength:'normal',conservativeRetries:0});
},30000);
it('legacy and text-file requests retain their existing relation-check behavior',async()=>{
  const source='민수는 사과를 샀고 지수는 배를 샀다. 오늘 장터는 조용하다.\n';
  for(const options of [undefined,{inputKind:'text-file',strength:'normal'}]){
    // Pass null sentinel to avoid the fixture default.
    const {output,calls}=await run(source,s=>s.replace('민수는 사과를 샀고 지수는 배를 샀다','지수는 사과를 샀고 민수는 배를 샀다'),'codex',options??null);
    expect(output).toContain('지수는 사과를 샀고 민수는 배를 샀다');expect(calls).toHaveLength(1);
    expect(calls[0]!.stdin).not.toContain('<rewrite_policy>');
  }
},30000);

it.each(['codex','claude'] as const)('web query reaches real %s runner prompt and does not bleed into model settings',async kind=>{
 const source='오늘 하늘은 맑다. 바람은 조용하다.\n';
 const {calls,result}=await run(source,s=>s,kind,{inputKind:'direct-text',strength:'medium'},true);
 expect(calls[0]!.stdin).toContain('요청 강도: medium');
 expect(result.diagnostics.requestedStrength).toBe('medium');
},30000);
it('web direct-text without strength defaults to normal',async()=>{
 const {calls}=await run('오늘 하늘은 맑다.\n',s=>s,'codex',{inputKind:'direct-text'},true);
 expect(calls[0]!.stdin).toContain('요청 강도: normal');
},30000);

it('explains restricted broad scope even when the CLI already preserves protected sentences',async()=>{
 const {result,calls}=await run('민수는 사과를 샀고 지수는 배를 샀다.\n',s=>s);
 expect(calls).toHaveLength(1);
 expect(result.warnings).toContainEqual(expect.objectContaining({code:'DIRECT_TEXT_PROTECTED_SENTENCES'}));
},30000);
it('retries a real skipped hedge restoration and rolls back a persistent second failure',async()=>{
 const source='이 정책이 결과를 왜곡할 수 있다는 지적도 나온다. 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.\n';
 const {result,output,calls}=await run(source,s=>s.replace('이 정책이 결과를 왜곡할 수 있다는 지적도 나온다.','이 정책은 결과를 왜곡한다. 그런 지적도 나온다.'));
 expect(output).toBe(source);expect(calls).toHaveLength(2);
 expect(result.diagnostics).toMatchObject({skippedSentences:2,rolledBackChunks:1,conservativeRetries:1});
},30000);
it('accepts a safe conservative retry after a rejected factual relation edit',async()=>{
 const source='민수는 사과를 샀고 지수는 배를 샀다. 이 방안은 강한 경쟁력을 가지고 있다.\n';
 const {result,output,calls}=await run(source,(s,attempt)=>attempt===1?s.replace('민수는 사과를 샀고 지수는 배를 샀다','지수는 사과를 샀고 민수는 배를 샀다'):s.replace('가지고 있다','갖고 있다'));
 expect(output).toBe('민수는 사과를 샀고 지수는 배를 샀다. 이 방안은 강한 경쟁력을 갖고 있다.\n');
 expect(calls).toHaveLength(2);expect(result.diagnostics).toMatchObject({fidelityGuardFailures:1,rolledBackChunks:0});
},30000);

it('full-source guard restores a post-verification assembly omission before emitting a result',async()=>{
 const source='원문 보존 검토를 진행한다. 자료를 정리한다. 문서를 확인한다. 결과를 전달한다.\n';
 const {result,output}=await run(source,s=>s,'codex',{inputKind:'direct-text',strength:'strong'},false,workspace=>{
  const manifest=JSON.parse(readFileSync(workspace.path('chunk_manifest.json'),'utf8'));
  const chunk=manifest.chunks.find((entry:any)=>!entry.passthrough);
  const file=workspace.path(chunk.rewritten_file);
  writeFileSync(file,readFileSync(file,'utf8').replace('자료를 정리한다. ',''),'utf8');
 });
 expect(output).toBe(source);
 expect(result.diagnostics.fullSourceRollbacks).toBe(1);
 expect(result.warnings).toContainEqual(expect.objectContaining({code:'DIRECT_TEXT_DOCUMENT_ROLLED_BACK'}));
},30000);
