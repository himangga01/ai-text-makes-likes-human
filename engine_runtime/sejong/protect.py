"""Protected spans of Super Sejong Engine v2 (DESIGN.md 3.1).

Two policies (types.SpanPolicy):
  freeze      the model (prompt) and every repair must leave the text verbatim; a change is the
              floor failure protected_span_changed on that sentence
  keep-token  the token may move inside its sentence, but the sentence's multiset of keep tokens
              must survive (OD 2: CMC tokens, 할께-family spellings, discourse markers)

Kinds (types.SPAN_KINDS) and detection, in the priority used when freeze spans overlap
(FREEZE_PRIORITY):
  code        fenced block (text.fence_ranges), inline `code`
  url, email  text.url_spans / text.email_spans (trailing sentence punctuation excluded)
  quote       paired “…” ‘…’ "…" 「…」 『…』 《…》 〈…〉 per paragraph, marks included; an unclosed
              curly opener runs to the paragraph end (text.quote_regions, linear)
  footnote    inline marker "…했다.1)" and its definition line in the trailing definition block
              (vendor checks.py rules), Markdown [^1], superscript digits
  heading     every heading unit (Markdown #, 제N장, Ⅱ., [제목], unmarked heading of 3.2)
  markdown    syntax only, never the words: line markers (#, -, 1., >, |), emphasis marks
              (** __ ~~ *), link and image brackets with their targets, rules, HTML tags
  phone       02-123-4567, 010-1234-5678, 1588-1234, (02)123-4567, +82-10-…
  date        calendar dates and clock times: 2024년 3월 5일, 3월 5일, 2024.3.5, 2024-03-05, 09:30
  number      quantities._QUANTITY (signed number, 천/백/만/억/조, recognised unit: 3만 원, 5,000원,
              20%, 3개월) extended with %p, 배, 시, 층, 퍼센트/포인트 and a few counters when a
              particle or a word end follows (10시에, 3배로; not 3세대); digits only (see below)
  money       the rest of a money amount: currency sign or a foreign currency word ($5, 10달러);
              "3만 원" is already a number span and keeps that kind (the WP-0 plan fixtures)
  handle      @name ; hashtag #태그
  name        Latin name/acronym token and Han run (workflow._NAME_TOKEN)
  cmc         ㅋㅋ ㅎㅎ ㅠㅠ ^^ ~ !! ?? emoji (text.CMC_RE); a range tilde (3~5, 9시~오후, " ~ " between
              two words) is not CMC                                          keep-token
  colloquial  할께-family spellings (an eojeol whose ㄹ-final syllable is followed by 께/꺼/껄/껀:
              전화할께, 연락드릴께요, 할 꺼야) and the T2 colloquial lexemes (넹, 걍, 쫌, 해용 …);
              할려면/웬지 are errors, not colloquial (DESIGN 9.2a item 1); 께 after 달/날/말/일/월/들 is
              the time suffix or the particle (다음달께, 15일께, 어른들께)
                                                         keep-token unless fix_colloquial
  discourse   sentence-initial 사실, 솔직히, 뭐, 진짜, 아무튼 … (T2 DISCOURSE_INITIAL_RE)
                                                         keep-token unless fix_colloquial

Overlapping freeze spans are merged into one span: a span inside another takes the outer kind (a
number inside a quotation is covered by the quotation), a partial overlap takes the better-ranked
kind, and equal spans take the better-ranked kind. A keep-token span that touches a freeze span is
dropped: the freeze span already protects it. Number words (세 배, 열 명) are not frozen: 세 배 →
3배 keeps the value, and the quantities floor check compares values, not spellings.
Every detector is one regex pass or a linear scan; overlap resolution is O(k log k).
"""
from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import text as T
from .types import Document, Span, Unit

try:                                   # imported as engine_runtime.sejong.protect
    from .. import quantities
except (ImportError, ValueError):      # imported as sejong.protect with engine_runtime/ on sys.path
    import quantities  # type: ignore[no-redef]

FREEZE = "freeze"
KEEP = "keep-token"
FREEZE_PRIORITY = ("code", "url", "email", "quote", "footnote", "heading", "markdown", "phone", "date",
                   "number", "money", "handle", "hashtag", "name")
