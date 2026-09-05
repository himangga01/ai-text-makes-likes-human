import path from "node:path";

export interface AppConfig {
  readonly projectRoot: string;
  readonly host: string;
  readonly port: number;
  readonly maxAcceptedJobs: number;
  readonly maxActiveJobs: number;
  readonly chunkTimeoutMs: number;
  readonly minFreeBytes: number;
  readonly runtimeRoot: string;
  readonly vendorRoot: string;
  readonly codexCommand: string;
  readonly claudeCommand: string;
  readonly pythonCommand: string;
  readonly autoRoute: boolean;
  readonly chunkConcurrency: 1 | 2;
}

export function loadConfig(
  env: NodeJS.ProcessEnv,
  projectRoot: string
): AppConfig {
  const port = Number(env.PORT ?? 7882);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("PORT must be an integer from 1 to 65535");
  }

  const concurrency = Number(env.CODEX_CHUNK_CONCURRENCY ?? 1);
  if (concurrency !== 1 && concurrency !== 2) {
    throw new Error("CODEX_CHUNK_CONCURRENCY must be 1 or 2");
  }

  return Object.freeze({
    projectRoot,
    host: env.HOST ?? "0.0.0.0",
    port,
    maxAcceptedJobs: 3,
    maxActiveJobs: 1,
    chunkTimeoutMs: 10 * 60 * 1000,
    minFreeBytes: 1024 ** 3,
    runtimeRoot: path.join(projectRoot, "runtime", "jobs"),
    vendorRoot: path.join(projectRoot, "vendor", "humanize-engine"),
    codexCommand: env.CODEX_COMMAND ?? "codex",
    claudeCommand: env.CLAUDE_COMMAND ?? "claude",
    pythonCommand: env.PYTHON_COMMAND ?? "python",
    autoRoute: env.HUMANIZE_AUTO_ROUTE !== "0",
    chunkConcurrency: concurrency
  });
}
