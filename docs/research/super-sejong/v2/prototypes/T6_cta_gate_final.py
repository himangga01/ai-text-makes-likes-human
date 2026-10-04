# -*- coding: utf-8 -*-
"""CTA ledger comparison (gate) for Super Sejong v2 research track T6.

compare(source_text, rewrite_text) -> {'hard': [...], 'soft': [...], 'info': [...], 'matched': [...]}
Every finding is {'code', 'src', 'rw', 'detail'}.  Severities are fixed here and were fixed before the pair sets were run:

  hard: CTA_DROPPED CTA_INVENTED CTA_FORCE_WEAKENED CTA_FORCE_STRENGTHENED CTA_POLARITY_FLIPPED CTA_ACTION_CHANGED
        CTA_ACTION_COUNT_CHANGED CTA_CONDITION_CHANGED CTA_DEADLINE_CHANGED CTA_CHANNEL_CHANGED CTA_BENEFIT_DROPPED
  soft: CTA_OBJECT_CHANGED CTA_MOVED
  info: CTA_INTENSITY_CLASS_CHANGED CTA_FORM_CHANGED_SAME_FORCE CTA_SPEECH_LEVEL_CHANGED
"""
import re
from cta_detect import detect, split_units, action_key, deontic_units, offer_units

HARD = {'CTA_DROPPED', 'CTA_INVENTED', 'CTA_FORCE_WEAKENED', 'CTA_FORCE_STRENGTHENED', 'CTA_POLARITY_FLIPPED',
        'CTA_ACTION_CHANGED', 'CTA_ACTION_COUNT_CHANGED', 'CTA_CONDITION_CHANGED', 'CTA_DEADLINE_CHANGED',
        'CTA_CHANNEL_CHANGED', 'CTA_BENEFIT_DROPPED'}
SOFT = {'CTA_OBJECT_CHANGED', 'CTA_MOVED', 'CTA_ACTION_REPLACED', 'CTA_TO_DEONTIC', 'CTA_FROM_DEONTIC', 'CTA_OFFER_DROPPED'}
ACTION_ALIAS = {'내려': '다운', '다운': '다운', '서이': '이웃', '이웃': '이웃', '서로': '이웃', '카톡': '카카'}


def akey(a):
    k = action_key(a)
    return ACTION_ALIAS.get(k, k)


CLOSED_ACTIONS = {ACTION_ALIAS.get(action_key(a), action_key(a)) for a in ['문의', '상담', '연락', '전화', '예약', '방문', '구독', '공감', '댓글', '이웃추가', '서로이웃', '공유', '팔로우', '저장', '스크랩', '다운로드', '클릭', '신청']}

CHANNEL_SYN = {'카톡': '카카오톡', '이메일': '메일', '디엠': 'DM', '오픈카톡': '오픈채팅', '오픈채팅': '오픈채팅'}
_WS = re.compile(r'\s+')


def _canon(s):
    return re.sub(r'[\s.!?~…]+', '', s or '')


def _norm(s):
    return _WS.sub('', s or '')


def _bigrams(s):
    s = re.sub(r'[^가-힣A-Za-z0-9]', '', s)
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def _jac(a, b):
    A, B = _bigrams(a), _bigrams(b)
    return len(A & B) / len(A | B) if A | B else 0.0


def _score(s, r):
    sc = 0.0
    if action_key(s['action']) and action_key(s['action']) == action_key(r['action']):
        sc += 0.5
    elif action_key(s['action']) in {action_key(x) for x in r['actions']} and action_key(s['action']):
        sc += 0.4
    sc += 0.35 * _jac(s['text'], r['text'])
    if s['tier'] == r['tier']:
        sc += 0.15
    return sc


def _match(S, R):
    """order-preserving alignment: equal counts pair in order; otherwise greedy by score inside a diagonal band
    (O(n * band) instead of O(n * m))."""
    if len(S) == len(R):
        return list(zip(range(len(S)), range(len(R))))
    band = 8
    scored = []
    for i, s in enumerate(S):
        centre = int(i * len(R) / max(1, len(S)))
        for j in range(max(0, centre - band), min(len(R), centre + band + 1)):
            scored.append((_score(s, R[j]), i, j))
    scored.sort(reverse=True)
    used_s, used_r, out = set(), set(), []
    for sc, i, j in scored:
        if sc < 0.3 or i in used_s or j in used_r:
            continue
        used_s.add(i)
        used_r.add(j)
        out.append((i, j))
    return sorted(out)


def _window(R_sents, units, j):
    """text of the matched rewrite sentence plus its neighbours (CTA components may move to the next sentence)"""
    k = units[j]['sent_idx']
    idxs = [x for x in (k - 1, k, k + 1) if 0 <= x < len(R_sents)]
    return ' '.join(R_sents[x] for x in idxs)


_LIGHT = re.compile(r'^(?:있|없|되|하|이|인|같|보|오|가|않|나타나|생기|들|받|되시|하시)')


