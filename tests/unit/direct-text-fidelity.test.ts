import { expect, it } from 'vitest';
import { checkDirectTextFidelity, checkStructuralFidelity, preservesVoice, restoreProtectedSentences, sourceSentences } from '../../src/engine/direct-text-fidelity.js';
import { parseTextResult } from '../../src/engine/text-edits.js';
it.each([
  ['공사 진행은 금지된다.', '공사 진행은 허용된다.'],
  ['공사 진행은 불가하다.', '공사 진행은 가능하다.'],
  ['문서를 공개한다.', '문서를 공개하지 않는다.'],
  ['자료를 검토한다.', '자료를 검토해야 한다.'],
  ['자료를 전달한다.', '자료를 전달할 수 있다.'],
])('rejects newly introduced protected meaning in %s', (source, candidate) => {
  expect(checkDirectTextFidelity(source, candidate).violations).toBeGreaterThan(0);
});
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
it('rejects sentences moved to another source position',()=>{
 const source='먼저 학생들은 도서관에서 공부했다. 그다음 학생들은 도서관에서 잠을 잤다.\n';
 expect(checkDirectTextFidelity(source,'그다음 학생들은 도서관에서 잠을 잤다. 먼저 학생들은 도서관에서 공부했다.\n').violations).toBeGreaterThan(0);
 expect(checkDirectTextFidelity(source,'그다음 학생들은 도서관에서 잠을 잤다. 먼저 학생들은 도서관에서 공부를 했다.\n').violations).toBeGreaterThan(0);
});
it('accepts parallel sentences that are each rewritten in place',()=>{
 expect(checkDirectTextFidelity('상반기에는 신규 채용 규모를 줄인다. 하반기에는 신규 채용 규모를 늘린다.\n','상반기에는 신규 채용의 규모를 줄인다. 하반기에는 신규 채용의 규모를 늘린다.\n').violations).toBe(0);
});
it('checks paragraph structure and duplicated sentences for every input kind',()=>{
 const source='첫 문장이다. 둘째 문장이다.\n\n# 제목\n- 목록 항목이다.\n';
 expect(checkStructuralFidelity(source,source.replace('첫 문장이다','처음 문장이다'))).toBe(0);
 for(const candidate of [
  source.replace('둘째 문장이다.','둘째 문장이다. 둘째 문장이다.'),
  source.replace('\n\n','\n'),
  source.replace('- 목록','목록'),
  `BEGIN_SOURCE_${'f'.repeat(32)}\n${source}`
 ])expect(checkStructuralFidelity(source,candidate)).toBeGreaterThan(0);
});
it('lets file inputs split, merge and respell punctuation, which the rulebook prescribes',()=>{
 const source='이번 작업은 쉽지 않은 작업이었다 — 자료가 부족했기 때문이다. 그래도 끝냈다.\n';
 expect(checkStructuralFidelity(source,source.replace(' — ','. '))).toBe(0);
 expect(checkStructuralFidelity(source,source.replace('. 그래도',', 그래도'))).toBe(0);
 expect(checkStructuralFidelity('기다렸다... 결국 왔다.\n','기다렸다… 결국 왔다.\n')).toBe(0);
 // Drops are left to the Python sentence_dropped gate; verbatim copies are caught here.
 expect(checkStructuralFidelity(source,source.replace('그래도 끝냈다.','그래도 끝냈다. 그래도 끝냈다.'))).toBeGreaterThan(0);
});
it('accepts an in-place rewrite that happens to equal another source sentence',()=>{
 const source='이 결과는 중요한 의미를 가진다. 이 결과는 중요한 의미를 가지고 있다.\n';
 const candidate='이 결과는 중요한 의미를 가진다. 이 결과는 중요한 의미를 가진다.\n';
 expect(checkStructuralFidelity(source,candidate)).toBe(0);
 expect(checkDirectTextFidelity(source,candidate).violations).toBe(0);
});
it('still counts sentences for direct text, ignoring the spelling of an ellipsis',()=>{
 const source='첫 문장이다. 둘째 문장이다.\n';
 expect(checkDirectTextFidelity(source,'첫 문장이다.\n').violations).toBeGreaterThan(0);
 expect(checkDirectTextFidelity(source,'첫 문장이다, 둘째 문장이다.\n').violations).toBeGreaterThan(0);
 expect(checkDirectTextFidelity('기다렸다... 결국 왔다.\n','기다렸다… 결국 왔다.\n').violations).toBe(0);
});

