"""Clarity non-regression guards of Super Sejong Engine v2 (WP-7, DESIGN.md 3.3, 3.8, T4 report 3-6).

    check(src, out, pairs, *, genre="general")  -> list[Violation]   one chunk, per aligned pair
    long_review(unit, genre="general")          -> bool              the CLR-LONG trigger (4 / 3.3)
    approx2(text)                               -> list[Finding]     CLR-APPROX2 findings (3.3)
    CODES                                       code names of this family

Why a guard and not a rule set (T4 section 0): of about 20 mechanical clarity checks only 2-3 reach a
usable precision, and a rewrite can lower clarity while it reads as polished (T4 section 6: KatFish LLM
prose carries 4-5x the bare demonstratives and agentless passives of human prose). So the engine does not
diagnose clarity beyond CLR-LONG and CLR-APPROX2; it checks that a rewrite does not make an aligned
sentence worse. Every code compares the candidate with its own source through the WP-2 pairs, so a source
that already has the pattern passes unchanged. The family is `clarity` (default mode shadow, config.py);
the false-block rate was never measured (T4 section 6), so these codes log first.

Codes (family "clarity", severity hard once the family is enforced; sentence = source sentence id, an
inserted sentence takes the one before it; detail = codes and counts only):

  clarity_longer_sentence       An output sentence is more than 2 eojeol longer than the longest source
                                sentence of its pair, or it is new above the LONG trigger (long_review), or
                                it is an inserted sentence above the trigger. Forbids E-1-style merging
                                (a 2:1 pair of two 10-eojeol sentences becoming one 19-eojeol sentence).
                                A sentence with no more characters (spaces aside) than the longest source
                                sentence never counts: the deterministic spacing fixes (할수 있다 -> 할 수 있다)
                                add eojeol and no text, and verify(x, base(x)) must stay empty.
                                Counterexamples: a split, a rewrite within +2 eojeol, a source that is already
                                above the trigger and stays within +2. Risk: a legitimate rewrite that
                                spells out a nominalisation by 3+ eojeol trips it (shadow).
  clarity_bare_demonstrative_added
                                More sentence-initial bare demonstratives (이는 이것은 이를 이에 이로 ...) in
                                the pair than in the source. 이러한 + noun is not bare. T4: an LLM flow
                                tell, 0/25 precision as an ambiguity defect, so only "do not add".
  clarity_agentless_oblig_added More agentless obligation passives (되어야 합니다, 요구됩니다) in the pair
                                without 에 의해, 에게, 께서 or 로부터. The reverse (making it active) is fine.
  clarity_acronym_gloss_dropped A source sentence glosses an acronym, ABC(풀이) or 풀이(ABC); the output keeps
                                the acronym but no gloss in either form. Dropping the acronym too is the
                                floor's name_changed, and a new unglossed acronym is the floor's too.
  clarity_number_marker_changed A number present on both sides changes the marker next to it: 배, %, %p
                                (포인트), 이상 이하 초과 미만. 20% -> 20%p, 3배 -> 3배 이상, 이상 -> 초과.
                                Spelling variants (퍼센트 = %) are the same marker; a changed number is the
                                floor's quantity_changed.
  clarity_list_structure_changed
                                A list, quotation or button unit changes its kind or marker, or list items
                                are merged or lost (T4 section 6: "changes list markers or line structure").
                                Only list, quote and button units count; plain hard-wrapped lines do not.

CLR-LONG genre values are [R] taken from T4 section 4 (P99 of eojeol per sentence: blog 26, essay human 37,
news 44, abstract 39): 28 for blog, essay and notice, 40 for report, document and general (no genre known:
the larger value, so an unknown genre gets fewer review requests, not more).
"""
from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from . import text as T
from .align import Pair
from .flow import LEXICON, PairMap, body_text
from .types import Finding, Unit, Violation

