import { readFile, writeFile, mkdir } from "node:fs/promises";
import { loadConfig } from "../src/config.js";
import { createProductionRuntime } from "../src/runtime/create-runtime.js";
import { SpawnCommandRunner } from "../src/process/command-runner.js";
import { JobWorkspace } from "../src/engine/workspace.js";
import { EngineError } from "../src/engine/errors.js";
import { parseEngineChoice } from "../src/engine/model-policy.js";
import type { TransformEvent } from "../src/contracts.js";
import path from "node:path";

const port = (process as typeof process & { parentPort: { on(name: string, listener: (message: { data: any }) => void): void; postMessage(data: unknown): void } }).parentPort;
const root = process.env.HUMANIZE_RESOURCE_ROOT!;
const jobs = process.env.HUMANIZE_JOBS_ROOT!;
let active: { id: string; controller: AbortController; settled: Promise<void> } | undefined;
let stopping = false;

function event(id: string, value: TransformEvent) { port.postMessage({ kind: "event", id, event: value }); }
function errorMessage(error: unknown): string {
  const messages: Record<string, string> = {
    CLIENT_ABORTED: "변환을 취소했습니다.", ENGINE_TIMEOUT: "변환 시간이 초과되었습니다.",
    ENGINE_OUTPUT_INVALID: "CLI 결과를 읽지 못했습니다. 선택한 CLI의 로그인·모델 접근 상태를 확인해 주세요.",
    VALIDATION_FAILED: "내용 보존 검증을 통과하지 못했습니다.", ENGINE_UNAVAILABLE: "선택한 CLI의 설치·로그인 상태를 확인해 주세요."
  };
  return error instanceof EngineError ? messages[error.publicCode] ?? "변환에 실패했습니다." : "작업을 처리하지 못했습니다. 다시 시도해 주세요.";
}
async function runtime(commands: Record<string, string> = {}) {
  const base = loadConfig(process.env, root);
  return createProductionRuntime({ ...base, runtimeRoot: jobs,
    pythonCommand: process.env.HUMANIZE_PYTHON ?? base.pythonCommand,
    codexCommand: commands.codex || base.codexCommand, claudeCommand: commands.claude || base.claudeCommand
  }, new SpawnCommandRunner((pid, alive) => port.postMessage({ kind: "child", pid, alive })));
}
async function transform(id: string, input: { text: string; engine: string; commands: Record<string, string> }, signal: AbortSignal) {
  let workspace: JobWorkspace | undefined;
  const startedAt = Date.now();
  try {
    const engineChoice = parseEngineChoice(input.engine);
    if (!engineChoice || typeof input.text !== "string" || !input.text.trim()) throw new EngineError("EMPTY_INPUT", false, "Empty input");
    event(id, { type: "accepted", jobId: id, position: 0 });
    const services = await runtime(input.commands);
    if (signal.aborted) throw new EngineError("CLIENT_ABORTED", true, "Cancelled");
    if (!services.preflight.ready || !services.preflight.providers?.[engineChoice].ready) throw new EngineError("ENGINE_UNAVAILABLE", true, "Not ready");
    workspace = await JobWorkspace.create(jobs, id);
    await writeFile(workspace.path("01_input.txt"), input.text.replace(/\r\n?/g, "\n"), "utf8");
    const engine = engineChoice === "claude" ? services.claudeEngine! : services.engine;
    const result = await engine.transform({ jobId: id, workspace, signal, onEvent: value => event(id, value) });
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
  const fail = () => port.postMessage({ kind: "response", id: data.id, error: "엔진 작업을 처리하지 못했습니다." });
  (async () => {
    if (data.kind === "shutdown") {
      stopping = true; active?.controller.abort(); await active?.settled; respond(true); return;
    }
    if (stopping) throw new Error("Stopping");
    if (data.kind === "health") {
      const services = await runtime(data.commands);
      respond({ status: services.preflight.ready ? "ready" : "degraded", ...services.preflight,
        claudeAvailable: Boolean(services.claudeEngine), activeJobs: active ? 1 : 0, queuedJobs: 0 });
      return;
    }
    if (data.kind !== "transform" || active) throw new Error("Already running");
    await mkdir(path.resolve(jobs), { recursive: true });
    const controller = new AbortController();
    const settled = transform(data.id, data.input, controller.signal);
    active = { id: data.id, controller, settled };
    try { await settled; respond(true); } finally { active = undefined; }
  })().catch(fail);
});
