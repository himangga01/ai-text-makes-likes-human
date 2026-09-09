// Explicit live benchmark: uses the selected, already authenticated local CLI.
// Reports contain timings/hashes only; private inputs and model output stay local.
import { mkdir, readFile, writeFile, copyFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
const root=process.cwd();
const label=process.argv[2] ?? 'candidate';
const base=path.resolve(process.env.BENCH_DIST ?? 'dist');
const mod=async name=>import(pathToFileURL(path.join(base,name+'.js')).href);
const {loadConfig}=await mod('config');
const {SpawnCommandRunner}=await mod('process/command-runner');
const {resolveCli}=await mod('runtime/cli-path');
const {CodexRunner}=await mod('engine/codex-runner');
const {ClaudeRunner}=await mod('engine/claude-runner');
const {CodexSemaphore}=await mod('engine/codex-semaphore');
const {PythonEngine}=await mod('engine/python-engine');
const {HumanizeEngine}=await mod('engine/humanize-engine');
const {JobWorkspace}=await mod('engine/workspace');
const work=path.resolve('runtime/test-tmp/speed-loop',label);await mkdir(work,{recursive:true});
const config=loadConfig(process.env,root);
const provider=process.env.BENCH_PROVIDER ?? 'codex';
const settings={model:process.env.BENCH_MODEL ?? (provider==='codex'?'gpt-6-astra':'claude-sonnet-5'),effort:'low'};
const native=new SpawnCommandRunner();
let calls=[];
const runner={async run(request){const started=performance.now();const result=await native.run(request);
  if(request.stdin)calls.push({elapsedMs:performance.now()-started,promptChars:Array.from(request.stdin).length,stdoutChars:result.stdout.length,exitCode:result.exitCode});return result;}};
const options={schemaPath:path.resolve(process.env.BENCH_SCHEMA ?? 'src/engine/output-schema.json'),quickRulesPath:path.join(config.vendorRoot,'skills/humanize-korean/references/quick-rules.md'),timeoutMs:600000,runner,permitPool:new CodexSemaphore(1)};
const model=provider==='codex'?new CodexRunner({...options,codexCommand:resolveCli(provider)}):new ClaudeRunner({...options,claudeCommand:resolveCli(provider)});
const python=new PythonEngine({pythonCommand:path.resolve('build-resources/python/python.exe'),vendorRoot:config.vendorRoot,runner});
const engine=new HumanizeEngine({python,codex:model,chunkConcurrency:1});
const paragraphs=[
  '이번 작업에서는 자료를 정리하고 검토 의견을 모았습니다. 담당자는 초안을 읽고 근거가 부족한 부분을 표시했습니다. 이러한 과정을 통해 검토의 효율성을 제고할 수 있습니다.',
  '회의에서는 안내 문구가 너무 길다는 의견이 나왔습니다. 핵심 내용을 먼저 설명하고 세부 안내는 뒤에 배치하기로 했습니다. 이는 독자의 이해를 돕는 데 있어 중요한 역할을 수행합니다.',
  '현장에서는 안내문을 읽지 않고 지나가는 사람이 많았습니다. 글자의 크기를 키우고 문장을 짧게 나누었습니다. 다만 수정한 안내문이 실제로 도움이 되었는지는 아직 확인하지 못했습니다.',
  '검토자는 표현을 바꾼 이유를 기록했습니다. 의미가 달라질 수 있는 문장은 그대로 두었습니다. 문서의 가독성을 향상시키기 위한 노력이 필요합니다.',
  '자료에는 확인된 사실과 검토자의 의견이 함께 담겨 있었습니다. 두 내용을 구분한 뒤 다시 읽었습니다. 이 작업은 향후 의사 결정에 있어 유용한 기반을 제공할 것입니다.',
  '작성자는 다음 검토 전에 누락된 자료를 확인하기로 했습니다. 일정은 아직 정해지지 않았습니다. 추가 자료가 도착하면 담당자가 초안을 다시 검토할 수 있습니다.'
];
const source=process.env.BENCH_TEXT_FILE ? await readFile(path.resolve(process.env.BENCH_TEXT_FILE),'utf8') : paragraphs.join('\n\n');
const records=[];
if (process.env.BENCH_DOCUMENT) {
  const {DocumentEngine}=await mod('documents/document-engine');
  const documents=new DocumentEngine({...config,runtimeRoot:work},runner);
  const input=path.resolve(process.env.BENCH_DOCUMENT);
  const start=performance.now();const state=await documents.prepare(input);
  const preparedMs=performance.now()-start;
  try {
    console.log(`START ${label} ${provider} ${state.format}: ${state.totalChunks} batches`);
    const result=await documents.transform(state,provider,work,new AbortController().signal,event=>{
      if(event.type==='progress')console.log(event.message);
    },settings);
    await copyFile(result.output,path.join(work,`result.${state.format}`));
    const finalState=JSON.parse(await readFile(path.join(documents.root,state.job,'job.json'),'utf8'));
    records.push({label,provider,settings,inputHash:state.sourceHash,format:state.format,sourceChars:state.sourceChars,
      batches:state.totalChunks,preparedMs,elapsedMs:performance.now()-start,calls,restoredBlocks:finalState.restored,
      changedBlocks:Object.values(finalState.accepted).filter(edits=>edits.length).length,
      warnings:result.state.warnings,outputHash:result.sha256});
    // Private detailed evidence remains under ignored runtime, never in public reports.
    await writeFile(path.join(work,'accepted.json'),JSON.stringify(finalState));
    console.log(JSON.stringify(records.at(-1)));
  } finally {await documents.cleanup(state.job);await writeFile(path.join(work,'report.json'),JSON.stringify(records,null,2));}
  process.exit(0);
}
for(let i=0;i<Number(process.env.BENCH_RUNS ?? 3);i++){
  calls=[];const workspace=await JobWorkspace.create(work,`speed-${i}-${Date.now()}`);
  await writeFile(workspace.path('01_input.txt'),source);
  console.log(`START ${label} ${provider} text ${i+1}`);
  try {const start=performance.now();const result=await engine.transform({workspace,jobId:workspace.jobId,settings,signal:new AbortController().signal,onEvent:()=>{}});
    const output=await readFile(result.finalPath,'utf8');await writeFile(path.join(work,`output-${i}.txt`),output);
    records.push({label,provider,settings,inputChars:Array.from(source).length,inputHash:createHash('sha256').update(source).digest('hex'),elapsedMs:performance.now()-start,calls,diagnostics:result.diagnostics,changed:output!==source,warnings:result.warnings});
    console.log(JSON.stringify(records.at(-1)));
  } finally {await workspace.cleanup();await writeFile(path.join(work,'report.json'),JSON.stringify(records,null,2));}
}