def _cond_tokens(cond):
    """content tokens (>= 2 syllables, light predicates removed) of a condition clause, as 2-syllable keys, in order"""
    if not cond:
        return []
    out, single = [], []
    for w in re.findall(r'[가-힣]+', cond):
        w = re.sub(r'(?:하시다면|시다면|하신다면|하다면|라면|이라면|다면|하시면|으시면|시면|하면|으면|면|거든|는|은|이|가|을|를|도|에|의|로|과|와)$', '', w)
        w = re.sub(r'(?:하시|하|되시|되|되었|됐|이)$', '', w) if len(w) > 2 else w
        if len(w) >= 2 and not _LIGHT.match(w):
            out.append(w[:2])
        elif len(w) == 1 and not _LIGHT.match(w) and not re.fullmatch(r'[이가은는을를도에의로과와]', w):
            single.append(w)
    return out or single


def _cond_key(cond):
    t = _cond_tokens(cond)
    return t[-1] if t else None


def _chan_norm(items):
    out = set()
    for x in items:
        x = _norm(x)
        out.add(CHANNEL_SYN.get(x, x))
    return out


def compare(src_text, rw_text):
    S, _ = detect(src_text)
    R, _ = detect(rw_text)
    R_sents = [x[0] for x in split_units(rw_text)]
    out = {'hard': [], 'soft': [], 'info': [], 'matched': [], 'n_src': len(S), 'n_rw': len(R)}

    def add(code, i, j, detail=''):
        sev = 'hard' if code in HARD else ('soft' if code in SOFT else 'info')
        out[sev].append({'code': code, 'src': S[i]['text'] if i is not None else None, 'rw': R[j]['text'] if j is not None else None, 'detail': detail})

    pairs = _match(S, R)
    ms = {i for i, _ in pairs}
    mr = {j for _, j in pairs}
    all_rw_text = ' '.join(R_sents)
    all_rw_norm = _norm(all_rw_text)
    src_norm = _norm(src_text)
    matched_r = {j for _, j in pairs}
    unmatched_keys_by_sent, unmatched_text_by_sent = {}, {}
    for j, u in enumerate(R):
        if j not in matched_r:
            unmatched_keys_by_sent.setdefault(u['sent_idx'], set()).update(akey(a) for a in u['actions'])
            unmatched_text_by_sent[u['sent_idx']] = unmatched_text_by_sent.get(u['sent_idx'], '') + _norm(u['text'])
    count_by_sent = {}
    for u in R:
        count_by_sent.setdefault(u['sent_idx'], set()).update(akey(a) for a in u['actions'])
    chan_global = _chan_norm([x for u in R for x in u['channel']])
    src_action_keys = {action_key(a) for s in S for a in s['actions']}
    Dn_s, Dn_r = deontic_units(src_text), deontic_units(rw_text)
    canon_s = {_canon(d['text']) for d in Dn_s}
    canon_r = {_canon(d['text']) for d in Dn_r}
    dn_r_keys = {d['key'] for d in Dn_r if d['key'] and _canon(d['text']) not in canon_s}      # deontic statements the rewrite introduced
    dn_s_keys = {d['key'] for d in Dn_s if d['key'] and _canon(d['text']) not in canon_r}      # deontic statements the rewrite removed
    for i, s in enumerate(S):
        if i not in ms:
            # an instruction-tier imperative rewritten as "해야 합니다" keeps the advice but loses the direct address
            if s['tier'] == 'task' and action_key(s['action']) and action_key(s['action']) in dn_r_keys:
                add('CTA_TO_DEONTIC', i, None)
            else:
                add('CTA_DROPPED', i, None)
    best_force = max([S[i]['force'] for i, _ in pairs], default=0)
    for j, r in enumerate(R):
        if j in mr:
            continue
        # a split part of a source CTA is not an invention: same actions, not stronger
        rk = {action_key(a) for a in r['actions']}
        if rk and rk <= src_action_keys and r['force'] <= best_force:
            continue
        if rk and (rk & dn_s_keys) and r['tier'] == 'task':
            add('CTA_FROM_DEONTIC', None, j)
            continue
        add('CTA_INVENTED', None, j)
    n_doc = max([u['para'] for u in S] + [1])
    n_doc_rw = max([u['para'] for u in R] + [1])
    for i, j in pairs:
        s, r = S[i], R[j]
        win = _window(R_sents, R, j)
        winn = _norm(win)
        out['matched'].append((i, j))
        if s['polarity'] != r['polarity']:
            add('CTA_POLARITY_FLIPPED', i, j)
        # --- force
        if r['force'] != s['force']:
            add('CTA_FORCE_WEAKENED' if r['force'] < s['force'] else 'CTA_FORCE_STRENGTHENED', i, j, '%d->%d' % (s['force'], r['force']))
        else:
            if s['form'] != r['form']:
                add('CTA_FORM_CHANGED_SAME_FORCE', i, j, '%s->%s' % (s['form'], r['form']))
            if set(s['intensity']) != set(r['intensity']):
                add('CTA_INTENSITY_CLASS_CHANGED', i, j, '%s->%s' % (s['intensity'], r['intensity']))
        if s['level'] != r['level']:
            add('CTA_SPEECH_LEVEL_CHANGED', i, j, '%s->%s' % (s['level'], r['level']))
        # --- action(s)
        keys = [akey(a) for a in s['actions'] if akey(a)]
        split_keys = set().union(*[unmatched_keys_by_sent.get(r['sent_idx'] + d, set()) for d in (-2, -1, 0, 1, 2)])
        r_keys = {akey(a) for a in r['actions']} | split_keys
        own_norm = _norm(r['text']) + ''.join(unmatched_text_by_sent.get(r['sent_idx'] + d, '') for d in (-2, -1, 0, 1, 2))
        missing = [k for k in keys if k not in r_keys and k not in own_norm]
        main = akey(s['action'])
        rw_main = akey(r['action'])
        rw_count = len(set().union(*[count_by_sent.get(r['sent_idx'] + d, set()) for d in (-1, 0, 1)]))
        if main and main not in r_keys and main not in own_norm and action_key(s['action']) not in own_norm:
            # closed-class communication/engagement acts (문의, 구독, 공감 ...) have no near-synonyms: a change is a real change.
            # open-class task verbs (제출/내다, 준비/챙기다) are often legitimate lexical substitutions: soft.
            if main in CLOSED_ACTIONS or rw_main in CLOSED_ACTIONS:
                add('CTA_ACTION_CHANGED', i, j, 'main action %s missing' % s['action'])
            else:
                add('CTA_ACTION_REPLACED', i, j, '%s -> %s' % (s['action'], r['action']))
        elif missing:
            if rw_count < len(keys):
                add('CTA_ACTION_COUNT_CHANGED', i, j, 'missing %s' % missing)
            else:
                add('CTA_ACTION_REPLACED', i, j, 'missing %s' % missing)
        # --- object (soft)
        if s['object']:
            ok = _norm(s['object'])[:2] in winn
            if not ok:
                add('CTA_OBJECT_CHANGED', i, j, s['object'])
        # --- condition
        ck = _cond_key(s['condition'])
        if ck:
            if ck not in winn:
                add('CTA_CONDITION_CHANGED', i, j, 'condition %s dropped/changed' % s['condition'])
        elif r['condition']:
            toks_r = _cond_tokens(r['condition'])
            if toks_r and all(t not in src_norm for t in toks_r):
                add('CTA_CONDITION_CHANGED', i, j, 'condition %s added' % r['condition'])
        # --- deadline
        for d in s['deadline']:
            dn = _norm(d)
            if dn not in winn:
                # allow the bare date/number form when the rewrite dropped only a postposition
                core = re.sub(r'(?:까지|부터|이내|안에|전까지|전에|내|전|이전|이후)$', '', dn)
                if not (core and core in winn and re.search(r'\d', core)) or re.search(r'\d', core) is None:
                    add('CTA_DEADLINE_CHANGED', i, j, d)
                    break
        else:
            pass
        if not s['deadline'] and r['deadline']:
            if any(_norm(d) not in _norm(s['text']) for d in r['deadline']):
                add('CTA_DEADLINE_CHANGED', i, j, 'added %s' % r['deadline'])
        # --- channel
        sc, rc = _chan_norm(s['channel']), _chan_norm(r['channel']) | chan_global
        lost = [c for c in sc if c not in rc and c not in winn]
        if lost:
            add('CTA_CHANNEL_CHANGED', i, j, 'lost %s' % lost)
        else:
            new_hard = [c for c in _chan_norm(r['channel']) if re.search(r'[\d@/.]', c) and c not in _norm(s['text'])]
            if new_hard:
                add('CTA_CHANNEL_CHANGED', i, j, 'added %s' % new_hard)
        # --- benefit
        if any(b not in win for b in s['benefit']):
            add('CTA_BENEFIT_DROPPED', i, j, str(s['benefit']))
        # --- placement
        if abs(s['para'] / n_doc - r['para'] / n_doc_rw) > 0.34:
            add('CTA_MOVED', i, j)
    # --- service offers ("검토해 드립니다") are part of the closing value proposition; losing all of them is a soft signal
    O_s, O_r = offer_units(src_text), offer_units(rw_text)
    if O_s and not O_r:
        out['soft'].append({'code': 'CTA_OFFER_DROPPED', 'src': O_s[0]['text'], 'rw': None, 'detail': ''})
    return out


def verdict(res, level='hard'):
    """True when the rewrite is accepted."""
    if res['hard']:
        return False
    if level == 'soft' and res['soft']:
        return False
    return True



def strict_identity(src_text, rw_text):
    """Idempotent mode for text that was already processed once: every source CTA sentence must reappear unchanged
    (whitespace and end punctuation ignored); a sentence that carries a deterministic wording defect must reappear as
    exactly safe_repair(sentence).  Returns the list of CTA sentences that were edited."""
    from cta_detect import safe_repair
    S, _ = detect(src_text)
    rw_set = {_canon(s) for s, _, _ in split_units(rw_text)}
    edited = []
    for u in S:
        fixed = safe_repair(u['text'])[0]
        if _canon(u['text']) in rw_set or _canon(fixed) in rw_set:
            continue
        edited.append(u['text'])
    return edited


if __name__ == '__main__':
    import sys, json
    print(json.dumps(compare(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=1))
