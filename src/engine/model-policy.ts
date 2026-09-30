export const HUMANIZE_MODEL = "gpt-5.6-sol" as const;
export const HUMANIZE_REASONING_EFFORT = "medium" as const;

export const CLAUDE_MODEL = "claude-fable-5-1" as const;
export const CLAUDE_REASONING_EFFORT = "high" as const;

export type EngineChoice = "codex" | "claude";

export interface ModelSettings { model: string; effort: string }
// Served with the options so clients fall back to the same defaults as the server.
export const MODEL_DEFAULTS: Record<EngineChoice, ModelSettings> = {
  codex: { model: HUMANIZE_MODEL, effort: HUMANIZE_REASONING_EFFORT },
  claude: { model: CLAUDE_MODEL, effort: CLAUDE_REASONING_EFFORT }
};
const codexEfforts = ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'];
const claudeEfforts = ['low', 'medium', 'high', 'xhigh', 'max'];
// Codex 0.159.0 model catalog and Claude Code 2.1.284 model configuration (2026-09-30).
// GPT-5.5 is omitted on purpose: it retires 2026-10-14.
// These are selectable configurations, not a promise of account model access.
export const MODEL_OPTIONS = {
  codex: [
    { id: HUMANIZE_MODEL, label: 'GPT-5.6 Sol', efforts: codexEfforts },
    { id: 'gpt-6-astra', label: 'GPT-6 Astra', efforts: codexEfforts },
    { id: 'gpt-6-sol', label: 'GPT-6 Sol', efforts: codexEfforts },
    { id: 'gpt-6-luna', label: 'GPT-6 Luna', efforts: codexEfforts.slice(0, 5) },
    { id: 'gpt-5.6-terra', label: 'GPT-5.6 Terra', efforts: codexEfforts },
    { id: 'gpt-5.6-luna', label: 'GPT-5.6 Luna', efforts: codexEfforts.slice(0, 5) }
  ],
  claude: [
    { id: CLAUDE_MODEL, label: 'Claude Fable 5.1', efforts: claudeEfforts },
    { id: 'claude-opus-5-5', label: 'Claude Opus 5.5', efforts: claudeEfforts },
    { id: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', efforts: claudeEfforts },
    { id: 'claude-sonnet-5', label: 'Claude Sonnet 5', efforts: claudeEfforts },
    { id: 'claude-opus-5', label: 'Claude Opus 5', efforts: claudeEfforts }
  ]
};

export function parseModelSettings(engine: EngineChoice, model?: unknown, effort?: unknown): ModelSettings {
  const id = model === undefined ? (engine === 'codex' ? HUMANIZE_MODEL : CLAUDE_MODEL) : model;
  const level = effort === undefined ? (engine === 'codex' ? HUMANIZE_REASONING_EFFORT : CLAUDE_REASONING_EFFORT) : effort;
  const option = MODEL_OPTIONS[engine].find(item => item.id === id);
  if (!option || typeof level !== 'string' || !option.efforts.includes(level)) {
    throw new Error('선택한 CLI에서 지원하는 모델과 추론 레벨을 선택해 주세요.');
  }
  return { model: option.id, effort: level };
}

export function parseEngineChoice(value: unknown): EngineChoice | undefined {
  if (value === undefined || value === "codex") return "codex";
  if (value === "claude") return "claude";
  return undefined;
}
