import { readFile } from "node:fs/promises";
import path from "node:path";
import type { AppConfig } from "../config.js";
import type { CommandRunner } from "../process/command-runner.js";
import { engineVersionPath, runPreflight, type PreflightReport } from "../process/preflight.js";
import { HumanizeEngine } from "../engine/humanize-engine.js";
import { SejongEngine } from "../engine/sejong/engine.js";
import { SejongPython } from "../engine/sejong/python-adapter.js";
import { PythonEngine } from "../engine/python-engine.js";
import { CodexRunner } from "../engine/codex-runner.js";
import { ClaudeRunner } from "../engine/claude-runner.js";
import { CodexSemaphore } from "../engine/codex-semaphore.js";
import { CLAUDE_MODEL, CLAUDE_REASONING_EFFORT } from "../engine/model-policy.js";
import { TransformQueue } from "../queue/transform-queue.js";
import { resolveCli } from "./cli-path.js";
import { DocumentEngine } from '../documents/document-engine.js';

/** The engine that produces the delivered text: legacy (default) or Super Sejong v2 (SUPER_SEJONG_ENGINE=v2). */
export type TextEngine = HumanizeEngine | SejongEngine;

export interface ProductionRuntime {
  refreshHealth: () => Promise<PreflightReport>;
  documentEngine: DocumentEngine;
  engine: TextEngine;
  claudeEngine?: TextEngine;
  queue: TransformQueue;
  preflight: PreflightReport;
}

export async function createProductionRuntime(
  config: AppConfig,
  runner: CommandRunner
): Promise<ProductionRuntime> {
  config = { ...config, codexCommand: resolveCli("codex", config.codexCommand), claudeCommand: resolveCli("claude", config.claudeCommand) };
  // The engine is chosen once at start-up (config.engine); preflight checks that engine's own version file.
  const engineEnv = { SUPER_SEJONG_ENGINE: config.engine };
  const engineVersion = await readFile(
    engineVersionPath(config, engineEnv),
    "utf8"
  );
  const preflight = await runPreflight(config, runner, engineVersion, engineEnv);
  let refreshing: Promise<PreflightReport> | undefined;
  let checkedAt = Date.now();
  const refreshHealth = () => {
    if (refreshing) return refreshing;
    if (Date.now() - checkedAt < 3000) return Promise.resolve(preflight);
    refreshing = runPreflight(config, runner, engineVersion, engineEnv).then(next => {
      Object.assign(preflight, next, { providers: next.providers, message: next.message, errorCode: next.errorCode });
      checkedAt = Date.now(); return preflight;
    }).finally(() => { refreshing = undefined; });
    return refreshing;
  };
  if (config.engine === "v2") return createSejongRuntime(config, runner, preflight, refreshHealth);
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
        reasoningEffort: CLAUDE_REASONING_EFFORT
      });
  return {
    refreshHealth,
    documentEngine: new DocumentEngine(config, runner),
    engine: new HumanizeEngine({
      python,
      codex,
      chunkConcurrency: config.chunkConcurrency
    }),
    claudeEngine,
    queue: new TransformQueue({
      maxActive: config.maxActiveJobs,
      maxAccepted: config.maxAcceptedJobs
    }),
    preflight
  };
}

/** Super Sejong v2 wiring: the same writer CLIs, given ready prompts (runPrompt) and the v2 response schema;
 * no vendor rulebook is read. */
function createSejongRuntime(
  config: AppConfig,
  runner: CommandRunner,
  preflight: PreflightReport,
  refreshHealth: () => Promise<PreflightReport>
): ProductionRuntime {
  // SejongPython takes the engine_runtime directory (sejong_cli.py lives beside the sejong package).
  const python = new SejongPython({
    pythonCommand: config.pythonCommand,
    engineRoot: path.dirname(config.engineRoot),
    runner
  });
  const schemaPath = path.join(config.projectRoot, "src", "engine", "sejong", "response-schema.json");
  const codex = new CodexRunner({
    codexCommand: config.codexCommand,
    schemaPath,
    timeoutMs: config.chunkTimeoutMs,
    runner,
    permitPool: new CodexSemaphore(2)
  });
  const claude = new ClaudeRunner({
    claudeCommand: config.claudeCommand,
    schemaPath,
    timeoutMs: config.chunkTimeoutMs,
    runner,
    permitPool: new CodexSemaphore(2)
  });
  return {
    refreshHealth,
    documentEngine: new DocumentEngine(config, runner),
    engine: new SejongEngine({ python, writer: codex, schemaPath, chunkConcurrency: config.chunkConcurrency }),
    claudeEngine: new SejongEngine({
      python,
      writer: claude,
      schemaPath,
      chunkConcurrency: config.chunkConcurrency,
      model: CLAUDE_MODEL,
      reasoningEffort: CLAUDE_REASONING_EFFORT
    }),
    queue: new TransformQueue({
      maxActive: config.maxActiveJobs,
      maxAccepted: config.maxAcceptedJobs
    }),
    preflight
  };
}
