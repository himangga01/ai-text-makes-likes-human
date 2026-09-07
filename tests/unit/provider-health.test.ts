import { describe, expect, it } from "vitest";
import { probeProvider } from "../../src/runtime/provider-health.js";
import { runPreflight } from "../../src/process/preflight.js";
import { loadConfig } from "../../src/config.js";
import { exited, FakeCommandRunner } from "../helpers/fake-command-runner.js";

describe("independent CLI health", () => {
  it("keeps Claude ready when Codex is missing", async () => {
    const runner = new FakeCommandRunner([exited("Python 3.14.7"), new Error("missing Codex"), exited("2.1.261 (Claude Code)"), exited('{"loggedIn":true,"email":"private@example.invalid"}')]);
    const result = await runPreflight(loadConfig({}, process.cwd()), runner, "version=2.3.2");
    expect(result.ready).toBe(true);
    expect(result.providers?.codex.ready).toBe(false);
    expect(result.providers?.claude.ready).toBe(true);
    expect(JSON.stringify(result)).not.toContain("private@example");
  });
  it("does not mistake Claude version availability for authentication", async () => {
    const runner = new FakeCommandRunner([exited("2.1.261"), exited('{"loggedIn":false}', 1)]);
    expect(await probeProvider("claude", "claude", process.cwd(), runner)).toMatchObject({ ready: false, installed: true, authenticated: false });
  });
  it("rejects malformed Claude authentication without exposing output", async () => {
    const runner = new FakeCommandRunner([exited("2.1.261"), exited("private malformed payload")]);
    const report = await probeProvider("claude", "claude", process.cwd(), runner);
    expect(report.ready).toBe(false); expect(JSON.stringify(report)).not.toContain("private malformed");
  });
  it("diagnoses a shell launcher without running it", async () => {
    const runner = new FakeCommandRunner([]);
    const report = await probeProvider("codex", "C:/custom/codex.cmd", process.cwd(), runner);
    expect(report.ready).toBe(false); expect(report.message).toContain("EXE"); expect(runner.calls).toEqual([]);
  });
});