KEEP_KINDS = ("cmc", "colloquial", "discourse")
OPT_IN_KINDS = ("colloquial", "discourse")     # FIX targets under SUPER_SEJONG_FIX_COLLOQUIAL=1
# Kinds compared without whitespace by freeze_intact: "3만 원" -> "3만원" is a spacing change of the
# same quantity, which the norms layer may make; the value check lives in the floor.
SPACE_INSENSITIVE = ("number", "money", "date")
_RANK = {kind: i for i, kind in enumerate(FREEZE_PRIORITY)}

# --------------------------------------------------------------------------
# detectors (each returns (start, end) pairs in text coordinates)
# --------------------------------------------------------------------------
_INLINE_CODE = re.compile(r"``[^`\n]+``|`[^`\n]+`")
_HAN_RUN = re.compile("[㐀-䶿一-鿿豈-﫿]+")
_PHONE = re.compile(r"(?<![\d\-.])(?:\+82[ -]?)?(?:0\d{1,2}\) ?\d{3,4}-\d{4}|\d{2,4}-\d{3,4}-\d{4}|1\d{3}-\d{4}"
                    r"|0\d{1,2}\.\d{3,4}\.\d{4})(?![\d\-])")
_HANDLE = re.compile(r"(?<![\w@.])@[A-Za-z0-9_](?:[A-Za-z0-9_.]*[A-Za-z0-9_])?")
_HASHTAG = re.compile(r"(?<![\w&#/])#[0-9A-Za-z가-힣_]*[A-Za-z가-힣_][0-9A-Za-z가-힣_]*")
_DATE = re.compile(
    r"(?<!\d)\d{4}[ ]?년(?:[ ]?\d{1,2}[ ]?월)?(?:[ ]?\d{1,2}[ ]?일)?"
    r"|(?<!\d)\d{1,2}[ ]?월[ ]?\d{1,2}[ ]?일"
    r"|(?<![\d.])\d{4}[.\-/][ ]?\d{1,2}[.\-/][ ]?\d{1,2}(?!\d)\.?"
    r"|(?<![\d:])\d{1,2}:\d{2}(?::\d{2})?(?![\d:])")
_MONEY = re.compile(
    r"[$₩€£¥][ ]?\d+(?:,\d{3})*(?:\.\d+)?(?:[ ]?[천백만억조]+)?"
    r"|(?<![\d.,])\d+(?:,\d{3})*(?:\.\d+)?(?:[ ]?[천백십]?[만억조])*[ ]?(?:원|달러|엔|위안|유로|파운드|불)(?![A-Za-z])")
# Units quantities._QUANTITY does not know; tried right after a unitless match and kept only when
# the next character ends the word or starts a particle (quantities._AFTER_COUNTER): "10시에",
# "3배로" extend, "3세대" does not.
_EXTRA_UNIT = re.compile(r"[ ]?(?:%p(?![A-Za-z])|%포인트|퍼센트포인트|퍼센트|포인트|페이지|가지|단계|배|평|층|세|살|위|등|차|쪽|시|호|권|장|대)(?![A-Za-z])")
_PERCENT_P = re.compile(r"p(?![A-Za-z])|포인트")
# Markdown syntax (marks only).
_MD_LINE = re.compile(r"^[ \t]*(?:#{1,6}[ \t]+|>+[ \t]?|[-*+][ \t]+|\d{1,3}[.)][ \t]+|\(\d{1,3}\)[ \t]*"
                      r"|[가-하][.)][ \t]+|[①-⑳][ \t]*|[•·▪◦‣○●■□◆◇][ \t]*)", re.MULTILINE)
