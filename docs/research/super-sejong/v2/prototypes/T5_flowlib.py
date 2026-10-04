"""T5 flow-feature library. Surface (regex) features are runtime-grade: they use no morphological analyser.
Kiwi features (offline only) validate and extend them.
A document is a list of paragraphs; a paragraph is a list of sentences (strings)."""
import re, math, collections

# ---------------------------------------------------------------- segmentation
_SENT = re.compile(r'.+?(?:[.!?。…]+["”’)\]」』]*(?=\s|$)|$)', re.S)

# a terminator glued to the next sentence ("...한다.논문에서는"): common in KatFish LLM abstracts (10.3% of
# boundaries), human essays (5.7%) and KLUE hankyung (19.5%). The shipped splitters require whitespace.
_GLUED = re.compile(r'(?<=[가-힣])([.!?]+["”’)\]」』]*)(?=[가-힣A-Z“"‘0-9])')

def split_sentences(par):
    par = _GLUED.sub(r'\1 ', par.strip())
    out = [m.group(0).strip() for m in _SENT.finditer(par)]
    return [s for s in out if s]

def doc_from_text(text):
    """Blank-line paragraphs; single-paragraph if no blank line (KatFish, news, MRC)."""
    pars = [p for p in re.split(r'\n\s*\n+', text.strip()) if p.strip()]
    return [split_sentences(p.replace('\n', ' ')) for p in pars]

def eoj(s):
    return len(s.split())

# ---------------------------------------------------------------- connective lexicon
CONN_CATS = {
    'add':  ['그리고', '또한', '또', '게다가', '더욱이', '더구나', '나아가', '아울러', '더불어', '한편', '이와 더불어', '이와 함께', '뿐만 아니라'],
    'adv':  ['그러나', '하지만', '그렇지만', '그런데', '반면에', '반면', '그럼에도 불구하고', '그럼에도', '이와 달리', '이와 반대로', '다만', '그러면서도'],
    'cau':  ['그래서', '그러므로', '그러니까', '따라서', '이에 따라', '이로 인해', '이로써', '결과적으로', '결국', '그러면', '그렇다면', '그러다 보니', '이 때문에', '그 결과'],
    'ex':   ['예를 들어', '예를 들면', '예컨대', '가령', '즉', '다시 말해', '다시 말하면', '특히', '물론', '무엇보다도', '무엇보다', '사실', '실제로'],
    'sum':  ['결론적으로', '요약하면', '요약하자면', '정리하면', '정리하자면', '종합하면', '이처럼', '이와 같이', '이렇듯', '이러한 점에서', '이런 점에서'],
    'seq':  ['먼저', '우선', '다음으로', '첫째', '둘째', '셋째', '첫 번째', '두 번째', '세 번째', '마지막으로', '끝으로', '이어서', '그다음', '그 다음'],
}
CONN_ALL = []
for cat, ws in CONN_CATS.items():
    for w in ws:
        CONN_ALL.append((w, cat))
CONN_ALL.sort(key=lambda x: -len(x[0]))
_CONN_RE = re.compile(r'^[\s"“‘\'(「]*(' + '|'.join(re.escape(w) for w, _ in CONN_ALL) + r')(?=[\s,，]|$)')
_CAT = dict(CONN_ALL)

# the narrow list used by the shipped CONNECTOR_RUN rule (src/engine/super-sejong.ts)
_ENGINE_CONN = re.compile(r'^[\s"“‘\'(「]*(또한|따라서|그러므로|이에\s*따라|더불어|아울러|결과적으로|결론적으로)(?=[,\s])')

def initial_connective(sent):
    m = _CONN_RE.match(sent)
    return m.group(1) if m else None

# ---------------------------------------------------------------- demonstratives
_DEM_PRON_INIT = re.compile(r'^[\s"“‘\'(「]*(이는|이것은|이것이|이를|이로|이에|이와|이에도|이 때문에|이 점|이러한|이런|이같은|이 같은)')
_DEM_N_TOPIC = re.compile(r'^[\s"“‘\'(「]*(이|그)\s?[가-힣]{1,6}(은|는)(?=\s)')
_DEM_I = re.compile(r'(?<![가-힣])(이러한|이런|이와 같은|이처럼|이를 통해|이를|이는|이에|이로|이것은|이것을|이것이)(?![가-힣])')
_DEM_KU = re.compile(r'(?<![가-힣])(그러한|그런|그와 같은|그처럼|그를 통해|그것은|그것을|그것이|그로|그에|그와)(?![가-힣])')

