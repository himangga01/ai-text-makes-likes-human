import { describe, expect, it } from 'vitest';
import { collectKoreanStyleFindings, diagnoseKoreanStyle, type StyleFinding } from '../../src/engine/super-sejong.js';

const ids = (source: string) => collectKoreanStyleFindings(source).map(f => f.ruleId);
const texts = (source: string) => collectKoreanStyleFindings(source).map(f => source.slice(f.start, f.end));

describe('legacy rules', () => {
  it('keeps PROCESS_NOMINALIZATION and PUBLIC_LANGUAGE_FRAME anchored to the governing word', () => {
    const source = '자료를 검토하는 과정에서 오류를 발견했다. 교육에 있어서는 기초가 중요하다.';
    expect(texts(source)).toEqual(['검토하는 과정에서', '교육에 있어서']);
  });
  it('flags only unambiguous "에 있어서" frames, never locative 있다 + -어서', () => {
    expect(texts('정책을 결정함에 있어서 신중해야 한다.')).toEqual(['결정함에 있어서']);
    expect(texts('문제를 해결하는 데 있어서 시간이 걸렸다.')).toEqual(['데 있어서']);
    expect(texts('행정에 있어서의 원칙을 지킨다.')).toEqual(['행정에 있어서']);
    for (const locative of ['나는 집에 있어서 나가지 않았다.', '열쇠가 서랍에 있어서 찾았다.', '회의실에 있어서 전화를 못 받았다.'])
      expect(ids(locative)).not.toContain('PUBLIC_LANGUAGE_FRAME');
  });
  it('ignores fenced code and inline literals', () => {
    const source = '`검토하는 과정에서`와 “검토하는 과정에서”를 기록했다.\n```\n검토하는 과정에서\n```\n';
    expect(diagnoseKoreanStyle(source)).toEqual([]);
  });
  it('matches across a soft line wrap inside one paragraph but not across a blank line', () => {
    expect(ids('자료를 검토하는\n과정에서 오류를 찾았다.')).toEqual(['PROCESS_NOMINALIZATION']);
    expect(ids('자료를 검토하는\n\n과정에서 오류를 찾았다.')).toEqual([]);
  });
});

describe('single-phrase rules', () => {
  it('IMPORTANCE_FORMULA flags 하는 것이 중요합니다 and 중요한 역할, not a plain 중요하다', () => {
    expect(ids('꾸준히 운동하는 것이 중요합니다.')).toEqual(['IMPORTANCE_FORMULA']);
    expect(diagnoseKoreanStyle('교육은 사회 발전에 중요한 역할을 합니다.').map(f => f.ruleId)).toEqual(['IMPORTANCE_FORMULA']);
    expect(ids('이 문제는 중요하다. 중요한 것은 시간이다.')).toEqual([]);
  });
  it('CONCLUDING_SIGNPOST needs sentence-initial position', () => {
    expect(ids('이상입니다. 결론적으로, 우리는 계속해야 합니다.')).toEqual(['CONCLUDING_SIGNPOST']);
    expect(ids('그는 결론적으로 옳았다고 말했다.')).toEqual([]);
  });
  it('DEMONSTRATIVE_THROUGH flags 이를 통해 only', () => {
    expect(texts('실험을 반복했다. 이를 통해 오차를 줄였다.')).toEqual(['이를 통해']);
    expect(ids('실험을 통해 오차를 줄였다.')).toEqual([]);
  });
  it('ROLE_FORMULA skips acting roles', () => {
    expect(ids('그 제도는 안전망 역할을 한다.')).toEqual(['ROLE_FORMULA']);
    expect(ids('그는 영화에서 주인공 역할을 맡았고 악역 역할을 하기도 했다.')).toEqual([]);
  });
  it('BOILERPLATE_ANNOUNCE flags announcement endings', () => {
    expect(ids('지금부터 세 가지를 살펴보겠습니다.')).toEqual(['BOILERPLATE_ANNOUNCE']);
    expect(ids('지금부터 어떻게 되는지 알아볼까요.')).toEqual(['BOILERPLATE_ANNOUNCE']);
    expect(ids('우리는 결과를 살펴보았다.')).toEqual([]);
  });
  it('DOUBLE_PASSIVE flags 되어지/보여지/쓰여진 but not lexical 이루어지/만들어지', () => {
    expect(ids('연구가 많이 진행되어지고 있다.')).toEqual(['DOUBLE_PASSIVE']);
    expect(ids('이렇게 보여진다. 책에 쓰여진 글이다.')).toEqual(['DOUBLE_PASSIVE', 'DOUBLE_PASSIVE']);
    expect(ids('합의가 이루어졌다. 제품이 만들어지는 과정이다. 지난 일이 잊혀졌다고 본다.')).toEqual(['DOUBLE_PASSIVE']);
    expect(ids('돼지가 보인다. 이 이야기는 믿어지지 않는다.')).toEqual([]);
  });
  it('CAUSAL_LEAD flags 로 이어질', () => {
    expect(texts('이 조치가 차질로 이어질 것이다.')).toEqual(['차질로 이어질']);
  });
});

