"""T4 clarity detectors (research prototype). Each detector takes a sentence record
{text, para, toks:[(form,tag,start,len)...]} (Kiwi 0.24.0) plus optional doc context and
returns a list of (start, end, note) character spans inside sentence['text'].

Detector IDs (CLR_*) are research IDs, not shipped rule IDs.
"""
import re, os

NOMTAGS = {'NNG', 'NNP', 'NR', 'SN', 'SL', 'SH', 'XSN', 'XPN', 'XR', 'NNB'}
J = lambda t: t.startswith('J')
E = lambda t: t.startswith('E')
CLAUSE_BREAK = {'EC', 'EF', 'SF', 'SP', 'SE'}


def surf(s, t):
    f, tag, st, ln = t
    return s['text'][st:st + ln]


def is_heading(s, para_size):
    """Short single-sentence paragraph with no sentence-final ending: heading/title/list label."""
    toks = s['toks']
    has_ef = any(t[1] == 'EF' for t in toks)
    return (not has_ef) and len(s['text']) <= 60


def eoj_ids(s):
    """eojeol index for each token (by whitespace split of sentence text)."""
    text = s['text']
    idx = []
    cur = -1
    prev_space = True
    pos_to_eoj = []
    for ch in text:
        if ch.isspace():
            prev_space = True
            pos_to_eoj.append(-1)
        else:
            if prev_space:
                cur += 1
            prev_space = False
            pos_to_eoj.append(cur)
    out = []
    for f, tag, st, ln in s['toks']:
        e = pos_to_eoj[st] if st < len(pos_to_eoj) else cur
        out.append(e)
    return out, cur + 1


# ------------------------------------------------------------------ D1 length / clauses
def clause_count(s):
    toks = s['toks']
    n = 0
    for i, (f, tag, st, ln) in enumerate(toks):
        if tag == 'EF':
            n += 1
        elif tag == 'EC':
            nxt = toks[i + 1][1] if i + 1 < len(toks) else ''
            # skip auxiliary-construct connectives (-어/-지/-게/-고 + VX) : not a new clause
            if nxt == 'VX':
                continue
            n += 1
    return n


def etm_window_stats(s):
    """max number of adnominal endings (ETM) inside a window not broken by EC/EF/SF/SP; and its eojeol length."""
    toks = s['toks']
    eids, _ = eoj_ids(s)
    best = (0, 0, None)
    cnt = 0
    start_i = 0
    for i, (f, tag, st, ln) in enumerate(toks + [('', 'EF', 0, 0)]):
        if tag in CLAUSE_BREAK:
            if cnt > 0 or True:
                w = toks[start_i:i]
                if w:
                    e0 = eids[start_i]
                    e1 = eids[i - 1]
                    ln_e = e1 - e0 + 1
                    if cnt > best[0] or (cnt == best[0] and ln_e > best[1]):
                        best = (cnt, ln_e, (toks[start_i][2], toks[i - 1][2] + toks[i - 1][3]))
            cnt = 0
            start_i = i + 1
        elif tag == 'ETM':
            cnt += 1
    return best


def det_long(s, thr):
    n = len(s['text'].split())
    return [(0, len(s['text']), 'eoj=%d' % n)] if n >= thr else []


# ------------------------------------------------------------------ D2 noun chain
def bare_nominal_runs(s, minrun=4):
    toks = s['toks']
    eids, ne = eoj_ids(s)
    tags_by = [set() for _ in range(ne)]
    spans = [[10**9, -1] for _ in range(ne)]
    for (f, tag, st, ln), e in zip(toks, eids):
        if e < 0:
            continue
        tags_by[e].add(tag)
        spans[e][0] = min(spans[e][0], st)
        spans[e][1] = max(spans[e][1], st + ln)
    bare = []
    for e in range(ne):
        ts = tags_by[e]
        bare.append(bool(ts) and ts <= NOMTAGS and bool(ts & {'NNG', 'NNP'}))
    out = []
    i = 0
    while i < ne:
        if bare[i]:
            j = i
            while j + 1 < ne and bare[j + 1]:
                j += 1
            # allow one trailing eojeol that ends with a particle (noun + J)
            k = j
            if j + 1 < ne:
                ts = tags_by[j + 1]
                if ts and all((t in NOMTAGS or J(t)) for t in ts) and any(J(t) for t in ts):
                    k = j + 1
            run = k - i + 1
            if run >= minrun:
                out.append((spans[i][0], spans[k][1], 'run=%d' % run))
            i = j + 1
        else:
            i += 1
    return out


