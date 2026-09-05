import { createServer, type Server } from "node:http";
import { spawn, type ChildProcess } from "node:child_process";
import {
  mkdtemp,
  mkdir,
  readFile,
  rm,
  utimes,
  writeFile
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  HermesServiceSupervisor,
  NodeServicePlatform,
  type ServiceHealth,
  type ServicePlatform
} from "../../src/ops/hermes-service.js";

const temporaryRoots: string[] = [];
const servers: Server[] = [];
const children: ChildProcess[] = [];

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void;
  const promise = new Promise<void>(done => {
    resolve = done;
  });
  return { promise, resolve };
}

async function makeRuntimeRoot(): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "hermes-service-"));
  temporaryRoots.push(root);
  const runtimeRoot = path.join(root, "runtime");
  await mkdir(runtimeRoot, { recursive: true });
  return runtimeRoot;
}

async function writeState(
  runtimeRoot: string,
  desired: "running" | "stopped",
  consecutiveFailures = 0
): Promise<void> {
  await writeFile(
    path.join(runtimeRoot, "hermes-service-state.json"),
    JSON.stringify({ desired, consecutiveFailures }),
    "utf8"
  );
}

class FakeServicePlatform implements ServicePlatform {
  readonly pid = 4242;
  readonly identity = "fake-start-time fake-portal-command";
  running = false;
  responding = false;
  spawnSucceeds = true;
  healthStatus: "ready" | "degraded" = "ready";
  starts = 0;
  stops = 0;
  stopEntered?: ReturnType<typeof deferred>;
  stopRelease?: ReturnType<typeof deferred>;

  constructor(private readonly runtimeRoot: string) {}

  async getProcessIdentity(pid: number): Promise<string | null> {
    return pid === this.pid && this.running ? this.identity : null;
  }

  async spawnService(): Promise<void> {
    this.starts += 1;
    if (!this.spawnSucceeds) return;
    this.running = true;
    this.responding = true;
    await writeFile(
      path.join(this.runtimeRoot, "server.lock"),
      `${this.pid}\n`,
      "utf8"
    );
  }

  async stopProcess(pid: number, identity: string): Promise<void> {
    if (pid !== this.pid || identity !== this.identity) return;
    this.stopEntered?.resolve();
    await this.stopRelease?.promise;
    this.stops += 1;
    this.running = false;
    this.responding = false;
  }

  async getHealth(): Promise<ServiceHealth | null> {
    if (!this.running || !this.responding) return null;
    return {
      status: this.healthStatus,
      pid: this.pid,
      activeJobs: 0,
      queuedJobs: 0
    };
  }

  sleep(): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, 0));
  }
}

afterEach(async () => {
  for (const child of children.splice(0)) {
    if (child.pid !== undefined) child.kill("SIGKILL");
  }
  await Promise.all(
    servers.splice(0).map(
      server =>
        new Promise<void>((resolve, reject) =>
          server.close(error => (error ? reject(error) : resolve()))
        )
    )
  );
  await Promise.all(
    temporaryRoots.splice(0).map(root => rm(root, { recursive: true, force: true }))
  );
});