describe('cluster and run rules', () => {
  it('INTENSIFIER_CLUSTER needs three in one window', () => {
    expect(ids('다양한 방법을 매우 효과적으로 적용한다.')).toEqual(['INTENSIFIER_CLUSTER']);
    expect(ids('다양한 방법을 적용한다.')).toEqual([]);
    expect(ids('다양한 방법을 쓴다. ' + '가'.repeat(300) + ' 매우 빠르다. ' + '나'.repeat(300) + ' 효과적인 방법이다.')).toEqual([]);
  });
  it('THROUGH_CLUSTER needs two 통해 uses and leaves 이를 통해 to its own rule', () => {
    expect(ids('조사를 통해 자료를 모으고 분석을 통해 결론을 냈다.')).toEqual(['THROUGH_CLUSTER']);
    expect(ids('조사를 통해 자료를 모았다.')).toEqual([]);
    expect(ids('조사를 했다. 이를 통해 알았고 이를 통해 확인했다.')).toEqual(['DEMONSTRATIVE_THROUGH', 'DEMONSTRATIVE_THROUGH']);
  });
  it('JEOK_CLUSTER needs three ~적 modifiers and skips nouns such as 목적', () => {
    expect(ids('체계적인 접근으로 지속적인 개선을 위해 적극적으로 움직인다.')).toContain('JEOK_CLUSTER');
    expect(ids('이 목적은 성적 향상이며 실적이 면적과 무관하다.')).toEqual([]);
  });
  it('CAPABILITY_HEDGE_CLUSTER needs four 수 있다', () => {
    const four = '쓸 수 있다. 볼 수 있다. 갈 수 있다. 할 수 있다.';
    expect(ids(four)).toContain('CAPABILITY_HEDGE_CLUSTER');
    expect(ids('쓸 수 있다. 볼 수 있다.')).toEqual([]);
  });
  it('CONNECTOR_RUN flags the second connector-led sentence within three sentences', () => {
    const source = '비용이 늘었다. 또한 기간도 길어졌다. 따라서 계획을 바꾼다.';
    expect(texts(source)).toEqual(['따라서']);
    expect(ids('비용이 늘었다. 또한 기간도 길어졌다. 계획을 바꾼다. 그래서 끝냈다.')).toEqual([]);
    expect(ids('따라서 비용이 늘었다.\n\n따라서 기간도 길어졌다.')).toEqual([]);
  });
  it('ENDING_MONOTONY fires on the fifth identical ending within a paragraph only', () => {
    const run = (n: number) => Array.from({ length: n }, (_, i) => `${i + 1}번째 일이 있습니다.`).join(' ');
    expect(ids(run(4))).toEqual([]);
    expect(texts(run(5))).toEqual(['있습니다.']);
    expect(ids(run(3) + '\n\n' + run(3))).toEqual([]);
    expect(ids('요약 한 줄이다. 둘째는 한다. 셋째는 된다. 넷째는 본다. 다섯째는 쓴다. 여섯째는 간다.')).toEqual([]);
  });
});

