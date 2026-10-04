"""Meaning ledger and per-sentence meaning family of Super Sejong Engine v2 (DESIGN.md 3.3, 3.8).

    ledger(text)                         -> list[str]        plan.sentences[].meaning entries
    compare(source, candidate)           -> list[Violation]  one aligned sentence pair
    check(src, out, pairs=None)          -> list[Violation]  every aligned pair of a chunk (WP-2 align)
    aspect(text), partial_negation(text)                     the two new axes, for tests and the plan
    findings(source, candidate)          -> [(code, detail, keep)]   compare() without the identity shortcut
    temporal(text), drops(source, candidate)                 WP-10b axes, for tests and measurements

Codes (family "meaning", severity "hard" unless noted; types.CODE_RE):
  polarity_changed           clause negation count or short-negation target changed      v1
  modality_changed           ability, obligation/prohibition/no-need/recommendation, hedge,
                             certainty; double negation that means obligation is OBLIG   v1
  lexical_polarity_changed   antonym axes, quantifier classes, numeric bounds, comparison
                             orientation, before/after order                             v1
  participant_role_changed   agent/patient frames, converse verbs, focus particles       v1
  aspect_changed             progressive or resultative aspect lost                      new
  partial_negation_changed   "not all" turned into "none" (or back)                       new
  participant_role_changed   (WP-10b) also per clause: a frame of a coordinated clause reversed
  temporal_order_changed     BEFORE <-> AFTER marker flip (전에 -> 뒤에, 먼저 -> 나중에)       WP-10b
  condition_dropped          a conditional clause (-면, 경우, -어야) gone with its content word WP-10b
  content_dropped            (soft; config.SHADOW_CODES) content words gone without a licence WP-10b

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
  Rule  aspect_changed when the source has PROG and the candidate has none and gained a past mark
        (했, 었, 됐 …) or a future mark (-겠-, -ㄹ 것/예정), or the source has a strict RES and the
        candidate has no RES of any kind. Progressive -> simple non-past is neutral (WP-10b, lead item
        A: 검토하고 있습니다 -> 검토합니다; the non-past covers ongoing and habitual meaning); this drops the
        E-2 "읽고 있다 -> 읽는다" flag of the WP-5 design. Only losses count, as T8 states the
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
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import text as T
from .align import Pair, align_documents
from .types import Document, Violation

try:                                   # imported as engine_runtime.sejong.meaning
    from .. import super_sejong as _v1
except (ImportError, ValueError):      # imported as sejong.meaning with engine_runtime/ on sys.path
    import super_sejong as _v1  # type: ignore[no-redef]

FAMILY = "meaning"
CODES = ("polarity_changed", "modality_changed", "lexical_polarity_changed", "participant_role_changed",
         "aspect_changed", "partial_negation_changed", "temporal_order_changed", "condition_dropped",
         "content_dropped")
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


_FUTURE = re.compile(r"겠|[가-힣]\s*(?:것|거|예정|계획)(?=[이입인을으일]|$|[\s.,!?])")


def _tense(text: str) -> Tuple[int, int]:
    """(past, future) marks: syllables with final ㅆ except 있/겠 (했, 었, 됐, 렸 …), and -겠- or an adnominal
    -ㄹ before 것/거/예정/계획 (할 것이다, 열릴 예정)."""
    past = sum(1 for ch in text if _jong(ch) == 20 and ch not in "있겠")
    future = sum(1 for m in _FUTURE.finditer(text) if m.group(0) == "겠" or _jong(m.group(0)[0]) == 8)
    return past, future


def _aspect_changed(a: Dict[str, int], b: Dict[str, int], source: str = "", candidate: str = "") -> Optional[str]:
    """Detail label when the candidate `b` lost an aspect the source `a` has (losses only). A lost
    progressive counts only when the candidate also gained a past or future mark: the Korean simple non-past
    covers ongoing and habitual meaning (검토하고 있습니다 -> 검토합니다, 영업을 진행하고 있습니다 -> 영업합니다;
    lead item A, WP-10b), while 오르고 있다 -> 올랐다 and 개발 중입니다 -> 개발했습니다 still change the aspect."""
    if a["PROG"] and not b["PROG"]:
        (pa, fa), (pb, fb) = _tense(source), _tense(candidate)
        if pb > pa:
            return "PROG:1->PAST"
        if fb > fa:
            return "PROG:1->FUTURE"
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
# temporal order (WP-10b)
# --------------------------------------------------------------------------
# BEFORE: -기 전/이전/직전, a time phrase + 전 (3일 전, 얼마 전, 식사 전에), 이전에, 앞서, 먼저, 미리, 사전에.
# AFTER:  adnominal -ㄴ + 뒤/후/다음 (마친 뒤, 끝난 후, 한 다음에), -고 나서, standalone 후/뒤 (식사 후, 3일 뒤,
#         그 후), 이후, 직후, 나중에, 뒤이어, 사후에.
# 전 needs a preceding -기, a digit, a space, or a closed time word, and a following 에/엔/까지/부터/의 or the
# end of the word, so 전국, 전체, 전혀, 전문 never count; "전 직원" (all staff) is excluded by the follower.
_BEFORE_RE = re.compile(
    r"기\s*(?:이|직)?전(?![가-힣])|기\s*(?:이|직)?전(?=에|엔|까지|부터|의)"
    r"|(?:(?<=\d)|(?<=[\d가-힣]\s)|(?<=얼마|조금|오래|며칠|방금|일찍|진작))전(?=에|엔|까지|부터|만\s*해도|$|[\s.,!?])(?!\s+[가-힣]+(?:을|를|이|가|은|는)\s)"
    r"|(?<![가-힣])(?:이전|직전)(?=에|엔|까지|부터|의|$|[\s.,!?])"
    r"|(?<![가-힣])앞서(?![가-힣])|(?<![가-힣])먼저(?![가-힣])|(?<![가-힣])미리(?![가-힣])|(?<![가-힣])사전에(?![가-힣])")
_AFTER_NOUN = re.compile(r"([가-힣])\s*(?:뒤|후|다음)(?=에|엔|로|부터|까지|의|$|[\s.,!?])")
_AFTER_RE = re.compile(
    r"고\s*나서|고\s*나니|(?<![가-힣])(?:후|뒤)(?=에|엔|로|부터|까지|$|[\s.,!?])"
    r"|(?<![가-힣])(?:이후|직후|뒤이어|나중에|나중엔|사후에)(?![가-힣])|(?<![가-힣])그\s*다음")


def temporal(text: str) -> Tuple[int, int]:
    """(BEFORE, AFTER) marker counts of one sentence (quotations included; both sides are read alike)."""
    if len(text) > 4000:
        text = text[:2000] + " " + text[-2000:]
    # markers are counted by end position, so "하기 전" (-기 전 and the spaced 전) and "한 뒤" (adnominal and
    # standalone 뒤) count once
    before = {m.end() for m in _BEFORE_RE.finditer(text)}
    after = {m.end() for m in _AFTER_RE.finditer(text)}
    # adnominal -ㄴ (final ㄴ) right before 뒤/후/다음: 마친 뒤, 끝난 후, 한 다음에
    after.update(m.end() for m in _AFTER_NOUN.finditer(text) if _jong(m.group(1)) == 4)
    return len(before), len(after)


def _temporal_changed(source: str, candidate: str) -> Optional[str]:
    """BEFORE<->AFTER flip: one direction lost and the other gained. Synonyms in one direction (뒤에 <-> 후에
    <-> 다음에, 전에 <-> 앞서 <-> 이전에) keep both counts, and a marker that is only dropped or only added
    (전에 -> 때까지, "먼저 확인하세요" -> "확인하세요") is not a flip."""
    sb, sa = temporal(source)
    cb, ca = temporal(candidate)
    if sb > cb and ca > sa:
        return "BEFORE->AFTER"
    if sa > ca and cb > sb:
        return "AFTER->BEFORE"
    return None


# --------------------------------------------------------------------------
# participant roles per clause (WP-10b)
# --------------------------------------------------------------------------
# v1 _frame reads one frame per sentence and gives up when a sentence has two subjects, so a swap across a
# coordinated sentence ("시청은 업체에 … 통보했고, 업체는 이에 반발하여 …" -> "업체는 시청에 …, 시청은 …", seed
# damage T08) passed. The sentence is cut into clauses at commas and at eojeols that end in a clausal
# connective; every clause gets the v1 frame, and a (agent, other) pair of a source clause that appears
# reversed in a candidate clause, while the original order appears in none, is a swap unless the two clause
# predicates are converses (빌리다/빌려주다, 주다/받다). Only the swap test is used per clause: focus
# particles stay a whole-sentence check (v1), because clause boundaries move freely in a paraphrase.
_CLAUSE_END = re.compile(r"[가-힣](?:고|며|면서|지만|는데|은데|ㄴ데|자|어서|아서|여서|해서|니까|으나|으며|"
                         r"거나|더니|다가|도록|려고|으려고|므로|으므로)$")
_COMITATIVE = re.compile(r"(?:하고|이고)$")


def _clauses(sentence: str) -> List[str]:
    out: List[str] = []
    current: List[str] = []
    for token in sentence.split():
        current.append(token)
        bare = token.rstrip(",")
        if token.endswith(",") or (_CLAUSE_END.search(bare) and not _COMITATIVE.search(bare) and len(current) > 1):
            out.append(" ".join(current).rstrip(","))
            current = []
    if current:
        out.append(" ".join(current))
    return [c for c in out if c.strip()]


def _clause_frames(sentence: str) -> Dict[Tuple[str, str], Optional[str]]:
    frames: Dict[Tuple[str, str], Optional[str]] = {}
    for clause in _clauses(sentence):
        pairs, _focus, pred = _v1._frame(clause)
        for pair in pairs:
            frames.setdefault(pair, _v1._converse_class(pred))
    return frames


def _clause_roles_swapped(source: str, candidate: str) -> bool:
    if len(source) > 2000 or len(candidate) > 2000:
        return False
    if len(_clauses(source)) < 2 and len(_clauses(candidate)) < 2:
        return False                                   # one clause each: the v1 sentence frame decided
    fa, fb = _clause_frames(source), _clause_frames(candidate)
    for (x, y), pred_a in fa.items():
        if (y, x) in fb and (x, y) not in fb:
            pred_b = fb[(y, x)]
            if not (pred_a and pred_b and _v1._CONVERSE_OPP.get(pred_a) == pred_b):
                return True
    return False


# --------------------------------------------------------------------------
# content words dropped (WP-10b)
# --------------------------------------------------------------------------
# A content word of the source sentence (noun, adverb, adjective or verb stem; numbers are the floor's) that
# has no trace in the candidate. Words are Hangul runs with quotations masked. Each word is read three ways
# and is present when any reading is found in the candidate (spaces removed), so inflection, particles and
# spacing never count as a drop:
#   whole    the first two syllables of the word as written (함께, 미리, 시립도서관 -> 시립)
#   stripped the same after the longest trailing particle or copula form (예정입니다 -> 예정, 책은 -> 책)
#   stem     when the second syllable is an ending syllable (먹지, 도와, 볶습니다, 몰라), the first syllable
#            compared by its initial consonant and vowel only, so 도와/돕, 들어/듣, 몰라/모르 match;
#            two-syllable keys also accept a second syllable with the same initial consonant and vowel
#            (어려워/어렵다, 가까운/가깝다)
# A one-syllable reading is found anywhere in the candidate, so one-syllable nouns (책, 집) and native verb
# stems are only reported when they vanish completely: the rule is built to miss rather than to block.
# Not content (never counted): light and auxiliary verbs (하다, 되다, 있다, 없다, 주다, 드리다, 보다, 같다 …),
# negation (안, 못: the polarity guard's), bound nouns (것, 수, 때 …), connectives and discourse markers (the
# flow and voice families'), demonstratives.
# Licensed drops: a word inside a span of a requestable diagnosis of the source sentence (any FIX/SUGGEST
# request rule: the redundancy list SSJ-A05 licenses the redundant member, CLR-APPROX2 the trailing 정도,
# SSJ-A01 왜냐하면, the translationese frames), except that the light-verb rules SSJ-LV1..LV4 license only
# the light verb itself (가능, 이루어지다, 진행, 실시), never the verbal noun. The licence is read from the
# source text, not from the plan, so it is the same for a request, an open-review nomination (type 26/27)
# and the document gate.
# Rule: content_dropped when the unlicensed dropped words outnumber the content words the candidate added
# (a substitution 함께 -> 같이 is a paraphrase, not a drop). detail = the count; keep = the dropped words
# (the retry prompt names them).
# FP risk: synonym substitution combined with a plain deletion elsewhere is reported with both words named;
# a compound split or merged across the two-syllable key (도서관 -> 시립 도서관 is fine, 세미나실 -> 회의실
# is a substitution).
_HANGUL_RUN = re.compile(r"[가-힣]+")
_PARTICLES = tuple(sorted((
    "에서는", "에서도", "에게서", "에게는", "에게도", "으로는", "으로도", "으로서", "으로써", "까지는", "까지도",
    "부터는", "부터도", "한테서", "이라도", "이라고", "이라는", "라고는", "에서", "에게", "한테", "께서", "으로",
    "까지", "부터", "마저", "조차", "처럼", "보다", "이나", "이랑", "라도", "라고", "라는", "에는", "에도", "와는",
    "과는", "로서", "로써", "로는", "은", "는", "이", "가", "을", "를", "에", "의", "도", "만", "로", "와", "과",
    "랑", "나", "께", "요"), key=len, reverse=True))
_COPULA = tuple(sorted((
    "이었습니다", "였습니다", "입니다", "입니까", "이에요", "이었다", "이었고", "이라서", "이지만", "이므로", "인데",
    "예요", "이다", "이고", "이며", "이라", "이면", "이죠", "이야", "였다", "였고", "인", "일", "임"),
    key=len, reverse=True))
_ENDING_SYLLABLES = set("고며면니는은을다어아여해워와라러려쳐져켜혀겨서도요게지기음자세시셨실신습십겠었았였했웠왔렀랐"
                        "렸쳤졌켰혔겼던든데냐네나죠군구대래랬잖거길까봐줘돼야으므되듯셔심오")
# ㅂ-irregular adnominal endings (쉬운, 어려운, 가까울): verb-like only against a ㅂ-final stem in the candidate
# (쉽지, 어렵다), so 서울, 행운, 겨울 stay nouns.
_BIEUP_ENDINGS = frozenset("운울웁")
# First syllables of light and auxiliary verbs (하다, 되다, 있다, 없다, 않다, 이다, 주다, 드리다, 보다, 같다,
# 싶다, 두다, 놓다, 버리다, 지다, 말다, 가다, 오다, 계시다) when the word is verb-like, and the two-syllable
# honorific/humble forms of them whose second syllable is not an ending (드립니다, 주십시오, 계십니다).
_LIGHT_FIRST = set("하한할함합해했되된될됨됩돼됐있없않안아못이인일임입주준줄줍줘줬드보본볼봅봐봤같싶두둔둘놓버지진질집져졌"
                   "마가간갈갑와왔오온올옵계")
_LIGHT_PREFIX = frozenset("드리 드립 드려 드렸 드릴 드린 드림 주시 주십 주셔 주셨 하시 하십 하셔 하셨 되시 되십 되셔 되셨 보시 보십 "
                          "보셔 보셨 계시 계십 계셔 계셨 계신 계실".split())
_FUNCTION_WORDS = frozenset("""
그리고 그러나 하지만 그래서 따라서 그러므로 그러니까 그런데 그러면 그럼 또한 또는 혹은 및 즉 한편 반면 게다가 더구나
그럼에도 다만 물론 결국 이처럼 이렇게 그렇게 저렇게 이와 이에 그래도 아무튼 어쨌든 왜냐하면 왜냐면 예를 들어 들면
이 그 저 이런 그런 저런 이러한 그러한 저러한 이것 그것 저것 이거 그거 저거 여기 거기 저기 이곳 그곳 이번에도
것 거 수 때 등 중 데 바 뿐 줄 듯 만큼 대로 채 적 터 리 측 점 경우 정도 가량 쯤 내외 안팎
전 후 뒤 앞 다음 이전 이후 직전 직후 동안 사이 무렵 또 없이 아닌 아니라 대신
때문 의해 의하여 의한 대한 대해 대하여 관한 관해 관하여 통해 통하여 통한 위해 위하여 위한 따라 따른 인해 인하여 인한
비해 비하여 향해 걸쳐 불구하고 어쩔 그뿐 이뿐 아무런 아무 말고 말라 말자 말아 말았 말아야 말지
하나 둘 셋 넷 다섯 여섯 일곱 여덟 아홉 열 스물 서른 마흔 쉰 예순 일흔 여든 아흔 백 천 만 억 조 한 두 세 네 첫
사실 뭐 진짜 정말 참 그냥 막 좀 아 어 네 예 응 음 저기요
""".split())


_NEG_PREFIX = set("불비무미")
_HA_SYLLABLES = frozenset("하한할함합해했")
_KNOW_FIRST = frozenset("알안몰")
_VARIANTS = (("새로", ("새",)), ("먹", ("드시", "드셨", "드세", "드십", "드실", "드신", "잡수", "잡숴")), ("자", ("주무",)),
               ("말하", ("말씀",)), ("말해", ("말씀",)), ("말했", ("말씀",)), ("묻", ("여쭈", "여쭙", "여쭤")),
               ("물어", ("여쭈", "여쭙", "여쭤")), ("데리", ("모시", "모셔")), ("데려", ("모시", "모셔")),
               ("아프", ("편찮",)), ("아파", ("편찮",)), ("나이", ("연세",)), ("이름", ("성함",)), ("집", ("댁",)),
               ("밥", ("진지",)), ("생일", ("생신",)), ("드시", ("먹",)), ("말씀", ("말",)), ("성함", ("이름",)),
               ("연세", ("나이",)), ("댁", ("집",)))
# Modality and polarity carriers are the modality guard's business (불가능 -> 가능하지 않다, 필요 없다 ->
# 않아도 된다), bounds the lexical guard's (과반수 이상 -> 과반수).
_GUARDED_KEYS = frozenset("필요 가능 불가 금지 허용 허락 의무 필수 권장 확실 분명 반드 틀림 아마 이상 이하 미만 초과 이내".split())


def _cv(syllable: str) -> int:
    """Initial consonant + vowel of a Hangul syllable (the final consonant dropped); -1 otherwise."""
    code = ord(syllable) - 0xAC00
    return code // 28 if 0 <= code < 11172 else -1


_PARTICLE_SET = frozenset(_PARTICLES + _COPULA)
_NO_STRIP = frozenset(("좀처럼", "함께", "바로", "그대로", "제대로", "스스로", "서로", "새로", "따로", "홀로", "별로", "주로",
                       "대체로", "실제로", "정말로", "참으로", "진정으로", "처음으로", "마지막으로", "억지로"))


def _strip(word: str) -> str:
    for suffix in _COPULA:
        # a one-syllable copula form (인, 일, 임) only after two syllables: 확인, 직원 are words of their own
        if word.endswith(suffix) and len(word) - len(suffix) >= (2 if len(suffix) == 1 else 1):
            return word[:-len(suffix)]
    for suffix in _PARTICLES:
        if word.endswith(suffix) and len(word) > len(suffix):
            return word[:-len(suffix)]
    return word


class _Index:
    """Presence tests against one candidate text (spaces removed), linear to build."""

    def __init__(self, text: str):
        self.flat = "".join(_HANGUL_RUN.findall(T.mask_quotes(text)))
        self.cvs = {_cv(ch) for ch in self.flat}
        self.codes = {ord(ch) for ch in self.flat}
        self.negated = bool(_ANY_NEG.search(text))
        self.has_ha = any(ch in _HA_SYLLABLES for ch in self.flat)
        self.next_initial: Dict[str, set] = {}
        self.next_syllable: Dict[str, set] = {}
        for a, b in zip(self.flat, self.flat[1:]):
            self.next_initial.setdefault(a, set()).add(_cv(b) // 21)
            if b in _HA_SYLLABLES:
                self.next_syllable.setdefault(a, set()).add(b)

    def has(self, key: str) -> bool:
        if len(key) == 1:
            return key in self.flat
        if key[:2] in self.flat:
            return True
        # same first syllable, second syllable with the same initial consonant: 불리워 / 불렸, 어려워 / 어렵다
        return _cv(key[1]) // 21 in self.next_initial.get(key[0], ())

    def has_stem(self, syllable: str) -> bool:
        return _cv(syllable) in self.cvs

    def has_bieup(self, syllable: str) -> bool:
        return _cv(syllable) * 28 + 17 + 0xAC00 in self.codes

    def short_verb(self, root: str) -> bool:
        return bool(self.next_syllable.get(root, set()) & _HA_SYLLABLES)


def _readings(word: str, *, source_side: bool = True) -> Optional[Tuple[str, str, bool]]:
    """(two-syllable key as written, stripped core, verb-like) of one Hangul run, or None when it is not a
    content word. Verb-likeness is read on the word as written (its second syllable is an ending), so 함께
    is an adverb and not 하- + ㅁ + 께. Light and auxiliary verbs are skipped on the source side only: on
    the candidate side a new 하다/되다 form counts as an added word, which can only cancel a drop."""
    if word in _FUNCTION_WORDS or word in _PARTICLE_SET:
        return None
    core = word if word in _NO_STRIP else _strip(word)
    if core in _FUNCTION_WORDS or core[:2] in _GUARDED_KEYS:
        return None
    verb_like = len(word) == 1 or word[1] in _ENDING_SYLLABLES
    if source_side and verb_like and (word[0] in _KNOW_FIRST or word.startswith(("모르", "모른"))):
        return None                           # 알다/모르다: the v1 KNOW axis compares them
    if source_side and word[0] in _LIGHT_FIRST and (verb_like or word[:2] in _LIGHT_PREFIX):
        return None
    return word[:2], core, verb_like


def _present(readings: Tuple[str, str, bool], index: _Index, word: str) -> bool:
    """Lenient presence of a source word in the candidate (any reading)."""
    whole, core, verb_like = readings
    if index.has(whole) or index.has(core[:2]):
        return True
    if verb_like and index.has_stem(word[0]):
        return True
    if len(word) >= 2 and word[1] in _BIEUP_ENDINGS and index.has_bieup(word[0]):
        return True
    # noun + 하다 split by the rewrite: 말하지 -> 말을 … 하지, 공부하고 -> 공부를 하고
    split = next((i for i in range(1, min(len(word), 4)) if word[i] in _HA_SYLLABLES), 0)
    if split and word[:split] in index.flat and index.has_ha:
        return True
    # a negative prefix spelled out as a negation: 비공개로 -> 공개하지 않고, 무관심 -> 관심이 없다
    if len(core) >= 3 and core[0] in _NEG_PREFIX and index.negated and index.has(core[1:3]):
        return True
    # a Sino-Korean verbal noun shortened to its second root + 하다: 선택할 -> 택할, 대답 -> 답하다
    if len(core) >= 2 and index.short_verb(core[1]):
        return True
    # honorific suppletion (먹었다 -> 드셨다, 이름 -> 성함) and adnominal variants (새로운 -> 새): the voice
    # family judges the honorific
    for stem, forms in _VARIANTS:
        if core.startswith(stem) and any(form in index.flat for form in forms):
            return True
    return False


def _present_strict(readings: Tuple[str, str, bool], index: _Index) -> bool:
    """Strict presence of a candidate word in the source (the key as written or stripped), used to count
    added words: a substitution should count as added whenever it is not literally there."""
    whole, core, _verb_like = readings
    return whole in index.flat or core[:2] in index.flat


def _licensed_spans(source: str) -> List[Tuple[int, int, Optional[str]]]:
    """(start, end, licensed key or None = any word) of the requestable diagnoses of `source`."""
    from . import diagnose as D               # late: diagnose -> protect/text imports are heavier
    spans: List[Tuple[int, int, Optional[str]]] = []
    for rule in D.RULES.values():
        if rule.scope != "sentence" or rule.action != "request" or rule.tier == "LEAVE":
            continue
        try:
            hits = rule.detect(source)
        except Exception:                     # a detector that needs more context than one sentence
            continue
        for start, end, _fix in hits:
            spans.append((start, end, "LV" if rule.id.startswith("SSJ-LV") else None))
    return spans


_LIGHT_VERB_KEYS = ("가능", "이루", "이뤄", "진행", "실시", "시행")
_OBJECT_OR_SUBJECT = re.compile(r"[가-힣](?:을|를|이|가)\s+$")
_ROLE_FRAME = re.compile(r"\s*(?:을|를)?\s*(?:하|한|할|합|해|했|담당|수행)")


def _frame_word(text: str, m: "re.Match", core: str) -> bool:
    """A light verb after an object or subject (영업을 진행하고 있습니다 -> 영업합니다, 요청이 이루어질 -> 요청될)
    or the 역할/기능 of a "-는 역할을 하다" frame (제공하는 역할을 하고 있습니다 -> 줍니다): the frame word itself
    carries no content of its own, whatever verbal noun precedes it (the SSJ-LV lists are closed for
    precision as requests, not as licences)."""
    if core.startswith(_LIGHT_VERB_KEYS[1:]) and _OBJECT_OR_SUBJECT.search(text, max(0, m.start() - 12), m.start()):
        return True
    return core in ("역할", "기능") and _ROLE_FRAME.match(text, m.start() + 2) is not None


def _blank_idioms(text: str) -> str:
    """Source side: idioms that contain a negation word (다름 아닌, 쉴 새 없이, 못지않게: v1 _IDIOMS) are one
    unit for the polarity guard, not words of their own; each is blanked to the end of its last eojeol,
    keeping the length. The candidate keeps them, so an idiom it introduces counts as an added word."""
    pieces: List[str] = []
    last = 0
    for m in _v1._IDIOMS.finditer(text):
        if m.start() < last:
            continue
        end = m.end()
        while end < len(text) and "가" <= text[end] <= "힣":
            end += 1
        pieces.append(text[last:m.start()])
        pieces.append(" " * (end - m.start()))
        last = end
    pieces.append(text[last:])
    return "".join(pieces)


@dataclass
class Drops:
    """Content-word comparison of one pair: dropped words with their source offsets, the added words, and
    the dropped place or weekday words whose substitute (same head, other prefix) the candidate added."""
    dropped: List[Tuple[int, int, str]]
    added: List[str]
    substituted: List[str]

    @property
    def words(self) -> List[str]:
        out: List[str] = []
        for _start, _end, shown in self.dropped:
            if shown not in out:
                out.append(shown)
        return out


# Heads of place and date names: a word made of another prefix + the same head (서울시청 -> 부산시청, 토요일 ->
# 일요일, 강남역 -> 역삼역) is a substitution of a name, never a paraphrase, so the added word does not cancel the
# dropped one. One-syllable heads need a prefix of two syllables or more (지역, 활동, 온도 are words, not names).
_ENTITY_HEADS = tuple(sorted(("시청", "구청", "군청", "도청", "요일", "공항", "대학교", "대학", "병원", "도서관", "경찰서",
                              "소방서", "우체국", "은행", "학교", "공원", "시장", "터미널", "센터", "회관", "아파트", "호텔",
                              "박물관", "미술관", "체육관", "경기장", "해수욕장", "시", "구", "군", "도", "동", "읍",
                              "역"), key=len, reverse=True))


def _entity(core: str) -> Optional[Tuple[str, str]]:
    """(prefix, head) of a place or date name; a prefix ending in a verbal syllable (위반하면, 원하시) is an
    inflected verb, not a name."""
    for head in _ENTITY_HEADS:
        if core.endswith(head) and len(core) - len(head) >= (2 if len(head) == 1 else 1):
            prefix = core[:-len(head)]
            if prefix[-1] in _ENDING_SYLLABLES or prefix[-1] in _HA_SYLLABLES or prefix[-1] in "되된될됩":
                return None
            return prefix, head
    return None


def drops(source: str, candidate: str) -> Drops:
    """Unlicensed content words of `source` with no trace in `candidate` (once each, in source order, as
    their stripped form) and the content words the candidate added (module notes above)."""
    if len(source) > 4000 or len(candidate) > 4000:
        return Drops([], [], [])              # a run-on "sentence": the floor and the other families decide
    masked_src = _blank_idioms(T.mask_quotes(source))
    cand_index, src_index = _Index(candidate), _Index(source)
    licences = None
    dropped: List[Tuple[int, int, str]] = []
    for m in _HANGUL_RUN.finditer(masked_src):
        word = m.group(0)
        readings = _readings(word)
        if readings is None or _present(readings, cand_index, word):
            continue
        if licences is None:
            licences = _licensed_spans(source)
        core = _strip(word)
        if any(a < m.end() and m.start() < b and (kind is None or core.startswith(_LIGHT_VERB_KEYS))
               for a, b, kind in licences):
            continue
        if _frame_word(masked_src, m, core):
            continue
        dropped.append((m.start(), m.end(), core if len(core) >= 2 else word))
    if not dropped:
        return Drops([], [], [])
    added: List[str] = []
    for m in _HANGUL_RUN.finditer(T.mask_quotes(candidate)):
        readings = _readings(m.group(0), source_side=False)
        if readings is not None and not _present_strict(readings, src_index) and readings[1] not in added:
            added.append(readings[1])
    substituted: List[str] = []
    for _start, _end, shown in dropped:
        name = _entity(shown)
        if name is None:
            continue
        for other in added:
            match = _entity(other)
            if match is not None and match[1] == name[1] and match[0] != name[0]:
                substituted.append(shown)
                added.remove(other)
                break
    return Drops(dropped, added, substituted)


def dropped_words(source: str, candidate: str) -> Tuple[List[str], int]:
    """(dropped words, count of added words) of drops(), the inputs of the content_dropped rule."""
    found = drops(source, candidate)
    return found.words, len(found.added)


def _content_dropped(found: Drops) -> Optional[Tuple[str, str]]:
    words = found.words
    if words and (len(words) > len(found.added) or found.substituted):
        return str(len(words)), ", ".join(words)
    return None


# --------------------------------------------------------------------------
# conditions (WP-10b, lead item D)
# --------------------------------------------------------------------------
# A conditional clause: an eojeol ending in -(으)면 (회원이면, 늦으면, 원하시면), -다면/-라면, -거든, the
# necessity condition -어야 not followed by 하다/되다 (직접 내야 접수됩니다), or 경우, 만약, 만일.
# Not conditions here: nouns in 면 (반면, 측면, 화면 …), 예를 들면, and prohibition/obligation -면 안 되다
# (찍으면 안 된다, 줄이지 않으면 안 됩니다), which the modality guard compares. The clause is the marker eojeol
# and up to three eojeols before it, back to a comma.
# Rule: condition_dropped when the candidate has fewer conditional markers than the source and a content
# word of a source conditional clause is dropped (drops()), so "회원이면 무료로 이용할 수 있어요" -> "무료로
# 이용할 수 있어요" is caught while a condition said another way ("회원은 무료로 …", "회원인 경우 …") is not.
# detail = "COND:n->m"; keep = the dropped clause words.
_NOUN_MYEON = frozenset("반면 측면 전면 화면 장면 정면 표면 내면 이면 단면 지면 국면 방면 대면 수면 체면 외면 일면 후면 "
                        "앞면 뒷면 양면 라면 냉면 들면".split())
_COND = re.compile(r"([가-힣]+)면(?![가-힣])(?!\s*안\s*(?:되|돼|됩|된))|(?<![가-힣])경우(?=[에는도]|[\s,.]|$)"
                   r"|(?<![가-힣])만약(?![가-힣])|(?<![가-힣])만일(?![가-힣])|[가-힣]거든(?=[\s,])"
                   r"|(?P<ya>[가-힣])야(?=[\s,])(?!\s*(?:하|한|할|합|해|했|된|됩|돼|되))")
_YA_VOWELS = {0, 1, 4, 6, 9, 10, 14}          # ㅏ ㅐ ㅓ ㅕ ㅘ ㅙ ㅝ: the -어 of -어야 (내야, 와야, 해야, 봐야)


def _conditions(text: str) -> List[Tuple[int, int]]:
    """(clause start, marker end) of every conditional marker of one sentence."""
    out: List[Tuple[int, int]] = []
    for m in _COND.finditer(text):
        word = m.group(0)
        if m.group(1) is not None:
            if word in _NOUN_MYEON or len(word) < 2:
                continue
        if m.group("ya") is not None:
            ch = m.group("ya")
            if _jong(ch) not in (0, 20) or (_jong(ch) == 0 and _jung(ch) not in _YA_VOWELS):
                continue                      # 친구야 (vocative), 학생이야 is not -어야
        start = m.start()
        for _ in range(3):
            prev = text.rfind(" ", 0, max(0, start - 1))
            piece = text[prev + 1:start]
            if "," in piece or prev < 0:
                start = prev + 1 + (piece.rfind(",") + 1 if "," in piece else 0)
                break
            start = prev + 1
        out.append((start, m.end()))
    return out


def _condition_dropped(source: str, candidate: str, found: Drops) -> Optional[Tuple[str, str]]:
    if not found.dropped:
        return None
    src_conds = _conditions(source)
    n, k = len(src_conds), len(_conditions(candidate))
    if n <= k:
        return None
    words = [shown for a, b, shown in found.dropped if any(c <= a and b <= e for c, e in src_conds)]
    if not words:
        return None
    return f"COND:{n}->{k}", ", ".join(dict.fromkeys(words))


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


# WP-10 integration fix: the deterministic FIX repairs of the norm layer must be invisible to this family
# (verify(x, base(x)) == [], DESIGN 3.9), but the v1 guards read the bound noun 수 only when it is spaced
# (할수 없다 -> 할 수 없다 looked like a new CAN_NEG and a lost negation) and read 안 되요 -> 안 돼요 as a
# polarity change. Both sides are therefore compared after norms.fix_text, the very function repair step 1
# applies (N01, N02, N04, CTA-SP1/SP2; outside protected spans): a difference made only of those fixes
# disappears, and every other difference is still seen. Only sentences that differ pay for it.
# WP-10b (lead item B): attached 안 before a form of 되다 (안되요, 안돼요, 안됩니다) is compared spaced, so the
# spacing fix "그건 안되요." -> "그건 안 돼요." is neutral. This is a comparison step only: no deterministic
# 안되 -> 안 돼 fix exists, because 안되다 (참 안됐다, pity) is a word of its own; both sides are spaced alike, so
# 안됐다 -> 안됐다 stays identical and a real change is still seen.
_AN_DOE = re.compile(r"(?<![가-힣])안(?=[되돼됐됩될된])")


def _normalised(text: str) -> str:
    from . import norms                     # late: norms -> diagnose -> protect imports are heavier
    fixed, _applied = norms.fix_text(text)
    return _AN_DOE.sub("안 ", fixed) if "안" in fixed else fixed


# WP-10 integration fix, same reason: SSJ-A04 (FIX/request) asks the writer to turn a double passive into the
# single passive (보고되어집니다 -> 보고됩니다), and the v1 role guard reads 되어 as passive but not 됩니다, so the
# rule's own repair was a participant_role_changed. Both sides are compared with the closed A04 list
# (data/double_passive.json "fix") collapsed to the single passive: stem + 지/진/질/집 -> base verb (+ ㄴ/ㄹ/ㅂ),
# stem + 져/졌 -> stem (+ ㅆ). Only those six stems are touched, on both sides alike.
_SINGLE = {"되어": "되", "보여": "보이", "쓰여": "쓰이", "나뉘어": "나뉘", "읽혀": "읽히", "불려": "불리"}


def _with_final(syllable: str, jong: int) -> str:
    code = ord(syllable) - 0xAC00
    return chr(ord(syllable) + jong) if 0 <= code < 11172 and code % 28 == 0 else syllable


def _double_passive_re() -> "re.Pattern":
    global _DOUBLE_RE
    if _DOUBLE_RE is None:
        import json
        from pathlib import Path
        data = json.loads((Path(__file__).resolve().parent / "data" / "double_passive.json").read_text(encoding="utf-8"))
        stems = [stem for stem in data["fix"] if stem in _SINGLE]
        _DOUBLE_RE = re.compile("(" + "|".join(sorted(stems, key=len, reverse=True)) + ")(지|진|질|집|져|졌)")
    return _DOUBLE_RE


_DOUBLE_RE: Optional["re.Pattern"] = None


def _single_passive(text: str) -> str:
    if "지" not in text and "진" not in text and "질" not in text and "집" not in text and "져" not in text \
            and "졌" not in text:
        return text

    def collapse(m: "re.Match") -> str:
        stem, ending = m.group(1), m.group(2)
        base = _SINGLE[stem]
        if ending == "지":
            return base
        if ending in ("진", "질", "집"):
            return base[:-1] + _with_final(base[-1], {"진": 4, "질": 8, "집": 17}[ending])
        return stem if ending == "져" else stem[:-1] + _with_final(stem[-1], 20)
    return _double_passive_re().sub(collapse, text)


SOFT_CODES = ("content_dropped",)


def findings(source: str, candidate: str) -> List[Tuple[str, str, Optional[str]]]:
    """(code, detail, keep) for one pair of texts, without the identical-text shortcut of compare()."""
    if source != candidate:
        source, candidate = _single_passive(_normalised(source)), _single_passive(_normalised(candidate))
    found: List[Tuple[str, str, Optional[str]]] = [(code, detail, None) for code, detail in _v1_codes(source, candidate)]
    seen = {code for code, _detail, _keep in found}
    if "participant_role_changed" not in seen and _clause_roles_swapped(source, candidate):
        found.append(("participant_role_changed", "clause_roles", None))
    detail = _aspect_changed(aspect(source), aspect(candidate), source, candidate)
    if detail:
        found.append(("aspect_changed", detail, None))
    detail = _partial_changed(source, candidate)
    if detail:
        found.append(("partial_negation_changed", detail, None))
    if not any(code == "lexical_polarity_changed" and detail == "order" for code, detail, _keep in found):
        detail = _temporal_changed(source, candidate)
        if detail:
            found.append(("temporal_order_changed", detail, None))
    if source != candidate:
        words = drops(source, candidate)
        condition = _condition_dropped(source, candidate, words)
        if condition:
            found.append(("condition_dropped", condition[0], condition[1]))
        dropped = _content_dropped(words)
        if dropped:
            found.append(("content_dropped", dropped[0], dropped[1]))
    return found


def codes(source: str, candidate: str) -> List[Tuple[str, str]]:
    """(code, detail) for one pair of texts, without the identical-text shortcut of compare()."""
    return [(code, detail) for code, detail, _keep in findings(source, candidate)]


def compare(source: Any, candidate: Any, *, sentence: Optional[str] = None) -> List[Violation]:
    """Meaning violations of one aligned pair. `source` and `candidate` are a str, a types.Unit or
    a sequence of them (the two sides of a 1:2 or 2:1 Pair). `sentence` defaults to the first
    source unit's id. Identical texts return [] without running the guards. content_dropped is
    severity soft and carries the dropped words in `keep` (never in `detail`)."""
    before, after = _text(source).strip(), _text(candidate).strip()
    if before == after or not before or not after:
        return []
    sid = sentence if sentence is not None else _first_id(source)
    return [Violation(code=code, family=FAMILY, severity="soft" if code in SOFT_CODES else "hard", sentence=sid,
                      detail=detail, keep=keep)
            for code, detail, keep in findings(before, after)]


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
                                   detail=v.detail, keep=v.keep) for v in hits)
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