# ---------------------------------------------------------------- frames
_NOT_ONLY = re.compile(r'뿐만\s?아니라|뿐\s?아니라')
_SEQ_FIRST = re.compile(r'(?:^|[\s,])(먼저|우선|첫째|첫\s?번째)(?=[\s,])')
_SEQ_MID = re.compile(r'(?:^|[\s,])(다음으로|둘째|두\s?번째|이어서|또한)(?=[\s,])')
_SEQ_LAST = re.compile(r'(?:^|[\s,])(마지막으로|끝으로|셋째|세\s?번째|결론적으로)(?=[\s,])')
_FIRST_PERSON_INIT = re.compile(r'^[\s"“‘\'(「]*(저는|제가|나는|내가|저의|제|우리는|우리가)(?=[\s])')

def short_comma_chain(sent, seg_max=10):
    """Sentence contains >=3 consecutive short comma-separated segments (list / parallel frame candidate)."""
    segs = re.split(r'[,，]', sent)
    run = 0
    best = 0
    for sg in segs:
        n = len(re.sub(r'\s', '', sg))
        if 1 <= n <= seg_max:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best >= 3

# ---------------------------------------------------------------- crude noun proxy (no analyser)
_PARTICLES = ['에서는', '으로는', '에게는', '에서도', '으로도', '에서', '으로', '에게', '에는', '에도', '까지', '부터', '처럼', '보다', '이나', '이라',
              '은', '는', '이', '가', '을', '를', '의', '에', '로', '와', '과', '도', '만', '나', '라']
_STOP = set('이것 그것 저것 이러한 그러한 이런 그런 때문 경우 수 것 등 및 또한 하지만 그리고 그러나 따라서 매우 다른 모든 많은 여러 하는 있는 있다 한다 합니다 입니다'.split())

def noun_proxy(sent):
    out = set()
    for w in re.findall(r'[가-힣]{2,}', sent):
        stem = w
        for p in _PARTICLES:
            if stem.endswith(p) and len(stem) - len(p) >= 2:
                stem = stem[:-len(p)]
                break
        # drop obvious verb/adjective endings
        if re.search(r'(니다|습니다|하다|한다|했다|된다|있다|없다|이다|하는|되는|하고|하며|하여|해서|하면|하게|지만|으며|이며|에서|으로|하기|되어|이다)$', stem):
            continue
        if stem in _STOP or len(stem) < 2:
            continue
        out.add(stem)
    return out

# ---------------------------------------------------------------- feature computation
def _entropy(counter):
    n = sum(counter.values())
    if n <= 1:
        return 0.0
    return -sum(c / n * math.log2(c / n) for c in counter.values())

def _mean(x):
    return sum(x) / len(x) if x else float('nan')

def _sd(x):
    if len(x) < 2:
        return float('nan')
    m = _mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))

