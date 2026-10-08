/** Super Sejong Engine v2 writer-reply parser (DESIGN.md 3.5 output schema, 3.6 whole-response rules).
 * The reply must match response-schema.json exactly (hand-coded here, pinned to the file by
 * tests/unit/sejong-response.test.ts). The whole-reply rules are the ones engine_runtime/sejong/apply.py
 * applies, so this side and the Python check never disagree on whether a reply is usable:
 * - every R id names a request of the plan; an S id names a plan sentence and needs the open review
 *   (an S id of a requested sentence stands for that request); no id twice, no sentence twice;
 * - `rewrittenText` non-blank only when plan.options.allowFullText, on attempt 1, with no replacements.
 * Any of these makes the whole reply unusable (MODEL_OUTPUT_UNUSABLE, which counts as the attempt).
 * Per-replacement problems reject that replacement only (3.6) and the reply stays usable:
 * - a newline in the text (replacement_newline, eligible for retry; Python rejects it the same way);
 * - open-review nominations beyond plan.openReview.maxSentences, in reply order (open_review_limit; Python
 *   rejects the same ones);
 * - on attempt 2, an id of the plan that is not on the retry list (not_in_retry): the retry may touch only
 *   the failed requests (3.5), so `forward` drops it before the reply reaches the check step.
 * Rewrite plans (strength rewrite, WP-19; engine_runtime/sejong/rewrite.py applies the same rules): attempt 1 answers
 * with rewrittenText only (replacements_not_allowed otherwise) holding as many blank-line paragraphs as the source
 * (paragraph_count; a blank reply means "nothing to change"); attempt 2 answers with replacements only, each id a
 * paragraph id P… of the plan (unknown_id otherwise) and its text the whole paragraph (line breaks allowed: a list
 * paragraph keeps its lines); ids off the retry list are not_in_retry, as above.
 * Error messages carry codes and ids, never reply text.
 */
import { EngineError } from '../errors.js';
import type { Plan, RetryRequest, SejongReplacement, SejongResponse } from './types.js';

/** Limits of response-schema.json. String lengths count code points, as the Python validator does. */
export const RESPONSE_LIMITS = {
  replacements: 200, textMin: 1, textMax: 4000, reasonMax: 60, warnings: 20, warningMax: 300,
  id: /^(R|S|P)[0-9]{1,4}$/
} as const;
/** Upper bound on the raw reply before JSON parsing: 200 × 4,000 + a full-text reply of a 15k chunk, with room. */
export const MAX_REPLY_CHARS = 2_000_000;

export const MODEL_OUTPUT_UNUSABLE = 'MODEL_OUTPUT_UNUSABLE';
export type UnusableReason =
  | 'too_large' | 'not_json' | 'schema' | 'unknown_id' | 'duplicate_id' | 'duplicate_target'
  | 'review_disabled' | 'full_text_not_allowed' | 'full_text_with_replacements'
  | 'replacements_not_allowed' | 'paragraph_count';

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
  code: 'replacement_newline' | 'open_review_limit' | 'not_in_retry';
}

export interface ParsedSejongReply {
  /** The schema-valid reply, unchanged. */
  response: SejongResponse;
  /** What the Python check receives: the reply without the not_in_retry replacements. */
  forward: SejongResponse;
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
  if (plan.options.mode === 'rewrite') return readRewriteReply(response, plan, options.retry, fail);

  const retry = options.retry;
  const sentences = new Set(plan.sentences.map(sentence => sentence.id));
  const requestSentence = new Map(plan.requests.map(request => [request.id, request.sentence]));
  const requested = new Set(plan.requests.map(request => request.sentence));
  const retryIds = retry ? new Set(retry.map(entry => entry.id)) : undefined;
  const seen = new Set<string>();
  const targeted = new Set<string>();
  const targets: Record<string, string> = {};

  for (const [index, item] of response.replacements.entries()) {
    const at = `$.replacements[${index}].id`;
    if (seen.has(item.id)) return fail('duplicate_id', at);
    seen.add(item.id);
    let sentence = requestSentence.get(item.id);
    if (sentence === undefined) {
      if (!item.id.startsWith('S') || !sentences.has(item.id)) return fail('unknown_id', at);
      if (!plan.openReview.enabled) return fail('review_disabled', at);
      sentence = item.id;
    }
    if (targeted.has(sentence)) return fail('duplicate_target', at);
    targeted.add(sentence);
    targets[item.id] = sentence;
  }

