import { execFile, spawn } from "node:child_process";
import { closeSync, openSync, realpathSync } from "node:fs";
import {
  access,
  mkdir,
  readFile,
  rename,
  rm,
  stat,
  writeFile
} from "node:fs/promises";
import { fileURLToPath } from "node:url";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export interface ServiceHealth {
  readonly status: string;
  readonly pid: number;
  readonly activeJobs: number;
  readonly queuedJobs: number;
  readonly [key: string]: unknown;
}

export interface ServicePlatform {
  getProcessIdentity(pid: number): Promise<string | null>;
  spawnService(): Promise<void>;
  stopProcess(pid: number, identity: string): Promise<void>;
  getHealth(): Promise<ServiceHealth | null>;
  sleep(ms: number): Promise<void>;
}

interface SupervisorState {
  readonly desired: "running" | "stopped";
  readonly consecutiveFailures: number;
}

interface ServiceInspection {
  readonly pid: number | null;
  readonly identity: string | null;
  readonly running: boolean;
  readonly health: ServiceHealth | null;
  readonly foreignHealth: boolean;
}

export interface SupervisorOptions {
  readonly runtimeRoot: string;
  readonly failureThreshold?: number;
  readonly startupTimeoutMs?: number;
  readonly pollIntervalMs?: number;
  readonly lockTimeoutMs?: number;
}

export interface ServiceActionResult {
  readonly outcome:
    | "already-running"
    | "already-stopped"
    | "started"
    | "started-degraded"
    | "started-unhealthy"
    | "failed-start"
    | "stopped"
    | "failed-stop"
    | "healthy"
    | "degraded"
    | "unhealthy"
    | "unmanaged-service"
    | "intentionally-stopped"
    | "restarted"
    | "restarted-degraded"
    | "failed-restart"
    | "recovery-failed";
  readonly desired: "running" | "stopped";
  readonly pid: number | null;
  readonly health: ServiceHealth | null;
  readonly consecutiveFailures: number;
}

const defaultState: SupervisorState = Object.freeze({
  desired: "running",
  consecutiveFailures: 0
});

export class HermesServiceSupervisor {
  private readonly serverLockPath: string;
  private readonly statePath: string;
  private readonly controlLockPath: string;
  private readonly failureThreshold: number;
  private readonly startupTimeoutMs: number;
  private readonly pollIntervalMs: number;
  private readonly lockTimeoutMs: number;

  constructor(
    private readonly options: SupervisorOptions,
    private readonly platform: ServicePlatform
  ) {
    this.serverLockPath = path.join(options.runtimeRoot, "server.lock");
    this.statePath = path.join(options.runtimeRoot, "hermes-service-state.json");
    this.controlLockPath = path.join(
      options.runtimeRoot,
      "hermes-service-control.lock"
    );
    this.failureThreshold = options.failureThreshold ?? 3;
    this.startupTimeoutMs = options.startupTimeoutMs ?? 30_000;
    this.pollIntervalMs = options.pollIntervalMs ?? 250;
    this.lockTimeoutMs = options.lockTimeoutMs ?? 60_000;
  }

  start(): Promise<ServiceActionResult> {
    return this.withControlLock(async () => {
      const state = { desired: "running", consecutiveFailures: 0 } as const;
      await this.writeState(state);
      return this.startUnlocked(state);
    });
  }

  reconcile(): Promise<ServiceActionResult> {
    return this.withControlLock(async () => {
      const state = await this.readState();
      if (state.desired === "stopped") {
        return this.ensureStoppedUnlocked(state, "intentionally-stopped");
      }
      return this.startUnlocked(state);
    });
  }

  stop(): Promise<ServiceActionResult> {
    return this.withControlLock(async () => {
      const state = { desired: "stopped", consecutiveFailures: 0 } as const;
      await this.writeState(state);
      return this.ensureStoppedUnlocked(state, "already-stopped");
    });
  }

