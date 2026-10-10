// Strength rewrite, 매우 강하게(다시쓰기) (WP-19): option lists and parsing, the legacy mapping to very-strong (byte-identical
// legacy prompts), the v2 rewrite prompt (contract, per-paragraph voice lines, retry by paragraph), the rewrite reply
// rules, the plan/check contracts of rewrite mode and the bundled UI options. Plans and reports come from the Python
// engine (tests/fixtures/sejong/plan-rewrite.json, check-rewrite-retry.json; pinned by tests/skills/test_sejong_rewrite.py).
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { candidateReviewForRetry } from '../../src/engine/candidate-review.js';
import { buildHumanizePrompt } from '../../src/engine/prompt-builder.js';
import {
  LEGACY_REWRITE_OPTIONS, legacyRewriteOptions, parseRewriteOptions, parseRewriteStrength, rewriteInstructions,
  SEJONG_REWRITE_OPTIONS, type RewriteOptions
} from '../../src/engine/rewrite-policy.js';
import { openReviewEnabled, sejongFlags } from '../../src/engine/sejong/config.js';
import {
  buildSejongPrompt, paragraphSheetLine, rewriteViolationKo, SEJONG_CONTRACT, SEJONG_REWRITE_CONTRACT
} from '../../src/engine/sejong/prompt.js';
import { checkProblems, planProblems, type JsonSchema } from '../../src/engine/sejong/python-adapter.js';
import { paragraphCount, readSejongReply } from '../../src/engine/sejong/response.js';
import type { CheckReport, Plan } from '../../src/engine/sejong/types.js';

const root = path.resolve('.');
const json = <T>(file: string): T => JSON.parse(readFileSync(path.join(root, file), 'utf8')) as T;
const planSchema = json<JsonSchema>('engine_runtime/sejong/schemas/plan.schema.json');
const checkSchema = json<JsonSchema>('engine_runtime/sejong/schemas/check.schema.json');
const SOURCE = '# 이번 주 소식\n\n저희 베이커리는 매일 아침 7시에 문을 엽니다. 왜냐하면 반죽을 매일 새로 합니다. 모든 빵은 당일 판매를 원칙으로 합니다.\n\n' +
  '오늘은 새로 나온 무화과 깜빠뉴를 소개해 드릴게요ㅋㅋ 하나에 6,500원이에요. 궁금하신 점은 댓글로 남겨 주세요.\n';
const NONCE = '0123456789abcdef0123456789abcdef';
const plan = (): Plan => json<Plan>('tests/fixtures/sejong/plan-rewrite.json');
const retryReport = (): CheckReport => json<CheckReport>('tests/fixtures/sejong/check-rewrite-retry.json');
const reply = (replacements: Array<{ id: string; text: string }>, rewrittenText = ''): string =>
  JSON.stringify({ replacements: replacements.map(item => ({ ...item, reason: '' })), rewrittenText, warnings: [] });

describe('the rewrite strength in the option lists', () => {
  it('is the fifth option of both lists, with the agreed label', () => {
    for (const list of [LEGACY_REWRITE_OPTIONS, SEJONG_REWRITE_OPTIONS]) {
      expect(list.map(option => option.id)).toEqual(['normal', 'medium', 'strong', 'very-strong', 'rewrite']);
      expect(list[4]!.label).toBe('매우 강하게(다시쓰기)');
    }
    expect(LEGACY_REWRITE_OPTIONS[4]!.description).toContain('가장 크게 다시 씁니다');
  });

  it('parses for direct text and TXT/MD files', () => {
    expect(parseRewriteStrength('rewrite')).toBe('rewrite');
    expect(parseRewriteOptions('direct-text', 'rewrite')).toEqual({ inputKind: 'direct-text', strength: 'rewrite' });
    expect(parseRewriteOptions('text-file', 'rewrite')).toEqual({ inputKind: 'text-file', strength: 'rewrite' });
    expect(() => parseRewriteStrength('rewrite-all')).toThrow();
  });

  it('never gets the open review', () => {
    for (const setting of ['medium', 'strong', 'always', 'off']) {
      expect(openReviewEnabled(sejongFlags({ SUPER_SEJONG_OPEN_REVIEW: setting }), 'rewrite')).toBe(false);
    }
  });
});

