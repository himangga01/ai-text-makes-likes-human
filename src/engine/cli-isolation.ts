import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

/** How the portal starts the AI CLIs on untrusted document text.
 *
 * A rewrite needs the model and nothing else: no command execution, file access, web access, sub-agents or
 * plugins, and none of the operator's own CLI setup (instructions, memory, skills, hooks). Each CLI is
 * therefore started with every tool and extension it lets us turn off, from an empty private directory
 * outside any project. The flags below were checked against Codex CLI 0.170 and Claude Code 2.1.329. */

/** `codex exec` flags placed before the model and output options. Most entries remove a tool or an extension
 * outright, so the result does not depend on the model's tool mode. Code-mode models (the current GPT
 * lineup) reach every tool through the code-mode host; with the host disabled their tool calls fail
 * closed. The read-only sandbox stays as the last line for anything a future CLI might add. */
export const CODEX_EXEC_ISOLATION_ARGS: readonly string[] = [
  "--ephemeral",
  "--skip-git-repo-check",
  "--ignore-user-config",
  "--ignore-rules",
  // Tools
  "--disable", "code_mode_host",
  "--disable", "shell_tool",
  "--disable", "unified_exec",
  "--disable", "view_image",
  "--disable", "image_generation",
  "--disable", "browser_use",
  "--disable", "computer_use",
  "--disable", "apps",
  "--disable", "multi_agent",
  "--config", "agents.enabled=false",
  "--disable", "sleep_tool",
  "--disable", "goals",
  "--disable", "tool_suggest",
  "--config", 'web_search="disabled"',
  "--config", "tools.experimental_request_user_input.enabled=false",
  // The operator's own Codex setup: hooks, plugins, memories, skills, project instructions
  "--disable", "hooks",
  "--disable", "plugins",
  "--disable", "remote_plugin",
  "--disable", "memories",
  "--disable", "skill_search",
  "--disable", "skill_mcp_dependency_install",
  "--disable", "workspace_dependencies",
  "--config", "skills.bundled.enabled=false",
  "--config", "skills.include_instructions=false",
  "--config", "project_doc_max_bytes=0",
  // Context sections about tools and the machine that a rewrite does not use
  "--config", "include_permissions_instructions=false",
  "--config", "include_apps_instructions=false",
  "--config", "include_environment_context=false",
  "--sandbox", "read-only"
];

/** `codex app-server` (model discovery) has no --ignore-user-config. It only answers initialize and model/list
 * there and starts no session, so it is just kept from loading the operator's extensions. */
export const CODEX_APP_SERVER_ISOLATION_ARGS: readonly string[] = [
  "--disable", "hooks",
  "--disable", "plugins",
  "--disable", "remote_plugin",
  "--disable", "apps"
];

/** `claude -p` flags placed after -p. --restricted ignores user, project and local settings files (and with
 * them their hooks, skills and plugins); --safe-mode turns off the remaining customizations (CLAUDE.md,
 * installed plugins, hooks, custom agents, output styles) while sign-in keeps working;
 * --disable-slash-commands drops the bundled skills; --tools "" leaves the model no built-in tool and
 * --strict-mcp-config no MCP server. */
export const CLAUDE_ISOLATION_ARGS: readonly string[] = [
  "--restricted",
  "--safe-mode",
  "--disable-slash-commands",
  "--strict-mcp-config",
  "--tools",
  "",
  "--no-session-persistence"
];

/** Environment switches that keep CLAUDE.md files and auto memory out even if a flag's coverage changes. */
export const CLAUDE_ISOLATION_ENV: Readonly<Record<string, string>> = {
  CLAUDE_CODE_DISABLE_CLAUDE_MDS: "1",
  CLAUDE_CODE_DISABLE_AUTO_MEMORY: "1"
};

/** Runs `task` with a new empty private directory under the OS temporary directory and removes the directory
 * afterwards. Started there, a CLI finds no project instructions, settings or git repository; removal is best
 * effort so that a lingering handle (Windows) cannot replace the task's own result or error. */
export async function inScratchDirectory<T>(prefix: string, task: (directory: string) => Promise<T>): Promise<T> {
  const directory = await mkdtemp(path.join(os.tmpdir(), prefix));
  try {
    return await task(directory);
  } finally {
    await rm(directory, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 }).catch(() => undefined);
  }
}
