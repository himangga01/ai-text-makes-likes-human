import { fileURLToPath } from "node:url";
import { mkdir, readdir, rm } from "node:fs/promises";
import path from "node:path";
import type { Server } from "node:http";
import { createApp, createProductionRuntime } from "./app.js";
import { loadConfig } from "./config.js";
import { listLanUrls } from "./network/lan-addresses.js";
import { SpawnCommandRunner } from "./process/command-runner.js";

const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  ".."
);

async function clearStaleJobs(runtimeRoot: string): Promise<void> {
  await mkdir(runtimeRoot, { recursive: true });
  for (const entry of await readdir(runtimeRoot, { withFileTypes: true })) {
    if (entry.name === ".gitkeep") continue;
    await rm(path.join(runtimeRoot, entry.name), { recursive: true, force: true });
  }
}

async function closeServer(server: Server): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    server.close(error => (error ? reject(error) : resolve()));
  });
}

async function main(): Promise<void> {
  const config = loadConfig(process.env, projectRoot);
  await clearStaleJobs(config.runtimeRoot);
  const runtime = await createProductionRuntime(config, new SpawnCommandRunner());
  const app = createApp({ config, ...runtime });
  const server = app.listen(config.port, config.host, () => {
    console.log(`로컬: http://localhost:${config.port}`);
    for (const url of listLanUrls(config.port)) console.log(`와이파이: ${url}`);
    if (!runtime.preflight.ready) console.log(runtime.preflight.message);
  });

  let shuttingDown = false;
  const shutdown = async (): Promise<void> => {
    if (shuttingDown) return;
    shuttingDown = true;
    const forceExit = setTimeout(() => process.exit(1), 15_000);
    forceExit.unref();
    try {
      await closeServer(server);
      await runtime.queue.shutdown();
      await clearStaleJobs(config.runtimeRoot);
      clearTimeout(forceExit);
      process.exit(0);
    } catch (error) {
      console.error(error);
      process.exit(1);
    }
  };
  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);
}

main().catch(error => {
  console.error(error);
  process.exit(1);
});