describe('offsets', () => {
  it('are UTF-16 units into the string given, so chunk offsets differ from document offsets', () => {
    const chunk = '자료를 검토하는 과정에서 오류가 났다.';
    const doc = '😀 머리말입니다.\n\n' + chunk;
    const a = diagnoseKoreanStyle(chunk)[0], b = diagnoseKoreanStyle(doc)[0];
    expect(chunk.slice(a.start, a.end)).toBe('검토하는 과정에서');
    expect(doc.slice(b.start, b.end)).toBe('검토하는 과정에서');
    expect(b.start - a.start).toBe(doc.length - chunk.length);
    expect(doc.length - chunk.length).toBe('😀 머리말입니다.\n\n'.length); // astral char counts as 2 units
  });
});

describe('protected ranges', () => {
  const frame = '자료를 검토하는 과정에서 오류를 찾았다.';
  it('skips quotations that continue over a line break and nested quotes', () => {
    expect(ids('그는 "자료를 검토하는\n과정에서 문제가 생겼다"고 말했다.')).toEqual([]);
    expect(ids('그는 “그가 ‘자료를 검토하는 과정에서’ 쓴 말”이라 했다.')).toEqual([]);
  });
  it('does not let an apostrophe inside a word swallow Korean prose', () => {
    expect(ids(`Korea's economy isn't simple. ${frame} It's fine.`)).toEqual(['PROCESS_NOMINALIZATION']);
    expect(ids(`'${'자료를 검토하는 과정에서'}'라고 적었다.`)).toEqual([]);
  });
  it('skips Markdown tables, link destinations, footnote labels, indented code, headings and quotes', () => {
    expect(ids(`| 항목 | 설명 |\n| --- | --- |\n| ${frame} | 값 |`)).toEqual([]);
    expect(ids('[문서](https://example.com/검토하는-과정에서) 참고')).toEqual([]);
    expect(ids(`${frame}[^1]\n\n[^1]: 각주 문장이다.`)).toEqual(['PROCESS_NOMINALIZATION']);
    expect(ids(`문단이다.\n\n    ${frame}\n\n본문 끝.`)).toEqual([]);
    expect(ids(`# ${frame}\n\n> ${frame}`)).toEqual([]);
  });
  it('still scans list item text and footnote text', () => {
    expect(ids(`- ${frame}\n1. ${frame}\n\n[^1]: ${frame}`)).toEqual(['PROCESS_NOMINALIZATION', 'PROCESS_NOMINALIZATION', 'PROCESS_NOMINALIZATION']);
  });
  it('treats an unbalanced quote as plain text', () => {
    expect(ids(`그가 "시작했다. ${frame}\n\n다른 문단.`)).toEqual(['PROCESS_NOMINALIZATION']);
  });
});

describe('limit and selection', () => {
  const many = Array.from({ length: 30 }, () => '교육에 있어서는 일이 있다.').join(' ');
  it('caps at 12 and clamps larger or invalid limits', () => {
    expect(diagnoseKoreanStyle(many)).toHaveLength(12);
    expect(diagnoseKoreanStyle(many, 99)).toHaveLength(12);
    expect(diagnoseKoreanStyle(many, 3)).toHaveLength(3);
    expect(diagnoseKoreanStyle(many, 0)).toEqual([]);
    expect(diagnoseKoreanStyle(many, Number.NaN)).toEqual([]);
  });
  it('keeps rarer high-priority rules when a frequent rule fills the cap', () => {
    const source = many + ' 연구가 진행되어지고 있다. 결론적으로 끝이다.';
    const out = diagnoseKoreanStyle(source);
    expect(out.map(f => f.ruleId)).toEqual(expect.arrayContaining(['DOUBLE_PASSIVE', 'CONCLUDING_SIGNPOST']));
    expect([...out].sort((a, b) => a.start - b.start)).toEqual(out);
  });
  it('drops the lower-priority duplicate when two rules claim one phrase', () => {
    const out = diagnoseKoreanStyle('이 제도는 중요한 역할을 한다.');
    expect(out.map(f => f.ruleId)).toEqual(['IMPORTANCE_FORMULA']);
  });
  it('returns well-formed ranges', () => {
    const source = '결론적으로, 다양한 방법을 매우 효과적으로 적용하는 것이 중요합니다. 이를 통해 연구가 보여진다. 또한 이를 통해 알았다. 따라서 끝.';
    for (const f of diagnoseKoreanStyle(source) as StyleFinding[]) {
      expect(f.start).toBeGreaterThanOrEqual(0);
      expect(f.end).toBeGreaterThan(f.start);
      expect(f.end).toBeLessThanOrEqual(source.length);
    }
  });
});

