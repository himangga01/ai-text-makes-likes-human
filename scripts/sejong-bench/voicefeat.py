"""Per-sentence voice (말투) features for the independent scorer (WP-15a).

Port of T7_voicefeat.py plus the per-sentence `voice_profile` of T7's seed builder. Owner decision
(4 Oct 2026, OD 1): voice is compared per aligned sentence, never against a document register.
A sentence's features are its speech level, ending class (about 20 classes such as 더라고요 / 거든요 /
잖아요 / 네요 / 죠 / ㄹ게요 / 합쇼 declarative), the honorific multiset (-시-, 께서/께, 님, lexical
honorific verbs), humble forms and first-person markers. Quotations are scored apart from the
narration around them and must stay verbatim.

Backends. Kiwi (kiwipiepy, Apache-2.0) tags -시-, 께서, 님 and first-person pronouns when it is
installed; it is optional and never required. Without it, or with SEJONG_BENCH_KIWI=off, regex
patterns do the same job. The regex honorific pattern is deliberately narrower than Kiwi (it
counts -시- only in forms a regex can separate from a noun); the self-test pins the seed numbers
for both backends so a change to either shows up. The backend name is stored in every metrics
record, and a sealed run should pin one backend.

This module imports no engine code. Standard library only (Kiwi optional).
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from bench_text import QUOTE, segment

CMC = re.compile(r"(?:[ㅎㅋㅠㅜ]{2,}|\^{2,}|\^_\^|~+)")
LEX_HON = re.compile(r"(드세요|드셔|드셨|드십|주무세요|주무셔|주무셨|계세요|계셔|계십|계셨|잡수|말씀하)")
HUMBLE = re.compile(r"(드립니다|드려요|드릴|드렸|드리겠|드리고|드리며|드리는|여쭤|여쭙|여쭈|뵙|저희|저는|제가|제게|저도|저의)")
_FIRST_PERSON_SKIP = ("저는", "제가", "제게", "저도", "저의", "저희")  # persona markers, not humble verbs

# ---- backend selection ------------------------------------------------------------------------
_KIWI: Any = None
_KIWI_NAME = ""
_MODE = "auto"
_MODES = {"auto": "auto", "off": "off", "on": "on", "0": "off", "1": "on"}


@lru_cache(maxsize=1)
def _load_kiwi() -> Tuple[Any, str]:
    """(analyser, "kiwi-<version>") or (None, ""). Built once per process (about 1 s and 580 MB)."""
    try:
        import kiwipiepy  # type: ignore
        return kiwipiepy.Kiwi(), "kiwi-" + str(getattr(kiwipiepy, "__version__", "unknown"))
    except Exception:  # not installed, or its model failed to load
        return None, ""


def set_backend(mode: str) -> str:
    """mode = "auto" (Kiwi if importable), "off" (regex), "on" (Kiwi, ImportError if missing).
    Returns the backend name."""
    global _KIWI, _KIWI_NAME, _MODE
    key = mode.strip().lower()
    if key not in _MODES:
        raise ValueError(f"voice backend mode must be auto, on or off, not {mode!r}")
    mode = _MODES[key]
    kiwi, name = (None, "") if mode == "off" else _load_kiwi()
    if mode == "on" and kiwi is None:
        raise ImportError("kiwipiepy is not available but Kiwi was requested (SEJONG_BENCH_KIWI=on)")
    _MODE, _KIWI, _KIWI_NAME = mode, kiwi, name
    _honorific_cached.cache_clear()
    _persona_cached.cache_clear()
    return backend_name()


def backend_name() -> str:
    """Name of the active backend: "regex" or "kiwi-<version>"."""
    return _KIWI_NAME if _KIWI is not None else "regex"


# ---- ending classes ---------------------------------------------------------------------------
def strip_tail(s: str) -> str:
    """The sentence without trailing closers, terminal punctuation and CMC runs (ㅋㅋ, ㅠㅠ, ^^, ~)."""
    t = s.strip()
    for _ in range(4):
        t = re.sub(r'[\s"“”‘’「」』\)\]]+$', '', t)
        t = re.sub(r'[.?!…]+$', '', t)
        first = CMC.search(t)
        if first and first.end() == len(t):  # a CMC token that ends the sentence (also ^_^)
            t = CMC.sub(lambda m, whole=t: "" if m.end() == len(whole) else m.group(0), t)
        t = re.sub(r'(?:[ㅎㅋㅠㅜ]+|\^+|~+)$', '', t).rstrip()
    return t


ENDINGS = [  # (class, regex on the stripped tail). Order matters: most specific first.
    ("hapsyo_q", r"(습니까|ㅂ니까|[가-힣]니까)$"),
    ("hapsyo_imp", r"(십시오|십시요)$"),
    ("hapsyo_prop", r"(읍시다|습시다|ㅂ시다|[가-힣]시다)$"),
    ("hapsyo_decl", r"(습니다|[가-힣]니다)$"),
    ("haeyo_deolagoyo", r"더라고요$"),
    ("haeyo_geodeunyo", r"거든요$"),
    ("haeyo_janayo", r"잖아요$"),
    ("haeyo_neyo", r"네요$"),
    ("haeyo_gunyo", r"군요$"),
    ("haeyo_jyo", r"(죠|지요)$"),
    ("haeyo_lgeyo", r"[게께]요$"),
    ("haeyo_lkkayo", r"까요$"),
    ("haeyo_ndeyo", r"[는은ㄴ]?데요$"),
    ("haeyo_seyo", r"(세요|셔요)$"),
    ("haeyo_generic", r"요$"),
    ("haera_q", r"(니|냐|는가|ㄴ가|은가|까)$"),
    ("haeche_deola", r"더라$"),
    ("haeche_geoya", r"(거야|건데|거든|잖아)$"),
    ("haera_decl", r"다$"),
    ("haeche_generic", r"[어아야지네게께래대군걸데]$"),
]
_COMPILED = [(name, re.compile(rx)) for name, rx in ENDINGS]
_HAPSYO_TAIL = ("습니다", "습니까", "십시오", "십시요", "읍시다", "습시다")


def level_from_class(c: Optional[str]) -> str:
    if c is None:
        return "other"
    head = c.split("_")[0]
    return {"hapsyo": "hapsyo", "haeyo": "haeyo", "haera": "haera", "haeche": "haeche"}.get(head, "other")


def ending_class(sentence: str) -> Optional[str]:
    t = strip_tail(sentence)
    if not t:
        return None
    if t.endswith("아니다"):
        return "haera_decl"
    for name, rx in _COMPILED:
        if rx.search(t):
            if name.startswith("hapsyo") and not (
                    t.endswith(_HAPSYO_TAIL)
                    or (len(t) >= 3 and "가" <= t[-3] <= "힣" and (ord(t[-3]) - 0xAC00) % 28 == 17)):
                continue  # 아니다 / 하니까 etc. are not 합쇼체
            return name
    if len(t) > 1 and "가" <= t[-1] <= "힣" and (ord(t[-1]) - 0xAC00) % 28 == 0:
        return "haeche_open"  # open-syllable plain ending (와, 봐, 줘, 해 ...)
    return None


# ---- honorific and first-person markers -------------------------------------------------------
def _has_final_rieul(ch: str) -> bool:
    return "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 == 8


# Regex stand-in for Kiwi's EP 시/으시 token. It counts the forms a regex can tell from a noun:
#   -으시-, 시겠, 하셨 / 주셨 / 보셨 ..., 하십니다, 하십시오;
#   an open syllable + 시 + ending (하시면, 주시기, 기다리시고, 하시나요, 두시길), except 마시-
#   (마시다) and the lexical honorific verbs 드시-, 계시- (counted once as "lexical" via LEX_HON);
#   a stem 하·주·보·가·오·두·아·되·리·이 + 시는 / 시지 / 셔, + 신 or 실 at the end of the eojeol
#   or before a short ending (문의하신 분, 하신다면, 확인하실 때, 하실게요, 교수님이신); 으 + 신·실·셔.
# It leaves out -세요 / -셔요 (Kiwi tags them as one ending; the ending class carries them) and
# stems not listed (a verb outside them with an embedded -시- before 는/ㄴ/ㄹ is missed, and a city
# such as 충주시는 reads as honorific): the regex backend is an approximation, Kiwi is the reference.
_OPEN_SYLLABLE = "".join(chr(0xAC00 + 28 * k) for k in range(19 * 21))
_SI_REGEX = re.compile(
    r"(?<![드계])(?:셨|십니[다까]|십시[오요])"
    r"|으시|시겠"
    rf"|(?<=[{_OPEN_SYLLABLE}])(?<![드계마])시(?=면|며|고|기|길|던|도록|다|오|려|니|나|거)"
    r"|(?<=[하주보가오두아되리니이])시(?:는|지)"
    r"|(?<=[하주보가오두아되리이])셔"
    r"|(?<=[하주보가오두아되리이])신(?=$|[^가-힣]|다|데|가|지)"
    r"|(?<=[하주보가오두아되이])실(?=$|[^가-힣]|게|까|래|거|텐|수|때)"
    r"|(?<=으)(?:신|실|셔)")


def _regex_kkeseo(sentence: str) -> int:
    """Count honorific 께서 / 께. A bare 께 is not counted right after a syllable with final ㄹ (the
    colloquial future ending 할께, 갈께요: correcting 할께 to 할게 must not read as a lost honorific;
    the T7 fallback counted it) nor inside the adverb 함께, the noun 두께 and time approximations
    (7시께, 중순께). 학부모님들께 keeps its particle: 들 is the plural suffix there."""
    count = 0
    for m in re.finditer(r"께서?", sentence):
        before = sentence[m.start() - 1] if m.start() > 0 else ""
        if m.group(0) == "께" and before and before != "들" and (_has_final_rieul(before) or before in "함두시초순월년"):
            continue
        count += 1
    return count


@lru_cache(maxsize=65536)
def _honorific_cached(sentence: str, backend: str) -> tuple:
    marks: List[str] = []
    if _KIWI is not None:
        for t in _KIWI.tokenize(sentence):
            if t.tag == "EP" and t.form in ("시", "으시"):
                marks.append("si")
            elif t.form in ("께서", "께") and t.tag.startswith("J"):
                marks.append("kkeseo")
            elif t.tag == "XSN" and t.form == "님":
                marks.append("nim")
    else:
        marks += ["si"] * len(_SI_REGEX.findall(sentence))
        marks += ["kkeseo"] * _regex_kkeseo(sentence)
        marks += ["nim"] * sentence.count("님")
    marks += ["lexical"] * len(LEX_HON.findall(sentence))
    return tuple(sorted(marks))


def honorific_markers(sentence: str) -> List[str]:
    """Multiset (sorted list) of honorific markers: -시- count matters, so losing one of two is a change."""
    return list(_honorific_cached(sentence, backend_name()))


def humble_markers(sentence: str) -> FrozenSet[str]:
    return frozenset(m.group(0) for m in HUMBLE.finditer(sentence) if m.group(0) not in _FIRST_PERSON_SKIP)


# Regex stand-in for Kiwi's first-person NP tags: whole eojeol (punctuation stripped) -> lemma, as
# Kiwi reports it (제가 -> 저, 내 -> 나). A bare 저 is left out (it is also the demonstrative 저 "that").
_PERSONA_FORMS = {}
for _lemma, _forms in (
        ("저", "저는 저도 저만 저를 저의 저에게 저에게는 저에게도 저한테 제가 제게 제게는 제"),
        ("나", "나 나는 나도 나만 나를 나의 나에게 나에게는 나에게도 나한테 내가 내게 내게는 내"),
        ("우리", "우리 우리는 우리가 우리의 우리를 우리도 우리에게"),
        ("저희", "저희 저희는 저희가 저희의 저희를 저희도 저희에게"),
        ("필자", "필자 필자는 필자가 필자의 필자를")):
    for _form in _forms.split():
        _PERSONA_FORMS[_form] = _lemma
_EDGE_PUNCT = re.compile(r'^[\s"“”‘’「」『』\(\)\[\],.?!…~]+|[\s"“”‘’「」『』\(\)\[\],.?!…~]+$')


@lru_cache(maxsize=65536)
def _persona_cached(sentence: str, backend: str) -> frozenset:
    out = set()
    if _KIWI is not None:
        for t in _KIWI.tokenize(sentence):
            if t.tag == "NP" and t.form in ("저", "나", "우리", "저희", "내"):
                out.add(t.form if t.form != "내" else "나")
            elif t.tag == "NNG" and t.form == "필자":
                out.add("필자")
    else:
        for word in sentence.split():
            lemma = _PERSONA_FORMS.get(_EDGE_PUNCT.sub("", word))
            if lemma:
                out.add(lemma)
    return frozenset(out)


def persona_markers(sentence: str) -> FrozenSet[str]:
    return _persona_cached(sentence, backend_name())


def features(sentence_narration: str) -> Dict[str, Any]:
    c = ending_class(sentence_narration)
    return {"level": level_from_class(c), "ending": c, "honorific": honorific_markers(sentence_narration),
            "humble": sorted(humble_markers(sentence_narration)), "persona": sorted(persona_markers(sentence_narration))}


def diff_features(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    return [k for k in ("level", "ending", "honorific", "humble", "persona") if a[k] != b[k]]


# ---- per-sentence profile ---------------------------------------------------------------------
_NO_FEATURES = {"level": "nominal", "ending": None, "honorific": [], "humble": [], "persona": []}


def voice_profile(text: str) -> List[Dict[str, Any]]:
    """Per-sentence voice features. Boundaries fall only outside quotations; quotations are scored
    apart from the narration (the narration is the sentence with its quotations cut out)."""
    sents = []
    for idx, (a, b, kind) in enumerate(segment(text)):
        seg = text[a:b]
        qs = [(m.start(), m.end()) for m in QUOTE.finditer(seg)]
        narration = QUOTE.sub("", seg)
        if kind in ("heading", "list"):
            feat = dict(_NO_FEATURES)
        elif narration.strip(" .?!…"):
            feat = features(narration)
        else:
            feat = {"level": "quote_only", "ending": None, "honorific": [], "humble": [], "persona": []}
        quotes = []
        for x, y in qs:
            qf = features(seg[x + 1:y - 1])
            quotes.append({"span": [a + x, a + y], "features": qf, "level": qf["level"]})
        sents.append({"i": idx, "span": [a, b], "kind": kind, "level": feat["level"], "features": feat, "quotes": quotes})
    return sents


set_backend(os.environ.get("SEJONG_BENCH_KIWI") or "auto")
