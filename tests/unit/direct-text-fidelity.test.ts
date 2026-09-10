import { expect, it } from 'vitest';
import { checkDirectTextFidelity, restoreProtectedSentences, sourceSentences } from '../../src/engine/direct-text-fidelity.js';
import { parseTextResult } from '../../src/engine/text-edits.js';
it('preserves concept identity instead of accepting a concept as a substring of a different word',()=>{
  expect(checkDirectTextFidelity('자료의 안전성이 중요하다.','자료의 불안전성이 중요하다.').violations).toBeGreaterThan(0);
});
it('protects sentence/paragraph correspondence and Markdown headings',()=>{
  for(const [source,output] of [
    ['검토를 진행한다. 자료를 정리한다.','검토를 진행하고 자료를 정리한다.'],
    ['검토를 진행한다.\n\n자료를 정리한다.','검토를 진행한다. 자료를 정리한다.'],
    ['# 검토\n자료를 정리한다.','# 자료\n자료를 정리한다.'],
    ['검토를 진행한다. 자료를 정리한다.','자료를 정리한다. 검토를 진행한다.']
  ]) expect(checkDirectTextFidelity(source,output).violations).toBeGreaterThan(0);
});
it('declines restoration when a protected sentence moved into a conceptless unprotected slot',()=>{
  const source='자료는 정리할 수 있다. 정리한다. 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.\n';
  const candidate='자료를 정리한다. 자료는 정리할 수 있다. 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.\n';
  expect(restoreProtectedSentences(source,candidate)).toEqual({
    rewrittenText:candidate,
    restoredProtectedSentences:0
  });
});
it('declines restoration when a changed unprotected slot has no usable concept anchor',()=>{
  const source='자료는 정리할 수 있다. 정리한다. 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.\n';
  const candidate='자료를 정리한다. 검토한다. 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.\n';
  expect(restoreProtectedSentences(source,candidate)).toEqual({
    rewrittenText:candidate,
    restoredProtectedSentences:0
  });
});
it('assigns local sentence spans despite astral characters and freezes quotes and numeric facts',()=>{
  const source='😀 자료를 정리한다. 오늘은 12일이다. “확인했다”라고 말했다.';
  const spans=sourceSentences(source);
  expect(spans.map(s=>source.slice(s.start,s.end))).toEqual(['😀 자료를 정리한다.','오늘은 12일이다.','“확인했다”라고 말했다.']);
  expect(spans.map(s=>s.protected)).toEqual([false,true,true]);
});
it('marks compact changes spanning multiple source sentences for conservative retry',()=>{
  const source='자료를 정리한다. 검토를 진행한다.';
  const raw=JSON.stringify({rewrittenText:'',edits:[{before:source,after:'자료를 정리했다. 검토를 진행했다.'}],warnings:[]});
  const result=parseTextResult(raw,source,'CLI',{inputKind:'direct-text',strength:'very-strong'} as any) as any;
  expect(result.fidelityIssues??0).toBeGreaterThan(0);
  expect(parseTextResult(raw,source).rewrittenText).toBe('자료를 정리했다. 검토를 진행했다.');
});
it('allows an exact edit with unchanged surrounding sentence context',()=>{
  const source='자료를 정리한다. 검토를 진행한다.';
  const raw=JSON.stringify({rewrittenText:'',edits:[{before:source,after:'자료를 정리한다. 검토를 진행했다.'}],warnings:[]});
  const result=parseTextResult(raw,source,'CLI',{inputKind:'direct-text',strength:'strong'} as any) as any;
  expect(result.fidelityIssues??0).toBe(0);
});

it('does not mistake adnominal verb endings for core nouns during safe compression',()=>{
 expect(checkDirectTextFidelity('검토 의견을 반영하는 작업을 진행했다.','검토 의견을 반영했다.').violations).toBe(0);
 expect(checkDirectTextFidelity('이 방안은 반복되는 작업을 정리한다.','이 방안은 작업의 반복을 정리한다.').violations).toBe(0);
});

it.each([
 ['문제를 정리한다.','문제의식을 정리한다.'],
 ['자료를 검토한다.','자료가치를 검토한다.']
])('rejects a new compound instead of treating its prefix as an attached particle: %s', (source,candidate)=>{
 expect(checkDirectTextFidelity(source,candidate).violations).toBeGreaterThan(0);
});
it.each([
 ['자료를 검토한다.','자료 검토를 진행한다.'],
 ['자료를 검토한다.','자료는 검토한다.'],
 ['자료를 검토한다.','자료에도 검토를 진행한다.'],
 ['자료를 검토한다.','자료에서는 검토를 진행한다.'],
 ['자료를 검토한다.','자료만으로도 검토를 진행한다.'],
 ['자료를 검토한다.','자료로부터는 검토를 진행한다.'],
 ['자료를 검토한다.','자료와의 검토를 진행한다.'],
 ['이 자료는 중요하다.','중요한 것은 자료이다.']
])('retains recognized vocabulary with complete supported particle sequences: %s -> %s',(source,candidate)=>{
 // This guard checks vocabulary identity, not semantic equivalence of these grammar probes.
 expect(checkDirectTextFidelity(source,candidate).violations).toBe(0);
});

it.each(['했는지','했는지에','됐는지','됐는지에'])('recognizes the complete verbal realization %s',suffix=>{
 expect(checkDirectTextFidelity('문장 표현을 확인한다.',`문장으로 표현${suffix} 확인한다.`).violations).toBe(0);
 expect(checkDirectTextFidelity('문장 표현을 확인한다.',`문장으로 표현${suffix}평가를 확인한다.`).violations).toBeGreaterThan(0);
});
it.each(['과정에서','과정에 있어서'])('permits only contextual action-preserving compression of %s',construction=>{
 const source=`자료를 검토하는 ${construction} 내용을 확인했다.`;
 for(const ending of ['하면서','하며'])expect(checkDirectTextFidelity(source,`자료를 검토${ending} 내용을 확인했다.`).violations).toBe(0);
 for(const candidate of ['내용을 확인했다.','자료를 정리하면서 내용을 확인했다.','문서를 검토하면서 내용을 확인했다.','자료를 검토한 뒤 내용을 확인했다.'])expect(checkDirectTextFidelity(source,candidate).violations).toBeGreaterThan(0);
});
it.each(['승인 과정','제조 과정','교육 과정','검토하는 과정'])('preserves substantive %s',phrase=>{
 expect(checkDirectTextFidelity(`${phrase}을 기록했다.`, '기록했다.').violations).toBeGreaterThan(0);
});
it('does not omit an additional substantive process when compressing a functional process',()=>{
 expect(checkDirectTextFidelity('자료를 검토하는 과정에서 승인 과정을 기록했다.','자료를 검토하면서 승인을 기록했다.').violations).toBeGreaterThan(0);
});
it('rejects a compound masquerading as the retained original process construction',()=>{
 expect(checkDirectTextFidelity('자료를 검토하는 과정에서 내용을 확인했다.','자료를 검토하는 과정에서평가 내용을 확인했다.').violations).toBeGreaterThan(0);
});
