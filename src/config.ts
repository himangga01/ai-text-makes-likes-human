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
  readonly pythonCommand: string;
}

export function loadConfig(
  env: NodeJS.ProcessEnv,
  projectRoot: string
): AppConfig {
  const port = Number(env.PORT ?? 3210);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("PORT must be an integer from 1 to 65535");
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
    pythonCommand: env.PYTHON_COMMAND ?? "python"
  });
}
