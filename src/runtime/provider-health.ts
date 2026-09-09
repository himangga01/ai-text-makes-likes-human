import type { CommandRunner } from "../process/command-runner.js";
import type { EngineChoice } from "../engine/model-policy.js";

export interface ProviderHealth {
  reason?: 'unsupported-version' | 'invalid-command' | 'execution-error';
  ready: boolean;
  installed: boolean;
  authenticated: boolean;
  version?: string;
  message: string;
}
export type ProviderHealthMap = Record<EngineChoice, ProviderHealth>;

export async function probeProvider(kind: EngineChoice, command: string, cwd: string, runner: CommandRunner): Promise<ProviderHealth> {
  const label = kind === "codex" ? "Codex" : "Claude Code";
  let version: string | undefined;
  let installed = false;
  try {
    if (/\.(cmd|bat|ps1)$/i.test(command)) {
      return { ready: false, installed: false, authenticated: false, reason: 'invalid-command', message: `${label}의 네이티브 EXE 경로를 선택해 주세요.` };
    }
    const info = await runner.run({ command, args: ["--version"], cwd, timeoutMs: 10_000 });
    if (info.exitCode !== 0 || info.termination !== "exit") throw new Error("not installed");
    installed = true;
    version = `${info.stdout}\n${info.stderr}`.match(/\d+\.\d+\.\d+/)?.[0];
    if (kind === "codex" && version) {
      const [major = 0, minor = 0] = version.split(".").map(Number);
      if (major === 0 && minor < 149) return { ready: false, installed, authenticated: false, version, reason: 'unsupported-version', message: "Codex CLI 0.149.0 이상이 필요합니다." };
    }
    const auth = await runner.run({ command, args: kind === "codex" ? ["login", "status"] : ["auth", "status"], cwd, timeoutMs: 10_000 });
    let authenticated = false;
    if (auth.exitCode === 0 && auth.termination === "exit") {
      if (kind === "codex") authenticated = /Logged in/i.test(auth.stdout + auth.stderr);
      else {
        try { authenticated = JSON.parse(auth.stdout).loggedIn === true; } catch { /* invalid auth payload */ }
      }
    }
    return { ready: authenticated, installed, authenticated, version, message: authenticated ? `${label} 사용 가능` : kind === "codex" ? "서버의 Codex 로그인이 필요합니다." : "Claude Code 로그인이 필요합니다. claude auth login을 실행해 주세요." };
  } catch {
    return { ready: false, installed, authenticated: false, version, reason: 'execution-error', message: `${label} 실행 파일과 로그인 상태를 확인해 주세요.` };
  }
}
