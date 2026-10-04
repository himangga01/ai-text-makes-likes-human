"""Per-sentence voice signature (말투) of Super Sejong Engine v2 (DESIGN.md 3.3, 3.5).

    signature(sentence, kind="body") -> VoiceSig
    profile(doc)                     -> {"dominant", "share", "mixed", "line"}   (types.Profile shape)
    sheet_line(unit, sig)            -> "S7 해요체·명령·시 「확인하세요」 keep:[~]"
    features(sentence, kind="body")  -> Features   (the signature plus the extra values the gate compares)

Port of the T2 regex backend (docs/research/super-sejong/v2/prototypes/T2_voice.py, T2_gate.stance):
blind holdout accuracy 0.964, equal to Kiwi [T2 §2]. The level classifier reads the final eojeol
of the sentence after quotations are masked:

  HAPSYO   -(스)ㅂ니다/ㅂ니까, -십시오, -답니다 ...        HAEYO   -요/-죠 (not 필요, 중요 ...)
  HAERA    -다, -는가, -구나, -냐, -어라, -자 ...          HAE     -어, -지, -네, -ㄹ게, -거든 ...
  HAO      -오/-소, -구려, -ㅂ시다 (NIKL: 하오체 청유)      HAGE    -네/-는가 with 자네 context, -구먼 ...
  NOMINAL  -음/-기, bare noun, number (개조식)               NONE    connective, comma continuation, particle

Changes against the prototype, each tested in tests/skills/test_sejong_voice.py:
  - quotations are found with text.quote_regions (the WP-1 rule shared with protect.py) and
    replaced by the token 인용, so the classifier sees the narration, as T2's mask_quotes did; a
    sentence that is one quotation is classified by its content;
  - CMC tokens, 할께-family spellings and sentence-initial discourse markers come from
    protect.keep_tokens (one definition for the whole engine); the intensifiers 진짜/완전/대박/솔직히
    count anywhere in the sentence (T2 DISCOURSE_ANY_RE), which protect.py does not cover;
  - cute codas (알겠습니당, 좋아용~, 봤어여) are normalised before the level is read when
    protect.py marks the ending as a colloquial spelling, so 봤어여 is 해요체, not 해체;
  - si_count counts every honorific -시- (lead decision 9.2a item 3): T2's counter plus -시죠,
    -시네요, -시니, -시나요 ..., adnominal -실 before 수/것/거/때/분 ... and -실게요/-실까요; the
    syllable before -시- must be open (증시, 택시, 임신, 오십 명 never count), and nouns and
    loanwords that still match (당시, 반드시, 메시지, 사실 ...) are listed in the lexicon. hon_si
    (final predicate, T2's last-one-or-two-eojeol rule) uses the same counter, which drops T2's
    false -시- in 봅시다 and 마셨다;
  - a clause closed by ^^ or ~ inside one unit (문의해 주세요^^ 제가 …) keeps its own (level, mood)
    in Features.inner, because the WP-1 splitter does not cut there;
  - the gate also compares what the main-branch lock compares (direct-text-fidelity.ts): the
    number of humble forms, raw CMC runs (ㅋㅋㅋ vs ㅋㅋ), request endings (바랍니다) and a final '?';
    plus honorific address nouns and datives (학부모님, 학부모님들께);
  - final-word analysis is limited to the last 400 characters, so a 100k run-on stays linear.

Lexicon (word lists, stems, honorific nouns, stance families, labels): data/voice_lexicon.json.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import protect
from . import text as T
from .types import Document, Unit, VoiceSig

LEXICON_PATH = Path(__file__).resolve().parent / "data" / "voice_lexicon.json"
LEX = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))

HAPSYO, HAEYO, HAERA, HAE, HAO, HAGE, NOMINAL, NONE = (
    "HAPSYO", "HAEYO", "HAERA", "HAE", "HAO", "HAGE", "NOMINAL", "NONE")
LEVELS = (HAPSYO, HAEYO, HAERA, HAE, HAO, HAGE, NOMINAL, NONE)
FINITE = (HAPSYO, HAEYO, HAERA, HAE, HAO, HAGE)
DECL, INTERR, IMPER, PROPOS, EXCL = "DECL", "INTERR", "IMPER", "PROPOS", "EXCL"
QUOTE_TOKEN = "인용"
TAIL_WINDOW = 400            # characters the final-word analysis looks at

_LV = LEX["levels"]
_NOUN_YO = tuple(_LV["noun_yo"])
_KIN_NI = tuple(_LV["kin_ni"])
_NOUN_JA = tuple(_LV["noun_ja"])
_PROPOS_STEM = re.compile(_LV["propos_stem"])
_HAO_SO = re.compile(_LV["hao_so"])
_HAO_O = re.compile(_LV["hao_o"])
_HAGE_CTX = re.compile(_LV["hage_context"])
_HAGE_ENDINGS = tuple(_LV["hage_endings"])
_HAE_BARE = frozenset(_LV["hae_bare"])
_HAE_BARE_SUFFIX = tuple(_LV["hae_bare_suffix"])
_HAE_EO_NOT = tuple(_LV["hae_eo_not"])
_HAE_YA_NOT = tuple(_LV["hae_ya_not"])
_HAE_NE_NOT = tuple(_LV["hae_ne_not"])
_HAE_DAE_NOT = tuple(_LV["hae_dae_not"])
_CUTE = dict(LEX["cute_coda"])
_CUTE_COLLOQ = dict(LEX["cute_coda_colloquial"])
STANCE: Tuple[Tuple[str, str], ...] = tuple((suffix, family) for suffix, family in LEX["stance"])
STANCE_LABEL: Dict[str, str] = dict(LEX["stance_label"])
_HON = LEX["honorific"]
_SI_NOUN = re.compile(_HON["si_noun"])
_HON_NOUN = re.compile(_HON["hon_noun"])
# The honorific dative 께 (학부모님들께, 어른께); not 께서 (counted by si_count), not the 할께 spelling
# (a ㄹ-final syllable other than 들 before it), not the time suffix 께 (15일께, 초께) and not 함께.
_HON_DATIVE = re.compile(r"(?<=[가-힣])(?<!함)께(?=[는도만]?(?:\s|$|[,.!?]))")     # not 함께 (together)
_TIME_GGE = frozenset("달날말일월초순시년")                                     # 15일께, 다음 주 초께
# Every honorific -시- in a predicate, one match per -시- (quotes masked, nouns removed first). The
# syllable before it never has a final consonant: vowel stems take -시- (하시, 주시), consonant stems
# -으시- (받으시), ㄹ stems drop the ㄹ (아시, 만드시), so 증시, 공시, 택시, 임신, 회복시기 never count;
# a 시 after a ㅂ coda is the propositive -ㅂ시다 (봅시다) or the 시 of 십시오. Counted forms:
#   시 before an ending syllable, 셨, 셔 before 서/야/요/도/라 (not 럭셔리, 인터내셔널), 세요, 십 before
#   니/시, adnominal 신 (궁금하신 점, 가신다), 실 before 게/께/래/까/걸/테 (not 회의실까지) or before a bound
#   noun (하실 수, 오실 때), and the lexical honorifics 계시다, 드시다, 주무시다 and the particle 께서.
_OPEN_SYLLABLE = "".join(chr(0xAC00 + 28 * k) for k in range(399))
_SI_ANY = re.compile(
    r"(?<=[" + _OPEN_SYLLABLE + r"])(?:시(?=[는고면며기지어겠었다니네오죠라나던든잖거길게]|$)|셨|셔(?=[서야요도라])"
    r"|세요|십(?=[니시])|신(?=\s|$|[가건데지다대걸게겐])|실(?=[게께래걸테텐]|까(?!지))"
    r"|실(?=\s+(?:(?:수|것|분|줄|리|뿐|만큼|텐데|때|경우|예정|계획|곳)(?:[이가은는을를도만에의]|에는|에도|들)?(?![가-힣])"
    r"|거|건|겁)))"
    r"|" + _HON["si_lexical"])
_PERSONA = {key: re.compile(rx) for key, rx in LEX["persona"].items()}
FIRST_PERSONS = ("first_humble", "first_plain", "first_we")
_ADDRESSEE = re.compile(r"(?<![가-힣])(?:" + "|".join(map(re.escape, LEX["addressee"])) + ")")
_HUMBLE = re.compile("|".join(map(re.escape, LEX["humble"])))
_INTENSIFIER = re.compile(r"(?<![가-힣])(?:" + "|".join(map(re.escape, LEX["intensifiers"])) + r")(?=[\s,.!?~]|$)")
_DIRECTIVE = tuple(LEX["directive_endings"])
UPSHIFT = re.compile(LEX["upshift"])
# A double passive folded before up-shift forms are counted: 변경되어졌습니다 -> 변경되었습니다 is the
# SSB-A04 norm fix, not a 했 -> 하였 up-shift.
_FOLD = tuple((a, b) for a, b in LEX["double_passive_fold"])
LEVEL_KO: Dict[str, str] = LEX["labels"]["level"]
LEVEL_SHORT: Dict[str, str] = LEX["labels"]["level_short"]
MOOD_KO: Dict[str, str] = LEX["labels"]["mood"]
MOOD_USE: Dict[str, str] = LEX["labels"]["mood_use"]

# Trailing material after the final eojeol (T2 TRAIL_RE): spaces, punctuation, closing marks,
# laughter/crying jamo, emoji, emoticons.
_TRAIL = re.compile(r"(?:\s|[.!?。…~～,;:\"”’'」』)\]）】>*\-_=+/\\|♡♥★☆^]|ㅎ|ㅋ|ㅠ|ㅜ|;|\(웃음\)|\(\^\^\)|"
                    r"[\U0001F300-\U0001FAFF☀-➿]|[:;]-?[)(DP])+$")
_CITATION = re.compile(r"\s*[(（][^()（）]{0,80}[)）][.!?。…~]*$")
_NON_WORD_TAIL = re.compile(r"[^가-힣A-Za-z0-9%]+$")
_INTERJECTION_TAIL = re.compile(r"\s+(?:ㅎ+|ㅋ+|ㅠ+|ㅜ+|허허+|하하+|호호+|헤헤+|글쎄|참|뭐)$")
_LAST_WORD = re.compile(r"([가-힣A-Za-z0-9%]+)$")
_TERMINAL = re.compile(r"\s*([.!?。！？…]+)")
_HEADING_MARK = re.compile(r"^\s*#{1,6}\s*")
_BLOCKQUOTE_MARK = re.compile(r"^\s*>+\s?")
_CONNECTIVE_END = re.compile(
    r"(?:고|며|면|서|해서|하여|지만|는데|면서|도록|려고|으나|니|거나|든지|든가|자마자|듯|게|지|ㄴ지|는지|을지|ㄹ지|이나|나|로"
    r"|으로|에|에서|에게|을|를|이|가|은|는|와|과|도|만|의|및|등)$")
# A clause that ends in ^^ or ~ before the next word stays inside one WP-1 unit ("문의해 주세요^^ 제가
# 확인해 드릴게요~", T7 seed convention); its ending is read separately so it stays locked too.
_INNER_END = re.compile(r"(?<=[가-힣])[ \t]*(?:\^\^;*|\^_\^|[~～]+)(?=[ \t]+[가-힣\"“‘'(])")
# Raw CMC marks as the main-branch voice lock reads them (direct-text-fidelity.ts voiceSignature):
# jamo runs including a single ㅋ/ㅎ, ^^ and tilde runs; a range tilde (3~5) is not a mark.
_RAW_MARKS = re.compile(r"[ㅋㅎㅠㅜ]+|\^\^|(?<![\d])[~～]+(?![\d])")


def jong(ch: str) -> int:
    """Final-consonant index of a precomposed Hangul syllable (0 none, 4 ㄴ, 8 ㄹ, 16 ㅁ, 17 ㅂ, 20 ㅆ)."""
    code = ord(ch) - 0xAC00
    return code % 28 if 0 <= code < 11172 else -1


def is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


# --------------------------------------------------------------------------
# quotations
# --------------------------------------------------------------------------
def quotes(sentence: str) -> List[str]:
    """Contents of the quotations in a sentence (closed ones; an unclosed opener runs to the end)."""
    out = []
    for start, end, closed in T.quote_regions(sentence):
        out.append(sentence[start + 1:end - 1] if closed else sentence[start + 1:end])
    return out


def whole_quote(sentence: str) -> Optional[str]:
    """Content of the quotation when the sentence is nothing but one quotation (plus trailing
    punctuation or CMC), else None."""
    regions = T.quote_regions(sentence)
    if len(regions) != 1:
        return None
    start, end, closed = regions[0]
    if not closed or sentence[:start].strip():
        return None
    rest = sentence[end:]
    if len(rest) > TAIL_WINDOW:
        return None
    if rest.strip() and _TRAIL.sub("", rest).strip():
        return None
    return sentence[start + 1:end - 1]


def mask_quotes(sentence: str) -> str:
    """The sentence with every quotation replaced by 인용 (T2 mask_quotes), or the quotation's
    content when the sentence is one quotation."""
    inner = whole_quote(sentence)
    if inner is not None:
        return inner
    regions = T.quote_regions(sentence)
    if not regions:
        return sentence
    pieces, last = [], 0
    for start, end, _ in regions:
        pieces.append(sentence[last:start])
        pieces.append(QUOTE_TOKEN)
        last = end
    pieces.append(sentence[last:])
    return "".join(pieces)


def strip_marker(sentence: str, kind: str) -> str:
    """Line markers removed from a heading, list or block-quote line (## …, - …, 1. …, > …)."""
    if kind == "heading":
        return _HEADING_MARK.sub("", sentence)
    if kind == "list":
        return T.LIST_MARKER.sub("", sentence, count=1)
    if kind == "quote":
        return _BLOCKQUOTE_MARK.sub("", sentence)
    return sentence


# --------------------------------------------------------------------------
# final eojeol and level (T2 regex backend)
# --------------------------------------------------------------------------
@dataclass
class _Final:
    word: str          # final eojeol used for classification (cute codas normalised)
    raw: str           # final eojeol as written
    tail: str          # characters after it (punctuation, CMC, closing marks)


def _final(masked: str, keep: Counter) -> _Final:
    s = masked.strip()[-TAIL_WINDOW:]
    core = s
    while True:
        prev = core
        core = _CITATION.sub("", core)            # (행정심판법 제27조), (웃음), kaomoji
        core = _TRAIL.sub("", core)
        core = _NON_WORD_TAIL.sub("", core)
        core = _INTERJECTION_TAIL.sub("", core)   # trailing laughter or interjection
        if core == prev:
            break
    tail = s[len(core):]
    m = _LAST_WORD.search(core)
    raw = m.group(1) if m else ""
    word = raw
    if len(word) >= 2:
        colloquial = any(kind == "colloquial" and word.endswith(token) for kind, token in keep)
        if word[-1] in _CUTE and (colloquial or any(kind == "cmc" for kind, _ in keep)):
            word = word[:-1] + _CUTE[word[-1]]
        elif colloquial and word[-1] in _CUTE_COLLOQ:
            word = word[:-1] + _CUTE_COLLOQ[word[-1]]
    return _Final(word, raw, tail)


def _level(sentence: str, fin: _Final) -> Tuple[str, str]:
    """(level, ending label) from the final eojeol; a line of T2 regex_level per rule."""
    w, tail = fin.word, fin.tail
    if sentence.rstrip().endswith((",", "，")):
        return NONE, "comma-continuation"
    if not w or not is_hangul(w[-1]):
        if w and re.search(r"[0-9A-Za-z%]$", w):
            return NOMINAL, "non-hangul"
        return NONE, ""
    # HAPSYO: -(스)ㅂ니다 / -(스)ㅂ니까 / -십시오 / -답니다
    if len(w) >= 3 and w[-2:] in ("니다", "니까") and (jong(w[-3]) == 17 or w[-3] in "습읍"):
        return HAPSYO, ("답니다" if w.endswith(("답니다", "랍니다", "냅니다", "잡니다")) else "ㅂ니" + w[-1])
    if w.endswith(("십시오", "십시요", "옵소서", "나이다", "나이까", "십시다")):
        return HAPSYO, w[-3:]
    if len(w) >= 3 and w.endswith("시다") and jong(w[-3]) == 17:          # 갑시다 / 합시다 (NIKL: 하오체 청유)
        return HAO, "ㅂ시다"
    # HAEYO
    if w.endswith(("요", "죠")) and not w.endswith(_NOUN_YO):
        for e in ("더라고요", "거든요", "잖아요", "는데요", "던데요", "네요", "군요", "걸요", "게요", "래요", "대요",
                  "나요", "까요", "지요", "세요", "셔요", "예요", "에요", "고요", "어요", "아요", "여요", "해요", "워요",
                  "와요", "줘요", "봐요"):
            if w.endswith(e):
                return HAEYO, e
        return HAEYO, w[-1]
    # HAO
    if w.endswith("시오") or w.endswith("구려") or _HAO_SO.search(w) or (len(w) >= 2 and _HAO_O.search(w)):
        return HAO, w[-2:]
    # HAGE
    if w.endswith(_HAGE_ENDINGS):
        return HAGE, w[-2:]
    if w.endswith("게") and len(w) >= 2 and jong(w[-2]) != 8 and re.search(r"(?:오|가|하|보|주|앉|들|먹|쉬|오시|두)게$", w) \
            and "!" not in tail and "자네" in sentence:
        return HAGE, "게"
    if w.endswith(("는가", "ㄴ가", "던가")) or (len(w) >= 2 and w.endswith("가") and jong(w[-2]) == 4 and "?" in tail):
        return (HAGE if _HAGE_CTX.search(sentence) else HAERA), "는가"
    # HAERA
    if w.endswith("다"):
        if w.endswith(("는다", "었다", "았다", "였다", "했다", "겠다", "이다", "한다", "된다", "있다", "없다", "않다", "같다",
                       "싶다", "렵다", "롭다", "스럽다")):
            return HAERA, w[-2:]
        if w in ("바다", "사다", "마다") or w.endswith(("보다", "마다", "부터다")):
            return (NOMINAL if w.endswith("마다") else HAERA), "다"
        return HAERA, "다"
    if w.endswith(("구나", "로구나", "는구나", "더라", "도다", "노라", "느냐", "으냐", "려무나", "렴")):
        return HAERA, w[-2:]
    if w.endswith("냐") or (w.endswith("니") and "?" in tail and not w.endswith(_KIN_NI)) or w.endswith(("으랴", "ㄹ쏘냐")):
        return HAERA, w[-1]
    if w.endswith(("어라", "아라", "거라", "너라", "여라", "해라", "하라", "봐라", "줘라", "와라", "워라")):
        return HAERA, "어라"
    if w.endswith("자") and not w.endswith(_NOUN_JA) and _PROPOS_STEM.search(w):
        return HAERA, "자"
    # HAE (해체 / 반말)
    if w.endswith(("니깐", "라니까", "다니까", "라니깐")):
        return HAE, "니까"
    if w.endswith(("는지", "은지", "을지", "던지")) and "?" in tail:
        return HAE, "는지"
    if w in _HAE_BARE or w.endswith(_HAE_BARE_SUFFIX):
        return HAE, "어"
    for e in ("더라고", "거든", "잖아", "는데", "던데", "은데", "을걸", "는걸", "을게", "을래", "을까", "군", "니까"):
        if w.endswith(e):
            if e == "니까" and len(w) >= 3 and jong(w[-3]) == 17:
                break
            return HAE, e
    if len(w) >= 2 and w[-1] in "게께래까걸" and jong(w[-2]) == 8:            # 할게, 할께, 갈래, 할까, 할걸
        return HAE, "ㄹ" + w[-1]
    if len(w) >= 2 and w.endswith("네") and not w.endswith(_HAE_NE_NOT):
        return HAE, "네"
    if len(w) >= 2 and w.endswith("대") and (jong(w[-2]) == 4 or w[-2] in "했였었았이") and not w.endswith(_HAE_DAE_NOT):
        return HAE, "대"
    if w.endswith(("었지", "았지", "였지", "겠지", "했지", "됐지", "하지", "되지", "있지", "없지", "않지", "같지", "좋지",
                   "맞지", "그렇지", "이지", "거지", "그치", "알지", "봤지", "거야", "이야", "잖니")):
        return HAE, w[-1]
    if len(w) >= 2 and w.endswith("지") and jong(w[-2]) == 20:               # 렸지, 겠지, 했지
        return HAE, "지"
    if w.endswith("나") and "?" in tail and len(w) >= 2:
        return HAE, "나"
    if len(w) >= 2 and w[-1] in "어아여해워와줘봐돼봬셔져쳐펴켜려써" and not w.endswith(_HAE_EO_NOT):
        return HAE, "어"
    if w.endswith("야") and len(w) >= 2 and (jong(w[-2]) == 0 or w[-2] == "이") and not w.endswith(_HAE_YA_NOT):
        return HAE, "야"
    # NOMINAL (명사형·개조식) vs NONE (connective / fragment)
    if (jong(w[-1]) == 16 and len(w) >= 2) or w.endswith(("음", "기", "것", "중", "예정", "필요", "가능", "불가", "완료", "기준")):
        return NOMINAL, "ㅁ/기/명사"
    if _CONNECTIVE_END.search(w):
        return NONE, "connective/particle"
    return NOMINAL, "명사"


def _mood(fin: _Final, level: str, ending: str) -> str:
    """Sentence type (T2 mood_of). Non-finite sentences are INTERR with a final '?', else DECL."""
    w, tail = fin.word, fin.tail
    if level not in FINITE:
        return INTERR if "?" in tail else DECL
    if w in ("안녕하세요", "안녕하십니까", "안녕하시오", "안녕하신가", "안녕하셨어요", "안녕하셨습니까"):
        return INTERR if "?" in tail else DECL
    if "?" in tail or w.endswith(("니까", "나요", "까요", "가요", "는지요", "을까", "할까", "냐", "느냐", "는가", "ㄴ가", "던가")) \
            or ending in ("냐", "느냐", "ㄹ까", "ㄹ까요", "을까요", "나요", "는가", "니"):
        return INTERR
    if w.endswith(("십시오", "시오", "어라", "아라", "거라", "너라", "여라", "해라", "하라", "세요", "셔요", "십시요")):
        if w.endswith(("세요", "셔요")) and re.search(r"(?:이세요|계세요|으세요\?|분이세요|하시네요)$", w):
            return DECL
        if w.endswith(("세요", "셔요")) and re.search(
                r"(?:친절하|바쁘|좋으|크|젊으|예쁘|많으|높으|멋지|훌륭하|대단하|아프|편찮으|이|이시|분이)(?:세요|셔요)$", w):
            return DECL
        return IMPER
    if w.endswith(("마오", "마시오", "마십시오")):
        return IMPER
    if w.endswith(("ㅂ시다", "십시다", "하자", "보자", "가자", "읍시다")) or ending in ("자", "ㅂ시다", "십시다") \
            or (len(w) >= 3 and w.endswith("시다") and jong(w[-3]) == 17):
        return PROPOS
    if w.endswith(("구나", "군요", "군", "구먼", "도다", "네요", "구려")) and "!" in tail:
        return EXCL
    return DECL


def _stance(fin: _Final, level: str) -> Optional[str]:
    """Stance family of the final ending (T2 gate.stance): evidential, reason, shared, discovery,
    teaching, hearsay, confirm, background, promise, counter; None for a plain ending."""
    w = fin.word
    if len(w) >= 2 and w[-1] in "게께" and jong(w[-2]) == 8:
        return "promise"
    if w.endswith("지") and len(w) >= 2 and jong(w[-2]) in (20, 0) and not w.endswith(("까지", "부터지")):
        return "confirm" if level == HAE else None
    if w.endswith("바랍니다"):
        return None
    for suffix, family in STANCE:
        if w.endswith(suffix):
            return family
    return None


def _hon_si_final(masked: str) -> bool:
    """-시- in the final predicate complex: the last eojeol, or the last two when the last one is
    a bound or auxiliary word (것, 싶다, 있다 ...), as T2 regex_hon_si; the -시- itself is found
    with the same counter as si_count (T2's own pattern also read 봅시다 and 마셨다 as -시-)."""
    words = re.sub(r"[^가-힣\s]+", " ", masked[-TAIL_WINDOW:]).split()
    if not words:
        return False
    tail = words[-1]
    if len(words) >= 2 and re.match(r"(?:것|거|건|겁|게|겐|싶|있|않|없|같)", words[-1]):
        tail = words[-2] + " " + words[-1]
    return si_count(tail) > 0


def si_count(masked: str) -> int:
    """Honorific -시- anywhere in the sentence (quotes already masked), lexical honorifics and
    께서 included; nouns that end in 시/신/실 and numerals are not counted."""
    return len(_SI_ANY.findall(_si_text(masked)))


def _si_text(masked: str) -> str:
    """Hangul and whitespace only, nouns blanked, same length as `masked` (offsets stay valid)."""
    t = re.sub(r"[^가-힣\s]", " ", masked)
    return _SI_NOUN.sub(lambda m: " " * len(m.group(0)), t)


def si_spans(masked: str) -> List[str]:
    """The eojeols that carry a counted -시- (diagnostics and tests)."""
    t = _si_text(masked)
    out = []
    for m in _SI_ANY.finditer(t):
        a = t.rfind(" ", 0, m.start()) + 1
        b = t.find(" ", m.end())
        out.append(masked[a:b if b >= 0 else len(t)])
    return out


# --------------------------------------------------------------------------
# signature
# --------------------------------------------------------------------------
@dataclass
class Features:
    sig: VoiceSig
    ending: str                    # classifier ending label (ㅂ니다, 어요, 세요, ...)
    stance_family: Optional[str]   # gate value; sig.stance is its display form
    question: bool                 # final '?' (also for non-finite sentences)
    directive: bool                # request by ending: 바랍니다, 부탁드립니다 ...
    humble_count: int
    hon_nouns: int                 # 고객님, 학부모님 ... and the dative 께 (honorific address)
    keep: Counter                  # protect.keep_tokens + intensifiers: {(kind, token): n}
    marks: Counter                 # raw CMC marks as the main-branch lock reads them
    upshift: int                   # 하였/되었/하여 ... forms
    quote_levels: Tuple[str, ...]  # level inside each quotation (non-whole-quote sentences)
    inner: Tuple[Tuple[str, str], ...] = ()   # (level, mood) of clauses closed by ^^ or ~ inside the unit


def features(sentence: str, kind: str = "body") -> Features:
    """Signature and gate features of one sentence (unit text)."""
    body = strip_marker(sentence, kind)
    keep = protect.keep_tokens(body)
    masked = mask_quotes(body)
    lead = len(masked) - len(masked.lstrip(" \t\"“‘'("))
    for m in _INTENSIFIER.finditer(masked):
        if m.start() == lead and keep.get(("discourse", m.group(0))):
            continue                       # already the sentence-initial discourse marker
        keep[("discourse", m.group(0))] += 1
    fin = _final(masked, keep)
    level, ending = _level(masked, fin)
    mood = _mood(fin, level, ending)
    family = _stance(fin, level) if level in FINITE else None
    hon_si = level in FINITE and _hon_si_final(masked)
    count = si_count(masked)
    stance = STANCE_LABEL.get(family) if family else ("ㅂ니다" if ending.startswith("ㅂ니") else None)
    persona = sorted(key for key, rx in _PERSONA.items() if rx.search(masked))
    addressee = _ADDRESSEE.search(masked)
    humble = len(_HUMBLE.findall(masked))
    cmc = [token for (k, token), n in keep.items() if k in ("cmc", "colloquial") for _ in range(n)]
    discourse = [token for (k, token), n in keep.items() if k == "discourse" for _ in range(n)]
    sig = VoiceSig(level=level, mood=mood, hon_si=bool(hon_si), si_count=count, stance=stance, persona=persona,
                   humble=humble > 0, cmc=cmc[:40], discourse=discourse[:40], final=_display_final(body, masked, fin),
                   addressee=addressee.group(0) if addressee else None)
    whole = whole_quote(body) is not None
    quote_levels = () if whole else tuple(_level(q, _final(q, Counter()))[0] for q in quotes(body))
    marks = Counter(m.group(0) for m in _RAW_MARKS.finditer(masked))
    return Features(sig=sig, ending=ending, stance_family=family, question="?" in fin.tail,
                    directive=fin.word.endswith(_DIRECTIVE), humble_count=humble,
                    hon_nouns=_hon_nouns(masked), keep=keep, marks=marks,
                    upshift=len(UPSHIFT.findall(_fold(masked))), quote_levels=quote_levels, inner=_inner(masked))


def _hon_nouns(masked: str) -> int:
    """Honorific address nouns (고객님, 학부모님) plus honorific datives (어른께)."""
    dative = 0
    for m in _HON_DATIVE.finditer(masked):
        before = masked[m.start() - 1]
        if before not in _TIME_GGE and (jong(before) != 8 or before == "들"):     # 들께 = plural + 께
            dative += 1
    return len(_HON_NOUN.findall(masked)) + dative


def _fold(text: str) -> str:
    for a, b in _FOLD:
        if a in text:
            text = text.replace(a, b)
    return text


def _inner(masked: str) -> Tuple[Tuple[str, str], ...]:
    """(level, mood) of every finite clause that a ^^ or ~ run closes inside the sentence."""
    out = []
    start = 0
    for m in _INNER_END.finditer(masked):
        clause = masked[start:m.end()]
        start = m.end()
        fin = _final(clause, Counter())
        level, ending = _level(clause, fin)
        if level in FINITE:
            out.append((level, _mood(fin, level, ending)))
    return tuple(out)


def _display_final(body: str, masked: str, fin: _Final) -> str:
    """Final eojeol as written plus its terminal punctuation ("정리합니다.", "확인하세요")."""
    raw = fin.raw
    if not raw or raw == QUOTE_TOKEN:
        words = body.split()
        return words[-1][:200] if words else ""
    m = _TERMINAL.match(fin.tail)
    return (raw + (m.group(1) if m else ""))[:200]


def signature(sentence: str, kind: str = "body") -> VoiceSig:
    """Voice signature of one sentence (DESIGN 3.3). cmc lists CMC tokens and 할께-family spellings,
    discourse lists discourse markers and intensifiers; stance is the display form of the stance
    family (더라고요, 거든요, ...), "ㅂ니다" for a plain 합쇼체 ending, None otherwise."""
    return features(sentence, kind).sig


def final_eojeol(sentence: str) -> Tuple[str, str]:
    """(final eojeol as written, the characters after it) with quotations masked; the eojeol is
    QUOTE_TOKEN when the sentence ends in a quotation that is not the whole sentence."""
    fin = _final(mask_quotes(sentence), protect.keep_tokens(sentence))
    return fin.raw, fin.tail


def level_of(sentence: str) -> str:
    """Speech level of one sentence (the classifier alone; quotes masked)."""
    masked = mask_quotes(sentence)
    keep = protect.keep_tokens(sentence)
    return _level(masked, _final(masked, keep))[0]


# --------------------------------------------------------------------------
# document profile and voice sheet (prompt aids only, never used in a decision)
# --------------------------------------------------------------------------
def profile(doc: Document) -> dict:
    """Document voice profile as types.Profile JSON: the dominant finite level of the body
    sentences, its share, whether several finite levels occur, and one Korean context line such
    as "합쇼 82%, 해요 CTA·질문 섞임". OD 1: the profile is a prompt aid and never decides anything."""
    levels: Counter = Counter()
    moods: Dict[str, Counter] = {}
    for unit in doc.units:
        if unit.kind not in ("body", "quote"):
            continue
        sig = signature(unit.text, unit.kind)
        if sig.level in FINITE:
            levels[sig.level] += 1
            moods.setdefault(sig.level, Counter())[sig.mood] += 1
    total = sum(levels.values())
    if not total:
        return {"dominant": NONE, "share": 0.0, "mixed": False, "line": "종결 문장 없음(명사형·개조식 위주)"}
    dominant = max(LEVELS, key=lambda lv: (levels.get(lv, 0), -LEVELS.index(lv)))
    share = levels[dominant] / total
    others = [lv for lv in LEVELS if lv != dominant and levels.get(lv)]
    line = f"{LEVEL_SHORT[dominant]} {round(share * 100)}%"
    if others:
        parts = []
        for lv in sorted(others, key=lambda x: -levels[x]):
            uses = "·".join(MOOD_USE[m] for m, _ in moods[lv].most_common())
            parts.append(f"{LEVEL_SHORT[lv]} {uses}")
        line += ", " + ", ".join(parts) + " 섞임"
    return {"dominant": dominant, "share": round(share, 2), "mixed": bool(others), "line": line}


def sheet_line(unit: Unit, sig: VoiceSig) -> str:
    """One voice-sheet line for the prompt (T2 §5 format): S7 해요체·명령·시 「확인하세요」 keep:[~]."""
    parts = [LEVEL_KO.get(sig.level, sig.level)]
    if sig.level in FINITE or sig.mood == INTERR:
        parts.append(MOOD_KO.get(sig.mood, sig.mood))
    if sig.si_count > 1:
        parts.append(f"시×{sig.si_count}")
    elif sig.si_count or sig.hon_si:
        parts.append("시")
    if sig.stance and sig.stance != "ㅂ니다":
        parts.append(sig.stance)
    final = _TERMINAL.sub("", sig.final) if sig.final else ""
    final = re.sub(r"[.!?。！？…]+$", "", final)
    line = f"{unit.id} {'·'.join(parts)} 「{final}」"
    keep = list(sig.cmc) + list(sig.discourse)
    if sig.humble:
        keep.append("드리다")
    if any(p == "first_humble" for p in sig.persona):
        keep.append("저")
    if keep:
        line += " keep:[" + ", ".join(dict.fromkeys(keep)) + "]"
    return line


def signatures(units: Sequence[Unit]) -> List[Features]:
    """features() of every unit, in order."""
    return [features(unit.text, unit.kind) for unit in units]
