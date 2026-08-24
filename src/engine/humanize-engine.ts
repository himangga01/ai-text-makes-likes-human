import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import type { EventSink } from "../contracts.js";
import type { CodexResult } from "./codex-runner.js";
import type {
  ChunkTiming,
  GateCode,
  TransformDiagnostics
} from "./diagnostics.js";
import { EngineError } from "./errors.js";
import {
  HUMANIZE_MODEL,
  HUMANIZE_REASONING_EFFORT
} from "./model-policy.js";
import type {
  ChunkManifest,
  GateResult
} from "./python-engine.js";
import type { JobWorkspace } from "./workspace.js";

export interface PythonAdapter {
  prepare(runDir: string, signal: AbortSignal): Promise<ChunkManifest>;
  verify(
    beforePath: string,
    afterPath: string,
    signal: AbortSignal
  ): Promise<GateResult>;
  reassemble(runDir: string, signal: AbortSignal): Promise<string>;
}

export interface CodexAdapter {
  transform(
    inputPath: string,
    outputPath: string,
    attempt: 1 | 2,
    signal: AbortSignal
  ): Promise<CodexResult>;
}

export interface HumanizeRequest {
  jobId: string;
  workspace: JobWorkspace;
  signal: AbortSignal;
  onEvent: EventSink;
}

export interface HumanizeWarning {
  code: string;
  message: string;
}

export interface HumanizeResult {
  finalPath: string;
  sourceChars: number;
  outputChars: number;
  chunks: number;
  warnings: HumanizeWarning[];
  diagnostics: TransformDiagnostics;
}

export interface HumanizeEngineOptions {
  python: PythonAdapter;
  codex: CodexAdapter;
  chunkConcurrency: 1 | 2;
  now?: () => number;
  maxObservedCodexConcurrency?: () => number;
}

interface ChunkTaskContext {
  source: string;
  workspace: JobWorkspace;
  signal: AbortSignal;
  onWorkUnit(): void;
}

export interface ChunkTaskResult {
  chunkIndex: number;
  warnings: HumanizeWarning[];
  codexCalls: number;
  retries: number;
  gateCodes: GateCode[];
  timings: ChunkTiming;
}

function cancelled(): EngineError {
  return new EngineError(
    "CLIENT_ABORTED",
    true,
    "Transformation was cancelled"
  );
}

function validation(message: string): EngineError {
  return new EngineError("VALIDATION_FAILED", false, message);
}

function codePointLength(value: string): number {
  return Array.from(value).length;
}

export class HumanizeEngine {
  private readonly python: PythonAdapter;
  private readonly codex: CodexAdapter;
  private readonly chunkConcurrency: 1 | 2;
  private readonly now: () => number;
  private readonly maxObservedCodexConcurrency: () => number;

  constructor(options: HumanizeEngineOptions) {
    this.python = options.python;
    this.codex = options.codex;
    this.chunkConcurrency = options.chunkConcurrency;
    this.now = options.now ?? (() => performance.now());
    this.maxObservedCodexConcurrency =
      options.maxObservedCodexConcurrency ?? (() => 1);
  }

  private ensureActive(signal: AbortSignal): void {
    if (signal.aborted) throw cancelled();
  }

  private emitWarning(
    request: HumanizeRequest,
    warnings: HumanizeWarning[],
    warning: HumanizeWarning
  ): void {
    warnings.push(warning);
    request.onEvent({ type: "warning", ...warning });
  }

  private collectCodexWarnings(
    warnings: HumanizeWarning[],
    messages: string[]
  ): void {
    for (const message of messages) {
      warnings.push({
        code: "CODEX_WARNING",
        message
      });
    }
  }