# ------------------------------------------------------------------ D3 ambiguity
def det_coord_scope(s):
    """ETM-clause + N1 (와/과/및/,) N2 : modifier scope ambiguous (modifies N1 only or N1+N2)."""
    toks = s['toks']
    out = []
    n = len(toks)
    for i, (f, tag, st, ln) in enumerate(toks):
        if tag != 'ETM':
            continue
        j = i + 1
        n1 = []
        while j < n and toks[j][1] in ('NNG', 'NNP', 'XSN') and not (toks[j][0] == '들'):
            n1.append(toks[j]); j += 1
        if not n1 or toks[i + 1][1] not in ('NNG', 'NNP'):
            continue
        if j >= n:
            continue
        conj = toks[j]
        if not ((conj[1] == 'JC') or (conj[0] == '및' and conj[1] in ('MAJ', 'NNB', 'NNG')) or (conj[1] == 'SP' and conj[0] == ',')):
            continue
        j += 1
        n2 = []
        while j < n and toks[j][1] in ('NNG', 'NNP', 'XSN'):
            n2.append(toks[j]); j += 1
        if not n2:
            continue
        # N2 must close with a particle, a copula/ending or end of sentence (not another modifier/compound start)
        if j < n and not (J(toks[j][1]) or toks[j][1] in ('XSV', 'XSA', 'VCP', 'EF', 'EC', 'SF', 'SP')):
            continue
        # ETM clause must be a real predicate (not a determiner-like '그런/이런/같은')
        out.append((st, n2[-1][2] + n2[-1][3], 'ETM+N+%s+N' % conj[0]))
    return out


QUANT = {'모든', '모두', '전부', '다', '항상', '언제나', '늘', '반드시', '꼭', '누구나', '어디서나', '모든 사람', '둘 다'}
NEGF = {'않', '못', '안', '아니', '못하'}


def det_neg_scope(s):
    toks = s['toks']
    out = []
    n = len(toks)
    for i, (f, tag, st, ln) in enumerate(toks):
        if f in QUANT and tag in ('MM', 'MAG', 'NNG', 'NP'):
            # find negation token after, before EF
            for j in range(i + 1, min(n, i + 14)):
                if toks[j][1] == 'EF':
                    break
                if (toks[j][0] in NEGF and toks[j][1] in ('VX', 'MAG', 'VCN', 'VV')):
                    # exclude the idiom '않을 수 없' and '지 않으면 안'
                    out.append((st, toks[j][2] + toks[j][3], '%s..%s' % (f, toks[j][0])))
                    break
    return out


def det_compare(s):
    toks = s['toks']
    n = len(toks)
    out = []
    for i, (f, tag, st, ln) in enumerate(toks):
        if f == '보다' and tag == 'JKB':
            k = None
            for j in range(i + 1, min(n, i + 8)):
                if toks[j][1] in ('EF', 'EC', 'SF'):
                    break
                if toks[j][1] in ('JKO', 'JKS') and toks[j][0] in ('을', '를', '이', '가'):
                    k = j
                    break
            if k is None:
                continue
            for j in range(k + 1, min(n, k + 4)):
                if toks[j][0] in ('더', '더욱', '훨씬', '더욱더', '많이', '더더욱') and toks[j][1] in ('MAG',):
                    out.append((st, toks[j][2] + toks[j][3], '보다..%s..%s' % (toks[k][0], toks[j][0])))
                    break
    return out


BARE_DEM = {'이것', '그것', '이', '그', '이들', '그들', '이를', '이는'}


def det_ref_bare(s):
    """sentence-initial bare demonstrative pronoun (이는/이를/그것은/이것이 ...) : referent must be recovered from earlier text."""
    toks = s['toks']
    if len(toks) < 2:
        return []
    f, tag, st, ln = toks[0]
    if tag == 'NP' and (f in ('이', '그', '이것', '그것', '이들', '그들') or (f == '저' and os.environ.get('T4_LEGACY_REF'))):
        nxt = toks[1]
        if J(nxt[1]):
            return [(st, nxt[2] + nxt[3], 'bare-dem:%s%s' % (f, nxt[0]))]
    return []


