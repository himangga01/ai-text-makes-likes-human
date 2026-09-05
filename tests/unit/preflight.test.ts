import { describe, expect, it } from "vitest";
import { loadConfig } from "../../src/config.js";
import { runPreflight } from "../../src/process/preflight.js";
import { exited, FakeCommandRunner } from "../helpers/fake-command-runner.js";

const config = loadConfig({}, process.cwd());
const engineVersion =
  "version=2.3.2\ncommit=31a66d165a9cc6c26c4c1246553f95d0468d27fb\n";

describe("runPreflight", () => {
  it("reports ready for supported Python, Codex, login, and engine versions", async () => {
    const runner = new FakeCommandRunner([
      exited("Python 3.14.7"),
      exited("codex-cli 0.149.0"),
      exited("Logged in using ChatGPT")
    ]);

    const report = await runPreflight(config, runner, engineVersion);

    expect(report).toMatchObject({
      ready: true,
      pythonVersion: "3.14.7",
      codexVersion: "0.149.0",
      humanizeVersion: "2.3.2"
    });
  });

  it("returns one safe public failure when Codex is not logged in", async () => {
    const runner = new FakeCommandRunner([
      exited("Python 3.14.7"),
      exited("codex-cli 0.149.0"),
      exited("", 1, "secret-path C:/Users/name/.codex/auth.json")
    ]);

    const report = await runPreflight(config, runner, engineVersion);

    expect(report).toMatchObject({
      ready: false,
      errorCode: "ENGINE_UNAVAILABLE",
      message: "서버의 Codex 로그인이 필요합니다."
    });
    expect(JSON.stringify(report)).not.toContain("secret-path");
    expect(JSON.stringify(report)).not.toContain("auth.json");
  });

  it("accepts the Windows Codex login message emitted on stderr", async () => {
    const runner = new FakeCommandRunner([
      exited("Python 3.14.7"),
      exited("codex-cli 0.149.0"),
      exited("", 0, "Logged in using ChatGPT")
    ]);

    const report = await runPreflight(config, runner, engineVersion);

    expect(report.ready).toBe(true);
  });

  it("rejects Codex versions older than 0.149.0", async () => {
    const runner = new FakeCommandRunner([
      exited("Python 3.14.7"),
      exited("codex-cli 0.148.0"),
      exited("Logged in using ChatGPT")
    ]);

    const report = await runPreflight(config, runner, engineVersion);

    expect(report.ready).toBe(false);
    expect(report.message).toContain("0.149.0 이상");
  });
});