_MD_RULE = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.MULTILINE)
_MD_TABLE_SEP = re.compile(r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$", re.MULTILINE)
_MD_REF_DEF = re.compile(r"^[ \t]*\[[^\]\n]{1,80}\]:[ \t]*\S+.*$", re.MULTILINE)
# Emphasis delimiters, paired per line by _paired_marks (no lazy scan, so "**a " * 25k is linear).
# An opener follows whitespace, a line start or punctuation and precedes a non-space; a closer
# follows a non-space. CMC tildes glued to a word ("좋아요~~") therefore never open a pair.
_MD_MARK = re.compile(r"\*\*|__|~~|(?<![*\w])\*(?![*])|(?<=[^\s*])\*(?![*\w])")
_MD_LINK = re.compile(r"(!?\[)[^\[\]\n]*(\]\([^()\s]*(?:[ \t]+\"[^\"\n]*\")?\))")
_HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:[ \t][^<>\n]*)?/?>")
# Footnotes (vendor scripts/checks.py: _INLINE_MARKER, _DEF_LINE, _BLOCK_HEADING).
_FN_INLINE = re.compile(r"(?<=\S)(?<![(\dA-Za-z\-])(\d{1,3})\)")
_FN_DEF_LINE = re.compile(r"^\s*\d{1,3}\)\s")
_FN_DEF_LABEL = re.compile(r"\s*(\d{1,3})\)\s")
_FN_BLOCK_HEADING = re.compile(r"^\s*(?:#{1,6}\s|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+\.\s|제\d+[장절])")
_FN_MARKDOWN = re.compile(r"\[\^[^\]\s]{1,20}\]:?")
_ASCII_ALNUM = re.compile(r"[A-Za-z0-9]")
_SUPERSCRIPT = re.compile("[¹²³⁰⁴-⁹]+")
# Colloquial spellings. The 할께 family needs an ㄹ-final syllable before 께/꺼/껄/껀, so the
# honorific particle 께 (선생님께, 할아버지께) never matches; other forms are the T2 lexemes.
_GGE = re.compile(r"(?<=[가-힣])[ ]?(?:께|꺼|껄|껀)(?:요|야|예요|에요|여|다|지|죠|데|데요|라|라고|니|니까|든|면|지만|구나|네)?"
                  r"(?![가-힣])")
# Cute endings must close a predicate (a syllable before them), so 어용 노조 and 베이징 never
# match; 이징 is left out of T2's list (베이징, 디노이징 are the common hits on KLUE news).
# The adverbs 걍 젤 넘 쫌 첨 must modify a following word ("젤 좋아", not "젤, 왁스"); cute endings
# must close the sentence (punctuation, CMC or line end), so 유아용 세제 and 이세용 대표 never match.
_SENTENCE_END = r"(?=[.!?~ㅋㅎㅠ^]|[ \t]*(?:\n|\Z)|[ \t]+[ㅋㅎㅠㅜ^~])"
_COLLOQ_LEXEME = re.compile(
    r"(?<![가-힣])(?:넹|넵|넴|웅|응응|그쵸|암튼|글구|담에)(?![가-힣])"
    r"|(?<![가-힣])(?:걍|젤|넘|쫌|첨|머)(?=[ ]+[가-힣])"
    r"|(?<=[가-힣])(?:니당|어용|아용|해용|세용|네용|했당|었당|았당|좋당|같당|이당|해여|어여|아여|세여|네여|거징|했엉|었엉|았엉|해앙"
    r"|거양|이얌|거얌)" + _SENTENCE_END)
# 께 after these ㄹ-final syllables is the time suffix "around" (다음달께, 15일께, 월말께), not 할께.
# 께 after 들 is the honorific particle on a plural (어른들께, 어르신들께).
_TIME_GGE = frozenset("달날말일월들")
_DISCOURSE_INITIAL = re.compile(
    r"[\s\"“‘'(]*(사실|솔직히|아무튼|암튼|어쨌든|뭐|아이고|에휴|어머|와|음|아|참|글쎄|그니까|자|헐|진짜|완전|대박)"
    r"(?=[\s,.!?~]|$)")


def _jong(ch: str) -> int:
    code = ord(ch) - 0xAC00
    return code % 28 if 0 <= code < 11172 else -1


def _code_spans(text: str) -> List[Tuple[int, int]]:
    out = list(T.fence_ranges(text))
    out.extend(m.span() for m in _INLINE_CODE.finditer(text))
    return out


def _quote_spans(text: str, doc: Document) -> List[Tuple[int, int]]:
    out = []
    for p_start, p_end in doc.paragraphs:
        out.extend((a, b) for a, b, _ in T.quote_regions(text, p_start, p_end))
    return out


def _footnote_spans(text: str) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    lines: List[Tuple[int, str]] = []
    pos = 0
    for line in text.split("\n"):
        lines.append((pos, line))
        pos += len(line) + 1
    markers = set()
    for start, line in lines:
        if not _FN_DEF_LINE.match(line):
            for m in _FN_INLINE.finditer(line):
                # "(2002년=100)", "(이하 코로나19)": the ")" closes a parenthesis, not a footnote
                window = max(0, m.start() - 80)
                if line.rfind("(", window, m.start()) > line.rfind(")", window, m.start()):
                    continue
                markers.add(m.group(1))
                out.append((start + m.start(), start + m.end()))
    # definition lines: blocks that end the text or end at a heading, cited by a marker
    index = 0
    while index < len(lines):
        if not _FN_DEF_LINE.match(lines[index][1]):
            index += 1
            continue
        end = index
        while end < len(lines) and (not lines[end][1].strip() or _FN_DEF_LINE.match(lines[end][1])):
            end += 1
        if end == len(lines) or _FN_BLOCK_HEADING.match(lines[end][1]):
            for start, line in lines[index:end]:
                label = _FN_DEF_LABEL.match(line)
                if label and label.group(1) in markers:
                    out.append((start, start + len(line.rstrip())))
        index = end
    out.extend(m.span() for m in _FN_MARKDOWN.finditer(text))
    out.extend(m.span() for m in _SUPERSCRIPT.finditer(text)
               if m.start() == 0 or not _ASCII_ALNUM.match(text[m.start() - 1]))    # m², 10³: units, powers
    return out


