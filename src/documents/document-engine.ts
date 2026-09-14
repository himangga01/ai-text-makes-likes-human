import { mkdir, readFile, writeFile, rm, stat, access } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import path from 'node:path';
import type { AppConfig } from '../config.js';
import type { CommandRunner } from '../process/command-runner.js';
import type { EventSink } from '../contracts.js';
import { CodexRunner } from '../engine/codex-runner.js';
import { ClaudeRunner } from '../engine/claude-runner.js';
import { CodexSemaphore } from '../engine/codex-semaphore.js';
import { buildDocumentPrompt } from '../engine/document-prompt.js';
import { resolveCli } from '../runtime/cli-path.js';
import { EngineError } from '../engine/errors.js';
import { parseModelSettings, type ModelSettings } from '../engine/model-policy.js';

export interface DocumentState {
  job: string; kind: 'document'; format: 'docx'|'pptx'; name: string; sourceHash: string;
  status: string; chunk: number; attempt: 1|2; inputPath: string; responsePath: string;
  preview: string; sourceChars: number; editableBlocks: number; preservedBlocks: number;
  totalChunks: number; slides: number; warnings: string[]; outputPath?: string;
}
export class DocumentEngine {
  readonly root: string;
  private pool = new CodexSemaphore(1);
  constructor(private config: AppConfig, private runner: CommandRunner) { this.root = path.join(config.runtimeRoot, 'documents'); }
  async python(): Promise<string> {
    // Bundled Windows runtime first; other platforms fall back to the configured interpreter.
    const executable = process.platform === 'win32' ? 'python.exe' : path.join('bin','python3');
    const candidates = [path.join(this.config.projectRoot,'python',executable),path.join(this.config.projectRoot,'build-resources','python',executable)];
    for (const file of candidates) { try { await access(file); return file; } catch {} }
    return this.config.pythonCommand;
  }
  async health() {
    try { const r = await this.runner.run({command:await this.python(), args:['-c','from lxml import etree'],cwd:this.config.projectRoot,timeoutMs:10000}); return r.exitCode===0; }
    catch { return false; }
  }
  async call(args: string[], signal?: AbortSignal): Promise<DocumentState> {
    const result=await this.runner.run({command:await this.python(), args:[path.join(this.config.projectRoot,'engine_runtime','skill_gateway.py'),
      '--workspace-root',this.root,'--vendor-root',this.config.vendorRoot,...args], cwd:this.config.projectRoot,
      timeoutMs:120000,signal,env:{...process.env,PYTHONUTF8:'1',PYTHONDONTWRITEBYTECODE:'1',NODE_COMMAND:process.execPath}});
    if (result.termination==='aborted') throw new EngineError('CLIENT_ABORTED',true,'Cancelled');
    if (result.exitCode!==0) {
      let message='문서를 처리하지 못했습니다. 파일 형식과 보호 설정을 확인해 주세요.';
      try { const error=JSON.parse(result.stdout); if(typeof error.message==='string') message=error.message; } catch {}
      throw new Error(message);
    }
    return JSON.parse(result.stdout) as DocumentState;
  }
  async prepare(file: string, signal?: AbortSignal) { await mkdir(this.root,{recursive:true}); return this.call(['prepare','--input',file],signal); }
  async cleanup(job: string) { if (/^job-[a-f0-9]{32}$/.test(job)) await this.call(['cleanup','--job',job]); }
  async transform(state: DocumentState, engine: 'claude'|'codex', outputDir: string, signal: AbortSignal, onEvent: EventSink, settings?: ModelSettings) {
    const selection = parseModelSettings(engine, settings?.model, settings?.effort);
    const options={schemaPath:path.join(this.config.projectRoot,'engine_runtime','documents','response-schema.json'),
      quickRulesPath:path.join(this.config.vendorRoot,'skills','humanize-korean','references','quick-rules.md'),
      timeoutMs:this.config.chunkTimeoutMs, runner:this.runner,permitPool:this.pool,promptBuilder:buildDocumentPrompt,
      resultParser:(raw: string)=>({rewrittenText:raw,warnings:[]})};
    const model=engine==='claude'?new ClaudeRunner({...options,claudeCommand:resolveCli('claude',this.config.claudeCommand)}):
      new CodexRunner({...options,codexCommand:resolveCli('codex',this.config.codexCommand)});
    const started=Date.now();
    const seen=new Set<string>();
    while(state.status==='rewrite') {
      onEvent({type:'progress',phase:'transform',current:state.chunk,total:state.totalChunks,message:`문서 ${state.chunk}/${state.totalChunks} 구간 · ${state.attempt}차 처리`});
      const result=await model.transform(state.inputPath,state.responsePath,state.attempt,signal,selection);
      await writeFile(state.responsePath,result.rewrittenText,'utf8');
      state=await this.call(['accept','--job',state.job,'--chunk',String(state.chunk),'--attempt',String(state.attempt),
        '--source-hash',state.sourceHash,'--response',state.responsePath],signal);
      for (const message of state.warnings) if(!seen.has(message)) { seen.add(message); onEvent({type:'warning',code:'DOCUMENT_REVIEW',message}); }
    }
    if(state.status!=='ready-to-finalize') throw new Error('문서 작업 상태가 잘못되었습니다.');
    await mkdir(outputDir,{recursive:true});
    const output=path.join(outputDir,randomUUID()+'.'+state.format);
    onEvent({type:'progress',phase:'assemble',current:state.totalChunks,total:state.totalChunks,message:'원본 서식을 유지해 문서를 저장하고 검증합니다.'});
    state=await this.call(['finalize','--job',state.job,'--output',output],signal);
    if(signal.aborted) { await rm(output,{force:true}); throw new EngineError('CLIENT_ABORTED',true,'Cancelled'); }
    const bytes=await readFile(output);
    return {state,output,bytes:(await stat(output)).size,sha256:createHash('sha256').update(bytes).digest('hex'),elapsedMs:Date.now()-started};
  }
}
