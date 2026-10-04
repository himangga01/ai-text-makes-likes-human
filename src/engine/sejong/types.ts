/** Super Sejong Engine v2 contracts (DESIGN.md 3.12), mirroring engine_runtime/sejong/types.py.
 * Plan and CheckReport come from the Python engine as JSON (schemas in engine_runtime/sejong/schemas/);
 * SejongResponse is the writer's reply (response-schema.json in this directory).
 * start/end are code-point offsets into the chunk text; startU16/endU16 index the JS string.
 * Nothing imports this module yet: the legacy engine stays the default.
 */
import type { RewriteOptions, RewriteStrength } from '../rewrite-policy.js';

export const PLAN_SCHEMA = 'sejong-plan/1';
export const CHECK_SCHEMA = 'sejong-check/1';
export const ENGINE_ID = 'super-sejong';

export const SEJONG_LEVELS = ['HAPSYO', 'HAEYO', 'HAERA', 'HAE', 'HAO', 'HAGE', 'NOMINAL', 'NONE'] as const;
export const SEJONG_MOODS = ['DECL', 'INTERR', 'IMPER', 'PROPOS', 'EXCL'] as const;
export const SEJONG_GENRES = ['general', 'blog', 'essay', 'report', 'notice', 'document'] as const;
export const SEJONG_FAMILIES = ['floor', 'meaning', 'voice', 'cta', 'flow', 'clarity', 'norms', 'runaway', 'nli'] as const;
export const REQUEST_OUTCOMES = ['FIXED', 'UNTOUCHED', 'STILL_PRESENT', 'LOST', 'DECLINED'] as const;
/** The legacy closed list parsed by candidate-review.ts; v2 emits at most P0_CHANGE_RATE. */
export const LEGACY_REASONS = ['P0_CHANGE_RATE', 'P1_STYLE_TARGET', 'P2_ANTITHESIS', 'P3_GOLDEN',
  'P4_NUMBER_DROPPED', 'P5_MODALITY', 'P5_UNCERTAIN', 'UNKNOWN'] as const;

export type SpeechLevel = typeof SEJONG_LEVELS[number];
export type SentenceMood = typeof SEJONG_MOODS[number];
export type SejongGenre = typeof SEJONG_GENRES[number];
export type SejongFamily = typeof SEJONG_FAMILIES[number];
export type RequestOutcome = typeof REQUEST_OUTCOMES[number];
export type UnitKind = 'body' | 'heading' | 'list' | 'quote' | 'button';
export type DeterministicScope = 'all' | 'edited-only' | 'off';
export type FindingTier = 'FIX' | 'SUGGEST' | 'LEAVE';
/** REVIEW = an open-review nomination. */
export type RequestTier = 'FIX' | 'SUGGEST' | 'REVIEW';
export type SpanKind = 'quote' | 'number' | 'date' | 'money' | 'url' | 'email' | 'phone' | 'handle' | 'hashtag' |
  'name' | 'code' | 'markdown' | 'heading' | 'footnote' | 'cmc' | 'colloquial' | 'discourse';
export type SentenceStatus = 'unchanged' | 'deterministic' | 'accepted' | 'retry' | 'rejected' | 'reverted';
export type GatePolicy = 'accept' | 'retry' | 'rollback' | 'accept-with-warning' | 'error';

/** Violation, repair and shadow codes. python-engine.ts drops any other shadowFailures entry. */
export const SEJONG_CODE = /^[a-z_]{1,60}$/;
export function isSejongCode(value: unknown): value is string {
  return typeof value === 'string' && SEJONG_CODE.test(value);
}

/* ---------- plan (sejong-plan/1) ---------- */

export interface VoiceSignature {
  level: SpeechLevel;
  mood: SentenceMood;
  /** -시- on the final predicate. */
  honSi: boolean;
  /** -시- anywhere in the sentence; every one is locked (DESIGN 9.2a item 3). */
  siCount: number;
  stance: string | null;
  persona: string[];
  humble: boolean;
  cmc: string[];
  discourse: string[];
  /** Final eojeol. */
  final: string;
  addressee?: string | null;
}

export interface PlanSentence {
  id: string;
  start: number;
  end: number;
  startU16: number;
  endU16: number;
  para: number;
  kind: UnitKind;
  voice: VoiceSignature;
  /** CTA ledger id when the sentence is a CTA unit. */
  cta: string | null;
  meaning: string[];
  findings: string[];
}

