"""CTA gate of Super Sejong Engine v2 (DESIGN.md 3.8; port of T6 cta_gate_final.py).

    compare(src, out, pairs=None) -> {"hard": [...], "soft": [...], "info": [...]}   (types.Violation lists)

The source CTA ledger is compared with the rewrite's ledger. Codes are lowercase (CODE_RE); a finding
carries the family "cta", its severity, the id of the SOURCE sentence it concerns (for an invented CTA:
the source sentence aligned with, or nearest before, the new sentence), `detail` = labels and numbers
only, and `keep` = the source component the writer must keep (it may be document text; `detail` never is).

  hard  cta_dropped cta_invented cta_force_weakened cta_force_strengthened cta_polarity_flipped
        cta_action_changed (closed-class acts only) cta_action_count_changed cta_condition_changed
        cta_deadline_changed cta_channel_changed cta_benefit_dropped
  soft  cta_object_changed cta_action_replaced cta_moved cta_to_deontic cta_from_deontic cta_offer_dropped
        and cta_condition_changed when a condition was reworded with no evidence that its meaning changed
        (detail "reworded", see condition_check)
  info  cta_intensity_class_changed cta_form_changed_same_force cta_speech_level_changed

Pairing. T6 paired CTA units by order or by a banded greedy score; here the sentence alignment of
align.align_documents() pairs the CTA units that stand in aligned sentences (1:1, a split's parts, a
merge's sources). CTA units left over on either side are paired by the T6 score (action, bigram overlap,
tier), which is what recognises a CTA that moved. A leftover rewrite CTA whose actions are all source
actions and that is not stronger is the part of a split, not an invention.

Severities are fixed here and were fixed in T6 before any pair set ran. Everything is linear in the
number of sentences except the leftover pairing, which is banded (±8) and runs on leftovers only.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from . import cta
from .align import Pair, align_documents
from .cta import CtaDetail, Ledger
from .types import Document, Violation

FAMILY = "cta"
HARD: FrozenSet[str] = frozenset({
    "cta_dropped", "cta_invented", "cta_force_weakened", "cta_force_strengthened", "cta_polarity_flipped",
    "cta_action_changed", "cta_action_count_changed", "cta_condition_changed", "cta_deadline_changed",
    "cta_channel_changed", "cta_benefit_dropped"})
SOFT: FrozenSet[str] = frozenset({
    "cta_object_changed", "cta_moved", "cta_action_replaced", "cta_to_deontic", "cta_from_deontic",
    "cta_offer_dropped"})
INFO: FrozenSet[str] = frozenset({
    "cta_intensity_class_changed", "cta_form_changed_same_force", "cta_speech_level_changed"})
# cta_condition_changed is hard, except for a reworded condition (soft, detail "reworded").
CODES: FrozenSet[str] = HARD | SOFT | INFO

PAIR_THRESHOLD = 0.3          # T6: leftover CTA units pair at this score or higher
PAIR_BAND = 8                 # T6: diagonal band of the leftover pairing
MAX_KEEP = 200                # schemas/check.schema.json: violation.keep maxLength

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^가-힣A-Za-z0-9]")
_DEADLINE_TAIL = re.compile(r"(?:까지|부터|이내|안에|전까지|전에|내|전|이전|이후)$")
_DIGIT = re.compile(r"\d")
_HARD_CHANNEL = re.compile(r"[\d@/.]")
CLOSED_ACTIONS: FrozenSet[str] = frozenset(
    cta.ACTION_ALIAS.get(cta.action_key(a), cta.action_key(a)) for a in cta.CLOSED_ACTIONS_RAW)


def akey(action: str) -> str:
    """Action key with the lexicon's aliases (다운로드/내려받기, 이웃추가/서이추, 카톡/카카오톡)."""
    k = cta.action_key(action)
    return cta.ACTION_ALIAS.get(k, k)


def _norm(text: str) -> str:
    return _WS.sub("", text or "")


