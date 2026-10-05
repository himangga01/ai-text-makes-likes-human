"""Flow guards of Super Sejong Engine v2 (WP-7, DESIGN.md 3.8 and 3.10, T5 report 4-6, T8 report item 4).

    check(src, out, pairs, *, seam=None, allow=None)   -> list[Violation]   one chunk, per aligned pair
    seam_check(document_src, document_out, manifest)   -> list[Violation]   after reassembly
    violation_mode(flags, violation)                   -> 'enforce' | 'shadow' | 'off'
    initial_connective(sentence)                       -> (word, class) | None
    CODES / SOFT_CODES / SHADOW_CODES                  code names of this family

Principle (T5 section 6): a flow guard never judges how good the flow is. It compares the rewrite with
the writer's own source, sentence by sentence through the WP-2 alignment, and reports structure or
connective changes the rewriter was not asked to make. Population thresholds fail on the owner's genre
(T5 section 2.3), so none is used. Nothing here is a diagnosis and nothing is requested from the model.

Codes (family "flow"; severity hard unless noted). `sentence` is the id of the source sentence the
change is attached to; an inserted sentence is attached to the source sentence before it (the one
after it at the start of the text). `detail` holds codes and counts only, never text. Counting is per
aligned pair (every source and output sentence is in exactly one WP-2 pair), on the sentence without its
list marker and with quotations masked.

  flow_transition_added      A pair gains a sentence-initial additive, summary, sequence or example
                             connective (T5 F1a-c; example = 특히 즉 예를 들어 사실 ..., added here because the
                             minimal-edit contract forbids any new connective and T8 item 4 says the count of
                             sentence-initial connectives must not rise; data/connectives.json added_classes
                             is the switch), or a causal marker: sentence-initial 그래서/따라서/..., or an
                             inline 때문/므로/로 인해 (explicitation, T8 item 4: no new causal marker without a
                             source counterpart). Swapping one causal marker for another is neutral, and
                             a sentence with 왜냐하면 and no other causal marker counts as one reason, so
                             the SSJ-A01 repair (왜냐하면 ... -> ... -기 때문이다) is neutral.
                             Also a spoken connective replaced by a written one (그래서 -> 따라서, 그리고 ->
                             또한; detail "register_upshift"). The reverse (또한 -> 그리고) is allowed (T5 B3).
  flow_contrast_changed      The number of contrast markers (하지만 그러나 다만 반면 -지만 -으나 -는데도 ...) in a
                             pair differs: lost (F2a, F3a) or added (F3b). Replacing one marker by another
                             is neutral (하지만 -> 그러나, 하지만 -> 단,). 비록/아무리/설령 count only when the
                             sentence has no other contrast marker, so the SSJ-A07 repair (비록 -기 때문에 ->
                             비록 -지만) is neutral. A repair that really changes the relation (그러나 -> 그래서)
                             is flagged; `allow` licenses it for a requested sentence.
  flow_paragraph_count_changed
                             Paragraph count differs (merge F8, split F9), or the same count with a sentence
                             moved across a paragraph boundary.
  flow_order_changed         A source sentence reappears elsewhere in the output (unpaired on both sides by
                             the monotone alignment and Dice >= MOVED_DICE): swapped sentences (F4) and
                             paragraphs (F5).
  flow_duplicate             Two adjacent output sentences (bigram cover >= 0.85 both ways) that the source
                             does not have (F12), one source sentence echoed by a neighbour (detail
                             "adjacent"), or an inserted sentence that is an exact copy of another output
                             sentence anywhere in the chunk beyond the source's own copies (detail "copy").
  flow_context_leak          An output sentence copies the read-only seam context (cover >= 0.85) and has
                             little in common with its own chunk source (cover < 0.5), T5 section 5.3.
  flow_seam_connective_changed
                             At a chunk seam the first sentence changes its initial-connective class or its
                             demonstrative starter, or the connective count of the seam window (two sentences
                             on each side) differs, 3.10.
  flow_sentence_added        (soft, SHADOW_CODES: never enforced until promoted.) An output sentence with no
                             source counterpart and cover < 0.5 against the source, a split piece with new
                             content, or any sentence inserted before the first or after the last source
                             sentence of a chunk or at a seam (detail "edge:first", "edge:last", "edge:seam";
                             DESIGN 3.10 "no new first or last sentence"). The real-rewrite false-alarm rate is
                             unknown (T5 section 6), and an allowSplit replacement may legitimately add sentences.

Genre boundary. Nothing is a genre rule: the guards compare with the source, so a source that already has
a chain of 또한 or a repeated sentence is accepted unchanged. Counterexamples that stay clean: a connective
replaced within its class, a connective count that drops (F2b is soft by design: only a lost contrast marker
is flagged), a sentence split or merged inside one paragraph (T5 B1/B2), a source that already repeats a
sentence. False-positive risk: a legitimate rewrite that adds a causal connective for clarity trips
flow_transition_added by design (T5 section 6: allowed only with an explicit override, which the engine
does not offer); a heavy rewrite of a sentence next to a moved one can be paired wrongly.

Cost. One pass over the aligned pairs; every regex runs on one sentence; moved-sentence matching only
compares unpaired sentences and is capped (MAX_MOVED_CELLS), so nothing is quadratic in the text length.
Quoted text is masked (text.mask_quotes) before any marker is counted, because quotations are frozen and
their wording is the floor's business.
"""
from __future__ import annotations

