"""Diagnostics of Super Sejong Engine v2: the complete rule set of DESIGN.md 3.3.

Every rule has an authority tier and an action:
  FIX      a human-norm error; the engine applies it (deterministic) or asks the writer (request)
  SUGGEST  an optional request the writer may decline; never a failure if it remains
  LEAVE    never requested (action report); counted in plan stats and usable as a "do not introduce" counter

A rule's tier depends on the genre: a rule listed for some genres only is LEAVE/report in every other
genre, so `general` (direct text) keeps only the rules valid everywhere. Blog keeps every LLM tell as
LEAVE (BOILERPLATE 1.22 and IMPORTANCE 1.83 per 10k are the owner's voice, T3 §3-4). SSJ-N04c (할께
family) is LEAVE unless SUPER_SEJONG_FIX_COLLOQUIAL=1 makes it FIX/deterministic (OD 2).

Detectors run on the sentence text with freeze spans masked (protect.protected_spans): a number, money,
date or phone span becomes "0"s except its Hangul counter, every other freeze span becomes text.MASK_CHAR ("ㅇ", not a Hangul
syllable), newlines stay. So nothing inside a quotation, heading, URL, code or Latin name can fire,
and 약 30명 정도 still looks like 약 0000 정도 to SSJ-A05/CLR-APPROX2. A deterministic finding that
touches any protected span (freeze or keep-token) is dropped, so a fix never edits protected text.

Deterministic findings carry the smallest edit: [start, end) is the text to replace and `fix` the
replacement (never an empty `before`, as the plan schema requires); norms.apply_fixes applies them.
Request findings span the flagged phrase; `fix` is the expected form when the rule knows it (SSJ-N03).

CLR-LONG and CLR-APPROX2 come from clarity.py (WP-7, DESIGN 5.1 long_review/approx2); while that module
is absent they do not fire. Every detector is a regex pass over one sentence or a linear pass over one
paragraph; nothing is quadratic in the text length.

Precision figures quoted in comments are the T3/T4/T6 hand-checks by one LLM annotator; no native
reader has rated any rule.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import re
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import protect as P
from . import text as T
from .types import Document, Finding, Options, Span, Unit

DATA_DIR = Path(__file__).resolve().parent / "data"
ALL = "all"
NUMERIC_KINDS = frozenset(("number", "money", "date", "phone"))
# Genres of 3.3. general = direct text without a declared genre: only rules valid in every genre.
ESSAY_REPORT = ("essay", "report")
TRANSLATIONESE = ("essay", "report", "document")

Hit = Tuple[int, int, Optional[str]]        # (start, end, fix) relative to the scanned text


def coda(ch: str) -> int:
    """Final-consonant index of a Hangul syllable (0 none, 4 ㄴ, 8 ㄹ), -1 for anything else."""
    o = ord(ch) - 0xAC00 if ch else -1
    return o % 28 if 0 <= o < 11172 else -1


RIEUL_CLASS = "".join(chr(0xAC00 + i) for i in range(11172) if i % 28 == 8)


# --------------------------------------------------------------------------
# data files
# --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _data(name: str) -> dict:
    with open(DATA_DIR / name, encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=None)
def misspellings(cls: str) -> Tuple[Tuple[str, "re.Pattern", str], ...]:
    """(entry id, compiled pattern, replace template) for every entry of class `cls` ("error" | "colloquial")."""
    out = []
    for entry in _data("misspellings.json")["entries"]:
        if entry["class"] == cls:
            out.append((entry["id"], re.compile(entry["pattern"].replace("{RIEUL}", RIEUL_CLASS)), entry["replace"]))
    return tuple(out)


@lru_cache(maxsize=None)
def _redundancy() -> "re.Pattern":
    entries = _data("redundancy.json")["entries"]
    return re.compile("|".join(f"(?:{e['pattern']})" for e in entries))


@lru_cache(maxsize=None)
def _double_passive() -> Tuple["re.Pattern", "re.Pattern"]:
    data = _data("double_passive.json")
    endings = "|".join(data["endings"])
    fix = re.compile("(?:" + "|".join(data["fix"]) + ")(?:" + endings + ")")
    suggest = re.compile("(?:" + "|".join(data["suggest"]) + ")(?:" + endings + ")")
    return fix, suggest


@lru_cache(maxsize=None)
def guides() -> Dict[str, str]:
    return {key: value for key, value in _data("guides.ko.json").items() if not key.startswith("_")}


def guide(rule_id: str) -> str:
    """The one-line Korean guide of a rule (data/guides.ko.json)."""
    return guides()[rule_id]


# --------------------------------------------------------------------------
# masking
# --------------------------------------------------------------------------
def masked_text(text: str, spans: Sequence[Span]) -> str:
    """`text` with every freeze span blanked: in number/money/date/phone spans every character but a Hangul
    syllable (the counter: 명, 살, 등) becomes "0"; other spans become MASK_CHAR; newlines are kept.
    Same length as `text`, so offsets carry over."""
    out: List[str] = []
    last = 0
    for span in spans:
        if span.policy != P.FREEZE or span.end <= last:
            continue
        start = max(span.start, last)
        out.append(text[last:start])
        if span.kind in NUMERIC_KINDS:      # keep the Hangul counter: 16살이였다 -> 00살이였다
            out.append(re.sub(r"[^\n가-힣]", "0", text[start:span.end]))
        else:
            out.append(re.sub(r"[^\n]", T.MASK_CHAR, text[start:span.end]))
        last = span.end
    out.append(text[last:])
    return "".join(out)


_LEAD = re.compile("[\\s\"'“‘(\\[「『《〈*>#" + T.MASK_CHAR + "-]*")


def _lead_len(s: str) -> int:
    """Length of the sentence-initial filler (spaces, quotes, Markdown markers, masked spans)."""
    return _LEAD.match(s).end()


def _full(s: str) -> bool:
    """A complete sentence: ends with a terminator or a closing quote (T3 _full)."""
    s = s.rstrip()
    return bool(s) and s[-1] in ".!?。\"”'’"


# --------------------------------------------------------------------------
# rule table
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Rule:
    id: str
    tier: str                                   # tier inside `genres`; LEAVE/report elsewhere
    action: str                                 # deterministic | request | report
    genres: object                              # ALL or a tuple of genres
    detect: Callable[..., Iterable[Hit]]        # sentence scope: detect(s) ; paragraph scope: detect(ctx)
    guide_id: str
    success: Optional[Callable[[str], bool]] = None   # rule-specific "fixed" check on a rewritten sentence
    scope: str = "sentence"                     # sentence | document
    allow_split: bool = False


def _rx_hits(pattern: "re.Pattern", s: str, guard=None, lead: int = 0, group: int = 0) -> List[Hit]:
    out: List[Hit] = []
    for m in pattern.finditer(s):
        if guard is not None and not guard(s, m):
            continue
        start, end = m.span(group)
        if lead:
            limit = max(0, start - lead)
            while start > limit and "가" <= s[start - 1] <= "힣":
                start -= 1
        out.append((start, end, None))
    return out


def _rx(pattern: str, flags: int = 0, guard=None, lead: int = 0, group: int = 0):
    compiled = re.compile(pattern, flags)
    return lambda s: _rx_hits(compiled, s, guard, lead, group)


# ---- SSJ-N01 bound-noun spacing (한글 맞춤법 제42항), 59/60 [T3] ----------------------------
_N01_SU = re.compile(r"([가-힣])수(\s?)(있|없|밖에)")
_N01_GEOT = re.compile(r"([가-힣])것")
_N01_TTAE = re.compile(r"([가-힣])때(?!기|문)")
# 할 수 밖에 없다 -> 할 수밖에 없다: the particle 밖에 attaches to the bound noun (제41항).
_N01_BAKKE = re.compile(r"(?<=[" + RIEUL_CLASS + r"] )수( )밖에(?=\s+(?:없|안\s|못))")
# Nouns that end in ㄹ+수 / ㄴ,ㄹ+것 / ㄹ+때 and are not bound-noun constructions:
# 실수 없이, 별수 없다, 술수, 홀수, 필수 ; 날것, 들것, 탈것, 별것, 군것(질), 헌것 ; 물때, 볼때기.
_N01_SU_NOUN = frozenset("실술홀필별")
_N01_GEOT_NOUN = frozenset("날들탈별생산군헌")
_N01_TTAE_NOUN = frozenset("물볼")


def _n01(s: str) -> List[Hit]:
    out: List[Hit] = []
    for m in _N01_SU.finditer(s):
        prev = m.group(1)
        # 실수/별수/홀수/필수 only as a word of their own (하실수 있다 is 하실 수 있다); 술수 anywhere (권모술수)
        noun = prev == "술" or (prev in _N01_SU_NOUN and (m.start() == 0 or not "가" <= s[m.start() - 1] <= "힣"))
        if coda(prev) == 8 and not noun:
            su = m.start() + 1
            if m.group(3) == "밖에":
                # 할수밖에 / 할수 밖에 -> 할 수밖에 (밖에 is a particle and attaches to 수)
                out.append((su, m.start(3), " 수"))
            else:
                # 할수있다 -> 할 수 있다 ; 할수 있다 -> 할 수 있다
                out.append((su, su + 1, " 수" if m.group(2) else " 수 "))
    for m in _N01_GEOT.finditer(s):
        prev = m.group(1)
        if coda(prev) in (4, 8) and prev not in _N01_GEOT_NOUN:
            out.append((m.start() + 1, m.end(), " 것"))
    for m in _N01_TTAE.finditer(s):
        prev = m.group(1)
        if coda(prev) == 8 and prev not in _N01_TTAE_NOUN:
            out.append((m.start() + 1, m.end(), " 때"))
    for m in _N01_BAKKE.finditer(s):
        out.append((m.start(), m.end(1), "수"))
    return out


# ---- SSJ-N02 -지 않 spacing (제47항; 머지않다/못지않다/마지않다 are headwords), 20/20 [T3] -------
_N02 = re.compile(r"(?<![마머못])지(않)(?=[가-힣])")


def _n02(s: str) -> List[Hit]:
    return [(m.start(1), m.end(1), " 않") for m in _N02.finditer(s)]


# ---- SSJ-N03 율/률 (제11항 붙임 1), 26/27 [T3] -------------------------------------------
_SURNAMES = frozenset("김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하곽성차주우구민류나진지엄채원천"
                      "방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예봉경")
_N03 = re.compile(r"([가-힣])(율|률)")


def _n03(s: str) -> List[Hit]:
    out: List[Hit] = []
    for m in _N03.finditer(s):
        prev, suffix = m.group(1), m.group(2)
        want = "율" if coda(prev) in (0, 4) else "률"
        if suffix == want:
            continue
        if prev in _SURNAMES and (m.start() == 0 or not "가" <= s[m.start() - 1] <= "힣"):
            continue                                        # a two-syllable name: 김율
        out.append((m.start(), m.end(), prev + want))
    return out


# ---- SSJ-N04 / N04c closed misspelling list (data/misspellings.json) -------------------------
def _trim(before: str, after: str) -> Tuple[int, int, str]:
    """Shrink a replacement to its changed core, keeping at least one character of `before`."""
    p = 0
    while p < len(before) and p < len(after) and before[p] == after[p]:
        p += 1
    q = 0
    while q < len(before) - p and q < len(after) - p and before[-1 - q] == after[-1 - q]:
        q += 1
    if p + q >= len(before):                     # pure insertion: keep one character on the right
        q = max(0, len(before) - p - 1)
        if p >= len(before):
            p = len(before) - 1
    return p, len(before) - q, after[p:len(after) - q]


def _lexicon_hits(s: str, cls: str) -> List[Hit]:
    out: List[Hit] = []
    for _id, pattern, replace in misspellings(cls):
        for m in pattern.finditer(s):
            before = m.group(0)
            after = m.expand(replace)
            if before == after or not before:
                continue
            a, b, new = _trim(before, after)
            out.append((m.start() + a, m.start() + b, new))
    return out


# ---- SSJ-N05 이였/이예요 after a consonant-final noun (regex 24/30 [T3]) ------------------------
_N05 = re.compile(r"([가-힣])이(였|예요)")
# Nouns that end in 이 themselves (외톨이였던 is correct) and common -이 suffix families.
_I_NOUNS = ("외톨이", "놀이", "토박이", "고양이", "원숭이", "어린이", "늙은이", "젊은이", "지은이", "글쓴이", "옮긴이",
            "엮은이", "먹이", "길잡이", "떡볶이", "구이", "멍멍이", "꼬맹이", "바둑이", "똘똘이", "막둥이", "개구쟁이",
            "부엉이", "지렁이", "굼벵이", "달팽이", "호랑이", "반딧불이", "오뚝이", "높이", "깊이", "넓이", "길이",
            "하루살이", "시집살이", "셋방살이", "타향살이")
_I_SUFFIX = re.compile(r"(?:쟁|뱅|둥|박|잡|받|돌|순|퉁|붙|맞|벌|걸)이$")


@lru_cache(maxsize=None)
def _n04_ieoss() -> "re.Pattern":
    """The closed noun + 이였 entry of misspellings.json (WP-10b): its hits are N04 fixes, not N05 requests."""
    return next(rx for entry_id, rx, _replace in misspellings("error") if entry_id == "ieoss_closed")


def _n05(s: str) -> List[Hit]:
    out: List[Hit] = []
    for m in _N05.finditer(s):
        if coda(m.group(1)) <= 0:
            continue
        start = m.start()
        while start > 0 and "가" <= s[start - 1] <= "힣":
            start -= 1
        word = s[start:m.start() + 2]                   # the eojeol up to and including 이
        if word.endswith(_I_NOUNS) or _I_SUFFIX.search(word):
            continue
        if m.group(2) == "였" and _n04_ieoss().match(s, start):
            continue                                    # the closed SSJ-N04 entry fixes it deterministically
        out.append((m.start() + 1, m.end(), "이었" if m.group(2) == "였" else "이에요"))
    return out


# ---- SSJ-N06 로서/로써 (제57항), 7/7 [T3] ----------------------------------------------------
_ROLE_NOUNS = ("학생|부모|사람|선생님|교사|친구|선배|후배|리더|국민|시민|어른|자녀|아이|전문가|엄마|아빠|일원|대표|회원|인간|"
               "개인|당사자|주체|구성원|한국인|기업|단체|공무원|의사|변호사|행정사|소비자|청소년|여성|남성|가장|책임자|담당자|"
               "보호자|어머니|아버지|형|누나|언니|오빠|동생|직원|팀원|팀장|선수|작가|독자")
_N06 = re.compile(r"(함|됨|시킴|짐|줌)으로서|(?<![가-힣])(이)로서(?=[\s,])|(" + _ROLE_NOUNS + r")(으로|로)써(?![가-힣])")


def _n06(s: str) -> List[Hit]:
    out: List[Hit] = []
    for m in _N06.finditer(s):
        if m.group(1):
            fix = m.group(1) + "으로써"
        elif m.group(2):
            fix = "이로써"
        else:
            fix = m.group(3) + m.group(4) + "서"
        out.append((m.start(), m.end(), fix))
    return out


# ---- SSJ-A01 왜냐하면 without a reason ending, 25/26 [T3] ------------------------------------
_WAENYA = re.compile(r"(?<![가-힣])(?:왜냐하면은|왜냐하면|왜냐면)(?![가-힣])")
_REASON = re.compile(r"때문|니까|니깐|해서[이였]|어서[이였]|아서[이였]|서다|서이다|서예요|서입니다|기에|므로|거든|잖|이유|탓")


def _a01(s: str) -> List[Hit]:
    if not _full(s):
        return []
    return [(m.start(), m.end(), None) for m in _WAENYA.finditer(s) if not _REASON.search(s[m.end():])]


def a01_fixed(sentence: str) -> bool:
    """A01 counts as fixed only when a reason ending is present (deleting 왜냐하면 is logged separately)."""
    return _REASON.search(sentence) is not None


# ---- SSJ-A02 thought double (제 생각은 … 생각합니다), 10/10 [T3] ------------------------------
_THOUGHT_SUBJ = re.compile(r"(?:^|[\s,])((?:제|저의|나의|내|우리의|필자의)\s?(?:생각|의견|입장|주장)(?:은|는))\s")
_THOUGHT_END = re.compile(r"(?:생각|판단)(?:한다|합니다|해요|했다|했습니다|된다|됩니다|돼요|이\s?든다|이\s?듭니다)\s*[.!?…\"”)]*$")


def _a02(s: str) -> List[Hit]:
    m = _THOUGHT_SUBJ.search(s)
    if m and _THOUGHT_END.search(s.rstrip()):
        return [(m.start(1), m.end(1), None)]
    return []


# ---- SSJ-A03 object particle + passive 되다, 4/4 after fix [T3] -----------------------------
# (?<!게): -게 되다 (하게 되면, 찾게 되었다) is not a passive; 6 of 10 corpus hits before this guard.
_A03 = re.compile(r"([가-힣])([을를])\s(?!잘못|안|못|참|헛|덜|잘|일관)([가-힣][가-힣])(?<!게)되(?:었|어|는|다|며|고|면|기|지|도록|니)")


def _a03(s: str) -> List[Hit]:
    out: List[Hit] = []
    for m in _A03.finditer(s):
        prev, particle = m.group(1), m.group(2)
        # a real particle: 을 after a final consonant, 를 after a vowel (가을/마을/노을 end in 을 themselves)
        if (particle == "을") != (coda(prev) > 0):
            continue
        out.append((m.start(3), m.end(), None))
    return out


# ---- SSJ-A04 double passive (closed list), SSJ-A04s 잊혀지다 [T3, T8 #10] ----------------------
def _a04(s: str) -> List[Hit]:
    return _rx_hits(_double_passive()[0], s)


def _a04s(s: str) -> List[Hit]:
    return _rx_hits(_double_passive()[1], s)


# ---- SSJ-A05 redundancy (겹말) lexicon, 52/55 [T3] ------------------------------------------
def _a05(s: str) -> List[Hit]:
    return _rx_hits(_redundancy(), s)


# ---- SSJ-A06 negative-polarity adverb without negation [T3 §3] ------------------------------
_NEG = re.compile(r"아닙|아님|어려|힘든|힘듭|힘들|드뭅|않|(?<![가-힣])안\s?[가-힣]|(?<![가-힣])안(?=[\s.])|못|없|아니|아닌|아냐|아녜|"
                  r"말(?:고|라|아|자|것)|모르|모른|몰라|몰랐|불가능|어렵|싫|금물|드물|쉽지|는커녕|\?|뿐이|만\s|밖에|"
                  r"금지|금합|금한|금하|엄금|사절|불가")
# WP-10b: 별로, 도저히 and 일절 joined the closed list (seed AGREE items SSB-044/185 별로, SSB-049 도저히,
# SSB-190 일절: each gold fix adds the negation, so the request's polarity licence applies). 거의 stays out:
# "거의 다", "거의 모든", "거의 매일" are ordinary positive uses. 일절 with a particle (애국가 일절을) is the
# noun 一節 and never matches, because a Hangul syllable may not follow; prohibition (반입 일절 금지, 사절)
# counts as the negation. 별로 followed by a word of filling or shining is the noun 별 + 로 (별로 가득한 하늘).
_A06 = re.compile(r"(?<![가-힣])(결코|좀처럼|차마|전혀|별로|도저히|일절)(?![가-힣])")
_JEONHYEO_OK = re.compile(r"\s*(?:다르|다른|달라|달랐|달리|다릅|새롭|새로운|딴|반대|예상\s?밖|의외|생소|낯설|무관|별개|엉뚱|상반)")
_BYEOLRO_STAR = re.compile(r"\s*(?:가득|빛나|빛난|반짝|뒤덮|수놓|장식|꾸미|꾸민|꾸며)")


def _a06(s: str) -> List[Hit]:
    out: List[Hit] = []
    for m in _A06.finditer(s):
        rest = s[m.end():]
        if m.group(1) == "전혀" and _JEONHYEO_OK.match(rest):
            continue
        if m.group(1) == "별로" and _BYEOLRO_STAR.match(rest):
            continue
        if not _NEG.search(rest):
            out.append((m.start(), m.end(), None))
    return out


# ---- SSJ-A07 비록/아무리/만약 agreement [T3, T8 §1a] ------------------------------------------
_BIROK = re.compile(r"(?<![가-힣])비록(?![가-힣])")
_CONCESSIVE = re.compile(r"지만|지마는|더라도|지라도|[어아여해]도|라도|[은는]들|으나|(?<=[가-힣])나[\s,]|망정|에도\s?불구|데도|면서도|"
                         r"음에도|임에도|되|이나")
_AMURI = re.compile(r"(?<![가-힣])아무리(?![가-힣])")
_AMURI_OK = re.compile(r"[가-힣]도|더라도|[은는]들|지만|봐야|해야|라도")
_MANYAK = re.compile(r"(?<![가-힣])(?:만약|만일)(?:에)?(?![가-힣의])")
_CONDITIONAL = re.compile(r"면|다면|라면|거든|경우|시에|때|이라도|해도|라도|더라도|든지")
_MANYAK_NOUN = re.compile(r"\s*(?:을|를|의|에\s?대비|에\s?대한)")


def _a07(s: str) -> List[Hit]:
    if not _full(s):
        return []
    out: List[Hit] = []
    for m in _BIROK.finditer(s):
        if not _CONCESSIVE.search(s[m.end():]):
            out.append((m.start(), m.end(), None))
    for m in _AMURI.finditer(s):
        if not _AMURI_OK.search(s[m.end():]):
            out.append((m.start(), m.end(), None))
    for m in _MANYAK.finditer(s):
        rest = s[m.end():]
        if not _MANYAK_NOUN.match(rest) and not _CONDITIONAL.search(rest):
            out.append((m.start(), m.end(), None))
    return out


# ---- CTA wording [T6 §5] ---------------------------------------------------------------------
# SP1: a 3+-syllable 하다-verb form + 주다 is spaced (NIKL 331217, 326874 as cited by T6).
# (?<=[가-힣]{2}) instead of [가-힣]{2,}: same matches, no quadratic backtracking on a long Hangul run.
_SP1 = re.compile(r"(?<=[가-힣]{2})해(주)(?=세요|십시오|시기|시길|시면|실래요|시겠어요)")
_SP2 = re.compile(r"(?:연락|문의|답변|회신|댓글|말씀|조언)(주)(?=세요|십시오|시기|시면)")
_SILGE = re.compile(r"(?<=[가-힣])실[게께]요")
_BARAE = re.compile(r"바래(?:요|서|며)|바래\s*(?:봅니다|봐요)")
_BARAE_FADE = re.compile(r"(?:빛|색|색깔|빛깔)(?:이|은|도)?\s*$")


def _sp(pattern: "re.Pattern") -> Callable[[str], List[Hit]]:
    return lambda s: [(m.start(1), m.end(1), " 주") for m in pattern.finditer(s)]


def _barae(s: str) -> List[Hit]:
    return [(m.start(), m.end(), None) for m in _BARAE.finditer(s) if not _BARAE_FADE.search(s[max(0, m.start() - 6):m.start()])]


# ---- light-verb nominalisation (lead decision 2026-10-04; NIKL easy-writing guidance [T4 §2]) -------
# Verbal nouns whose N이 되다 / N을 하다 forms are plain passives or actives; closed for precision.
_VERBAL_NOUNS = sorted(set("""
신청 접수 예약 결제 취소 환불 변경 확인 처리 등록 가입 탈퇴 해지 발급 승인 인증 수정 삭제 저장 설정 설치 연결 연동 이용 사용 적용
제공 지원 지급 발송 배송 수령 반품 교환 수리 교체 점검 검사 검토 평가 심사 상담 문의 안내 공지 공개 발표 출시 판매 구매 주문
입금 출금 이체 송금 충전 적립 할인 참여 참석 방문 입장 퇴장 출입 주차 동반 대여 반납 열람 조회 검색 업데이트 운영 관리 유지
보관 보장 보호 개선 향상 증가 감소 해결 해소 완료 종료 시작 마감 개최 개설 개통 개방 폐쇄 중단 재개 연기 확정 결정 선정 선발
채용 모집 배정 배치 이동 이전 전달 전송 공유 출력 인쇄 작성 제출 기록 측정 분석 조사 연구 실험 교육 훈련 학습 수강 강의 수업
회의 논의 협의 합의 계약 체결 반영 포함 제외 추가 생성 구성 형성 조정 정리 준비 마련 도입 활용 촬영 녹화 녹음 청소 소독 방역
정비 보수 시공 작업 인정 허용 금지 제한 차단 예방 치료 진료 진단 처방 입원 퇴원 수술 복용 섭취 관찰 확보 투자 지출 홍보 배포
노출 표시 설명 소개 추천 요청 신고 고지 통보 통지 연락 응답 답변 회신 대응 조치 검증 전환 연장 갱신 발생 이해 예상 해석 판단
진행 실시 시행 상영 관람 체험 대출 수거 배달 출장 숙박 투숙 입실 퇴실 취사 흡연 반입 출고 입고 재입고 환급 정산
""".split()), key=lambda w: (-len(w), w))
_VN = "(?:" + "|".join(_VERBAL_NOUNS) + ")"
_VN_WORD = r"(?<![가-힣])[가-힣]{0,3}?(" + _VN + r")"
_LV1 = re.compile("(?:" + _VN_WORD + r"[이가]|(?<![가-힣])[가-힣]{1,8}(는)\s+것이)\s+가능(?:하|합|한|해|했|할|함)")
# 기록/시작 + 이 되다 mostly means "become a record/the start" (좋은 기록이 되었다), not a passive.
_VN_LV2 = "(?:" + "|".join(w for w in _VERBAL_NOUNS if w not in ("기록", "시작")) + ")"
_LV2 = re.compile(r"(?<![가-힣])[가-힣]{0,3}?(" + _VN_LV2 + r")[이가]\s+(?:되|됩|된|될|돼|됐)")
_LV3 = re.compile(_VN_WORD + r"[이가]\s+이루어(?:지|진|질|져|졌|집)")
_LV4 = re.compile(_VN_WORD + r"[을를]\s+(?:진행|실시)(?:하|합|한|할|해|했|함|됩|된|되)")
_LV_NEGATED = re.compile(r"\s*지\s*(?:않|못)")
_LEGAL = re.compile(r"제\s*\d+\s*(?:조|항|호)|법률|시행령|시행규칙|조례|약관|정관|법령")


def _light_verb(pattern: "re.Pattern") -> Callable[[str], List[Hit]]:
    def detect(s: str) -> List[Hit]:
        if _LEGAL.search(s):
            return []                    # legal or defined terms: the wording is the term (3.3)
        out: List[Hit] = []
        for m in pattern.finditer(s):
            if _LV_NEGATED.match(s, m.end()):
                continue
            start = m.start(1) if m.group(1) else m.start()
            out.append((start, m.end(), None))
        return out
    return detect


# ---- translationese hints (essay, report, document) [T3 §3, T8 #13] ---------------------------
_GAJANG_HANA = (r"가장\s(?:[가-힣]{1,20}\s){0,4}?[가-힣]{1,20}\s?(?:것|곳|사람|요소|방법|문제|이유|도시|나라|국가|분야|기업|사례|원인|작품|과제|"
                r"수단|기술|특징|부분|측면|가치)?\s?중(?:의|에)?\s?(?:하나|한\s?가지|한\s?명|한\s?곳|하나로)")
_PILYO_RO = r"(?:을|를)\s필요로\s(?:하|한|했|합)"
_GANEUNG_MAKE = r"(?:을|를)\s가능하게\s(?:만들|한|하|해|했)"
_LIST_AND = r"(?<![가-힣A-Za-z])[가-힣A-Za-z]{1,20}(?:[와과])?,\s[가-힣A-Za-z ]{1,15},\s그리고\s[가-힣A-Za-z]{1,20}"
_SIKIDA = r"(?:소개|설득|입금|주차|접수|전달|완화|충족|확장|자동화|취소|금지|해소|분리|연결|대입|진행|개선|단축|접목)\s?시(?:키|켜|킨|킬|켰|킴)"

# ---- calque requests (WP-8b) ---------------------------------------------------------------------
# Closed patterns from the lead's first real-model run (genre general): the writer was never asked to fix
# "넓은 공간을 가지고 있어서", "배송 준비중에 있습니다", "주문 건에 대해서 안내드립니다". A request span licenses
# every word it overlaps for meaning.drops (content_dropped), so each span starts at the frame word (가지고 있,
# 중에 있 or 있 after an attached 준비중에, 대해서) and never overlaps the noun; 으로부터 is written inside the noun's
# eojeol and cannot avoid it (the repair keeps the noun). Hand-checked precision, hit rates and genre scope
# are in the WP-8b report; NIKL 한눈에 알아보는 공공언어 바로 쓰기 (개정판, 2022; PDF pp. 42, 44, 54, 98, 100)
# calls ~에 대하여, ~를 ~ 중에 있다 and 으로부터 translation-style or unnatural (the possession calque is not in it).
#
# TR-GAJIDA: an abstract noun object of 가지다/갖다 ("N을 가지고 있다" -> "N이 있다/N이 넓다"). Closed noun list:
# the lead's ten nouns plus the abstract nouns that occurred as such objects in the WP-8b corpora; natural
# collocations (관심·시간·자신감·기회·책임감·꿈·생각·의견·경험) are not in it. 가지고 without 있다 is the instrument
# reading (이 기능을 가지고 만든다) and never matches; negation (가지고 있지 않다) and legal text (권한을 가진다 in
# a statute) are skipped.
_GAJI_NOUNS = sorted(set("""
공간 기능 특징 장점 단점 의미 역할 능력 권한 효과
특성 강점 약점 이점 의의 성능 가치 매력 한계 공통점 문제점 잠재력 영향력 기술력
""".split()), key=lambda w: (-len(w), w))
_GAJI_ADVERB = r"(?:(?:많이|모두|이미|여전히|충분히|동시에|각각|분명히|확실히|두루|고루)\s)?"
_GAJI = re.compile(r"(?<![가-힣])[가-힣]{0,4}?(?:" + "|".join(_GAJI_NOUNS) + r")(?:들)?[을를]\s" + _GAJI_ADVERB +
                   r"(가지고\s?있|갖고\s?있|가진|가지는|가집니|가지며|가졌|갖는|갖습니)")
_GAJI_NEGATED = re.compile(r"[가-힣]{0,6}?지\s*(?:않|못)")
# A quoted gloss: "'전하다'라는 의미를 가진 텔" reads best as "~라는 뜻의", not "~라는 의미가 있는" (2/2 FP in the check).
_GAJI_GLOSS = re.compile(r"(?:라는|이란)\s(?:의미|의의)[를을]\s(?:가진|가지는|갖는)")


def _gajida(s: str) -> List[Hit]:
    if _LEGAL.search(s):
        return []
    out: List[Hit] = []
    for m in _GAJI.finditer(s):
        if _GAJI_NEGATED.match(s, m.end()) or _GAJI_GLOSS.search(s, max(0, m.start(1) - 12), m.end(1)):
            continue
        out.append((m.start(1), m.end(1), None))
    return out


# TR-JUNGE_ITDA: "N 중에 있다" after a verbal noun (진행 중에 있습니다, 준비중에 있으며) -> "N 중이다 / N하고 있다"
# (NIKL 2022 PDF p. 44: '~를 ~ 중에 있다'는 부자연스러우므로 '~를 ~하고 있다'). Predicate forms only: the adnominal
# 회의 중에 있었던 일 ("what happened during the meeting") is a time adverbial, not the calque; honorific 계시다
# is left alone (회의 중에 계십니다 -> 회의 중이십니다 would touch the honorific lock).
_JUNG_NOUNS = sorted(set(_VERBAL_NOUNS) | set("""
추진 건립 개발 공사 수행 계획 분양 협상 수사 제작 시공 조성 구축 집행 심의 협력 추적 편집 촬영 리모델링 복구 공모 기획
""".split()), key=lambda w: (-len(w), w))
_JUNG = re.compile(r"(?<![가-힣])[가-힣]{0,3}?(?:" + "|".join(_JUNG_NOUNS) + r")\s?(중에\s?(있(?:습니|었습니|다|어요|었어요|"
                   r"어|었다|으며|었으며|고|었고|음|으나|는데|었는데|지만|으니)))")


def _junge(s: str) -> List[Hit]:
    out: List[Hit] = []
    for m in _JUNG.finditer(s):
        attached = "가" <= s[m.start(1) - 1] <= "힣"          # 준비중에: the eojeol holds the noun
        out.append((m.start(2) if attached else m.start(1), m.end(1), None))
    return out


# TR-DAEHAE: "N에 대해(서) + 안내/설명/논의 … + 하다/드리다" where the verbal noun takes N as its object
# ("주문 건에 대해서 안내드립니다" -> "주문 건을 안내드립니다"). The verbal noun must follow directly (with an
# optional 을/를 and at most one manner adverb: 자세히 설명드리겠습니다): "N에 대해 X를 설명하다" already has an
# object and keeps 대해. Topic 대해서는 never matches. Verbs whose object reading changes the sense stay out
# (이야기·얘기·말씀·토론·답변·질문·교육: 질문들에 대해 답변했다 -> *질문들을 답변했다; 17/40 in the WP-8b check).
_DAEHAE_VN = "안내|설명|논의|언급|소개|공지|검토|조사|분석|강조"
_DAEHAE_ADVERB = (r"(?:(?:자세히|간단히|간략히|다시|먼저|충분히|구체적으로|자세하게|상세히|추가로|따로|직접|미리|"
                  r"다음과\s같이)\s)?")
_DAEHAE = re.compile(r"[가-힣](에\s?대(?:해서?|하여))\s+" + _DAEHAE_ADVERB + r"(?:" + _DAEHAE_VN + r")(?:을|를)?\s?"
                     r"(?:하|해|했|합|한|할|함|드리|드립|드려|드릴|드렸|드린|드림)")
# Pronouns that refer to a person: 그에 대해 설명했다 -> 그를 설명했다 changes the sense.
_DAEHAE_PERSON = re.compile(r"(?:^|[^가-힣])(?:그|그녀|그들|그분|저|나|너|당신|우리|저희|자신|본인)$")


def _daehae(s: str) -> List[Hit]:
    if _LEGAL.search(s):
        return []                        # 제3조에 대하여 심사한다: the statute's wording
    out: List[Hit] = []
    for m in _DAEHAE.finditer(s):
        if _DAEHAE_PERSON.search(s, max(0, m.start(1) - 6), m.start(1)):
            continue
        start = m.start(1) + (m.group(1).index("대"))      # 대해서, not the 에 of the noun's eojeol
        out.append((start, m.end(1), None))
    return out


# TR-ROBUTEO: "N(으)로부터" with a person source and a receiving verb (고객으로부터 문의를 받았습니다 ->
# 고객에게서/고객한테서 문의를 받았습니다). 님 nouns are left alone (부모님으로부터 -> 부모님께 changes the
# honorific-noun count the voice family locks), and so are separation verbs (위협으로부터 보호하다, 부모로부터
# 독립하다), whose 로부터 is not "from a giver".
_ROBUTEO_PERSON = sorted(set("""
고객 회원 사용자 이용자 소비자 구매자 판매자 시민 주민 국민 학생 학부모 부모 친구 동료 선배 후배 상사 부하 직원 팀장 관계자
담당자 전문가 의사 교수 지인 가족 이웃 독자 시청자 손님 아이 아이들 엄마 아빠 어머니 아버지 남편 아내 언니 오빠 형 누나 동생
""".split()), key=lambda w: (-len(w), w))
_ROBUTEO = re.compile(r"(?<![가-힣])(?:" + "|".join(_ROBUTEO_PERSON) + r")(?:들)?(으로부터|로부터)(?![가-힣])")
_ROBUTEO_RECEIVE = re.compile(r"받|들었|들은|듣|들어|전해|전달|연락|문의|요청|제안|부탁|초대|소식|편지|메일|메시지|선물|칭찬|"
                              r"비판|항의|지적|추천|배우|배운|배웠|얻|빌|물려|건네")
_ROBUTEO_SEPARATE = re.compile(r"자유|벗어|보호|지키|지켜|멀어|멀리|독립|분리|해방|격리|차단|탈피|떨어|도망|도피|숨")


def _robuteo(s: str) -> List[Hit]:
    out: List[Hit] = []
    for m in _ROBUTEO.finditer(s):
        rest = s[m.end():m.end() + 24]
        if _ROBUTEO_SEPARATE.search(rest) or not _ROBUTEO_RECEIVE.search(rest):
            continue
        out.append((m.start(1), m.end(1), None))
    return out


# ---- v1 style rules kept as SUGGEST (port of src/engine/super-sejong.ts) -----------------------
_PROCESS = r"하는\s+과정에서"
# v1 frames plus 에게 있어(서) (T3 A_EGE_ISSEO), which has no locative reading when nothing stands between.
_PUBLIC_FRAME = (r"(?:함|됨|하기|되기)에\s+있어서|(?<=[가-힣][는은]\s)데\s+있어서|(?:에|에서)\s+있어서(?=는|의|도)|"
                 r"(?:에게|에겐|한테)\s?있어(?:서)?(?![가-힣]*[다요])")
_CAUSAL_LEAD = r"(?:으로|로)\s+이어(?:질|지|진|집니다|졌)(?![가-힣])"


def _public_guard(s: str, m: "re.Match") -> bool:
    return s[m.start()] == "데" or (m.start() > 0 and "가" <= s[m.start() - 1] <= "힣")


def _process_guard(s: str, m: "re.Match") -> bool:
    return m.start() > 0 and "가" <= s[m.start() - 1] <= "힣"


# ---- LLM tells: SUGGEST in essay/report, LEAVE elsewhere (blog: the owner's voice) [T3 §3-4] -----
_IMPORTANCE = (r"(?:는|은|ㄹ|할|될|볼)\s*것이\s*(?:매우\s+|가장\s+|무엇보다\s+)?(?:중요|필수적|필요|바람직)(?:하|합|한|해)|"
               r"중요한\s+(?:역할|도구|요소|열쇠|과제)(?=[을를이가은는입\s,.])")
_CONCLUDING = re.compile(r"(?:결론적으로|요약하자면|요약하면|종합하면|정리하자면)(?=[\s,])")
_DEMO_THROUGH = r"(?<![가-힣])이를\s+통(?:해서?|하여)(?![가-힣])"
_ROLE_ADJ = (r"(?:중요한|큰|핵심적인|결정적인|주요한|필수적인|중대한|막대한|지대한|중추적인|핵심|중요)\s(?:[가-힣]+\s)?역할을\s+"
             r"(?:하|한|합|했|해|수행|담당)")
_BOILER = (r"(?:알아보|살펴보|짚어보|다뤄보|정리해\s*보|소개해\s*드리|알려\s*드리)(?:겠습니다|겠다|도록\s*하겠습니다|도록\s*하겠다)|"
           r"(?:알아볼|살펴볼)까요|(?:알아|살펴)봅시다")
_NAGAYA = r"(?:해|어|아|여)\s?나가야\s?(?:할|합니다|한다|하겠)|해야\s할\s것(?:이다|입니다)"
_INEUN = re.compile(r"이는\s")


def _role_guard(s: str, m: "re.Match") -> bool:
    return not re.search(r"주인공|배역|악역|조연|주연|배우|연기|캐릭터|직책", s[max(0, m.start() - 12):m.start()])


def _boiler_guard(s: str, m: "re.Match") -> bool:
    # quoted commitments in news: "면밀히 살펴보겠다"고 말했다
    return not re.match(r"\s?[”\"’'" + T.MASK_CHAR + r"]?\s?(?:고|라고|며|면서|는|던)(?![가-힣])", s[m.end():m.end() + 6])


def _nagaya_guard(s: str, m: "re.Match") -> bool:
    tail = s[m.end():m.end() + 6]
    return not re.match(r"\s?[”\"’']?\s?(?:고|며|면서|는|던)(?![가-힣])", tail) and not re.match(r"다?\s?[”\"]?\s?(?:고|며|는)\s", tail)


def _initial(pattern: "re.Pattern") -> Callable[[str], List[Hit]]:
    def detect(s: str) -> List[Hit]:
        lead = _lead_len(s)
        m = pattern.match(s, lead)
        return [(m.start(), m.end() - (1 if m.group(0).endswith(" ") else 0), None)] if m else []
    return detect


# ---- paragraph-scope rules: clusters and runs (v1) --------------------------------------------
_INTENSIFIER = re.compile(r"(?<![가-힣])(?:매우|다양한|효과적(?:인|으로)?|적극적(?:인|으로)?|지속적(?:인|으로)?|체계적(?:인|으로)?|"
                          r"종합적(?:인|으로)?|획기적(?:인|으로)?|핵심적(?:인)?|중요한|필수적(?:인|이다)?|긍정적(?:인)?|"
                          r"다각적(?:인|으로)?)(?![가-힣])")
_JEOK = re.compile(r"(?<![가-힣])(?!목적|표적|국적|성적|실적|면적|체적)[가-힣]{2,8}적(?:인|으로)(?![가-힣])")
_THROUGH = re.compile(r"[을를]\s+통(?:해서?|하여|한|하며)(?![가-힣])")
_HEDGE = re.compile(r"[가-힣]\s+수\s+있(?:다|습니다|으며|는|고|을)")
_CONNECTOR = re.compile(r"(또한|따라서|그러므로|이에\s*따라|더불어|아울러|결과적으로|결론적으로)(?=[,\s])")
_ENDING_TAIL = re.compile(r"[.!?\"”’')\]」』。]+$")


@dataclass
class _Ctx:
    doc: Document
    masked: str
    spans: Sequence[Span]
    genre: str = "general"


def _clusters(ctx: _Ctx, pattern: "re.Pattern", minimum: int, window: int, guard=None) -> List[Hit]:
    out: List[Hit] = []
    for p_start, p_end in ctx.doc.paragraphs:
        hits = [(m.start(), m.end()) for m in pattern.finditer(ctx.masked, p_start, p_end)
                if guard is None or guard(ctx.masked, m)]
        i = 0
        while i < len(hits):
            j = i
            while j + 1 < len(hits) and hits[j + 1][0] - hits[i][0] <= window:
                j += 1
            if j - i + 1 >= minimum:
                out.append((hits[i][0], hits[j][1], None))
                i = j + 1
            else:
                i += 1
    return out


def _through_guard(s: str, m: "re.Match") -> bool:
    return not re.search(r"(?:^|[^가-힣])이$", s[max(0, m.start() - 2):m.start()])


def _hedge_guard(s: str, m: "re.Match") -> bool:
    return coda(s[m.start()]) == 8


def _connector_run(ctx: _Ctx) -> List[Hit]:
    out: List[Hit] = []
    units = [u for u in ctx.doc.units if u.kind not in ("heading", "quote")]
    marks: List[Optional[Tuple[int, int]]] = []
    for u in units:
        s = ctx.masked[u.start:u.end]
        lead = _lead_len(s)
        m = _CONNECTOR.match(s, lead)
        marks.append((u.start + m.start(1), u.start + m.end(1)) if m else None)
    for i in range(1, len(units)):
        if not marks[i]:
            continue
        count = 1
        for j in range(i - 1, max(-1, i - 3), -1):
            if units[j].para != units[i].para:
                break
            if marks[j]:
                count += 1
        if count >= 2:
            out.append((marks[i][0], marks[i][1], None))
    return out


def _ending_monotony(ctx: _Ctx) -> List[Hit]:
    out: List[Hit] = []
    previous, run, para = "", 0, -1
    for u in ctx.doc.units:
        s = ctx.masked[u.start:u.end]
        bare = _ENDING_TAIL.sub("", s)
        tail = bare[-3:]
        key = tail if re.fullmatch("[가-힣]{3}", tail) else ""
        run = run + 1 if key and key == previous and u.para == para else (1 if key else 0)
        previous, para = key, u.para
        if run == 5:
            start = len(bare)
            while start > 0 and not bare[start - 1].isspace() and len(bare) - start < 16:
                start -= 1
            out.append((u.start + start, u.end, None))
    return out


# ---- clarity (WP-7) ---------------------------------------------------------------------------
def _clarity():
    """sejong.clarity when WP-7 is merged, else None (CLR-LONG and CLR-APPROX2 then never fire)."""
    if importlib.util.find_spec(__package__ + ".clarity") is None:
        return None
    return importlib.import_module(__package__ + ".clarity")


def _clr_long(ctx: _Ctx) -> List[Hit]:
    clarity = _clarity()
    if clarity is None or not hasattr(clarity, "long_review"):
        return []
    return [(u.start, u.end, None) for u in ctx.doc.units if u.kind == "body" and clarity.long_review(u, ctx.genre)]


def _clr_approx2(s: str) -> List[Hit]:
    clarity = _clarity()
    if clarity is None or not hasattr(clarity, "approx2"):
        return []
    out: List[Hit] = []
    for item in clarity.approx2(s):
        start, end = (item.start, item.end) if hasattr(item, "start") else (item[0], item[1])
        out.append((start, end, None))
    return out


# ---- the table ---------------------------------------------------------------------------------
def _r(id, tier, action, genres, detect, success=None, scope="sentence", allow_split=False) -> Rule:
    return Rule(id=id, tier=tier, action=action, genres=genres, detect=detect, guide_id=id, success=success,
                scope=scope, allow_split=allow_split)


_RULE_LIST: Tuple[Rule, ...] = (
    # norm layer: FIX
    _r("SSJ-N01", "FIX", "deterministic", ALL, _n01),
    _r("SSJ-N02", "FIX", "deterministic", ALL, _n02),
    _r("SSJ-N03", "FIX", "request", ALL, _n03),
    _r("SSJ-N04", "FIX", "deterministic", ALL, lambda s: _lexicon_hits(s, "error")),
    _r("SSJ-N04C", "LEAVE", "report", ALL, lambda s: _lexicon_hits(s, "colloquial")),
    _r("SSJ-N05", "FIX", "request", ALL, _n05),
    _r("SSJ-N06", "FIX", "request", ALL, _n06),
    _r("SSJ-A01", "FIX", "request", ALL, _a01, success=a01_fixed),
    _r("SSJ-A02", "FIX", "request", ALL, _a02),
    _r("SSJ-A03", "FIX", "request", ALL, _a03),
    _r("SSJ-A04", "FIX", "request", ALL, _a04),
    _r("SSJ-A06", "FIX", "request", ALL, _a06),
    _r("SSJ-A07", "FIX", "request", ALL, _a07),
    _r("CTA-SP1", "FIX", "deterministic", ALL, _sp(_SP1)),
    _r("CTA-SP2", "FIX", "deterministic", ALL, _sp(_SP2)),
    # SUGGEST in every genre
    _r("SSJ-A04S", "SUGGEST", "request", ALL, _a04s),
    _r("SSJ-A05", "SUGGEST", "request", ALL, _a05),
    _r("CTA-BARAE", "SUGGEST", "request", ALL, _barae),
    _r("CLR-LONG", "SUGGEST", "request", ALL, _clr_long, scope="document", allow_split=True),
    _r("CLR-APPROX2", "SUGGEST", "request", ALL, _clr_approx2),
    _r("SSJ-LV1", "SUGGEST", "request", ALL, _light_verb(_LV1)),
    _r("SSJ-LV2", "SUGGEST", "request", ALL, _light_verb(_LV2)),
    _r("SSJ-LV3", "SUGGEST", "request", ALL, _light_verb(_LV3)),
    _r("SSJ-LV4", "SUGGEST", "request", ALL, _light_verb(_LV4)),
    _r("CONNECTOR_RUN", "SUGGEST", "request", ALL, _connector_run, scope="document"),
    _r("TR-GAJIDA", "SUGGEST", "request", ALL, _gajida),
    _r("TR-JUNGE_ITDA", "SUGGEST", "request", ALL, _junge),
    _r("TR-DAEHAE", "SUGGEST", "request", ALL, _daehae),
    _r("TR-ROBUTEO", "SUGGEST", "request", ALL, _robuteo),
    # SUGGEST in some genres, LEAVE elsewhere
    _r("TR-GAJANG_HANA", "SUGGEST", "request", TRANSLATIONESE, _rx(_GAJANG_HANA)),
    _r("TR-PILYO_RO", "SUGGEST", "request", TRANSLATIONESE, _rx(_PILYO_RO)),
    _r("TR-GANEUNG_MAKE", "SUGGEST", "request", TRANSLATIONESE, _rx(_GANEUNG_MAKE)),
    _r("TR-LIST_AND", "SUGGEST", "request", TRANSLATIONESE, _rx(_LIST_AND)),
    _r("TR-SIKIDA", "SUGGEST", "request", TRANSLATIONESE, _rx(_SIKIDA)),
    _r("PUBLIC_LANGUAGE_FRAME", "SUGGEST", "request", TRANSLATIONESE, _rx(_PUBLIC_FRAME, guard=_public_guard, lead=24)),
    _r("PROCESS_NOMINALIZATION", "SUGGEST", "request", ESSAY_REPORT, _rx(_PROCESS, guard=_process_guard, lead=24)),
    _r("CAUSAL_LEAD", "SUGGEST", "request", ESSAY_REPORT, _rx(_CAUSAL_LEAD, lead=10)),
    _r("THROUGH_CLUSTER", "SUGGEST", "request", ESSAY_REPORT,
       lambda ctx: _clusters(ctx, _THROUGH, 2, 250, _through_guard), scope="document"),
    _r("JEOK_CLUSTER", "SUGGEST", "request", ("essay",), lambda ctx: _clusters(ctx, _JEOK, 3, 150), scope="document"),
    _r("IMPORTANCE_FORMULA", "SUGGEST", "request", ESSAY_REPORT, _rx(_IMPORTANCE, lead=12)),
    _r("CONCLUDING_SIGNPOST", "SUGGEST", "request", ESSAY_REPORT, _initial(_CONCLUDING)),
    _r("DEMONSTRATIVE_THROUGH", "SUGGEST", "request", ESSAY_REPORT, _rx(_DEMO_THROUGH)),
    _r("ROLE_FORMULA", "SUGGEST", "request", ESSAY_REPORT, _rx(_ROLE_ADJ, guard=_role_guard)),
    _r("BOILERPLATE_ANNOUNCE", "SUGGEST", "request", ESSAY_REPORT, _rx(_BOILER, guard=_boiler_guard)),
    _r("NAGAYA_CLOSING", "SUGGEST", "request", ESSAY_REPORT, _rx(_NAGAYA, guard=_nagaya_guard)),
    _r("SENT_INITIAL_INEUN", "SUGGEST", "request", ESSAY_REPORT, _initial(_INEUN)),
    # LEAVE everywhere (report only)
    _r("CTA-SILGE", "LEAVE", "report", ALL, _rx(_SILGE.pattern)),
    _r("ENDING_MONOTONY", "LEAVE", "report", ALL, _ending_monotony, scope="document"),
    _r("INTENSIFIER_CLUSTER", "LEAVE", "report", ALL, lambda ctx: _clusters(ctx, _INTENSIFIER, 3, 250), scope="document"),
    _r("CAPABILITY_HEDGE_CLUSTER", "LEAVE", "report", ALL,
       lambda ctx: _clusters(ctx, _HEDGE, 4, 300, _hedge_guard), scope="document"),
)
RULES: Dict[str, Rule] = {rule.id: rule for rule in _RULE_LIST}

# Families used by norms.introduced(): the norm rules of the 3.8 "norms" row, and the LLM tells.
NORM_RULES = ("SSJ-N01", "SSJ-N02", "SSJ-N03", "SSJ-N04", "SSJ-N05", "SSJ-N06", "SSJ-A04")
TELL_RULES = ("IMPORTANCE_FORMULA", "CONCLUDING_SIGNPOST", "DEMONSTRATIVE_THROUGH", "ROLE_FORMULA",
              "BOILERPLATE_ANNOUNCE", "NAGAYA_CLOSING", "SENT_INITIAL_INEUN")


def rule_tier(rule_id: str, genre: str = "general", fix_colloquial: bool = False) -> Tuple[str, str]:
    """(tier, action) of a rule in a genre (3.3 table and genre gating)."""
    rule = RULES[rule_id]
    if rule_id == "SSJ-N04C":
        return ("FIX", "deterministic") if fix_colloquial else ("LEAVE", "report")
    if rule.genres == ALL or genre in rule.genres:
        return rule.tier, rule.action
    return "LEAVE", "report"


# --------------------------------------------------------------------------
# running the rules
# --------------------------------------------------------------------------
def _overlaps(starts: List[int], spans: Sequence[Span], start: int, end: int) -> bool:
    """Whether [start, end) intersects a span. protected_spans() returns spans sorted by start that never
    overlap each other, so their ends are sorted too and only the last span starting before `end` matters."""
    k = bisect_right(starts, end - 1) - 1
    return k >= 0 and spans[k].end > start


_TABLE_ROW = re.compile(r"\s*\|.*\|\s*\Z")


def _skipped_units(doc: Document) -> List[Unit]:
    """Units no rule reads (v1 parity, DESIGN 3.3 "excl. quotes, headings"): headings, blockquote lines and
    whole quotations (kind quote), Markdown table rows, and paragraphs indented as code (every line starts
    with four spaces or a tab). protect.py freezes headings and quotations already; the other two are
    not freeze spans in WP-1, so they are skipped here."""
    out: List[Unit] = []
    code_paras = set()
    for index, (p_start, p_end) in enumerate(doc.paragraphs):
        lines = [line for line in doc.text[p_start:p_end].split("\n") if line.strip()]
        if lines and all(line.startswith(("    ", "\t")) for line in lines):
            code_paras.add(index)
    table_lines: List[Tuple[int, int]] = []          # (start, end) of Markdown table rows, sorted
    pos = 0
    for line in doc.text.split("\n"):
        if _TABLE_ROW.match(line):
            table_lines.append((pos, pos + len(line)))
        pos += len(line) + 1
    table_starts = [a for a, _ in table_lines]
    for unit in doc.units:
        k = bisect_right(table_starts, unit.start) - 1
        in_table = k >= 0 and unit.start < table_lines[k][1]
        if unit.kind in ("heading", "quote") or unit.para in code_paras or in_table:
            out.append(unit)
    return out


def raw_hits(doc: Document, spans: Sequence[Span], rule_ids: Optional[Iterable[str]] = None,
             genre: str = "general") -> List[Tuple[str, int, int, Optional[str]]]:
    """(rule, start, end, fix) for every detector hit, document offsets, before tier gating. A rule's
    detection never depends on the genre (only CLR-LONG's threshold does, inside clarity.long_review)."""
    wanted = list(RULES) if rule_ids is None else list(rule_ids)
    masked = masked_text(doc.text, spans)
    skipped = _skipped_units(doc)
    if skipped:                                   # blank them so paragraph-scope rules skip them too
        pieces, last = [], 0
        for unit in skipped:
            pieces.append(masked[last:unit.start])
            pieces.append(re.sub(r"[^\n]", T.MASK_CHAR, masked[unit.start:unit.end]))
            last = unit.end
        pieces.append(masked[last:])
        masked = "".join(pieces)
    skip_ids = {unit.id for unit in skipped}
    ctx = _Ctx(doc=doc, masked=masked, spans=spans, genre=genre)
    sentence_rules = [RULES[r] for r in wanted if RULES[r].scope == "sentence"]
    out: List[Tuple[str, int, int, Optional[str]]] = []
    for unit in doc.units:
        if unit.id in skip_ids:
            continue
        s = masked[unit.start:unit.end]
        if not re.search("[가-힣]", s):
            continue
        for rule in sentence_rules:
            for start, end, fix in rule.detect(s):
                out.append((rule.id, unit.start + start, unit.start + end, fix))
    for rule_id in wanted:
        rule = RULES[rule_id]
        if rule.scope == "document":
            out.extend((rule.id, start, end, fix) for start, end, fix in rule.detect(ctx))
    return out


def diagnose(doc: Document, options: Optional[Options] = None, *, genre: Optional[str] = None,
             strength: Optional[str] = None, fix_colloquial: Optional[bool] = None,
             spans: Optional[Sequence[Span]] = None) -> List[Finding]:
    """Findings of every rule on a segmented chunk, with tier and action per the 3.3 table.

    `options` (types.Options) supplies genre and fix_colloquial; keyword arguments override it.
    `strength` is accepted for the DESIGN 5.1 signature but does not change detection: which tiers
    become requests is plan.build_plan's decision (3.4). `spans` defaults to
    protect.protected_spans(doc, fix_colloquial=...). Findings are sorted by position and numbered F1..
    """
    genre = genre or (options.genre if options else "general")
    if fix_colloquial is None:
        fix_colloquial = options.fix_colloquial if options else False
    del strength
    if spans is None:
        spans = P.protected_spans(doc, fix_colloquial=fix_colloquial)
    starts = [s.start for s in spans]
    findings: List[Tuple[int, int, str, str, str, Optional[str]]] = []
    for rule_id, start, end, fix in raw_hits(doc, spans, genre=genre):
        tier, action = rule_tier(rule_id, genre, fix_colloquial)
        if action == "deterministic":
            if fix is None or _overlaps(starts, spans, start, end):
                continue
        elif rule_id not in ("SSJ-N03", "SSJ-N05", "SSJ-N06"):
            fix = None                     # only rules that know the expected form carry one
        findings.append((start, end, rule_id, tier, action, fix))
    findings.sort(key=lambda f: (f[0], f[1], f[2]))
    out: List[Finding] = []
    for start, end, rule_id, tier, action, fix in findings:
        unit = T.unit_at(doc, start) or T.unit_at(doc, max(start, end - 1))
        if unit is None:
            continue
        out.append(Finding(id=f"F{len(out) + 1}", rule=rule_id, tier=tier, action=action, sentence=unit.id,
                           start=start, end=end, fix=fix))
    return out


def rule_fires(rule_id: str, sentence: str, *, fix_colloquial: bool = False) -> bool:
    """Whether a sentence-scope rule still fires on one (rewritten) sentence, freeze spans masked."""
    doc = T.segment(sentence)
    spans = P.protected_spans(doc, fix_colloquial=fix_colloquial)
    return any(True for _ in raw_hits(doc, spans, [rule_id]))


def request_fixed(rule_id: str, sentence: str) -> bool:
    """Request-status helper (3.8): a rule's own success check, else "its detector no longer fires"."""
    rule = RULES[rule_id]
    if rule.success is not None:
        return rule.success(sentence)
    if rule.scope != "sentence":
        raise ValueError(f"{rule_id} is not a sentence rule")
    return not rule_fires(rule_id, sentence)
