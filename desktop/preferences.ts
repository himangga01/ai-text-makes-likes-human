import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { parseEngineChoice, parseModelSelection, parseModelSettings, type EngineChoice, type ModelSettings } from '../src/engine/model-policy.js';
import { parseRewriteStrength, type RewriteStrength } from '../src/engine/rewrite-policy.js';

export interface Preferences {
  selectedEngine: EngineChoice;
  commands: Partial<Record<EngineChoice, string>>;
  models: Partial<Record<EngineChoice, ModelSettings>>;
  rewriteStrength: RewriteStrength;
}
export function defaultPreferences(): Preferences {
  return {selectedEngine:'codex',commands:{},models:{},rewriteStrength:'normal'};
}
export async function loadPreferences(file: string): Promise<Preferences> {
  const preferences = defaultPreferences();
  try {
    const saved = JSON.parse(await readFile(file, 'utf8'));
    preferences.selectedEngine = parseEngineChoice(saved?.selectedEngine) ?? 'codex';
    try { preferences.rewriteStrength = parseRewriteStrength(saved?.rewriteStrength); } catch { /* Legacy or malformed saved value. */ }
    for (const kind of ['codex','claude'] as const) {
      // Only a model the user saved is restored; an absent entry must keep following future defaults. This process
      // never sees the worker's live list, so a well-formed choice is kept and the worker and UI judge it; only a
      // legacy entry without an effort is completed from the fallback list.
      const value=saved?.models?.[kind];
      if (value?.model !== undefined) try {
        preferences.models[kind] = value.effort === undefined ? parseModelSettings(kind,value.model) : parseModelSelection(value.model,value.effort);
      } catch { /* Malformed selection defaults on use. */ }
      if (typeof saved?.commands?.[kind] === 'string') preferences.commands[kind] = saved.commands[kind];
    }
  } catch { /* First run or malformed JSON. */ }
  return preferences;
}
export async function savePreferences(file: string, preferences: Preferences): Promise<void> {
  const value = JSON.stringify(preferences);
  await mkdir(path.dirname(file), {recursive:true});
  await writeFile(file,value,'utf8');
}
export async function selectRewriteStrength(preferences: Preferences, value: unknown, persist: () => Promise<void>): Promise<RewriteStrength> {
  preferences.rewriteStrength = parseRewriteStrength(value);
  await persist();
  return preferences.rewriteStrength;
}
