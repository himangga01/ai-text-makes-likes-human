import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { EngineError } from '../../src/engine/errors.js';
import { validateSchema, type JsonSchema } from '../../src/engine/sejong/python-adapter.js';
import {
  MAX_REPLY_CHARS, parseSejongResponse, readSejongReply, RESPONSE_LIMITS, SejongOutputError, type UnusableReason
} from '../../src/engine/sejong/response.js';
import type { Plan, RetryRequest, SejongResponse } from '../../src/engine/sejong/types.js';

const root = path.resolve('.');
const json = <T>(file: string): T => JSON.parse(readFileSync(path.join(root, file), 'utf8')) as T;
const raw = (file: string): string => readFileSync(path.join(root, 'tests/fixtures/sejong', file), 'utf8');
const schema = json<JsonSchema>('src/engine/sejong/response-schema.json');
const blog = (): Plan => json<Plan>('tests/fixtures/sejong/plan-blog-medium.json');
const closed = (): Plan => {
  const plan = blog();
  plan.options.openReview = false;
  plan.openReview = { enabled: false, maxSentences: 0 };
  return plan;
};
const reply = (replacements: unknown[], rewrittenText = '', warnings: unknown[] = []): string =>
  JSON.stringify({ replacements, rewrittenText, warnings });
const r = (id: string, text = '고친 문장입니다.', reason = 'SSJ-A01') => ({ id, text, reason });

function reason(text: string, plan: Plan, retry?: RetryRequest[]): UnusableReason | 'ok' {
  const result = readSejongReply(text, plan, { retry });
  return result.ok ? 'ok' : result.error.reason;
}

describe('readSejongReply on the WP-0 fixtures', () => {
  it('accepts the replacement, open-review and no-edit replies', () => {
    const replaced = readSejongReply(raw('response-replacements.json'), blog());
    expect(replaced).toMatchObject({ ok: true, value: { rejected: [], targets: { R1: 'S2' } } });
    if (replaced.ok) expect(replaced.value.usable).toEqual(replaced.value.response.replacements);
    const reviewed = readSejongReply(raw('response-open-review.json'), blog());
    expect(reviewed).toMatchObject({ ok: true, value: { targets: { R1: 'S2', S1: 'S1' } } });
    for (const plan of [blog(), closed(), json<Plan>('tests/fixtures/sejong/plan-no-edit.json')]) {
      expect(readSejongReply(raw('response-no-edit.json'), plan)).toMatchObject({ ok: true, value: { usable: [], rejected: [] } });
    }
  });

  it('refuses S ids when the plan has the open review off', () => {
    expect(reason(raw('response-open-review.json'), closed())).toBe('review_disabled');
    expect(reason(raw('response-replacements.json'), closed())).toBe('ok');
  });
});

