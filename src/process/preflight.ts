import path from "node:path";
import type { AppConfig } from "../config.js";
import type { CommandRunner } from "./command-runner.js";
import { probeProvider, type ProviderHealthMap } from "../runtime/provider-health.js";
import { selectEngine } from "../engine/sejong/config.js";
import {
  engineVersionAtLeast,
  ENGINE_VERSION_FILE,
  MINIMUM_ENGINE_VERSION,
  parseEngineVersion,
  SUPPORTED_ENGINE_SCHEMA
} from "../engine/sejong/version.js";

export interface PreflightReport {
  ready: boolean;
  providers?: ProviderHealthMap;
  nodeVersion: string;
  pythonVersion?: string;
  codexVersion?: string;
  /** Version of the selected engine: the vendor label under legacy, the Super Sejong version under v2. */
  humanizeVersion?: string;
  /** Set only when v2 is selected, so legacy reports keep their shape. */
  engineId?: "super-sejong";
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

/** ENGINE_VERSION file of the engine selected by SUPER_SEJONG_ENGINE: the vendor pin under legacy (default),
 * engine_runtime/sejong under v2. runPreflight needs the text of this file. */
export function engineVersionPath(
  config: Pick<AppConfig, "projectRoot" | "vendorRoot">,
  env: NodeJS.ProcessEnv = process.env
): string {
  return selectEngine(env) === "v2"
    ? path.join(config.projectRoot, "engine_runtime", "sejong", ENGINE_VERSION_FILE)
    : path.join(config.vendorRoot, ENGINE_VERSION_FILE);
}

/** v2 pin: id super-sejong, at least MINIMUM_ENGINE_VERSION, and the schema this build's types read.
 * The failure message names the requirement only, never the file content. */
function checkSejongVersion(text: string): string | undefined {
  try {
    const found = parseEngineVersion(text);
    if (engineVersionAtLeast(found.version) && found.schema === SUPPORTED_ENGINE_SCHEMA) return found.version;
  } catch {
    // A malformed version file is the same packaging failure as a wrong one.
  }
  return undefined;
}

export async function runPreflight(
  config: AppConfig,
  runner: CommandRunner,
  engineVersionText: string,
  env: NodeJS.ProcessEnv = process.env
): Promise<PreflightReport> {
  try {
    const v2 = selectEngine(env) === "v2";
    let engineVersion: string;
    if (v2) {
      const sejongVersion = checkSejongVersion(engineVersionText);
      if (sejongVersion === undefined) {
        return unavailable(`Super Sejong 엔진 ${MINIMUM_ENGINE_VERSION} 이상(스키마 ${SUPPORTED_ENGINE_SCHEMA})이 필요합니다.`);
      }
      engineVersion = sejongVersion;
    } else {
      engineVersion = parseVersion(engineVersionText, "humanize engine");
      if (engineVersion !== "2.3.2") {
        return unavailable("Humanize 엔진 2.3.2가 필요합니다.");
      }
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

    const codex = await probeProvider("codex", config.codexCommand, config.projectRoot, runner);
    const claude = await probeProvider("claude", config.claudeCommand, config.projectRoot, runner);
    const ready = codex.ready || claude.ready;
    return {
      ready,
      nodeVersion: process.versions.node,
      pythonVersion,
      codexVersion: codex.version,
      humanizeVersion: engineVersion,
      ...(v2 ? { engineId: "super-sejong" as const } : {}),
      providers: { codex, claude },
      ...(ready ? {} : { errorCode: "ENGINE_UNAVAILABLE" as const, message: codex.message })
    };
  } catch {
    return unavailable("서버의 변환 엔진을 사용할 수 없습니다.");
  }
}
