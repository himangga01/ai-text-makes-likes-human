"""CTA ledger of Super Sejong Engine v2 (DESIGN.md 3.3, 3.8; port of T6 cta_detect_final.py).

A CTA unit is a sentence, heading or button line in which the AUTHOR directs, requests, advises or invites
the READER to perform a future action with an explicit directive form. Not CTA: greetings and blessings,
speaker commissives (정리해 보겠습니다, 안내해 드립니다), plain deontic statements (해야 합니다, 필요합니다:
tracked in the meaning ledger, returned here only as units), ability or option statements, anything
inside quotation marks, reported speech.

    detect(doc)               -> (list[CtaUnit], list[Unit])    ledger and the plain deontic units
    analyse(doc)              -> Ledger                          detect() plus what the gate needs
    wording_findings(doc)     -> list[Finding]                   CTA-SP1, CTA-SP2, CTA-SILGE, CTA-BARAE
    safe_repair(text, *, fix_colloquial=False) -> (text, [repair codes])

Force ladder (ordinal, our own design, T6 section 4): 5 emphatic (directive + 꼭/반드시/지금 바로),
4 directive (imperative, request, prohibition), 3 softened (해 보세요, 합시다, conditional offer),
2 advisory (하는 것이 좋습니다, 권합니다), 1 option (해 보는 것도 좋습니다, 하셔도 됩니다), 0 none.

Differences from the T6 prototype (each is pinned in tests/skills/test_sejong_cta.py):
  * units come from text.segment() and quotations from text.mask_quotes(), masked once per document, so a
    quotation that spans lines stays masked; a nominal button line must be a whole line of the text
  * extraction runs on the lead-stripped sentence (the prototype applied cue offsets to the unstripped
    one, which cut the core of a bulleted CTA short)
  * the condition clause ends only at a conditional ending that is not followed by a Hangul syllable and
    skips nouns that end in 면 (도면, 화면, 서면, 반면; 면허 and 면접 no longer open a condition); it knows
    "-ㄴ/-ㄹ 경우" and "-ㄴ/-ㄹ 때" (T6 wrote ㄹ as a jamo, which never occurs in text)
  * found on the seed benchmark's gold rewrites, which T6 never ran: the light verb 하여 (연락을 하여
    주시기) was read as an action, 보시길 바라겠습니다 had another force than 보시기 바랍니다, and
    "주시면 힘이 됩니다" was not a request; a button's action is its verbal noun (예약), not its phrase
  * classification is a pure function of the unit's strings and is memoised, so repeated sentences and the
    sentences a rewrite leaves unchanged are classified once
  * safe_repair has no -실게요 repair (OD 4); -ㄹ께요 -> -ㄹ게요 runs only with fix_colloquial (OD 2) and
    also repairs a stem that stands alone (제가 볼께요), which T6's lookbehind skipped
Every regex runs on at most the last MAX_UNIT characters of a sentence, except the plain-obligation test,
which scans the whole sentence once, so no input is quadratic in the text length.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import text as T
from .types import CtaUnit, Document, Finding, Unit

LEXICON_PATH = Path(__file__).resolve().parent / "data" / "cta_lexicon.json"
MAX_UNIT = 400


def _jong_class(*jongs: int) -> str:
    """Character class body of the Hangul syllables whose final consonant index is in `jongs`
    (4 = ㄴ, 8 = ㄹ)."""
    return "".join(chr(c) for c in range(0xAC00, 0xD7A4) if (c - 0xAC00) % 28 in jongs)


def load_lexicon() -> dict:
    with LEXICON_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


LEX = load_lexicon()


def _re(pattern: str, flags: int = 0) -> "re.Pattern[str]":
    return re.compile(pattern, flags)


def _cond_pattern(pattern: str) -> str:
    return (pattern.replace("{NOUN_MYEON}", LEX["condition"]["noun_myeon_prefix"])
            .replace("{JONG_NL}", _jong_class(4, 8)))


@dataclass(frozen=True)
class Cue:
    id: str
    form: str
    force: int
    rx: "re.Pattern[str]"


CUES: Tuple[Cue, ...] = tuple(Cue(c["id"], c["form"], c["force"], _re(c["pattern"])) for c in LEX["cues"])
DEONTIC = _re(LEX["deontic"])
DEON_ACTION = _re(LEX["deontic_action"])
OFFER = _re(LEX["offer"])
NOMINAL_ACTION = _re(LEX["nominal_action"])
NOMINAL_ACTION_HEAD = _re(LEX["nominal_action"][:-1])      # the same without its end anchor
BTN_NOUN = _re(LEX["button"]["noun"])
BTN_MARK = _re(LEX["button"]["mark"])
BTN_STRONG_MARKS = LEX["button"]["strong_marks"]
INTENS_NEC = _re(LEX["intensity"]["necessity"])
INTENS_IMM = _re(LEX["intensity"]["immediacy"])
INTENS_PROHIB = _re(LEX["intensity"]["prohibitive_emphatic"])
CHANNELS = _re(LEX["channels"])
URLS = _re(LEX["urls"])
BENEFITS = _re(LEX["benefits"])
DEADLINE = _re(LEX["deadline"])
ENGAGE_N = _re(LEX["tiers"]["engage"])
CONTACT_N = _re(LEX["tiers"]["contact"])
NAV_N = _re(LEX["tiers"]["navigate"])
COND_ENDING = _re(_cond_pattern(LEX["condition"]["ending"]))
COND_CLAUSE = _re("((?:[^,.!?]*?)" + _cond_pattern(LEX["condition"]["ending"]) + r")\s*[,]?\s*")
COND_HINT = _re(LEX["condition"]["hint"])
CLOSED_ACTIONS_RAW: Tuple[str, ...] = tuple(LEX["closed_actions"])
ACTION_ALIAS: Dict[str, str] = dict(LEX["action_alias"])
CHANNEL_SYNONYMS: Dict[str, str] = dict(LEX["channel_synonyms"])
_EX = LEX["exclusions"]
EX_GREETING = _re(_EX["greeting"])
EX_BLESSING = _re(_EX["blessing_stem"])
EX_PHATIC = _re(_EX["phatic_request"])
EX_REPORTED = _re(_EX["reported"])
EX_WH = _re(_EX["wh_question"])
EX_SYSTEM_END = _re(_EX["system_advisory_end"])
EX_SYSTEM_SUBJECT = _re(_EX["system_subject"])
EX_EXPLANATION = _re(_EX["explanation"])
EX_SOCIETY_END = _re(_EX["society_wish_end"])
EX_SOCIETY_KEEP = tuple(_re(p) for p in _EX["society_wish_keep"])
EX_TRANSCRIPT_MARK = _re(_EX["transcript_mark"])
EX_TRANSCRIPT_REQUEST = _re(_EX["transcript_request"])
EX_ABILITY = _re(_EX["ability_wish"])
EX_MENTAL = _re(_EX["mental_verb"])

# Text hygiene that is not vocabulary: bullets and numbering before a sentence, closing punctuation.
_LEAD = _re(r"^(?:[\s▶▷►☞👉✔✅※■□●○◆◇★☆•·\-–—>▼▽\[\(#*]+|\d{1,2}[.)]\s+)+(?=[가-힣A-Za-z0-9“‘\"'])")
_TRAIL = _re("[\\s.!?~…ㅎㅋㅠㅜ♡♥^)\\]​\"”’'」』:;,]+$")
_PART = _re(r"(?:을|를|은|는)$")
_PART_ANY_END = _re(r"(?:을|를)$")
_VERBAL_END = _re(r"(?:해서|하여서|하시고|하시는|하신|하실|하셔|하시|하여|하고|하며|하면|하는|하기|하자|하라|한\s*뒤|한\s*후|해|하|시고|시는|시|고|며|면|어서|아서|어|아|여)$")
_OPEN_START = _re(r"^[“‘「『]")
_CLOSE_ANY = _re(r"[”’」』]")
_WHOLE_QUOTE = _re(r"^[“‘\"'「『].*[”’\"'」』][.!?]*$")
_NOT_ACTION_TAIL = _re(r"(?:것|수|때|점|등|중|내용|부분|곳|분|번|개)$")
_LIGHT_TOKENS = ("", "해", "하", "하여", "하여서", "해서", "하시어", "하셔", "하시", "보", "보시", "보시길", "보시기",
                 "보셔", "오", "와", "두", "놓", "가", "주")
_CHAIN_SPLIT = _re(r"((?:하시고|하고|하며|하시며|해서|한\s*뒤|한\s*후|하신\s*후|하신\s*뒤|고|며)\s+|(?<=[가-힣])(?:과|와|및)\s+|\s*[,·]\s*)")
_VERBAL_LINK = _re(r"(?:하시고|하고|하며|하시며|해서|한\s*뒤|한\s*후|하신\s*후|하신\s*뒤|고|며)")
_NOMINAL_REQ_HEAD = _re(r"\s*(?:부탁|요청|당부)")
_NOMINAL_REQ_TAIL = _re(r"\s*(?:을|를)?\s*(?:바랍니다|바라요|부탁(?:\s*\S*)?|요청(?:\s*\S*)?|당부(?:\s*\S*)?)$")
_WORDS = _re(r"[가-힣A-Za-z0-9·]+")
_ALNUM_WORDS = _re(r"[가-힣A-Za-z0-9]+")
_SPACES = _re(r"\s+")
_BUTTON_CLOSE = _re(r"[\]\)>]+$")
_TERMINAL = _re(r"[.!?]")
_OBJECT = _re(r"([가-힣A-Za-z0-9·]+?)(?:을|를)(?=\s|$)")
_HONORIFIC = _re(r"시|세요|십시오|드립니다|드려요|바랍니다|실래요|겠습니까")
_COND_OFFER = _re(
    r"[가-힣]{1,8}\s*(?:해\s*)?(?:주|하|해주|드리)(?:시면|신다면|시다면|시는\s*경우)[^.!?]{0,120}?"
    r"(?:하겠습니다|드리겠습니다|드립니다|드릴게요|드리겠어요|안내|답변|도와|상담|연락|확인|검토|알려|회신|돕겠습니다|도와드리|도와\s*드리"
    r"|응답|조언|반영|처리|접수|참고|살펴볼\s*수\s*있|도와드릴\s*수\s*있|수\s*있습니다|수\s*있어요)")
_COND_OFFER_ACTION = _re(
    r"([가-힣\s]{0,24}?(?:문의|연락|상담|전화|댓글|쪽지|톡|메일|의견|질문|말씀|이야기|연락처|신청|예약|방문|남겨|알려|물어|요청|의뢰))")
_BUTTON_TAIL = _re(r"(?:하기|보기|가기|받기)$")
_COLON = _re(r"[:：]")
_LEVELS = (
    ("hapsyo", _re(r"(?:십시오|ㅂ시다|습니다|ㅂ니다|바랍니다|드립니다|하시오|시옵소서|겠습니까|합시다|입니다)$")),
    ("haeyo", _re(r"(?:세요|해요|예요|죠|까요|어요|아요|래요|요)$")),
    ("haera", _re(r"(?:하라|해라|하거라|하렴|자|라|다|렴|거라)$")),
    ("hae", _re(r"(?:줘|봐|해)$")),
)
_QUOTE_MARK = _re("[" + re.escape("".join(T.QUOTE_PAIRS)) + "]")
_JOSA_WS = _re(r"(?:을|를)\s*$")


# ==========================================================================
# result types
# ==========================================================================
@dataclass(frozen=True)
class Hit:
    """What the classifier found in one CTA sentence (the fields of the plan's CtaUnit and a little more)."""

    form: str
    force: int
    tier: str
    polarity: str             # pos | neg
    level: str                # T6 speech level: hapsyo, haeyo, haera, hae, other
    honorific: bool
    action: str               # main action: the last one in the sentence
    actions: Tuple[str, ...]  # every action in order, main one included
    obj: Optional[str]
    condition: Optional[str]
    deadline: Tuple[str, ...]
    channel: Tuple[str, ...]
    benefit: Tuple[str, ...]
    intensity: Tuple[str, ...]
    text: str                 # the classified text: lead stripped, at most MAX_UNIT trailing characters


@dataclass(frozen=True)
class CtaDetail:
    """One ledger unit: the hit plus where it stands. `unit` is the plan's JSON record (types.CtaUnit);
    the gate reads `hit` directly, which keeps a compare on thousands of CTA lines cheap."""

    id: str                   # "C1", "C2", ... in document order
    sentence: str             # id of the sentence unit ("S7")
    index: int                # index of the sentence unit in doc.units
    para: int
    hit: Hit

    @property
    def text(self) -> str:
        return self.hit.text

    @property
    def main_action(self) -> str:
        return self.hit.action

    @property
    def unit(self) -> CtaUnit:
        """The plan record; strings and lists are cut to the limits of schemas/plan.schema.json (cta)."""
        h = self.hit
        return CtaUnit(id=self.id, sentence=self.sentence, form=h.form, force=h.force, tier=h.tier,
                       polarity=h.polarity, action=_short(h.actions), object=_clip(h.obj, 80) if h.obj else None,
                       condition=_clip(h.condition, 200) if h.condition else None, deadline=_short(h.deadline),
                       channel=_short(h.channel), benefit=_short(h.benefit), intensity=_short(h.intensity),
                       level=h.level, hon_si=h.honorific)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _short(items: Tuple[str, ...]) -> List[str]:
    return [_clip(x, 80) for x in items[:40]]


@dataclass(frozen=True)
class DeonticUnit:
    index: int
    key: str                  # first two syllables of the obliged action, "" when unknown
    canon: str                # text without spaces and sentence punctuation


@dataclass
class Ledger:
    ctas: List[CtaDetail]
    deontic: List[DeonticUnit]      # every sentence with a plain obligation form, CTA or not
    offers: List[int]               # indices of service-offer sentences (검토해 드립니다)


# ==========================================================================
# helpers shared with the gate
# ==========================================================================
_CANON_DROP = _re(r"[\s.!?~…]+")
_NON_ALNUM = _re(r"[^가-힣A-Za-z0-9]")
_TRAIL_COMMA = _re(r"[,·]$")


def action_key(action: str) -> str:
    return _NON_ALNUM.sub("", action or "")[:2]


def canon(text: str) -> str:
    """Text without spaces and sentence punctuation (equality of sentences across a rewrite)."""
    return _CANON_DROP.sub("", text or "")


def speech_level(ending: str) -> str:
    for name, rx in _LEVELS:
        if rx.search(ending):
            return name
    return "other"


def norm_action(token: str) -> str:
    """Strip verbal endings from an eojeol and return the nominal or verbal root ("문의해" -> "문의")."""
    t = _TRAIL_COMMA.sub("", token.strip())
    for _ in range(3):
        n = _VERBAL_END.sub("", t)
        if n == t or len(n) == 0:
            break
        t = n
    return _PART.sub("", t) or t


def _tier(text: str) -> str:
    if ENGAGE_N.search(text) and not CONTACT_N.search(text):
        return "engage"
    if CONTACT_N.search(text):
        return "contact"
    if NAV_N.search(text):
        return "navigate"
    return "task"


def _clean_tail(text: str) -> str:
    return _TRAIL.sub("", text)


# ==========================================================================
# classification of one sentence (pure, memoised)
# ==========================================================================
def _quote_count(s: str) -> int:
    return sum(1 for a, b, closed in T.quote_regions(s) if (b - a - (2 if closed else 1)) >= 1)


def _classify_cue(s: str, ms: str, clean: str):
    """(cue, match, clean text, quoted) or None: the first cue that matches the end of the sentence."""
    nq = _quote_count(s) if _QUOTE_MARK.search(s) else 0
    if _OPEN_START.match(s) and not _CLOSE_ANY.search(s):
        return None                       # the quotation continues in the next sentence
    if _WHOLE_QUOTE.match(s.strip()) and nq == 1 and len(clean.replace(T.MASK_CHAR, "")) < 4:
        return None                       # the whole sentence is a quotation
    for cue in CUES:
        m = cue.rx.search(clean)
        if m:
            return cue, m, clean
    if ":" in clean or "：" in clean:      # "다음 서류를 준비하세요: 신분증, 인감도장."
        head = _COLON.split(clean, 1)[0].rstrip()
        for cue in CUES:
            m = cue.rx.search(head)
            if m:
                return cue, m, head
    return None


def _excluded(cue: Cue, clean: str, s: str) -> bool:
    if EX_GREETING.search(clean):
        return True
    if cue.form in ("request", "imperative", "trial") and EX_BLESSING.search(clean[-24:]):
        return True
    if EX_PHATIC.search(clean) or EX_REPORTED.search(clean):
        return True
    if cue.form == "suggestion" and EX_WH.search(clean):
        return True
    if cue.form == "advisory" and EX_SYSTEM_END.search(clean) and EX_SYSTEM_SUBJECT.search(clean):
        return True
    if cue.form == "instruction" and EX_EXPLANATION.search(clean):
        return True
    if cue.form == "request":
        if EX_SOCIETY_END.search(clean) and not any(rx.search(clean) for rx in EX_SOCIETY_KEEP):
            return True
        if EX_TRANSCRIPT_MARK.search(s) and EX_TRANSCRIPT_REQUEST.search(clean):
            return True
        if EX_ABILITY.search(clean):
            return True
    if cue.form == "instruction" and EX_MENTAL.search(clean):
        return True
    return False


def _nominal_button(raw: str, is_line: bool) -> Optional[str]:
    """Button or link line ("▶ 무료 상담 예약하기"); the text without its marks, or None."""
    if not is_line:
        return None
    stripped = raw.strip()
    t = BTN_MARK.sub("", stripped)
    t = _BUTTON_CLOSE.sub("", t).strip()
    if len(t) > 26 or _TERMINAL.search(t):
        return None
    marked = bool(BTN_MARK.match(stripped)) and stripped[:1] in BTN_STRONG_MARKS
    if BTN_NOUN.search(t) and (marked or len(t.split()) <= 3):
        return t
    return None


def _extract(s: str, m: "re.Match[str]") -> Tuple[str, Tuple[str, ...], Optional[str], Optional[str]]:
    """(main action, all actions, object, condition) of a cue match on the cleaned sentence."""
    core = s[:m.start()].rstrip()
    cond, rest = None, core
    cm = COND_CLAUSE.match(core)
    if cm:
        cond = cm.group(1).strip()
        rest = core[cm.end():]
    toks = _WORDS.findall(rest)
    action, obj = "", None
    if toks:
        action = norm_action(toks[-1])
        # "문의를 해 주세요": the last eojeol is only the light verb, the verbal noun stands before it
        if action in _LIGHT_TOKENS and len(toks) >= 2:
            action = norm_action(toks[-2])
    objs = list(_OBJECT.finditer(rest))
    if objs:
        obj = objs[-1].group(1)
    # nominal requests ("협조 바랍니다", "관심 부탁드립니다"): the action is the noun before the cue
    head = s[:m.end()].rstrip()
    pre_full = _NOMINAL_REQ_TAIL.sub("", head)
    cue_text = m.group(0)
    nominal_req = bool(_NOMINAL_REQ_HEAD.match(cue_text) or
                       NOMINAL_ACTION_HEAD.match(cue_text.strip()))
    nm = NOMINAL_ACTION.search(_JOSA_WS.sub("", pre_full))
    if nm and nominal_req and (not action or NOMINAL_ACTION.search(action) is None):
        action = nm.group(0)
    if nominal_req:
        rest = pre_full
    # chained or coordinated actions (문의하시고 신청하세요, 공감과 댓글 부탁드립니다)
    parts = _CHAIN_SPLIT.split(rest)
    pieces = parts[0::2]
    delims = parts[1::2] + [""]
    actions: List[str] = []
    for k, piece in enumerate(pieces):
        w = _ALNUM_WORDS.findall(piece)
        if not w:
            continue
        last_piece = k == len(pieces) - 1
        d = delims[k]
        verbal_link = bool(d) and bool(_VERBAL_LINK.match(d.strip()))
        coord_noun = bool(d) and not verbal_link
        if not (last_piece or verbal_link or (nominal_req and coord_noun)):
            continue
        if not nominal_req and _PART_ANY_END.search(w[-1]):
            continue                      # object of a verbal predicate, not an action
        cand = norm_action(_PART_ANY_END.sub("", w[-1]) if nominal_req else w[-1])
        if cand and len(cand) >= 2 and cand not in _LIGHT_TOKENS and not _NOT_ACTION_TAIL.search(cand):
            actions.append(cand)
    if action and action_key(action) not in {action_key(x) for x in actions}:
        actions.append(action)
    seen, uniq = set(), []
    for x in actions:
        key = action_key(x)
        if key and key not in seen:
            seen.add(key)
            uniq.append(x)
    return action, tuple(uniq), obj, cond


@lru_cache(maxsize=16384)
def _classify(raw: str, s: str, ms: str, is_line: bool) -> Optional[Hit]:
    """CTA hit of one sentence, or None. raw is the unit text (tail), s its lead-stripped form, ms the
    same with quotations masked, is_line whether the unit is a whole line."""
    clean = _clean_tail(ms)
    if not clean:
        return None
    found = _classify_cue(s, ms, clean)
    form, force = "", 0
    m: Optional["re.Match[str]"] = None
    button_text = None
    if found is not None:
        cue, m, clean = found
        if _excluded(cue, clean, s):
            return None
        form, force = cue.form, cue.force
    else:
        button_text = _nominal_button(raw, is_line)
        if button_text:
            form, force = "nominal", 3
        elif COND_HINT.search(clean):
            m = _COND_OFFER.search(clean)
            if m is None:
                return None
            form, force = "conditional_offer", 3
        else:
            return None
    if form == "nominal":
        # the verbal noun of the button: the last word without -하기 ("무료 상담 예약하기" -> 예약)
        last = _BUTTON_TAIL.sub("", button_text.split()[-1]) or button_text
        root = norm_action(last) or last
        action, actions, obj, cond = root, (root,), None, None
    elif form == "conditional_offer":
        cm = _COND_OFFER_ACTION.search(clean)
        act = norm_action(cm.group(1).split()[-1]) if cm else ""
        action, actions, obj, cond = act, ((act,) if act else ()), None, None
    else:
        action, actions, obj, cond = _extract(s, m)
    text = "" if form == "nominal" else s
    intensity: List[str] = []
    if INTENS_NEC.search(text):
        intensity.append("necessity")
    if INTENS_IMM.search(text) and form in ("imperative", "request", "prohibitive", "trial", "conditional_offer"):
        intensity.append("immediacy")
    if form == "prohibitive" and INTENS_PROHIB.search(s) and "necessity" not in intensity:
        intensity.append("necessity")
    f = force
    if intensity and form in ("imperative", "request", "prohibitive"):
        f = min(5, force + 1)
    elif intensity and form in ("trial", "suggestion") and "necessity" in intensity:
        f = min(5, force + 1)
    tail = m.group(0) if m is not None else clean
    return Hit(
        form=form, force=f, tier=_tier(s), polarity="neg" if form == "prohibitive" else "pos",
        level=speech_level(_clean_tail(clean)), honorific=bool(_HONORIFIC.search(tail)),
        action=action, actions=actions, obj=obj, condition=cond,
        deadline=tuple(sorted({x.strip() for x in DEADLINE.findall(s) if x.strip()})),
        channel=tuple(sorted({_SPACES.sub("", x) for x in CHANNELS.findall(s)} | set(URLS.findall(s)))),
        benefit=tuple(sorted(set(BENEFITS.findall(s)))),
        intensity=tuple(sorted(set(intensity))), text=s)


def _deontic_key(ms: str) -> Optional[str]:
    """None when the sentence has no plain obligation form, else the obliged action's key ("" if unknown).
    Memoised for ordinary sentences only: a long run-on must not stay in the cache as a key."""
    return _deontic_cached(ms) if len(ms) <= MAX_UNIT * 2 else _deontic_key_uncached(ms)


@lru_cache(maxsize=16384)
def _deontic_cached(ms: str) -> Optional[str]:
    return _deontic_key_uncached(ms)


def _deontic_key_uncached(ms: str) -> Optional[str]:
    dm = DEONTIC.search(ms)
    if dm is None:
        return None
    # the obliged noun stands right before the obligation phrase; a bounded window keeps the lazy
    # {2,}? in DEON_ACTION linear on a long run of Hangul
    window = ms[max(0, dm.start() - 80):dm.end() + 30]
    am = DEON_ACTION.search(window)
    if not am:
        return ""
    g = am.group(1) or am.group(2) or ""
    words = g.split()
    return action_key(norm_action(words[-1] if words else g))


@lru_cache(maxsize=16384)
def _is_offer(ms: str) -> bool:
    return OFFER.search(_clean_tail(ms)) is not None


def _whole_line(text: str, unit: Unit) -> bool:
    start = text.rfind("\n", 0, unit.start) + 1
    end = text.find("\n", unit.end)
    end = len(text) if end < 0 else end
    return not text[start:unit.start].strip() and not text[unit.end:end].strip()


def analyse(doc: Document) -> Ledger:
    """CTA units, deontic units and service offers of a segmented text."""
    text = doc.text
    masked = T.mask_quotes(text)
    ctas: List[CtaDetail] = []
    deontic: List[DeonticUnit] = []
    offers: List[int] = []
    for index, unit in enumerate(doc.units):
        if unit.kind == "quote":
            continue                      # a whole quotation or a block quote is not the author's call
        raw = unit.text if len(unit.text) <= MAX_UNIT else unit.text[-MAX_UNIT:]
        mfull = masked[unit.start:unit.end]
        mraw = mfull if len(mfull) <= MAX_UNIT else mfull[-MAX_UNIT:]
        lead = _LEAD.match(raw)
        k = lead.end() if lead else 0
        s, ms = raw[k:], mraw[k:]
        is_line = len(raw) <= 60 and BTN_NOUN.search(_BUTTON_CLOSE.sub("", raw.rstrip()).rstrip()) is not None \
            and _whole_line(text, unit)
        hit = _classify(raw, s, ms, is_line)
        key = _deontic_key(mfull)
        if key is not None:
            deontic.append(DeonticUnit(index, key, canon(unit.text)))
        if _is_offer(ms):
            offers.append(index)
        if hit is None:
            continue
        ctas.append(CtaDetail(id=f"C{len(ctas) + 1}", sentence=unit.id, index=index, para=unit.para, hit=hit))
    return Ledger(ctas, deontic, offers)


def detect(doc: Document) -> Tuple[List[CtaUnit], List[Unit]]:
    """(CTA ledger, plain deontic units). The deontic units are the sentences with an obligation form
    (해야 합니다, 필요합니다) that are not CTA units; DESIGN 3.3 tracks them in the meaning ledger."""
    ledger = analyse(doc)
    cta_index = {d.index for d in ledger.ctas}
    return ([d.unit for d in ledger.ctas],
            [doc.units[d.index] for d in ledger.deontic if d.index not in cta_index])


# ==========================================================================
# awkward CTA wording and deterministic repair
# ==========================================================================
_WORDING = [(w, _re(w["pattern"])) for w in LEX["wording"]]
_LGGE = LEX["safe_repair"]["lgge"]
_LGGE_RX = _re(_LGGE["pattern"])


def wording_findings(doc: Document) -> List[Finding]:
    """Wording findings outside quotations and frozen spans. CTA-SP1/SP2 (spacing of 주다) are FIX /
    deterministic with the spaced form in `fix`; CTA-SILGE is LEAVE / report (OD 4: no repair exists);
    CTA-BARAE is SUGGEST / request. Ids are local (F1, F2, ...); the plan builder renumbers them."""
    from . import protect          # late: protect imports engine_runtime/quantities.py (Python >= 3.10)
    masked = T.mask_quotes(doc.text)
    freeze = [(sp.start, sp.end) for sp in protect.protected_spans(doc) if sp.policy == "freeze"]
    out: List[Finding] = []
    for index, unit in enumerate(doc.units):
        if unit.kind in ("quote", "heading"):
            continue
        seg = masked[unit.start:unit.end]
        for item, rx in _WORDING:
            for m in rx.finditer(seg):
                a, b = unit.start + m.start(), unit.start + m.end()
                if any(fa < b and a < fb for fa, fb in freeze):
                    continue
                fix = m.expand(item["repl"]) if item["repl"] is not None else None
                out.append(Finding(id=f"F{len(out) + 1}", rule=item["rule"], tier=item["tier"],
                                   action=item["action"], sentence=unit.id, start=a, end=b, fix=fix))
    return out


def safe_repair(text: str, *, fix_colloquial: bool = False) -> Tuple[str, List[str]]:
    """Deterministic, voice-neutral repairs outside quotations; idempotent.

    cta_spacing_juseyo (CTA-SP1) and cta_spacing_noun_juseyo (CTA-SP2) always; cta_lgge (-ㄹ께요 ->
    -ㄹ게요) only with fix_colloquial (OD 2). There is no -실게요 -> -세요 repair: it changes the
    honorific form (OD 4), so CTA-SILGE stays a report-only finding."""
    masked = T.mask_quotes(text)
    edits: List[Tuple[int, int, str, str]] = []
    for item, rx in _WORDING:
        if item["repl"] is None or item["action"] != "deterministic":
            continue
        for m in rx.finditer(masked):
            edits.append((m.start(), m.end(), m.expand(item["repl"]), item["repair"]))
    if fix_colloquial:
        for m in _LGGE_RX.finditer(masked):
            edits.append((m.start(), m.end(), m.expand(_LGGE["repl"]), _LGGE["repair"]))
    edits.sort()
    pieces: List[str] = []
    applied: List[str] = []
    last = 0
    for a, b, new, code in edits:
        if a < last:
            continue                          # overlapping edit: the first one wins
        pieces.append(text[last:a])
        pieces.append(new)
        last = b
        applied.append(code)
    pieces.append(text[last:])
    return "".join(pieces), applied
