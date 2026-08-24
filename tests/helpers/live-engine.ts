import { randomUUID } from "node:crypto";
import { readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { loadConfig } from "../../src/config.js";
import type { EventSink } from "../../src/contracts.js";
import { CodexRunner } from "../../src/engine/codex-runner.js";
import { CodexSemaphore } from "../../src/engine/codex-semaphore.js";
import type { TransformDiagnostics } from "../../src/engine/diagnostics.js";
import { HumanizeEngine } from "../../src/engine/humanize-engine.js";
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

const DEFAULT_OPTIONS: LiveEngineOptions = {
  autoRoute: true,
  chunkConcurrency: 1
};

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

  const python = new PythonEngine({
    pythonCommand: config.pythonCommand,
    vendorRoot: config.vendorRoot,
    runner,
    autoRoute: options.autoRoute
  });
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
    python,
    codex,
    chunkConcurrency: options.chunkConcurrency,
    maxObservedCodexConcurrency: () => codexSemaphore.maxObserved
  });

  const workspace = await JobWorkspace.create(
    config.runtimeRoot,
    `live-${randomUUID()}`
  );
  let resultText = "";
  let diagnostics: TransformDiagnostics | undefined;
  try {
    await writeFile(workspace.path("01_input.txt"), source, "utf8");
    const transformed = await engine.transform({
      jobId: workspace.jobId,
      workspace,
      signal: new AbortController().signal,
      onEvent: options.onEvent ?? (() => undefined)
    });
    resultText = await readFile(transformed.finalPath, "utf8");
    diagnostics = transformed.diagnostics;
  } finally {
    await workspace.cleanup();
  }

  const runtimeChildren = (await readdir(config.runtimeRoot)).filter(
    name => name !== ".gitkeep"
  );
  if (!diagnostics) throw new Error("Live transform produced no diagnostics");
  return { result: resultText, diagnostics, runtimeChildren };
}
