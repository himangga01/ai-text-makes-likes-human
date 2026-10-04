"""Prototype: span-level edit requests and post-hoc verification (T3, task 5).

build_requests(source)  -> list of edit requests (source offsets + rule + guidance + expected fix kind)
verify(source, output, requests) -> per-request status + collateral-edit report

Verification logic (no model call):
  1. Sentence alignment source->output (difflib over sentence strings, then character ratio for replaced pairs).
  2. A request is FIXED when its detector no longer fires on the aligned output sentence and the sentence's
     protected tokens (numbers, Latin words, quoted spans) are unchanged; UNTOUCHED when the aligned sentence is
     identical; STILL_PRESENT when the detector still fires; LOST when the sentence has no counterpart.
  3. Collateral edits: sentences that carried no request but changed. Reported as a rate; deterministic repairs
     (spacing-only diffs) are counted separately because they are expected.
  4. Speech level (말투) per aligned sentence must be unchanged (same final ending class).
"""
import re, json, difflib, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detectors import DETECTORS, sentences

RULES = {d.id: d for d in DETECTORS}
# Which detectors become requests, with the fix kind and Korean guidance shown to the writer.
POLICY = {
    'N_RYUL': ('replace', '율/률: 모음·ㄴ 받침 뒤는 "율", 그 밖의 받침 뒤는 "률"로 고친다(한글 맞춤법 제11항 붙임1). 다른 말은 바꾸지 않는다.'),
    'N_FIXED_MISSPELLING': ('replace', '표준 표기로만 고친다(며칠, 웬, -ㄹ게, 돼요, 거예요 등). 말투와 어미 등급은 그대로 둔다.'),
    'N_IEYO': ('replace', '받침 있는 말 뒤 "이였/이예요"는 "이었/이에요"로 고친다.'),
    'N_BOUND_NOUN_SPACING': ('replace', '의존 명사(수·것·때)를 앞말과 띄어 쓴다. 띄어쓰기 외에는 바꾸지 않는다.'),
    'N_AUX_ANH_SPACING': ('replace', '"-지 않-"을 띄어 쓴다. 띄어쓰기 외에는 바꾸지 않는다.'),
    'N_ROSEO_ROSSEO': ('replace', '자격은 "로서", 수단·방법은 "로써"(함으로써, 이로써)로 고친다.'),
    'N_OBJ_PASSIVE': ('rewrite_span', '목적어(을/를)와 피동 서술어("되다")가 맞지 않는다. 능동(~을 ~하다) 또는 주어(~이/가 ~되다) 중 원문 의미에 맞는 하나로 고친다.'),
    'A_WAENYA': ('rewrite_span', '"왜냐하면"으로 시작한 문장의 끝을 "~기 때문이다/때문입니다"처럼 이유 표현으로 맞춘다. 문장 등급(합쇼체 등)은 원문 그대로.'),
    'A_THOUGHT_DOUBLE': ('rewrite_span', '"제 생각은 ~ 생각합니다"의 중복을 없앤다: "저는 ~라고 생각합니다" 또는 "제 생각은 ~라는 것입니다". 주장 내용·강도는 그대로.'),
    'A_DOUBLE_PASSIVE': ('replace', '이중 피동(되어지다·보여지다 등)을 단일 피동으로 고친다(되어지다→되다, 보여지다→보이다). 시·노랫말의 "잊혀진"은 그대로 둔다.'),
    'A_REDUNDANCY': ('rewrite_span', '뜻이 겹치는 말 중 하나만 남긴다(미리 예방→예방, 가장 최고→최고). 수치와 근사 표현(약/가량)은 하나만 남기되 수치는 그대로.'),
}
HINT_ONLY = {'A_HONORIFIC', 'A_EGE_INANIMATE', 'A_SIKIDA', 'A_GAJANG_HANA', 'A_PUBLIC_FRAME', 'A_EGE_ISSEO',
             'S_PILYO_RO', 'S_GANEUNG_MAKE', 'S_LIST_AND', 'T_IMPORTANCE', 'T_CONCLUDING', 'T_DEMO_THROUGH',
             'T_ROLE_ADJ', 'T_NAGAYA', 'T_DANSUN_NEOMEO'}

PROTECT = re.compile(r'[0-9][0-9,.%]*|[A-Za-z][A-Za-z0-9_\-]*|[“"‘\'「『][^”"’\'」』]{1,80}[”"’\'」』]')


