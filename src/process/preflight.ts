import type { AppConfig } from "../config.js";
import type { CommandRunner } from "./command-runner.js";

export interface PreflightReport {
  ready: boolean;
  nodeVersion: string;
  pythonVersion?: string;
  codexVersion?: string;
  humanizeVersion?: string;
  errorCode?: "ENGINE_UNAVAILABLE";
  message?: string;
}

function parseVersion(text: string, label: string): string {
  const match = text.match(/(\d+)\.(\d+)\.(\d+)/);
  if (!match) throw new Error(`Unable to parse ${label} version`);
  return `${match[1]}.${match[2]}.${match[3]}`;
}

function atLeast(actual: string, minimum: string): boolean {
  const current = actual.split(".").map(Number);
  const required = minimum.split(".").map(Number);
  for (let index = 0; index < 3; index += 1) {
    const a = current[index] ?? 0;
    const b = required[index] ?? 0;
    if (a > b) return true;
    if (a < b) return false;
  }
  return true;
}

function unavailable(message: string): PreflightReport {
  return {
    ready: false,
    nodeVersion: process.versions.node,
    errorCode: "ENGINE_UNAVAILABLE",
    message
  };
}

export async function runPreflight(
  config: AppConfig,
  runner: CommandRunner,
  engineVersionText: string
): Promise<PreflightReport> {
  try {
    const engineVersion = parseVersion(engineVersionText, "humanize engine");
    if (engineVersion !== "2.3.2") {
      return unavailable("Humanize 엔진 2.3.2가 필요합니다.");
    }

    const python = await runner.run({
      command: config.pythonCommand,
      args: ["--version"],
      cwd: config.projectRoot,
      timeoutMs: 10_000
    });
    if (python.exitCode !== 0 || python.termination !== "exit") {
      return unavailable("Python 3.11 이상이 필요합니다.");
    }
    const pythonVersion = parseVersion(
      `${python.stdout}\n${python.stderr}`,
      "Python"
    );
    if (!atLeast(pythonVersion, "3.11.0")) {
      return unavailable("Python 3.11 이상이 필요합니다.");
    }

    const codex = await runner.run({
      command: config.codexCommand,
      args: ["--version"],
      cwd: config.projectRoot,
      timeoutMs: 10_000
    });
    if (codex.exitCode !== 0 || codex.termination !== "exit") {
      return unavailable("Codex CLI 0.149.0 이상이 필요합니다.");
    }
    const codexVersion = parseVersion(
      `${codex.stdout}\n${codex.stderr}`,
      "Codex"
    );
    if (!atLeast(codexVersion, "0.149.0")) {
      return unavailable("Codex CLI 0.149.0 이상이 필요합니다.");
    }

    const login = await runner.run({
      command: config.codexCommand,
      args: ["login", "status"],
      cwd: config.projectRoot,
      timeoutMs: 10_000
    });
    if (
      login.exitCode !== 0 ||
      login.termination !== "exit" ||
      !login.stdout.includes("Logged in")
    ) {
      return unavailable("서버의 Codex 로그인이 필요합니다.");
    }

    return {
      ready: true,
      nodeVersion: process.versions.node,
      pythonVersion,
      codexVersion,
      humanizeVersion: engineVersion
    };
  } catch {
    return unavailable("서버의 변환 엔진을 사용할 수 없습니다.");
  }
}
