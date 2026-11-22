import { describe, expect, it } from "vitest";
import { childEnvironment, isInheritedVariable } from "../../src/process/child-env.js";

describe("childEnvironment", () => {
  it("drops agent-session tokens, sockets and credential helpers", () => {
    const env = childEnvironment({
      PATH: "/usr/bin", HOME: "/Users/a", LANG: "ko_KR.UTF-8", LC_ALL: "ko_KR.UTF-8",
      SUPER_SEJONG_V2_SHADOW: "1", CODEX_CHUNK_CONCURRENCY: "1", HUMANIZE_RUNTIME_ROOT: "/x",
      ANTHROPIC_API_KEY: "k", CLAUDE_CONFIG_DIR: "/c",
      CLAUDECODE: "1", CLAUDE_CODE_MESSAGING_TOKEN: "t", CLAUDE_CODE_SESSION_ID: "s", ORCA_AGENT_HOOK_TOKEN: "o",
      SSH_AUTH_SOCK: "/tmp/ssh", GIT_ASKPASS: "/a", SSH_ASKPASS: "/b", GITHUB_TOKEN: "g", AWS_SECRET_ACCESS_KEY: "w"
    });
    expect(Object.keys(env).sort()).toEqual([
      "ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR", "CODEX_CHUNK_CONCURRENCY", "HOME", "HUMANIZE_RUNTIME_ROOT",
      "LANG", "LC_ALL", "PATH", "SUPER_SEJONG_V2_SHADOW"
    ]);
  });

  it("keeps Windows system variables whatever their case", () => {
    for (const name of ["SystemRoot", "windir", "ComSpec", "PATHEXT", "LOCALAPPDATA", "Path", "ProgramFiles(x86)"]) {
      expect(isInheritedVariable(name)).toBe(true);
    }
  });

  it("applies extra values on top, even outside the allowlist", () => {
    expect(childEnvironment({ PATH: "/p", NO_COLOR: "0" }, { NO_COLOR: "1", NODE_COMMAND: "/n" }))
      .toEqual({ PATH: "/p", NO_COLOR: "1", NODE_COMMAND: "/n" });
  });
});