import json
import re
from bisect import bisect_left
from collections import Counter
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from . import text as T
from .align import Pair, align_documents
from .config import Flags, family_mode
from .types import Document, Unit, Violation

FAMILY = "flow"
CODES: Tuple[str, ...] = ("flow_transition_added", "flow_contrast_changed", "flow_paragraph_count_changed",
                          "flow_order_changed", "flow_duplicate", "flow_context_leak",
                          "flow_seam_connective_changed")
SOFT_CODES: Tuple[str, ...] = ("flow_sentence_added",)
# Soft codes whose false-alarm rate on real rewrites is unknown stay in shadow whatever the family mode
# says (DESIGN 3.8, 9.3). Promote one by removing it here after the S3 shadow logs.
SHADOW_CODES: FrozenSet[str] = frozenset({"flow_sentence_added"})

DUP_COVER = 0.85          # T5 flow_gate: adjacent near-duplicate, both ways
LEAK_CONTEXT = 0.85       # T5 section 5.3: copy of the seam context
LEAK_OWN = 0.5            # ... that is not in the chunk's own source
ADDED_COVER = 0.5         # T5 FLOW_SENTENCE_ADDED: cover against the source bag
MOVED_DICE = 0.7          # an unpaired source sentence and an unpaired output sentence this alike are one sentence
MIN_NORM = 12             # normalised characters; shorter sentences are never judged by cover (T5: len > 12)
MOVED_SHORT = 6           # normalised characters below which a moved sentence must match exactly
MAX_MOVED_CELLS = 40_000  # full pairing of unpaired sentences up to this many cells, windowed beyond
MOVED_WINDOW = 40
MEMBERSHIP_SCORE = 0.5    # a 1:1 pair counts for paragraph membership from this Dice on
STACK_MAX = 3             # stacked sentence-initial connectives read per sentence (그리고 또한 ...)
SEAM_WINDOW = 2           # sentences on each side of a seam (T5 section 5.3 item 4)
DUP_WINDOW = 4            # output sentences before a sentence near a seam that it is compared with


# --------------------------------------------------------------------------
# lexicon (data/connectives.json)
# --------------------------------------------------------------------------
LEXICON_PATH = Path(__file__).resolve().parent / "data" / "connectives.json"


def load_lexicon(path: Path = LEXICON_PATH) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    seen: Dict[str, str] = {}
    for cls, words in data["classes"].items():
        for word in words:
            if word in seen:
                raise ValueError(f"connectives.json: {word!r} is in {seen[word]} and {cls}")
            seen[word] = cls
    return data


LEXICON = load_lexicon()
CLASS_OF: Dict[str, str] = {w: c for c, ws in LEXICON["classes"].items() for w in ws}
ADDED_CLASSES: Tuple[str, ...] = tuple(LEXICON["added_classes"])
SPOKEN: FrozenSet[str] = frozenset(LEXICON["spoken"])
WRITTEN: FrozenSet[str] = frozenset(LEXICON["written"])


def _alt(words: Iterable[str]) -> str:
    return "|".join(re.escape(w) for w in sorted(set(words), key=lambda w: (-len(w), w)))


def _jong_n() -> str:
    """Hangul syllables whose final consonant is ㄴ (한데도, 좋은데도: the ending is written -ㄴ데도)."""
    return "".join(chr(0xAC00 + index * 28 + 4) for index in range(19 * 21))


