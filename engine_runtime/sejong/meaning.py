"""Meaning ledger and per-sentence meaning family of Super Sejong Engine v2 (DESIGN.md 3.3, 3.8).

    ledger(text)                         -> list[str]        plan.sentences[].meaning entries
    compare(source, candidate)           -> list[Violation]  one aligned sentence pair
    check(src, out, pairs=None)          -> list[Violation]  every aligned pair of a chunk (WP-2 align)
    aspect(text), partial_negation(text)                     the two new axes, for tests and the plan

Codes (family "meaning", severity "hard"; types.CODE_RE):
  polarity_changed           clause negation count or short-negation target changed      v1
  modality_changed           ability, obligation/prohibition/no-need/recommendation, hedge,
                             certainty; double negation that means obligation is OBLIG   v1
  lexical_polarity_changed   antonym axes, quantifier classes, numeric bounds, comparison
                             orientation, before/after order                             v1
  participant_role_changed   agent/patient frames, converse verbs, focus particles       v1
  aspect_changed             progressive or resultative aspect lost                      new
  partial_negation_changed   "not all" turned into "none" (or back)                       new

The four v1 guards are the shipped engine_runtime/super_sejong.py, imported unchanged (DESIGN 4.3
lets super_sejong.py become a shim of this module; it stays the implementation for now so the
legacy engine's verify, restore and Office paths remain byte-identical). Each guard runs on one
aligned pair: the source sentence(s) and the candidate sentence(s) of a WP-2 Pair, joined by a
space for a split or a merge. _order_swapped keeps main's best-match rule (an unchanged sentence
with two 전에/후에 frames is not a swap; OD 8).

Aspect (T8 §2 Syntax and §4 item 5: 박종후 2016, 송창선 2012; E-2 "읽고 있다 → 읽는다" dropped):
  PROG  -고 있-/-고 계시- (읽고 있다, 하고 계십니다), -는 중 (읽는 중이다, 가는 중에),
        noun + 중 + copula (검토 중입니다, 공사 중인); attached 검토중 only for a closed list of
        verbal nouns, because 집중이/비중이/체중이 are ordinary nouns
        not PROG: 가지고/갖고/지니고/알고/모르고/보유하고/소유하고 있다, which are possession or
        knowledge states and rewrite to 있다/안다/모른다/보유한다 without an aspect change
  RES   -아/어 있-/-아/어 계시- (앉아 있다, 열려 있다, 쓰여 있다, 서 있다); the syllable before 있 has
        no final consonant and an ㅏ/ㅓ/ㅕ/ㅘ/ㅝ vowel; function words and particles with such a
        vowel are excluded (다/더/거/뭐/저/너/나 있다, 문제가 있다, 친구와 있다, 효과 있다, 학교에서
        있었던, 하나 더 있다), and so is the experiential -ㄴ 바 있다 (밝힌 바 있다)
  RES_STATIVE  되어/돼/-어져 있- (금지되어 있다, 예정돼 있다, 정해져 있다, 알려져 있다): the state of a
        rule, plan or fact; "금지되어 있다 → 금지된다", "예정되어 있다 → 예정일은 12월이다" keep the
        meaning (code-reviewer pairs labelled preserve), so it never triggers a flag, but it satisfies
        a strict RES on the other side; so do -ㄴ 상태 and -ㄴ 채 (열린 상태다, 켜진 채로)
  Rule  aspect_changed when the source has PROG and the candidate has none, or the source has a
        strict RES and the candidate has no RES of any kind. Only losses count, as T8 states the
        invariant ("the count of -고 있-/-어 있- per sentence must not drop"): an added -고 있-
        ("그녀는 책을 읽는다 → 읽고 있다", labelled preserve by the code-reviewer set) or an added
        -어 있- ("말이 있다 → 말이 남아 있다") is not flagged, so "증가했다 → 증가하고 있다" is an
        accepted miss. Presence, not count: merging two progressive clauses ("읽고 있고 쓰고 있다" →
        "읽고 쓰고 있다") keeps the aspect, and dropping one of two -고 있- is not flagged.
  FP risk: a dropped particle before 있다 on a noun ending in such a syllable (피자 있어요 → 피자가
        있어요) reads as RES; 하고 as the comitative particle (가족하고 있을 때) reads as PROG;
        resultative -고 있- of wearing verbs (입고 있다 → 입었다) is flagged.

Partial negation (T4 §3 CLR_NEG_SCOPE: on the blog the hits are "모든 …는 것은 아니다"; do not
edit, and the guard must keep partial negation partial):
  partial  a universal (모든, 모두, 전부, 전원, 항상, 언제나, 늘, 누구나, 매번, 하나같이, adverb 다)
           followed later in the sentence by a partial cue: -ㄴ/는 것은(이) 아니-, 건/게 아니-,
           -지는/-지만은/-진 않-/못- (not -지도, which is emphatic total negation; 전체 is a noun
           here, "전체 매출이 감소한 것은 아니다" is plain negation)
  kept     the other side is partial, or says "some … not" in another way: an existential negative
           (합격하지 못한 학생도 있다, 그렇지 않을 때도 있다) or a SOME quantifier with a negation
           (일부 학생은 합격하지 못했다)
  Rule     partial_negation_changed when one side is partial and the other side does not keep it
           ("모든 사람이 동의하는 것은 아니다" → "모든 사람이 동의하지 않는다"; and the reverse).
           반드시/꼭 are not universals here: "반드시 ~해야 하는 것은 아니다" is the no-need modality,
           which the modality guard compares.
  FP risk: a universal inside a relative clause ("항상 웃는 그가 화난 것은 아니다").

Everything here is regular expressions over one sentence pair; a pair of very long "sentences"
(no terminal punctuation for 100k chars) stays linear because every pattern is bounded.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .align import Pair, align_documents
from .types import Document, Violation

try:                                   # imported as engine_runtime.sejong.meaning
    from .. import super_sejong as _v1
except (ImportError, ValueError):      # imported as sejong.meaning with engine_runtime/ on sys.path
    import super_sejong as _v1  # type: ignore[no-redef]

FAMILY = "meaning"
CODES = ("polarity_changed", "modality_changed", "lexical_polarity_changed", "participant_role_changed",
         "aspect_changed", "partial_negation_changed")
_V1_CODE = {"polarity": "polarity_changed", "modality": "modality_changed", "lexical": "lexical_polarity_changed"}

# Legacy wrappers (DESIGN 5.1): the v1 API, unchanged, for callers that move to this module.
sentences = _v1.sentences
features = _v1.features
polarity_count = _v1.polarity_count
short_negation_targets = _v1.short_negation_targets
obligation_count = _v1.obligation_count
changed_polarity = _v1.changed_polarity
changed_sentence_modality = _v1.changed_sentence_modality
changed_lexical_polarity = _v1.changed_lexical_polarity
changed_participant_roles = _v1.changed_participant_roles
document_sentence_drift = _v1.document_sentence_drift

# --------------------------------------------------------------------------
# aspect
# --------------------------------------------------------------------------
_EXIST = r"\s*(?:있|계시|계신|계셨|계십|계세|계실)"
# -고 있-: the eojeol before 고 must have at least one syllable (a bare 고 is not a verb ending).
_PROG_GO = re.compile(r"(?<![가-힣])([가-힣]+)고" + _EXIST)
_PROG_STATE_STEMS = ("가지", "갖", "지니", "알", "모르", "보유하", "소유하")
# -는 중: the adnominal -는 right before the bound noun 중, then a copula, 에 or a word end.
_PROG_NEUN_JUNG = re.compile(r"[가-힣]는\s*중(?=이|입|인|에|$|[\s.,!?…~])")
# noun + spaced 중 + copula (검토 중입니다, 공사 중인 도로); a one-syllable word (그 중, 이 중) never
# counts, and without the copula "참가자 중 절반" is "among".
_PROG_NOUN_JUNG = re.compile(r"(?<![가-힣])[가-힣]{2,}\s+중(?=이|입|인)")
# Attached 중 only after common verbal nouns (진행중); 집중이, 비중이, 체중이 are words of their own.
_VERBAL_NOUNS = ("진행", "검토", "준비", "공사", "회의", "통화", "운영", "개발", "작업", "수리", "점검", "협의",
                 "논의", "상담", "조사", "확인", "처리", "배송", "제작", "모집", "판매", "영업", "휴가", "출장",
                 "이동", "대기", "시행", "시공", "접수", "심사", "공부", "식사", "운전", "수업", "연구", "고민",
                 "촬영", "교체", "정비", "업데이트", "설치", "충전", "로딩", "다운로드", "업로드", "생각")
_PROG_VN_JUNG = re.compile("(?:" + "|".join(_VERBAL_NOUNS) + r")\s*중(?=이|입|인|에)")
# -아/어 있-: candidate syllable right before (optional space) 있/계시.
_RES = re.compile(r"(?<![가-힣])([가-힣]*)([가-힣])" + _EXIST)
_RES_VOWELS = {0, 4, 6, 9, 14}            # ㅏ ㅓ ㅕ ㅘ ㅝ (jungseong index)
# Whole words before 있 that are not an -아/어 form: adverbs, pronouns, 것 contractions.
_RES_NOT_WORDS = {"다", "더", "또", "거", "뭐", "저", "너", "나", "좀더", "이거", "그거", "저거", "하나", "여기", "거기",
                  "저기", "어디", "누가", "뭐가", "까", "라", "가", "와", "과",
                  "바"}                               # -ㄴ 바 있다 is experiential (밝힌 바 있다), not resultative
# Last syllables that are particles (or a noun ending that is never an -아/어 form) when the word is
# longer than one syllable: 문제가 있다, 친구와 있다, 효과 있다, 이나 있다, 이라 있다.
_RES_PARTICLE_FINALS = {"가", "와", "과", "나", "라", "다", "며", "야", "까", "거", "처"}
# -ㄴ 상태 / -ㄴ 채: the syllable before must end in ㄴ (열린, 켜진, 앉은); checked in _res_equivalents.
_RES_EQUIV = re.compile(r"([가-힣])\s*(?:상태|채)(?![가-힣])|([가-힣])\s*(?:상태|채)(?=이|입|인|에|로|라|다|였)")


def _jong(ch: str) -> int:
    return (ord(ch) - 0xAC00) % 28 if "가" <= ch <= "힣" else -1


def _jung(ch: str) -> int:
    return ((ord(ch) - 0xAC00) // 28) % 21 if "가" <= ch <= "힣" else -1


def _progressive(text: str) -> int:
    count = 0
    for m in _PROG_GO.finditer(text):
        stem = m.group(1)
        if not stem.endswith(_PROG_STATE_STEMS):
            count += 1
    count += len(_PROG_NEUN_JUNG.findall(text))
    # "읽는 중이다" is already counted as -는 중
    count += sum(1 for m in _PROG_NOUN_JUNG.finditer(text) if not m.group(0).split()[0].endswith("는"))
    # A spaced verbal noun + 중 + copula is already counted above; 검토중, 회의중에 and 회의 중에 are not.
    count += sum(1 for m in _PROG_VN_JUNG.finditer(text)
                 if not re.search(r"\s", m.group(0)) or text.startswith("에", m.end()))
    return count


def _resultative(text: str) -> Tuple[int, int]:
    """(strict -아/어 있- count, stative 되어/돼/-어져 있- count)."""
    count = stative = 0
    for m in _RES.finditer(text):
        head, last = m.group(1), m.group(2)
        word = head + last
        if word in _RES_NOT_WORDS:
            continue
        if last in ("돼", "져") or word.endswith("되어"):
            stative += 1
            continue
        if _jong(last) != 0 or _jung(last) not in _RES_VOWELS:
            continue
        if head and last in _RES_PARTICLE_FINALS:
            continue
        if last == "서" and head.endswith(("에", "로", "으로")):   # 학교에서 있었던 일, 가장으로서 있을
            continue
        if last == "고":                                 # -고 있- is progressive (vowel ㅗ never matches anyway)
            continue
        count += 1
    return count, stative


def _res_equivalents(text: str) -> int:
    return sum(1 for m in _RES_EQUIV.finditer(text) if _jong(m.group(1) or m.group(2)) == 4)


def aspect(text: str) -> Dict[str, int]:
    """{"PROG", "RES", "RES_STATIVE", "RES_EQUIV"} counts for one sentence (the rule uses presence)."""
    strict, stative = _resultative(text)
    return {"PROG": _progressive(text), "RES": strict, "RES_STATIVE": stative, "RES_EQUIV": _res_equivalents(text)}


def _aspect_changed(a: Dict[str, int], b: Dict[str, int]) -> Optional[str]:
    """Detail label when the candidate `b` lost an aspect the source `a` has (losses only)."""
    if a["PROG"] and not b["PROG"]:
        return "PROG:1->0"
    if a["RES"] and not (b["RES"] or b["RES_STATIVE"] or b["RES_EQUIV"]):
        return "RES:1->0"
    return None


# --------------------------------------------------------------------------
# partial negation
# --------------------------------------------------------------------------
_UNIVERSAL = re.compile(r"모든|모두|전부|전원|항상|언제나|(?<![가-힣])늘(?=\s)|누구나|누구든|무엇이든|언제든|"
                        r"어디서나|매번|하나같이|모조리|죄다|(?<![가-힣])다(?=\s+[가-힣])")
_NOT = r"(?:아니|아닙|아닌(?![가지])|아냐|아녜)"          # not the rhetorical 아닌가/아닌지
_PARTIAL_CUE = re.compile(r"(?:것|거)\s*(?:은|는|이)\s*" + _NOT + r"|(?:(?<![가-힣])|(?<=는))(?:건|게)\s*" + _NOT + "|"
                          r"지(?:는|만은)\s*(?:않|못|아니)|진\s*(?:않|못)")
# "some … not" said without a universal: an existential negative (못한 학생도 있다, 않을 때도 있다).
_EXIST_NEG = re.compile(r"(?:않|못하|못한|없)(?:는|은|을|던)?\s+(?:[가-힣]+\s+)?(?:[가-힣]*도|경우가|때가)\s*(?:있|많|적지\s*않)")
_SOME = re.compile(r"일부|몇몇|더러|간혹|가끔|때때로|종종|어떤\s*경우")
_ANY_NEG = re.compile(r"않|못|없|아니|아닙|아닌|(?<![가-힣])안\s")


def partial_negation(text: str) -> bool:
    """True for "not all" with a universal: 모든 …는 것은 아니다, 모두 …지는 않다, 항상 그런 건 아니다."""
    universal = _UNIVERSAL.search(text)
    if universal is None:
        return False
    return _PARTIAL_CUE.search(text, universal.end()) is not None


def _keeps_partial(text: str) -> bool:
    """The text says "not all" / "some … not" in any accepted way."""
    if partial_negation(text) or _EXIST_NEG.search(text):
        return True
    return bool(_SOME.search(text) and _ANY_NEG.search(text))


def _partial_changed(source: str, candidate: str) -> Optional[str]:
    if partial_negation(source) and not _keeps_partial(candidate):
        return "PARTIAL:1->0"
    if partial_negation(candidate) and not _keeps_partial(source):
        return "PARTIAL:0->1"
    return None


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------
def _text(item: Any) -> str:
    """A str, an object with .text (types.Unit), or a sequence of those (the sides of a Pair)."""
    if isinstance(item, str):
        return item
    if hasattr(item, "text"):
        return item.text
    return " ".join(_text(part).strip() for part in item)


def _first_id(item: Any) -> Optional[str]:
    if isinstance(item, str):
        return None
    if hasattr(item, "id"):
        return item.id
    for part in item:
        found = _first_id(part)
        if found:
            return found
    return None


def _v1_codes(before: str, after: str) -> List[Tuple[str, str]]:
    """The four v1 guards on one aligned pair, exactly as workflow.verify runs them on a 1:1
    alignment (whole-pair events, comparison orientation, before/after order, roles)."""
    out: List[Tuple[str, str]] = []
    reasons = _v1._feature_diff(_v1.features(before), _v1.features(after))
    for reason in ("polarity", "modality", "lexical"):
        if reason in reasons:
            out.append((_V1_CODE[reason], reason))
    if "lexical" not in reasons:
        ca, cb = _v1._comparisons(before), _v1._comparisons(after)
        if any(k in cb and ca[k] and cb[k] and ca[k] != cb[k] for k in ca):
            out.append(("lexical_polarity_changed", "comparison"))
        elif _v1._order_swapped(before, after):
            out.append(("lexical_polarity_changed", "order"))
    if _v1.changed_participant_roles(before, after, [(before, after)]):
        out.append(("participant_role_changed", "roles"))
    return out


def codes(source: str, candidate: str) -> List[Tuple[str, str]]:
    """(code, detail) for one pair of texts, without the identical-text shortcut of compare()."""
    found = _v1_codes(source, candidate)
    detail = _aspect_changed(aspect(source), aspect(candidate))
    if detail:
        found.append(("aspect_changed", detail))
    detail = _partial_changed(source, candidate)
    if detail:
        found.append(("partial_negation_changed", detail))
    return found


def compare(source: Any, candidate: Any, *, sentence: Optional[str] = None) -> List[Violation]:
    """Meaning violations of one aligned pair. `source` and `candidate` are a str, a types.Unit or
    a sequence of them (the two sides of a 1:2 or 2:1 Pair). `sentence` defaults to the first
    source unit's id. Identical texts return [] without running the guards."""
    before, after = _text(source).strip(), _text(candidate).strip()
    if before == after or not before or not after:
        return []
    sid = sentence if sentence is not None else _first_id(source)
    return [Violation(code=code, family=FAMILY, severity="hard", sentence=sid, detail=detail)
            for code, detail in codes(before, after)]