describe('legacy engine: rewrite runs exactly as very-strong', () => {
  const rewrite: RewriteOptions = { inputKind: 'direct-text', strength: 'rewrite' };
  const veryStrong: RewriteOptions = { inputKind: 'direct-text', strength: 'very-strong' };

  it('maps only rewrite', () => {
    expect(legacyRewriteOptions(rewrite)).toEqual(veryStrong);
    for (const strength of ['normal', 'medium', 'strong', 'very-strong'] as const) {
      const options: RewriteOptions = { inputKind: 'direct-text', strength };
      expect(legacyRewriteOptions(options)).toBe(options);
    }
    expect(legacyRewriteOptions(undefined)).toBeUndefined();
  });

  it('renders the very-strong policy and prompt byte for byte', () => {
    for (const attempt of [1, 2] as const) {
      expect(rewriteInstructions(rewrite, attempt)).toBe(rewriteInstructions(veryStrong, attempt));
      expect(rewriteInstructions(rewrite, attempt, true)).toBe(rewriteInstructions(veryStrong, attempt, true));
      const input = { source: '원문이다. 두 번째 문장이다.', quickRules: '규칙', attempt, nonce: 'fixed' };
      expect(buildHumanizePrompt({ ...input, rewriteOptions: rewrite })).toBe(buildHumanizePrompt({ ...input, rewriteOptions: veryStrong }));
    }
    expect(rewriteInstructions(rewrite, 1)).toContain('요청 강도: very-strong.');
  });

  it('gets the very-strong candidate review', () => {
    const gate = { status: 'warn', exitCode: 1, policy: 'retry', gateCodes: ['GATE_WARN'], hardFailures: [],
      warningReasons: { version: 1, codes: ['P1_STYLE_TARGET'] } } as never;
    const probe = (options: RewriteOptions) => candidateReviewForRetry({
      source: '자료의 표현을 확인한다.', candidate: '자료를 어떻게 표현했는지 확인한다.', options, gate, parserIssues: 0, skippedSentences: 0 });
    expect(probe(rewrite)).toEqual(probe(veryStrong));
    expect(probe(rewrite)).toBeDefined();
  });
});

describe('rewrite plans and check reports', () => {
  it('validate against the schemas and the cross-reference rules', () => {
    expect(planProblems(plan(), planSchema)).toEqual([]);
    expect(checkProblems(retryReport(), checkSchema)).toEqual([]);
    const broken = plan();
    delete broken.options.mode;
    expect(planProblems(broken, planSchema).some(problem => problem.includes('rewrite mode'))).toBe(true);
    const report = retryReport();
    report.retry = report.retry.slice(1);
    expect(checkProblems(report, checkSchema).some(problem => problem.includes('$.retry'))).toBe(true);
  });

  it('carry one entry per paragraph with its voice rule', () => {
    expect(plan().paragraphs!.map(p => [p.id, p.editable, p.level, p.honSi, p.humble, p.requests])).toEqual([
      ['P1', false, 'NOMINAL', false, false, 0], ['P2', true, 'HAPSYO', false, false, 0], ['P3', true, 'HAEYO', true, true, 1]
    ]);
  });
});

