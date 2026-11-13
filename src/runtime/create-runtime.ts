import { mkdir, readFile } from "node:fs/promises";
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
import { CLAUDE_MODEL, CLAUDE_REASONING_EFFORT, type EngineChoice } from "../engine/model-policy.js";
import { TransformQueue } from "../queue/transform-queue.js";
import { resolveCli } from "./cli-path.js";
import { DocumentEngine } from '../documents/document-engine.js';
import { ModelCatalogService } from './model-catalog.js';
import { discoverModels, ModelDiscoveryError } from './model-discovery.js';

/** The engine that produces the delivered text: legacy (default) or Super Sejong v2 (SUPER_SEJONG_ENGINE=v2). */
export type TextEngine = HumanizeEngine | SejongEngine;

export interface ProductionRuntime {
  refreshHealth: () => Promise<PreflightReport>;
  documentEngine: DocumentEngine;
  engine: TextEngine;
  claudeEngine?: TextEngine;
  queue: TransformQueue;
  preflight: PreflightReport;
  modelCatalog: ModelCatalogService;
}

// One catalog per process: the model lists are process-wide and the desktop worker builds a runtime per request.
// A later runtime only points discovery at its own CLI paths.
let probeTarget: { commands: Record<EngineChoice, string>; cwd: string } | undefined;
let sharedCatalog: ModelCatalogService | undefined;
function modelCatalogFor(config: AppConfig): ModelCatalogService {
  // An empty private directory: a CLI started there reads no project instructions or settings.
  probeTarget = { commands: { codex: config.codexCommand, claude: config.claudeCommand }, cwd: path.join(config.runtimeRoot, "model-probe") };
  return sharedCatalog ??= new ModelCatalogService({ discover: async engine => {
    const { commands, cwd } = probeTarget!;
    try { await mkdir(cwd, { recursive: true }); } catch { throw new ModelDiscoveryError("spawn", "Model probe directory is unavailable"); }
    return discoverModels(engine, commands[engine], { cwd });
  } });
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
  const modelCatalog = modelCatalogFor(config);
  // Not awaited: start-up does not wait on the CLIs, and a provider that is not ready is skipped until it is.
  const probeModels = (report: PreflightReport) => { if (report.providers) modelCatalog.refreshIfStale(report.providers); };
  probeModels(preflight);
  let refreshing: Promise<PreflightReport> | undefined;
  let checkedAt = Date.now();
  const refreshHealth = () => {
    if (refreshing) return refreshing;
    if (Date.now() - checkedAt < 3000) return Promise.resolve(preflight);
    refreshing = runPreflight(config, runner, engineVersion, engineEnv).then(next => {
      Object.assign(preflight, next, { providers: next.providers, message: next.message, errorCode: next.errorCode });
      checkedAt = Date.now(); probeModels(preflight); return preflight;
    }).finally(() => { refreshing = undefined; });
    return refreshing;
  };
  if (config.engine === "v2") return createSejongRuntime(config, runner, preflight, refreshHealth, modelCatalog);
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
  const v2Shadow = new SejongPython({ pythonCommand: config.pythonCommand, engineRoot: path.dirname(config.engineRoot), runner });
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
    preflight,
    modelCatalog
  };
}

/** Super Sejong v2 wiring: the same writer CLIs, given ready prompts (runPrompt) and the v2 response schema;
 * no vendor rulebook is read. */
function createSejongRuntime(
  config: AppConfig,
  runner: CommandRunner,
  preflight: PreflightReport,
  refreshHealth: () => Promise<PreflightReport>,
  modelCatalog: ModelCatalogService
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
    preflight,
    modelCatalog
  };
}
