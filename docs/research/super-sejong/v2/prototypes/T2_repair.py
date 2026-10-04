"""Voice repair prototype: graft the source final eojeol back, restore emoticons, else revert the sentence (group).

repair(source, candidate, backend) -> (repaired_text, actions)
Graft is a partial revert: it copies the writer's own final eojeol, so it never invents a conjugation.
It is applied only when the final eojeols share the same lemma key (ending syllables stripped, contraction normalised).
"""
from __future__ import annotations
import re
import voice, gate

END_SYL = set('니다요어아여세십시오까죠지습읍입군네구나거든잖더라고게께걸래대야당징용엉얌앙')
CONTR = {'해': '하', '합': '하', '했': '하', '할': '하', '한': '하', '돼': '되', '됩': '되', '됐': '되', '될': '되', '된': '되',
         '려': '리', '혀': '히', '쳐': '치', '셔': '시', '워': '우', '와': '오', '봐': '보', '줘': '주', '꿔': '꾸', '써': '쓰', '겨': '기', '져': '지', '펴': '피', '켜': '키'}


def _drop_b(ch):
    if voice.is_hangul(ch) and voice.jong(ch) == 17:                  # 걸립 -> 걸리 (ㅂ니다 coda)
        return chr(ord(ch) - 17)
    return ch


def lemma_key(word: str) -> str:
    w = word
    while len(w) > 1 and w[-1] in END_SYL:
        w = w[:-1]
    if not w:
        return ''
    last = CONTR.get(w[-1], _drop_b(w[-1]))
    return w[:-1] + last


def _final_span(sentence: str):
    w, tail = voice.final_word(sentence)
    if not w:
        return None
    core = sentence[:len(sentence) - len(tail)] if tail else sentence
    idx = core.rfind(w)
    return (idx, idx + len(w)) if idx >= 0 else None


def graft(src: str, out: str):
    ws, _ = voice.final_word(src); wo, _ = voice.final_word(out)
    if not ws or not wo or ws == wo:
        return None
    ks, ko = lemma_key(ws), lemma_key(wo)
    if not ks or ks != ko:
        return None
    sp = _final_span(out)
    if not sp:
        return None
    new = out[:sp[0]] + ws + out[sp[1]:]
    # restore source final punctuation (?, !, .) when the mood changed
    _, ts = voice.final_word(src); _, to = voice.final_word(new)
    if ts.strip() != to.strip():
        new = new[:len(new) - len(to)] + ts if to else new + ts
    return new


def restore_emoticons(src: str, out: str):
    tail = re.search(r'(\s*(?:ㅎ{2,}|ㅋ{2,}|ㅠ+|\^\^|~+|[\U0001F300-\U0001FAFF☀-➿])+\s*)$', src.rstrip())
    if not tail or voice.EMO_RE.search(out):
        return None
    return re.sub(r'[.。]\s*$', '', out.rstrip()) + tail.group(1).rstrip()


def NOMINAL_INVOLVED(a, b):
    return voice.NOMINAL in (a.sig['level'], b.sig['level']) or voice.NONE in (a.sig['level'], b.sig['level'])


def repair(source: str, candidate: str, backend: str = 'regex'):
    src, out = gate.units(source, backend), gate.units(candidate, backend)
    texts = [u.text for u in out]
    actions = []
    replace = {}
    for si, oi in gate.align(src, out):
        S = [src[i] for i in si]; O = [out[j] for j in oi]
        if not S or not O:
            continue
        if len(S) == 1 and len(O) == 1:
            v = gate.compare_one(S[0], O[0], backend) + gate.compare_markers([S[0].text], [O[0].text], [S[0].sig], [O[0].sig])
        elif len(S) == 1 and len(O) == 2:
            v = gate.compare_one(S[0], O[1], backend)
            if S[0].sig['level'] in voice.FINITE and O[0].sig['level'] != S[0].sig['level']:
                v.append(gate.Violation('split_level', 'hard', '', ''))
        else:
            v = gate.compare_one(S[-1], O[-1], backend)
            if S[0].sig['level'] in voice.FINITE and S[1].sig['level'] in voice.FINITE and S[0].sig['level'] != S[1].sig['level']:
                v.append(gate.Violation('merge_across_levels', 'hard', '', ''))
        if not (len(S) == 1 and len(O) == 1):
            v += gate.compare_markers([u.text for u in S], [u.text for u in O], [u.sig for u in S], [u.sig for u in O])
        v = [x for x in v if x.severity in ('hard', 'soft')]
        if not v:
            continue
        codes = {x.code for x in v}
        if len(S) == 1 and len(O) == 1:
            t = O[0].text
            if 'emoticon_dropped' in codes:
                r = restore_emoticons(S[0].text, t)
                if r: t = r; actions.append(('emoticon_restore', S[0].text, t))
            graftable = codes & {'level', 'hon_si_dropped', 'hon_si_added', 'stance', 'colloquial_spelling_changed'}
            no_graft = 'mood' in codes or 'quote_level' in codes or NOMINAL_INVOLVED(S[0], O[0])
            if graftable and not no_graft:
                g = graft(S[0].text, t)
                if g:
                    t = g; actions.append(('graft', S[0].text, t))
            u = gate.Unit(t, O[0].kind, O[0].par, voice.signature(t, backend, O[0].kind))
            rest = [x for x in gate.compare_one(S[0], u, backend) + gate.compare_markers([S[0].text], [t], [S[0].sig], [u.sig])
                    if x.severity in ('hard', 'soft')]
            if rest:                                   # anything still off: give the writer's sentence back
                t = S[0].text; actions.append(('revert', S[0].text, t))
            replace[oi[0]] = [t]
        else:
            if v:
                replace[oi[0]] = [u.text for u in S]
                for j in oi[1:]:
                    replace[j] = []
                actions.append(('revert_group', ' '.join(u.text for u in S), ''))
    new = []
    for j, t in enumerate(texts):
        new += replace.get(j, [t])
    return ' '.join(new), actions
