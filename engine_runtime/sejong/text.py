"""Text hygiene and the one sentence splitter of Super Sejong Engine v2 (DESIGN.md 3.1, 3.2).

sanitize() is a port of vendor/humanize-engine/scripts/sanitize_text.py with the same behaviour
byte for byte (tests/skills/test_sejong_text.py compares both on every fixture): zero-width, BOM,
bidi and tag characters are removed, special spaces become a plain space, line breaks become LF,
trailing spaces are dropped, and only decomposed Hangul jamo sequences are recomposed. Nothing is
NFKC-normalised, so compatibility jamo (ㅋㅋ, ㅠㅠ) and CJK compatibility ideographs survive.

segment() replaces the three splitters that exist today (_TERMINAL in super_sejong.py,
sentencesIn in super-sejong.ts, the vendor chunker). Rules, each mechanically checkable:

  paragraph   a maximal run of non-blank lines; a blank (whitespace-only) line separates paragraphs
  boundary    every newline;
              a terminator run [.!?。！？…]+ plus closing quotes/brackets, followed by whitespace or
              end of line, or GLUED to a Hangul syllable, an uppercase Latin letter, a digit or an
              opening quote when the character before the terminator is a Hangul syllable
              ("…한다.논문에서는", T5 §2.1: 10.3% of LLM-abstract boundaries, blog 3.4%);
              a CMC run after a Hangul syllable, followed by whitespace and a new word, when it
              holds a laughter/crying jamo token (ㅋㅋ ㅎㅎ ㅠㅠ; spaces before it allowed: "비 온대ㅋㅋ
              우산 …", "봤어요 ㅎㅎ 우유를 …") or an emoji glued to a sentence-final syllable 요 다 죠 까
              네 군 ("좋았어요😀 다음 …"); "~" and "^^" alone are not boundaries ("놀랐어요~ 다음에 …"),
              as in the seed benchmark's segmentation (T7 build_seed)
  trailing    a CMC run after a boundary stays with the sentence before it ("좋아요. ㅋㅋ 그런데")
  not a boundary
              digit.digit (3.5, 1.2.3) and spaced dates (2024. 10. 4.); a line-initial ordinal
              (1. 가. A. iv.); dotted abbreviations (U.S., e.g., i.e.) and a closed list (Dr., etc.,
              vs.); a single capital initial before a capital (J. K. Rowling); URLs, e-mails, Latin
              name tokens and inline code; anything inside a quotation (masked per paragraph, an
              unclosed curly opener masks to the paragraph end); anything inside matched
              parentheses on the line ("(아마?)"); a quotation followed by narration stays one
              unit with it ("“알겠어요.” 그가 대답했다.", seed benchmark convention)

Units carry code-point offsets (Python string indices) and UTF-16 offsets (TypeScript), the
paragraph index and a kind: heading, list, quote, button or body (line_kind, unmarked_heading).
Every step is a single regex pass or a linear scan; nothing is quadratic in the text length.
"""
from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left, bisect_right
from typing import Dict, List, Optional, Sequence, Tuple

from .types import Document, Unit

# ==========================================================================
# sanitize (port of vendor scripts/sanitize_text.py; keep both in step)
# ==========================================================================
# Code points are written as numbers so that no invisible character appears in this file.
SOFT_HYPHEN = 0x00AD
NBSP = 0x00A0
MONGOLIAN_VOWEL_SEP = 0x180E
OGHAM_SPACE = 0x1680
ZWSP = 0x200B
ZWNJ = 0x200C
ZWJ = 0x200D
WORD_JOINER = 0x2060
BOM = 0xFEFF
NARROW_NBSP = 0x202F
MED_MATH_SPACE = 0x205F
IDEOGRAPHIC_SPACE = 0x3000
LINE_SEP = 0x2028
PARA_SEP = 0x2029


def _cls(*ranges) -> str:
    """Code points and (first, last) ranges -> body of a regex character class."""
    out = []
    for item in ranges:
        if isinstance(item, tuple):
            out.append(f"\\U{item[0]:08x}-\\U{item[1]:08x}")
        else:
            out.append(f"\\U{item:08x}")
    return "".join(out)


