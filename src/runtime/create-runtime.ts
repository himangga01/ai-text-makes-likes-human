import { readFile } from "node:fs/promises";
import path from "node:path";
import type { AppConfig } from "../config.js";
import type { CommandRunner } from "../process/command-runner.js";
import { runPreflight, type PreflightReport } from "../process/preflight.js";
import { HumanizeEngine } from "../engine/humanize-engine.js";
import { PythonEngine } from "../engine/python-engine.js";
import { CodexRunner } from "../engine/codex-runner.js";
import { ClaudeRunner } from "../engine/claude-runner.js";
import { CodexSemaphore } from "../engine/codex-semaphore.js";
import { CLAUDE_MODEL, CLAUDE_REASONING_EFFORT } from "../engine/model-policy.js";
import { SejongPython } from "../engine/sejong/python-adapter.js";
import { TransformQueue } from "../queue/transform-queue.js";
import { resolveCli } from "./cli-path.js";
import { DocumentEngine } from '../documents/document-engine.js';

export interface ProductionRuntime {
  refreshHealth: () => Promise<PreflightReport>;
  documentEngine: DocumentEngine;
  engine: HumanizeEngine;
  claudeEngine?: HumanizeEngine;
  queue: TransformQueue;
  preflight: PreflightReport;
}

export async function createProductionRuntime(
  config: AppConfig,
  runner: CommandRunner
): Promise<ProductionRuntime> {
  config = { ...config, codexCommand: resolveCli("codex", config.codexCommand), claudeCommand: resolveCli("claude", config.claudeCommand) };
  const engineVersion = await readFile(
    path.join(config.vendorRoot, "ENGINE_VERSION"),
    "utf8"
  );
  const preflight = await runPreflight(config, runner, engineVersion);
  let refreshing: Promise<PreflightReport> | undefined;
  let checkedAt = Date.now();
  const refreshHealth = () => {
    if (refreshing) return refreshing;
    if (Date.now() - checkedAt < 3000) return Promise.resolve(preflight);
    refreshing = runPreflight(config, runner, engineVersion).then(next => {
      Object.assign(preflight, next, { providers: next.providers, message: next.message, errorCode: next.errorCode });
      checkedAt = Date.now(); return preflight;
    }).finally(() => { refreshing = undefined; });
    return refreshing;
  };
  const python = new PythonEngine({
    pythonCommand: config.pythonCommand,
    vendorRoot: config.vendorRoot,
    runner,
    autoRoute: config.autoRoute
  });
  const quickRulesPath = path.join(
    config.vendorRoot,
    "skills",
    "humanize-korean",
    "references",
    "quick-rules.md"
  );
  // Inert unless SUPER_SEJONG_V2_SHADOW=1: the legacy engines then look at each job through v2 on the side (no model call).
  const v2Shadow = new SejongPython({ pythonCommand: config.pythonCommand, engineRoot: path.join(config.projectRoot, "engine_runtime"), runner });
  const codexSemaphore = new CodexSemaphore(2);
  const codex = new CodexRunner({
    codexCommand: config.codexCommand,
    schemaPath: path.join(config.projectRoot, "src", "engine", "output-schema.json"),
    quickRulesPath,
    timeoutMs: config.chunkTimeoutMs,
    runner,
    permitPool: codexSemaphore
  });
  const claudeSemaphore = new CodexSemaphore(2);
  const claudeEngine = new HumanizeEngine({
        python,
        codex: new ClaudeRunner({
          claudeCommand: config.claudeCommand,
          schemaPath: path.join(
            config.projectRoot,
            "src",
            "engine",
            "output-schema.json"
          ),
          quickRulesPath,
          timeoutMs: config.chunkTimeoutMs,
          runner,
          permitPool: claudeSemaphore
        }),
        chunkConcurrency: config.chunkConcurrency,
        model: CLAUDE_MODEL,
        reasoningEffort: CLAUDE_REASONING_EFFORT,
        v2Shadow
      });
  return {
    refreshHealth,
    documentEngine: new DocumentEngine(config, runner),
    engine: new HumanizeEngine({
      python,
      codex,
      chunkConcurrency: config.chunkConcurrency,
      v2Shadow
    }),
    claudeEngine,
    queue: new TransformQueue({
      maxActive: config.maxActiveJobs,
      maxAccepted: config.maxAcceptedJobs
    }),
    preflight
  };
}