def _chan_norm(items: Iterable[str]) -> Set[str]:
    out = set()
    for x in items:
        x = _norm(x)
        out.add(cta.CHANNEL_SYNONYMS.get(x, x))
    return out


# --------------------------------------------------------------------------
# pairing
# --------------------------------------------------------------------------
def _bigrams(text: str) -> Set[str]:
    s = _NON_ALNUM.sub("", text)
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


class _Score:
    """T6 pair score of a source and a rewrite CTA unit: action 0.5 (0.4 among the actions) + 0.35 *
    bigram Jaccard of the sentences + 0.15 for the same tier."""

    def __init__(self, S: Ledger, R: Ledger):
        self.S, self.R = S, R
        self._sg: Dict[int, Set[str]] = {}
        self._rg: Dict[int, Set[str]] = {}

    def __call__(self, i: int, j: int) -> float:
        s, r = self.S.ctas[i], self.R.ctas[j]
        sc = 0.0
        sk = cta.action_key(s.main_action)
        if sk and sk == cta.action_key(r.main_action):
            sc += 0.5
        elif sk and sk in {cta.action_key(x) for x in r.hit.actions}:
            sc += 0.4
        a = self._sg.get(i)
        if a is None:
            a = self._sg[i] = _bigrams(s.text)
        b = self._rg.get(j)
        if b is None:
            b = self._rg[j] = _bigrams(r.text)
        union = a | b
        sc += 0.35 * (len(a & b) / len(union) if union else 0.0)
        if s.hit.tier == r.hit.tier:
            sc += 0.15
        return sc


def _match(S: Ledger, R: Ledger, pairs: Sequence[Pair]) -> Tuple[Dict[int, int], Dict[int, int], Set[int]]:
    """(matched source -> rewrite, absorbed source -> rewrite, used rewrite units) over ledger indices."""
    score = _Score(S, R)
    s_at = {d.index: k for k, d in enumerate(S.ctas)}
    r_at = {d.index: k for k, d in enumerate(R.ctas)}
    matched: Dict[int, int] = {}
    absorbed: Dict[int, int] = {}
    used: Set[int] = set()
    for p in pairs:
        sk = [s_at[i] for i in p.src if i in s_at]
        rk = [r_at[j] for j in p.out if j in r_at]
        if not sk or not rk:
            continue
        if len(sk) == 1 and len(rk) == 1:
            best = (sk[0], rk[0])
        else:
            best, top = (sk[0], rk[0]), -1.0
            for a in sk:
                for b in rk:
                    sc = score(a, b)
                    if sc > top:
                        best, top = (a, b), sc
        matched[best[0]] = best[1]
        used.add(best[1])
        for a in sk:                      # a merge: the other source CTAs live in the same rewrite unit
            if a != best[0]:
                absorbed[a] = best[1]
    ls = [k for k in range(len(S.ctas)) if k not in matched and k not in absorbed]
    lr = [k for k in range(len(R.ctas)) if k not in used]
    if ls and lr:
        scored: List[Tuple[float, int, int]] = []
        for i, a in enumerate(ls):
            centre = int(i * len(lr) / max(1, len(ls)))
            for j in range(max(0, centre - PAIR_BAND), min(len(lr), centre + PAIR_BAND + 1)):
                sc = score(a, lr[j])
                if sc >= PAIR_THRESHOLD:
                    scored.append((-sc, i, j))
        scored.sort()
        taken_s: Set[int] = set()
        taken_r: Set[int] = set()
        for _, i, j in scored:
            if i in taken_s or j in taken_r:
                continue
            taken_s.add(i)
            taken_r.add(j)
            matched[ls[i]] = lr[j]
            used.add(lr[j])
    return matched, absorbed, used


