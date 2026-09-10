import { parseRewriteOptions, type RewriteOptions } from './rewrite-policy.js';
import { checkDirectTextFidelity } from './direct-text-fidelity.js';
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
import type { ModelSettings } from './model-policy.js';

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
    signal: AbortSignal,
    settings?: ModelSettings,
    rewriteOptions?: RewriteOptions
  ): Promise<CodexResult>;
}

export interface HumanizeRequest {
  rewriteOptions?: RewriteOptions;
  settings?: ModelSettings;
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
  rewriteOptions?: RewriteOptions;
  settings?: ModelSettings;
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
  skippedSentences: number;
  fidelityGuardFailures: number;
  rolledBackChunks: number;
  protectedSentences: number;
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
    let skippedSentences = 0;
    let fidelityGuardFailures = 0;
    let rolledBackChunks = 0;
    const direct = context.rewriteOptions?.inputKind === 'direct-text';
    const protectedSentences = direct ? checkDirectTextFidelity(sourceText, sourceText).protectedSentences : 0;
    let fidelityFailed = false;
    let candidateFidelityIssues = 0;
    if (protectedSentences > 0 && context.rewriteOptions?.strength !== 'normal') {
      this.recordChunkWarning(context, warnings, {
        code: 'DIRECT_TEXT_PROTECTED_SENTENCES',
        message: `${chunk.index}번 구간의 ${protectedSentences}개 문장은 사실·인용·서법 또는 조건 보존을 위해 원문을 유지하므로 변경 범위가 작을 수 있습니다.`
      });
    }

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
      if (direct) {
        skippedSentences += report.skippedSentences;
        fidelityFailed = candidateFidelityIssues > 0 || report.skippedSentences > 0 || checkDirectTextFidelity(sourceText, await readFile(rewrittenPath, 'utf8')).violations > 0;
        if (fidelityFailed) {
          fidelityGuardFailures++;
          this.recordChunkWarning(context, warnings, {
            code: 'DIRECT_TEXT_FIDELITY_RESTRICTED',
            message: `${chunk.index}번 구간에서 문장 경계·사실 관계·핵심 개념 또는 서법 보존을 확인하지 못해 넓은 수정을 제한했습니다.`
          });
        }
      }
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
      context.signal,
      context.settings,
      context.rewriteOptions
    );
    codexMs += this.now() - firstCodexStartedAt;
    codexCalls += 1;
    this.ensureActive(context.signal);
    context.onWorkUnit("transform");
    this.collectCodexWarnings(context, warnings, first.warnings);
    candidateFidelityIssues = first.fidelityIssues ?? 0;
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

    if (fidelityFailed || gate.policy === "retry" || (!gate.policy && (gate.status === "warn" || gate.status === "abort"))) {
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
        context.signal,
        context.settings,
        context.rewriteOptions
      );
      codexMs += this.now() - secondCodexStartedAt;
      codexCalls += 1;
      this.ensureActive(context.signal);
      this.collectCodexWarnings(context, warnings, second.warnings);
      candidateFidelityIssues = second.fidelityIssues ?? 0;
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
      if (fidelityFailed || gate.status === "abort") {
        if (direct) rolledBackChunks++;
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
      skippedSentences, fidelityGuardFailures, rolledBackChunks, protectedSentences,
      gateCodes,
      timings: { codexMs, restoreMs, gateMs }
    };
  }

  async transform(request: HumanizeRequest): Promise<HumanizeResult> {
    const rewriteOptions = parseRewriteOptions(request.rewriteOptions?.inputKind, request.rewriteOptions?.strength);
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
          settings: request.settings,
          rewriteOptions,
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
    let fullFidelityFailures = 0;
    if (rewriteOptions?.inputKind === 'direct-text' && checkDirectTextFidelity(source, await readFile(finalPath, 'utf8')).violations > 0) {
      fullFidelityFailures = 1;
      await writeFile(finalPath, source, 'utf8');
      this.emitWarning(request, warnings, {code:'DIRECT_TEXT_DOCUMENT_ROLLED_BACK',message:'전체 글의 문장 경계·내용 보존을 확인하지 못해 원문을 유지했습니다.'});
    }
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
      ...(rewriteOptions ? {requestedStrength: rewriteOptions.strength} : {}),
      ...(rewriteOptions?.inputKind === 'direct-text' ? {
        conservativeRetries: chunkResults.reduce((sum, result) => sum + result.retries, 0),
        skippedSentences: chunkResults.reduce((sum, result) => sum + result.skippedSentences, 0),
        fidelityGuardFailures: chunkResults.reduce((sum, result) => sum + result.fidelityGuardFailures, 0) + fullFidelityFailures,
        rolledBackChunks: chunkResults.reduce((sum, result) => sum + result.rolledBackChunks, 0),
        protectedSentences: chunkResults.reduce((sum, result) => sum + result.protectedSentences, 0),
        fullSourceRollbacks: fullFidelityFailures
      } : {}),
      model: request.settings?.model ?? this.model,
      reasoningEffort: request.settings?.effort ?? this.reasoningEffort,
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