# ------------------------------------------------------------------ D4 hedges / intensifiers
HEDGE_RE = re.compile(
    r'것 같|듯 ?하|ㄹ ?수도 있|수도 있|로 보인|로 여겨|로 생각되|것으로 (?:보|예상|판단|전망|생각|추정)|'
    r'다소|약간|어느 정도|비교적|대체로|대개|아마|어쩌면|일정 (?:수준|부분|정도)|상당 부분|경우에 따라|'
    r'할 수 있을 것|수 있을 것|기도 합니다|기도 한다')
INTENS_RE = re.compile(r'매우|굉장히|아주|정말|너무|상당히|대단히|무척|엄청|몹시|극도로|지극히|실로|진짜')


def det_hedge(s):
    return [(m.start(), m.end(), m.group(0)) for m in HEDGE_RE.finditer(s['text'])]


def det_intens(s):
    return [(m.start(), m.end(), m.group(0)) for m in INTENS_RE.finditer(s['text'])]


# ------------------------------------------------------------------ D5 acronyms, hard words
ACR_RE = re.compile(r'(?<![A-Za-z0-9])([A-Z][A-Z0-9]{1,6}|[A-Z][a-z]?[A-Z][A-Za-z]{0,4})(?![A-Za-z])')
ACR_WHITE = {'AI', 'PC', 'TV', 'IT', 'SNS', 'CEO', 'USB', 'GPS', 'DNA', 'KTX', 'SUV', 'PDF', 'QR', 'OK', 'NGO', 'ID', 'PR', 'CCTV', 'LED', 'LTE', 'SMS', 'APP', 'CD', 'DVD', 'ATM', 'VIP', 'MBTI', 'OECD', 'UN', 'EU', 'US', 'USA', 'UK', 'WHO', 'GDP', 'BTS', 'CF', 'DIY', 'PPT', 'IQ', 'FAQ', 'Q', 'A', 'PM', 'AM', 'MC', 'KBS', 'MBC', 'SBS', 'EBS', 'YTN', 'LG', 'SK', 'KT', 'CJ', 'GS', 'IBM', 'NASA', 'ICT', 'IoT', 'OS', 'HTML', 'WiFi'}


def doc_acronyms(doc):
    """first mention of each non-whitelisted acronym; glossed if defined at the site or within the same doc (before/after)."""
    seen = {}
    out = []
    defined = set()
    full = '\n'.join(s['text'] for s in doc['sents'])
    for m in re.finditer(r'\(([A-Z][A-Z0-9]{1,6})\)', full):
        defined.add(m.group(1))
    for m in re.finditer(r'([A-Z][A-Z0-9]{1,6})\s?\([^()]{2,40}\)', full):
        defined.add(m.group(1))
    for si, s in enumerate(doc['sents']):
        t = s['text']
        for m in ACR_RE.finditer(t):
            a = m.group(1)
            if a in ACR_WHITE or a in seen:
                continue
            before = t[max(0, m.start() - 1):m.start()]
            after = t[m.end():m.end() + 2]
            site_glossed = before == '(' or after.startswith('(') or after.startswith(' (')
            seen[a] = True
            out.append((si, m.start(), m.end(), a, 'glossed-here' if site_glossed else ('defined-elsewhere' if a in defined else 'UNGLOSSED')))
    return out


HARD = ['제반', '제고', '득하', '상존', '미연에', '익일', '귀책', '봉입', '불비', '계도', '동 사업', '타 지자체', '타 기관', '기하다', '당해', '소정의', '상기', '하기와', '금번', '차기', '도래', '통로암거', '내구연한', '일할 계산']
HARD_RE = re.compile('|'.join(re.escape(h) for h in HARD))


def det_hard(s):
    return [(m.start(), m.end(), m.group(0)) for m in HARD_RE.finditer(s['text'])]


