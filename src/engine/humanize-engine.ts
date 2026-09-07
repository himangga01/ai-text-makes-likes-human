import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import type { EventSink } from "../contracts.js";
import { runChunkPool } from "./chunk-pool.js";
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
  GateResult,
  RestoreReport
} from "./python-engine.js";
import type { JobWorkspace } from "./workspace.js";

export interface PythonAdapter {
  prepare(runDir: string, signal: AbortSignal): Promise<ChunkManifest>;
  restore(
    beforePath: string,
    afterPath: string,
    signal: AbortSignal
  ): Promise<RestoreReport>;
  verify(
    beforePath: string,
    afterPath: string,
    signal: AbortSignal,
    attempt?: 1 | 2
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
  model?: string;
  reasoningEffort?: string;
  now?: () => number;
  maxObservedCodexConcurrency?: () => number;
}

interface ChunkTaskContext {
  sourcePoints: readonly string[];
  workspace: JobWorkspace;
  signal: AbortSignal;
  onWorkUnit(phase: "transform" | "verify"): void;
  onWarning(warning: HumanizeWarning): void;
}

export interface ChunkTaskResult {
  chunkIndex: number;
  warnings: HumanizeWarning[];
  codexCalls: number;
  retries: number;
  restoredSentences: number;
  removedCommas: number;
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
  private readonly model: string;
  private readonly reasoningEffort: string;
  private readonly now: () => number;
  private readonly maxObservedCodexConcurrency: () => number;

