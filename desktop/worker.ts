import { REWRITE_OPTIONS, parseRewriteOptions } from '../src/engine/rewrite-policy.js';
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { loadConfig } from "../src/config.js";
import { createProductionRuntime } from "../src/runtime/create-runtime.js";
import { SpawnCommandRunner } from "../src/process/command-runner.js";
import { JobWorkspace } from "../src/engine/workspace.js";
import { EngineError } from "../src/engine/errors.js";
import { PUBLIC_MESSAGES } from "../src/transport/public-error.js";
import { parseEngineChoice } from "../src/engine/model-policy.js";
import type { TransformEvent } from "../src/contracts.js";
import path from "node:path";
import { ArtifactStore } from '../src/documents/artifact-store.js';
import { MODEL_DEFAULTS, MODEL_OPTIONS, type ModelSettings } from '../src/engine/model-policy.js';

const port = (process as typeof process & { parentPort: { on(name: string, listener: (message: { data: any }) => void): void; postMessage(data: unknown): void } }).parentPort;
const root = process.env.HUMANIZE_RESOURCE_ROOT!;
const jobs = process.env.HUMANIZE_JOBS_ROOT!;
let active: { id: string; controller: AbortController; settled: Promise<void> } | undefined;
let stopping = false;
let documentStore: ArtifactStore|undefined;
let documentStorePromise: Promise<ArtifactStore>|undefined;
const documentReadLeases=new Map<string,()=>Promise<void>>();
async function documents() {
  documentStorePromise ??= runtime().then(services=>documentStore=new ArtifactStore(path.join(jobs,'document-artifacts'),services.documentEngine));
  return documentStorePromise;
}
async function transformDocument(id:string,input:any,signal:AbortSignal) {
  const store=await documents();const record=store.get(input.id,input.token);
  if(record.busy||record.output||!record.state)throw new Error('문서를 다시 선택해 주세요.');
  record.busy=true;
  let complete=false,accepted=false;
  try {
    const services=await runtime(input.commands);
    const choice=parseEngineChoice(input.engine);
    if(!choice||!services.preflight.providers?.[choice].ready)throw new EngineError('ENGINE_UNAVAILABLE',true,'CLI is not ready');
    event(id,{type:'accepted',jobId:id,position:0});accepted=true;
    const result=await services.documentEngine.transform(record.state,choice,record.dir,AbortSignal.any([signal,record.controller.signal]),value=>event(id,value),input.settings);
    if(record.deleted||record.controller.signal.aborted)throw new EngineError('CLIENT_ABORTED',true,'Document was closed during the transform');
    record.output=result.output;record.state=result.state;
    record.expires=Date.now()+30*60000;
    event(id,{type:'document-result',artifactId:record.id,name:record.name!,format:result.state.format,bytes:result.bytes,sha256:result.sha256,preview:result.state.preview});
    event(id,{type:'done',sourceChars:result.state.sourceChars,outputChars:result.state.sourceChars,chunks:result.state.totalChunks,elapsedMs:result.elapsedMs});
    complete=true;
  } catch(e){
    // A job that started is removed after any failure and cannot be retried; a rejection before
    // "accepted" keeps the document so the user can fix the CLI or model and convert it again.
    if(e instanceof EngineError)event(id,{type:'error',code:e.publicCode,message:errorMessage(e),retryable:!accepted});
    else event(id,{type:'error',code:'VALIDATION_FAILED',message:e instanceof Error&&/[가-힣]/.test(e.message)?e.message:'문서 변환에 실패했습니다.',retryable:!accepted});
  }
  finally {record.busy=false;if(!complete&&accepted)await store.remove(record);}
}