FAMILY = "clarity"
CODES: Tuple[str, ...] = ("clarity_longer_sentence", "clarity_bare_demonstrative_added",
                          "clarity_agentless_oblig_added", "clarity_acronym_gloss_dropped",
                          "clarity_number_marker_changed", "clarity_list_structure_changed")

LONG_EOJEOL: Dict[str, int] = {"blog": 28, "essay": 28, "notice": 28, "report": 40, "document": 40, "general": 40}
LONG_CLAUSES = 4          # clause endings a long sentence needs to be a review candidate (T4 section 4)
GROWTH_SLACK = 2          # eojeol an output sentence may exceed the longest source sentence of its pair by


# --------------------------------------------------------------------------
# sentence measures
# --------------------------------------------------------------------------
def eojeol_count(text: str) -> int:
    """Eojeol (space-separated words) of a sentence without its list marker."""
    return len(body_text(text).split())


def char_count(text: str) -> int:
    """Characters of a sentence without spaces and its list marker."""
    return len("".join(body_text(text).split()))


# Connective endings that open a new clause. Only multi-character endings (T5: the regex proxy has
# precision 0.96 and recall 0.08 against Kiwi, so it is conservative on purpose); a bare 고 or 서 would
# match nouns (광고, 문서).
_CLAUSE_END = re.compile(
    r"(?:하며|이며|되며|으며|하고|이고|되고|있고|없고|았고|었고|였고|했고|겠고|하여|하면|이면|되면|해서|하지만|이지만|으나"
    r"|시고|시며|시면|셔서|시다가|시니까|시거나|시므로|는데|은데|인데|니까|으니까|므로|면서|으면서|거나|이거나|다가|도록|려고"
    r"|라서|이라서|아서|어서|여서|라며|하기에)[,，]?$")


def clause_endings(words: Sequence[str]) -> int:
    """Connective endings among the eojeol before the last one."""
    return sum(1 for word in words[:-1] if _CLAUSE_END.search(word))


def long_threshold(genre: str) -> int:
    return LONG_EOJEOL.get(genre, LONG_EOJEOL["general"])


def long_review(unit: Any, genre: str = "general") -> bool:
    """CLR-LONG (T4 section 4): at least max(28, genre P99) eojeol and at least 4 clause endings, outside a
    direct quotation. `unit` is a types.Unit or a str. A heading or button is never long. A sentence that
    fuses a CTA keeps its CTA wording when it is split; that rule belongs to the plan and the CTA gate."""
    text = unit if isinstance(unit, str) else unit.text
    if getattr(unit, "kind", "body") in ("heading", "button"):
        return False
    body = body_text(text)
    words = body.split()
    if len(words) < long_threshold(genre):
        return False
    if T.mask_quotes(body) != body:
        return False
    return clause_endings(words) >= LONG_CLAUSES


# --------------------------------------------------------------------------
# CLR-APPROX2 (3.3): 약 30분 정도 -> the trailing marker is redundant
# --------------------------------------------------------------------------
_APPROX2 = re.compile(
    r"(?<![가-힣])(?:약|대략|거의)[ ]?\d[\d,.]*[ ]?[가-힣%]{0,4}?[ ]?(가량|정도|쯤|안팎|내외)")


def approx2(text: str) -> List[Finding]:
    """Double approximations (약/대략/거의 + number + 가량/정도/쯤/안팎/내외) of one sentence or paragraph, as
    SUGGEST request findings whose span is the trailing marker; fix == "" means delete it. Word boundaries
    keep 만약, 계약, 노약자 out (T4: 10/10 after the fix). `id` and `sentence` are left empty for the caller
    (diagnose) to number. Quoted text is not searched."""
    masked = T.mask_quotes(text)
    return [Finding(id="", rule="CLR-APPROX2", tier="SUGGEST", action="request", sentence="",
                    start=m.start(1), end=m.end(1), fix="") for m in _APPROX2.finditer(masked)]