  restart(): Promise<ServiceActionResult> {
    return this.withControlLock(async () => {
      const state = { desired: "running", consecutiveFailures: 0 } as const;
      await this.writeState(state);
      const current = await this.inspect();
      if (current.foreignHealth && !current.running) {
        return this.result("failed-restart", state, current.pid, current.health);
      }
      if (current.running && current.pid !== null && current.identity !== null) {
        await this.platform.stopProcess(current.pid, current.identity);
      }
      return this.spawnAndClassify(state, "restart");
    });
  }

  status(): Promise<ServiceActionResult> {
    return this.withControlLock(async () => {
      const state = await this.readState();
      const current = await this.inspect();
      if (state.desired === "stopped" && !current.running) {
        return this.result("intentionally-stopped", state, current.pid);
      }
      if (current.foreignHealth) {
        return this.result("unmanaged-service", state, current.pid);
      }
      if (!current.running) {
        return this.result("unhealthy", state, current.pid);
      }
      const outcome = current.health?.status === "ready" ? "healthy" : "degraded";
      return this.result(outcome, state, current.pid, current.health);
    });
  }

  watch(): Promise<ServiceActionResult> {
    return this.withControlLock(async () => {
      let state = await this.readState();
      if (state.desired === "stopped") {
        return this.ensureStoppedUnlocked(state, "intentionally-stopped");
      }

      const current = await this.inspect();
      if (current.running && current.health !== null) {
        state = { desired: "running", consecutiveFailures: 0 };
        await this.writeState(state);
        const outcome = current.health.status === "ready" ? "healthy" : "degraded";
        return this.result(outcome, state, current.pid, current.health);
      }

      state = {
        desired: "running",
        consecutiveFailures: state.consecutiveFailures + 1
      };
      await this.writeState(state);
      if (state.consecutiveFailures < this.failureThreshold) {
        return this.result("unhealthy", state, current.pid);
      }

      const latest = await this.readState();
      if (latest.desired === "stopped") {
        return this.result("intentionally-stopped", latest, current.pid);
      }
      if (current.foreignHealth && !current.running) {
        return this.result("recovery-failed", state, current.pid);
      }
      if (current.running && current.pid !== null && current.identity !== null) {
        await this.platform.stopProcess(current.pid, current.identity);
      }

      try {
        await this.platform.spawnService();
      } catch {
        return this.result("recovery-failed", state, await this.readPid());
      }
      const restarted = await this.waitForService();
      if (!restarted.running || restarted.health === null) {
        return this.result(
          "recovery-failed",
          state,
          restarted.pid,
          restarted.health
        );
      }

      const recoveredState = { desired: "running", consecutiveFailures: 0 } as const;
      await this.writeState(recoveredState);
      const outcome =
        restarted.health.status === "ready" ? "restarted" : "restarted-degraded";
      return this.result(outcome, recoveredState, restarted.pid, restarted.health);
    });
  }

  private async startUnlocked(
    state: SupervisorState
  ): Promise<ServiceActionResult> {
    const current = await this.inspect();
    if (current.running && current.health !== null) {
      const outcome =
        current.health.status === "ready" ? "already-running" : "degraded";
      return this.result(outcome, state, current.pid, current.health);
    }
    if (current.foreignHealth && !current.running) {
      return this.result("unmanaged-service", state, current.pid);
    }
    if (current.running) {
      return this.result("started-unhealthy", state, current.pid);
    }

    // The server entry point owns atomic acquisition and stale-lock recovery.
    // An earlier process/health snapshot cannot authorize deleting that lock.
    return this.spawnAndClassify(state, "start");
  }

  private async ensureStoppedUnlocked(
    state: SupervisorState,
    alreadyStoppedOutcome: "already-stopped" | "intentionally-stopped"
  ): Promise<ServiceActionResult> {
    const current = await this.inspect();
    if (!current.running || current.pid === null || current.identity === null) {
      if (current.foreignHealth) {
        return this.result("failed-stop", state, current.pid);
      }
      return this.result(alreadyStoppedOutcome, state, current.pid);
    }

    try {
      await this.platform.stopProcess(current.pid, current.identity);
    } catch {
      return this.result("failed-stop", state, current.pid, current.health);
    }
    const stopped = await this.inspect();
    return this.result(
      stopped.running || stopped.foreignHealth ? "failed-stop" : "stopped",
      state,
      current.pid,
      stopped.health
    );
  }

