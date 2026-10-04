"""Per-sentence voice-lock gate prototype (track T2).

check(source, candidate, backend='regex') -> list[Violation]
repair(source, candidate, violations) -> (text, actions)   (see repair.py)

Every source sentence keeps its own speech level, mood, -시- marking, stance ending, persona/humble markers and
emoticons. The document profile is NOT used for decisions (owner decision 2026-10-04: strictly per sentence).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import voice
from voice import FINITE, NOMINAL, NONE

STANCE = [  # final-eojeol suffix -> stance family (order: longest first)
    ('더라고요', 'evidential'), ('더라구요', 'evidential'), ('더라고', 'evidential'), ('더라', 'evidential'), ('던데요', 'evidential'), ('던데', 'evidential'),
    ('거든요', 'reason'), ('거든', 'reason'),
    ('잖습니까', 'shared'), ('잖아요', 'shared'), ('잖아', 'shared'), ('잖소', 'shared'),
    ('네요', 'discovery'), ('군요', 'discovery'), ('구나', 'discovery'), ('구먼', 'discovery'), ('군', 'discovery'),
    ('답니다', 'teaching'), ('랍니다', 'teaching'), ('대요', 'hearsay'), ('래요', 'hearsay'), ('답니다', 'teaching'),
    ('죠', 'confirm'), ('지요', 'confirm'),
    ('는데요', 'background'), ('ㄴ데요', 'background'), ('은데요', 'background'),
    ('ㄹ게요', 'promise'), ('게요', 'promise'), ('ㄹ게', 'promise'),
    ('걸요', 'counter'), ('을걸', 'counter'),
]
UPSHIFT_RE = re.compile(r'하였|되었|하여(?!야)|이었|였다|되어(?=[ .,])')


def stance(sentence: str) -> str | None:
    w, _ = voice.final_word(sentence)
    if len(w) >= 2 and w[-1] in '게' and voice.jong(w[-2]) == 8:
        return 'promise'
    if w.endswith('지') and len(w) >= 2 and voice.jong(w[-2]) in (20, 0) and not w.endswith(('까지', '부터지')):
        return 'confirm' if voice.regex_level(sentence)[0] == voice.HAE else None
    if w.endswith('바랍니다'):
        return None
    for suf, fam in STANCE:
        if w.endswith(suf):
            return fam
    return None


@dataclass
class Violation:
    code: str
    severity: str           # hard | soft | info
    src: str
    out: str
    detail: str = ''


@dataclass
class Unit:
    text: str
    kind: str
    par: int
    sig: dict = field(default_factory=dict)


def units(text: str, backend: str):
    out = []
    for sg in voice.split_sentences(text):
        body = voice.LIST_RE.sub('', re.sub(r'^\s*#{1,6}\s*', '', sg.text)) if sg.kind in ('heading', 'list') else sg.text
        out.append(Unit(sg.text, sg.kind, sg.par, voice.signature(body, backend, sg.kind)))
    return out


def _grams(s: str):
    t = re.sub(r'[^가-힣A-Za-z0-9]', '', s)
    return {t[i:i + 2] for i in range(len(t) - 1)} or {t}


def sim(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    return 2 * len(ga & gb) / (len(ga) + len(gb)) if ga and gb else 0.0


def align(src, out):
    """Monotonic alignment with 1:1, 1:2 (split), 2:1 (merge), 1:0, 0:1. Returns list of (src_idx_list, out_idx_list)."""
    n, m = len(src), len(out)
    NEG = -1e9
    best = [[NEG] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    SKIP = -0.15
    for i in range(n + 1):
        for j in range(m + 1):
            b = best[i][j]
            if b == NEG:
                continue
            moves = []
            if i < n and j < m:
                moves.append((1, 1, sim(src[i].text, out[j].text)))
            if i < n and j + 1 < m:
                moves.append((1, 2, 2 * sim(src[i].text, out[j].text + out[j + 1].text) - 1))   # split
            if i + 1 < n and j < m:
                moves.append((2, 1, 2 * sim(src[i].text + src[i + 1].text, out[j].text) - 1))   # merge
            if i < n:
                moves.append((1, 0, SKIP))
            if j < m:
                moves.append((0, 1, SKIP))
            for di, dj, sc in moves:
                if b + sc > best[i + di][j + dj]:
                    best[i + di][j + dj] = b + sc
                    back[i + di][j + dj] = (di, dj)
    pairs, i, j = [], n, m
    while i > 0 or j > 0:
        di, dj = back[i][j]
        pairs.append((list(range(i - di, i)), list(range(j - dj, j))))
        i, j = i - di, j - dj
    return pairs[::-1]


def _quotes(s: str):
    return [q.group(0)[1:-1] for q in voice.QUOTE_RE.finditer(s)]


def compare_one(s: Unit, o: Unit, backend: str, mood_check: bool = True, prefix: str = ''):
    v = []
    a, b = s.sig, o.sig
    # quoted speech keeps its own level
    qs, qo = _quotes(s.text), _quotes(o.text)
    if s.kind != 'quote' and qs and len(qs) == len(qo):
        for x, y in zip(qs, qo):
            lx, ly = voice.signature(x, backend)['level'], voice.signature(y, backend)['level']
            if lx != ly and lx in FINITE:
                v.append(Violation(prefix + 'quote_level', 'hard', s.text, o.text, f'{lx}->{ly}'))
    if a['level'] != NONE and a['level'] != b['level']:
        v.append(Violation(prefix + 'level', 'hard', s.text, o.text, f"{a['level']}->{b['level']}"))
    if mood_check and a['mood'] and b['mood'] and a['mood'] != b['mood']:
        sev = 'soft' if {a['mood'], b['mood']} == {'DECL', 'EXCL'} else 'hard'
        v.append(Violation(prefix + 'mood', sev, s.text, o.text, f"{a['mood']}->{b['mood']}"))
    if a['level'] in FINITE and b['level'] in FINITE and a['hon_si'] != b['hon_si']:
        v.append(Violation(prefix + ('hon_si_dropped' if a['hon_si'] else 'hon_si_added'), 'hard', s.text, o.text))
    if mood_check:
        sa, sb = stance(s.text), stance(o.text)
        if sa != sb and a['level'] in FINITE:
            v.append(Violation(prefix + 'stance', 'soft', s.text, o.text, f'{sa}->{sb}'))
    return v


SI_ANY = re.compile(r'(?<=[가-힣])(?:시(?=[는ᆫ고면며기지어겠었다]|$)|셨|셔|세요|십|신(?=\s|$|가|건|데|지|다))')


def _si_count(text: str) -> int:
    t = voice.HON_SI_NOUN.sub(' ', re.sub(r'[^가-힣\s]+', ' ', voice.mask_quotes(text)))
    return len(SI_ANY.findall(t)) + len(re.findall(r'계시|계셔|계세|계십|계신|드시|드셔|주무시|께서', t))


def compare_markers(src_texts, out_texts, src_sigs, out_sigs, allow_cmc_normalise: bool = False):
    v = []
    from collections import Counter
    cs = Counter(t for g in src_sigs for t in g.get('cmc', [])); co = Counter(t for g in out_sigs for t in g.get('cmc', []))
    lost, gained = cs - co, co - cs
    sev = 'info' if allow_cmc_normalise else 'soft'
    for kind, code in (('spell', 'colloquial_spelling_changed'), ('disc', 'discourse_marker_dropped')):
        l = [x for (k, x) in lost.elements() if k == kind]
        if l:
            v.append(Violation(code, sev, ' '.join(src_texts), ' '.join(out_texts), str(l)))
    g = [x for (k, x) in gained.elements() if k in ('spell', 'disc')]
    if g:
        v.append(Violation('colloquial_added', 'soft', ' '.join(src_texts), ' '.join(out_texts), str(g)))
    S, O = ' '.join(src_texts), ' '.join(out_texts)
    ps = set(p for g in src_sigs for p in g['persona']); po = set(p for g in out_sigs for p in g['persona'])
    firsts = {'first_humble', 'first_plain', 'first_we'}
    if (ps & firsts) and (po & firsts) and (ps & firsts) != (po & firsts):
        v.append(Violation('persona_swap', 'soft', S, O, f'{sorted(ps & firsts)}->{sorted(po & firsts)}'))
    elif ps - po:
        v.append(Violation('persona_dropped', 'soft', S, O, str(sorted(ps - po))))
    elif (po - ps) & firsts:
        v.append(Violation('persona_added', 'soft', S, O, str(sorted(po - ps))))
    if any(g['humble'] for g in src_sigs) and not any(g['humble'] for g in out_sigs):
        v.append(Violation('humble_dropped', 'soft', S, O))
    es, eo = len(voice.EMO_RE.findall(S)), len(voice.EMO_RE.findall(O))
    if es > eo:
        v.append(Violation('emoticon_dropped', 'info' if allow_cmc_normalise else 'soft', S, O, f'{es}->{eo}'))
    elif eo > es:
        v.append(Violation('emoticon_added', 'soft', S, O, f'{es}->{eo}'))
    hs, ho = _si_count(S), _si_count(O)
    if hs != ho and not any(x.code.startswith('hon_si') for x in v):
        v.append(Violation('hon_si_elsewhere', 'soft', S, O, f'{hs}->{ho}'))
    if len(UPSHIFT_RE.findall(O)) > len(UPSHIFT_RE.findall(S)):
        v.append(Violation('written_upshift', 'soft', S, O))
    return v


def check(source: str, candidate: str, backend: str = 'regex', allow_cmc_normalise: bool = False):
    src, out = units(source, backend), units(candidate, backend)
    viol = []
    prev_src_level = None
    for si, oi in align(src, out):
        S = [src[i] for i in si]; O = [out[j] for j in oi]
        if S:
            prev_src_level = S[-1].sig['level']
        if len(S) == 1 and len(O) == 1:
            viol += compare_one(S[0], O[0], backend)
        elif len(S) == 1 and len(O) == 2:          # split: last piece keeps everything, first piece keeps level
            viol += compare_one(S[0], O[1], backend)
            if S[0].sig['level'] in FINITE and O[0].sig['level'] != S[0].sig['level']:
                viol.append(Violation('split_level', 'hard', S[0].text, O[0].text, f"{S[0].sig['level']}->{O[0].sig['level']}"))
        elif len(S) == 2 and len(O) == 1:          # merge: output keeps the last source sentence; first must share level/mood
            viol += compare_one(S[1], O[0], backend)
            a, b = S[0].sig, S[1].sig
            if a['level'] in FINITE and b['level'] in FINITE and a['level'] != b['level']:
                viol.append(Violation('merge_across_levels', 'hard', S[0].text + ' ' + S[1].text, O[0].text, f"{a['level']}+{b['level']}"))
            elif a['mood'] in ('INTERR', 'IMPER', 'PROPOS') and a['mood'] != O[0].sig['mood']:
                viol.append(Violation('merge_lost_mood', 'hard', S[0].text, O[0].text, a['mood']))
            elif a['hon_si'] and not O[0].sig['hon_si'] and not b['hon_si']:
                viol.append(Violation('merge_lost_hon_si', 'hard', S[0].text, O[0].text))
        elif len(S) == 0 and len(O) == 1:
            if O[0].sig['level'] in FINITE and prev_src_level in FINITE and O[0].sig['level'] != prev_src_level:
                viol.append(Violation('inserted_level', 'hard', '', O[0].text, f'{prev_src_level}->{O[0].sig["level"]}'))
            continue
        elif len(S) == 1 and len(O) == 0:
            viol.append(Violation('sentence_deleted', 'info', S[0].text, ''))
            continue
        viol += compare_markers([u.text for u in S], [u.text for u in O], [u.sig for u in S], [u.sig for u in O], allow_cmc_normalise)
    return viol
