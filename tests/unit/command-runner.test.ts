import { describe, expect, it } from "vitest";
import { SpawnCommandRunner } from "../../src/process/command-runner.js";

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
});