it('lets a protected sentence fix awkward wording when its protected elements survive',()=>{
 const source='해당 서류는 발급일로부터 3개월 이내의 것만 인정이 됩니다. 마지막 문장은 그대로다.\n';
 const candidate='해당 서류는 발급일부터 3개월 이내의 것만 인정됩니다. 마지막 문장은 그대로다.\n';
 expect(sourceSentences(source)[0]!.protected).toBe(true);
 expect(checkDirectTextFidelity(source,candidate).violations).toBe(0);
 expect(restoreProtectedSentences(source,candidate)).toEqual({rewrittenText:candidate,restoredProtectedSentences:0});
});
it.each([
 ['possibility to obligation','서류는 온라인으로 신청할 수 있습니다.','서류는 온라인으로 신청해야 합니다.'],
 ['changed number','처리 기간은 20일입니다.','처리 기간은 30일입니다.'],
 ['dropped negation','이 경우 등록이 되지 않습니다.','이 경우 등록이 됩니다.'],
 ['swapped values','처리 건수는 12건에서 20건으로 늘었습니다.','처리 건수는 20건에서 12건으로 늘었습니다.'],
 ['several subjects','가팀은 12건을 처리했고 나팀은 20건을 처리했다.','가팀은 20건을 처리했고 나팀은 12건을 처리했다.']
])('still rejects and restores a protected sentence with %s',(_label,original,changed)=>{
 const source=original+' 마지막 문장은 그대로다.\n', candidate=changed+' 마지막 문장은 그대로다.\n';
 expect(checkDirectTextFidelity(source,candidate).violations).toBeGreaterThan(0);
 expect(restoreProtectedSentences(source,candidate).rewrittenText).toBe(source);
});

it.each([
 ['honorific -시- dropped','궁금하신 점이 있으시면 사무소로 문의해 주세요.','궁금한 점이 있으시면 사무소로 문의해 주세요.'],
 ['해요체 request to 합쇼체','서류는 사무소로 보내 주세요.','서류는 사무소로 보내 주시기 바랍니다.'],
 ['request weakened','계약 전에 꼭 확인하세요.','계약 전에 꼭 확인하시는 것이 좋아요.'],
 ['question to statement','실적이 없어도 신청할 수 있을까요?','실적이 없어도 신청할 수 있어요.'],
 ['합쇼체 to 해라체','등록 요건은 업종마다 다릅니다.','등록 요건은 업종마다 다르다.'],
 ['stance ending flattened','작년에 규정이 바뀌었더라고요.','작년에 규정이 바뀌었어요.'],
 ['humble verb dropped','필요한 서류는 상담할 때 안내해 드리겠습니다.','필요한 서류는 상담할 때 안내하겠습니다.'],
 ['CMC mark dropped','이 카페는 디저트가 정말 맛있어요 ㅎㅎ','이 카페는 디저트가 정말 맛있어요.']
])('rejects a voice change: %s',(_label,original,changed)=>{
 expect(preservesVoice(original,changed)).toBe(false);
 expect(checkDirectTextFidelity(original+' 끝이다.\n',changed+' 끝이다.\n').violations).toBeGreaterThan(0);
});
it.each([
 ['합쇼체 rewording','신청서를 제출하기 전에 서류의 유효기간을 반드시 확인하는 것이 필요합니다.','신청서를 내기 전에 서류의 유효기간을 반드시 확인해야 합니다.'],
 ['해요체 CTA rewording','궁금하신 점이 있으시다면 언제든지 편하게 문의해 주세요.','궁금하신 점이 있으시면 언제든 편하게 문의해 주세요.'],
 ['question kept','그렇다면 매출액 기준은 어떻게 판단하는 것일까요?','그렇다면 매출액 기준은 어떻게 판단할까요?']
])('keeps a voice-preserving rewrite: %s',(_label,original,changed)=>{
 expect(preservesVoice(original,changed)).toBe(true);
});