def groups(pairs: Sequence[Pair]) -> List[Tuple[List[int], List[int]]]:
    """(source indices, candidate indices) per comparison: every pair with two sides, extended by the
    unpaired sentences (1:0, 0:1) next to it, which join the preceding pair (the following one at
    the start). The aligner prefers 1:1 + 0:1 over 1:2 when one half of a split is close to the
    source ("빠르고 가볍지만 기능이 적다" → "빠르고 가볍다. 다만 기능은 적다."), and comparing only the
    1:1 half would report the moved clause as lost. A sentence that really vanished is the floor's
    sentence_dropped; an inserted claim is compared with its neighbour instead of being ignored."""
    out: List[Tuple[List[int], List[int]]] = []
    lead_src: List[int] = []
    lead_out: List[int] = []
    for pair in pairs:
        if pair.src and pair.out:
            out.append((lead_src + list(pair.src), lead_out + list(pair.out)))
            lead_src, lead_out = [], []
        elif out:
            out[-1][0].extend(pair.src)
            out[-1][1].extend(pair.out)
        else:
            lead_src.extend(pair.src)
            lead_out.extend(pair.out)
    return out


def check(src: Document, out: Document, pairs: Optional[Sequence[Pair]] = None) -> List[Violation]:
    """Meaning family over a chunk: one comparison per group() of the WP-2 alignment (pairs default to
    align_documents(src, out)). A chunk whose candidate has no sentence pairs with the source at
    all is left to the floor. Each violation is reported once per source sentence of its group, so
    every sentence involved can be reverted."""
    if pairs is None:
        pairs = align_documents(src, out)
    found: List[Violation] = []
    for src_index, out_index in groups(pairs):
        src_units = [src.units[i] for i in sorted(src_index)]
        out_units = [out.units[j] for j in sorted(out_index)]
        hits = compare(src_units, out_units)
        for unit in src_units:
            found.extend(Violation(code=v.code, family=v.family, severity=v.severity, sentence=unit.id,
                                   detail=v.detail) for v in hits)
    return found