# ------------------------------------------------------------------ D6 double negation
DNEG = {
    'OBLIG_ANDOEN': re.compile(r'(?:지|하지|않|아니하)\s?(?:않|아니하)(?:으면|으면서|는다면|으면은)\s?안\s?(?:됩|된|되|돼)'),
    'OBLIG_SUEOPSDA': re.compile(r'지\s?(?:않|아니하)(?:을|ㄹ)\s?수(?:밖에|가)?\s?(?:없|있)' if os.environ.get('T4_LEGACY_DNEG') else r'지\s?(?:않|아니하)(?:을|ㄹ)\s?수(?:밖에|가)?\s?없'),
    'NOT_NOT_GEOT': re.compile(r'(?:않|못하|없|아니)(?:는|은|을|ㄴ|ㄹ)?\s?(?:것|거|게|건|경우)(?:은|이|도|는)?\s?(?:아니|없)'),
    'NEG_NEG_CHAIN': re.compile(r'(?:없|아니|못하|않)지(?:는|도|만)?\s?(?:않|못하|아니)'),
    'WITHOUT_CANNOT': re.compile(r'(?:없이|않고|아니하고|않고서|아니고)(?:는|서는)?\s?[^.。]{0,25}?수\s?(?:가\s?)?없'),
}


def det_dneg(s):
    out = []
    for k, rx in DNEG.items():
        for m in rx.finditer(s['text']):
            out.append((m.start(), m.end(), k))
    return out


# ------------------------------------------------------------------ D7 passive
AGENT_RE = re.compile(r'에 ?의해|에 ?의하여|에 ?의한|에게서?|한테|로부터|께서|에 ?의거')
OBLIG_PASS_RE = re.compile(r'(?:되|돼)어야|(?:요구|권장|금지|의무화|제한|강제|필요로)(?:되|된|됩|해야)')


def passive_marks(s):
    """passive predicate positions: 되 (XSV) after nominal, -어지다, 받/당하 (XSV)."""
    toks = s['toks']
    out = []
    for i, (f, tag, st, ln) in enumerate(toks):
        if tag == 'XSV' and f in ('되', '받', '당하') and i > 0 and toks[i - 1][1] in ('NNG', 'NNP', 'XR', 'SL', 'SN'):
            out.append((st, st + ln, f))
        elif tag == 'VX' and f == '지' and i > 0 and toks[i - 1][1] == 'EC' and toks[i - 1][0] in ('어', '아', '여', '해', '워', '라'):
            out.append((st, st + ln, '어지다'))
    return out


def det_passive(s):
    p = passive_marks(s)
    if not p:
        return []
    return [(p[0][0], p[0][1], 'passive:' + p[0][2])]


def det_passive_agentless_oblig(s):
    p = passive_marks(s)
    if not p:
        return []
    t = s['text']
    if AGENT_RE.search(t):
        return []
    m = OBLIG_PASS_RE.search(t)
    if m:
        return [(m.start(), m.end(), 'agentless-obligation-passive')]
    return []


# ------------------------------------------------------------------ D8 numbers
PCT = re.compile(r'\d[\d,]*(?:\.\d+)?\s?%')
CHG = re.compile(r'증가|상승|감소|하락|올랐|내렸|늘었|줄었|높아|낮아|인상|인하|확대|축소|성장|급증|급감|늘어|줄어')
PP = re.compile(r'%p|%P|포인트|퍼센트포인트|%포')
BAE = re.compile(r'\d+(?:\.\d+)?\s?배(?!로|가|\s?(?:이상|이하|넘|정도|가까|가량|쯤))\s?(?:이?나\s)?(?:증가|늘|상승|확대|성장|급증|커졌|커지|높아|높은|감소|줄|하락|낮아|급감)')
APPROX = re.compile(r'(?<![가-힣])(?:약|대략|대충|거의)\s?[^.,;]{0,14}?\d[^.,;]{0,8}?\s?(?:정도|가량|쯤|안팎|내외|남짓)')
REL = re.compile(r'최근|올해|작년|지난해|금년|내년|지난달|이번 ?달|요즘|오는 \d|현재')
YEAR = re.compile(r'(?<!\d)(?:19|20)\d\d(?!\d)')


