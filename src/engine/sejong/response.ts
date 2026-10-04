/** Super Sejong Engine v2 writer-reply parser (DESIGN.md 3.5 output schema, 3.6 whole-response rules).
 * The reply must match response-schema.json exactly (hand-coded here, pinned to the file by
 * tests/unit/sejong-response.test.ts). On top of the schema:
 * - every id names a request of the plan (or of the retry list on attempt 2); no id twice;
 * - `S…` ids only when the plan enables the open review, never for a requested sentence, at most
 *   plan.openReview.maxSentences of them;
 * - `rewrittenText` non-empty only when plan.options.allowFullText, on attempt 1, with no replacements.
 * Any of these makes the whole reply unusable (MODEL_OUTPUT_UNUSABLE, which counts as the attempt).
 * A newline inside one replacement's text rejects that replacement only (3.6: status `rejected`,
 * eligible for retry); the reply stays usable. Error messages carry codes and ids, never reply text.
 */
import { EngineError } from '../errors.js';
import type { Plan, RetryRequest, SejongReplacement, SejongResponse } from './types.js';

/** Limits of response-schema.json. String lengths count code points, as the Python validator does. */
export const RESPONSE_LIMITS = {
  replacements: 200, textMin: 1, textMax: 4000, reasonMax: 60, warnings: 20, warningMax: 300,
  id: /^(R|S)[0-9]{1,4}$/
} as const;
/** Upper bound on the raw reply before JSON parsing: 200 × 4,000 + a full-text reply of a 15k chunk, with room. */
export const MAX_REPLY_CHARS = 2_000_000;

export const MODEL_OUTPUT_UNUSABLE = 'MODEL_OUTPUT_UNUSABLE';
export type UnusableReason =
  | 'too_large' | 'not_json' | 'schema' | 'unknown_id' | 'duplicate_id' | 'duplicate_target'
  | 'review_disabled' | 'review_limit' | 'full_text_not_allowed' | 'full_text_with_replacements';

export class SejongOutputError extends EngineError {
  readonly code = MODEL_OUTPUT_UNUSABLE;
  constructor(readonly reason: UnusableReason, readonly at?: string) {
    super('ENGINE_OUTPUT_INVALID', false, `Writer reply is unusable (${reason}${at ? ` at ${at}` : ''})`);
    this.name = 'SejongOutputError';
  }
}

export interface RejectedReplacement {
  id: string;
  sentence: string;
  code: 'replacement_newline';
}

export interface ParsedSejongReply {
  /** The schema-valid reply, unchanged (what the Python check receives). */
  response: SejongResponse;
  /** Replacements that passed every check this parser can make, in reply order. */
  usable: SejongReplacement[];
  /** Replacements rejected one by one (3.6); the Python apply step rejects them the same way. */
  rejected: RejectedReplacement[];
  /** Target sentence of every replacement id. */
  targets: Record<string, string>;
}

export type SejongReplyResult = { ok: true; value: ParsedSejongReply } | { ok: false; error: SejongOutputError };

export interface ParseReplyOptions {
  /** Attempt 2: the retry list the prompt rendered. Only its ids are valid and full text is not allowed. */
  retry?: RetryRequest[];
}