def surface_features(paras):
    """paras: list[list[str]]. Returns dict of regex-grade flow features."""
    sents = [s for p in paras for s in p]
    n = len(sents)
    f = {'n_sent': n, 'n_par': len(paras)}
    if n < 3:
        return None
    chars = sum(len(s) for s in sents)
    f['n_chars'] = chars
    L = [eoj(s) for s in sents]
    f['mean_eoj'] = _mean(L)
    f['sd_eoj'] = _sd(L)
    f['cv_eoj'] = f['sd_eoj'] / f['mean_eoj'] if f['mean_eoj'] else float('nan')
    f['max_eoj'] = max(L)
    f['share_ge20'] = sum(1 for v in L if v >= 20) / n
    f['share_le5'] = sum(1 for v in L if v <= 5) / n
    f['share_8_14'] = sum(1 for v in L if 8 <= v <= 14) / n
    # adjacent rhythm (within paragraph)
    rel = []; sim_flags = []
    run_sizes = []
    for p in paras:
        pl = [eoj(s) for s in p]
        cur = 1
        for a, b in zip(pl, pl[1:]):
            d = abs(a - b) / ((a + b) / 2) if (a + b) else 0
            rel.append(d)
            sim = d <= 0.25 and min(a, b) >= 5
            sim_flags.append(sim)
            if sim:
                cur += 1
            else:
                run_sizes.append(cur); cur = 1
        run_sizes.append(cur)
    f['mean_rel_diff'] = _mean(rel)
    f['sim_pair_share'] = _mean([1.0 if v else 0.0 for v in sim_flags]) if sim_flags else float('nan')
    f['sim_run3_share'] = sum(r for r in run_sizes if r >= 3) / n
    f['max_sim_run'] = max(run_sizes) if run_sizes else 1
    # connectives
    conn = []   # per sentence: connective or None, with paragraph index
    par_idx = []
    for pi, p in enumerate(paras):
        for si, s in enumerate(p):
            conn.append(initial_connective(s))
            par_idx.append((pi, si))
    nonfirst = [c for c, (pi, si) in zip(conn, par_idx) if not (pi == 0 and si == 0)]
    f['sic_rate'] = sum(1 for c in nonfirst if c) / max(1, len(nonfirst))
    cc = collections.Counter(c for c in nonfirst if c)
    k = sum(cc.values())
    f['sic_count'] = k
    f['sic_distinct'] = len(cc)
    f['sic_variety'] = len(cc) / k if k else float('nan')
    f['sic_entropy'] = _entropy(cc) if k else float('nan')
    f['sic_top1'] = max(cc.values()) / k if k else float('nan')
    for cat in CONN_CATS:
        f[f'sic_{cat}'] = sum(v for w, v in cc.items() if _CAT[w] == cat) / max(1, len(nonfirst))
    # adjacent pair and window-of-3 (engine rule analogue)
    pairs = 0; both = 0; run3 = 0; win3 = 0; wins = 0; eng_hits = 0
    for pi, p in enumerate(paras):
        flags = [initial_connective(s) is not None for s in p]
        engf = [bool(_ENGINE_CONN.match(s)) for s in p]
        for a, b in zip(flags, flags[1:]):
            pairs += 1; both += (a and b)
        r = 0
        for fl in flags:
            r = r + 1 if fl else 0
            if r == 3:
                run3 += 1
        for i in range(len(p) - 2):
            wins += 1
            if sum(flags[i:i + 3]) >= 2:
                win3 += 1
        for i in range(1, len(p)):
            if engf[i] and any(engf[max(0, i - 2):i]):
                eng_hits += 1
    f['sic_pair_rate'] = both / pairs if pairs else float('nan')
    f['sic_run3_per100'] = 100 * run3 / n
    f['sic_win3_rate'] = win3 / wins if wins else float('nan')
    f['engine_conn_run_per100'] = 100 * eng_hits / n
    # paragraph openings
    pfirst = [initial_connective(p[0]) is not None for p in paras if p]
    f['par_open_conn'] = _mean([1.0 if v else 0.0 for v in pfirst[1:]]) if len(pfirst) > 1 else float('nan')
    # demonstratives
    f['dem_init_pron'] = sum(1 for s in sents if _DEM_PRON_INIT.match(s)) / n
    f['dem_init_N_topic'] = sum(1 for s in sents if _DEM_N_TOPIC.match(s)) / n
    text = ' '.join(sents)
    ni = len(_DEM_I.findall(text)); nk = len(_DEM_KU.findall(text))
    f['dem_i_per1k'] = 1000 * ni / chars
    f['dem_ku_per1k'] = 1000 * nk / chars
    f['dem_i_share'] = ni / (ni + nk) if (ni + nk) else float('nan')
    f['dem_total_per_sent'] = (ni + nk) / n
    f['ireul_tonghae_per100'] = 100 * len(re.findall(r'이를\s통(?:해서?|하여)', text)) / n
    # frames
    f['not_only_per100'] = 100 * len(_NOT_ONLY.findall(text)) / n
    f['first_person_init'] = sum(1 for s in sents if _FIRST_PERSON_INIT.match(s)) / n
    f['list3_sent'] = sum(1 for s in sents if short_comma_chain(s)) / n
    # sequence triad (first -> mid -> last within document order)
    pos = {'F': [], 'M': [], 'L': []}
    for i, s in enumerate(sents):
        if _SEQ_FIRST.search(s): pos['F'].append(i)
        if _SEQ_MID.search(s): pos['M'].append(i)
        if _SEQ_LAST.search(s): pos['L'].append(i)
    f['seq_triad'] = 1.0 if (pos['F'] and pos['M'] and pos['L'] and min(pos['F']) < max(pos['M']) < max(pos['L'])) else 0.0
    # repeated first eojeol / first bigram
    firsts = [s.split()[0] if s.split() else '' for s in sents]
    adj_same = 0; adj_n = 0
    for p in paras:
        fp = [s.split()[0] if s.split() else '' for s in p]
        for a, b in zip(fp, fp[1:]):
            adj_n += 1; adj_same += (a == b and a != '')
    f['same_first_adj'] = adj_same / adj_n if adj_n else float('nan')
    bi = collections.Counter(' '.join(s.split()[:2]) for s in sents if len(s.split()) >= 2)
    f['first2_rep3'] = sum(c for c in bi.values() if c >= 3) / n
    # commas
    f['comma_per_sent'] = sum(s.count(',') + s.count('，') for s in sents) / n
    # lexical-overlap proxy (no analyser)
    props = [noun_proxy(s) for s in sents]
    jac = []; abrupt = 0; abrupt_n = 0
    flat_idx = 0
    for pi, p in enumerate(paras):
        for si, s in enumerate(p):
            i = flat_idx; flat_idx += 1
            if si == 0:
                continue
            a, b = props[i - 1], props[i]
            if a and b:
                jac.append(len(a & b) / len(a | b))
            prev2 = props[i - 1] | (props[i - 2] if si >= 2 else set())
            if len(b) >= 2 and prev2:
                abrupt_n += 1
                starter = initial_connective(s) or _DEM_PRON_INIT.match(s) or _DEM_N_TOPIC.match(s)
                if not (b & prev2) and not starter:
                    abrupt += 1
    f['jaccard_adj_proxy'] = _mean(jac)
    f['abrupt_proxy'] = abrupt / abrupt_n if abrupt_n else float('nan')
    return f

