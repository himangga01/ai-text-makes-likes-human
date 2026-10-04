"""Floor family of Super Sejong Engine v2 (DESIGN.md 3.8, 3.10): facts that no rewrite may change.

    check(source, output, *, document=None)                 -> list[Violation]   chunk or document
    check_pair(src, out, spans=(), *, document=None)        -> list[Violation]   one aligned sentence pair
    codes(violations)                                       -> list[str]         unique codes, in order

The floor is always enforced (config.ALWAYS_ENFORCED) and every code keeps the name the legacy gate
uses (vendor scripts/checks.py failure codes and engine_runtime/workflow.verify), so gate JSON,
diagnostics counts and the TS parser keep their meaning:

  empty_output            the output is blank (checks.run_checks)
  quote_altered           a direct quotation with a speaker or speech verb is not verbatim
                          (checks.check_quotes at 8+ chars, and workflow's 1+ char variant)
  heading_lost            a heading line disappeared                       (checks.check_headings)
  heading_absorbed        a heading's title survives only inside body prose (checks.check_headings)
  footnote_count          fewer inline footnote markers                    (checks.check_footnotes)
  footnote_numbers        the set of footnote numbers changed
  footnote_def            a footnote definition was lost or altered
  footnote_anchor         a marker moved away from its nearest preceding number
  number_injected         a numeric value the source never had (number words count: 세 배 == 3배)
  number_dropped          a numeric value of the source is gone             (checks.dropped_numbers)
  quantity_changed        signed quantity + unit multiset changed           (quantities.signed_quantities)
  name_changed            the case-folded set of Latin/Han name tokens changed  (workflow.names)
  sentence_dropped        a source sentence lost its counterpart and its own words are not in a
                          neighbour (workflow.dropped_sentences, on the WP-2 alignment)
  protected_span_changed  a freeze span of a source sentence is not verbatim in its aligned
                          output (protect.freeze_intact; new in v2)
  josa_mismatch           a particle allomorph mismatch the rewrite introduced, at "certain"
                          (super_sejong_josa.gate; legacy runs it in the Super Sejong group)

Port. The quotation, heading, footnote and number helpers below are ported from the vendored 윤문
엔진 `vendor/humanize-engine/scripts/checks.py` (label 2.3.2 with the local portal patch), MIT
License, Copyright (c) 2026 epoko77-ai; the vendor module is not imported, so v2 keeps working
after `vendor/` is removed (WP-18). The MIT notice moves to engine_runtime/sejong/THIRD_PARTY.md
with WP-18. One behaviour differs on purpose: footnote_anchor compares the k-th occurrence of a
marker number in the source with the k-th occurrence in the output (the vendor compared every
occurrence with the output's first one, which flags an unchanged text that repeats a marker).

sentence_dropped. The legacy check aligned with the vendor's 1:1-or-gap aligner, so a merge looked
like a gap plus a pair and the gap sentence was cleared by bigram coverage in its neighbours.
WP-2 pairs merges explicitly, so the same coverage test runs on every 1:0 pair (neighbours = the
adjacent pairs) and on each source sentence of a 2:1 merge (against the merged output and the
adjacent pairs). A sentence is dropped when less than MIN_DROPPED_COVERAGE of its own bigrams
(those it does not share with its source neighbours, when it has at least two) survive nearby.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import protect as P
from . import text as T
from .align import Pair, align_documents
from .types import Document, Span, Unit, Violation

try:                                   # imported as engine_runtime.sejong.floor
    from .. import quantities
    from .. import super_sejong_josa as josa
except (ImportError, ValueError):      # imported as sejong.floor with engine_runtime/ on sys.path
    import quantities  # type: ignore[no-redef]
    import super_sejong_josa as josa  # type: ignore[no-redef]

FAMILY = "floor"
# Section 3.8 floor row, in the order check() reports them.
CODES = ("empty_output", "quote_altered", "heading_lost", "heading_absorbed", "footnote_count", "footnote_numbers",
         "footnote_def", "footnote_anchor", "number_injected", "number_dropped", "quantity_changed", "name_changed",
         "sentence_dropped", "protected_span_changed", "josa_mismatch")
MIN_DROPPED_COVERAGE = 0.5           # workflow.MIN_DROPPED_COVERAGE


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------
# summary block (checks.strip_summary_block)
# --------------------------------------------------------------------------
_SUMMARY_BLOCK_RE = re.compile(r"<!--\s*HUMANIZE-SUMMARY\b.*", re.DOTALL)


def strip_summary_block(text: str) -> str:
    """Drop the trailing <!-- HUMANIZE-SUMMARY --> metadata block (it is not rewritten text)."""
    return _SUMMARY_BLOCK_RE.sub("", text).strip()


# --------------------------------------------------------------------------
# headings (checks.extract_headings, check_headings)
# --------------------------------------------------------------------------
_HEADING_PREFIX = re.compile(
    r"^(?:#{1,6}\s+"                      # markdown: ## 제목
    r"|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+\.\s*"          # roman: Ⅱ. 제목
    r"|\d{1,2}\.\s+"                      # arabic: 1. 제목
    r"|\(\d{1,2}\)\s*"                    # parenthesised: (3) 제목
    r"|제\d+[장절]\s*"                    # 제3장 제목
    r")"
)
_PROSE_ENDING = re.compile(r"(?:다|요|음|함|까)\s*[.?!]$")
_DEF_LINE = re.compile(r"^\s*\d{1,3}\)\s")
# Numbered-list styles: consecutive numbers (k, k+1) of the same style are list items, not headings.
_LIST_STYLES = (re.compile(r"^(\d{1,2})\.\s+"), re.compile(r"^\((\d{1,2})\)\s*"))
_TOC_TITLE = re.compile(r"^(?:#{1,6}\s*)?(?:목\s*차|차\s*례|contents|table of contents)\s*:?$", re.IGNORECASE)


def _list_style(line: str) -> Optional[Tuple[int, int]]:
    if line[:1].isspace():
        return None                       # an indented line is a nested item
    s = line.strip()
    for i, rx in enumerate(_LIST_STYLES):
        m = rx.match(s)
        if m:
            return i, int(m.group(1))
    return None


def _is_list_item(lines: List[str], index: int) -> bool:
    """A numbered line continues the nearest numbered line of the same style above or below
    (blank and indented lines skipped); a numbered run right under a contents title is headings."""
    style = _list_style(lines[index])
    if style is None:
        return False
    consecutive = False
    for step in (-1, 1):
        j = index + step
        while 0 <= j < len(lines) and (not lines[j].strip() or lines[j][:1].isspace()):
            j += step
        other = _list_style(lines[j]) if 0 <= j < len(lines) else None
        if other and other[0] == style[0] and other[1] == style[1] + step:
            consecutive = True
    if not consecutive:
        return False
    j = index
    while j > 0 and (not lines[j - 1].strip() or lines[j - 1][:1].isspace() or _list_style(lines[j - 1])):
        j -= 1
    return not (j > 0 and _TOC_TITLE.match(lines[j - 1].strip()))


def extract_headings(text: str) -> List[Tuple[str, str]]:
    """[(normalised heading line, title without numbering), ...]."""
    heads = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        s = line.strip()
        if not s or len(s) > 50 or _DEF_LINE.match(s) or not _HEADING_PREFIX.match(s):
            continue
        if _is_list_item(lines, index) or _PROSE_ENDING.search(s):
            continue
        core = _HEADING_PREFIX.sub("", s).strip()
        if core:
            heads.append((_norm_ws(s), core))
    return heads


def heading_codes(original: str, output: str) -> List[str]:
    found = []
    out_lines = {_norm_ws(line) for line in output.splitlines() if line.strip()}
    out_joined = _norm_ws(output)
    for line, core in extract_headings(original):
        if line not in out_lines:
            found.append("heading_absorbed" if core in out_joined else "heading_lost")
    return found


# --------------------------------------------------------------------------
# footnotes (checks.extract_inline_markers, extract_defs, check_footnotes)
# --------------------------------------------------------------------------
# Inline marker: digits + ')' attached to the preceding character ("증가했다.1)"); a hyphen or a
# Latin letter before the digits is a version or model name ("GPT-4)").
_INLINE_MARKER = re.compile(r"(?<=\S)(?<![(\dA-Za-z\-])(\d{1,3})\)")
_BLOCK_HEADING = re.compile(r"^\s*(?:#{1,6}\s|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+\.\s|제\d+[장절])")
_DEF_LABEL = re.compile(r"(?:^|(?<=\s))(\d{1,3})\)\s")
_NUM_TOKEN = re.compile(r"\d+(?:[.,]\d+)*")
ANCHOR_WINDOW = 50


def extract_inline_markers(text: str) -> List[Tuple[str, int]]:
    """[(footnote number, absolute position), ...] in document order (definition lines skipped)."""
    markers = []
    offset = 0
    for line in text.splitlines(keepends=True):
        if not _DEF_LINE.match(line):
            markers.extend((m.group(1), offset + m.start(1)) for m in _INLINE_MARKER.finditer(line))
        offset += len(line)
    return markers


def _definition_lines(lines: List[str]) -> List[str]:
    """Definition-style lines of every block that ends the text or ends at a heading."""
    found: List[str] = []
    index = 0
    while index < len(lines):
        if not _DEF_LINE.match(lines[index]):
            index += 1
            continue
        end = index
        while end < len(lines) and (not lines[end].strip() or _DEF_LINE.match(lines[end])):
            end += 1
        if end == len(lines) or _BLOCK_HEADING.match(lines[end]):
            found.extend(line for line in lines[index:end] if _DEF_LINE.match(line))
        index = end
    return found


def extract_defs(text: str, markers: Optional[Set[str]] = None) -> Dict[str, str]:
    """{number: normalised definition}; a definition counts only when an inline marker (here or in
    `markers`, the document's markers for a chunk) cites it, so a body "1) 항목" list is not one."""
    defs: Dict[str, str] = {}
    cited = {num for num, _ in extract_inline_markers(text)} | set(markers or ())
    for line in _definition_lines(text.splitlines()):
        first = _DEF_LABEL.match(line.lstrip())
        if first is None or first.group(1) not in cited:
            continue
        labels = [(m.start(), m.group(1)) for m in _DEF_LABEL.finditer(line)]
        for i, (pos, num) in enumerate(labels):
            end = labels[i + 1][0] if i + 1 < len(labels) else len(line)
            defs[num] = _norm_ws(re.sub(r"^\s*\d{1,3}\)\s*", "", line[pos:end]))
    return defs


def _nearest_num_before(text: str, pos: int) -> Optional[str]:
    nums = _NUM_TOKEN.findall(text[max(0, pos - ANCHOR_WINDOW):pos])
    return nums[-1] if nums else None


def footnote_codes(original: str, output: str, document: Optional[str] = None) -> List[str]:
    """`document` is the whole source when `original` is one chunk of it."""
    found: List[str] = []
    in_markers = extract_inline_markers(original)
    out_markers = extract_inline_markers(output)
    cited = {num for num, _ in extract_inline_markers(document)} if document else set()
    in_defs = extract_defs(original, cited)
    if not in_markers and not in_defs:
        return found
    if len(out_markers) < len(in_markers):
        found.append("footnote_count")
    if {n for n, _ in in_markers} != {n for n, _ in out_markers}:
        found.append("footnote_numbers")
    # Anchor proxy: the nearest number token in the 50 chars before the marker (numbers are frozen,
    # so they survive a legitimate rewrite). The k-th occurrence of a number is compared with the
    # k-th occurrence in the output.
    out_positions: Dict[str, List[int]] = {}
    for num, pos in out_markers:
        out_positions.setdefault(num, []).append(pos)
    seen: Counter = Counter()
    for num, pos in in_markers:
        k = seen[num]
        seen[num] += 1
        anchor = _nearest_num_before(original, pos)
        if anchor is None or num not in out_positions:
            continue
        positions = out_positions[num]
        out_anchor = _nearest_num_before(output, positions[min(k, len(positions) - 1)])
        if out_anchor != anchor:
            found.append("footnote_anchor")
            break
    out_defs = extract_defs(output, cited)
    if any(num not in out_defs or out_defs[num] != content for num, content in in_defs.items()):
        found.append("footnote_def")
    return found


# --------------------------------------------------------------------------
# numbers (checks._number_values, dropped_numbers; workflow number-word folding)
# --------------------------------------------------------------------------
_KO_UNIT_MULT = {"백": 100, "천": 1_000, "만": 10_000, "억": 100_000_000, "조": 1_000_000_000_000}


def number_values(text: str) -> Set[str]:
    """Canonical numeric values: thousands commas removed, one attached 백/천/만/억/조 applied
    ("1만" == "10,000" == "10000"); a set, so renumbering and repetition are not changes."""
    values: Set[str] = set()
    for m in _NUM_TOKEN.finditer(text):
        tok = m.group(0).replace(",", "")
        mult = _KO_UNIT_MULT.get(text[m.end():m.end() + 1])
        if mult:
            try:
                val = float(tok) * mult
                values.add(str(int(val)) if val == int(val) else str(val))
                continue
            except ValueError:
                pass
        values.add(tok)
    return values


def _number_word_values(text: str) -> Set[str]:
    return {str(int(value)) for value, _ in quantities.number_words(text)}


def number_codes(source: str, output: str) -> List[str]:
    """number_injected, quantity_changed and number_dropped exactly as workflow.verify computes them."""
    found = []
    wide_source, wide_output = quantities.fold_width(source), quantities.fold_width(output)
    if number_values(wide_output) - number_values(wide_source) - _number_word_values(wide_source):
        found.append("number_injected")
    if quantities.signed_quantities(source) != quantities.signed_quantities(output):
        found.append("quantity_changed")
    if number_values(wide_source) - number_values(wide_output) - _number_word_values(wide_output):
        found.append("number_dropped")
    return found


# --------------------------------------------------------------------------
# quotations (checks.extract_quotes, _is_protected_quote, check_quotes)
# --------------------------------------------------------------------------
MIN_QUOTE_LEN = 8
_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n")
# Speech marks and the "…"라고 + verb attribution: only a quotation with a speaker is frozen; a
# writer's own rhetorical question in quotation marks is the writer's text (vendor policy 2026-08-29).
_SPEECH_MARK_RE = re.compile(
    r"말했|말한다|밝혔|밝힌|강조했|강조한|언급|설명했|설명한다|전했|덧붙"
    r"|지적했|지적한다|답했|묻자|물었|따르면|촉구|당부|호소|주장했|경고했"
)
_ATTRIB_AFTER_RE = re.compile(r'^[""\"]?\s*(?:[이으]?라고|고|[으]?로)\s*[가-힣]{1,8}(?:하|했|한다|된다|였|입니다)')


def _paired(paragraph: str, op: str, cl: str) -> List[str]:
    """re.findall(op + "([^cl]+)" + cl) in one linear scan (the regex rescans to the paragraph end
    from every unclosed opener: 2 s on 100k chars of "“" without a closer)."""
    found: List[str] = []
    pos = 0
    while True:
        i = paragraph.find(op, pos)
        if i < 0:
            break
        j = paragraph.find(cl, i + 1)
        if j < 0:
            break                         # no closer after this opener, so none after a later one
        if j > i + 1:
            found.append(paragraph[i + 1:j])
            pos = j + 1
        else:
            pos = i + 1                   # "“”": empty, try the next opener
    return found


def extract_quotes(text: str, min_len: int = MIN_QUOTE_LEN) -> List[str]:
    """Quotations paired per paragraph, same mark kind only; an odd straight-quote count drops the
    inch/second marks after digits (27" 모니터) before pairing."""
    quotes: List[str] = []
    for paragraph in _PARAGRAPH_SPLIT.split(text):
        for op, cl in (("「", "」"), ("『", "』"), ("“", "”")):
            quotes += _paired(paragraph, op, cl)
        marks = [i for i, ch in enumerate(paragraph) if ch == '"']
        if len(marks) % 2:
            marks = [i for i in marks if not (i > 0 and paragraph[i - 1].isdigit())]
        if len(marks) % 2 == 0:
            quotes += [paragraph[a + 1:b] for a, b in zip(marks[::2], marks[1::2])]
    return [q for q in quotes if len(q.strip()) >= min_len]


def is_protected_quote(original: str, span: str) -> bool:
    i = original.find(span)
    if i < 0:
        return True                       # not found: protect conservatively
    before = original[max(0, i - 30):i]
    cut = max(before.rfind(". "), before.rfind("다. "))
    if cut >= 0:
        before = before[cut + 1:]
    after = original[i + len(span):i + len(span) + 24]
    cut = after.find(". ")
    if cut >= 0:
        after = after[:cut + 1]
    if _ATTRIB_AFTER_RE.search(after):
        return True
    return bool(_SPEECH_MARK_RE.search(before) or _SPEECH_MARK_RE.search(after))


def _quotes_altered(original: str, output: str) -> Tuple[bool, bool]:
    """(checks.check_quotes fails: a quotation of 8+ chars, workflow's variant: any length)."""
    long = short = False
    for q in extract_quotes(original, min_len=1):
        if q not in output and is_protected_quote(original, q):
            short = True
            long = long or len(q.strip()) >= MIN_QUOTE_LEN
    return long, short


def quote_altered(original: str, output: str) -> bool:
    """A protected quotation of any length is no longer verbatim."""
    return _quotes_altered(original, output)[1]


# --------------------------------------------------------------------------
# names (workflow._NAME_TOKEN, workflow.names)
# --------------------------------------------------------------------------
# Latin words (Apple, AI) and Han runs (李文學) are names or terms; their case-folded set must survive.
_NAME_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[.'’\-][A-Za-z0-9]+)*"
                         r"|[㐀-䶿一-鿿豈-﫿]+")


def names(text: str) -> Set[str]:
    return {token.casefold() for token in _NAME_TOKEN.findall(text)}


# --------------------------------------------------------------------------
# dropped sentences (workflow.dropped_sentences on the WP-2 alignment)
# --------------------------------------------------------------------------
def _bigrams(s: str) -> Counter:
    c = "".join(ch for ch in s if ch.isalnum())
    return Counter(c[i:i + 2] for i in range(len(c) - 1))


def _lost(src_text: str, shared_with: Iterable[str], nearby: Iterable[str]) -> bool:
    grams = _bigrams(src_text)
    own = grams - _bigrams(" ".join(shared_with))
    if sum(own.values()) >= 2:
        grams = own
    total = sum(grams.values())
    if not total:
        return False
    near = _bigrams(" ".join(nearby))
    kept = sum(min(count, near[gram]) for gram, count in grams.items())
    return kept / total < MIN_DROPPED_COVERAGE


def dropped_units(src: Document, out: Document, pairs: Sequence[Pair]) -> List[Unit]:
    """Source units whose content did not survive: 1:0 pairs and members of a 2:1 merge."""
    def src_texts(k: int) -> List[str]:
        return [src.units[i].text for i in pairs[k].src] if 0 <= k < len(pairs) else []

    def out_texts(k: int) -> List[str]:
        return [out.units[j].text for j in pairs[k].out] if 0 <= k < len(pairs) else []

    dropped: List[Unit] = []
    for k, pair in enumerate(pairs):
        if not pair.src or (pair.out and len(pair.src) < 2):
            continue
        neighbours_src = src_texts(k - 1) + src_texts(k + 1)
        nearby = out_texts(k - 1) + out_texts(k) + out_texts(k + 1)
        for i in pair.src:
            others = [src.units[x].text for x in pair.src if x != i]
            if _lost(src.units[i].text, neighbours_src + others, nearby):
                dropped.append(src.units[i])
    return dropped


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def _violation(code: str, sentence: Optional[str] = None, detail: str = "") -> Violation:
    return Violation(code=code, family=FAMILY, severity="hard", sentence=sentence, detail=detail)


def codes(violations: Iterable[Violation]) -> List[str]:
    """Unique codes in first-seen order (the legacy hardFailures list)."""
    seen: List[str] = []
    for v in violations:
        if v.code not in seen:
            seen.append(v.code)
    return seen


def _text_of(item: Any) -> str:
    if isinstance(item, str):
        return item
    if hasattr(item, "text"):
        return item.text
    return " ".join(_text_of(part).strip() for part in item)


def text_codes(source: str, output: str, *, document: Optional[str] = None) -> List[str]:
    """The text-level floor codes in workflow.verify's order: the vendor checks (sorted), then
    number_injected, quantity_changed, the short-quote variant of quote_altered, number_dropped,
    name_changed. Summary blocks are ignored by the name check, as in workflow.names."""
    long_quote, any_quote = _quotes_altered(source, output)
    found = sorted(set(heading_codes(source, output)) | set(footnote_codes(source, output, document))
                   | ({"quote_altered"} if long_quote else set()))
    numbers = number_codes(source, output)
    found += [code for code in numbers if code != "number_dropped"]
    if any_quote and "quote_altered" not in found:
        found.append("quote_altered")
    if "number_dropped" in numbers:
        found.append("number_dropped")
    if names(strip_summary_block(source)) != names(strip_summary_block(output)):
        found.append("name_changed")
    return found


def check(source: str, output: str, *, document: Optional[str] = None,
          spans: Optional[Sequence[Span]] = None) -> List[Violation]:
    """Floor violations of a whole chunk (`document` = the whole source for footnote markers) or of
    a whole document (`document` None). Codes appear in workflow.verify's order; sentence_dropped
    and protected_span_changed name the source sentence (ids of text.segment(source)). `spans`
    defaults to protect.protected_spans(segment(source))."""
    source_body, output_body = strip_summary_block(source), strip_summary_block(output)
    if not output_body.strip():
        return [] if not source_body.strip() else [_violation("empty_output")]
    found = [_violation(code) for code in text_codes(source, output, document=document)]
    # Sentence-level checks on the WP-2 alignment of the segmented texts.
    src_doc, out_doc = T.segment(source_body), T.segment(output_body)
    pairs = align_documents(src_doc, out_doc)
    found.extend(_violation("sentence_dropped", unit.id) for unit in dropped_units(src_doc, out_doc, pairs))
    if spans is None:
        spans = P.protected_spans(src_doc)
    found.extend(_protected(src_doc, out_doc, pairs, spans))
    if josa.gate(source, output, None, "certain"):
        found.append(_violation("josa_mismatch"))
    return found


def _protected(src: Document, out: Document, pairs: Sequence[Pair], spans: Sequence[Span]) -> List[Violation]:
    """protected_span_changed per source unit: each freeze span must appear verbatim in the aligned
    output (for a deleted sentence, in the neighbouring outputs, where a merge would have put it)."""
    if not spans:
        return []
    found: List[Violation] = []
    for k, pair in enumerate(pairs):
        if not pair.src:
            continue
        lo, hi = (k, k + 1) if pair.out else (max(0, k - 1), min(len(pairs), k + 2))
        target = " ".join(out.units[j].text for p in pairs[lo:hi] for j in p.out)
        for i in pair.src:
            unit = src.units[i]
            if not P.freeze_intact(unit, target, spans):
                found.append(_violation("protected_span_changed", unit.id))
    return found


def check_pair(src: Any, out: Any, spans: Sequence[Span] = (), *, document: Optional[str] = None,
               sentence: Optional[str] = None) -> List[Violation]:
    """Floor violations of one aligned pair: `src` is a types.Unit (spans in document offsets), a
    str (spans relative to it) or a sequence of units (a 2:1 merge); `out` is the candidate text
    (str, unit or units). An empty candidate is sentence_dropped. Headings and footnotes are
    checked on the pair's lines; `document` supplies the footnote markers cited elsewhere."""
    src_units: List[Unit]
    if isinstance(src, str):
        src_units = [Unit(id=sentence or "S1", start=0, end=len(src), start_u16=0, end_u16=len(src), para=0,
                          kind="body", text=src)]
    elif hasattr(src, "text"):
        src_units = [src]
    else:
        src_units = list(src)
    source = " ".join(unit.text.strip() for unit in src_units)
    output = _text_of(out).strip()
    sid = sentence if sentence is not None else (src_units[0].id if not isinstance(src, str) else None)
    if not source.strip():
        return []
    if not output:
        return [_violation("sentence_dropped", sid)]
    if source == output:
        return []
    found = [_violation(code, sid) for code in text_codes(source, output, document=document)]
    if spans:
        for unit in src_units:
            if not P.freeze_intact(unit, output, spans):
                found.append(_violation("protected_span_changed", unit.id if not isinstance(src, str) else sid))
    if josa.gate(source, output, None, "certain"):
        found.append(_violation("josa_mismatch", sid))
    return found
