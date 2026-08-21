import { randomUUID } from "node:crypto";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { createProductionRuntime } from "../../src/app.js";
import { loadConfig } from "../../src/config.js";
import { JobWorkspace } from "../../src/engine/workspace.js";
import { SpawnCommandRunner } from "../../src/process/command-runner.js";

export async function runLiveEngineFixture(
  source: string
): Promise<{ result: string; runtimeChildren: string[] }> {
  const config = loadConfig(process.env, process.cwd());
  const runtime = await createProductionRuntime(
    config,
    new SpawnCommandRunner()
  );
  if (!runtime.preflight.ready) {
    throw new Error(runtime.preflight.message ?? "Live engine is not ready");
  }

  const workspace = await JobWorkspace.create(
    config.runtimeRoot,
    `live-${randomUUID()}`
  );
  let resultText = "";
  try {
    await writeFile(workspace.path("01_input.txt"), source, "utf8");
    const transformed = await runtime.engine.transform({
      jobId: workspace.jobId,
      workspace,
      signal: new AbortController().signal,
      onEvent: () => undefined
    });
    resultText = await readFile(transformed.finalPath, "utf8");
  } finally {
    await workspace.cleanup();
  }

  const runtimeChildren = (await readdir(config.runtimeRoot)).filter(
    name => name !== ".gitkeep"
  );
  return { result: resultText, runtimeChildren };
}
