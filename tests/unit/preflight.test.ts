import { readFile } from "node:fs/promises";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadConfig } from "../../src/config.js";
import { engineVersionPath, runPreflight } from "../../src/process/preflight.js";
import { exited, FakeCommandRunner } from "../helpers/fake-command-runner.js";

const config = loadConfig({}, process.cwd());
const engineVersion =
  "version=2.3.2\ncommit=31a66d165a9cc6c26c4c1246553f95d0468d27fb\n";
const sejongVersion = "id=super-sejong\nversion=2.0.0\nschema=1\n";
// The engine switch is read from the environment, so every call names it instead of inheriting the shell's.
const legacyEnv: NodeJS.ProcessEnv = {};
const v2Env: NodeJS.ProcessEnv = { SUPER_SEJONG_ENGINE: "v2" };

function readyRunner(): FakeCommandRunner {
  return new FakeCommandRunner([
    exited("Python 3.14.7"),
    exited("codex-cli 0.149.0"),
    exited("Logged in using ChatGPT")
  ]);
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("runPreflight", () => {
  it("reports ready for supported Python, Codex, login, and engine versions", async () => {
    const runner = new FakeCommandRunner([
      exited("Python 3.14.7"),
      exited("codex-cli 0.149.0"),
      exited("Logged in using ChatGPT")
    ]);

    const report = await runPreflight(config, runner, engineVersion, legacyEnv);

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

    const report = await runPreflight(config, runner, engineVersion, legacyEnv);

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

    const report = await runPreflight(config, runner, engineVersion, legacyEnv);

    expect(report.ready).toBe(true);
  });

  it("rejects Codex versions older than 0.149.0", async () => {
    const runner = new FakeCommandRunner([
      exited("Python 3.14.7"),
      exited("codex-cli 0.148.0"),
      exited("Logged in using ChatGPT")
    ]);

    const report = await runPreflight(config, runner, engineVersion, legacyEnv);

    expect(report.ready).toBe(false);
    expect(report.message).toContain("0.149.0 이상");
  });
});

describe("runPreflight with the legacy engine (SUPER_SEJONG_ENGINE unset)", () => {
  it("still requires the vendor engine 2.3.2 and rejects any other version before running anything", async () => {
    for (const text of ["version=2.3.1\n", "version=2.4.0\n", "version=3.0.0\n"]) {
      const runner = new FakeCommandRunner([]);
      expect(await runPreflight(config, runner, text, legacyEnv)).toMatchObject({
        ready: false,
        errorCode: "ENGINE_UNAVAILABLE",
        message: "Humanize 엔진 2.3.2가 필요합니다."
      });
      expect(runner.calls).toEqual([]);
    }
  });

  it("gives the generic failure for an unreadable vendor version, as before", async () => {
    const report = await runPreflight(config, new FakeCommandRunner([]), "no version here", legacyEnv);
    expect(report).toMatchObject({ ready: false, message: "서버의 변환 엔진을 사용할 수 없습니다." });
  });

  it("does not accept the Super Sejong version file", async () => {
    const runner = new FakeCommandRunner([]);
    const report = await runPreflight(config, runner, sejongVersion, legacyEnv);

    expect(report).toMatchObject({ ready: false, message: "Humanize 엔진 2.3.2가 필요합니다." });
    expect(runner.calls).toEqual([]);
  });

  it("keeps the report shape: no engine id is added", async () => {
    const report = await runPreflight(config, readyRunner(), engineVersion, legacyEnv);
    expect(report.ready).toBe(true);
    expect("engineId" in report).toBe(false);
  });

  it("treats an unknown switch value as legacy", async () => {
    for (const value of ["", "v3", "v2.0", "super-sejong", "1"]) {
      const report = await runPreflight(config, readyRunner(), engineVersion, { SUPER_SEJONG_ENGINE: value });
      expect(report).toMatchObject({ ready: true, humanizeVersion: "2.3.2" });
    }
  });
});

describe("runPreflight with SUPER_SEJONG_ENGINE=v2", () => {
  it("is ready with the Super Sejong version and reports it", async () => {
    const report = await runPreflight(config, readyRunner(), sejongVersion, v2Env);

    expect(report).toMatchObject({
      ready: true,
      humanizeVersion: "2.0.0",
      engineId: "super-sejong",
      pythonVersion: "3.14.7",
      codexVersion: "0.149.0"
    });
  });

  it("reads the switch case-insensitively and with surrounding spaces, like selectEngine", async () => {
    const report = await runPreflight(config, readyRunner(), sejongVersion, { SUPER_SEJONG_ENGINE: " V2 " });
    expect(report).toMatchObject({ ready: true, engineId: "super-sejong" });
  });

  it("accepts a newer compatible engine, including a pre-release of a newer version", async () => {
    for (const version of ["2.0.1", "2.4.1", "3.0.0", "2.1.0-rc.1"]) {
      const report = await runPreflight(config, readyRunner(), `id=super-sejong\nversion=${version}\nschema=1\n`, v2Env);
      expect(report).toMatchObject({ ready: true, humanizeVersion: version });
    }
  });

  it("accepts the version file with Windows line endings", async () => {
    const report = await runPreflight(config, readyRunner(), sejongVersion.replace(/\n/g, "\r\n"), v2Env);
    expect(report.ready).toBe(true);
  });

  it("rejects the vendor version file", async () => {
    const runner = new FakeCommandRunner([]);
    const report = await runPreflight(config, runner, engineVersion, v2Env);

    expect(report).toMatchObject({
      ready: false,
      errorCode: "ENGINE_UNAVAILABLE",
      message: "Super Sejong 엔진 2.0.0 이상(스키마 1)이 필요합니다."
    });
    expect(runner.calls).toEqual([]);
  });

  it("rejects an old engine, a pre-release of the minimum, another schema, another id or a malformed file", async () => {
    const rejected = [
      "id=super-sejong\nversion=1.9.9\nschema=1\n",
      "id=super-sejong\nversion=2.0.0-rc.1\nschema=1\n",
      "id=super-sejong\nversion=2.0.0\nschema=2\n",
      "id=other-engine\nversion=2.0.0\nschema=1\n",
      "id=super-sejong\nversion=2.0\nschema=1\n",
      "id=super-sejong\nversion=2.0.0\n",
      "id=super-sejong\nversion=2.0.0\nschema=1\ncommit=abc\n",
      "id=super-sejong\nid=super-sejong\nversion=2.0.0\nschema=1\n",
      "id = super-sejong\nversion = 2.0.0\nschema = 1\n",
      "super-sejong 2.0.0",
      ""
    ];
    for (const text of rejected) {
      const runner = new FakeCommandRunner([]);
      const report = await runPreflight(config, runner, text, v2Env);
      expect(report, JSON.stringify(text)).toMatchObject({
        ready: false,
        errorCode: "ENGINE_UNAVAILABLE",
        message: "Super Sejong 엔진 2.0.0 이상(스키마 1)이 필요합니다."
      });
      expect(report.humanizeVersion).toBeUndefined();
      expect(runner.calls).toEqual([]);
    }
  });

  it("never echoes the version file in the public failure", async () => {
    const report = await runPreflight(config, new FakeCommandRunner([]), "id=super-sejong\nversion=secret-marker\nschema=1\n", v2Env);
    expect(report.ready).toBe(false);
    expect(JSON.stringify(report)).not.toContain("secret-marker");
  });

  it("keeps the Python and Codex checks of the legacy path", async () => {
    const tooOld = new FakeCommandRunner([exited("Python 3.10.9")]);
    expect(await runPreflight(config, tooOld, sejongVersion, v2Env)).toMatchObject({
      ready: false,
      message: "Python 3.11 이상이 필요합니다."
    });

    const loggedOut = new FakeCommandRunner([
      exited("Python 3.14.7"),
      exited("codex-cli 0.149.0"),
      exited("", 1, "secret-path")
    ]);
    const report = await runPreflight(config, loggedOut, sejongVersion, v2Env);
    expect(report).toMatchObject({ ready: false, message: "서버의 Codex 로그인이 필요합니다." });
    expect(JSON.stringify(report)).not.toContain("secret-path");
  });

  it("takes the switch from process.env when no environment is passed", async () => {
    vi.stubEnv("SUPER_SEJONG_ENGINE", "v2");
    expect(await runPreflight(config, readyRunner(), sejongVersion)).toMatchObject({ ready: true, engineId: "super-sejong" });
    expect(await runPreflight(config, new FakeCommandRunner([]), engineVersion)).toMatchObject({ ready: false });

    vi.stubEnv("SUPER_SEJONG_ENGINE", "legacy");
    expect(await runPreflight(config, readyRunner(), engineVersion)).toMatchObject({ ready: true, humanizeVersion: "2.3.2" });
  });
});

describe("engineVersionPath and the repository's own version files", () => {
  it("points at the vendor pin by default and at engine_runtime/sejong under v2", () => {
    expect(engineVersionPath(config, legacyEnv)).toBe(path.join(config.vendorRoot, "ENGINE_VERSION"));
    expect(engineVersionPath(config, { SUPER_SEJONG_ENGINE: "legacy" })).toBe(path.join(config.vendorRoot, "ENGINE_VERSION"));
    expect(engineVersionPath(config, v2Env)).toBe(path.join(config.projectRoot, "engine_runtime", "sejong", "ENGINE_VERSION"));
  });

  it("passes preflight for each engine with its own version file", async () => {
    const legacyText = await readFile(engineVersionPath(config, legacyEnv), "utf8");
    const v2Text = await readFile(engineVersionPath(config, v2Env), "utf8");

    expect(await runPreflight(config, readyRunner(), legacyText, legacyEnv)).toMatchObject({
      ready: true,
      humanizeVersion: "2.3.2"
    });
    expect(await runPreflight(config, readyRunner(), v2Text, v2Env)).toMatchObject({
      ready: true,
      humanizeVersion: "2.0.0",
      engineId: "super-sejong"
    });
  });

  it("fails each engine when it is given the other engine's version file", async () => {
    const legacyText = await readFile(engineVersionPath(config, legacyEnv), "utf8");
    const v2Text = await readFile(engineVersionPath(config, v2Env), "utf8");

    expect((await runPreflight(config, new FakeCommandRunner([]), v2Text, legacyEnv)).ready).toBe(false);
    expect((await runPreflight(config, new FakeCommandRunner([]), legacyText, v2Env)).ready).toBe(false);
  });
});