  if (response.rewrittenText.trim().length > 0) {
    if (retry || !plan.options.allowFullText) return fail('full_text_not_allowed', '$.rewrittenText');
    if (response.replacements.length > 0) return fail('full_text_with_replacements', '$.rewrittenText');
  }

  // Open-review budget of attempt 1. At attempt 2 only retried nominations come back, and they fitted the
  // budget at attempt 1 already (a retried sentence went back to its base text, so it holds no slot).
  let budget = plan.openReview.maxSentences;
  const retriedSentences = new Set((retry ?? []).map(entry => entry.sentence));
  const usable: SejongReplacement[] = [];
  const rejected: RejectedReplacement[] = [];
  const forwarded: SejongReplacement[] = [];
  for (const item of response.replacements) {
    const sentence = targets[item.id]!;
    // An S id of a requested sentence stands for its request, so it may answer that request's retry entry.
    if (retryIds && !retryIds.has(item.id) && !(requested.has(sentence) && retriedSentences.has(sentence))) {
      rejected.push({ id: item.id, sentence, code: 'not_in_retry' });
      continue;
    }
    forwarded.push(item);
    if (!requested.has(sentence) && !retry) {
      if (budget <= 0) {
        rejected.push({ id: item.id, sentence, code: 'open_review_limit' });
        continue;
      }
      budget -= 1;
    }
    if (LINE_BREAK.test(item.text)) rejected.push({ id: item.id, sentence, code: 'replacement_newline' });
    else usable.push(item);
  }
  const forward = forwarded.length === response.replacements.length ? response : { ...response, replacements: forwarded };
  return { ok: true, value: { response, forward, usable, rejected, targets } };
}

// Lines Python's str.strip() and sanitize leave empty: whitespace, zero-width and bidi marks, the BOM.
const BLANK_LINE = /^[\s\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]*$/u;

/** Blank-line paragraphs of a text (text.segment: maximal runs of non-blank lines). */
export function paragraphCount(text: string): number {
  let count = 0, inside = false;
  for (const line of text.split('\n')) {
    const blank = BLANK_LINE.test(line);
    if (!blank && !inside) count += 1;
    inside = !blank;
  }
  return count;
}

function readRewriteReply(response: SejongResponse, plan: Plan, retry: RetryRequest[] | undefined,
  fail: (reason: UnusableReason, at?: string) => SejongReplyResult): SejongReplyResult {
  const paragraphs = new Map((plan.paragraphs ?? []).map(paragraph => [paragraph.id, paragraph]));
  if (!retry) {
    if (response.replacements.length) return fail('replacements_not_allowed', '$.replacements');
    if (response.rewrittenText.trim() && paragraphCount(response.rewrittenText) !== paragraphs.size) {
      return fail('paragraph_count', '$.rewrittenText');
    }
    return { ok: true, value: { response, forward: response, usable: [], rejected: [], targets: {} } };
  }
  if (response.rewrittenText.trim()) return fail('full_text_not_allowed', '$.rewrittenText');
  const retryIds = new Set(retry.map(entry => entry.id));
  const seen = new Set<string>();
  const targets: Record<string, string> = {};
  for (const [index, item] of response.replacements.entries()) {
    const at = `$.replacements[${index}].id`;
    if (seen.has(item.id)) return fail('duplicate_id', at);
    seen.add(item.id);
    const paragraph = paragraphs.get(item.id);
    if (!item.id.startsWith('P') || !paragraph) return fail('unknown_id', at);
    targets[item.id] = paragraph.sentences[0] ?? item.id;
  }
  const usable: SejongReplacement[] = [];
  const rejected: RejectedReplacement[] = [];
  for (const item of response.replacements) {
    if (retryIds.has(item.id)) usable.push(item);
    else rejected.push({ id: item.id, sentence: targets[item.id]!, code: 'not_in_retry' });
  }
  const forward = usable.length === response.replacements.length ? response : { ...response, replacements: usable };
  return { ok: true, value: { response, forward, usable, rejected, targets } };
}

/** DESIGN 5.2 signature: the validated reply, or a thrown SejongOutputError (ENGINE_OUTPUT_INVALID).
 * Replacements with a newline stay in the returned reply; use readSejongReply to see them rejected. */
export function parseSejongResponse(raw: string, plan: Plan, options: ParseReplyOptions = {}): SejongResponse {
  const result = readSejongReply(raw, plan, options);
  if (!result.ok) throw result.error;
  return result.value.response;
}