  private async processChunk(
    chunk: ChunkManifest["chunks"][number],
    context: ChunkTaskContext
  ): Promise<ChunkTaskResult> {
    this.ensureActive(context.signal);
    const warnings: HumanizeWarning[] = [];
    const gateCodes: GateCode[] = [];
    const sourceText = context.source.slice(chunk.start, chunk.end);
    const chunkSourcePath = context.workspace.path(
      `chunk-${chunk.index}-source.txt`
    );
    const rewrittenPath = context.workspace.path(chunk.rewrittenFile!);
    let codexCalls = 0;
    let retries = 0;
    let codexMs = 0;
    let gateMs = 0;

    await writeFile(chunkSourcePath, sourceText, "utf8");

    const firstCodexStartedAt = this.now();
    const first = await this.codex.transform(
      chunkSourcePath,
      context.workspace.path(`codex-${chunk.index}-attempt-1.json`),
      1,
      context.signal
    );
    codexMs += this.now() - firstCodexStartedAt;
    codexCalls += 1;
    this.ensureActive(context.signal);
    this.collectCodexWarnings(warnings, first.warnings);
    await writeFile(rewrittenPath, first.rewrittenText, "utf8");
    context.onWorkUnit();

    const firstGateStartedAt = this.now();
    let gate = await this.python.verify(
      chunkSourcePath,
      rewrittenPath,
      context.signal
    );
    gateMs += this.now() - firstGateStartedAt;
    gateCodes.push(...gate.gateCodes);
    if (gate.status === "error") {
      throw validation(`Chunk ${chunk.index} gate execution failed`);
    }

    if (gate.status === "warn" || gate.status === "abort") {
      retries += 1;
      warnings.push({
        code: "CHUNK_RETRY",
        message: `${chunk.index}번 구간을 더 보수적으로 다시 다듬습니다.`
      });

      const secondCodexStartedAt = this.now();
      const second = await this.codex.transform(
        chunkSourcePath,
        context.workspace.path(`codex-${chunk.index}-attempt-2.json`),
        2,
        context.signal
      );
      codexMs += this.now() - secondCodexStartedAt;
      codexCalls += 1;
      this.ensureActive(context.signal);
      this.collectCodexWarnings(warnings, second.warnings);
      await writeFile(rewrittenPath, second.rewrittenText, "utf8");

      const secondGateStartedAt = this.now();
      gate = await this.python.verify(
        chunkSourcePath,
        rewrittenPath,
        context.signal
      );
      gateMs += this.now() - secondGateStartedAt;
      gateCodes.push(...gate.gateCodes);
      if (gate.status === "error") {
        throw validation(`Chunk ${chunk.index} retry gate execution failed`);
      }
      if (gate.status === "abort") {
        await writeFile(rewrittenPath, sourceText, "utf8");
        warnings.push({
          code: "CHUNK_ROLLED_BACK",
          message: `${chunk.index}번 구간은 의미 보존을 위해 원문을 유지했습니다.`
        });
      } else if (gate.status === "warn") {
        warnings.push({
          code: "CHUNK_WARNING_ACCEPTED",
          message: `${chunk.index}번 구간에 검토 권고가 있습니다.`
        });
      }
    }

    context.onWorkUnit();
    return {
      chunkIndex: chunk.index,
      warnings,
      codexCalls,
      retries,
      gateCodes,
      timings: { codexMs, gateMs }
    };
  }