_OPENERS = "\\s\"“‘'(「『《"
_INITIAL = re.compile("[" + _OPENERS + "]*(" + "|".join(
    re.escape(w) + ("" if w.endswith(",") else r"(?=[\s,，]|$)")
    for w in sorted(CLASS_OF, key=lambda w: (-len(w), w))) + ")")
_DEM_STARTER = re.compile("[" + _OPENERS + "]*(?:(?:" + _alt(LEXICON["demonstrative_starters"])
                          + r")(?![가-힣])|(?:이|그)\s[가-힣]{1,6}(?:은|는)(?=\s))")


# 그래도 before 되다/괜찮다 is the permission "that is fine to do" (그래도 돼요? = 그렇게 해도 돼요?), not the
# concessive connective (code review 2026-10-05).
_PERMISSION = r"(?!\s*(?:돼|되|된|됩|될|됐|괜찮))"


def _contrast_word(word: str) -> str:
    base = word.rstrip(",")
    return (("(?<![가-힣])" if len(base) <= 2 else "") + re.escape(word) + "(?![가-힣])"
            + (_PERMISSION if word == "그래도" else ""))


_CONTRAST = re.compile("|".join(
    [_contrast_word(w) for w in sorted(set(LEXICON["contrast_words"]), key=lambda w: (-len(w), w))]
    + [re.escape(w) + "(?![가-힣])" for w in sorted(set(LEXICON["contrast_endings"]), key=lambda w: (-len(w), w))
       if w not in ("는데도", "은데도")]
    + ["[" + _jong_n() + "은는]데도"]))
_CAUSAL = re.compile("(?:" + _alt(LEXICON["classes"]["causal"]) + ")(?![가-힣])|" + _alt(LEXICON["causal_markers"]))
_CONCESSIVE = re.compile(r"(?<![가-힣])(?:비록|아무리|설령|설사)(?![가-힣])")
_REASON_ADVERB = re.compile(r"(?<![가-힣])왜냐(?:하면|면)")
_QUOTE_PREFIX = re.compile(r"[ \t]*>+[ \t]*")


# --------------------------------------------------------------------------
# sentence features
# --------------------------------------------------------------------------
def body_text(text: str) -> str:
    """The sentence without its list marker, block-quote mark or bullet ("- 또한 ..." starts with 또한)."""
    prev = None
    while prev != text:
        prev = text
        m = T.LIST_MARKER.match(text) or _QUOTE_PREFIX.match(text)
        if m and m.end() > 0:
            text = text[m.end():]
    return text


def _initial(masked: str) -> Optional[Tuple[str, str]]:
    m = _INITIAL.match(masked)
    if m is None:
        return None
    word = m.group(1)
    if word == "또" and masked[m.end():].lstrip().startswith("다른"):   # "또 다른 방법": the determiner
        return None
    if word == "그래도" and re.match(_PERMISSION, masked[m.end():]) is None:   # "그래도 돼요?": permission
        return None
    return word, CLASS_OF[word]


def _stack(masked: str, first: Optional[Tuple[str, str]]) -> Tuple[Tuple[str, str], ...]:
    """Every connective stacked at the start ("그리고 또한 ...", "하지만 그래도 ..."), first one included,
    at most STACK_MAX: removing one of them is not adding the next one."""
    out: List[Tuple[str, str]] = []
    rest, cur = masked, first
    while cur is not None and len(out) < STACK_MAX:
        out.append(cur)
        m = _INITIAL.match(rest)
        rest = rest[m.end():].lstrip(" \t,，")
        cur = _initial(rest)
    return tuple(out)


def initial_connective(sentence: str) -> Optional[Tuple[str, str]]:
    """(word, class) of the sentence-initial connective, or None. Quoted text is not looked at."""
    return _initial(T.mask_quotes(body_text(sentence)))


class _Feat:
    """Marker counts of one sentence, computed once. All counts are on the quote-masked text."""

    __slots__ = ("init", "stack", "contrast", "causal", "starter", "masked")

    def __init__(self, unit: Unit):
        masked = T.mask_quotes(body_text(unit.text))
        self.masked = masked
        self.init = _initial(masked)
        self.stack = _stack(masked, self.init)
        self.contrast: List[str] = _CONTRAST.findall(masked)
        stacked = sum(1 for _word, cls in self.stack if cls == "contrast")
        if stacked > 1:                             # 하지만 그래도 ... is one contrast, stacked for emphasis
            self.contrast = self.contrast[stacked - 1:]
        if not self.contrast:                       # 비록 ... 지만 is one concession: the adverb counts only alone
            self.contrast = _CONCESSIVE.findall(masked)[:1]
        self.causal = len(_CAUSAL.findall(masked))
        if not self.causal and _REASON_ADVERB.search(masked):        # 왜냐하면 ... 때문이다 is one reason
            self.causal = 1
        self.starter = unit.kind == "body" and _DEM_STARTER.match(masked) is not None


