export const HUMANIZE_MODEL = "gpt-6.1-sol" as const;
export const HUMANIZE_REASONING_EFFORT = "high" as const;

export const CLAUDE_MODEL = "claude-opus-5-5" as const;
export const CLAUDE_REASONING_EFFORT = "xhigh" as const;

export type EngineChoice = "codex" | "claude";

export interface ModelSettings { model: string; effort: string }
export interface ModelOption { id: string; label: string; efforts: string[] }
export type ModelOptions = Record<EngineChoice, ModelOption[]>;
export interface CliModelDefault { model: string; effort?: string }

const ENGINES = ['codex', 'claude'] as const;
const CONFIGURED_DEFAULTS: Record<EngineChoice, ModelSettings> = {
  codex: { model: HUMANIZE_MODEL, effort: HUMANIZE_REASONING_EFFORT },
  claude: { model: CLAUDE_MODEL, effort: CLAUDE_REASONING_EFFORT }
};
export const INVALID_MODEL_SETTINGS_MESSAGE = '선택한 CLI에서 지원하는 모델과 추론 레벨을 선택해 주세요.';

const codexEfforts = ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'];
const claudeEfforts = ['low', 'medium', 'high', 'xhigh', 'max'];
// Codex 0.167.0 model/list and Claude Code 2.1.323 initialize (2026-11-13). Served until a live list arrives
// (runtime/model-catalog.ts). Claude Haiku 4.5 is left out: it has no effort levels and the portal always sends one.
// These are selectable configurations, not a promise of account model access.
export const FALLBACK_MODEL_OPTIONS: ModelOptions = {
  codex: [
    { id: HUMANIZE_MODEL, label: 'GPT-6.1 Sol', efforts: codexEfforts },
    { id: 'gpt-6-astra', label: 'GPT-6 Astra', efforts: codexEfforts },
    { id: 'gpt-6.1-terra', label: 'GPT-6.1 Terra', efforts: codexEfforts },
    { id: 'gpt-6-sol', label: 'GPT-6 Sol', efforts: codexEfforts },
    { id: 'gpt-6-luna', label: 'GPT-6 Luna', efforts: codexEfforts.slice(0, 5) },
    { id: 'gpt-5.6-sol', label: 'GPT-5.6 Sol', efforts: codexEfforts },
    { id: 'gpt-5.6-terra', label: 'GPT-5.6 Terra', efforts: codexEfforts },
    { id: 'gpt-5.6-luna', label: 'GPT-5.6 Luna', efforts: codexEfforts.slice(0, 5) }
  ],
  claude: [
    { id: CLAUDE_MODEL, label: 'Claude Opus 5.5', efforts: claudeEfforts },
    { id: 'claude-fable-5-2', label: 'Claude Fable 5.2', efforts: claudeEfforts },
    { id: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', efforts: claudeEfforts },
    { id: 'claude-haiku-5-5', label: 'Claude Haiku 5.5', efforts: claudeEfforts },
    { id: 'claude-fable-5-1', label: 'Claude Fable 5.1', efforts: claudeEfforts },
    { id: 'claude-sonnet-5', label: 'Claude Sonnet 5', efforts: claudeEfforts },
    { id: 'claude-opus-5', label: 'Claude Opus 5', efforts: claudeEfforts },
    { id: 'claude-fable-5', label: 'Claude Fable 5', efforts: claudeEfforts },
    { id: 'claude-opus-4-8', label: 'Claude Opus 4.8', efforts: claudeEfforts },
    { id: 'claude-opus-4-7', label: 'Claude Opus 4.7', efforts: claudeEfforts },
    { id: 'claude-opus-4-6', label: 'Claude Opus 4.6', efforts: ['low', 'medium', 'high', 'max'] },
    { id: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6', efforts: ['low', 'medium', 'high', 'max'] }
  ]
};

// Process-wide: the live list replaces the fallback per engine. Ids and efforts go back to the CLI as arguments
// (Codex reads the effort inside a -c override), so only plain tokens are taken from a discovered list.
const MODEL_ID = /^[A-Za-z0-9][\w.:/@[\]-]{0,127}$/;
const EFFORT = /^[a-z][a-z0-9_-]{0,31}$/;
let options: ModelOptions;
let cliDefaults: Partial<Record<EngineChoice, CliModelDefault>>;
let defaults: Record<EngineChoice, ModelSettings>;

function defaultEffort(engine: EngineChoice, option: ModelOption): string {
  const cli = cliDefaults[engine];
  const wanted = [CONFIGURED_DEFAULTS[engine].effort, cli?.model === option.id ? cli.effort : undefined, 'high'];
  return wanted.find(level => level !== undefined && option.efforts.includes(level)) ?? option.efforts[0]!;
}
function defaultOption(engine: EngineChoice): ModelOption {
  const list = options[engine]; const cli = cliDefaults[engine]?.model;
  return list.find(item => item.id === CONFIGURED_DEFAULTS[engine].model) ?? list.find(item => item.id === cli) ?? list[0]!;
}
function computeDefaults(): void {
  defaults = Object.fromEntries(ENGINES.map(engine => {
    const option = defaultOption(engine);
    return [engine, { model: option.id, effort: defaultEffort(engine, option) }];
  })) as Record<EngineChoice, ModelSettings>;
}

export function resetModelCatalog(): void {
  options = { codex: FALLBACK_MODEL_OPTIONS.codex, claude: FALLBACK_MODEL_OPTIONS.claude };
  cliDefaults = {};
  computeDefaults();
}
resetModelCatalog();

export function getModelOptions(): Readonly<ModelOptions> { return options; }
// Served with the options so clients fall back to the same defaults as the server.
export function getModelDefaults(): Readonly<Record<EngineChoice, ModelSettings>> { return defaults; }

/** Replaces one engine's list with a discovered one. Returns false, keeping the current list, when no entry is usable. */
export function setLiveModels(engine: EngineChoice, models: readonly { id: string; label: string; efforts: readonly string[] }[], cliDefault?: CliModelDefault): boolean {
  const seen = new Set<string>(); const list: ModelOption[] = [];
  for (const model of models) {
    if (typeof model?.id !== 'string' || !MODEL_ID.test(model.id) || seen.has(model.id) || !Array.isArray(model.efforts)) continue;
    const efforts = [...new Set(model.efforts.filter(level => typeof level === 'string' && EFFORT.test(level)))];
    if (!efforts.length) continue;
    seen.add(model.id);
    list.push({ id: model.id, label: typeof model.label === 'string' && model.label.trim() ? model.label.trim() : model.id, efforts });
  }
  if (!list.length) return false;
  options = { ...options, [engine]: list };
  const cli = cliDefault && typeof cliDefault.model === 'string' ? { model: cliDefault.model, ...(typeof cliDefault.effort === 'string' ? { effort: cliDefault.effort } : {}) } : undefined;
  cliDefaults = { ...cliDefaults, [engine]: cli };
  computeDefaults();
  return true;
}

export function isKnownModel(engine: EngineChoice, model: unknown): boolean {
  return options[engine].some(item => item.id === model);
}

export function parseModelSettings(engine: EngineChoice, model?: unknown, effort?: unknown): ModelSettings {
  const id = model === undefined ? defaults[engine].model : model;
  const option = options[engine].find(item => item.id === id);
  // An omitted effort follows the defaults rule for the chosen model, so a model without the default level still works.
  const level = effort === undefined && option ? defaultEffort(engine, option) : effort;
  if (!option || typeof level !== 'string' || !option.efforts.includes(level)) throw new Error(INVALID_MODEL_SETTINGS_MESSAGE);
  return { model: option.id, effort: level };
}

/** Shape only, for a process whose list never goes live (the desktop main process); the worker checks validity. */
export function parseModelSelection(model: unknown, effort: unknown): ModelSettings {
  if (typeof model !== 'string' || !model || typeof effort !== 'string' || !effort) throw new Error(INVALID_MODEL_SETTINGS_MESSAGE);
  return { model, effort };
}

export function parseEngineChoice(value: unknown): EngineChoice | undefined {
  if (value === undefined || value === "codex") return "codex";
  if (value === "claude") return "claude";
  return undefined;
}
