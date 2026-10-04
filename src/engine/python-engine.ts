import { readFile } from "node:fs/promises";
import path from "node:path";
import { EngineError } from "./errors.js";
import { parseGateReasonMetadata, type GateReasonMetadata } from './candidate-review.js';
import type {
  GateCode,
  ProcessingMode,
  RouteHint
} from "./diagnostics.js";
import type {
  CommandResult,
  CommandRunner
} from "../process/command-runner.js";

export interface ChunkEntry {
  index: number;
  start: number;
  end: number;
  charCount: number;
  startsWithHeading: boolean;
  heading: string | null;
  passthrough: boolean;
  inputFile: string | null;
  rewrittenFile: string | null;
}

export interface ChunkManifest {
  version: 1;
  sourceFile: string;
  sourceChars: number;
  sourceSha256: string;
  chunkCount: number;
  bodyChunkCount: number;
  passthroughChunkCount: number;
  routeHint: RouteHint | null;
  routeReason: string | null;
  processingMode: ProcessingMode;
  chunks: ChunkEntry[];
  warnings: string[];
}

export interface GateResult {
  warningReasons?: GateReasonMetadata;
  hardFailures?: string[];
  /** Super Sejong codes that would have blocked in enforce mode (SUPER_SEJONG_MODE=shadow). */
  shadowFailures?: string[];
  status: "ok" | "warn" | "abort" | "error";
  exitCode: 0 | 1 | 2 | 3;
  gateCodes: GateCode[];
  policy?: "accept" | "retry" | "rollback" | "accept-with-warning" | "error";
}

export interface RestoreReport {
  restoredSentences: number;
  skippedSentences: number;
  removedCommas: number;
  /** Particle allomorphs (회의을 → 회의를) the Super Sejong josa step repaired after the rewrite. */
  repairedParticles?: number;
}

export interface PythonEngineOptions {
  pythonCommand: string;
  vendorRoot: string;
  runner: CommandRunner;
  timeoutMs?: number;
  autoRoute?: boolean;
}