# --------------------------------------------------------------------------
# ledger
# --------------------------------------------------------------------------
_LEDGER_MAX = 200


def _bound_label(kind: str, value: str) -> str:
    value = re.sub(r"\s+", "", value)[:60] or "X"       # the schema allows no whitespace in a value
    return "BOUND:" + {">=": "GE", "<=": "LE", ">": "GT", "<": "LT", "~": "ABOUT"}.get(kind, "X") + ":" + value


def ledger(text: str) -> List[str]:
    """Meaning ledger entries of one sentence (plan.sentences[].meaning; pattern ^[A-Z][A-Z0-9_]*(:\\S+)?$).

    Only non-zero entries, in a fixed order: NEG, CAN_POS/CAN_NEG, OBLIG/NOREQ/REC/OPTIONAL, HEDGE,
    Q_ALL/Q_MOST/Q_SOME, BOUND, AX_<axis> (CERTX is the certainty axis), ASPECT_PROG/ASPECT_RES,
    PARTIAL_NEG. Values are counts, +1/-1 for an axis direction, and comparison:value for a bound."""
    f = _v1.features(text)
    entries: List[str] = []
    negations = f.neg + sum(f.bound.values())
    if negations:
        entries.append(f"NEG:{negations}")
    can = f.sets.get("CAN", set())
    if 1 in can:
        entries.append("CAN_POS:1")
    if -1 in can:
        entries.append(f"CAN_NEG:{max(1, f.can_neg)}")
    for cls in ("OBLIG", "NOREQ", "REC", "OPTIONAL"):
        if cls in f.sets.get("DEONT", set()):
            entries.append(f"{cls}:1")
    if f.sets.get("HEDGE"):
        entries.append("HEDGE:1")
    for cls in ("ALL", "MOST", "SOME"):
        if cls in f.sets.get("Q", set()):
            entries.append(f"Q_{cls}:1")
    for (kind, value), count in sorted(f.bounds.items()):
        entries.extend([_bound_label(kind, value)] * count)
    for name in sorted(f.axes):
        net = f.axes[name][1] - f.axes[name][-1]
        if net:
            entries.append(f"AX_{name}:{1 if net > 0 else -1}")
    marks = aspect(text)
    if marks["PROG"]:
        entries.append(f"ASPECT_PROG:{marks['PROG']}")
    if marks["RES"]:
        entries.append(f"ASPECT_RES:{marks['RES']}")
    if partial_negation(text):
        entries.append("PARTIAL_NEG:1")
    return entries[:_LEDGER_MAX]


def ledgers(units: Iterable[Any]) -> Dict[str, List[str]]:
    """{unit id: ledger} for a sequence of types.Unit."""
    return {unit.id: ledger(unit.text) for unit in units}
