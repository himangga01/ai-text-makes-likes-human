/** Super Sejong Engine v2 configuration (DESIGN.md 5.4); same rules as engine_runtime/sejong/config.py.
 * Values are trimmed and lower-cased; unset or empty means the default; an unknown value falls back to
 * the default (a typo must not fail a job) and the variable name is listed in `rejected`. Values are
 * never echoed. The floor and runaway families are enforced in every mode and have no variable.
 */
import type { RewriteStrength } from '../rewrite-policy.js';
import type { SejongFamily, SejongGenre, DeterministicScope } from './types.js';

export type SejongEngineName = 'legacy' | 'v2';
export type FamilyMode = 'enforce' | 'shadow' | 'off';
export type OverridableFamily = Exclude<SejongFamily, 'floor' | 'runaway'>;
/** Lowest strength that gets the open review; `always` includes normal. */
export type OpenReviewSetting = 'medium' | 'strong' | 'always' | 'off';

export interface SejongFlags {
  engine: SejongEngineName;
  mode: FamilyMode;
  /** SUPER_SEJONG_GATE_<FAMILY> overrides only; NLI is capped at shadow. */
  gates: Partial<Record<OverridableFamily, FamilyMode>>;
  v2Shadow: boolean;
  fixColloquial: boolean;
  deterministicFix: DeterministicScope;
  openReview: OpenReviewSetting;
  genreDefault: SejongGenre;
  worker: boolean;
  /** 'worker' only when the worker is on: Kiwi never runs per spawn (OD 7). */
  kiwi: 'off' | 'worker';
  /** Variables whose value was not used as given. */
  rejected: string[];
}

export const OVERRIDABLE_FAMILIES: readonly OverridableFamily[] = ['meaning', 'voice', 'cta', 'flow', 'clarity', 'norms', 'nli'];
const FAMILY_MODES: readonly FamilyMode[] = ['enforce', 'shadow', 'off'];
const CHOICES = {
  SUPER_SEJONG_ENGINE: ['legacy', 'v2'],
  SUPER_SEJONG_MODE: FAMILY_MODES,
  SUPER_SEJONG_V2_SHADOW: ['0', '1'],
  SUPER_SEJONG_FIX_COLLOQUIAL: ['0', '1'],
  SUPER_SEJONG_DETERMINISTIC_FIX: ['all', 'edited-only', 'off'],
  // Lead decision 2026-10-04 (DESIGN 9.2a item 2): medium gets the open review, so it is the default.
  SUPER_SEJONG_OPEN_REVIEW: ['medium', 'strong', 'always', 'off'],
  SUPER_SEJONG_GENRE_DEFAULT: ['general', 'blog', 'essay', 'report', 'notice', 'document'],
  SUPER_SEJONG_WORKER: ['off', 'on'],
  SUPER_SEJONG_KIWI: ['off', 'worker']
} as const satisfies Record<string, readonly string[]>;
type ChoiceName = keyof typeof CHOICES;

const OPEN_REVIEW: Record<OpenReviewSetting, readonly RewriteStrength[]> = {
  medium: ['medium', 'strong', 'very-strong'],
  strong: ['strong', 'very-strong'],
  always: ['normal', 'medium', 'strong', 'very-strong'],
  off: []
};
// clarity has no false-block estimate yet, so it starts in shadow; NLI needs a licence-clean model, so it starts off.
const DEFAULTS: Record<FamilyMode, Record<OverridableFamily, FamilyMode>> = {
  enforce: { meaning: 'enforce', voice: 'enforce', cta: 'enforce', flow: 'enforce', clarity: 'shadow', norms: 'enforce', nli: 'off' },
  shadow: { meaning: 'enforce', voice: 'shadow', cta: 'shadow', flow: 'shadow', clarity: 'shadow', norms: 'shadow', nli: 'off' },
  off: { meaning: 'off', voice: 'off', cta: 'off', flow: 'off', clarity: 'off', norms: 'off', nli: 'off' }
};

function read(env: NodeJS.ProcessEnv, name: string): string {
  return (env[name] ?? '').trim().toLowerCase();
}

/** Which engine produces the delivered text; anything but `v2` keeps the legacy engine. */
export function selectEngine(env: NodeJS.ProcessEnv = process.env): SejongEngineName {
  return read(env, 'SUPER_SEJONG_ENGINE') === 'v2' ? 'v2' : 'legacy';
}

export function sejongFlags(env: NodeJS.ProcessEnv = process.env): SejongFlags {
  const rejected: string[] = [];
  const choice = <N extends ChoiceName>(name: N): typeof CHOICES[N][number] => {
    const allowed: readonly string[] = CHOICES[name];
    const value = read(env, name);
    if (!value) return CHOICES[name][0];
    if (!allowed.includes(value)) {
      rejected.push(name);
      return CHOICES[name][0];
    }
    return value as typeof CHOICES[N][number];
  };
  const engine = choice('SUPER_SEJONG_ENGINE');
  const mode = choice('SUPER_SEJONG_MODE');
  const v2Shadow = choice('SUPER_SEJONG_V2_SHADOW') === '1';
  const fixColloquial = choice('SUPER_SEJONG_FIX_COLLOQUIAL') === '1';
  const deterministicFix = choice('SUPER_SEJONG_DETERMINISTIC_FIX');
  const openReview = choice('SUPER_SEJONG_OPEN_REVIEW');
  const genreDefault = choice('SUPER_SEJONG_GENRE_DEFAULT');
  const worker = choice('SUPER_SEJONG_WORKER') === 'on';
  let kiwi = choice('SUPER_SEJONG_KIWI');
  const gates: Partial<Record<OverridableFamily, FamilyMode>> = {};
  for (const family of OVERRIDABLE_FAMILIES) {
    const name = `SUPER_SEJONG_GATE_${family.toUpperCase()}`;
    const value = read(env, name);
    if (!value) continue;
    const selected = FAMILY_MODES.find(item => item === value);
    if (!selected) rejected.push(name);
    else if (family === 'nli' && selected === 'enforce') {
      rejected.push(name); // no licence-clean NLI model: shadow at most (OD 7)
      gates.nli = 'shadow';
    } else gates[family] = selected;
  }
  if (kiwi === 'worker' && !worker) {
    rejected.push('SUPER_SEJONG_KIWI');
    kiwi = 'off';
  }
  return { engine, mode, gates, v2Shadow, fixColloquial, deterministicFix, openReview, genreDefault, worker, kiwi, rejected };
}

/** Mode of one v2 verification family. Describes v2 only; legacy keeps the v1 SUPER_SEJONG_MODE semantics. */
export function familyMode(flags: SejongFlags, family: SejongFamily): FamilyMode {
  if (family === 'floor' || family === 'runaway') return 'enforce';
  return flags.gates[family] ?? DEFAULTS[flags.mode][family];
}

/** SUPER_SEJONG_MODE=off keeps FIX requests and deterministic fixes only. */
export function suggestRequestsEnabled(flags: SejongFlags): boolean {
  return flags.mode !== 'off';
}

/** Open review is an optional edit like a SUGGEST request, so mode off disables it too. */
export function openReviewEnabled(flags: SejongFlags, strength: RewriteStrength): boolean {
  return suggestRequestsEnabled(flags) && OPEN_REVIEW[flags.openReview].includes(strength);
}