# --------------------------------------------------------------------------
# patterns of the guards
# --------------------------------------------------------------------------
_OPENERS = "\\s\"“‘'(「『《"
_BARE = re.compile("[" + _OPENERS + "]*(?:" + "|".join(
    re.escape(w) for w in sorted(set(LEXICON["bare_demonstratives"]), key=lambda w: (-len(w), w))) + r")(?![가-힣])")
_OBLIGATION = re.compile(r"(?:되어야|돼야|되야|지어야|져야)\s*(?:하|한|합|해|할|함)|요구(?:됩니다|된다|되며|되는|됨|되어)")
_AGENT = re.compile(r"에\s*의해|에\s*의하여|에게|께서|로부터")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_UNIT_MARKER = re.compile(r"[ ]?(%p|%포인트|퍼센트포인트|포인트|퍼센트|%|배)")      # directly after the number
_BOUND = re.compile(r"이상(?!하)|이하(?!다)|초과|미만")                            # after a counter noun too
_WINDOW_STOP = re.compile(r"[\d.!?;:()\"“”]")
_MARKER_WINDOW = 8
_ACRONYM = r"[A-Z][A-Za-z0-9]*[A-Z0-9]"
_GLOSS_AFTER = re.compile(r"(?<![A-Za-z0-9])(" + _ACRONYM + r")\s*\(([^()\n]{2,40})\)")
_GLOSS_BEFORE = re.compile(r"([가-힣][가-힣A-Za-z ]{1,30}?)\s*\((" + _ACRONYM + r")\)")


def _marker_class(token: str) -> str:
    if token in ("%p", "%포인트", "퍼센트포인트", "포인트"):
        return "%p"
    if token in ("%", "퍼센트"):
        return "%"
    return token


def _number_markers(text: str) -> Dict[str, Set[str]]:
    """Number (commas removed) -> markers next to it: 배, %, %p right after it, 이상, 이하, 초과, 미만 within
    MARKER_WINDOW characters after it and before the next digit or stop (30개 이상, 10만 원 이하)."""
    found: Dict[str, Set[str]] = {}
    for m in _NUMBER.finditer(text):
        tail = text[m.end():m.end() + _MARKER_WINDOW]
        stop = _WINDOW_STOP.search(tail)
        if stop:
            tail = tail[:stop.start()]
        markers = set(_BOUND.findall(tail))
        unit = _UNIT_MARKER.match(tail)
        if unit:
            markers.add(_marker_class(unit.group(1)))
        found.setdefault(m.group(0).replace(",", ""), set()).update(markers)
    return found


def _glossed(text: str) -> Dict[str, int]:
    """Acronym -> 1 for every acronym that has a gloss in parentheses, in either order."""
    masked = T.mask_quotes(text)
    out: Dict[str, int] = {}
    for m in _GLOSS_AFTER.finditer(masked):
        if sum(c.isupper() for c in m.group(1)) >= 2:
            out[m.group(1)] = 1
    for m in _GLOSS_BEFORE.finditer(masked):
        if sum(c.isupper() for c in m.group(2)) >= 2:
            out[m.group(2)] = 1
    return out


def _has_gloss(text: str, acronym: str) -> bool:
    masked = T.mask_quotes(text)
    return bool(re.search(re.escape(acronym) + r"\s*\([^()\n]{2,40}\)", masked)
                or re.search(r"[가-힣]\s*\(" + re.escape(acronym) + r"\)", masked))


_SHAPE_KINDS = ("list", "quote", "button")


def _shape(units: Sequence[Unit]) -> Tuple[FrozenSet[str], Tuple[str, ...]]:
    """(kinds of the list, quote and button units, their list markers in order)."""
    kinds = frozenset(u.kind for u in units if u.kind in _SHAPE_KINDS)
    markers: List[str] = []
    for u in units:
        if u.kind == "list":
            m = T.LIST_MARKER.match(u.text)
            if m:
                markers.append(re.sub(r"\s+", "", m.group(0)))
    return kinds, tuple(markers)