def _source_sentence_of_out(pairs: Sequence[Pair]) -> Dict[int, int]:
    """Rewrite sentence index -> source sentence index: the aligned source sentence, or for an inserted
    sentence the nearest source sentence before it (after it when nothing precedes)."""
    out: Dict[int, int] = {}
    last = -1
    pending: List[int] = []
    for p in pairs:
        if p.src:
            for j in p.out:
                out[j] = p.src[0]
            for j in pending:
                out[j] = p.src[0] if last < 0 else last
            pending = []
            last = p.src[-1]
        else:
            for j in p.out:
                if last >= 0:
                    out[j] = last
                else:
                    pending.append(j)
    return out


# --------------------------------------------------------------------------
# conditions
# --------------------------------------------------------------------------
_COND = cta.LEX["condition"]
_NEG_MORPH = re.compile(_COND["negation_morphological"])
_DEADLINE_SKELETON = re.compile(_COND["deadline_skeleton"])
_OPPOSITES = tuple((o["id"], re.compile(o["a"]), re.compile(o["b"])) for o in _COND["opposites"])
_CLASS_OF: Dict[str, str] = {stem: c["id"] for c in _COND["synonym_classes"] for stem in c["stems"]}
_DIGITS = re.compile(r"\d+(?:[.,]\d+)?")
_COND_LIGHT = re.compile(r"^(?:있|없|되|하|이|인|같|보|오|가|않|나타나|생기|들|받|되시|하시)")
_COND_STRIP1 = re.compile(
    r"(?:하시다면|시다면|하신다면|하다면|라면|이라면|다면|하시면|으시면|시면|하면|으면|면|거든|는|은|이|가|을|를|도|에|의|로|과|와)$")
_COND_STRIP2 = re.compile(r"(?:하시|하|되시|되|되었|됐|돼|이)$")
_PARTICLE = re.compile(r"[이가은는을를도에의로과와]")
_HANGUL_WORDS = re.compile(r"[가-힣]+")
_CLAUSE_START = re.compile(r"[,.!?]")
CLAUSE_REACH = 80


# Syllables whose final consonant is ㅆ (았 었 했 갔 났 ...) -> the same syllable without it.
_PAST_TABLE = {c: c - 20 for c in range(0xAC00, 0xD7A4) if (c - 0xAC00) % 28 == 20}


def _drop_past(text: str) -> str:
    """Past-tense syllables lose their final ㅆ (지났 -> 지나, 갔 -> 가), so 지났다면 and 지나셨다면 share a stem."""
    return text.translate(_PAST_TABLE)


@lru_cache(maxsize=8192)
def cond_tokens(cond: Optional[str]) -> Tuple[str, ...]:
    """Content stems of a condition clause as two-syllable keys, in order (T6 _cond_tokens): endings,
    honorific -시- and the light verbs 있/없/되/하 are dropped, so 준비되면, 준비되셨다면 and
    준비가 되면 share the key 준비. A one-syllable stem before 하 keeps it (원하시면 -> 원하, 급하시면
    -> 급하; T6 dropped these stems), and the final ㅆ of a past form is dropped (지났다면 -> 지나)."""
    if not cond:
        return ()
    out: List[str] = []
    single: List[str] = []
    for w0 in _HANGUL_WORDS.findall(_drop_past(cond)):
        w = _COND_STRIP1.sub("", w0)
        if len(w) > 2:
            w = _COND_STRIP2.sub("", w)
        if len(w) >= 2 and not _COND_LIGHT.match(w):
            out.append(w[:2])
        elif len(w) == 1 and w0.startswith(w + "하") and not _PARTICLE.fullmatch(w):
            out.append(w + "하")
        elif len(w) == 1 and not _COND_LIGHT.match(w) and not _PARTICLE.fullmatch(w):
            single.append(w)
    return tuple(out or single)


def _key_in(key: str, text: str) -> bool:
    """The stem `key` occurs in `text` (a text already passed through _drop_past), with the inflections
    of an open last syllable: 나오 matches 나오면, 나온다면, 나올 때, 나옴; 급하 matches 급하시면, 급할 때,
    급한 경우, 급합니다."""
    if len(key) == 2 and "가" <= key[1] <= "힣" and (ord(key[1]) - 0xAC00) % 28 == 0:
        return _stem_rx(key).search(text) is not None
    return key in text