describe('buildSejongPrompt for a rewrite plan', () => {
  const first = buildSejongPrompt({ plan: plan(), source: SOURCE, nonce: NONCE, attempt: 1 });

  it('sends the rewrite contract, the paragraph sheet, the requests as context and the source last', () => {
    expect(first.startsWith(SEJONG_REWRITE_CONTRACT)).toBe(true);
    expect([...SEJONG_REWRITE_CONTRACT].length).toBeLessThanOrEqual(2500);
    const order = ['[문단 말투] 문단 ID', `BEGIN_PARAGRAPHS_${NONCE}`, '[참고 지적] 규칙이', `BEGIN_REQUESTS_${NONCE}`, '[출력 형식]',
      '[원문] 이 구간 전체'];
    const at = order.map(marker => first.indexOf(marker));
    expect(at.every(index => index >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    expect(first.endsWith(`BEGIN_SOURCE_${NONCE}\n${SOURCE}\nEND_SOURCE_${NONCE}`)).toBe(true);
    for (const absent of [SEJONG_CONTRACT, '[말투 시트]', '[열린 검토]', '[요청] frozen', '[재시도]']) expect(first).not.toContain(absent);
    expect(first).toContain('"^(R|S|P)[0-9]{1,4}$"');
    expect(first).toContain('rewrittenText: 다시 쓴 구간 전체');
  });

  it('gives every paragraph one voice line', () => {
    const sheet = first.slice(first.indexOf(`BEGIN_PARAGRAPHS_${NONCE}\n`) + `BEGIN_PARAGRAPHS_${NONCE}\n`.length, first.indexOf(`\nEND_PARAGRAPHS_${NONCE}`));
    expect(sheet.split('\n')).toEqual([
      'P1 「# 이번 주 소식」 그대로 둠',
      'P2 「저희 베이커리는 매일 아침 7…」 합쇼체, 화자 저·제·저희, 보호:[7시]',
      "P3 「오늘은 새로 나온 무화과 깜빠…」 해요체, '-시-' 있음, 겸양 있음, 요청 1, keep:[ㅋㅋ], 보호:[6,500원]"
    ]);
    expect(paragraphSheetLine({ ...plan().paragraphs![1]!, persona: ['first_plain', 'first_we'], questions: 2 }, '나는', [], []))
      .toBe('P2 「나는」 합쇼체, 화자 나·내/우리, 질문 2');
  });

  it('lists the plan requests by paragraph as hints', () => {
    const hints = JSON.parse(first.slice(first.indexOf(`BEGIN_REQUESTS_${NONCE}\n`) + `BEGIN_REQUESTS_${NONCE}\n`.length,
      first.indexOf(`\nEND_REQUESTS_${NONCE}`))) as Array<{ paragraph: string; sentence: string; text: string }>;
    expect(hints.map(hint => [hint.paragraph, hint.sentence, hint.text])).toEqual([['P2', 'S3', '왜냐하면 반죽을 매일 새로 합니다.']]);
  });

  it('retries the failed paragraphs only, by paragraph id, with their violations in Korean', () => {
    const retry = retryReport().retry;
    const second = buildSejongPrompt({ plan: plan(), source: SOURCE, nonce: NONCE, attempt: 2, retry });
    expect(second).toContain('[재시도]\n이번 호출은 검증에 걸린 문단만 다시 쓰는 재시도 1회다.');
    expect(second).toContain('P2 이전 답: 원문에 없는 숫자가 들어갔다(number_injected).');
    expect(second).toContain('P3 이전 답: 이 문단은 모든 문장을 해요체로 끝내야 하는데 합쇼체 문장이 있었다(voice_level).');
    const sheet = second.slice(second.indexOf(`BEGIN_PARAGRAPHS_${NONCE}\n`), second.indexOf(`END_PARAGRAPHS_${NONCE}`));
    expect(sheet).not.toContain('P1 ');
    expect(sheet).toContain('P2 ');
    const paragraphs = JSON.parse(second.slice(second.indexOf(`BEGIN_RETRY_PARAGRAPHS_${NONCE}\n`) + `BEGIN_RETRY_PARAGRAPHS_${NONCE}\n`.length,
      second.indexOf(`\nEND_RETRY_PARAGRAPHS_${NONCE}`))) as Array<{ id: string; text: string }>;
    expect(paragraphs.map(p => p.id)).toEqual(['P2', 'P3']);
    expect(paragraphs[1]!.text).toBe('오늘은 새로 나온 무화과 깜빠뉴를 소개해 드릴게요ㅋㅋ 하나에 6,500원이에요. 궁금하신 점은 댓글로 남겨 주세요.');
    expect(second).toContain('id는 그 문단 ID(P…)');
    expect(second).toContain('rewrittenText: 항상 빈 문자열 ""이다.');
    expect(second).not.toContain('[참고 지적] 규칙이');
  });

  it('refuses a retry entry that is not an editable paragraph', () => {
    const retry = retryReport().retry;
    expect(() => buildSejongPrompt({ plan: plan(), source: SOURCE, nonce: NONCE, attempt: 2,
      retry: [{ ...retry[0]!, id: 'P1', sentence: 'S1' }] })).toThrow(/not a paragraph/u);
    expect(() => buildSejongPrompt({ plan: plan(), source: SOURCE, nonce: NONCE, attempt: 2,
      retry: [{ ...retry[0]!, id: 'R1' }] })).toThrow(/not a paragraph/u);
  });

  it('words the paragraph voice codes for a rewrite', () => {
    expect(rewriteViolationKo({ code: 'voice_mood', detail: 'questions:1->0' })).toBe('질문 문장 수가 원문 1개에서 0개로 바뀌었다(voice_mood).');
    expect(rewriteViolationKo({ code: 'paragraph_length_ratio', detail: 'ratio:2.10' })).toBe('문단 길이가 원문과 너무 다르다(paragraph_length_ratio).');
  });
});

describe('readSejongReply for a rewrite plan', () => {
  const retry = retryReport().retry;
  const reason = (raw: string, options = {}) => {
    const result = readSejongReply(raw, plan(), options);
    return result.ok ? 'ok' : result.error.reason;
  };
  const rewritten = SOURCE.replace('하나에 6,500원이에요.', '가격은 하나에 6,500원이에요.');

  it('takes the whole chunk at attempt 1', () => {
    expect(reason(reply([], rewritten))).toBe('ok');
    expect(reason(reply([], ''))).toBe('ok');                                // nothing to change
    expect(reason(reply([{ id: 'P2', text: '문단' }]))).toBe('replacements_not_allowed');
    expect(reason(reply([], rewritten.replace('원칙으로 합니다.\n\n', '원칙으로 합니다. ')))).toBe('paragraph_count');
  });

  it('takes paragraphs by id at attempt 2', () => {
    expect(reason(reply([{ id: 'P2', text: '새 문단' }]), { retry })).toBe('ok');
    expect(reason(reply([], rewritten), { retry })).toBe('full_text_not_allowed');
    expect(reason(reply([{ id: 'R1', text: '새 문단' }]), { retry })).toBe('unknown_id');
    expect(reason(reply([{ id: 'P9', text: '새 문단' }]), { retry })).toBe('unknown_id');
    expect(reason(reply([{ id: 'P2', text: 'a' }, { id: 'P2', text: 'b' }]), { retry })).toBe('duplicate_id');
    const result = readSejongReply(reply([{ id: 'P2', text: '첫 줄\n둘째 줄' }, { id: 'P1', text: '# 제목' }]), plan(), { retry });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.usable.map(item => item.id)).toEqual(['P2']);       // a line break is the paragraph's business
    expect(result.value.rejected).toEqual([{ id: 'P1', sentence: 'S1', code: 'not_in_retry' }]);
    expect(result.value.forward.replacements.map(item => item.id)).toEqual(['P2']);
  });

  it('keeps paragraph ids out of the edit strengths', () => {
    const blog = json<Plan>('tests/fixtures/sejong/plan-blog-medium.json');
    const result = readSejongReply(reply([{ id: 'P1', text: '문단' }]), blog);
    expect(result.ok ? 'ok' : result.error.reason).toBe('unknown_id');
    const prompt = buildSejongPrompt({ plan: blog, source: '오늘은 세미나 후기를 정리합니다. 왜냐하면 일정이 바뀌었습니다. 참가비는 3만 원이 됬습니다.\n\n' +
      '현장 분위기가 좋았어요😀 ㅎㅎ 궁금한 점이 있으시면 댓글로 문의해 주세요.\n', nonce: NONCE, attempt: 1 });
    expect(prompt).toContain('"^(R|S)[0-9]{1,4}$"');                       // the edit prompt is unchanged
    expect(prompt).not.toContain('"^(R|S|P)[0-9]{1,4}$"');
  });

  it('counts paragraphs as the Python segmenter does', () => {
    expect(paragraphCount('가\n\n나\n다\n\n\n라\n')).toBe(3);
    expect(paragraphCount('  \n가\n \t\n나')).toBe(2);
    expect(paragraphCount('가\n​\n나')).toBe(2);
    expect(paragraphCount('')).toBe(0);
  });
});

describe('bundled UI options', () => {
  const app = readFileSync(path.join(root, 'public/app.js'), 'utf8');
  const css = readFileSync(path.join(root, 'public/styles.css'), 'utf8');

  it('list the legacy options, rewrite included, and accept a server list of four or five', () => {
    const block = /const bundledRewriteOptions = (\[[\s\S]*?\]);/u.exec(app)![1]!;
    const bundled = Function(`return ${block}`)() as Array<{ id: string; label: string; description: string }>;
    expect(bundled).toEqual(LEGACY_REWRITE_OPTIONS.map(option => ({ ...option })));
    expect(app).toContain('options.length < 4 || options.length > bundledRewriteOptions.length');
    expect(app).toContain('style.setProperty("--option-count"');
    expect(css).toContain('grid-template-columns: repeat(var(--option-count, 5), minmax(0, 1fr));');
  });
});