def _features(units: Sequence[Unit]) -> List[_Feat]:
    return [_Feat(u) for u in units]


# --------------------------------------------------------------------------
# bigram cover (T5 flow_gate)
# --------------------------------------------------------------------------
_CONTENT = re.compile(r"[^가-힣\u3131-\u318eA-Za-z0-9\u4e00-\u9fff]")


def _norm(text: str) -> str:
    return _CONTENT.sub("", text)


def _bag(text: str) -> Counter:
    core = _norm(text)
    return Counter(core[i:i + 2] for i in range(len(core) - 1))


def _cover(a: Counter, b: Counter) -> float:
    """Share of a's bigrams that b also has (multiset)."""
    total = sum(a.values())
    if not total:
        return 1.0
    return sum(min(c, b.get(g, 0)) for g, c in a.items()) / total


def _is_dup(a: Counter, b: Counter) -> bool:
    ta, tb = sum(a.values()), sum(b.values())
    if not ta or not tb or min(ta, tb) < 0.8 * max(ta, tb):
        return False
    return _cover(a, b) >= DUP_COVER and _cover(b, a) >= DUP_COVER


def _dice(a: Set[str], b: Set[str]) -> float:
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0


def _gram_set(core: str) -> Set[str]:
    return {core[i:i + 2] for i in range(len(core) - 1)} if len(core) > 1 else ({core} if core else set())


# --------------------------------------------------------------------------
# pair bookkeeping
# --------------------------------------------------------------------------
def _units(doc: Any) -> List[Unit]:
    return list(doc.units) if hasattr(doc, "units") else list(doc)


def _paragraph_count(doc: Any, units: Sequence[Unit]) -> int:
    return len(doc.paragraphs) if hasattr(doc, "paragraphs") else len({u.para for u in units})


class PairMap:
    """Alignment lookups of one check: source index -> pair, output index -> pair and first source index,
    and the anchor id of every pair (the source sentence a violation of that pair is attached to)."""

    def __init__(self, su: Sequence[Unit], ou: Sequence[Unit], pairs: Sequence[Pair]):
        self.pairs = pairs
        self.src_pair: List[int] = [0] * len(su)
        self.out_src: List[Optional[int]] = [None] * len(ou)
        self.out_pair: List[int] = [0] * len(ou)
        for k, pr in enumerate(pairs):
            for i in pr.src:
                self.src_pair[i] = k
            for j in pr.out:
                self.out_pair[j] = k
                self.out_src[j] = pr.src[0] if pr.src else None
        # Anchor: the first source sentence of the pair; an inserted sentence takes the previous source
        # sentence, or the next one when it comes first.
        anchor: List[Optional[str]] = [None] * len(pairs)
        last: Optional[str] = None
        for k, pr in enumerate(pairs):
            if pr.src:
                last = su[pr.src[0]].id
            anchor[k] = last
        nxt: Optional[str] = None
        for k in range(len(pairs) - 1, -1, -1):
            if pairs[k].src:
                nxt = su[pairs[k].src[0]].id
            if anchor[k] is None:
                anchor[k] = nxt
        self.anchor = anchor

    def sid(self, k: int) -> Optional[str]:
        return self.anchor[k]


def _v(code: str, severity: str, sentence: Optional[str], detail: str, keep: Optional[str] = None) -> Violation:
    return Violation(code=code, family=FAMILY, severity=severity, sentence=sentence, detail=detail, keep=keep)


# --------------------------------------------------------------------------
# per-pair rules
# --------------------------------------------------------------------------
def _init_counts(feats: Iterable[_Feat]) -> Counter:
    """Classes of the sentence-initial connectives, stacked ones included (그리고 또한 = additive twice)."""
    return Counter(cls for f in feats for _word, cls in f.stack)


def _connective_word(word: str) -> str:
    return ("(?<![가-힣])" if len(word.rstrip(",")) <= 2 else "") + re.escape(word.rstrip(",")) + "(?![가-힣])"