INVISIBLE_ALWAYS = re.compile("[" + _cls(SOFT_HYPHEN, MONGOLIAN_VOWEL_SEP, ZWSP, WORD_JOINER, BOM) + "]")
BIDI = re.compile("[" + _cls(0x061C, (0x200E, 0x200F), (0x202A, 0x202E), (0x2066, 0x2069)) + "]")
TAG_CHARS = re.compile("[" + _cls((0xE0000, 0xE007F)) + "]")
# U+3000 is a visible full-width space (some writers indent with it); it is opt-in like the vendor.
SPECIAL_SPACES = re.compile("[" + _cls(NBSP, OGHAM_SPACE, (0x2000, 0x200A), NARROW_NBSP, MED_MATH_SPACE) + "]")
IDEOGRAPHIC_SPACE_RE = re.compile("[" + _cls(IDEOGRAPHIC_SPACE) + "]")
UNI_BREAKS = re.compile("[" + _cls(LINE_SEP, PARA_SEP) + "]")
# Conjoining jamo L V (T): the only sequences that are recomposed. Full NFC would also rewrite CJK
# compatibility ideographs and symbols such as U+212B, and NFKC would destroy compatibility jamo.
DECOMPOSED_HANGUL = re.compile(
    "[" + _cls((0x1100, 0x1112)) + "]" "[" + _cls((0x1161, 0x1175)) + "]" "[" + _cls((0x11A8, 0x11C2)) + "]?")
# ZWJ/ZWNJ join emoji sequences, so they are removed only between two plain characters.
PLAIN_NEIGHBOR = re.compile(r"[가-힣0-9A-Za-z\s.,!?;:'\"()\[\]{}-]")
_JOINERS = (chr(ZWNJ), chr(ZWJ))
SANITIZE_COUNT_KEYS = ("hangul_recomposed", "invisible", "bidi", "tag_chars", "special_spaces",
                       "line_breaks", "trailing_space_lines")
_TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_LONE_CR = re.compile(r"\r(?!\n)")


def _strip_joiners_outside_emoji(text: str) -> Tuple[str, int]:
    if _JOINERS[0] not in text and _JOINERS[1] not in text:
        return text, 0
    removed = 0
    kept: List[str] = []
    n = len(text)
    for i, ch in enumerate(text):
        if ch in _JOINERS:
            prev = kept[-1] if kept else ""
            nxt = text[i + 1] if i + 1 < n else ""
            if (prev == "" or PLAIN_NEIGHBOR.match(prev)) and (nxt == "" or PLAIN_NEIGHBOR.match(nxt)):
                removed += 1
                continue
        kept.append(ch)
    return "".join(kept), removed


def _sanitize_summary(counts: Dict[str, int], changed: bool) -> str:
    if not changed:
        return ""
    labels = (("hangul_recomposed", "분해된 한글 {}자 결합"), ("invisible", "보이지 않는 문자 {}개 제거"),
              ("bidi", "방향 제어 문자 {}개 제거"), ("tag_chars", "숨은 태그 문자 {}개 제거"),
              ("special_spaces", "특수 공백 {}개 정리"), ("line_breaks", "줄바꿈 {}개 통일"),
              ("trailing_space_lines", "줄 끝 공백 {}줄 정리"))
    return " · ".join(label.format(counts[key]) for key, label in labels if counts.get(key))


def sanitize(text: str, *, normalize_unicode: bool = True, strip_invisible: bool = True,
             normalize_spaces: bool = True, normalize_lines: bool = True,
             normalize_ideographic_space: bool = False,
             collapse_blank_lines: bool = False) -> Tuple[str, dict]:
    """(clean text, report). The report is the vendor's SanitizeReport.to_dict() (00_sanitize.json):
    {"changed", "before_chars", "after_chars", "counts", "summary"}. Idempotent."""
    original = text
    counts = {key: 0 for key in SANITIZE_COUNT_KEYS}
    # Invisible characters first: a zero-width character between jamo blocks their recomposition.
    if strip_invisible:
        counts["invisible"] = len(INVISIBLE_ALWAYS.findall(text))
        text = INVISIBLE_ALWAYS.sub("", text)
        counts["bidi"] = len(BIDI.findall(text))
        text = BIDI.sub("", text)
        counts["tag_chars"] = len(TAG_CHARS.findall(text))
        text = TAG_CHARS.sub("", text)
        text, removed = _strip_joiners_outside_emoji(text)
        counts["invisible"] += removed
    if normalize_unicode:
        counts["hangul_recomposed"] = len(DECOMPOSED_HANGUL.findall(text))
        text = DECOMPOSED_HANGUL.sub(lambda m: unicodedata.normalize("NFC", m.group(0)), text)
    if normalize_spaces:
        counts["special_spaces"] = len(SPECIAL_SPACES.findall(text))
        text = SPECIAL_SPACES.sub(" ", text)
    if normalize_ideographic_space:
        counts["special_spaces"] += len(IDEOGRAPHIC_SPACE_RE.findall(text))
        text = IDEOGRAPHIC_SPACE_RE.sub(" ", text)
    if normalize_lines:
        counts["line_breaks"] = text.count("\r\n") + len(_LONE_CR.findall(text)) + len(UNI_BREAKS.findall(text))
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = UNI_BREAKS.sub("\n", text)
        counts["trailing_space_lines"] = len(_TRAILING_SPACE.findall(text))
        text = _TRAILING_SPACE.sub("", text)
    if collapse_blank_lines:
        text = re.sub(r"\n{3,}", "\n\n", text)
    changed = text != original
    return text, {"changed": changed, "before_chars": len(original), "after_chars": len(text),
                  "counts": counts, "summary": _sanitize_summary(counts, changed)}