describe('human-style sentences stay clean', () => {
  it('produces no findings on ordinary prose', () => {
    const source = '어제 비가 와서 우산을 챙겼다. 버스를 기다리는 동안 친구에게서 전화가 왔다. 점심은 국수로 했고, 오후에는 도서관에서 책을 빌렸다. 저녁이 되자 바람이 잦아들었다.';
    expect(diagnoseKoreanStyle(source)).toEqual([]);
  });
});

describe('performance on 50,000 characters', () => {
  const llm = '결론적으로, 다양한 방법을 통해 효과적인 결과를 얻는 것이 중요합니다. 이를 통해 연구가 진행되어지고 있습니다. 또한 체계적인 접근을 할 수 있습니다. ';
  const fit = (unit: string, prefix = '') => prefix + unit.repeat(Math.ceil(50_000 / unit.length)).slice(0, 50_000 - prefix.length);
  const shapes: Record<string, string> = {
    'unmatched hangul': fit('가'),
    'llm text repeated': fit(llm),
    'quote openers': fit('"가 '),
    'curly openers': fit('“가 ‘나 '),
    'apostrophes': fit("it's 가 don't "),
    'backticks': fit('`가 '),
    'one 50k backtick run': fit('`'),
    'mixed backtick runs': fit('`a``b```'),
    'link openers': fit('](가'),
    'corner quote openers': fit('「가'),
    'connector sentences': fit('또한 가. '),
    'unclosed fence then prose': fit(llm, '```\n'),
    'soft wraps': fit(('자료를 검토하는\n')),
    'table rows': fit('| 가 | 나 |\n'),
    'one-char sentences': fit('가. '),
    'many ~적 words': fit('체계적인 '),
    'long numbered list': fit('1. 다양한 효과적인 매우 방법\n')
  };
  for (const [name, source] of Object.entries(shapes))
    it(`scans ${name} in under one second`, () => {
      expect(source.length).toBe(50_000);
      const started = performance.now();
      const out = diagnoseKoreanStyle(source);
      expect(performance.now() - started).toBeLessThan(1000);
      expect(out.length).toBeLessThanOrEqual(12);
    });
});

describe('document register', () => {
  it('finds the dominant speech level outside quotes, headings and lists', async () => {
    const { documentRegister } = await import('../../src/engine/super-sejong.js');
    expect(documentRegister('안내합니다. 신청은 내일까지입니다. 문의는 메일로 받습니다.')).toBe('합쇼체');
    expect(documentRegister('나는 길을 걸었다. 그가 "어디 가요?"라고 물었다. 대답하지 않았다.')).toBe('해라체');
    expect(documentRegister('오늘은 맑아요. 내일은 비가 와요. 우산을 챙기세요.')).toBe('해요체');
    expect(documentRegister('# 제목입니다\n- 항목입니다\n짧다.')).toBeUndefined();
    expect(documentRegister('첫 문장입니다. 둘째 문장이다. 셋째 문장이에요.')).toBeUndefined();
  });
});