export interface ProtectedSpan {
  kind: SpanKind;
  start: number;
  end: number;
  policy: 'freeze' | 'keep-token';
}

export interface CtaUnit {
  id: string;
  sentence: string;
  form: 'prohibitive' | 'request' | 'request_wish' | 'trial' | 'imperative' | 'suggestion' | 'option' |
    'advisory' | 'instruction' | 'invitation' | 'nominal' | 'conditional_offer';
  /** 0-5 */
  force: number;
  tier: 'engage' | 'contact' | 'navigate' | 'task';
  polarity: 'pos' | 'neg';
  action: string[];
  object: string | null;
  condition: string | null;
  deadline: string[];
  channel: string[];
  benefit: string[];
  intensity: string[];
  level: 'hapsyo' | 'haeyo' | 'haera' | 'hae' | 'other';
  honSi: boolean;
}

export interface PlanFinding {
  id: string;
  rule: string;
  tier: FindingTier;
  action: 'deterministic' | 'request' | 'report';
  sentence: string;
  start: number;
  end: number;
  fix: string | null;
}

export interface PlanRequest {
  id: string;
  sentence: string;
  rules: string[];
  tier: RequestTier;
  allowSplit: boolean;
  guides: string[];
}

export interface DeterministicFix {
  finding: string;
  sentence: string;
  start: number;
  end: number;
  before: string;
  after: string;
}

export interface PlanOptions {
  inputKind: RewriteOptions['inputKind'];
  strength: RewriteStrength;
  genre: SejongGenre;
  fixColloquial: boolean;
  deterministicFix: DeterministicScope;
  openReview: boolean;
  allowFullText: boolean;
}

export interface Plan {
  schema: typeof PLAN_SCHEMA;
  engine: { id: typeof ENGINE_ID; version: string };
  chunk: { index: number; total: number; sourceSha256: string; chars: number };
  options: PlanOptions;
  sentences: PlanSentence[];
  protected: ProtectedSpan[];
  ctaLedger: CtaUnit[];
  findings: PlanFinding[];
  requests: PlanRequest[];
  deterministic: DeterministicFix[];
  /** Prompt context only; never used in a decision (OD 1). */
  profile: { dominant: SpeechLevel; share: number; mixed: boolean; line: string };
  seam: { prev: [number, number]; next: [number, number] };
  openReview: { enabled: boolean; maxSentences: number };
  needsModel: boolean;
  stats: { findingsByTier: Partial<Record<FindingTier, number>>; [key: string]: unknown };
}

/* ---------- check report (sejong-check/1) ---------- */

export interface SejongViolation {
  code: string;
  family?: SejongFamily;
  severity?: 'hard' | 'soft' | 'info';
  sentence?: string;
  /** Codes and labels only (e.g. "HAPSYO->HAEYO"), never document text. */
  detail: string;
  /** Form the retry prompt asks the writer to keep. */
  keep?: string | null;
}

export interface SentenceVerdict {
  id: string;
  request: string | null;
  status: SentenceStatus;
  codes: string[];
  repairs: string[];
}

export interface RetryRequest {
  id: string;
  sentence: string;
  violations: SejongViolation[];
}

export interface CheckCounts {
  revertedSentences: number;
  revertedByFamily: Partial<Record<SejongFamily, number>>;
  collateralReverts: number;
  voiceGrafts: number;
  cmcRestored: number;
  normFixes: number;
  repairedParticles: number;
  removedCommas: number;
  restoredSentences: number;
}

export interface CheckReport {
  /** The first five keys are the legacy gate JSON that PythonEngine.verify() parses. */
  gate: { exit_code: 0 | 1 | 2 | 3 };
  hardFailures: string[];
  warningReasons: { version: 1; codes: Array<typeof LEGACY_REASONS[number]> };
  policy: GatePolicy;
  shadowFailures: string[];
  schema: typeof CHECK_SCHEMA;
  attempt: 1 | 2;
  sentences: SentenceVerdict[];
  retry: RetryRequest[];
  requestStatus: Record<RequestOutcome, number>;
  counts: CheckCounts;
  changeRate: number;
}

/* ---------- writer reply (response-schema.json) ---------- */

export interface SejongReplacement {
  /** A request id (R…), or a sentence id (S…) only when open review is enabled. */
  id: string;
  /** The whole rewritten sentence, without newlines. */
  text: string;
  reason: string;
}

export interface SejongResponse {
  replacements: SejongReplacement[];
  /** Empty unless plan.allowFullText and replacements is empty. */
  rewrittenText: string;
  warnings: string[];
}