  constructor(options: HumanizeEngineOptions) {
    this.python = options.python;
    this.codex = options.codex;
    this.chunkConcurrency = options.chunkConcurrency;
    this.model = options.model ?? HUMANIZE_MODEL;
    this.reasoningEffort = options.reasoningEffort ?? HUMANIZE_REASONING_EFFORT;
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

  private recordChunkWarning(
    context: ChunkTaskContext,
    warnings: HumanizeWarning[],
    warning: HumanizeWarning
  ): void {
    warnings.push(warning);
    context.onWarning(warning);
  }

  private collectCodexWarnings(
    context: ChunkTaskContext,
    warnings: HumanizeWarning[],
    messages: string[]
  ): void {
    for (const message of messages) {
      this.recordChunkWarning(context, warnings, {
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
    // Manifest offsets are Python code-point indices, not UTF-16 units.
    const sourceText = context.sourcePoints
      .slice(chunk.start, chunk.end)
      .join("");
    const chunkSourcePath = context.workspace.path(
      `chunk-${chunk.index}-source.txt`
    );
    const rewrittenPath = context.workspace.path(chunk.rewrittenFile!);
    let codexCalls = 0;
    let retries = 0;
    let codexMs = 0;
    let restoreMs = 0;
    let gateMs = 0;
    let restoredSentences = 0;
    let removedCommas = 0;

    await writeFile(chunkSourcePath, sourceText, "utf8");

    // Deterministic post-processing right before the gate: sentences whose
    // deontic/hedge modality vanished go back to the source wording, and
    // commas the rewrite injected after connective endings are removed.
    const restore = async (): Promise<void> => {
      const startedAt = this.now();
      const report = await this.python.restore(
        chunkSourcePath,
        rewrittenPath,
        context.signal
      );
      restoreMs += this.now() - startedAt;
      restoredSentences += report.restoredSentences;
      removedCommas += report.removedCommas;
      if (report.restoredSentences > 0) {
        this.recordChunkWarning(context, warnings, {
          code: "MODALITY_RESTORED",
          message: `${chunk.index}번 구간에서 서법 보존을 위해 ${report.restoredSentences}개 문장을 원문으로 되돌렸습니다.`
        });
      }
    };

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
    context.onWorkUnit("transform");
    this.collectCodexWarnings(context, warnings, first.warnings);
    await writeFile(rewrittenPath, first.rewrittenText, "utf8");
    await restore();

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

    if (gate.policy === "retry" || (!gate.policy && (gate.status === "warn" || gate.status === "abort"))) {
      retries += 1;
      this.recordChunkWarning(context, warnings, {
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
      this.collectCodexWarnings(context, warnings, second.warnings);
      await writeFile(rewrittenPath, second.rewrittenText, "utf8");
      await restore();

      const secondGateStartedAt = this.now();
      gate = await this.python.verify(
        chunkSourcePath,
        rewrittenPath,
        context.signal,
        2
      );
      gateMs += this.now() - secondGateStartedAt;
      gateCodes.push(...gate.gateCodes);
      if (gate.status === "error") {
        throw validation(`Chunk ${chunk.index} retry gate execution failed`);
      }
      if (gate.status === "abort") {
        await writeFile(rewrittenPath, sourceText, "utf8");
        this.recordChunkWarning(context, warnings, {
          code: "CHUNK_ROLLED_BACK",
          message: `${chunk.index}번 구간은 의미 보존을 위해 원문을 유지했습니다.`
        });
      } else if (gate.status === "warn") {
        this.recordChunkWarning(context, warnings, {
          code: "CHUNK_WARNING_ACCEPTED",
          message: `${chunk.index}번 구간에 검토 권고가 있습니다.`
        });
      }
    }

    this.ensureActive(context.signal);
    context.onWorkUnit("verify");
    return {
      chunkIndex: chunk.index,
      warnings,
      codexCalls,
      retries,
      restoredSentences,
      removedCommas,
      gateCodes,
      timings: { codexMs, restoreMs, gateMs }
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
    const sourcePoints = Array.from(source);
    const lastChunk = manifest.chunks.at(-1);
    if (
      manifest.sourceChars !== sourcePoints.length ||
      (lastChunk ? lastChunk.end : 0) !== sourcePoints.length
    ) {
      throw new EngineError(
        "ENGINE_OUTPUT_INVALID",
        false,
        "Chunk manifest does not cover the prepared source text"
      );
    }
    const bodyChunks = manifest.chunks.filter(chunk => !chunk.passthrough);
    const concurrency =
      manifest.processingMode === "single" ? 1 : this.chunkConcurrency;
    let completedUnits = 0;
    const totalUnits = bodyChunks.length * 2;
    const chunkResults = await runChunkPool(
      bodyChunks.map((chunk, bodyIndex) => ({ chunk, bodyIndex })),
      concurrency,
      request.signal,
      async ({ chunk, bodyIndex }, signal) => {
        this.ensureActive(signal);
        return this.processChunk(chunk, {
          sourcePoints,
          workspace: request.workspace,
          signal,
          onWarning: warning =>
            request.onEvent({ type: "warning", ...warning }),
          onWorkUnit: phase => {
            completedUnits += 1;
            request.onEvent({
              type: "progress",
              phase,
              current: bodyIndex + 1,
              total: bodyChunks.length,
              completedUnits,
              totalUnits,
              message: phase === "transform"
                ? `${bodyIndex + 1}/${bodyChunks.length} 구간을 다듬는 중입니다.`
                : `${bodyIndex + 1}/${bodyChunks.length} 구간을 검증하는 중입니다.`
            });
          }
        });
      }
    );
    warnings.push(...chunkResults.flatMap(result => result.warnings));

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
    const sourceChars = sourcePoints.length;
    const diagnostics: TransformDiagnostics = {
      model: this.model,
      reasoningEffort: this.reasoningEffort,
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
      restoredSentences: chunkResults.reduce(
        (total, result) => total + result.restoredSentences,
        0
      ),
      removedCommas: chunkResults.reduce(
        (total, result) => total + result.removedCommas,
        0
      ),
      gateCodes: [
        ...chunkResults.flatMap(result => result.gateCodes),
        ...fullGate.gateCodes
      ],
      maxObservedCodexConcurrency: Math.min(
        this.maxObservedCodexConcurrency(),
        concurrency
      ),
      prepareMs,
      codexMs: chunkResults.reduce(
        (total, result) => total + result.timings.codexMs,
        0
      ),
      restoreMs: chunkResults.reduce(
        (total, result) => total + result.timings.restoreMs,
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