# ---------------------------------------------------------------- Kiwi features
def kiwi_features(paras, kiwi):
    sents = [s for p in paras for s in p]
    n = len(sents)
    if n < 3:
        return None
    toks = kiwi.tokenize(sents)
    nouns = []; topics = []; ecs = []
    for tl in toks:
        ns = set(); tp = []; ec = []
        for i, t in enumerate(tl):
            if t.tag in ('NNG', 'NNP') and len(t.form) >= 2:
                ns.add(t.form)
            if t.tag == 'EC':
                ec.append(t.form)
            if t.tag == 'JX' and t.form in ('은', '는') and i > 0 and tl[i - 1].tag in ('NNG', 'NNP', 'NP', 'NR', 'XSN'):
                # topic head: last noun before the particle
                tp.append((tl[i - 1].form, tl[i - 1].tag))
        nouns.append(ns); topics.append(tp); ecs.append(ec)
    f = {}
    # lexical continuity
    jac = []; none1 = 0; none2 = 0; cnt = 0; abr = 0; abrn = 0
    flat = 0
    for pi, p in enumerate(paras):
        for si, s in enumerate(p):
            i = flat; flat += 1
            if si == 0:
                continue
            a, b = nouns[i - 1], nouns[i]
            if a and b:
                jac.append(len(a & b) / len(a | b))
                cnt += 1
                none1 += (not (a & b))
            prev2 = nouns[i - 1] | (nouns[i - 2] if si >= 2 else set())
            if len(b) >= 2 and prev2:
                abrn += 1
                starter = initial_connective(s) or _DEM_PRON_INIT.match(s) or _DEM_N_TOPIC.match(s)
                if not (b & prev2) and not starter:
                    abr += 1
    f['k_jaccard_adj'] = _mean(jac)
    f['k_zero_overlap_adj'] = none1 / cnt if cnt else float('nan')
    f['k_abrupt'] = abr / abrn if abrn else float('nan')
    # topic (은/는) continuity: given = same noun in previous 3 sentences (same document)
    given = 0; tot = 0; sent_with_topic = 0; chain = 0
    for i in range(1, n):
        tps = topics[i]
        if tps:
            sent_with_topic += 1
        ctx = set().union(*nouns[max(0, i - 3):i]) if i > 0 else set()
        for form, tag in tps:
            if tag in ('NNG', 'NNP'):
                tot += 1
                given += (form in ctx)
        if tps and topics[i - 1] and any(a[0] == b[0] for a in tps for b in topics[i - 1]):
            chain += 1
    f['k_topic_sent_rate'] = sent_with_topic / max(1, n - 1)
    f['k_topic_given'] = given / tot if tot >= 2 else float('nan')
    f['k_topic_chain'] = chain / max(1, n - 1)
    # connective endings
    allec = [e for ec in ecs for e in ec]
    f['k_ec_per_sent'] = len(allec) / n
    ce = collections.Counter(allec)
    f['k_ec_distinct_per100'] = 100 * len(ce) / max(1, len(allec)) if allec else float('nan')
    f['k_ec_entropy'] = _entropy(ce) if allec else float('nan')
    f['k_ec_go_share'] = ce.get('고', 0) / len(allec) if allec else float('nan')
    f['k_sent_ec3'] = sum(1 for ec in ecs if len(ec) >= 3) / n
    f['k_nouns_per_sent'] = _mean([len(x) for x in nouns])
    return f