def det_pct_ambig(s):
    t = s['text']
    if len(PCT.findall(t)) >= 2 and CHG.search(t) and not PP.search(t):
        m = CHG.search(t)
        return [(m.start(), m.end(), 'pct>=2,no-%p')]
    return []


def det_bae(s):
    return [(m.start(), m.end(), m.group(0)) for m in BAE.finditer(s['text'])]


def det_approx2(s):
    return [(m.start(), m.end(), m.group(0)) for m in APPROX.finditer(s['text'])]


def det_bare_num(s):
    toks = s['toks']
    out = []
    n = len(toks)
    for i, (f, tag, st, ln) in enumerate(toks):
        if tag == 'SN' and f.isdigit():
            nxt = toks[i + 1] if i + 1 < n else None
            # exclude ordinals/list markers at sentence start like "1." and years/dates and article numbers
            if i == 0 and nxt and nxt[1] in ('SF', 'SP', 'SE', 'SW'):
                continue
            if nxt is None:
                continue
            if nxt[1] in ('JKO', 'JKS', 'JX', 'JKG', 'VCP', 'EF', 'EC') :
                prev = toks[i - 1] if i > 0 else None
                # skip things like "제3 조" / "No. 3"
                out.append((st, st + ln, 'bare:%s%s' % (f, nxt[0])))
    return out


# ------------------------------------------------------------------ D9 list / parallel
LIST_MARK = re.compile(r'^\s*(?:\d{1,2}[.)]|[①-⑩]|[-•·▶▷✔✅○●■□◆◇*※])\s*')


def seg_class(toks):
    """class of a comma-separated segment by its last content token."""
    k = len(toks) - 1
    while k >= 0 and (J(toks[k][1]) or toks[k][1] in ('SF', 'SP', 'SE', 'SSC', 'SO')):
        k -= 1
    if k < 0:
        return None
    f, tag, st, ln = toks[k]
    if tag in ('NNG', 'NNP', 'NR', 'XSN', 'SL', 'SN', 'SH', 'NP'):
        # '것' / nominalized verb
        return 'NOM' if f in ('것', '거', '게') else 'N'
    if tag == 'ETN':
        return 'NOM'
    if tag == 'XSV' or tag == 'XSA':
        return 'V'
    if tag in ('EC', 'EF', 'VV', 'VA', 'VX', 'EP'):
        return 'V'
    if tag == 'ETM':
        return 'ETM'
    return None


def det_comma_series(s):
    toks = s['toks']
    segs = []
    cur = []
    for t in toks:
        if t[1] == 'SP' and t[0] == ',':
            segs.append(cur); cur = []
        else:
            cur.append(t)
    segs.append(cur)
    if len(segs) < 3:
        return []
    # keep only the final run of >=3 short segments (items), each <= 8 tokens, excluding the last (tail) segment
    items = segs[:-1]
    if len(items) < 2:
        return []
    items = items[-4:]
    if any(len(x) == 0 or len(x) > 9 for x in items):
        return []
    cls = [seg_class(x) for x in items]
    if any(c is None for c in cls):
        return []
    kinds = set(c for c in cls)
    # flag if noun-type and verb-nominal/verb-type are mixed among items
    if ('N' in kinds and ('NOM' in kinds or 'V' in kinds)) or ('NOM' in kinds and 'V' in kinds):
        a = items[0][0][2]; b = items[-1][-1][2] + items[-1][-1][3]
        return [(a, b, '|'.join(c for c in cls))]
    return []


def list_classes_for_lines(sents_by_para):
    """for a run of >=2 consecutive list-marker paragraphs: classes by final tokens."""
    pass


def item_class(sents):
    toks = [t for s in sents for t in s['toks']]
    # strip marker tokens at start
    last = None
    for t in reversed(toks):
        if t[1] in ('SF', 'SP', 'SE', 'SSC', 'SO', 'SS', 'SW'):
            continue
        last = t
        break
    if last is None:
        return None
    f, tag, st, ln = last
    if tag == 'EF':
        text = ''.join(sents[-1]['text'][-6:])
        if '요' in f or sents[-1]['text'].rstrip(' .!?~').endswith('요'):
            return 'EF_YO'
        if f in ('ᆸ니다', '습니다', 'ᆸ니까', '습니까') or sents[-1]['text'].rstrip(' .!?~').endswith(('니다', '니까')):
            return 'EF_FORMAL'
        return 'EF_PLAIN'
    if tag == 'ETN':
        return 'NOMINAL'
    if tag in ('NNG', 'NNP', 'NR', 'SN', 'SL', 'SH', 'XSN', 'NP') or J(tag):
        return 'NOMINAL'
    if tag in ('EC', 'ETM'):
        return 'FRAG'
    return 'OTHER'


