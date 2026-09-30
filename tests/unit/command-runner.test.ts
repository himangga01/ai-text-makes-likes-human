import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { describe, expect, it } from "vitest";
import { SpawnCommandRunner } from "../../src/process/command-runner.js";

function alive(pid: number): boolean {
  try { process.kill(pid, 0); return true; } catch { return false; }
}

const runner = new SpawnCommandRunner();

describe("SpawnCommandRunner", () => {
  it("captures stdout, stderr, and a nonzero exit without using a shell", async () => {
    const result = await runner.run({
      command: process.execPath,
      args: [
        "-e",
        "process.stdout.write('out'); process.stderr.write('err'); process.exit(7)"
      ],
      cwd: process.cwd(),
      timeoutMs: 5_000
    });

    expect(result).toEqual({
      exitCode: 7,
      stdout: "out",
      stderr: "err",
      termination: "exit"
    });
  });

  it("writes the supplied stdin exactly", async () => {
    const result = await runner.run({
      command: process.execPath,
      args: ["-e", "process.stdin.pipe(process.stdout)"],
      cwd: process.cwd(),
      stdin: "한글 입력\n",
      timeoutMs: 5_000
    });

    expect(result.stdout).toBe("한글 입력\n");
    expect(result.termination).toBe("exit");
  });

  it("terminates a process tree when the timeout expires", async () => {
    const started = Date.now();
    const result = await runner.run({
      command: process.execPath,
      args: ["-e", "setInterval(() => {}, 1000)"],
      cwd: process.cwd(),
      timeoutMs: 100
    });

    expect(result.termination).toBe("timeout");
    expect(Date.now() - started).toBeLessThan(5_000);
  });

  it("terminates an active process when the signal is aborted", async () => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 50);

    const result = await runner.run({
      command: process.execPath,
      args: ["-e", "setInterval(() => {}, 1000)"],
      cwd: process.cwd(),
      timeoutMs: 5_000,
      signal: controller.signal
    });

    expect(result.termination).toBe("aborted");
  });
  it.skipIf(process.platform === "win32").each(["uncaught exception", "process.exit"])(
    "kills detached CLI children when the server process dies by %s",
    async mode => {
      const root = await mkdtemp(path.join(os.tmpdir(), "runner-exit-"));
      const script = path.join(root, "server.mts");
      const runnerUrl = pathToFileURL(path.resolve("src/process/command-runner.ts")).href;
      await writeFile(script, `
        import { SpawnCommandRunner, killChildProcessesOnExit } from ${JSON.stringify(runnerUrl)};
        killChildProcessesOnExit();
        const runner = new SpawnCommandRunner(pid => process.stdout.write(pid + "\\n"));
        void runner.run({ command: "/bin/sleep", args: ["30"], cwd: process.cwd(), timeoutMs: 60_000 });
        setTimeout(() => { ${mode === "process.exit" ? "process.exit(1)" : 'throw new Error("crash")'} }, 300);
      `, "utf8");
      let childPid = 0;
      try {
        const server = spawn(process.execPath, ["--import", "tsx", script], { cwd: process.cwd(), stdio: ["ignore", "pipe", "ignore"] });
        let output = "";
        server.stdout.on("data", chunk => { output += String(chunk); });
        await new Promise(resolve => server.once("close", resolve));
        childPid = Number.parseInt(output.trim(), 10);
        expect(childPid).toBeGreaterThan(0);
        await expect.poll(() => alive(childPid), { timeout: 2_000 }).toBe(false);
      } finally {
        if (childPid > 0 && alive(childPid)) process.kill(childPid, "SIGKILL");
        await rm(root, { recursive: true, force: true });
      }
    },
    15_000
  );
});