describe("HermesServiceSupervisor", () => {
  it("adopts an already-running portal without spawning a duplicate", async () => {
    const runtimeRoot = await makeRuntimeRoot();
    const platform = new FakeServicePlatform(runtimeRoot);
    platform.running = true;
    platform.responding = true;
    await writeFile(
      path.join(runtimeRoot, "server.lock"),
      `${platform.pid}\n`,
      "utf8"
    );
    const supervisor = new HermesServiceSupervisor({ runtimeRoot }, platform);

    const result = await supervisor.start();

    expect(result.outcome).toBe("already-running");
    expect(platform.starts).toBe(0);
    expect(
      JSON.parse(
        await readFile(path.join(runtimeRoot, "hermes-service-state.json"), "utf8")
      )
    ).toMatchObject({ desired: "running" });
  });

  it("preserves an explicit stop across watchdog and gateway reconciliation", async () => {
    const runtimeRoot = await makeRuntimeRoot();
    const platform = new FakeServicePlatform(runtimeRoot);
    const supervisor = new HermesServiceSupervisor({ runtimeRoot }, platform);

    await supervisor.stop();

    expect((await supervisor.watch()).outcome).toBe("intentionally-stopped");
    const reconciled = await supervisor.reconcile();
    expect(reconciled.outcome).toBe("intentionally-stopped");
    expect(reconciled.desired).toBe("stopped");
    expect((await supervisor.status()).outcome).toBe("intentionally-stopped");
    expect(platform.starts).toBe(0);
  });

  it.each(["reconcile", "watch"] as const)(
    "%s enforces a persisted stopped state against a still-running portal",
    async operation => {
      const runtimeRoot = await makeRuntimeRoot();
      const platform = new FakeServicePlatform(runtimeRoot);
      platform.running = true;
      platform.responding = true;
      await writeFile(
        path.join(runtimeRoot, "server.lock"),
        `${platform.pid}\n`,
        "utf8"
      );
      await writeState(runtimeRoot, "stopped");
      const supervisor = new HermesServiceSupervisor({ runtimeRoot }, platform);

      const result = await supervisor[operation]();

      expect(result.outcome).toBe("stopped");
      expect(result.desired).toBe("stopped");
      expect(platform.running).toBe(false);
      expect(platform.stops).toBe(1);
    }
  );

  it("reclaims an orphaned control lock whose owner file was never written", async () => {
    const runtimeRoot = await makeRuntimeRoot();
    const controlLock = path.join(runtimeRoot, "hermes-service-control.lock");
    await mkdir(controlLock);
    const old = new Date(Date.now() - 10_000);
    await utimes(controlLock, old, old);
    const platform = new FakeServicePlatform(runtimeRoot);
    const supervisor = new HermesServiceSupervisor(
      { runtimeRoot, lockTimeoutMs: 50 },
      platform
    );

    await expect(supervisor.status()).resolves.toMatchObject({
      outcome: "unhealthy"
    });
  });

  it("restarts only after three consecutive failed health checks", async () => {
    const runtimeRoot = await makeRuntimeRoot();
    const platform = new FakeServicePlatform(runtimeRoot);
    platform.running = true;
    await writeFile(
      path.join(runtimeRoot, "server.lock"),
      `${platform.pid}\n`,
      "utf8"
    );
    await writeState(runtimeRoot, "running");
    const supervisor = new HermesServiceSupervisor({ runtimeRoot }, platform);

    expect((await supervisor.watch()).outcome).toBe("unhealthy");
    expect((await supervisor.watch()).outcome).toBe("unhealthy");
    expect(platform.stops).toBe(0);

    expect((await supervisor.watch()).outcome).toBe("restarted");
    expect(platform.stops).toBe(1);
    expect(platform.starts).toBe(1);
  });

  it("does not report or persist a failed watchdog recovery as success", async () => {
    const runtimeRoot = await makeRuntimeRoot();
    const platform = new FakeServicePlatform(runtimeRoot);
    platform.spawnSucceeds = false;
    await writeState(runtimeRoot, "running", 2);
    const supervisor = new HermesServiceSupervisor(
      { runtimeRoot, startupTimeoutMs: 0 },
      platform
    );

    const result = await supervisor.watch();

    expect(result.outcome).toBe("recovery-failed");
    expect(result.consecutiveFailures).toBe(3);
    expect(
      JSON.parse(
        await readFile(path.join(runtimeRoot, "hermes-service-state.json"), "utf8")
      )
    ).toEqual({ desired: "running", consecutiveFailures: 3 });
  });

  it("serializes watchdog recovery with a concurrent explicit stop", async () => {
    const runtimeRoot = await makeRuntimeRoot();
    const platform = new FakeServicePlatform(runtimeRoot);
    platform.running = true;
    platform.stopEntered = deferred();
    platform.stopRelease = deferred();
    await writeFile(
      path.join(runtimeRoot, "server.lock"),
      `${platform.pid}\n`,
      "utf8"
    );
    await writeState(runtimeRoot, "running", 2);
    const supervisor = new HermesServiceSupervisor({ runtimeRoot }, platform);

    const watch = supervisor.watch();
    await platform.stopEntered.promise;
    const stop = supervisor.stop();
    platform.stopRelease.resolve();

    expect((await watch).outcome).toBe("restarted");
    expect((await stop).outcome).toBe("stopped");
    expect(platform.running).toBe(false);
    expect(
      JSON.parse(
        await readFile(path.join(runtimeRoot, "hermes-service-state.json"), "utf8")
      )
    ).toEqual({ desired: "stopped", consecutiveFailures: 0 });
  });

  it("reports an already-running degraded portal as degraded", async () => {
    const runtimeRoot = await makeRuntimeRoot();
    const platform = new FakeServicePlatform(runtimeRoot);
    platform.running = true;
    platform.responding = true;
    platform.healthStatus = "degraded";
    await writeFile(
      path.join(runtimeRoot, "server.lock"),
      `${platform.pid}\n`,
      "utf8"
    );
    const supervisor = new HermesServiceSupervisor({ runtimeRoot }, platform);

    await expect(supervisor.start()).resolves.toMatchObject({
      outcome: "degraded",
      desired: "running"
    });
  });
});