describe('readSejongReply rejections', () => {
  it('rejects what is not one JSON object of the schema', () => {
    const plan = blog();
    expect(reason('', plan)).toBe('not_json');
    expect(reason('```json\n{"replacements":[],"rewrittenText":"","warnings":[]}\n```', plan)).toBe('not_json');
    expect(reason('{"replacements":[],"rewrittenText":"","warnings":[]} trailing', plan)).toBe('not_json');
    expect(reason('x'.repeat(MAX_REPLY_CHARS + 1), plan)).toBe('too_large');
    expect(reason('[]', plan)).toBe('schema');
    expect(reason('{"replacements":[],"rewrittenText":""}', plan)).toBe('schema');
    expect(reason('{"replacements":[],"rewrittenText":"","warnings":[],"edits":[]}', plan)).toBe('schema');
    expect(reason(reply([{ ...r('R1'), extra: 1 }]), plan)).toBe('schema');
    expect(reason(reply([r('X1')]), plan)).toBe('schema');
    expect(reason(reply([r('R12345')]), plan)).toBe('schema');
    expect(reason(reply([r('R1', '')]), plan)).toBe('schema');
    expect(reason(reply([], 7 as unknown as string), plan)).toBe('schema');
    expect(reason(reply([], '', ['w'.repeat(301)]), plan)).toBe('schema');
  });

  it('agrees with the generic validator on response-schema.json, counting code points', () => {
    const cases: unknown[] = [
      { replacements: [], rewrittenText: '', warnings: [] },
      { replacements: [r('R1', '😀'.repeat(4000), '😀'.repeat(60))], rewrittenText: '', warnings: ['😀'.repeat(300)] },
      { replacements: [r('R1', '😀'.repeat(4001))], rewrittenText: '', warnings: [] },
      { replacements: [r('R1', 'a', '😀'.repeat(61))], rewrittenText: '', warnings: [] },
      { replacements: Array.from({ length: 201 }, (_, i) => r(`S${i}`)), rewrittenText: '', warnings: [] },
      { replacements: [], rewrittenText: '', warnings: Array.from({ length: 21 }, () => 'w') },
      { replacements: [r('R1\n')], rewrittenText: '', warnings: [] },
      { replacements: [{ id: 'R1', text: 'a' }], rewrittenText: '', warnings: [] },
      { replacements: [{ id: 1, text: 'a', reason: '' }], rewrittenText: '', warnings: [] },
      { replacements: {}, rewrittenText: '', warnings: [] },
      { replacements: [], rewrittenText: null, warnings: [] },
      { replacements: [], rewrittenText: '', warnings: [3] },
      null, 'text', 3
    ];
    for (const value of cases) {
      const generic = validateSchema(value, schema).length === 0;
      expect([value, reason(JSON.stringify(value), blog()) !== 'schema']).toEqual([value, generic]);
    }
  });

  it('pins the hand-coded limits to response-schema.json', () => {
    const item = (schema.properties as any).replacements.items.properties;
    expect(RESPONSE_LIMITS.replacements).toBe((schema.properties as any).replacements.maxItems);
    expect(RESPONSE_LIMITS.textMin).toBe(item.text.minLength);
    expect(RESPONSE_LIMITS.textMax).toBe(item.text.maxLength);
    expect(RESPONSE_LIMITS.reasonMax).toBe(item.reason.maxLength);
    expect(RESPONSE_LIMITS.id.source).toBe(item.id.pattern);
    expect(RESPONSE_LIMITS.warnings).toBe((schema.properties as any).warnings.maxItems);
    expect(RESPONSE_LIMITS.warningMax).toBe((schema.properties as any).warnings.items.maxLength);
  });

  it('rejects unknown and duplicate ids', () => {
    const plan = blog();
    expect(reason(reply([r('R2')]), plan)).toBe('unknown_id');
    expect(reason(reply([r('S9')]), plan)).toBe('unknown_id');
    expect(reason(reply([r('R1'), r('R1')]), plan)).toBe('duplicate_id');
    expect(reason(reply([r('S1'), r('S1')]), plan)).toBe('duplicate_id');
    // S2 carries request R1: naming it twice is one sentence edited twice (apply.py duplicate_sentence).
    expect(reason(reply([r('R1'), r('S2')]), plan)).toBe('duplicate_target');
    // Alone, an S id of a requested sentence stands for that request, as apply.py reads it.
    const alone = readSejongReply(reply([r('S2')]), plan);
    expect(alone).toMatchObject({ ok: true, value: { targets: { S2: 'S2' }, rejected: [] } });
  });

  it('refuses S ids when the open review is off and rejects nominations beyond the plan maximum one by one', () => {
    expect(reason(reply([r('S1')]), closed())).toBe('review_disabled');
    expect(reason(reply([r('S1'), r('S3'), r('S4')]), blog())).toBe('ok');
    const over = readSejongReply(reply([r('S1'), r('S3'), r('S4'), r('S5')]), blog());
    expect(over.ok && over.value.rejected).toEqual([{ id: 'S5', sentence: 'S5', code: 'open_review_limit' }]);
    expect(over.ok && over.value.usable.map(item => item.id)).toEqual(['S1', 'S3', 'S4']);
    // apply.py rejects the same excess itself, so the reply reaches the check step whole.
    expect(over.ok && over.value.forward.replacements).toHaveLength(4);
    const one = blog();
    one.openReview.maxSentences = 1;
    expect(reason(reply([r('R1'), r('S1')]), one)).toBe('ok');
    const second = readSejongReply(reply([r('S1'), r('S3')]), one);
    expect(second.ok && second.value.rejected.map(item => [item.id, item.code])).toEqual([['S3', 'open_review_limit']]);
  });

  it('allows rewrittenText only when the plan allows full text, alone, on attempt 1', () => {
    expect(reason(reply([], '전체 결과'), blog())).toBe('full_text_not_allowed');
    // A blank rewrittenText is no full text, as apply.py reads it (rewrittenText.strip()).
    expect(reason(reply([], ' '), blog())).toBe('ok');
    const full = blog();
    full.options.allowFullText = true;
    expect(reason(reply([], '전체 결과'), full)).toBe('ok');
    expect(reason(reply([r('R1')], '전체 결과'), full)).toBe('full_text_with_replacements');
    const retry: RetryRequest[] = [{ id: 'R1', sentence: 'S2', violations: [{ code: 'voice_level', detail: '' }] }];
    expect(reason(reply([], '전체 결과'), full, retry)).toBe('full_text_not_allowed');
  });

  it('forwards on attempt 2 only the ids of the retry list', () => {
    const plan = blog();
    const retry: RetryRequest[] = [{ id: 'S1', sentence: 'S1', violations: [{ code: 'collateral_edit', detail: '' }] }];
    expect(reason(reply([r('S1')]), plan, retry)).toBe('ok');
    // A plan id off the retry list is dropped by itself; the retry may touch only the failed requests (3.5).
    const extra = readSejongReply(reply([r('S1'), r('R1'), r('S3')]), plan, { retry });
    expect(extra.ok && extra.value.rejected.map(item => [item.id, item.code])).toEqual([['R1', 'not_in_retry'], ['S3', 'not_in_retry']]);
    expect(extra.ok && extra.value.forward.replacements.map(item => item.id)).toEqual(['S1']);
    expect(extra.ok && extra.value.response.replacements).toHaveLength(3);
    expect(reason(reply([r('R9')]), plan, retry)).toBe('unknown_id');
    expect(reason(reply([r('S3')]), closed(), retry)).toBe('review_disabled');
    const requestRetry: RetryRequest[] = [{ id: 'R1', sentence: 'S2', violations: [{ code: 'voice_level', detail: '' }] }];
    expect(reason(reply([r('R1')]), plan, requestRetry)).toBe('ok');
    expect(reason(reply([]), plan, requestRetry)).toBe('ok');
  });

  it('rejects a replacement with a line break by itself and keeps the reply usable (DESIGN 3.6)', () => {
    for (const lineBreak of ['\n', '\r', '\r\n', '\u2028', '\u2029', '\u0085', '\v', '\f']) {
      const result = readSejongReply(reply([r('R1', `첫 줄${lineBreak}둘째 줄`), r('S1')]), blog());
      expect(result.ok).toBe(true);
      if (!result.ok) continue;
      expect(result.value.rejected).toEqual([{ id: 'R1', sentence: 'S2', code: 'replacement_newline' }]);
      expect(result.value.usable.map(item => item.id)).toEqual(['S1']);
      expect(result.value.response.replacements).toHaveLength(2);
    }
    const tab = readSejongReply(reply([r('R1', '탭\t포함')]), blog());
    expect(tab.ok && tab.value.rejected).toEqual([]);
  });
});

describe('parseSejongResponse', () => {
  it('returns the validated reply', () => {
    const parsed: SejongResponse = parseSejongResponse(raw('response-open-review.json'), blog());
    expect(parsed).toEqual(JSON.parse(raw('response-open-review.json')));
  });

  it('throws a typed unusable-output error that never echoes reply text', () => {
    const secret = '비밀 원문 문장';
    let error: unknown;
    try {
      parseSejongResponse(reply([r('R7', secret, secret)]), blog());
    } catch (caught) {
      error = caught;
    }
    expect(error).toBeInstanceOf(SejongOutputError);
    expect(error).toBeInstanceOf(EngineError);
    const typed = error as SejongOutputError;
    expect([typed.publicCode, typed.retryable, typed.code, typed.reason, typed.at])
      .toEqual(['ENGINE_OUTPUT_INVALID', false, 'MODEL_OUTPUT_UNUSABLE', 'unknown_id', '$.replacements[0].id']);
    expect(typed.message).not.toContain(secret);
    expect(() => parseSejongResponse('not json', blog())).toThrow('not_json');
  });
});