function event(id: string, value: TransformEvent) { port.postMessage({ kind: "event", id, event: value }); }
function errorMessage(error: unknown): string {
  const messages: Record<string, string> = {
    CLIENT_ABORTED: "변환을 취소했습니다.", ENGINE_TIMEOUT: "변환 시간이 초과되었습니다.",
    ENGINE_OUTPUT_INVALID: "CLI 결과를 읽지 못했습니다. 선택한 CLI의 로그인·모델 접근 상태를 확인해 주세요.",
    VALIDATION_FAILED: "내용 보존 검증을 통과하지 못했습니다.", ENGINE_UNAVAILABLE: "선택한 CLI의 설치·로그인 상태를 확인해 주세요.",
    MODEL_UNAVAILABLE: PUBLIC_MESSAGES.MODEL_UNAVAILABLE
  };
  // Codes without a desktop wording (e.g. ENGINE_FAILED) use the shared public message.
  return error instanceof EngineError ? messages[error.publicCode] ?? (PUBLIC_MESSAGES as Record<string, string>)[error.publicCode] ?? "변환에 실패했습니다." : "작업을 처리하지 못했습니다. 다시 시도해 주세요.";
}
async function runtime(commands: Record<string, string> = {}) {
  const base = loadConfig(process.env, root);
  return createProductionRuntime({ ...base, runtimeRoot: jobs,
    pythonCommand: process.env.HUMANIZE_PYTHON ?? base.pythonCommand,
    codexCommand: commands.codex || base.codexCommand, claudeCommand: commands.claude || base.claudeCommand
  }, new SpawnCommandRunner((pid, alive) => port.postMessage({ kind: "child", pid, alive })));
}
async function transform(id: string, input: { text: string; engine: string; commands: Record<string, string>; inputKind?:unknown; strength?:unknown; settings?:ModelSettings }, signal: AbortSignal) {
  let workspace: JobWorkspace | undefined;
  const startedAt = Date.now();
  try {
    const rewriteOptions = parseRewriteOptions(input.inputKind,input.strength);
    const engineChoice = parseEngineChoice(input.engine);
    if (!engineChoice || typeof input.text !== "string" || !input.text.trim()) throw new EngineError("EMPTY_INPUT", false, "Empty input");
    event(id, { type: "accepted", jobId: id, position: 0 });
    const services = await runtime(input.commands);
    if (signal.aborted) throw new EngineError("CLIENT_ABORTED", true, "Cancelled");
    if (!services.preflight.ready || !services.preflight.providers?.[engineChoice].ready) throw new EngineError("ENGINE_UNAVAILABLE", true, "Not ready");
    workspace = await JobWorkspace.create(jobs, id);
    await writeFile(workspace.path("01_input.txt"), input.text.replace(/\r\n?/g, "\n"), "utf8");
    const engine = engineChoice === "claude" ? services.claudeEngine! : services.engine;
    const result = await engine.transform({ jobId: id, workspace, signal, settings:input.settings, rewriteOptions, onEvent: value => event(id, value) });
    if (signal.aborted) throw new EngineError("CLIENT_ABORTED", true, "Cancelled");
    const text = await readFile(result.finalPath, "utf8");
    event(id, { type: "result-start" });
    // Do not cut surrogate pairs between IPC deltas.
    const points = Array.from(text);
    for (let offset = 0; offset < points.length; offset += 16384) event(id, { type: "result-delta", text: points.slice(offset, offset + 16384).join("") });
    event(id, { type: "done", sourceChars: result.sourceChars, outputChars: result.outputChars, chunks: result.chunks, elapsedMs: Date.now() - startedAt });
  } catch (error) {
    event(id, { type: "error", code: error instanceof EngineError ? error.publicCode : "INTERNAL_ERROR", message: errorMessage(error), retryable: true });
  } finally {
    await workspace?.cleanup();
  }
}

port.on("message", ({ data }) => {
  if (data.kind === "cancel") { if (active && active.id === data.id) active.controller.abort(); return; }
  const respond = (value: unknown) => port.postMessage({ kind: "response", id: data.id, value });
  // Korean messages are user-facing (document import/save rejections); anything else is internal.
  const fail = (error: unknown) => { const message = (error as { message?: unknown } | undefined)?.message;
    port.postMessage({ kind: "response", id: data.id, error: typeof message === "string" && /[가-힣]/.test(message) ? message : "엔진 작업을 처리하지 못했습니다." }); };
  (async () => {
    if (data.kind === "shutdown") {
      stopping = true; active?.controller.abort(); await active?.settled;
      await documentStorePromise?.catch(()=>undefined);
      await Promise.allSettled([...documentReadLeases.values()].map(release=>release()));documentReadLeases.clear();
      await documentStore?.close(); respond(true); return;
    }
    if (stopping) throw new Error("Stopping");
    if(data.kind==='document-import') {if(active)throw new Error('Busy');respond(await (await documents()).importFile(data.file));return;}
    if(data.kind==='document-close') {const store=await documents();await store.remove(store.get(data.documentId,data.token));respond(true);return;}
    if(data.kind==='document-result') {
      const store=await documents();const lease=store.readResult(data.documentId,data.token);const r=lease.record;
      documentReadLeases.set(data.id,lease.release);
      respond({name:r.name,format:r.state!.format,output:r.output,original:r.original,leaseId:data.id});return;
    }
    if(data.kind==='document-release') {const release=documentReadLeases.get(data.leaseId);documentReadLeases.delete(data.leaseId);await release?.();respond(true);return;}
    if (data.kind === "health") {
      const services = await runtime(data.commands);
      respond({ status: services.preflight.ready ? "ready" : "degraded", ...services.preflight,
        rewriteOptions: REWRITE_OPTIONS,
        modelOptions: MODEL_OPTIONS, modelDefaults: MODEL_DEFAULTS, checkedAt:new Date().toISOString(),
        documentsAvailable: await services.documentEngine.health(),
        claudeAvailable: Boolean(services.claudeEngine), activeJobs: active ? 1 : 0, queuedJobs: 0 });
      return;
    }
    if (!['transform','document-transform'].includes(data.kind) || active) throw new Error("Already running");
    const controller = new AbortController();
    let finish!:()=>void;
    const settled=new Promise<void>(resolve=>finish=resolve);
    const job={id:data.id,controller,settled};active=job;
    try {
      await mkdir(path.resolve(jobs), { recursive: true });
      controller.signal.throwIfAborted();
      if(stopping)throw new Error('Stopping');
      await (data.kind==='document-transform'?transformDocument(data.id,data.input,controller.signal):transform(data.id,data.input,controller.signal));
      respond(true);
    } finally {if(active===job)active=undefined;finish();}
  })().catch(fail);
});