def _transition(sf: List[_Feat], of: List[_Feat], one_to_one: bool) -> List[str]:
    """Labels of the transition changes of one pair, [] when none. Dropping one of two stacked connectives
    ("그리고 또한 ..." -> "또한 ...", a redundancy fix) is neither an added class nor an upshift."""
    labels: List[str] = []
    si = _init_counts(sf)
    # A connective the source sentence already has elsewhere was moved to the front, not added (그는 사실 몰랐다 ->
    # 사실 그는 몰랐다, 그런데 그는 사실 -> 그런데 사실 그는; code review 2026-10-05).
    def uses(feats: List[_Feat], word: str) -> int:
        return sum(len(re.findall(_connective_word(word), f.masked)) for f in feats)
    oi = Counter(cls for f in of for word, cls in f.stack if si[cls] or uses(of, word) > uses(sf, word))
    for cls in ADDED_CLASSES:
        if oi[cls] > si[cls]:
            labels.append(cls)
    if sum(f.causal for f in of) > sum(f.causal for f in sf):
        labels.append("causal")
    if one_to_one and sf[0].init and of[0].init and sf[0].init[0] in SPOKEN and of[0].init[0] in WRITTEN \
            and all(word != of[0].init[0] for word, _cls in sf[0].stack):
        labels.append("register_upshift")
    return labels


def _contrast(sf: List[_Feat], of: List[_Feat]) -> Tuple[Optional[str], Optional[str]]:
    """(label, kept marker) when the contrast count of the pair differs."""
    ns, no = sum(len(f.contrast) for f in sf), sum(len(f.contrast) for f in of)
    if ns == no:
        return None, None
    keep = next((m for f in sf for m in f.contrast), None)
    return ("lost" if no < ns else "added"), keep


def _moved(su: Sequence[Unit], ou: Sequence[Unit], pairs: Sequence[Pair]) -> Tuple[Set[int], Set[int]]:
    """Unpaired source sentences that reappear as unpaired output sentences: (source indices, output indices)."""
    dels = [i for pr in pairs if pr.src and not pr.out for i in pr.src]
    inss = [j for pr in pairs if pr.out and not pr.src for j in pr.out]
    if not dels or not inss:
        return set(), set()
    s_core = {i: _norm(su[i].text) for i in dels}
    o_core = {j: _norm(ou[j].text) for j in inss}
    by_text: Dict[str, List[int]] = {}
    for j in inss:
        by_text.setdefault(o_core[j], []).append(j)
    taken: Set[int] = set()
    moved_s: Set[int] = set()
    rest: List[int] = []
    for i in dels:                                  # exact moves first: one hash lookup each
        hit = next((j for j in by_text.get(s_core[i], ()) if j not in taken), None)
        if hit is not None and s_core[i]:
            taken.add(hit)
            moved_s.add(i)
        else:
            rest.append(i)
    inss = [j for j in inss if j not in taken]
    s_grams = {i: _gram_set(s_core[i]) for i in rest}
    o_grams = {j: _gram_set(o_core[j]) for j in inss}
    full = len(rest) * len(inss) <= MAX_MOVED_CELLS
    for i in rest:
        if len(s_core[i]) < MOVED_SHORT:
            continue
        if full:
            pool = inss
        else:                                       # windowed around the proportional position
            centre = round(i * len(ou) / max(1, len(su)))
            pool = [j for j in inss if abs(j - centre) <= MOVED_WINDOW]
        best, best_j = 0.0, None
        for j in pool:
            if j in taken or len(o_core[j]) < MOVED_SHORT:
                continue
            score = _dice(s_grams[i], o_grams[j])
            if score > best:
                best, best_j = score, j
        if best_j is not None and best >= MOVED_DICE:
            taken.add(best_j)
            moved_s.add(i)
    return moved_s, taken


def _membership(su: Sequence[Unit], ou: Sequence[Unit], pairs: Sequence[Pair], m: PairMap) -> Optional[Tuple[int, str]]:
    """First place where the paragraph of a well-matched 1:1 pair shifts against the pair before it:
    (index of the pair, source id), or None when every paragraph keeps its sentences together."""
    delta = 0
    for k, pr in enumerate(pairs):
        if len(pr.src) != 1 or len(pr.out) != 1 or pr.score < MEMBERSHIP_SCORE:
            continue
        now = ou[pr.out[0]].para - su[pr.src[0]].para
        if now != delta:
            return k, su[pr.src[0]].id
        delta = now
    return None