def _bare_count(units: Sequence[Unit]) -> int:
    return sum(1 for u in units if u.kind == "body" and _BARE.match(T.mask_quotes(body_text(u.text))))


def _agentless_count(units: Sequence[Unit]) -> int:
    total = 0
    for u in units:
        masked = T.mask_quotes(body_text(u.text))
        if not _AGENT.search(masked):
            total += len(_OBLIGATION.findall(masked))
    return total


# --------------------------------------------------------------------------
# the guard
# --------------------------------------------------------------------------
def _v(code: str, sentence: Optional[str], detail: str) -> Violation:
    return Violation(code=code, family=FAMILY, severity="hard", sentence=sentence, detail=detail)


def _units(doc: Any) -> List[Unit]:
    return list(doc.units) if hasattr(doc, "units") else list(doc)


def check(src: Any, out: Any, pairs: Sequence[Pair], *, genre: str = "general") -> List[Violation]:
    """Clarity regressions of the candidate `out` against `src` (types.Document or a list of types.Unit),
    with `pairs` from align.align_documents(src, out); see the module docstring for the six codes.
    `genre` only selects the CLR-LONG trigger. check(x, x, align_documents(x, x)) is empty."""
    su, ou = _units(src), _units(out)
    m = PairMap(su, ou, pairs)
    trigger = long_threshold(genre)
    found: List[Violation] = []
    seen: Set[Tuple[str, Optional[str], str]] = set()

    def add(code: str, sentence: Optional[str], detail: str) -> None:
        if (code, sentence, detail) not in seen:
            seen.add((code, sentence, detail))
            found.append(_v(code, sentence, detail))

    for k, pr in enumerate(pairs):
        if not pr.out:
            continue
        sid = m.sid(k)
        s_units, o_units = [su[i] for i in pr.src], [ou[j] for j in pr.out]
        sized = [u for u in s_units if u.kind not in ("heading", "button")]
        src_max = max((eojeol_count(u.text) for u in sized), default=0)
        src_chars = max((char_count(u.text) for u in sized), default=0)
        for u in o_units:
            if u.kind in ("heading", "button"):
                continue
            length = eojeol_count(u.text)
            if pr.src and char_count(u.text) <= src_chars:      # only spacing changed (할수 있다 -> 할 수 있다)
                continue
            if pr.src and length > src_max + GROWTH_SLACK:
                add("clarity_longer_sentence", sid, f"eojeol:{src_max}->{length}")
            elif length >= trigger and src_max < trigger and long_review(u, genre):
                add("clarity_longer_sentence", sid, f"trigger:{length}")
        if _bare_count(o_units) > _bare_count(s_units):
            add("clarity_bare_demonstrative_added", sid, f"{_bare_count(s_units)}->{_bare_count(o_units)}")
        if _agentless_count(o_units) > _agentless_count(s_units):
            add("clarity_agentless_oblig_added", sid, f"{_agentless_count(s_units)}->{_agentless_count(o_units)}")
        if not pr.src:
            continue
        s_text, o_text = " ".join(u.text for u in s_units), " ".join(u.text for u in o_units)
        s_marks, o_marks = _number_markers(T.mask_quotes(s_text)), _number_markers(T.mask_quotes(o_text))
        if any(number in o_marks and o_marks[number] != markers for number, markers in s_marks.items()):
            add("clarity_number_marker_changed", sid, "marker")
        o_masked = T.mask_quotes(o_text)
        for acronym in _glossed(s_text):
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(acronym) + r"(?![A-Za-z0-9])", o_masked) and not _has_gloss(o_text, acronym):
                add("clarity_acronym_gloss_dropped", sid, "gloss")
                break
        if _shape(s_units) != _shape(o_units):
            add("clarity_list_structure_changed", sid, "list")
    return found