  private async spawnAndClassify(
    state: SupervisorState,
    action: "start" | "restart"
  ): Promise<ServiceActionResult> {
    try {
      await this.platform.spawnService();
    } catch {
      return this.result(
        action === "start" ? "failed-start" : "failed-restart",
        state,
        await this.readPid()
      );
    }
    const started = await this.waitForService();
    if (!started.running || started.health === null) {
      return this.result(
        action === "start" ? "failed-start" : "failed-restart",
        state,
        started.pid,
        started.health
      );
    }
    const ready = started.health.status === "ready";
    const outcome =
      action === "start"
        ? ready
          ? "started"
          : "started-degraded"
        : ready
          ? "restarted"
          : "restarted-degraded";
    return this.result(outcome, state, started.pid, started.health);
  }

  private async inspect(): Promise<ServiceInspection> {
    const pid = await this.readPid();
    const identity =
      pid === null ? null : await this.platform.getProcessIdentity(pid);
    const rawHealth = await this.platform.getHealth();
    const health =
      pid !== null && identity !== null && rawHealth?.pid === pid
        ? rawHealth
        : null;
    return {
      pid,
      identity,
      running: identity !== null,
      health,
      foreignHealth: rawHealth !== null && health === null
    };
  }

  private async waitForService(): Promise<ServiceInspection> {
    const deadline = Date.now() + this.startupTimeoutMs;
    do {
      const current = await this.inspect();
      if (current.running && current.health !== null) return current;
      await this.platform.sleep(this.pollIntervalMs);
    } while (Date.now() < deadline);
    return this.inspect();
  }

  private async readPid(): Promise<number | null> {
    try {
      const value = Number.parseInt(await readFile(this.serverLockPath, "utf8"), 10);
      return Number.isInteger(value) && value > 0 ? value : null;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw error;
    }
  }

  private async readState(): Promise<SupervisorState> {
    try {
      const parsed = JSON.parse(await readFile(this.statePath, "utf8")) as {
        desired?: unknown;
        consecutiveFailures?: unknown;
      };
      return {
        desired: parsed.desired === "stopped" ? "stopped" : "running",
        consecutiveFailures:
          typeof parsed.consecutiveFailures === "number" &&
          Number.isInteger(parsed.consecutiveFailures) &&
          parsed.consecutiveFailures >= 0
            ? parsed.consecutiveFailures
            : 0
      };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return defaultState;
      throw error;
    }
  }

  private async writeState(state: SupervisorState): Promise<void> {
    await mkdir(this.options.runtimeRoot, { recursive: true });
    const temporaryPath = `${this.statePath}.${process.pid}.${Date.now()}.tmp`;
    await writeFile(temporaryPath, `${JSON.stringify(state)}\n`, {
      encoding: "utf8",
      mode: 0o600
    });
    await rename(temporaryPath, this.statePath);
  }

  private async withControlLock<T>(operation: () => Promise<T>): Promise<T> {
    await mkdir(this.options.runtimeRoot, { recursive: true });
    const deadline = Date.now() + this.lockTimeoutMs;
    while (true) {
      try {
        await mkdir(this.controlLockPath, { mode: 0o700 });
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
        if (await this.controlLockIsStale()) {
          await rm(this.controlLockPath, { recursive: true, force: true });
          continue;
        }
        if (Date.now() >= deadline) {
          throw new Error("Timed out waiting for the Hermes service control lock");
        }
        await this.platform.sleep(25);
        continue;
      }
      // Publish the owner atomically; a failed write must not leave an ownerless lock.
      const ownerPath = path.join(this.controlLockPath, "owner.json");
      const temporaryPath = `${ownerPath}.${process.pid}.tmp`;
      try {
        await writeFile(
          temporaryPath,
          `${JSON.stringify({ pid: process.pid, createdAt: Date.now() })}\n`,
          { encoding: "utf8", mode: 0o600 }
        );
        await rename(temporaryPath, ownerPath);
      } catch (error) {
        await rm(this.controlLockPath, { recursive: true, force: true });
        throw error;
      }
      break;
    }

    try {
      return await operation();
    } finally {
      await rm(this.controlLockPath, { recursive: true, force: true });
    }
  }

