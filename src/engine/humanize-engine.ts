import { readFile, writeFile } from "node:fs/promises";
import type { EventSink } from "../contracts.js";
import type { CodexResult } from "./codex-runner.js";
import { EngineError } from "./errors.js";
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
}

export interface HumanizeEngineOptions {
  python: PythonAdapter;
  codex: CodexAdapter;
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

  constructor(options: HumanizeEngineOptions) {
    this.python = options.python;
    this.codex = options.codex;
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

  private emitCodexWarnings(
    request: HumanizeRequest,
    warnings: HumanizeWarning[],
    messages: string[]
  ): void {
    for (const message of messages) {
      this.emitWarning(request, warnings, {
        code: "CODEX_WARNING",
        message
      });
    }
  }

  async transform(request: HumanizeRequest): Promise<HumanizeResult> {
    this.ensureActive(request.signal);
    const warnings: HumanizeWarning[] = [];
    request.onEvent({
      type: "progress",
      phase: "sanitize",
      current: 0,
      total: 1,
      message: "원문을 안전하게 준비하는 중입니다."
    });

    const manifest = await this.python.prepare(
      request.workspace.root,
      request.signal
    );
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

    for (let bodyIndex = 0; bodyIndex < bodyChunks.length; bodyIndex += 1) {
      this.ensureActive(request.signal);
      const chunk = bodyChunks[bodyIndex]!;
      const sourceText = source.slice(chunk.start, chunk.end);
      const chunkSourcePath = request.workspace.path(
        `chunk-${chunk.index}-source.txt`
      );
      const rewrittenPath = request.workspace.path(chunk.rewrittenFile!);
      await writeFile(chunkSourcePath, sourceText, "utf8");

      request.onEvent({
        type: "progress",
        phase: "transform",
        current: bodyIndex + 1,
        total: bodyChunks.length,
        message: `${bodyIndex + 1}/${bodyChunks.length} 구간을 다듬는 중입니다.`
      });

      const first = await this.codex.transform(
        chunkSourcePath,
        request.workspace.path(`codex-${chunk.index}-attempt-1.json`),
        1,
        request.signal
      );
      this.ensureActive(request.signal);
      this.emitCodexWarnings(request, warnings, first.warnings);
      await writeFile(rewrittenPath, first.rewrittenText, "utf8");

      request.onEvent({
        type: "progress",
        phase: "verify",
        current: bodyIndex + 1,
        total: bodyChunks.length,
        message: `${bodyIndex + 1}/${bodyChunks.length} 구간을 검증하는 중입니다.`
      });
      let gate = await this.python.verify(
        chunkSourcePath,
        rewrittenPath,
        request.signal
      );
      if (gate.status === "error") {
        throw validation(`Chunk ${chunk.index} gate execution failed`);
      }

      if (gate.status === "warn" || gate.status === "abort") {
        this.emitWarning(request, warnings, {
          code: "CHUNK_RETRY",
          message: `${chunk.index}번 구간을 더 보수적으로 다시 다듬습니다.`
        });
        const second = await this.codex.transform(
          chunkSourcePath,
          request.workspace.path(`codex-${chunk.index}-attempt-2.json`),
          2,
          request.signal
        );
        this.ensureActive(request.signal);
        this.emitCodexWarnings(request, warnings, second.warnings);
        await writeFile(rewrittenPath, second.rewrittenText, "utf8");
        gate = await this.python.verify(
          chunkSourcePath,
          rewrittenPath,
          request.signal
        );
        if (gate.status === "error") {
          throw validation(`Chunk ${chunk.index} retry gate execution failed`);
        }
        if (gate.status === "abort") {
          await writeFile(rewrittenPath, sourceText, "utf8");
          this.emitWarning(request, warnings, {
            code: "CHUNK_ROLLED_BACK",
            message: `${chunk.index}번 구간은 의미 보존을 위해 원문을 유지했습니다.`
          });
        } else if (gate.status === "warn") {
          this.emitWarning(request, warnings, {
            code: "CHUNK_WARNING_ACCEPTED",
            message: `${chunk.index}번 구간에 검토 권고가 있습니다.`
          });
        }
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
    const finalPath = await this.python.reassemble(
      request.workspace.root,
      request.signal
    );
    const fullGate = await this.python.verify(
      sourcePath,
      finalPath,
      request.signal
    );
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
    return {
      finalPath,
      sourceChars: codePointLength(source),
      outputChars: codePointLength(output),
      chunks: bodyChunks.length,
      warnings
    };
  }
}