# --------------------------------------------------------------------------
# chunk level
# --------------------------------------------------------------------------
def check(src: Any, out: Any, pairs: Sequence[Pair], *, seam: Optional[Mapping[str, Any]] = None,
          allow: Optional[Mapping[str, Iterable[str]]] = None) -> List[Violation]:
    """Flow violations of one chunk, source `src` against candidate `out` (types.Document, or a list of
    types.Unit), with `pairs` from align.align_documents(src, out).

    `seam` is the read-only context of a chunk inside a longer document: {"prev": text, "next": text}
    (the plan's seam offsets resolved against the source; either may be empty or missing). A non-empty
    "prev" makes the chunk start at a seam and a non-empty "next" makes it end at one: the seam invariants
    of 3.10 are checked there and flow_context_leak looks for copies of either context text.
    `allow` maps a source sentence id to the codes a request on that sentence licenses (for a repair that
    legitimately changes a connective, for example an open-review nomination of a wrong connective); the
    engine's own FIX rules need none: SSJ-A01 (왜냐하면 -> -기 때문이다) and SSJ-A07 (비록 -기 때문에 -> 비록
    -지만) are neutral by construction. A licensed violation is dropped, not downgraded.
    check(x, x, align_documents(x, x)) is empty, with or without a seam."""
    su, ou = _units(src), _units(out)
    fs, fo = _features(su), _features(ou)
    m = PairMap(su, ou, pairs)
    found: List[Violation] = []
    moved_s, moved_o = _moved(su, ou, pairs)
    src_bag = _bag(" ".join(u.text for u in su))
    dup_out = _unexplained_duplicates(su, ou, m)
    dup_flat = {j for _, j in dup_out}

    for k, pr in enumerate(pairs):
        sid = m.sid(k)
        sf, of = [fs[i] for i in pr.src], [fo[j] for j in pr.out]
        if pr.src and pr.out:
            labels = _transition(sf, of, len(pr.src) == 1 and len(pr.out) == 1)
            label, keep = _contrast(sf, of)
        elif pr.out and not (set(pr.out) & moved_o):
            labels = _transition([], of, False)
            label, keep = _contrast([], of)
        else:                                       # deleted or moved: the floor and flow_order_changed own it
            labels, label, keep = [], None, None
        if labels:
            found.append(_v("flow_transition_added", "hard", sid, "+".join(labels)))
        if label:
            found.append(_v("flow_contrast_changed", "hard", sid, label, keep))
        if pr.out and not pr.src:
            for j in pr.out:
                if j in moved_o or j in dup_flat:
                    continue
                core = _norm(ou[j].text)
                if len(core) >= MIN_NORM and _cover(_bag(ou[j].text), src_bag) < ADDED_COVER:
                    found.append(_v("flow_sentence_added", "soft", sid, "inserted"))
        elif len(pr.src) == 1 and len(pr.out) == 2:  # split: a piece with content the source sentence lacks
            piece_src = _bag(su[pr.src[0]].text)
            for j in pr.out:
                if len(_norm(ou[j].text)) >= MIN_NORM and _cover(_bag(ou[j].text), piece_src) < ADDED_COVER:
                    found.append(_v("flow_sentence_added", "soft", sid, "split_new_content"))

    for i in sorted(moved_s):
        found.append(_v("flow_order_changed", "hard", su[i].id, "moved"))

    n_src, n_out = _paragraph_count(src, su), _paragraph_count(out, ou)
    shift = _membership(su, ou, pairs, m)
    if n_src != n_out:
        found.append(_v("flow_paragraph_count_changed", "hard", shift[1] if shift else None, f"paragraphs:{n_src}->{n_out}"))
    elif shift and not (moved_s or moved_o):          # a reorder is already reported as flow_order_changed
        found.append(_v("flow_paragraph_count_changed", "hard", shift[1], "boundaries"))

    for _, j in dup_out:
        found.append(_v("flow_duplicate", "hard", m.sid(m.out_pair[j]), "adjacent"))
    for j in _surplus_copies(su, ou, pairs, dup_flat):
        found.append(_v("flow_duplicate", "hard", m.sid(m.out_pair[j]), "copy"))

    if seam:
        prev_text, next_text = str(seam.get("prev") or ""), str(seam.get("next") or "")
        if prev_text.strip():
            found.extend(_boundary(su, ou, fs, fo, m, 0))
        if next_text.strip():
            found.extend(_boundary(su, ou, fs, fo, m, len(su)))
        found.extend(_context_leaks(ou, m, src_bag, prev_text + " " + next_text))
    found = _unique(found)
    if allow:
        licensed = {sid: set(codes) for sid, codes in allow.items()}
        found = [v for v in found if v.code not in licensed.get(v.sentence or "", ())]
    return found