def _markdown_spans(text: str) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for rx in (_MD_RULE, _MD_TABLE_SEP, _MD_REF_DEF, _HTML_TAG):
        out.extend(m.span() for m in rx.finditer(text))
    for m in _MD_LINE.finditer(text):
        s, e = m.span()
        lead = len(m.group(0)) - len(m.group(0).lstrip(" \t"))
        if e > s + lead:
            out.append((s + lead, e))
    out.extend(_paired_marks(text))
    for m in _MD_LINK.finditer(text):
        out.append(m.span(1))
        out.append(m.span(2))
    # table rows: the pipes of lines that start with "|"
    if "|" in text:
        pos = 0
        for line in text.split("\n"):
            if line.lstrip().startswith("|"):
                out.extend((pos + i, pos + i + 1) for i, ch in enumerate(line) if ch == "|")
            pos += len(line) + 1
    return out


def _paired_marks(text: str) -> List[Tuple[int, int]]:
    """Both delimiters of each emphasis pair (**x**, __x__, ~~x~~, *x*) within one line."""
    out: List[Tuple[int, int]] = []
    pending: Dict[str, int] = {}
    scanned = 0                        # text[:scanned] has been checked for newlines
    n = len(text)
    for m in _MD_MARK.finditer(text):
        a, b = m.span()
        if text.find("\n", scanned, a) >= 0:       # a new line: unpaired openers expire
            pending.clear()
        scanned = a
        mark = m.group(0)
        before = text[a - 1] if a > 0 else "\n"
        after = text[b] if b < n else "\n"
        if mark in pending and not before.isspace():
            opened = pending.pop(mark)
            out.append((opened, opened + len(mark)))
            out.append((a, b))
        elif not after.isspace() and (before.isspace() or not before.isalnum()):
            pending[mark] = a
    return out


def _phone_spans(text: str) -> List[Tuple[int, int]]:
    out = []
    for m in _PHONE.finditer(text):
        parts = re.findall(r"\d+", m.group(0))
        # "1099-1118" (재위 1099–1118) is a year range, not a 15xx/16xx service number
        if len(parts) == 2 and all(len(x) == 4 for x in parts) and 1000 <= int(parts[0]) <= 2100 \
                and 0 <= int(parts[1]) - int(parts[0]) <= 200:
            continue
        out.append(m.span())
    return out


def _number_spans(text: str) -> List[Tuple[int, int]]:
    """quantities._QUANTITY on the width-folded text (1:1 by construction), extended with the
    units it does not know (%p, 배, …)."""
    folded = quantities.fold_width(text)
    out = []
    for m in quantities._QUANTITY.finditer(folded):
        end = m.end()
        unit = m.group(3)
        if unit == "%":
            p = _PERCENT_P.match(folded, end)
            if p:
                end = p.end()
        elif not unit:
            extra = _EXTRA_UNIT.match(folded, end)
            if extra and _word_ends(folded, extra.end()):
                end = extra.end()
        # A dotted version or section number (1.2.3, 3.10.1) is one token: freeze all of it, not just "1.2".
        version = _VERSION_TAIL.match(folded, end)
        if version and not unit:
            end = version.end()
        out.append((m.start(), end))
    return out


_VERSION_TAIL = re.compile(r"(?:\.\d+)+(?![\d.])")


def _word_ends(text: str, end: int) -> bool:
    """The word ends at `end` or a particle follows (quantities._AFTER_COUNTER): 10달러입니다."""
    after = text[end:end + 1]
    return not ("가" <= after <= "힣") or after in quantities._AFTER_COUNTER


def _money_spans(text: str) -> List[Tuple[int, int]]:
    return [m.span() for m in _MONEY.finditer(text) if _word_ends(text, m.end())]