# ==========================================================================
# offsets
# ==========================================================================
class Utf16Index:
    """Code-point offset -> UTF-16 offset of one text in O(log a), a = astral characters in it."""

    def __init__(self, text: str):
        self._astral = [i for i, ch in enumerate(text) if ord(ch) > 0xFFFF] if _has_astral(text) else []

    def __call__(self, offset: int) -> int:
        return offset + bisect_left(self._astral, offset) if self._astral else offset


def _has_astral(text: str) -> bool:
    # str.isascii is O(1) for ASCII strings; the regex scan is one pass otherwise.
    return not text.isascii() and _ASTRAL.search(text) is not None


_ASTRAL = re.compile("[" + _cls((0x10000, 0x10FFFF)) + "]")


def utf16_offset(text: str, offset: int) -> int:
    """UTF-16 code units before code point `offset` of `text` (one-off use; prefer Utf16Index)."""
    return offset + len(_ASTRAL.findall(text, 0, offset))


# ==========================================================================
# quotations (per paragraph, linear)
# ==========================================================================
# Curly and CJK pairs plus the straight quotes. 《》〈〉 are title brackets; they are masked too
# so that a terminator inside a title never splits a sentence.
QUOTE_PAIRS = {"“": "”", "‘": "’", "「": "」", "『": "』", "《": "》", "〈": "〉", '"': '"', "'": "'"}
# An opener without a closer masks to the paragraph end only when it is unambiguous; a lone
# straight quote is just as often an inch mark, a typo or an apostrophe and is left alone.
_EXTEND_UNCLOSED = frozenset("“‘「『《〈")
MASK_CHAR = "ㅇ"          # same filler as the T6 prototype; not a terminator, not CMC, not Latin
_OPENER = re.compile("[" + re.escape("".join(QUOTE_PAIRS)) + "]")
_NOT_NEWLINE = re.compile(r"[^\n]")
_LATIN = re.compile(r"[A-Za-z]")


def _paragraph_ranges(text: str) -> List[Tuple[int, int]]:
    """(start, end) of each maximal run of non-blank lines; end excludes the final newline."""
    out: List[Tuple[int, int]] = []
    start = None
    pos = 0
    n = len(text)
    while pos <= n:
        nl = text.find("\n", pos)
        end = n if nl < 0 else nl
        if text[pos:end].strip():
            if start is None:
                start = pos
            last_end = end
        elif start is not None:
            out.append((start, last_end))
            start = None
        if nl < 0:
            break
        pos = nl + 1
    if start is not None:
        out.append((start, last_end))
    return out


def _is_apostrophe(text: str, i: int) -> bool:
    """' or ’ between two Latin letters (don't, Children’s) is an apostrophe, not a quote."""
    return 0 < i < len(text) - 1 and bool(_LATIN.match(text[i - 1])) and bool(_LATIN.match(text[i + 1]))