describe("NodeServicePlatform", () => {
  it("does not accept a relative server command from another working directory", async () => {
    const expectedRuntimeRoot = await makeRuntimeRoot();
    const otherRuntimeRoot = await makeRuntimeRoot();
    const otherProjectRoot = path.dirname(otherRuntimeRoot);
    await mkdir(path.join(otherProjectRoot, "dist"), { recursive: true });
    await writeFile(
      path.join(otherProjectRoot, "dist", "server.js"),
      "setInterval(() => {}, 1000);\n",
      "utf8"
    );
    const child = spawn(process.execPath, ["dist/server.js"], {
      cwd: otherProjectRoot,
      stdio: "ignore"
    });
    children.push(child);
    await new Promise<void>((resolve, reject) => {
      child.once("spawn", resolve);
      child.once("error", reject);
    });
    if (child.pid === undefined) throw new Error("Expected child PID");
    const platform = new NodeServicePlatform({
      projectRoot: path.dirname(expectedRuntimeRoot),
      port: 7882,
      nodeCommand: process.execPath,
      pythonCommand: "python",
      codexCommand: "codex",
      claudeCommand: "claude",
      stdoutLogPath: path.join(expectedRuntimeRoot, "stdout.log"),
      stderrLogPath: path.join(expectedRuntimeRoot, "stderr.log")
    });

    await expect(platform.getProcessIdentity(child.pid)).resolves.toBeNull();
  });

  it("preserves a responsive degraded health payload returned with HTTP 503", async () => {
    const server = createServer((_request, response) => {
      response.statusCode = 503;
      response.setHeader("content-type", "application/json");
      response.end(
        JSON.stringify({
          status: "degraded",
          pid: process.pid,
          errorCode: "ENGINE_UNAVAILABLE",
          activeJobs: 0,
          queuedJobs: 0
        })
      );
    });
    servers.push(server);
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    if (address === null || typeof address === "string") {
      throw new Error("Expected a TCP test server");
    }
    const runtimeRoot = await makeRuntimeRoot();
    const platform = new NodeServicePlatform({
      projectRoot: path.dirname(runtimeRoot),
      port: address.port,
      nodeCommand: process.execPath,
      pythonCommand: "python",
      codexCommand: "codex",
      claudeCommand: "claude",
      stdoutLogPath: path.join(runtimeRoot, "stdout.log"),
      stderrLogPath: path.join(runtimeRoot, "stderr.log")
    });

    await expect(platform.getHealth()).resolves.toMatchObject({
      status: "degraded",
      pid: process.pid,
      errorCode: "ENGINE_UNAVAILABLE"
    });
  });
});