// Python str.splitlines() boundaries: the sentence splitter cuts at every one of them.
const LINE_BREAK = /[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/u;

function codePoints(text: string, limit: number): number {
  let count = 0;
  for (let unit = 0; unit < text.length; unit += 1) {
    const code = text.charCodeAt(unit);
    if (code >= 0xd800 && code <= 0xdbff && unit + 1 < text.length) {
      const next = text.charCodeAt(unit + 1);
      if (next >= 0xdc00 && next <= 0xdfff) unit += 1;
    }
    if (++count > limit) return count;
  }
  return count;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const own = Object.keys(value);
  return own.length === keys.length && keys.every(key => Object.hasOwn(value, key));
}

function boundedString(value: unknown, min: number, max: number): value is string {
  if (typeof value !== 'string') return false;
  const length = codePoints(value, max);
  return length >= min && length <= max;
}

/** Schema check of response-schema.json; returns the JSON path of the first problem, or null. */
function schemaProblem(value: unknown): string | null {
  if (!isRecord(value) || !exactKeys(value, ['replacements', 'rewrittenText', 'warnings'])) return '$';
  const { replacements, rewrittenText, warnings } = value;
  if (!Array.isArray(replacements) || replacements.length > RESPONSE_LIMITS.replacements) return '$.replacements';
  for (let index = 0; index < replacements.length; index += 1) {
    const item: unknown = replacements[index];
    const at = `$.replacements[${index}]`;
    if (!isRecord(item) || !exactKeys(item, ['id', 'text', 'reason'])) return at;
    if (typeof item.id !== 'string' || !RESPONSE_LIMITS.id.test(item.id)) return `${at}.id`;
    if (!boundedString(item.text, RESPONSE_LIMITS.textMin, RESPONSE_LIMITS.textMax)) return `${at}.text`;
    if (!boundedString(item.reason, 0, RESPONSE_LIMITS.reasonMax)) return `${at}.reason`;
  }
  if (typeof rewrittenText !== 'string') return '$.rewrittenText';
  if (!Array.isArray(warnings) || warnings.length > RESPONSE_LIMITS.warnings) return '$.warnings';
  const bad = warnings.findIndex(warning => !boundedString(warning, 0, RESPONSE_LIMITS.warningMax));
  return bad < 0 ? null : `$.warnings[${bad}]`;
}

/** Parse and validate a writer reply against the plan; never throws. */
export function readSejongReply(raw: string, plan: Plan, options: ParseReplyOptions = {}): SejongReplyResult {
  const fail = (reason: UnusableReason, at?: string): SejongReplyResult => ({ ok: false, error: new SejongOutputError(reason, at) });
  if (typeof raw !== 'string' || raw.length > MAX_REPLY_CHARS) return fail('too_large');
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return fail('not_json');
  }
  const problem = schemaProblem(value);
  if (problem) return fail('schema', problem);
  const response = value as SejongResponse;

  const retry = options.retry;
  const sentences = new Set(plan.sentences.map(sentence => sentence.id));
  const allowed = new Map<string, string>(retry
    ? retry.map(entry => [entry.id, entry.sentence])
    : plan.requests.map(request => [request.id, request.sentence]));
  const requested = new Set(plan.requests.map(request => request.sentence));
  const reviewOn = !retry && plan.openReview.enabled;
  const seen = new Set<string>();
  const targeted = new Set<string>();
  const targets: Record<string, string> = {};
  let nominated = 0;

  for (const [index, item] of response.replacements.entries()) {
    const at = `$.replacements[${index}].id`;
    if (seen.has(item.id)) return fail('duplicate_id', at);
    seen.add(item.id);
    let sentence = allowed.get(item.id);
    if (sentence === undefined) {
      if (!item.id.startsWith('S') || !sentences.has(item.id)) return fail('unknown_id', at);
      if (!reviewOn) return fail('review_disabled', at);
      if (requested.has(item.id)) return fail('duplicate_target', at);
      if (++nominated > plan.openReview.maxSentences) return fail('review_limit', at);
      sentence = item.id;
    }
    if (targeted.has(sentence)) return fail('duplicate_target', at);
    targeted.add(sentence);
    targets[item.id] = sentence;
  }

  if (response.rewrittenText.length > 0) {
    if (retry || !plan.options.allowFullText) return fail('full_text_not_allowed', '$.rewrittenText');
    if (response.replacements.length > 0) return fail('full_text_with_replacements', '$.rewrittenText');
  }

  const usable: SejongReplacement[] = [];
  const rejected: RejectedReplacement[] = [];
  for (const item of response.replacements) {
    if (LINE_BREAK.test(item.text)) rejected.push({ id: item.id, sentence: targets[item.id]!, code: 'replacement_newline' });
    else usable.push(item);
  }
  return { ok: true, value: { response, usable, rejected, targets } };
}

/** DESIGN 5.2 signature: the validated reply, or a thrown SejongOutputError (ENGINE_OUTPUT_INVALID).
 * Replacements with a newline stay in the returned reply; use readSejongReply to see them rejected. */
export function parseSejongResponse(raw: string, plan: Plan, options: ParseReplyOptions = {}): SejongResponse {
  const result = readSejongReply(raw, plan, options);
  if (!result.ok) throw result.error;
  return result.value.response;
}