def quote_regions(text: str, start: int = 0, end: Optional[int] = None) -> List[Tuple[int, int, bool]]:
    """Quotations in text[start:end] (one paragraph) as (open, close_end, closed).

    open is the index of the opening mark; close_end is one past the closing mark, or `end` for
    an unclosed curly opener, which masks to the paragraph end. Quotations do not nest: marks
    inside an open quotation are content. Linear: openers and closers are found with str.find /
    one regex, and an unclosed straight quote proves that no further mark of its kind follows."""
    end = len(text) if end is None else end
    out: List[Tuple[int, int, bool]] = []
    dead = set()                 # straight marks with no closer left in the paragraph
    i = start
    while i < end:
        m = _OPENER.search(text, i, end)
        if m is None:
            break
        i = m.start()
        ch = text[i]
        if ch in dead or (ch in "'" and _is_apostrophe(text, i)):
            i += 1
            continue
        closer = QUOTE_PAIRS[ch]
        j = text.find(closer, i + 1, end)
        while j >= 0 and closer in "'’" and _is_apostrophe(text, j):
            j = text.find(closer, j + 1, end)
        if j >= 0:
            out.append((i, j + 1, True))
            i = j + 1
        elif ch in _EXTEND_UNCLOSED:
            out.append((i, end, False))
            break
        else:
            dead.add(ch)         # no closer of this kind after i: the mark is plain text
            i += 1
    return out


def mask_quotes(text: str) -> str:
    """Same-length copy of `text` with every quotation's content replaced by MASK_CHAR.

    Quote marks and newlines are kept, so offsets and line structure stay valid. Quotations are
    found per paragraph; an unclosed curly opener masks to the end of its paragraph. Linear."""
    if _OPENER.search(text) is None:
        return text
    pieces: List[str] = []
    last = 0
    for p_start, p_end in _paragraph_ranges(text):
        for q_open, q_end, closed in quote_regions(text, p_start, p_end):
            inner_end = q_end - 1 if closed else q_end
            pieces.append(text[last:q_open + 1])
            pieces.append(_NOT_NEWLINE.sub(MASK_CHAR, text[q_open + 1:inner_end]))
            last = inner_end
    pieces.append(text[last:])
    return "".join(pieces)


# ==========================================================================
# line kinds
# ==========================================================================
_MD_HEADING = re.compile(r"[ \t]*#{1,6}(?:[ \t]|$)")
# Numbered or bracketed headings; only when the line does not end like a sentence.
_PREFIX_HEADING = re.compile(
    r"[ \t]*(?:제\s*\d+\s*[장절편부관]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+\.|[IVX]{1,5}\.[ \t]"
    r"|【[^】\n]{1,40}】[ \t]*$|\[[^\]\n]{1,40}\][ \t]*$|<[^>A-Za-z/!\n][^>\n]{0,39}>[ \t]*$)")
_ARTICLE_HEADING = re.compile(r"[ \t]*제\s*\d+\s*조(?:의\d+)?[ \t]*(?:\([^)\n]{1,30}\))?[ \t]*$")
LIST_MARKER = re.compile(
    r"[ \t]*(?:[-*+][ \t]+|\d{1,3}[.)][ \t]+|\(\d{1,3}\)[ \t]*|[가-하][.)][ \t]+|[①-⑳][ \t]*"
    r"|[•·▪◦‣○●■□◆◇][ \t]*)")
_BLOCKQUOTE = re.compile(r"[ \t]*>")
# Nominal button / link lines (T6 _BTN_NOUN, _BTN_MARK).
_BTN_NOUN = re.compile(
    r"(?:구독|이웃\s*추가|서로\s*이웃(?:\s*추가)?|공감|좋아요|팔로우|신청|문의|상담|예약|다운로드|바로\s*가기|더\s*보기"
    r"|자세히\s*보기|알아보기|신청하기|문의하기|상담하기|예약하기|구독하기|공유하기|저장하기|등록하기|가입하기|전화하기"
    r"|전화\s*상담|상담\s*신청|방문하기|확인하기|조회하기|접수하기)$")
_BTN_MARK = re.compile(r"^[\s▶▷►☞👉✔✅※■□●○◆◇★☆•\[(\-–—>▼▽]+")
_BTN_STRONG_MARKS = "▶▷►☞👉✔✅※■□●○◆◇★☆•[(>"
_TERMINAL_CHAR = re.compile(r"[.!?。！？…]")
# A line ending like a sentence (predicate syllable, optionally CMC and punctuation) is prose,
# never an unmarked heading.
_PROSE_TAIL = re.compile(r"(?:[다요죠까네지군나래야자니라음함임]|습니다)[\s~～ㅋㅎㅠㅜ^!?.…]*$")
UNMARKED_HEADING_MAX = 40