# Inflected forms of an open last syllable of a stem: its own jongseong variants (오 -> 온 올 옴 옵), and for
# the light-verb syllables the contractions too (하 -> 해, 되 -> 돼).
_EXTRA_FORMS = {"하": "해", "해": "하", "되": "돼", "돼": "되"}


@lru_cache(maxsize=2048)
def _stem_rx(key: str) -> "re.Pattern[str]":
    base = ord(key[1])
    forms = {chr(base + j) for j in (0, 4, 8, 16, 17)}
    extra = _EXTRA_FORMS.get(key[1])
    if extra:
        forms |= {chr(ord(extra) + j) for j in (0, 4, 8, 16, 17)}
    return re.compile(re.escape(key[0]) + "[" + "".join(sorted(forms)) + "]")


def _clauses(text: str) -> List[str]:
    """Conditional clauses of a text: from the previous clause end or [,.!?] up to a conditional ending
    (면, 거든, -ㄴ/-ㄹ 경우, -ㄴ/-ㄹ 때). Linear: every match looks back at most CLAUSE_REACH characters."""
    out: List[str] = []
    start = 0
    for m in cta.COND_ENDING.finditer(text):
        lo = max(start, m.start() - CLAUSE_REACH)
        head = text[lo:m.start()]
        cut = max((head.rfind(c) for c in ",.!?"), default=-1)
        out.append(text[lo + cut + 1:m.end()].strip())
        start = m.end()
    return out


def _skeleton(text: str) -> str:
    return "".join(_DEADLINE_SKELETON.findall(text))


def _parity(rx: "re.Pattern[str]", text: str) -> int:
    return len(rx.findall(text)) % 2


def _same_class(src_keys: Iterable[str], clause_keys: Iterable[str]) -> bool:
    mine = {_CLASS_OF[k] for k in src_keys if k in _CLASS_OF}
    return bool(mine & {_CLASS_OF[k] for k in clause_keys if k in _CLASS_OF})


def _opposite(src: str, clause: str) -> Optional[str]:
    """Id of the lexicon's opposite pair (bound, timing, ease) the clause turns around, or None."""
    for name, a, b in _OPPOSITES:
        sa, sb, ca, cb = a.search(src), b.search(src), a.search(clause), b.search(clause)
        if (sa and not sb and cb and not ca) or (sb and not sa and ca and not cb):
            return name
    return None


def _content_flip(src: str, clause: str) -> Optional[str]:
    """Numbers and the lexicon's opposites (bound, timing, ease, presence): evidence of a changed condition
    whatever the wording."""
    if set(_DIGITS.findall(src)) != set(_DIGITS.findall(clause)):
        return "number"
    return _opposite(src, clause)