def _unique(items: List[Violation]) -> List[Violation]:
    seen: Set[Tuple[str, Optional[str], str]] = set()
    out: List[Violation] = []
    for v in items:
        key = (v.code, v.sentence, v.detail)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _unexplained_duplicates(su: Sequence[Unit], ou: Sequence[Unit], m: PairMap) -> List[Tuple[int, int]]:
    """Adjacent output sentences (j-1, j) that repeat each other, unless they are the output of two source
    sentences that repeat each other the same way."""
    bags: Dict[int, Counter] = {}

    def bag(units: Sequence[Unit], i: int, cache: Dict[int, Counter]) -> Counter:
        if i not in cache:
            cache[i] = _bag(units[i].text)
        return cache[i]

    src_bags: Dict[int, Counter] = {}
    found: List[Tuple[int, int]] = []
    for j in range(1, len(ou)):
        a, b = bag(ou, j - 1, bags), bag(ou, j, bags)
        if sum(a.values()) < MIN_NORM - 1 or not _is_dup(a, b):
            continue
        s0, s1 = m.out_src[j - 1], m.out_src[j]
        if s0 is not None and s1 is not None and s1 == s0 + 1 and _is_dup(bag(su, s0, src_bags), bag(su, s1, src_bags)):
            continue
        found.append((j - 1, j))
    return found


def _surplus_copies(su: Sequence[Unit], ou: Sequence[Unit], pairs: Sequence[Pair], skip: Set[int]) -> List[int]:
    """Inserted output sentences that are exact copies (same content characters) of another output sentence
    anywhere in the chunk, when the output has more copies of that sentence than the source. Linear: one
    hash count per side; near-copies are only looked for next to each other (_unexplained_duplicates)."""
    src_count = Counter(_norm(u.text) for u in su)
    out_norm = [_norm(u.text) for u in ou]
    out_count = Counter(out_norm)
    found: List[int] = []
    for pr in pairs:
        if pr.out and not pr.src:
            for j in pr.out:
                key = out_norm[j]
                if j not in skip and len(key) >= MIN_NORM and out_count[key] >= 2 and out_count[key] > src_count[key]:
                    found.append(j)
    return found


def _context_leaks(ou: Sequence[Unit], m: PairMap, src_bag: Counter, context: str) -> List[Violation]:
    context_bag = _bag(context)
    if not context_bag:
        return []
    found: List[Violation] = []
    for j, unit in enumerate(ou):
        if len(_norm(unit.text)) < MIN_NORM:
            continue
        bag = _bag(unit.text)
        if _cover(bag, context_bag) >= LEAK_CONTEXT and _cover(bag, src_bag) < LEAK_OWN:
            found.append(_v("flow_context_leak", "hard", m.sid(m.out_pair[j]), "context"))
    return found


# --------------------------------------------------------------------------
# seams (3.10)
# --------------------------------------------------------------------------
def _boundary(su: Sequence[Unit], ou: Sequence[Unit], fs: List[_Feat], fo: List[_Feat], m: PairMap, b: int) -> List[Violation]:
    """Seam invariants at source index b (0 = start of the text, len(su) = end, otherwise the first sentence
    after an interior seam): no inserted sentence on the seam, the first sentence after it keeps its
    connective class and demonstrative starter, and the connective count of the window around it holds."""
    n = len(su)
    if n == 0 or not m.pairs:
        return []
    found: List[Violation] = []
    pairs = m.pairs
    lo, hi = max(0, b - SEAM_WINDOW), min(n, b + SEAM_WINDOW)
    first_pair = 0 if b == 0 else m.src_pair[lo]
    last_pair = len(pairs) - 1 if b == n else m.src_pair[hi - 1]
    # an insertion sits between the pair before the seam and the pair after it
    before = m.src_pair[b - 1] if b > 0 else -1
    after = m.src_pair[b] if b < n else len(pairs)
    label = "edge:first" if b == 0 else ("edge:last" if b == n else "edge:seam")
    for k in range(before + 1, after):
        if pairs[k].out and not pairs[k].src:
            found.append(_v("flow_sentence_added", "soft", m.sid(k), label))
            break
    if b < n:
        pr = pairs[m.src_pair[b]]
        if pr.out:
            s, o = fs[b], fo[pr.out[0]]
            s_cls = s.init[1] if s.init else None
            o_cls = o.init[1] if o.init else None
            if s_cls != o_cls or s.starter != o.starter:
                found.append(_v("flow_seam_connective_changed", "hard", su[b].id,
                                "first:" + ("connective" if s_cls != o_cls else "demonstrative"),
                                s.init[0] if s.init else None))
    s_count = sum(1 for i in range(lo, hi) if fs[i].init)
    o_idx = [j for k in range(first_pair, last_pair + 1) for j in pairs[k].out]
    o_count = sum(1 for j in o_idx if fo[j].init)
    if s_count != o_count:
        found.append(_v("flow_seam_connective_changed", "hard", su[min(b, n - 1)].id, f"window:{s_count}->{o_count}"))
    return found