  private async controlLockIsStale(): Promise<boolean> {
    let ageMs: number;
    try {
      const lockStat = await stat(this.controlLockPath);
      ageMs = Date.now() - lockStat.mtimeMs;
      if (ageMs < 5_000) return false;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
      throw error;
    }

    try {
      const owner = JSON.parse(
        await readFile(path.join(this.controlLockPath, "owner.json"), "utf8")
      ) as { pid?: unknown };
      if (typeof owner.pid !== "number" || !Number.isInteger(owner.pid)) {
        return true;
      }
      try {
        process.kill(owner.pid, 0);
        return ageMs > 120_000;
      } catch (error) {
        return (error as NodeJS.ErrnoException).code !== "EPERM";
      }
    } catch (error) {
      // The lock is at least 5 s old here, so a missing or truncated owner
      // file belongs to an owner that died between mkdir and the write.
      if ((error as NodeJS.ErrnoException).code === "ENOENT" || error instanceof SyntaxError) return true;
      throw error;
    }
  }

  private result(
    outcome: ServiceActionResult["outcome"],
    state: SupervisorState,
    pid: number | null,
    health: ServiceHealth | null = null
  ): ServiceActionResult {
    return {
      outcome,
      desired: state.desired,
      pid,
      health,
      consecutiveFailures: state.consecutiveFailures
    };
  }
}

// Rows of `ps -A -o pid=,ppid=,pgid=` to kill targets for `parent`'s children:
// a child leading its own (detached) process group is killed as a group.
export function childProcessTargets(psOutput: string, parent: number): number[] {
  const targets = new Set<number>();
  for (const line of psOutput.split(/\r?\n/)) {
    const [pid, ppid, pgid] = line.trim().split(/\s+/).map(Number);
    if (!Number.isInteger(pid) || pid! <= 0 || ppid !== parent || pid === parent) continue;
    targets.add(pgid === pid ? -pid! : pid!);
  }
  return [...targets];
}

export interface NodeServicePlatformOptions {
  readonly projectRoot: string;
  readonly port: number;
  readonly nodeCommand: string;
  readonly pythonCommand: string;
  readonly codexCommand: string;
  readonly claudeCommand: string;
  readonly stdoutLogPath: string;
  readonly stderrLogPath: string;
}

// HUMANIZE_RUNTIME_ROOT is for test instances; the managed server must use the
// runtime directory (and server.lock) this supervisor inspects.
export function serviceEnvironment(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  const { HUMANIZE_RUNTIME_ROOT: testRuntimeRoot, ...inherited } = env;
  void testRuntimeRoot;
  return inherited;
}

export class NodeServicePlatform implements ServicePlatform {
  private readonly serverEntry: string;
  private readonly nodeCommand: string;

  constructor(private readonly options: NodeServicePlatformOptions) {
    this.serverEntry = path.resolve(options.projectRoot, "dist", "server.js");
    this.nodeCommand = realpathSync(options.nodeCommand);
  }

  async getProcessIdentity(pid: number): Promise<string | null> {
    try {
      const [started, executable, command, cwd] = await Promise.all([
        this.readPsField(pid, "lstart="),
        this.readPsField(pid, "comm="),
        this.readPsField(pid, "command="),
        this.readWorkingDirectory(pid)
      ]);
      const expectedCommand = `${this.nodeCommand} ${this.serverEntry}`;
      if (
        executable !== this.nodeCommand ||
        command !== expectedCommand ||
        cwd !== path.resolve(this.options.projectRoot)
      ) {
        return null;
      }
      return `${started}|${executable}|${command}|${cwd}`;
    } catch {
      return null;
    }
  }

