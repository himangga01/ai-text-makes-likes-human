import { expect, it } from 'vitest';
import { buildHumanizePrompt } from '../../src/engine/prompt-builder.js';

import * as policy from '../../src/engine/rewrite-policy.js';
it('validates strength and isolates absent legacy and file requests', () => {
  expect(policy.parseRewriteOptions()).toBeUndefined();
  expect(policy.parseRewriteOptions('direct-text')).toEqual({inputKind:'direct-text',strength:'normal'});
  for (const strength of ['normal','medium','strong','very-strong']) {
    expect(policy.parseRewriteOptions('direct-text',strength)).toEqual({inputKind:'direct-text',strength});
  }
  expect(policy.parseRewriteOptions('text-file','normal')).toEqual({inputKind:'text-file',strength:'normal'});
  for (const [kind,strength] of [[undefined,'strong'],['text-file','strong'],['direct-text','maximum'],['direct-text',['normal']],['other','normal'],[null,undefined],['direct-text',null]]) {
    expect(()=>policy.parseRewriteOptions(kind,strength)).toThrow();
  }
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
it('a retry retains requested strength but limits effective editing scope', () => {
  const prompt = buildHumanizePrompt({source:'원문이다.',quickRules:'규칙',attempt:2,nonce:'retry',rewriteOptions:{inputKind:'direct-text',strength:'very-strong'}} as any);
  expect(prompt).toContain('very-strong');
  expect(prompt).toContain('보수적');
  expect(prompt).not.toContain('많은 문장을 실제로 재서술');
});