def is_button_line(line: str) -> bool:
    """A nominal CTA line such as '▶ 무료 상담 예약하기' or '[상담 신청하기]' (T6 _nominal_button)."""
    raw = line.strip()
    if len(raw) > 60:
        return False
    body = re.sub(r"[\])>]+$", "", _BTN_MARK.sub("", raw)).strip()
    if not body or len(body) > 26 or _TERMINAL_CHAR.search(body):
        return False
    marked = bool(_BTN_MARK.match(raw)) and raw[:1] in _BTN_STRONG_MARKS
    return bool(_BTN_NOUN.search(body)) and (marked or len(body.split()) <= 3)


def line_kind(line: str) -> str:
    """heading | button | list | quote | body for one line (without its newline)."""
    if _MD_HEADING.match(line):
        return "heading"
    stripped = line.strip()
    if is_button_line(line):
        return "button"
    if len(stripped) <= 60 and not _TERMINAL_CHAR.search(stripped[-1:]) and (
            _PREFIX_HEADING.match(line) or _ARTICLE_HEADING.match(line)):
        return "heading"
    if LIST_MARKER.match(line):
        return "list"
    if _BLOCKQUOTE.match(line):
        return "quote"
    return "body"


def unmarked_heading(line: str, next_paragraph_chars: int) -> bool:
    """An unmarked heading (DESIGN 3.2): a paragraph of one line, at most 40 characters, with no
    terminal punctuation and no sentence-like ending, followed by a longer paragraph.
    "1. ", "1) ", "가. " and "(주)" lines are list items or names, never headings."""
    s = line.strip()
    if not s or len(s) > UNMARKED_HEADING_MAX or next_paragraph_chars <= len(s):
        return False
    if _TERMINAL_CHAR.search(s) or _PROSE_TAIL.search(s) or s.endswith((",", ":", ";")):
        return False
    if LIST_MARKER.match(s) or s.startswith(("(주)", "㈜")) or is_button_line(s):
        return False
    return bool(re.search(r"[가-힣A-Za-z]", s))


# ==========================================================================
# sentence boundaries
# ==========================================================================
_TERM_RUN = re.compile(r"[.!?。！？…]+")
_CLOSERS = frozenset("\"'”’」』》〉)]）】")
_GLUED_OPENERS = frozenset("“‘「『\"'")
_SPACE_CHARS = frozenset(" \t\r\f\v" + chr(IDEOGRAPHIC_SPACE))
# CMC tokens (T2 EMO_RE plus emoji modifiers and ZWJ sequences). Each alternative is matched on
# its own (cmc_run_end) so no quantifier is nested: "ㅋ" * 100k + "x" stays linear.
_EMOJI = "\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2B55"
# One emoji = base, optional variation selector / skin tone, then ZWJ-joined parts (a ZWJ family
# or profession sequence is one token).
_EMOJI_MOD = "[" + chr(0xFE0F) + "\U0001F3FB-\U0001F3FF]*"
_EMOJI_ONE = "[" + _EMOJI + "]" + _EMOJI_MOD + "(?:" + chr(ZWJ) + "[" + _EMOJI + "]" + _EMOJI_MOD + ")*"
CMC_TOKEN = (r"ㅋ{2,}|ㅎ{2,}|ㅠ+|ㅜ{2,}|ㅡㅡ|\^\^;*|\^_\^|;;+|(?<![~～\d])(?<!\d )[~～]+(?![~～0-9A-Za-z가-힣]| \d)|!{2,}|\?{2,}"
             r"|" + _EMOJI_ONE + r"|\(웃음\)|><|T_T")
