import { randomUUID } from "node:crypto";
import { readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { loadConfig } from "../../src/config.js";
import type {
  EventSink,
  PublicErrorCode
} from "../../src/contracts.js";
import { CodexRunner } from "../../src/engine/codex-runner.js";
import { CodexSemaphore } from "../../src/engine/codex-semaphore.js";
import type {
  GateCode,
  TransformDiagnostics
} from "../../src/engine/diagnostics.js";
import { EngineError } from "../../src/engine/errors.js";
import {
  HumanizeEngine,
  type HumanizeRequest,
  type HumanizeResult,
  type PythonAdapter
} from "../../src/engine/humanize-engine.js";
import { PythonEngine } from "../../src/engine/python-engine.js";
import { JobWorkspace } from "../../src/engine/workspace.js";
import { SpawnCommandRunner } from "../../src/process/command-runner.js";
import { runPreflight } from "../../src/process/preflight.js";

export interface LiveEngineOptions {
  autoRoute: boolean;
  chunkConcurrency: 1 | 2;
  onEvent?: EventSink;
}

export interface LiveEngineResult {
  result: string;
  diagnostics: TransformDiagnostics;
  runtimeChildren: string[];
}

export interface LiveEngineFailure {
  publicCode: PublicErrorCode;
  gateCodes: readonly GateCode[];
  elapsedMs: number;
  cleanup: boolean;
}

interface LiveEngineService {
  transform(request: HumanizeRequest): Promise<HumanizeResult>;
}

export interface LiveEngineExecutionOptions {
  runtimeRoot: string;
  engine: LiveEngineService;
  observedGateCodes(): readonly unknown[];
  onEvent?: EventSink;
  now?: () => number;
}

const GATE_CODE_ALLOWLIST = new Set<GateCode>([
  "GATE_OK",
  "GATE_WARN",
  "GATE_ABORT",
  "GATE_ERROR"
]);

const PUBLIC_CODE_ALLOWLIST = new Set<PublicErrorCode>([
  "EMPTY_INPUT",
  "QUEUE_FULL",
  "ENGINE_UNAVAILABLE",
  "ENGINE_TIMEOUT",
  "ENGINE_OUTPUT_INVALID",
  "VALIDATION_FAILED",
  "INSUFFICIENT_DISK",
  "CLIENT_ABORTED",
  "INTERNAL_ERROR"
]);

const DEFAULT_OPTIONS: LiveEngineOptions = {
  autoRoute: true,
  chunkConcurrency: 1
};

function gateCodes(values: readonly unknown[]): GateCode[] {
  return values.filter(
    (value): value is GateCode =>
      typeof value === "string" && GATE_CODE_ALLOWLIST.has(value as GateCode)
  );
}

function publicCode(error: unknown): PublicErrorCode {
  if (
    error instanceof EngineError &&
    PUBLIC_CODE_ALLOWLIST.has(error.publicCode)
  ) {
    return error.publicCode;
  }
  return "INTERNAL_ERROR";
}

function liveFailure(
  error: unknown,
  observedGateCodes: readonly unknown[],
  elapsedMs: number,
  cleanup: boolean
): LiveEngineFailure {
  return Object.freeze({
    publicCode: publicCode(error),
    gateCodes: Object.freeze(gateCodes(observedGateCodes)),
    elapsedMs: Number.isFinite(elapsedMs) ? Math.max(0, elapsedMs) : 0,
    cleanup
  });
}

export function isLiveEngineFailure(value: unknown): value is LiveEngineFailure {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const failure = value as Record<string, unknown>;
  return (
    Object.keys(failure).length === 4 &&
    typeof failure.publicCode === "string" &&
    PUBLIC_CODE_ALLOWLIST.has(failure.publicCode as PublicErrorCode) &&
    Array.isArray(failure.gateCodes) &&
    failure.gateCodes.every(code =>
      GATE_CODE_ALLOWLIST.has(code as GateCode)
    ) &&
    typeof failure.elapsedMs === "number" &&
    Number.isFinite(failure.elapsedMs) &&
    typeof failure.cleanup === "boolean"
  );
}

export function observePythonGates(python: PythonAdapter): {
  python: PythonAdapter;
  gateCodes(): readonly GateCode[];
} {
  const observed: GateCode[] = [];
  return {
    python: {
      prepare: (runDir, signal) => python.prepare(runDir, signal),
      restore: (beforePath, afterPath, signal) =>
        python.restore(beforePath, afterPath, signal),
      reassemble: (runDir, signal) => python.reassemble(runDir, signal),
      async verify(beforePath, afterPath, signal) {
        const result = await python.verify(beforePath, afterPath, signal);
        observed.push(...gateCodes(result.gateCodes));
        return result;
      }
    },
    gateCodes: () => [...observed]
  };
}

async function runtimeChildren(runtimeRoot: string): Promise<string[] | null> {
  try {
    return (await readdir(runtimeRoot)).filter(name => name !== ".gitkeep");
  } catch {
    return null;
  }
}

export async function executeLiveEngineFixture(
  source: string,
  options: LiveEngineExecutionOptions
): Promise<LiveEngineResult> {
  const now = options.now ?? Date.now;
  const startedAt = now();
  let workspace: JobWorkspace | undefined;
  let resultText = "";
  let diagnostics: TransformDiagnostics | undefined;
  let failed = false;
  let caught: unknown;
  let cleanupSucceeded = true;

  try {
    workspace = await JobWorkspace.create(
      options.runtimeRoot,
      `live-${randomUUID()}`
    );
    await writeFile(workspace.path("01_input.txt"), source, "utf8");
    const transformed = await options.engine.transform({
      jobId: workspace.jobId,
      workspace,
      signal: new AbortController().signal,
      onEvent: options.onEvent ?? (() => undefined)
    });
    resultText = await readFile(transformed.finalPath, "utf8");
    diagnostics = transformed.diagnostics;
  } catch (error) {
    failed = true;
    caught = error;
  } finally {
    try {
      await workspace?.cleanup();
    } catch {
      cleanupSucceeded = false;
    }
  }

  const children = await runtimeChildren(options.runtimeRoot);
  const cleanup = cleanupSucceeded && children !== null && children.length === 0;
  const elapsedMs = now() - startedAt;
  if (failed || !diagnostics) {
    throw liveFailure(
      caught,
      options.observedGateCodes(),
      elapsedMs,
      cleanup
    );
  }
  if (!cleanup) {
    throw liveFailure(
      new EngineError("INTERNAL_ERROR", false, "Live cleanup failed"),
      options.observedGateCodes(),
      elapsedMs,
      false
    );
  }
  return { result: resultText, diagnostics, runtimeChildren: children };
}

export async function runLiveEngineFixture(
  source: string,
  options: LiveEngineOptions = DEFAULT_OPTIONS
): Promise<LiveEngineResult> {
  const config = loadConfig(process.env, process.cwd());
  const runner = new SpawnCommandRunner();
  const engineVersion = await readFile(
    path.join(config.vendorRoot, "ENGINE_VERSION"),
    "utf8"
  );
  const preflight = await runPreflight(config, runner, engineVersion);
  if (!preflight.ready) {
    throw new Error(preflight.message ?? "Live engine is not ready");
  }

  const observedPython = observePythonGates(new PythonEngine({
    pythonCommand: config.pythonCommand,
    vendorRoot: config.vendorRoot,
    runner,
    autoRoute: options.autoRoute
  }));
  const codexSemaphore = new CodexSemaphore(2);
  const codex = new CodexRunner({
    codexCommand: config.codexCommand,
    schemaPath: path.join(config.projectRoot, "src", "engine", "output-schema.json"),
    quickRulesPath: path.join(
      config.vendorRoot,
      "skills",
      "humanize-korean",
      "references",
      "quick-rules.md"
    ),
    timeoutMs: config.chunkTimeoutMs,
    runner,
    permitPool: codexSemaphore
  });
  const engine = new HumanizeEngine({
    python: observedPython.python,
    codex,
    chunkConcurrency: options.chunkConcurrency,
    maxObservedCodexConcurrency: () => codexSemaphore.maxObserved
  });
  return executeLiveEngineFixture(source, {
    runtimeRoot: config.runtimeRoot,
    engine,
    observedGateCodes: observedPython.gateCodes,
    onEvent: options.onEvent
  });
}
