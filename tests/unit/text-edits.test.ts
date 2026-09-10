import { describe, expect, it } from 'vitest';
import { parseTextResult } from '../../src/engine/text-edits.js';
const parse=(source:string, edits:unknown[], rewrittenText='')=>parseTextResult(JSON.stringify({rewrittenText,edits,warnings:[]}),source);
describe('compact text reconstruction',()=>{
  it('preserves untouched Markdown, Unicode and line breaks exactly',()=>{
    const source='# 제목\r\n\r\n😀 강한 경쟁력을 가지고 있다.\r\n\r\n"인용" 2026년';
    expect(parse(source,[{before:'가지고 있다',after:'갖고 있다'}]).rewrittenText).toBe(source.replace('가지고 있다','갖고 있다'));
    expect(parse(source,[]).rewrittenText).toBe(source);
  });
  it('rejects missing, repeated, overlapping and out-of-order anchors',()=>{
    for(const [source,edits] of [
      ['가 나 가',[{before:'가',after:'다'}]],
      ['가나다',[{before:'없음',after:'다'}]],
      ['가나다',[{before:'가나',after:'다'},{before:'나다',after:'마'}]],
      ['가나다',[{before:'다',after:'마'},{before:'가',after:'나'}]]
    ] as [string,unknown[]][])expect(()=>parse(source,edits)).toThrow();
  });
  it('allows unique surrounding context for repeated expressions',()=>{
    expect(parse('가는 가지고 있다. 나는 가지고 있다.',[{before:'나는 가지고 있다.',after:'나는 갖고 있다.'}]).rewrittenText).toBe('가는 가지고 있다. 나는 갖고 있다.');
  });
  it('supports full text for dense rewrites but rejects mixed protocols and blank output',()=>{
    expect(parse('원문',[],'수정문').rewrittenText).toBe('수정문');
    expect(()=>parse('원문',[{before:'원문',after:'수정문'}],'수정문')).toThrow();
    expect(()=>parse('원문',[{before:'원문',after:''}])).toThrow();
  });
});

it('normalizes the recorded Claude disjoint edit order only for explicit direct input',async()=>{
 const {default:fixture}=await import('../fixtures/direct-live-quality.json');
 const raw=JSON.stringify(fixture.compact);
 const expected=fixture.compactSource.replace('과정에 있어서','과정에서').replace('제목 아래의 설명과 관련된 표현','제목 아래 설명의 표현').replace('초안의 구성과 관련된 의견','초안의 구성에 대한 의견');
 expect(parseTextResult(raw,fixture.compactSource,'Claude',{inputKind:'direct-text',strength:'normal'})).toEqual({rewrittenText:expected,warnings:[]});
 for(const options of [undefined,{inputKind:'text-file',strength:'normal'}] as const)expect(()=>parseTextResult(raw,fixture.compactSource,'Claude',options)).toThrow();
});
it.each([
 ['가 나 가',[{before:'가',after:'다'}]],
 ['가나다',[{before:'다',after:'라'},{before:'없음',after:'다'}]],
 ['가나다',[{before:'가나',after:'다'},{before:'나다',after:'마'}]],
 ['가나다',[{before:'가',after:'나'},{before:'가',after:'다'}]],
 ['가나다',[{before:'다',after:'라',extra:true}]]
])('rejects ambiguous or malformed direct intervals: %s',(source,edits)=>{
 expect(()=>parseTextResult(JSON.stringify({rewrittenText:'',edits,warnings:[]}),source as string,'CLI',{inputKind:'direct-text',strength:'very-strong'})).toThrow();
});