_UNIT_POWER = re.compile("[A-Za-z]{1,3}[\u00b2\u00b3]")


def _name_spans(text: str) -> List[Tuple[int, int]]:
    out = [m.span() for m in T.NAME_TOKEN.finditer(text)]
    out.extend(m.span() for m in _UNIT_POWER.finditer(text))
    out.extend(m.span() for m in _HAN_RUN.finditer(text))
    return out


def _heading_spans(doc: Document) -> List[Tuple[int, int]]:
    return [(u.start, u.end) for u in doc.units if u.kind == "heading"]


def _url_email_spans(text: str) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
    urls: List[Tuple[int, int]] = []
    emails: List[Tuple[int, int]] = []
    pos = 0
    for line in text.split("\n"):
        urls.extend((pos + a, pos + b) for a, b in T.url_spans(line))
        emails.extend((pos + a, pos + b) for a, b in T.email_spans(line))
        pos += len(line) + 1
    return urls, emails


# --------------------------------------------------------------------------
# keep tokens
# --------------------------------------------------------------------------
def _normalize_cmc(token: str) -> str:
    """ㅋㅋㅋㅋ == ㅋㅋ, ㅠ == ㅠㅠ, ~~~ == ~, !!! == !!; emoji keep their base character."""
    head = token[0]
    if head in "ㅋㅎㅠㅜㅡ":
        return head * 2
    if head in "~～":
        return "~"
    if head in "!?;":
        return head * 2
    if token.startswith("^^"):
        return "^^"
    if ord(head) > 0x2000 and head not in "(<":
        return head
    return token


def _gge_spans(text: str) -> List[Tuple[int, int]]:
    out = []
    for m in _GGE.finditer(text):
        # the syllable right before 께/꺼 (or before the space in "할 께요") must end in ㄹ
        before = text[m.start() - 1] if m.start() > 0 else ""
        if before and _jong(before) == 8 and not (before in _TIME_GGE and m.group(0).lstrip().startswith("께")):
            # the span is the whole eojeol ("전화할께", "연락드릴께요"); the scan back is bounded
            start = m.start() - 1
            floor = max(0, start - 20)
            while start > floor and "가" <= text[start - 1] <= "힣":
                start -= 1
            out.append((start, m.end()))
    return out


def _cmc_spans(masked: str) -> List[Tuple[int, int]]:
    out = []
    n = len(masked)
    for m in T.CMC_RE.finditer(masked):
        a, b = m.span()
        if masked[a] in "~～" and (a == 0 or masked[a - 1].isspace()) and b < n and masked[b] in " \t" \
                and b + 1 < n and not T.CMC_RE.match(masked, b + 1) and not masked[b + 1].isspace():
            continue                 # " ~ " between two words is a range (기원전 900년경 ~ 기원전 206년)
        out.append((a, b))
    return out


def _colloquial_spans(masked: str) -> List[Tuple[int, int]]:
    out = _gge_spans(masked)
    out.extend(m.span() for m in _COLLOQ_LEXEME.finditer(masked))
    return out


def _discourse_spans(masked: str, units: Iterable[Unit]) -> List[Tuple[int, int]]:
    out = []
    for unit in units:
        m = _DISCOURSE_INITIAL.match(masked, unit.start, unit.end)
        if m:
            out.append(m.span(1))
    return out


def keep_tokens(text: str, *, fix_colloquial: bool = False) -> Counter:
    """Multiset of keep tokens of `text` (normally one sentence), quotations masked, as
    Counter{(kind, token)}: ("cmc", "ㅋㅋ"), ("colloquial", "할께"), ("discourse", "사실").
    CMC runs are normalised (ㅋㅋㅋ == ㅋㅋ). With fix_colloquial the opt-in kinds are left out."""
    doc = T.segment(text)
    out: Counter = Counter()
    for span in protected_spans(doc, fix_colloquial=fix_colloquial):
        if span.policy != KEEP:
            continue
        token = text[span.start:span.end]
        out[(span.kind, _normalize_cmc(token) if span.kind == "cmc" else token.strip())] += 1
    return out


# --------------------------------------------------------------------------
# overlap resolution
# --------------------------------------------------------------------------
def _merge_freeze(candidates: List[Tuple[int, int, str]]) -> List[Span]:
    """Union of overlapping freeze candidates; the merged span keeps the best-ranked kind."""
    out: List[Span] = []
    for start, end, kind in sorted(candidates, key=lambda c: (c[0], -c[1], _RANK[c[2]])):
        if end <= start:
            continue
        if out and start < out[-1].end:
            last = out[-1]
            if end > last.end:           # partial overlap: the better-ranked kind names the union
                if _RANK[kind] < _RANK[last.kind]:
                    last.kind = kind
                last.end = end
        else:
            out.append(Span(kind=kind, start=start, end=end, policy=FREEZE))
    return out