  async spawnService(): Promise<void> {
    await access(this.serverEntry);
    await mkdir(path.dirname(this.options.stdoutLogPath), { recursive: true });
    const stdoutFd = openSync(this.options.stdoutLogPath, "a", 0o600);
    const stderrFd = openSync(this.options.stderrLogPath, "a", 0o600);
    try {
      const child = spawn(this.options.nodeCommand, [this.serverEntry], {
        cwd: this.options.projectRoot,
        detached: true,
        shell: false,
        stdio: ["ignore", stdoutFd, stderrFd],
        env: {
          ...serviceEnvironment(process.env),
          HOST: "0.0.0.0",
          PORT: String(this.options.port),
          PYTHON_COMMAND: this.options.pythonCommand,
          CODEX_COMMAND: this.options.codexCommand,
          CLAUDE_COMMAND: this.options.claudeCommand,
          CODEX_CHUNK_CONCURRENCY: "1"
        }
      });
      await new Promise<void>((resolve, reject) => {
        child.once("spawn", resolve);
        child.once("error", reject);
      });
      child.unref();
    } finally {
      closeSync(stdoutFd);
      closeSync(stderrFd);
    }
  }

  async stopProcess(pid: number, identity: string): Promise<void> {
    if ((await this.getProcessIdentity(pid)) !== identity) {
      throw new Error(`Refusing to stop PID ${pid}: portal identity changed`);
    }

    process.kill(pid, "SIGTERM");
    const gracefulDeadline = Date.now() + 20_000;
    while (
      (await this.getProcessIdentity(pid)) === identity &&
      Date.now() < gracefulDeadline
    ) {
      await this.sleep(250);
    }
    if ((await this.getProcessIdentity(pid)) !== identity) return;

    const processGroup = await this.getProcessGroup(pid);
    if ((await this.getProcessIdentity(pid)) !== identity) return;
    // The server's CLI children run in their own process groups; a SIGKILL of
    // the server skips its exit cleanup, so kill those groups first.
    await this.killChildProcesses(pid);
    if (processGroup === pid) {
      process.kill(-pid, "SIGKILL");
    } else {
      process.kill(pid, "SIGKILL");
    }

    const forceDeadline = Date.now() + 5_000;
    while (
      (await this.getProcessIdentity(pid)) === identity &&
      Date.now() < forceDeadline
    ) {
      await this.sleep(100);
    }
    if ((await this.getProcessIdentity(pid)) === identity) {
      throw new Error(`Portal PID ${pid} did not terminate`);
    }
  }

  async getHealth(): Promise<ServiceHealth | null> {
    try {
      const response = await fetch(
        `http://127.0.0.1:${this.options.port}/api/health`,
        { signal: AbortSignal.timeout(3_000) }
      );
      const value = (await response.json()) as Partial<ServiceHealth>;
      if (
        (value.status !== "ready" && value.status !== "degraded") ||
        typeof value.pid !== "number" ||
        !Number.isInteger(value.pid) ||
        value.pid <= 0
      ) {
        return null;
      }
      return {
        ...value,
        status: value.status,
        pid: value.pid,
        activeJobs:
          typeof value.activeJobs === "number" ? value.activeJobs : 0,
        queuedJobs:
          typeof value.queuedJobs === "number" ? value.queuedJobs : 0
      };
    } catch {
      return null;
    }
  }

  sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  private async killChildProcesses(parent: number): Promise<void> {
    let stdout: string;
    try {
      ({ stdout } = await execFileAsync("/bin/ps", ["-A", "-o", "pid=,ppid=,pgid="]));
    } catch {
      return;
    }
    for (const target of childProcessTargets(stdout, parent)) {
      try {
        process.kill(target, "SIGKILL");
      } catch {
        // The child exited after the process listing.
      }
    }
  }