# ------------------------------------------------------------------ extra: long / adnominal stack / nested quotes
def det_long_multi(s, eoj_thr=30, cc_thr=4):
    n = len(s['text'].split())
    cc = clause_count(s)
    if n >= eoj_thr and cc >= cc_thr:
        return [(0, len(s['text']), 'eoj=%d cc=%d' % (n, cc))]
    return []


def det_adn_stack(s, etm_thr=3, win_thr=8):
    c, ln, span = etm_window_stats(s)
    if c >= etm_thr and ln >= win_thr and span:
        return [(span[0], span[1], 'etm=%d win_eoj=%d' % (c, ln))]
    return []


OPEN = {'SSO'}
QUOTATIVE_SURF = ('다고', '라고', '냐고', '자고', '다며', '라며', '다는', '라는', 'ㄴ다고', '는다고')


def quote_depth(s):
    depth = 0
    mx = 0
    kinds = []
    for f, tag, st, ln in s['toks']:
        if tag == 'SSO':
            depth += 1
            kinds.append(s['text'][st:st + ln])
            mx = max(mx, depth)
        elif tag == 'SSC':
            depth = max(0, depth - 1)
    return mx, kinds


def quotative_count(s):
    n = 0
    for f, tag, st, ln in s['toks']:
        sf = s['text'][st:st + ln]
        if tag == 'JKQ' or (tag in ('EC', 'ETM') and sf.endswith(('다고', '라고', '냐고', '자고', '다며', '라며', '다는', '라는'))):
            n += 1
    return n


def det_quote_nest(s):
    d, kinds = quote_depth(s)
    q = quotative_count(s)
    # nested quote: inner quote opened while outer open and kinds differ or depth>=2 with different glyph families
    out = []
    if d >= 2:
        out.append((0, len(s['text']), 'quote-depth=%d' % d))
    elif q >= 3:
        out.append((0, len(s['text']), 'quotatives=%d' % q))
    return out


def det_coord_scope_long(s, min_mod_eoj=3):
    """Legal-drafting pattern (moleg 정비기준 6-1): a LONG modifier clause followed by 'N1 및/또는/와/과/나 N2'."""
    toks = s['toks']
    eids, _ = eoj_ids(s)
    base = det_coord_scope(s)
    out = []
    for (a, b, note) in base:
        # find ETM token whose start == a
        i = next((k for k, t in enumerate(toks) if t[2] == a and t[1] == 'ETM'), None)
        if i is None:
            continue
        j = i - 1
        while j >= 0 and toks[j][1] not in CLAUSE_BREAK:
            j -= 1
        mod_eoj = eids[i] - eids[j + 1] + 1 if j + 1 <= i else 1
        if mod_eoj >= min_mod_eoj:
            out.append((a, b, note + ' mod_eoj=%d' % mod_eoj))
    return out


def det_adn_stack2(s):
    return det_adn_stack(s, etm_thr=4, win_thr=14)


def det_noun_chain5(s):
    return bare_nominal_runs(s, 5)


def det_voice_shift(s):
    """same verbal noun used as active (하) and passive (되) inside one sentence, e.g. 변경하였다가 ... 변경되었습니다."""
    toks = s['toks']
    seen = {}
    out = []
    for i in range(1, len(toks)):
        f, tag, st, ln = toks[i]
        if tag == 'XSV' and f in ('하', '되') and toks[i - 1][1] == 'NNG':
            stem = toks[i - 1][0]
            if len(stem) < 2:
                continue
            seen.setdefault(stem, []).append((f, st))
    for stem, v in seen.items():
        kinds = {x[0] for x in v}
        if kinds == {'하', '되'}:
            out.append((min(x[1] for x in v), max(x[1] for x in v) + 1, 'voice-shift:' + stem))
    return out