  async transform(request: HumanizeRequest): Promise<HumanizeResult> {
    const totalStartedAt = this.now();
    this.ensureActive(request.signal);
    const warnings: HumanizeWarning[] = [];
    request.onEvent({
      type: "progress",
      phase: "sanitize",
      current: 0,
      total: 1,
      message: "원문을 안전하게 준비하는 중입니다."
    });

    const prepareStartedAt = totalStartedAt;
    const manifest = await this.python.prepare(
      request.workspace.root,
      request.signal
    );
    const prepareMs = this.now() - prepareStartedAt;
    this.ensureActive(request.signal);
    request.onEvent({
      type: "progress",
      phase: "chunk",
      current: 1,
      total: 1,
      message: `${manifest.bodyChunkCount}개 구간으로 준비했습니다.`
    });

    for (const message of manifest.warnings) {
      this.emitWarning(request, warnings, {
        code: "CHUNK_PREPARE_WARNING",
        message
      });
    }

    const sourcePath = request.workspace.path(manifest.sourceFile);
    const source = await readFile(sourcePath, "utf8");
    const bodyChunks = manifest.chunks.filter(chunk => !chunk.passthrough);
    const chunkResults: ChunkTaskResult[] = [];

    for (let bodyIndex = 0; bodyIndex < bodyChunks.length; bodyIndex += 1) {
      this.ensureActive(request.signal);
      const chunk = bodyChunks[bodyIndex]!;
      request.onEvent({
        type: "progress",
        phase: "transform",
        current: bodyIndex + 1,
        total: bodyChunks.length,
        message: `${bodyIndex + 1}/${bodyChunks.length} 구간을 다듬는 중입니다.`
      });

      let completedUnits = 0;
      const chunkResult = await this.processChunk(chunk, {
        source,
        workspace: request.workspace,
        signal: request.signal,
        onWorkUnit: () => {
          completedUnits += 1;
          if (completedUnits === 1) {
            request.onEvent({
              type: "progress",
              phase: "verify",
              current: bodyIndex + 1,
              total: bodyChunks.length,
              message: `${bodyIndex + 1}/${bodyChunks.length} 구간을 검증하는 중입니다.`
            });
          }
        }
      });
      chunkResults.push(chunkResult);
      for (const warning of chunkResult.warnings) {
        this.emitWarning(request, warnings, warning);
      }
    }

    this.ensureActive(request.signal);
    request.onEvent({
      type: "progress",
      phase: "assemble",
      current: 1,
      total: 1,
      message: "문단과 순서를 복원하는 중입니다."
    });
    const assembleStartedAt = this.now();
    const finalPath = await this.python.reassemble(
      request.workspace.root,
      request.signal
    );
    const assembleFinishedAt = this.now();
    const assembleMs = assembleFinishedAt - assembleStartedAt;
    const fullGateStartedAt = assembleFinishedAt;
    const fullGate = await this.python.verify(
      sourcePath,
      finalPath,
      request.signal
    );
    const fullGateMs = this.now() - fullGateStartedAt;
    if (fullGate.status === "abort" || fullGate.status === "error") {
      throw validation("Full-document validation failed");
    }
    if (fullGate.status === "warn") {
      this.emitWarning(request, warnings, {
        code: "DOCUMENT_REVIEW_RECOMMENDED",
        message: "전체 문서에 사람 검토가 권장되는 항목이 있습니다."
      });
    }

    const output = await readFile(finalPath, "utf8");
    const sourceChars = codePointLength(source);
    const diagnostics: TransformDiagnostics = {
      model: HUMANIZE_MODEL,
      reasoningEffort: HUMANIZE_REASONING_EFFORT,
      processingMode: manifest.processingMode,
      routeHint: manifest.routeHint,
      sourceChars,
      bodyChunks: bodyChunks.length,
      codexCalls: chunkResults.reduce(
        (total, result) => total + result.codexCalls,
        0
      ),
      retries: chunkResults.reduce(
        (total, result) => total + result.retries,
        0
      ),
      gateCodes: [
        ...chunkResults.flatMap(result => result.gateCodes),
        ...fullGate.gateCodes
      ],
      maxObservedCodexConcurrency: this.maxObservedCodexConcurrency(),
      prepareMs,
      codexMs: chunkResults.reduce(
        (total, result) => total + result.timings.codexMs,
        0
      ),
      gateMs:
        chunkResults.reduce(
          (total, result) => total + result.timings.gateMs,
          0
        ) + fullGateMs,
      assembleMs,
      totalMs: this.now() - totalStartedAt
    };
    return {
      finalPath,
      sourceChars,
      outputChars: codePointLength(output),
      chunks: bodyChunks.length,
      warnings,
      diagnostics
    };
  }
}
