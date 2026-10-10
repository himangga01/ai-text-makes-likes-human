import { expect, it } from 'vitest';
import { buildHumanizePrompt } from '../../src/engine/prompt-builder.js';

import * as policy from '../../src/engine/rewrite-policy.js';
it('validates strength and isolates absent legacy and file requests', () => {
  expect(policy.parseRewriteOptions()).toBeUndefined();
  expect(policy.parseRewriteOptions('direct-text')).toEqual({inputKind:'direct-text',strength:'normal'});
  for (const strength of ['normal','medium','strong','very-strong']) {
    expect(policy.parseRewriteOptions('direct-text',strength)).toEqual({inputKind:'direct-text',strength});
  }
  expect(policy.parseRewriteOptions('text-file')).toEqual({inputKind:'text-file',strength:'normal'});
  for (const strength of ['normal','medium','strong','very-strong','rewrite']) {
    expect(policy.parseRewriteOptions('text-file',strength)).toEqual({inputKind:'text-file',strength});
  }
  for (const [kind,strength] of [[undefined,'strong'],['text-file','maximum'],['direct-text','maximum'],['direct-text',['normal']],['other','normal'],[null,undefined],['direct-text',null]]) {
    expect(()=>policy.parseRewriteOptions(kind,strength)).toThrow();
  }
});
it('runs a text file above normal on the direct-text route of the legacy engine and keeps normal on the file route', () => {
  expect(policy.legacyRewriteOptions({inputKind:'text-file',strength:'normal'})).toEqual({inputKind:'text-file',strength:'normal'});
  for (const strength of ['medium','strong','very-strong'] as const) {
    expect(policy.legacyRewriteOptions({inputKind:'text-file',strength})).toEqual({inputKind:'direct-text',strength});
  }
  expect(policy.legacyRewriteOptions({inputKind:'text-file',strength:'rewrite'})).toEqual({inputKind:'direct-text',strength:'very-strong'});
  expect(policy.legacyRewriteOptions(undefined)).toBeUndefined();
  const file = (strength: string) => buildHumanizePrompt({source:'원문이다.',quickRules:'규칙',attempt:1,nonce:'file',rewriteOptions:{inputKind:'text-file',strength}} as any);
  const direct = (strength: string) => buildHumanizePrompt({source:'원문이다.',quickRules:'규칙',attempt:1,nonce:'file',rewriteOptions:{inputKind:'direct-text',strength}} as any);
  for (const strength of ['medium','strong','very-strong']) expect(file(strength)).toBe(direct(strength));
  expect(file('strong')).toContain('요청 강도: strong');
  expect(file('strong')).toContain('source_sentence_spans');
  expect(file('normal')).not.toContain('<rewrite_policy>');
  expect(file('normal')).not.toContain('source_sentence_spans');
});
it('very strong prompt asks for broad sentence restructuring and overrides local-only rules', () => {
  const prompt = buildHumanizePrompt({source:'원문이다.',quickRules:'국소 교정 규칙',attempt:1,nonce:'scope',rewriteOptions:{inputKind:'direct-text',strength:'very-strong'}} as any);
  expect(prompt).toContain('많은 문장');
  expect(prompt).toContain('source_sentence_spans');
  expect(prompt).toContain('구문');
  expect(prompt).toContain('대체');
  expect(prompt).not.toContain('기계적 표현만 수술적으로');
  expect(prompt).toContain('문장 분할·병합');
});
it.each(['strong','very-strong'] as const)('%s first attempt keeps concepts natural and avoids newly injected clichés', strength => {
  const prompt = buildHumanizePrompt({source:'원문이다.',quickRules:'규칙',attempt:1,nonce:'structure',rewriteOptions:{inputKind:'direct-text',strength}} as any);
  expect(prompt).toContain('핵심 개념어를 문장 속 자연스러운 자리에 둔다');
  expect(prompt).toContain('중요한 역할을 수행한다');
  expect(prompt).toContain('Y에서 X의 역할은 중요하다');
  expect(prompt).toContain('Y하는 것이 X의 핵심이다');
  expect(prompt).toContain('X와 Y를 결과에 그대로 쓰지 않는다');
  expect(prompt).toContain('원문에 없는 사실을 추가하지 않는다');
});
it('a retry retains requested strength but limits effective editing scope', () => {
  const prompt = buildHumanizePrompt({source:'원문이다.',quickRules:'규칙',attempt:2,nonce:'retry',rewriteOptions:{inputKind:'direct-text',strength:'very-strong'}} as any);
  expect(prompt).toContain('very-strong');
  expect(prompt).toContain('보수적');
  expect(prompt).not.toContain('많은 문장을 실제로 재서술');
});