def speech_class(s):
    b = re.sub(r'[\s"”’\')\]」』.!?。…~]+$', '', s.strip())
    if re.search(r'(?:니다|니까|십시오|시오|ㅂ시다)$', b): return 'hapsyo'
    if re.search(r'(?:요|죠)$', b): return 'haeyo'
    if re.search(r'(?:다|까|냐|구나|자|라)$', b): return 'haera'
    if re.search(r'(?:어|아|야|지|네|게|걸|래|해)$', b): return 'hae'
    return 'other'


def build_requests(source, genre='blog'):
    reqs = []
    for rid, (kind, guide) in POLICY.items():
        if genre == 'poetry' and rid in ('A_DOUBLE_PASSIVE', 'N_BOUND_NOUN_SPACING'):
            continue
        for s, e in RULES[rid].find(source):
            reqs.append({'id': f'{rid}@{s}', 'rule': rid, 'start': s, 'end': e, 'excerpt': source[s:e],
                         'kind': kind, 'guide': guide})
    return sorted(reqs, key=lambda r: r['start'])


def _align(src_sents, out_sents):
    sm = difflib.SequenceMatcher(a=[x[2] for x in src_sents], b=[x[2] for x in out_sents], autojunk=False)
    pairs = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1): pairs[i1 + k] = j1 + k
        elif tag == 'replace':
            used = set()
            for i in range(i1, i2):
                best, bj = 0.0, None
                for j in range(j1, j2):
                    if j in used: continue
                    r = difflib.SequenceMatcher(a=src_sents[i][2], b=out_sents[j][2], autojunk=False).ratio()
                    if r > best: best, bj = r, j
                if bj is not None and best >= 0.5:
                    pairs[i] = bj; used.add(bj)
    return pairs


def verify(source, output, reqs):
    S = [(s, e, source[s:e]) for s, e in sentences(source)]
    O = [(s, e, output[s:e]) for s, e in sentences(output)]
    pairs = _align(S, O)
    req_sent = {}
    for r in reqs:
        for i, (s, e, _) in enumerate(S):
            if s <= r['start'] < e: req_sent.setdefault(i, []).append(r)
    results, collateral, spacing_only, level_drift, protected_drift = [], [], 0, [], []
    for i, (s, e, text) in enumerate(S):
        j = pairs.get(i)
        out = O[j][2] if j is not None else None
        if out is not None and speech_class(text) != speech_class(out):
            level_drift.append({'src': text[:80], 'out': out[:80]})
        if out is not None and sorted(PROTECT.findall(text)) != sorted(PROTECT.findall(out)):
            protected_drift.append({'src': text[:80], 'out': out[:80]})
        if i in req_sent:
            for r in req_sent[i]:
                if out is None: st = 'LOST'
                elif out == text: st = 'UNTOUCHED'
                else:
                    still = any(True for _ in RULES[r['rule']].find(out))
                    st = 'STILL_PRESENT' if still else 'FIXED'
                results.append({'id': r['id'], 'status': st, 'out': (out or '')[:100]})
        elif out is not None and out != text:
            if re.sub(r'\s', '', out) == re.sub(r'\s', '', text): spacing_only += 1
            else: collateral.append({'src': text[:80], 'out': out[:80]})
    n_free = len(S) - len(req_sent)
    return {'requests': results, 'collateral_edits': collateral,
            'collateral_rate': round(len(collateral) / n_free, 3) if n_free else 0.0,
            'spacing_only_edits': spacing_only, 'speech_level_drift': level_drift,
            'protected_token_drift': protected_drift, 'lost_sentences': [i for i in range(len(S)) if i not in pairs]}


if __name__ == '__main__':
    src = ('제 생각은 미디어 발전을 제한해야 한다고 생각합니다. 왜냐하면 악플로 상처받는 사람이 많습니다. '
           '그래서 학교에서 미리 예방하는것이 중요합니다. 인식율은 85%였습니다. 오늘 날씨가 좋네요.')
    reqs = build_requests(src, genre='essay')
    print(json.dumps(reqs, ensure_ascii=False, indent=1))
    good = ('저는 미디어 발전을 제한해야 한다고 생각합니다. 왜냐하면 악플로 상처받는 사람이 많기 때문입니다. '
            '그래서 학교에서 예방하는 것이 중요합니다. 인식률은 85%였습니다. 오늘 날씨가 좋네요.')
    bad = ('저는 미디어 발전을 제한해야 한다고 생각한다. 악플로 상처받는 사람이 많다. '
           '그래서 학교에서 미리 예방하는것이 중요합니다. 인식률은 80%였습니다. 오늘은 날씨가 참 좋습니다.')
    print('GOOD', json.dumps(verify(src, good, reqs), ensure_ascii=False, indent=1))
    print('BAD', json.dumps(verify(src, bad, reqs), ensure_ascii=False, indent=1))
