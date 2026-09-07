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
import { TransformQueue } from "../queue/transform-queue.js";
import { resolveCli } from "./cli-path.js";

export interface ProductionRuntime {
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
  const codexSemaphore = new CodexSemaphore(2);
  const codex = new CodexRunner({
    codexCommand: config.codexCommand,
    schemaPath: path.join(config.projectRoot, "src", "engine", "output-schema.json"),
    quickRulesPath,
    timeoutMs: config.chunkTimeoutMs,
    runner,
    permitPool: codexSemaphore
  });
  const claudeAvailable = preflight.providers?.claude.ready === true;
  const claudeSemaphore = new CodexSemaphore(2);
  const claudeEngine = claudeAvailable
    ? new HumanizeEngine({
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
        maxObservedCodexConcurrency: () => claudeSemaphore.maxObserved
      })
    : undefined;
  return {
    engine: new HumanizeEngine({
      python,
      codex,
      chunkConcurrency: config.chunkConcurrency,
      maxObservedCodexConcurrency: () => codexSemaphore.maxObserved
    }),
    claudeEngine,
    queue: new TransformQueue({
      maxActive: config.maxActiveJobs,
      maxAccepted: config.maxAcceptedJobs
    }),
    preflight
  };
}
