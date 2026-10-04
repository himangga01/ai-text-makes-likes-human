"""Proposed v2 flow guard (regex-grade, stdlib only). check(src, out) -> (detected, codes).
Compares structure and connective profile of a rewrite against its source; never judges absolute 'flow quality'."""
import re, collections
from flowlib import split_sentences, initial_connective, CONN_CATS, CONN_ALL

_CAT = dict(CONN_ALL)

def _paragraphs(text):
    return [p.strip() for p in re.split(r'\n\s*\n+', text.strip()) if p.strip()]

def _bg(s):
    s = re.sub(r'\s+', '', s)
    return collections.Counter(s[i:i + 2] for i in range(len(s) - 1))

def _cover(a, b):
    """share of a's bigrams present in b"""
    ga, gb = _bg(a), _bg(b)
    t = sum(ga.values())
    return sum(min(c, gb[g]) for g, c in ga.items()) / t if t else 1.0

_CONTRAST = re.compile(r'하지만|그러나|그렇지만|그런데|다만|반면|지만(?![가-힣])|으나(?![가-힣])|ㄴ데도|는데도|에도\s*불구')

def _init_counts(text):
    c = collections.Counter()
    for p in _paragraphs(text):
        for s in split_sentences(p):
            w = initial_connective(s)
            if w: c[_CAT[w]] += 1
    return c

def check(src, out):
    codes = []
    ps, po = _paragraphs(src), _paragraphs(out)
    if len(ps) != len(po):
        codes.append('paragraph_count_changed')
    else:
        for a, b in zip(ps, po):
            if len(a) > 40 and _cover(a, b) < 0.45:
                codes.append('paragraph_order_changed'); break
        # sentence order inside each paragraph
        for a, b in zip(ps, po):
            sa, sb = split_sentences(a), split_sentences(b)
            if len(sa) < 2 or not sb: continue
            idx = []
            for s in sa:
                if len(s) < 12: continue
                best = max(range(len(sb)), key=lambda j: _cover(s, sb[j]))
                if _cover(s, sb[best]) >= 0.4: idx.append(best)
            if any(y < x for x, y in zip(idx, idx[1:])):
                codes.append('sentence_order_changed'); break
    ci, co = _init_counts(src), _init_counts(out)
    if sum(max(0, co[k] - ci[k]) for k in ('add', 'cau', 'sum')) >= 1:
        codes.append('transition_added')
    if len(_CONTRAST.findall(out)) < len(_CONTRAST.findall(src)):
        codes.append('contrast_marker_lost')
    if len(_CONTRAST.findall(out)) > len(_CONTRAST.findall(src)):
        codes.append('contrast_marker_added')
    # duplicated adjacent sentence not in source
    def adj_dups(text):
        n = 0
        for p in _paragraphs(text):
            ss = split_sentences(p)
            for x, y in zip(ss, ss[1:]):
                if len(x) > 15 and _cover(x, y) >= 0.85 and _cover(y, x) >= 0.85: n += 1
        return n
    if adj_dups(out) > adj_dups(src):
        codes.append('duplicated_sentence')
    # sentence with no counterpart in the source (new content)
    whole = src
    for p in po:
        for s in split_sentences(p):
            if len(s) > 12 and _cover(s, whole) < 0.5:
                codes.append('sentence_added'); break
        else:
            continue
        break
    return bool(codes), sorted(set(codes))