def _drop_covered(freeze: List[Span], keep: List[Tuple[int, int, str]]) -> List[Span]:
    starts = [s.start for s in freeze]
    out: List[Span] = []
    last_end = -1
    for start, end, kind in sorted(keep):
        if end <= start or start < last_end:
            continue
        k = bisect_right(starts, end - 1) - 1
        if k >= 0 and freeze[k].end > start:
            continue
        out.append(Span(kind=kind, start=start, end=end, policy=KEEP))
        last_end = end
    return out


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def protected_spans(doc: Document, *, fix_colloquial: bool = False) -> List[Span]:
    """Protected spans of a segmented document, sorted by start; freeze spans never overlap each
    other, and keep-token spans never overlap any span."""
    text = doc.text
    urls, emails = _url_email_spans(text)
    freeze: List[Tuple[int, int, str]] = []
    detectors = (
        ("code", _code_spans(text)), ("url", urls), ("email", emails), ("quote", _quote_spans(text, doc)),
        ("footnote", _footnote_spans(text)), ("heading", _heading_spans(doc)),
        ("markdown", _markdown_spans(text)), ("phone", _phone_spans(text)),
        ("date", [m.span() for m in _DATE.finditer(text)]), ("money", _money_spans(text)),
        ("number", _number_spans(text)), ("handle", [m.span() for m in _HANDLE.finditer(text)]),
        ("hashtag", [m.span() for m in _HASHTAG.finditer(text)]), ("name", _name_spans(text)),
    )
    for kind, spans in detectors:
        freeze.extend((a, b, kind) for a, b in spans)
    merged = _merge_freeze(freeze)
    masked = T.mask_quotes(text)
    keep: List[Tuple[int, int, str]] = [(a, b, "cmc") for a, b in _cmc_spans(masked)]
    if not fix_colloquial:
        keep.extend((a, b, "colloquial") for a, b in _colloquial_spans(masked))
        keep.extend((a, b, "discourse") for a, b in _discourse_spans(masked, doc.units))
    spans = merged + _drop_covered(merged, keep)
    spans.sort(key=lambda s: (s.start, s.end))
    return spans


def spans_in(unit: Unit, spans: Sequence[Span], policy: Optional[str] = None) -> List[Span]:
    """Spans that intersect `unit`, clipped to it (a fenced block or a multi-line quotation
    crosses several units). `spans` must be sorted and non-overlapping, as protected_spans()
    returns them; the lookup is a binary search, so per-sentence calls stay O(log k)."""
    lo, hi = 0, len(spans)
    while lo < hi:                       # first span that starts at or after unit.end
        mid = (lo + hi) // 2
        if spans[mid].start < unit.end:
            lo = mid + 1
        else:
            hi = mid
    out = []
    k = lo - 1
    while k >= 0 and spans[k].end > unit.start:
        span = spans[k]
        if policy is None or span.policy == policy:
            out.append(Span(kind=span.kind, start=max(span.start, unit.start), end=min(span.end, unit.end),
                            policy=span.policy))
        k -= 1
    out.reverse()
    return out


def _squeeze(value: str) -> str:
    return re.sub(r"\s+", "", value)


def freeze_intact(src_unit: Unit, out_text: str, spans: Sequence[Span]) -> bool:
    """True when every freeze span inside `src_unit` still appears verbatim in `out_text`, as
    often as in the source sentence (it may move). number, money and date spans are compared
    without whitespace (3만 원 == 3만원)."""
    needed: Dict[Tuple[bool, str], int] = {}
    for span in spans_in(src_unit, spans, FREEZE):
        value = src_unit.text[span.start - src_unit.start:span.end - src_unit.start]
        loose = span.kind in SPACE_INSENSITIVE
        key = (loose, _squeeze(value) if loose else value)
        if key[1]:
            needed[key] = needed.get(key, 0) + 1
    if not needed:
        return True
    squeezed = None
    for (loose, value), count in needed.items():
        if loose:
            squeezed = _squeeze(out_text) if squeezed is None else squeezed
            if squeezed.count(value) < count:
                return False
        elif out_text.count(value) < count:
            return False
    return True
