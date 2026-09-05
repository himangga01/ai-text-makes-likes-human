export const HUMANIZE_MODEL = "gpt-5.6-sol" as const;
export const HUMANIZE_REASONING_EFFORT = "medium" as const;

export const CLAUDE_MODEL = "claude-opus-5" as const;
export const CLAUDE_REASONING_EFFORT = "medium" as const;

export type EngineChoice = "codex" | "claude";

export function parseEngineChoice(value: unknown): EngineChoice | undefined {
  if (value === undefined || value === "codex") return "codex";
  if (value === "claude") return "claude";
  return undefined;
}