def condition_check(src_cond: str, window: str, own_cond: Optional[str]) -> Optional[Tuple[str, str]]:
    """Does the rewrite keep the source CTA's condition? None when it does, else (severity, detail).

    window is the text of the matched rewrite sentence and its neighbours, own_cond the condition the
    rewrite's CTA unit carries. T6 asked one question: does the last content stem of the source condition
    occur anywhere in the window? That blocks a synonym (준비되면 -> 갖춰지면) as hard and misses a
    negation that keeps the word (준비되셨다면 -> 준비되지 않았다면). Now the stem is compared as a stem
    (-시-, endings, past -ㅆ and 하다 forms ignored, see cond_tokens) and the clause is compared as a
    clause:

      stem present, in a conditional clause   hard when that clause has another negation (지 않, 못, 안),
                                              other numbers, or turns an opposite pair of the lexicon
                                              around (이상/이하, 전/후, 어렵/쉽, 있/없); soft when no other
                                              content word of the source clause is left (대리 신청이라면
                                              -> 직접 신청이라면)
      stem absent, no conditional clause      hard "dropped" (as T6)
      stem absent, a clause present           hard when numbers or an opposite pair differ; with stems of
                                              one synonym class of the lexicon (준비/갖춰/마련, 필요/원하)
                                              the condition is kept unless the negation differs (hard);
                                              anything else is soft "reworded": only a reviewed lexicon can
                                              tell a synonym from a change (T6 section 10), and a negated
                                              paraphrase (임박했다면 -> 남지 않았다면) looks like a flip
      stem present, outside any clause        not checked (T6; 비용이 부담되시면 -> 비용 부담 없이 is missed)"""
    toks = cond_tokens(src_cond)
    if not toks:
        return None
    key = toks[-1]
    winn = _drop_past(_norm(window))
    if _key_in(key, winn):
        if own_cond and _key_in(key, _drop_past(_norm(own_cond))):
            holder: Optional[str] = own_cond
        else:
            holder = next((c for c in _clauses(window) if _key_in(key, _drop_past(_norm(c)))), None)
        if holder is None:
            return None
        flip = _content_flip(src_cond, holder)
        if flip is None and _parity(_NEG_MORPH, src_cond) != _parity(_NEG_MORPH, holder):
            flip = "negation"
        if flip:
            return "hard", flip
        # the predicate stayed but every other content word of the source clause is gone: the condition
        # was about someone or something else (대리 신청이라면 -> 직접 신청이라면)
        holder_norm = _drop_past(_norm(holder))
        if len(toks) > 1 and not any(_key_in(t, holder_norm) for t in toks[:-1]):
            return "soft", "reworded"
        return None
    # the CTA's own condition is the rewritten condition; the window is searched only when it has none
    clauses = [own_cond] if own_cond else _clauses(window)
    if not clauses:
        return "hard", "dropped"
    best = max(clauses, key=lambda c: sum(1 for t in toks if _key_in(t, _drop_past(_norm(c)))))
    flip = _content_flip(src_cond, best)
    if flip:
        return "hard", flip
    if _same_class(toks, cond_tokens(best)):
        return ("hard", "negation") if _parity(_NEG_MORPH, src_cond) != _parity(_NEG_MORPH, best) else None
    return "soft", "reworded"


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------
def _clip(text: str) -> str:
    return text if len(text) <= MAX_KEEP else text[:MAX_KEEP - 1] + "…"


def _join(items: Iterable[str]) -> str:
    return _clip(", ".join(items))