  private async getProcessGroup(pid: number): Promise<number | null> {
    try {
      const { stdout } = await execFileAsync("/bin/ps", [
        "-p",
        String(pid),
        "-o",
        "pgid="
      ]);
      const value = Number.parseInt(stdout.trim(), 10);
      return Number.isInteger(value) && value > 0 ? value : null;
    } catch {
      return null;
    }
  }

  private async readPsField(pid: number, field: string): Promise<string> {
    const { stdout } = await execFileAsync("/bin/ps", [
      "-p",
      String(pid),
      "-o",
      field
    ]);
    return stdout.trim();
  }

  private async readWorkingDirectory(pid: number): Promise<string | null> {
    const { stdout } = await execFileAsync("/usr/sbin/lsof", [
      "-a",
      "-p",
      String(pid),
      "-d",
      "cwd",
      "-Fn"
    ]);
    const directory = stdout
      .split(/\r?\n/)
      .find(line => line.startsWith("n"));
    return directory?.slice(1) ?? null;
  }
}

async function readLogTail(filePath: string, lineCount: number): Promise<string> {
  try {
    const content = await readFile(filePath, "utf8");
    return content.split(/\r?\n/).slice(-lineCount - 1).join("\n").trim();
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return "";
    throw error;
  }
}

function commandFailed(
  command: string,
  result: ServiceActionResult
): boolean {
  if (
    result.outcome === "failed-start" ||
    result.outcome === "failed-stop" ||
    result.outcome === "failed-restart" ||
    result.outcome === "recovery-failed" ||
    result.outcome === "unmanaged-service" ||
    result.outcome === "started-unhealthy" ||
    result.outcome === "started-degraded" ||
    result.outcome === "restarted-degraded" ||
    result.outcome === "degraded"
  ) {
    return true;
  }
  return command === "status" && result.outcome === "unhealthy";
}

async function runCli(): Promise<void> {
  const projectRoot = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../.."
  );
  const runtimeRoot = path.join(projectRoot, "runtime");
  const home = os.homedir();
  const logPath = path.join(runtimeRoot, "hermes-service.log");
  const platform = new NodeServicePlatform({
    projectRoot,
    port: 7882,
    nodeCommand: process.execPath,
    pythonCommand: path.join(
      home,
      ".hermes",
      "hermes-agent",
      "venv",
      "bin",
      "python"
    ),
    codexCommand: path.join(home, ".local", "bin", "codex"),
    claudeCommand: path.join(home, ".local", "bin", "claude"),
    stdoutLogPath: logPath,
    stderrLogPath: logPath
  });
  const supervisor = new HermesServiceSupervisor({ runtimeRoot }, platform);
  const command = process.argv[2] ?? "status";

  if (command === "logs") {
    const requestedLines = Number.parseInt(process.argv[3] ?? "100", 10);
    const lineCount = Number.isInteger(requestedLines)
      ? Math.min(Math.max(requestedLines, 1), 500)
      : 100;
    const output = await readLogTail(logPath, lineCount);
    if (output) console.log(output);
    return;
  }

  let result: ServiceActionResult;
  switch (command) {
    case "start":
      result = await supervisor.start();
      break;
    case "reconcile":
      result = await supervisor.reconcile();
      break;
    case "stop":
      result = await supervisor.stop();
      break;
    case "restart":
      result = await supervisor.restart();
      break;
    case "status":
      result = await supervisor.status();
      break;
    case "watch":
      result = await supervisor.watch();
      if (
        result.outcome === "healthy" ||
        result.outcome === "intentionally-stopped"
      ) {
        return;
      }
      break;
    default:
      throw new Error(
        "Usage: hermes-service <start|reconcile|stop|restart|status|watch|logs> [lines]"
      );
  }
  console.log(JSON.stringify(result));
  if (commandFailed(command, result)) process.exitCode = 1;
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : "";
if (invokedPath === fileURLToPath(import.meta.url)) {
  runCli().catch(error => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}