function invalid(message: string, cause?: unknown): EngineError {
  return new EngineError("ENGINE_OUTPUT_INVALID", false, message, { cause });
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw invalid(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function integer(value: unknown, label: string): number {
  if (!Number.isInteger(value) || Number(value) < 0) {
    throw invalid(`${label} must be a nonnegative integer`);
  }
  return Number(value);
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string") throw invalid(`${label} must be a string`);
  return value;
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw invalid(`${label} must be a boolean`);
  return value;
}

function safeLeaf(value: unknown, label: string): string {
  const leaf = text(value, label);
  if (
    leaf.length === 0 ||
    path.isAbsolute(leaf) ||
    leaf.includes("/") ||
    leaf.includes("\\") ||
    leaf === "." ||
    leaf === ".."
  ) {
    throw invalid(`${label} must be a safe filename`);
  }
  return leaf;
}

function nullableLeaf(value: unknown, label: string): string | null {
  return value === null ? null : safeLeaf(value, label);
}

function routeHint(value: unknown): RouteHint | null {
  if (value === null) return null;
  if (value === "light" || value === "standard" || value === "heavy") {
    return value;
  }
  throw invalid("route_hint must be light, standard, heavy, or null");
}

function processingMode(value: unknown): ProcessingMode {
  if (value === "single" || value === "chunked") return value;
  throw invalid("processing_mode must be single or chunked");
}

function nullableText(value: unknown, label: string): string | null {
  return value === null ? null : text(value, label);
}

function parseJsonReport(
  output: string,
  label: string
): Record<string, unknown> {
  const starts = [...output.matchAll(/^\{/gmu)].map(match => match.index!);
  for (const start of starts.reverse()) {
    try {
      const value: unknown = JSON.parse(output.slice(start).trim());
      return record(value, `${label} report`);
    } catch {
      // Continue to an earlier line-starting object.
    }
  }
  throw invalid(`Unable to parse ${label} JSON report`);
}

function parseGateReport(stdout: string): Record<string, unknown> {
  return parseJsonReport(stdout, "gate");
}

const GATE_CODES = [
  "GATE_OK",
  "GATE_WARN",
  "GATE_ABORT",
  "GATE_ERROR"
] as const;

function parseManifest(value: unknown): ChunkManifest {
  const root = record(value, "manifest");
  const version = integer(root.version, "version");
  if (version !== 1) throw invalid("Unsupported manifest version");
  if (!Array.isArray(root.chunks)) throw invalid("chunks must be an array");

  const chunks = root.chunks.map((raw, offset): ChunkEntry => {
    const chunk = record(raw, `chunks[${offset}]`);
    const passthrough = boolean(chunk.passthrough, `chunks[${offset}].passthrough`);
    const inputFile = nullableLeaf(chunk.input_file, `chunks[${offset}].input_file`);
    const rewrittenFile = nullableLeaf(
      chunk.rewritten_file,
      `chunks[${offset}].rewritten_file`
    );
    if (passthrough && (inputFile !== null || rewrittenFile !== null)) {
      throw invalid("Passthrough chunks cannot have rewrite filenames");
    }
    if (!passthrough && (inputFile === null || rewrittenFile === null)) {
      throw invalid("Body chunks require input and rewritten filenames");
    }

    const headingValue = chunk.heading;
    if (headingValue !== null && typeof headingValue !== "string") {
      throw invalid(`chunks[${offset}].heading must be string or null`);
    }
    return {
      index: integer(chunk.index, `chunks[${offset}].index`),
      start: integer(chunk.start, `chunks[${offset}].start`),
      end: integer(chunk.end, `chunks[${offset}].end`),
      charCount: integer(chunk.char_count, `chunks[${offset}].char_count`),
      startsWithHeading: boolean(
        chunk.starts_with_heading,
        `chunks[${offset}].starts_with_heading`
      ),
      heading: headingValue as string | null,
      passthrough,
      inputFile,
      rewrittenFile
    };
  });

  const chunkCount = integer(root.chunk_count, "chunk_count");
  if (chunks.length !== chunkCount) throw invalid("chunk_count mismatch");
  for (let index = 0; index < chunks.length; index += 1) {
    const chunk = chunks[index]!;
    const previous = chunks[index - 1];
    if (chunk.index !== index + 1 || chunk.end < chunk.start) {
      throw invalid("Invalid chunk ordering");
    }
    if (previous && previous.end !== chunk.start) {
      throw invalid("Chunk spans are not contiguous");
    }
  }

  const warningsRaw = root.warnings;
  if (!Array.isArray(warningsRaw) || warningsRaw.some(item => typeof item !== "string")) {
    throw invalid("warnings must be a string array");
  }

  return {
    version: 1,
    sourceFile: safeLeaf(root.source_file, "source_file"),
    sourceChars: integer(root.source_chars, "source_chars"),
    sourceSha256: text(root.source_sha256, "source_sha256"),
    chunkCount,
    bodyChunkCount: integer(root.body_chunk_count, "body_chunk_count"),
    passthroughChunkCount: integer(
      root.passthrough_chunk_count,
      "passthrough_chunk_count"
    ),
    routeHint: routeHint(root.route_hint),
    routeReason: nullableText(root.route_reason, "route_reason"),
    processingMode: processingMode(root.processing_mode),
    chunks,
    warnings: warningsRaw as string[]
  };
}

export class PythonEngine {
  private readonly pythonCommand: string;
  private readonly vendorRoot: string;
  private readonly runner: CommandRunner;
  private readonly timeoutMs: number;
  private readonly autoRoute: boolean;

  constructor(options: PythonEngineOptions) {
    this.pythonCommand = options.pythonCommand;
    this.vendorRoot = path.resolve(options.vendorRoot);
    this.runner = options.runner;
    this.timeoutMs = options.timeoutMs ?? 120_000;
    this.autoRoute = options.autoRoute ?? true;
  }

  private script(name: string): string {
    return path.join(this.vendorRoot, "scripts", name);
  }

  private async run(
    args: string[],
    cwd: string,
    signal: AbortSignal
  ): Promise<CommandResult> {
    const result = await this.runner.run({
      command: this.pythonCommand,
      args,
      cwd,
      timeoutMs: this.timeoutMs,
      signal,
      env: {
        ...process.env,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONUTF8: "1"
      }
    });
    if (result.termination === "timeout") {
      throw new EngineError("ENGINE_TIMEOUT", true, "Python engine timed out");
    }
    if (result.termination === "aborted") {
      throw new EngineError("CLIENT_ABORTED", true, "Python engine was cancelled");
    }
    if (result.termination === "output-limit") {
      throw invalid("Python engine output exceeded the limit");
    }
    return result;
  }

  async prepare(runDir: string, signal: AbortSignal): Promise<ChunkManifest> {
    const args = [
      this.script("prepare_monolith_input.py"),
      "--chunk",
      ...(this.autoRoute ? ["--portal-auto-route"] : []),
      "--run-dir",
      path.resolve(runDir),
      "--genre",
      "essay"
    ];
    const result = await this.run(
      args,
      runDir,
      signal
    );
    if (result.exitCode !== 0) {
      throw invalid("Python prepare step failed");
    }

    try {
      const raw = await readFile(path.join(runDir, "chunk_manifest.json"), "utf8");
      return parseManifest(JSON.parse(raw));
    } catch (error) {
      if (error instanceof EngineError) throw error;
      throw invalid("Unable to read chunk manifest", error);
    }
  }

  // A chunk gate sees the whole prepared source too: footnote markers live in body
  // chunks while their definitions sit in the last one, and the chunk verdict must
  // agree with the full-document gate. The prepared source sits next to the chunks.
  private async documentContext(beforePath: string): Promise<string | undefined> {
    const dir = path.dirname(path.resolve(beforePath));
    try {
      const manifest = JSON.parse(await readFile(path.join(dir, "chunk_manifest.json"), "utf8")) as unknown;
      const source = path.join(dir, safeLeaf(record(manifest, "manifest").source_file, "source_file"));
      if (source === path.resolve(beforePath)) return undefined;
      await readFile(source);
      return source;
    } catch {
      return undefined;
    }
  }

  async verify(
    beforePath: string,
    afterPath: string,
    signal: AbortSignal,
    attempt: 1 | 2 = 1
  ): Promise<GateResult> {
    const context = await this.documentContext(beforePath);
    const result = await this.run(
      [
        path.resolve(this.vendorRoot, "../../engine_runtime/workflow.py"),
        "--vendor-root", this.vendorRoot,
        "--attempt", String(attempt),
        "--before",
        path.resolve(beforePath),
        "--after",
        path.resolve(afterPath),
        ...(context ? ["--context", context] : [])
      ],
      path.dirname(beforePath),
      signal
    );
    if (![0, 1, 2, 3].includes(result.exitCode)) {
      throw invalid("Unexpected gate exit code");
    }
    const exitCode = result.exitCode as 0 | 1 | 2 | 3;
    const statuses = ["ok", "warn", "abort", "error"] as const;
    const report = parseGateReport(result.stdout);
    const gate = record(report.gate, "gate report.gate");
    if (integer(gate.exit_code, "gate report.gate.exit_code") !== exitCode) {
      throw invalid("Gate report exit code mismatch");
    }
    return {
      status: statuses[exitCode],
      exitCode,
      gateCodes: [GATE_CODES[exitCode]],
      ...(parseGateReasonMetadata(report.warningReasons) ? { warningReasons: parseGateReasonMetadata(report.warningReasons)! } : {}),
      ...(Array.isArray(report.hardFailures) && report.hardFailures.length <= 100 &&
        report.hardFailures.every(code => typeof code === 'string' && code.length <= 100)
        ? { hardFailures: report.hardFailures as string[] } : {}),
      ...(Array.isArray(report.shadowFailures) && report.shadowFailures.length <= 100 &&
        report.shadowFailures.every(code => typeof code === 'string' && /^[a-z_]{1,60}$/.test(code))
        ? { shadowFailures: report.shadowFailures as string[] } : {}),
      ...(typeof report.policy === "string" ? { policy: report.policy as GateResult["policy"] } : {})
    };
  }

  async restore(
    beforePath: string,
    afterPath: string,
    signal: AbortSignal
  ): Promise<RestoreReport> {
    const before = path.resolve(beforePath);
    const after = path.resolve(afterPath);
    const cwd = path.dirname(before);
    const inPlace = [
      "--before",
      before,
      "--after",
      after,
      "--out",
      after,
      "--json"
    ];

    const modality = await this.run(
      [this.script("restore_modality.py"), ...inPlace],
      cwd,
      signal
    );
    if (modality.exitCode !== 0) {
      throw invalid("Python modality restore failed");
    }
    const modalityReport = parseJsonReport(modality.stderr, "modality restore");

    const commas = await this.run(
      [this.script("strip_injected_commas.py"), ...inPlace],
      cwd,
      signal
    );
    if (commas.exitCode !== 0) {
      throw invalid("Python comma strip failed");
    }
    const commaReport = parseJsonReport(commas.stderr, "comma strip");

    const particles = await this.run(
      [path.resolve(this.vendorRoot, "../../engine_runtime/super_sejong_josa.py"), ...inPlace],
      cwd,
      signal
    );
    if (particles.exitCode !== 0) {
      throw invalid("Python particle repair failed");
    }
    const particleReport = parseJsonReport(particles.stderr, "particle repair");

    return {
      restoredSentences: integer(
        modalityReport.restored,
        "modality restore report.restored"
      ),
      skippedSentences: integer(
        modalityReport.skipped,
        "modality restore report.skipped"
      ),
      removedCommas: integer(
        commaReport.commas_removed,
        "comma strip report.commas_removed"
      ),
      repairedParticles: integer(particleReport.repaired, "particle repair report.repaired")
    };
  }

  async reassemble(runDir: string, signal: AbortSignal): Promise<string> {
    const result = await this.run(
      [
        this.script("reassemble_chunks.py"),
        "--run-dir",
        path.resolve(runDir),
        "--output",
        "03_reassembled.md",
        "--report",
        "03_reassembly_report.json",
        "--strict"
      ],
      runDir,
      signal
    );
    if (result.exitCode !== 0) {
      throw invalid("Python reassembly failed validation");
    }
    const outputPath = path.join(runDir, "03_reassembled.md");
    try {
      await readFile(outputPath);
    } catch (error) {
      throw invalid("Reassembled output is missing", error);
    }
    return outputPath;
  }
}