def compare(src: Document, out: Document, pairs: Optional[Sequence[Pair]] = None) -> Dict[str, List[Violation]]:
    """CTA findings of a rewrite `out` against its source `src`; `pairs` = align_documents(src, out)."""
    if pairs is None:
        pairs = align_documents(src, out)
    S, R = cta.analyse(src), cta.analyse(out)
    result: Dict[str, List[Violation]] = {"hard": [], "soft": [], "info": []}
    out_to_src = _source_sentence_of_out(pairs)

    def add(code: str, s: Optional[CtaDetail], r: Optional[CtaDetail], detail: str = "", keep: str = "",
            severity: Optional[str] = None, sentence: Optional[str] = None) -> None:
        sev = severity or ("hard" if code in HARD else "soft" if code in SOFT else "info")
        if sentence is None:
            if s is not None:
                sentence = src.units[s.index].id
            elif r is not None and r.index in out_to_src:
                sentence = src.units[out_to_src[r.index]].id
        result[sev].append(Violation(code=code, family=FAMILY, severity=sev, sentence=sentence,
                                     detail=detail, keep=_clip(keep) if keep else None))

    matched, absorbed, used = _match(S, R, pairs)
    texts = [u.text for u in out.units]
    unmatched_keys: Dict[int, Set[str]] = {}
    unmatched_text: Dict[int, str] = {}
    for j, d in enumerate(R.ctas):
        if j not in used:
            unmatched_keys.setdefault(d.index, set()).update(akey(a) for a in d.hit.actions)
            unmatched_text[d.index] = unmatched_text.get(d.index, "") + _norm(d.text)
    count_by_sent: Dict[int, Set[str]] = {}
    for d in R.ctas:
        count_by_sent.setdefault(d.index, set()).update(akey(a) for a in d.hit.actions)
    chan_global = _chan_norm(x for d in R.ctas for x in d.hit.channel)
    src_action_keys = {cta.action_key(a) for d in S.ctas for a in d.hit.actions}
    canon_s = {d.canon for d in S.deontic}
    canon_r = {d.canon for d in R.deontic}
    dn_r_keys = {d.key for d in R.deontic if d.key and d.canon not in canon_s}   # obligations the rewrite introduced
    dn_s_keys = {d.key for d in S.deontic if d.key and d.canon not in canon_r}   # obligations the rewrite removed
    src_grams: List[Set[str]] = []                                               # built on first use

    def window_of(r: CtaDetail) -> str:
        return " ".join(texts[x] for x in (r.index - 1, r.index, r.index + 1) if 0 <= x < len(texts))

    def reach(r: CtaDetail, span: Iterable[int]) -> Tuple[Set[str], str]:
        keys: Set[str] = set()
        norm = ""
        for dlt in span:
            keys |= unmatched_keys.get(r.index + dlt, set())
            norm += unmatched_text.get(r.index + dlt, "")
        return keys, norm

    # --- source CTAs without a counterpart
    for i, s in enumerate(S.ctas):
        if i in matched:
            continue
        if i in absorbed:                 # a merge: its actions must live in the merged rewrite sentence
            r = R.ctas[absorbed[i]]
            keys, extra = reach(r, (-2, -1, 0, 1, 2))
            r_keys = {akey(a) for a in r.hit.actions} | keys
            own = _norm(r.text) + extra
            if any(akey(a) not in r_keys and akey(a) not in own for a in s.hit.actions if akey(a)):
                add("cta_dropped", s, None, "merged sentence lost an action", s.text)
            continue
        main = cta.action_key(s.main_action)
        if s.hit.tier == "task" and main and main in dn_r_keys:
            add("cta_to_deontic", s, None, "imperative -> obligation", s.text)
        else:
            add("cta_dropped", s, None, "no counterpart", s.text)
    # --- rewrite CTAs without a source counterpart
    best_force = max((S.ctas[i].hit.force for i in matched), default=0)
    for j, r in enumerate(R.ctas):
        if j in used:
            continue
        rk = {cta.action_key(a) for a in r.hit.actions}
        if rk and rk <= src_action_keys and r.hit.force <= best_force:
            continue                      # a part of a split source CTA, not an invention
        if rk and (rk & dn_s_keys) and r.hit.tier == "task":
            add("cta_from_deontic", None, r, "obligation -> imperative")
            continue
        add("cta_invented", None, r, "new %s force %d" % (r.hit.form, r.hit.force))
    # --- matched pairs
    n_src = max(1, len(src.paragraphs) - 1)
    n_out = max(1, len(out.paragraphs) - 1)
    for i, j in sorted(matched.items()):
        s, r = S.ctas[i], R.ctas[j]
        su, ru = s.hit, r.hit
        win = window_of(r)
        winn = _norm(win)
        if su.polarity != ru.polarity:
            add("cta_polarity_flipped", s, r, "%s->%s" % (su.polarity, ru.polarity))
        if ru.force != su.force:
            add("cta_force_weakened" if ru.force < su.force else "cta_force_strengthened", s, r,
                "force %d->%d %s->%s" % (su.force, ru.force, su.form, ru.form))
        else:
            if su.form != ru.form:
                add("cta_form_changed_same_force", s, r, "%s->%s" % (su.form, ru.form))
            if set(su.intensity) != set(ru.intensity):
                add("cta_intensity_class_changed", s, r, "%s->%s" % ("+".join(su.intensity) or "none",
                                                                     "+".join(ru.intensity) or "none"))
        if su.level != ru.level:
            add("cta_speech_level_changed", s, r, "%s->%s" % (su.level, ru.level))
        # action(s)
        keys = [akey(a) for a in su.actions if akey(a)]
        split_keys, extra = reach(r, (-2, -1, 0, 1, 2))
        r_keys = {akey(a) for a in ru.actions} | split_keys
        own = _norm(r.text) + extra
        missing = [k for k in keys if k not in r_keys and k not in own]
        main, rw_main = akey(s.main_action), akey(r.main_action)
        rw_count = len(set().union(*[count_by_sent.get(r.index + d, set()) for d in (-1, 0, 1)]))
        if main and main not in r_keys and main not in own and cta.action_key(s.main_action) not in own:
            # closed-class acts (문의, 구독, 공감 ...) have no near-synonyms: a change is a real change;
            # open-class task verbs (제출/내다, 준비/챙기다) are often a legitimate substitution: soft
            if main in CLOSED_ACTIONS or rw_main in CLOSED_ACTIONS:
                add("cta_action_changed", s, r, "main action missing", s.main_action)
            else:
                add("cta_action_replaced", s, r, "main action replaced", s.main_action)
        elif missing:
            if rw_count < len(keys):
                add("cta_action_count_changed", s, r, "%d of %d actions missing" % (len(missing), len(keys)),
                    ", ".join(su.actions))
            else:
                add("cta_action_replaced", s, r, "action replaced", ", ".join(su.actions))
        # object (soft)
        if su.obj and _norm(su.obj)[:2] not in winn:
            add("cta_object_changed", s, r, "object missing", su.obj)
        # condition
        if su.condition:
            verdict = condition_check(su.condition, win, ru.condition)
            if verdict:
                add("cta_condition_changed", s, r, verdict[1], su.condition, severity=verdict[0])
        elif ru.condition:
            toks = cond_tokens(ru.condition)
            if toks:
                if not src_grams:
                    sn = _norm(src.text)
                    src_grams.append(set(sn) | {sn[k:k + 2] for k in range(len(sn) - 1)})
                if all(t not in src_grams[0] for t in toks):
                    add("cta_condition_changed", s, r, "added", "")
        # deadline, compared as a skeleton (numbers and deadline words): the T6 pattern for 마감 also
        # captures the six characters after it, which are not part of the deadline
        if su.deadline or ru.deadline:
            win_skel = _skeleton(winn)
        for d in su.deadline:
            ds = _skeleton(_norm(d))
            if ds not in win_skel:
                core = _DEADLINE_TAIL.sub("", ds)
                has_digit = _DIGIT.search(core) is not None
                if not (core and core in win_skel and has_digit) or not has_digit:
                    add("cta_deadline_changed", s, r, "changed", ", ".join(su.deadline))
                    break
        if not su.deadline and ru.deadline:
            src_skel = _skeleton(_norm(s.text))
            if any(_skeleton(_norm(d)) not in src_skel for d in ru.deadline):
                add("cta_deadline_changed", s, r, "added", "")
        # channel
        sc, rc = _chan_norm(su.channel), _chan_norm(ru.channel) | chan_global
        lost = sorted(c for c in sc if c not in rc and c not in winn)
        if lost:
            add("cta_channel_changed", s, r, "lost %d" % len(lost), _join(lost))
        else:
            stext = _norm(s.text)
            new_hard = [c for c in _chan_norm(ru.channel) if _HARD_CHANNEL.search(c) and c not in stext]
            if new_hard:
                add("cta_channel_changed", s, r, "added %d" % len(new_hard), "")
        # benefit
        if any(b not in win for b in su.benefit):
            add("cta_benefit_dropped", s, r, "benefit missing", ", ".join(su.benefit))
        # placement
        if abs(s.para / n_src - r.para / n_out) > 0.34:
            add("cta_moved", s, r, "paragraph %.2f->%.2f" % (s.para / n_src, r.para / n_out))
    # --- service offers ("검토해 드립니다") are part of the closing value proposition
    if S.offers and not R.offers:
        add("cta_offer_dropped", None, None, "no offer left", sentence=src.units[S.offers[0]].id)
    return result