def _seam_offsets(manifest: Any) -> List[int]:
    """Source offsets of the seams of a chunk manifest. Accepts the manifest v1 dict (chunks[].start of every
    body chunk after the first; manifest["sejong"]["seams"][].prev[1], the end of the context before a chunk,
    when present), or a plain list of offsets."""
    if isinstance(manifest, (list, tuple)):
        return sorted({int(x) for x in manifest})
    offsets: Set[int] = set()
    seams = (manifest.get("sejong") or {}).get("seams") if isinstance(manifest, Mapping) else None
    for seam in seams or []:
        prev = seam.get("prev") or (0, 0)
        if prev[1] > 0:
            offsets.add(int(prev[1]))
    if not offsets and isinstance(manifest, Mapping):
        body = [c for c in manifest.get("chunks", []) if not c.get("passthrough")]
        offsets = {int(c["start"]) for c in body[1:]}
    return sorted(offsets)


def seam_check(document_src: Document, document_out: Document, manifest: Any,
               pairs: Optional[Sequence[Pair]] = None) -> List[Violation]:
    """Seam invariants of a reassembled document (3.10): for every chunk seam of `manifest`, no sentence
    inserted on the seam, the first sentence after it keeps its connective class and demonstrative starter,
    the connective count of the window of two sentences each side holds (flow_seam_connective_changed), and
    none of the two output sentences before or after the seam repeats one of the four before it unless the
    source does (flow_duplicate, the document-level form of flow_context_leak: a sentence of the previous
    chunk's end copied into the next chunk). `pairs` defaults to
    align_documents(document_src, document_out). seam_check(x, x, manifest) is empty."""
    su, ou = _units(document_src), _units(document_out)
    if pairs is None:
        pairs = align_documents(document_src, document_out)
    fs, fo = _features(su), _features(ou)
    m = PairMap(su, ou, pairs)
    starts = [u.start for u in su]
    found: List[Violation] = []
    bags: Dict[int, Counter] = {}
    src_bags: Dict[int, Counter] = {}
    for offset in _seam_offsets(manifest):
        b = bisect_left(starts, offset)
        if b <= 0 or b >= len(su):
            continue
        found.extend(_boundary(su, ou, fs, fo, m, b))
        pr = pairs[m.src_pair[b]]
        if not pr.out:
            continue
        ob = pr.out[0]
        # An inserted sentence sits on either side of the seam in the output, so the region is the two
        # sentences before it and the two after it, each compared with the DUP_WINDOW sentences before it.
        for j in range(max(0, ob - SEAM_WINDOW), min(len(ou), ob + SEAM_WINDOW)):
            if j not in bags:
                bags[j] = _bag(ou[j].text)
            if sum(bags[j].values()) < MIN_NORM - 1:
                continue
            for i in range(max(0, j - DUP_WINDOW), j):
                if i not in bags:
                    bags[i] = _bag(ou[i].text)
                if not _is_dup(bags[i], bags[j]):
                    continue
                s0, s1 = m.out_src[i], m.out_src[j]
                if s0 is not None and s1 is not None and s0 != s1:
                    for x in (s0, s1):
                        src_bags.setdefault(x, _bag(su[x].text))
                    if _is_dup(src_bags[s0], src_bags[s1]):
                        continue
                found.append(_v("flow_duplicate", "hard", m.sid(m.out_pair[j]), "seam"))
                break
    return _unique(found)


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------
def violation_mode(flags: Flags, violation: Violation) -> str:
    """'enforce' | 'shadow' | 'off' for one violation of the flow or clarity family: the family mode of
    config.family_mode, except that SHADOW_CODES never go above shadow."""
    if violation.family is None:
        raise ValueError("violation has no family")
    mode = family_mode(flags, violation.family)
    if mode == "enforce" and violation.code in SHADOW_CODES:
        return "shadow"
    return mode