CMC_RE = re.compile(CMC_TOKEN)
# A Hangul syllable, optional spaces, then the start of a CMC token ("좋았어요😀 ㅎㅎ", "왔어요 ㅋㅋ").
_HANGUL_THEN_CMC = re.compile(r"(?<=[가-힣])[ \t]*(?=[ㅋㅎㅠㅜㅡ^~～;!?(><T" + _EMOJI + r"])")
# Laughter/crying jamo end a sentence when a new word follows (seed benchmark convention, T7
# build_seed EMO), wherever they stand; an emoji does so only glued to a sentence-final syllable
# ("좋았어요😀 다음…", not "오늘 ☕ 한 잔"); "~" and "^^" alone never do ("놀랐어요~ 다음에 또 갈게요").
_JAMO_CMC = re.compile(r"[ㅋㅎㅠㅜ]")
_EMOJI_CMC = re.compile(r"[" + _EMOJI + r"]")
_FINAL_SYLLABLE = frozenset("요다죠까네군")
_ORDINAL_AT = re.compile(r"\d{1,3}\.(?=[ \t])")
# Zones where a terminator is never a boundary.
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"'“”‘’\[\]{}()가-힣ㄱ-ㅣ]+"
                  r"|(?<![\w@.\-])[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9-]+)*"
                  r"\.(?:com|net|org|kr|io|co|me|ai|dev|app|edu|gov|info|biz|tv|jp|cn|uk|us|eu)"
                  r"(?![A-Za-z0-9-])(?:/[^\s<>\"'“”‘’\[\]{}()가-힣ㄱ-ㅣ]*)?")
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_URL_TRAIL = re.compile(r"[.,!?;:…]+$")
# Latin name / acronym token (engine_runtime/workflow._NAME_TOKEN, Latin part).
NAME_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[.'’\-][A-Za-z0-9]+)*")
_ABBREV = re.compile(
    r"(?<![A-Za-z])(?:[A-Za-z]\.){2,}"
    r"|(?<![A-Za-z])(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Mt|vs|etc|Inc|Ltd|Co|Corp|Fig|Figs|Eq|Vol|No|pp|cf|al"
    r"|approx|ca|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.")
_INITIAL = re.compile(r"(?<![A-Za-z])[A-Z]\.(?=[ \t]+[A-Z])")
_DATE_DOTS = re.compile(r"(?<!\d)\d{2,4}\.[ \t]?\d{1,2}\.[ \t]?\d{1,2}\.?")
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_LINE_ORDINAL = re.compile(r"[ \t]*(?:\d{1,3}|[A-Za-z]|[가-하]|[ivxIVX]{1,4})\.(?=[ \t])")
_FENCE = re.compile(r"[ \t]*(?:```|~~~)")


def cmc_run(text: str, pos: int, end: Optional[int] = None) -> Tuple[int, bool, bool]:
    """(end, jamo, emoji) of the run of CMC tokens (separated by spaces or tabs) that starts at
    `pos`; end == pos when no token starts there. jamo / emoji: the run holds a laughter or crying
    jamo token / an emoji. Linear in the run length."""
    end = len(text) if end is None else end
    last = pos
    jamo = emoji = False
    p = pos
    while p < end:
        m = CMC_RE.match(text, p, end)
        if m is None or m.end() == p:
            break
        jamo = jamo or _JAMO_CMC.match(text, p) is not None
        emoji = emoji or _EMOJI_CMC.match(text, p) is not None
        last = m.end()
        p = last
        while p < end and text[p] in " \t":
            p += 1
    return last, jamo, emoji


def cmc_run_end(text: str, pos: int, end: Optional[int] = None) -> int:
    """End of the CMC run that starts at `pos` (see cmc_run); `pos` when there is none."""
    return cmc_run(text, pos, end)[0]


class _Zones:
    """Sorted, merged half-open intervals with O(log n) membership."""

    def __init__(self, intervals: Sequence[Tuple[int, int]]):
        merged: List[List[int]] = []
        for a, b in sorted(intervals):
            if b <= a:
                continue
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        self.starts = [a for a, _ in merged]
        self.ends = [b for _, b in merged]

    def __contains__(self, pos: int) -> bool:
        k = bisect_right(self.starts, pos) - 1
        return k >= 0 and pos < self.ends[k]

    def overlaps(self, a: int, b: int) -> bool:
        """Some zone intersects [a, b)."""
        k = bisect_right(self.starts, b - 1) - 1
        return k >= 0 and self.ends[k] > a


def url_spans(line: str) -> List[Tuple[int, int]]:
    """URLs and bare domains, without trailing sentence punctuation."""
    out = []
    for m in _URL.finditer(line):
        trimmed = _URL_TRAIL.sub("", m.group(0))
        if trimmed:
            out.append((m.start(), m.start() + len(trimmed)))
    return out


def email_spans(line: str) -> List[Tuple[int, int]]:
    return [m.span() for m in _EMAIL.finditer(line)]


def _paren_zones(line: str) -> List[Tuple[int, int]]:
    """Insides of matched (), [], （） on one line; one stack per bracket kind (linear). A pair
    longer than PAREN_ZONE_MAX is ignored: an unclosed "(" must not swallow the sentence ends up
    to an unrelated "2)" further on."""
    stacks: Dict[str, List[int]] = {"(": [], "[": [], "（": []}
    closers = {")": "(", "]": "[", "）": "（"}
    out = []
    for m in _PAREN.finditer(line):
        ch = m.group(0)
        if ch in stacks:
            stacks[ch].append(m.start())
        elif stacks[closers[ch]]:
            opened = stacks[closers[ch]].pop()
            if m.start() - opened <= PAREN_ZONE_MAX:
                out.append((opened + 1, m.start()))
    return out


_PAREN = re.compile(r"[()\[\]（）]")
PAREN_ZONE_MAX = 200


def _no_break_zones(line: str) -> _Zones:
    zones: List[Tuple[int, int]] = []
    zones.extend(url_spans(line))
    zones.extend(email_spans(line))
    for rx in (_ABBREV, _INITIAL, _DATE_DOTS, _INLINE_CODE):
        zones.extend(m.span() for m in rx.finditer(line))
    # Latin name tokens cover "Node.js" and "v1.2"; the dot after the token stays a boundary.
    zones.extend(m.span() for m in NAME_TOKEN.finditer(line) if "." in m.group(0))
    m = _LINE_ORDINAL.match(line)
    if m:
        zones.append((m.end() - 1, m.end()))
    zones.extend(_paren_zones(line))
    return _Zones(zones)


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


def _line_boundaries(line: str, masked: str) -> List[int]:
    """Sorted cut positions (ends of sentences) inside one line; the line end is implicit."""
    zones = _no_break_zones(line)
    n = len(line)
    cuts = set()

    def with_trailing_cmc(pos: int) -> int:
        p = pos
        while p < n and line[p] in " \t":
            p += 1
        run = cmc_run_end(masked, p, n)
        return run if run > p and (run >= n or line[run] in _SPACE_CHARS) else pos

    ordinals = set()          # "2." right after a glued cut ("보였다.2. 기존 …") is an ordinal
    for m in _TERM_RUN.finditer(masked):
        a, end = m.start(), m.end()
        if a in ordinals or zones.overlaps(a, end):
            continue
        # decimals and versions: digit . digit
        if end - a == 1 and masked[a] == "." and 0 < a and end < n and line[a - 1].isdigit() and line[end].isdigit():
            continue
        while end < n and line[end] in _CLOSERS:
            end += 1
        if end >= n or line[end] in _SPACE_CHARS:
            cuts.add(with_trailing_cmc(end))
            continue
        # glued terminator: Hangul before it, a new word start after it; "…" and ".." are pauses
        run = m.group(0)
        if "…" in run or ".." in run:
            continue
        prev, nxt = line[a - 1] if a > 0 else "", line[end]
        if _is_hangul(prev) and (_is_hangul(nxt) or "A" <= nxt <= "Z" or nxt.isdigit() or nxt in _GLUED_OPENERS):
            cuts.add(end)
            ordinal = _ORDINAL_AT.match(line, end)
            if ordinal:
                ordinals.add(ordinal.end() - 1)
    for m in _HANGUL_THEN_CMC.finditer(masked):
        run, jamo, emoji = cmc_run(masked, m.end(), n)
        p = run
        while p < n and line[p] in " \t":
            p += 1
        glued_to_final = m.start() == m.end() and line[m.start() - 1] in _FINAL_SYLLABLE
        if (jamo or (emoji and glued_to_final)) and run < p < n and not zones.overlaps(m.end(), run):
            cuts.add(run)
    return sorted(c for c in cuts if 0 < c < n)


def _whole_quote(text: str) -> bool:
    """The unit is one closed quotation, optionally followed by punctuation or CMC."""
    if len(text) < 2 or text[0] not in QUOTE_PAIRS:
        return False
    regions = quote_regions(text)
    if not regions or regions[0][0] != 0 or not regions[0][2]:
        return False
    p, n = regions[0][1], len(text)
    while p < n:
        if text[p] in " \t.,!?。…~～":
            p += 1
            continue
        run = cmc_run_end(text, p)
        if run == p:
            return False
        p = run
    return True


def fence_ranges(text: str) -> List[Tuple[int, int]]:
    """(start, end) of each fenced code block (``` or ~~~ lines), fences included; an unclosed
    fence runs to the end of the text, as in CommonMark."""
    out: List[Tuple[int, int]] = []
    if "```" not in text and "~~~" not in text:
        return out
    open_at = None
    pos = 0
    n = len(text)
    while pos <= n:
        nl = text.find("\n", pos)
        end = n if nl < 0 else nl
        if _FENCE.match(text, pos, end):
            if open_at is None:
                open_at = pos
            else:
                out.append((open_at, end))
                open_at = None
        if nl < 0:
            break
        pos = nl + 1
    if open_at is not None:
        out.append((open_at, n))
    return out


def _split_paragraph(text: str, p_start: int, p_end: int, masked: str,
                     fences: _Zones) -> List[Tuple[int, int, str, int]]:
    """(start, end, kind, line_index) per sentence of one paragraph, in text coordinates."""
    out = []
    pos = p_start
    line_index = 0
    while pos <= p_end:
        nl = text.find("\n", pos, p_end)
        l_end = p_end if nl < 0 else nl
        line = text[pos:l_end]
        if not line.strip():
            pass
        elif pos in fences:
            # code: one unit per line, never split inside
            lead = len(line) - len(line.lstrip())
            out.append((pos + lead, pos + len(line.rstrip()), "body", line_index))
        else:
            kind = line_kind(line)
            cuts: List[int] = []
            if kind not in ("heading", "button"):
                cuts = _line_boundaries(line, masked[pos:l_end])
            last = 0
            for cut in cuts + [len(line)]:
                piece = line[last:cut]
                if piece.strip():
                    lead = len(piece) - len(piece.lstrip())
                    s, e = pos + last + lead, pos + last + len(piece.rstrip())
                    unit_kind = "quote" if kind == "body" and _whole_quote(text[s:e]) else kind
                    out.append((s, e, unit_kind, line_index))
                last = cut
        line_index += 1
        if nl < 0:
            break
        pos = nl + 1
    return out


def _make_units(text: str, spans: List[Tuple[int, int, str, int]], u16: Utf16Index, first_id: int) -> List[Unit]:
    return [Unit(id=f"S{first_id + i}", start=s, end=e, start_u16=u16(s), end_u16=u16(e), para=para,
                 kind=kind, text=text[s:e]) for i, (s, e, kind, para) in enumerate(spans)]


def split_sentences(paragraph: str, base: int = 0, base_u16: Optional[int] = None) -> List[Unit]:
    """Sentence units of one paragraph (it may contain single newlines; every newline is a cut).

    Offsets are shifted by `base` (code points) and `base_u16` (UTF-16; defaults to `base`, which
    is exact only when the text before the paragraph has no astral characters). para is 0 and ids
    are S1.. local to the paragraph; segment() numbers units across a whole document."""
    base_u16 = base if base_u16 is None else base_u16
    masked = mask_quotes(paragraph)
    fences = _Zones(fence_ranges(paragraph))
    spans = _split_paragraph(paragraph, 0, len(paragraph), masked, fences) if paragraph.strip() else []
    u16 = Utf16Index(paragraph)
    return [Unit(id=f"S{i + 1}", start=base + s, end=base + e, start_u16=base_u16 + u16(s),
                 end_u16=base_u16 + u16(e), para=0, kind=kind, text=paragraph[s:e])
            for i, (s, e, kind, _) in enumerate(spans)]


def segment(text: str) -> Document:
    """Paragraphs and sentence units of a whole (sanitized) text.

    Unit ids run S1, S2, ... in document order. A one-line paragraph that passes
    unmarked_heading() against the next paragraph becomes a heading unit."""
    paragraphs = _paragraph_ranges(text)
    masked = mask_quotes(text)
    fences = _Zones(fence_ranges(text))
    u16 = Utf16Index(text)
    spans: List[Tuple[int, int, str, int]] = []
    for index, (p_start, p_end) in enumerate(paragraphs):
        pieces = _split_paragraph(text, p_start, p_end, masked, fences)
        if len(pieces) == 1 and pieces[0][2] == "body" and "\n" not in text[p_start:p_end].strip():
            nxt = paragraphs[index + 1] if index + 1 < len(paragraphs) else None
            if nxt is not None and unmarked_heading(text[p_start:p_end], len(text[nxt[0]:nxt[1]].strip())):
                pieces = [(pieces[0][0], pieces[0][1], "heading", 0)]
        spans.extend((s, e, kind, index) for s, e, kind, _ in pieces)
    return Document(text=text, paragraphs=paragraphs, units=_make_units(text, spans, u16, 1))


def unit_at(doc: Document, offset: int) -> Optional[Unit]:
    """The unit that contains code-point `offset`, or None (between units). O(log n)."""
    lo, hi = 0, len(doc.units)
    while lo < hi:
        mid = (lo + hi) // 2
        if doc.units[mid].start <= offset:
            lo = mid + 1
        else:
            hi = mid
    if lo and offset < doc.units[lo - 1].end:
        return doc.units[lo - 1]
    return None
