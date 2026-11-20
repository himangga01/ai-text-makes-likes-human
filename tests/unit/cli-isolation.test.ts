import { existsSync } from "node:fs";
import { readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  CLAUDE_ISOLATION_ARGS,
  CODEX_APP_SERVER_ISOLATION_ARGS,
  CODEX_EXEC_ISOLATION_ARGS,
  inScratchDirectory
} from "../../src/engine/cli-isolation.js";

describe("inScratchDirectory", () => {
  it("hands the task a new empty directory under the OS temp directory and removes it with its contents", async () => {
    let seen = "";
    const result = await inScratchDirectory("isolation-test-", async directory => {
      seen = directory;
      expect(path.dirname(directory)).toBe(path.resolve(tmpdir()));
      expect(await readdir(directory)).toEqual([]);
      await writeFile(path.join(directory, "left-behind.txt"), "x", "utf8");
      return 42;
    });
    expect(result).toBe(42);
    expect(existsSync(seen)).toBe(false);
  });

  it("removes the directory when the task fails and passes the task's error through", async () => {
    let seen = "";
    await expect(inScratchDirectory("isolation-test-", async directory => {
      seen = directory;
      throw new Error("task failed");
    })).rejects.toThrow("task failed");
    expect(existsSync(seen)).toBe(false);
  });
});

describe("CLI isolation flags", () => {
  it("only ever turns Codex features off and keeps the read-only sandbox last", () => {
    expect(CODEX_EXEC_ISOLATION_ARGS).not.toContain("--enable");
    expect(CODEX_APP_SERVER_ISOLATION_ARGS).not.toContain("--enable");
    expect(CODEX_EXEC_ISOLATION_ARGS.slice(-2)).toEqual(["--sandbox", "read-only"]);
    for (const feature of ["code_mode_host", "shell_tool", "multi_agent", "hooks", "plugins"]) {
      expect(CODEX_EXEC_ISOLATION_ARGS.join(" ")).toContain(`--disable ${feature}`);
    }
    expect(CODEX_EXEC_ISOLATION_ARGS).toContain('web_search="disabled"');
    expect(CODEX_EXEC_ISOLATION_ARGS).toContain("--ignore-user-config");
  });

  it("starts Claude Code restricted, in safe mode and without tools", () => {
    expect(CLAUDE_ISOLATION_ARGS).toEqual(expect.arrayContaining(["--restricted", "--safe-mode", "--disable-slash-commands", "--strict-mcp-config"]));
    expect(CLAUDE_ISOLATION_ARGS[CLAUDE_ISOLATION_ARGS.indexOf("--tools") + 1]).toBe("");
    expect(CLAUDE_ISOLATION_ARGS).not.toContain("--bare");
  });
});
