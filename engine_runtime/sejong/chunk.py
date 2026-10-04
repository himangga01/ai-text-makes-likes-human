"""Chunking, seams and reassembly of Super Sejong Engine v2 (DESIGN.md 3.2, 3.10, 4.4).

    prepare(run_dir, *, max_single=15000, target=7000, cap=9000, genre="general",
            sanitize_input=True) -> dict       writes chunk_manifest.json (manifest v1) and the chunk files
    reassemble(run_dir, output="03_reassembled.md", report="03_reassembly_report.json") -> dict
    compute_spans(text, *, max_single, target, cap) -> (spans, warnings)
    seam_context(text, start, end, *, body_end=None) -> ((s, e), (s, e))
    seam_ranges(manifest, chunk_index) -> ((s, e), (s, e))
    starts_dependent(text) -> bool             a connective or demonstrative opens the text

Port of vendor scripts/prepare_monolith_input.py and reassemble_chunks.py. Kept as they are: the
manifest v1 fields python-engine.ts parseManifest reads, lossless code-point spans with a SHA-256
and a join self-check, the footnote block at the end of the document as a passthrough chunk,
01_input.txt sanitized in place (00_sanitize.json), stale chunk files removed on re-chunking, and
the whitespace re-attachment of reassembly (the writer's leading and trailing whitespace is
dropped, the source chunk's is put back, so "no rewrite" reassembles to the source byte for byte).
Not written any more: 00_chunk_NN_metrics.json and 01_chunk_NN_input_with_metrics.txt (nothing read
them). The manifest still names an input_file per body chunk, now 01_chunk_NN_input.txt, the plain
chunk text.

Changed, with the rule that can be checked mechanically:

  single      len(text) <= max_single (15,000) is one body span whatever route_hint would have said;
              route_hint is null, route_reason "sejong:single" or "sejong:chunked"
  headings    a heading is a text.line_kind(...) == "heading" line (Markdown "#", 제N장/절/편, a
              Roman numeral, a bracketed title) or an unmarked heading (text.unmarked_heading: a
              one-line paragraph of at most 40 characters without terminal punctuation or a sentence
              ending, before a longer paragraph). "1. ", "1) ", "가. " and "(주)" lines are list
              items and names. No heading forces a cut (the vendor cut before every heading and left
              a median chunk of 574 characters, T5 §5.3). A heading always stays with the paragraph
              that follows it, so no chunk ends on one but the document's own last line. The glue is
              wider than text.unmarked_heading: any one-line paragraph of at most 40 characters that
              does not end in sentence punctuation, before a longer paragraph, also stays with it
              (that includes headings text.unmarked_heading refuses, such as 개요 and 다음, and
              "1. 준비물"-style labels; it costs one cut position, never a cut)
  packing     paragraph-first greedy fill to `target`; a paragraph above `cap` is cut into sentences
              (text.split_sentences), never inside a code fence; consecutive small sections share a
              chunk. A cut that would fall inside a section moves to the latest section start of the
              current chunk when the chunk stays at least 50% of `target`. Blank lines inside a code
              fence do not end the paragraph, and "#" lines there are not headings
  seam rules  a cut is not placed before a paragraph that opens with a connective or a demonstrative
              (starts_dependent): it moves earlier one paragraph at a time while the chunk stays at
              least 50% of `target`, then later one paragraph at a time while the chunk stays within
              `cap`, else it stays where the fill put it. A last chunk under 25% of `target` joins the
              one before it when both fit in `cap`
  seams       per body chunk, the read-only context of DESIGN 3.2: the last one or two source
              paragraphs before the chunk (at most 600 characters) and the first paragraph after it
              (at most 300), taken from the source document and not from any rewrite, so chunks still
              run in parallel. Stored as manifest["sejong"]["seams"] = [{"chunk": i, "prev": [s, e],
              "next": [s, e]}]; [0, 0] means none and a chunk without an entry has none. Offsets are
              CODE POINTS into the prepared document (01_input.txt), like every offset of the plan,
              which is what prompt.ts seamContextFrom slices (Array.from(documentText))
  reassembly  a chunk whose rewrite is empty or whose length ratio (stripped rewrite over stripped
              source) is below 0.5 or above 2.0 is replaced by its source chunk and reported
              (report["rolled_back_chunks"], report["warning_codes"] = ["CHUNK_ROLLED_BACK"]); the
              vendor failed the whole job. A SHA, span or missing-file problem still raises
              ReassemblyError

Every pass is a linear scan or a bisect; there is no quadratic path in the text length.
"""
from __future__ import annotations

import datetime
import hashlib
import re
from bisect import bisect_right
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from . import text as T
from .io import read_json, read_text, write_json, write_text
from .types import GENRES

PathLike = Union[str, Path]
Range = Tuple[int, int]

MANIFEST_VERSION = 1
MAX_SINGLE = 15000
TARGET = 7000
CAP = 9000
MIN_FILL = 0.5              # a cut moved for a section or seam rule leaves a chunk of at least this share of target
TAIL_FILL = 0.25            # a last chunk below this share of target joins its predecessor (within cap)
PREV_CONTEXT_CHARS = 600
PREV_CONTEXT_PARAGRAPHS = 2
NEXT_CONTEXT_CHARS = 300
RATIO_MIN = 0.5             # vendor reassemble_chunks.py thresholds
RATIO_MAX = 2.0
ROLLBACK_CODE = "CHUNK_ROLLED_BACK"

SOURCE_FILE = "01_input.txt"
MANIFEST_FILE = "chunk_manifest.json"
SANITIZE_FILE = "00_sanitize.json"
# Files a re-chunking invalidates (vendor list): stale rewrites must never reach a new reassembly.
STALE_PATTERNS = ("00_chunk_*", "01_chunk_*", "02_chunk_*_rewritten.txt", "03_reassembled.md",
                  "03_reassembly_report.json")


class ChunkingError(RuntimeError):
    """Empty input or a violated lossless invariant while chunking: a fidelity incident."""


class ReassemblyError(ValueError):
    """The run directory cannot be reassembled safely (missing or changed files, damaged manifest)."""


# ==========================================================================
# footnote block (vendor find_footnote_block_start, unchanged behaviour)
# ==========================================================================
FOOTNOTE_LINE_RE = re.compile(r"^(?:\d+\)\s|\[\d+\]\s)")


def _line_spans(text: str) -> List[Tuple[int, int]]:
    """(start, end) of each line, newline included; the spans join back into the text."""
    spans: List[Tuple[int, int]] = []
    pos, n = 0, len(text)
    while pos < n:
        nl = text.find("\n", pos)
        if nl < 0:
            spans.append((pos, n))
            break
        spans.append((pos, nl + 1))
        pos = nl + 1
    return spans


def find_footnote_block_start(text: str) -> Optional[int]:
    """Offset where the trailing block of footnote definition lines ("1) …", "[1] …") starts, or None.
    Walks back from the end over blank lines and definition lines and stops at any other line; at
    least one definition line is needed."""
    start: Optional[int] = None
    for line_start, line_end in reversed(_line_spans(text)):
        line = text[line_start:line_end]
        if not line.strip():
            continue
        if FOOTNOTE_LINE_RE.match(line):
            start = line_start
            continue
        break
    return start


# ==========================================================================
# seam rules: a connective or demonstrative opens a paragraph
# ==========================================================================
# T5_flowlib.CONN_CATS verbatim (T5 §5.3 measured the vendor chunker with these words). The
# acceptance measurement uses T5's own functions, not this table.
CONNECTIVES = (
    "그리고", "또한", "또", "게다가", "더욱이", "더구나", "나아가", "아울러", "더불어", "한편", "이와 더불어",
    "이와 함께", "뿐만 아니라",
    "그러나", "하지만", "그렇지만", "그런데", "반면에", "반면", "그럼에도 불구하고", "그럼에도", "이와 달리",
    "이와 반대로", "다만", "그러면서도",
    "그래서", "그러므로", "그러니까", "따라서", "이에 따라", "이로 인해", "이로써", "결과적으로", "결국", "그러면",
    "그렇다면", "그러다 보니", "이 때문에", "그 결과",
    "예를 들어", "예를 들면", "예컨대", "가령", "즉", "다시 말해", "다시 말하면", "특히", "물론", "무엇보다도",
    "무엇보다", "사실", "실제로",
    "결론적으로", "요약하면", "요약하자면", "정리하면", "정리하자면", "종합하면", "이처럼", "이와 같이", "이렇듯",
    "이러한 점에서", "이런 점에서",
    "먼저", "우선", "다음으로", "첫째", "둘째", "셋째", "첫 번째", "두 번째", "세 번째", "마지막으로", "끝으로",
    "이어서", "그다음", "그 다음",
)
# Demonstrative and anaphoric openers: T5 _DEM_PRON_INIT and _DEM_N_TOPIC (이/그 + noun + 은/는:
# "이곳은", "그 사람은"), plus the bare determiner 이/그/저 before a noun ("이 방법을") and the
# common pronoun forms.
DEMONSTRATIVES = (
    "이는", "이것은", "이것이", "이를", "이로", "이에", "이와", "이에도", "이 때문에", "이 점", "이러한", "이런",
    "이같은", "이 같은", "그러한", "그런", "그에", "그로", "그와", "그를", "이건", "그건", "이게", "그게", "이거",
    "그거", "이것", "그것", "그는", "그녀는", "그들은", "이들은", "이렇게", "그렇게", "이때", "그때", "이처럼",
    "그처럼",
)


def _phrase(word: str) -> str:
    return r"\s+".join(re.escape(part) for part in word.split(" "))


_CONNECTIVE_RE = re.compile(
    "(?:" + "|".join(_phrase(w) for w in sorted(CONNECTIVES, key=lambda w: -len(w))) + r")(?=[\s,，*_\"'”’」』)]|$)")
_DEMONSTRATIVE_RE = re.compile(
    "(?:" + "|".join(_phrase(w) for w in sorted(DEMONSTRATIVES, key=lambda w: -len(w)))
    + r")(?![가-힣])|(?:이|그)\s?[가-힣]{1,6}(?:은|는)(?=\s)|(?:이|그|저)(?=\s+[가-힣])")
# What may precede the first word: quotes, brackets, emphasis marks, a bullet (a list marker is skipped first).
_OPENING = re.compile("[\\s\"'“”‘’(「『《〈*_>•·▪-]*")


def starts_dependent(text: str) -> bool:
    """True when `text` opens with a connective ("그러나", "예를 들어") or a demonstrative ("이는",
    "이 방법은", "그는"), after a list marker, quotes and emphasis marks. A chunk that starts like this
    leans on the paragraph before it, so a cut is not placed before it when another cut is possible.
    A heading is not checked here; callers pass the first line of a body paragraph."""
    head = text[:160]
    marker = T.LIST_MARKER.match(head)
    pos = _OPENING.match(head, marker.end() if marker else 0).end()
    return bool(_CONNECTIVE_RE.match(head, pos) or _DEMONSTRATIVE_RE.match(head, pos))


# ==========================================================================
# document scan: paragraphs, blocks, pieces
# ==========================================================================
_SENTENCE_END = re.compile(r"[.!?。！？…][\"'”’」』)\]]*$")
_LETTER = re.compile(r"[가-힣A-Za-z0-9]")


def _glue_line(line: str, following: int) -> bool:
    """A short line without sentence-final punctuation before a longer paragraph: a title, a label or a
    lead-in ending in a colon. A cut right after it would orphan it. This is wider than
    text.unmarked_heading, which also refuses a line ending in a prose syllable (개요, 다음, 필요): for
    a heading that costs an orphan, for a short sentence it only costs one cut position."""
    s = line.strip()
    return bool(s) and len(s) <= T.UNMARKED_HEADING_MAX and following > len(s) and not _SENTENCE_END.search(s) \
        and bool(_LETTER.search(s))


class _Par:
    """A paragraph: a maximal run of non-blank lines (blank lines inside a code fence do not end it)."""
    __slots__ = ("start", "last", "lines", "unmarked", "glue")

    def __init__(self, start: int):
        self.start = start
        self.last = start                                   # end of the last line, newline excluded
        self.lines: List[Tuple[int, int, str]] = []         # (line start, line end, kind)
        self.unmarked = False                               # a one-line unmarked heading (text.unmarked_heading)
        self.glue = False                                   # must stay with the paragraph after it


class _Piece:
    """The indivisible run [start, end) between two possible cuts. Pieces tile the body."""
    __slots__ = ("start", "end", "section", "heading", "dependent")

    def __init__(self, start: int, end: int, section: bool, heading: Optional[str], dependent: bool):
        self.start = start
        self.end = end
        self.section = section          # starts with a heading
        self.heading = heading          # that heading, stripped
        self.dependent = dependent      # no heading, and opens with a connective or a demonstrative


class _Scan:
    """Paragraphs of `body` and the pieces a cut may fall between."""

    def __init__(self, body: str, cap: int):
        self.body = body
        self.cap = cap
        self.ends_with_heading = False
        fences = T.fence_ranges(body)
        self.fence_starts = [a for a, _ in fences]
        self.fence_ends = [b for _, b in fences]
        self.paras = self._paragraphs()
        self.para_starts = [p.start for p in self.paras]
        self.pieces = self._pieces()

    def _paragraphs(self) -> List[_Par]:
        body = self.body
        fence_starts, fence_ends = self.fence_starts, self.fence_ends
        paras: List[_Par] = []
        cur: Optional[_Par] = None
        fi = 0
        pos, n = 0, len(body)
        while pos < n:
            nl = body.find("\n", pos)
            end = n if nl < 0 else nl
            while fi < len(fence_starts) and fence_ends[fi] <= pos:
                fi += 1
            in_fence = fi < len(fence_starts) and fence_starts[fi] <= pos
            raw = body[pos:end]
            if in_fence or raw.strip():
                if cur is None:
                    cur = _Par(pos)
                    paras.append(cur)
                cur.lines.append((pos, end, "code" if in_fence else T.line_kind(raw.rstrip("\r"))))
                cur.last = end
            else:
                cur = None
            pos = n if nl < 0 else nl + 1
        for i, par in enumerate(paras):
            par.glue = all(kind == "heading" for _, _, kind in par.lines)
            if len(par.lines) == 1 and par.lines[0][2] == "body":
                nxt = paras[i + 1] if i + 1 < len(paras) else None
                following = len(body[nxt.start:nxt.last].strip()) if nxt else 0
                line = body[par.start:par.last].strip()
                par.unmarked = T.unmarked_heading(line, following)
                par.glue = par.unmarked or _glue_line(line, following)
        return paras

    def _blocks(self) -> List[Tuple[int, bool, Optional[str]]]:
        """(start, section, heading) of each block: a paragraph, split before any heading line inside it,
        with the heading-only runs in front of it glued on. Blocks tile the body (a block ends where the
        next starts); a heading run at the very end joins the last block."""
        body = self.body
        blocks: List[Tuple[int, bool, Optional[str]]] = []
        pending: Optional[Tuple[int, bool, Optional[str]]] = None
        for index, par in enumerate(self.paras):
            groups: List[List[Tuple[int, int, str]]] = []
            group: List[Tuple[int, int, str]] = []
            for line in par.lines:
                if line[2] == "heading" and group:
                    groups.append(group)
                    group = []
                group.append(line)
            groups.append(group)
            for g, members in enumerate(groups):
                section = par.unmarked or members[0][2] == "heading"
                if pending is None:
                    start = 0 if index == 0 and g == 0 else members[0][0]
                    heading = body[members[0][0]:members[0][1]].strip() if section else None
                    pending = (start, section, heading)
                if not (len(members) == 1 and (par.glue or members[0][2] == "heading")):
                    blocks.append(pending)
                    pending = None
        if pending is not None:
            self.ends_with_heading = True
            if not blocks:
                blocks.append(pending)
        return blocks

    def _pieces(self) -> List[_Piece]:
        blocks = self._blocks()
        pieces: List[_Piece] = []
        for k, (start, section, heading) in enumerate(blocks):
            end = blocks[k + 1][0] if k + 1 < len(blocks) else len(self.body)
            if end - start > self.cap:
                pieces.extend(self._explode(start, end, section, heading))
            else:
                pieces.append(self._piece(start, end, section, heading))
        return pieces

    def _piece(self, start: int, end: int, section: bool, heading: Optional[str]) -> _Piece:
        line_end = self.body.find("\n", start, end)
        first = self.body[start:end if line_end < 0 else line_end]
        return _Piece(start, end, section, heading, not section and starts_dependent(first))

    def _explode(self, start: int, end: int, section: bool, heading: Optional[str]) -> List[_Piece]:
        """A block above cap: one piece per sentence unit. Units of a heading line or of a paragraph that
        must stay with the next one (a glue paragraph) are glued to the unit after them, and no cut falls
        inside a code fence."""
        body = self.body
        units = T.split_sentences(body[start:end], base=start)
        if len(units) < 2:
            return [self._piece(start, end, section, heading)]
        titles: Dict[int, str] = {}               # unit index -> heading text (a heading starts the piece)
        glue = [False] * len(units)               # unit k is glued to unit k + 1
        for k, unit in enumerate(units):
            par = self._par_at(unit.start)
            if unit.kind == "heading" or (par is not None and par.unmarked):
                titles[k] = unit.text.strip()
            glue[k] = k + 1 < len(units) and (unit.kind == "heading" or (par is not None and par.glue))
        cuts = [(start, 0)] + [(units[k].start, k) for k in range(1, len(units))
                               if not glue[k - 1] and not self._in_fence(units[k].start)]
        out: List[_Piece] = []
        for c, (cut, k) in enumerate(cuts):
            piece_end = cuts[c + 1][0] if c + 1 < len(cuts) else end
            first = body[cut:piece_end].split("\n", 1)[0]
            if c == 0:
                out.append(_Piece(cut, piece_end, section, heading, not section and starts_dependent(first)))
            else:
                title = titles.get(k)
                out.append(_Piece(cut, piece_end, title is not None, title, title is None and starts_dependent(first)))
        return out

    def _par_at(self, pos: int) -> Optional[_Par]:
        k = bisect_right(self.para_starts, pos) - 1
        return self.paras[k] if k >= 0 and pos <= self.paras[k].last else None

    def _in_fence(self, pos: int) -> bool:
        """pos lies inside a fenced code block (after its opening fence): a cut there would leave a chunk
        with an unbalanced fence, and everything after it would read as code."""
        k = bisect_right(self.fence_starts, pos) - 1
        return k >= 0 and pos < self.fence_ends[k] and pos > self.fence_starts[k]


# ==========================================================================
# spans
# ==========================================================================
def _pack(pieces: Sequence[_Piece], target: int, cap: int) -> List[Tuple[int, int]]:
    """Piece-index ranges [i, j) of the chunks: greedy fill to `target`, then the section and seam
    rules of the module docstring."""
    n = len(pieces)
    floor = MIN_FILL * target

    def size(i: int, j: int) -> int:
        return pieces[j - 1].end - pieces[i].start

    def choose(i: int, c: int) -> int:
        """The cut before piece c, moved when a rule asks for it."""
        if not pieces[c].section:                          # a cut inside a section: prefer a section start
            k = c - 1
            while k > i and size(i, k) >= floor:
                if pieces[k].section:
                    return k
                k -= 1
        if not pieces[c].dependent:
            return c
        k = c - 1                                          # seam rule: earlier, then later, else stay
        while k > i and size(i, k) >= floor:
            if not pieces[k].dependent:
                return k
            k -= 1
        k = c + 1
        while k < n and size(i, k) <= cap:
            if not pieces[k].dependent:
                return k
            k += 1
        return c

    ranges: List[Tuple[int, int]] = []
    i = 0
    while i < n:
        j = i + 1
        while j < n and size(i, j + 1) <= target:
            j += 1
        if j < n:
            j = choose(i, j)
        ranges.append((i, j))
        i = j
    if len(ranges) >= 2:
        (pi, _), (li, lj) = ranges[-2], ranges[-1]
        if size(li, lj) < TAIL_FILL * target and size(pi, lj) <= cap:
            ranges[-2:] = [(pi, lj)]
    return ranges


def _chunk(text: str, max_single: int, target: int, cap: int) -> Tuple[List[dict], List[str], Optional[_Scan], int]:
    """(spans, warnings, scan of the body, body end). The scan is None when there is no body."""
    warnings: List[str] = []
    if not 0 < target <= cap:
        raise ValueError("target must be positive and at most cap")
    footnote = find_footnote_block_start(text)
    body_end = len(text) if footnote is None else footnote
    spans: List[dict] = []
    scan: Optional[_Scan] = None
    if body_end > 0:
        scan = _Scan(text[:body_end], cap)
        pieces = scan.pieces
        if len(text) <= max_single or not pieces:
            ranges = [(0, len(pieces))] if pieces else []
        else:
            ranges = _pack(pieces, target, cap)
        for i, j in ranges:
            first = pieces[i]
            spans.append({"start": first.start, "end": pieces[j - 1].end, "passthrough": False,
                          "heading": first.heading if first.section else None})
            size = pieces[j - 1].end - first.start
            if len(text) > max_single and size > cap:
                warnings.append(
                    f"문장 경계로 쪼갤 수 없는 초장 구간 {size}자 (offset {first.start}) — 상한({cap}) 초과 허용, 검토 요망"
                    if j - i == 1 else f"청크 {len(spans)} 크기 {size}자 — 상한({cap}) 초과")
        if not spans:                                       # a body without a single paragraph
            spans.append({"start": 0, "end": body_end, "passthrough": False, "heading": None})
        if len(text) > max_single and scan.ends_with_heading:
            warnings.append(f"청크 {len(spans)}가 헤딩으로 끝남 — 뒤따르는 본문이 없는 문서 말미 헤딩")
    if footnote is not None:
        spans.append({"start": footnote, "end": len(text), "passthrough": True, "heading": None})
    if "".join(text[s["start"]:s["end"]] for s in spans) != text:
        raise ChunkingError(
            f"lossless self-check failed: the chunks do not join back into the text ({len(text)} characters)")
    return spans, warnings, scan, body_end


def compute_spans(text: str, *, max_single: int = MAX_SINGLE, target: int = TARGET,
                  cap: int = CAP) -> Tuple[List[dict], List[str]]:
    """([{"start", "end", "passthrough", "heading"}], warnings): the chunk spans of `text`, in order,
    contiguous from 0 to len(text); the footnote block, if any, is the last span (passthrough).
    Raises ChunkingError when the spans do not join back into the text."""
    if not text:
        return [], []
    spans, warnings, _, _ = _chunk(text, max_single, target, cap)
    return spans, warnings


# ==========================================================================
# seam context
# ==========================================================================
def _tail_context(scan: _Scan, start: int, limit: int, paragraphs: int) -> Range:
    """The last one or two paragraphs before `start` within `limit` characters."""
    body = scan.body
    end = start
    while end > 0 and body[end - 1].isspace():
        end -= 1
    if end <= 0:
        return (0, 0)
    k = bisect_right(scan.para_starts, end - 1) - 1
    if k < 0:
        return (0, 0)
    first = scan.para_starts[k]
    if paragraphs >= 2 and k >= 1 and end - scan.para_starts[k - 1] <= limit:
        return (scan.para_starts[k - 1], end)
    if end - first <= limit:
        return (first, end)
    # The last paragraph alone is too long: its last whole sentences, else a word-boundary cut.
    lo = max(first, end - 2 * limit)
    for unit in T.split_sentences(body[lo:end], base=lo):
        if end - unit.start <= limit:
            return (unit.start, end)
    cut = end - limit
    space = re.compile(r"\s").search(body, cut, end)
    if space is None:
        return (cut, end)
    pos = space.end()
    while pos < end and body[pos].isspace():
        pos += 1
    return (pos, end) if pos < end else (cut, end)


def _head_context(scan: _Scan, body_end: int, end: int, limit: int) -> Range:
    """The first paragraph after `end` within `limit` characters; a heading paragraph takes the
    paragraph after it."""
    body = scan.body
    begin = end
    while begin < body_end and body[begin].isspace():
        begin += 1
    if begin >= body_end:
        return (0, 0)
    k = bisect_right(scan.para_starts, begin) - 1
    stop = begin
    if k >= 0:
        stop = max(stop, scan.paras[k].last)
        while scan.paras[k].glue and k + 1 < len(scan.paras):
            k += 1
            stop = scan.paras[k].last
    stop = min(stop, body_end)
    if stop - begin <= limit:
        return (begin, stop)
    # Too long: the first whole sentences (at least one that is not a heading), else a word-boundary cut.
    best = 0
    seen_body = False
    for unit in T.split_sentences(body[begin:min(stop, begin + 2 * limit)], base=begin):
        seen_body = seen_body or unit.kind != "heading"
        if seen_body and unit.end - begin <= limit:
            best = unit.end
    if best:
        return (begin, best)
    cut = begin + limit
    pos = max(body.rfind(ch, begin, cut) for ch in (" ", "\n", "\t"))
    while pos > begin and body[pos - 1].isspace():
        pos -= 1
    return (begin, pos) if pos > begin else (begin, cut)


def _seam(scan: _Scan, start: int, end: int, body_end: int, prev_chars: int, next_chars: int,
          prev_paragraphs: int) -> Tuple[Range, Range]:
    return _tail_context(scan, start, prev_chars, prev_paragraphs), _head_context(scan, body_end, end, next_chars)


def seam_context(text: str, start: int, end: int, *, body_end: Optional[int] = None,
                 prev_chars: int = PREV_CONTEXT_CHARS, next_chars: int = NEXT_CONTEXT_CHARS,
                 prev_paragraphs: int = PREV_CONTEXT_PARAGRAPHS) -> Tuple[Range, Range]:
    """((prev_start, prev_end), (next_start, next_end)) code-point ranges into `text` for the chunk
    [start, end): the last one or two paragraphs before `start` that fit in `prev_chars` (a longer
    paragraph gives its last whole sentences) and the first paragraph after `end` within `next_chars`
    (a heading paragraph takes the paragraph after it; a longer paragraph gives its first whole
    sentences). The ranges hold no leading or trailing whitespace. [0, 0] = none: at the start of the
    document, or where the footnote block begins (`body_end`, default len(text))."""
    limit = len(text) if body_end is None else body_end
    return _seam(_Scan(text[:limit], CAP), start, end, limit, prev_chars, next_chars, prev_paragraphs)


def seam_ranges(manifest: dict, chunk_index: int) -> Tuple[Range, Range]:
    """The seam of chunk `chunk_index` (1-based) from a manifest, ((0, 0), (0, 0)) when it has none."""
    for seam in (manifest.get("sejong") or {}).get("seams", []):
        if seam.get("chunk") == chunk_index:
            return (seam["prev"][0], seam["prev"][1]), (seam["next"][0], seam["next"][1])
    return (0, 0), (0, 0)


# ==========================================================================
# prepare
# ==========================================================================
def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prepare(run_dir: PathLike, *, max_single: int = MAX_SINGLE, target: int = TARGET, cap: int = CAP,
            genre: str = "general", sanitize_input: bool = True) -> dict:
    """Chunk <run_dir>/01_input.txt and write chunk_manifest.json (manifest v1 plus the "sejong"
    block), 01_chunk_NN_input.txt for each body chunk (the plain chunk text) and, when sanitizing
    changed the input, 00_sanitize.json. The input file is sanitized in place. Returns the manifest.
    Raises ChunkingError for empty input or a failed self-check; an OSError when the input is missing."""
    run = Path(run_dir)
    if genre not in GENRES:
        raise ValueError(f"unknown genre {genre!r}")
    source_path = run / SOURCE_FILE
    text = read_text(source_path)
    if sanitize_input:
        cleaned, report = T.sanitize(text)
        if report["changed"]:
            write_text(source_path, cleaned)
            write_json(run / SANITIZE_FILE, report)
        text = cleaned
    if not text.strip():
        raise ChunkingError(f"{SOURCE_FILE} is empty; nothing to chunk")

    spans, warnings, scan, body_end = _chunk(text, max_single, target, cap)
    mode = "single" if len(text) <= max_single else "chunked"

    for pattern in STALE_PATTERNS:
        for stale in sorted(run.glob(pattern)):
            stale.unlink()

    entries: List[dict] = []
    seams: List[dict] = []
    for index, span in enumerate(spans, 1):
        entry = {
            "index": index, "start": span["start"], "end": span["end"], "char_count": span["end"] - span["start"],
            "starts_with_heading": span["heading"] is not None, "heading": span["heading"],
            "passthrough": span["passthrough"], "input_file": None, "rewritten_file": None,
        }
        if not span["passthrough"]:
            entry["input_file"] = f"01_chunk_{index:02d}_input.txt"
            entry["rewritten_file"] = f"02_chunk_{index:02d}_rewritten.txt"
            write_text(run / entry["input_file"], text[span["start"]:span["end"]])
            if mode == "chunked" and scan is not None:
                prev, nxt = _seam(scan, span["start"], span["end"], body_end, PREV_CONTEXT_CHARS,
                                  NEXT_CONTEXT_CHARS, PREV_CONTEXT_PARAGRAPHS)
                if prev != (0, 0) or nxt != (0, 0):
                    seams.append({"chunk": index, "prev": list(prev), "next": list(nxt)})
        entries.append(entry)

    manifest = {
        "version": MANIFEST_VERSION,
        "created": datetime.date.today().isoformat(),
        "source_file": SOURCE_FILE,
        "source_chars": len(text),
        "source_sha256": _sha256(text),
        "genre": genre,
        "target_chunk_chars": target,
        "max_chunk_chars": cap,
        "route_hint": None,
        "route_reason": f"sejong:{mode}",
        "processing_mode": mode,
        "chunk_count": len(entries),
        "body_chunk_count": sum(1 for e in entries if not e["passthrough"]),
        "passthrough_chunk_count": sum(1 for e in entries if e["passthrough"]),
        "lossless_check": "ok",
        "warnings": warnings,
        "chunks": entries,
        "sejong": {"version": 1, "genre": genre, "seams": seams},
    }
    write_json(run / MANIFEST_FILE, manifest)
    return manifest


# ==========================================================================
# reassemble
# ==========================================================================
def _leading_ws(s: str) -> str:
    return s[:len(s) - len(s.lstrip())]


def _trailing_ws(s: str) -> str:
    return s[len(s.rstrip()):]


def _leaf(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value or value in (".", ".."):
        raise ReassemblyError(f"{label} must be a plain file name")
    return value


def _load_run(run: Path) -> Tuple[List[dict], str]:
    """(chunks, source text) of a run directory after the SHA-256, join and file checks."""
    manifest_path = run / MANIFEST_FILE
    if not manifest_path.exists():
        raise ReassemblyError(f"{MANIFEST_FILE} not found in the run directory; chunk first")
    try:
        manifest = read_json(manifest_path)
        chunks = manifest["chunks"]
        source_path = run / _leaf(manifest["source_file"], "source_file")
        if not source_path.exists():
            raise ReassemblyError("the source file is missing")
        text = read_text(source_path)
        if _sha256(text) != manifest.get("source_sha256"):
            raise ReassemblyError("the input changed after chunking (sha256 mismatch); chunk again")
        if "".join(text[c["start"]:c["end"]] for c in chunks) != text:
            raise ReassemblyError("the manifest spans do not join back into the input; chunk again")
        missing = [_leaf(c["rewritten_file"], "rewritten_file") for c in chunks if not c["passthrough"]]
    except ReassemblyError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise ReassemblyError(f"damaged manifest ({type(error).__name__})") from error
    missing = [name for name in missing if not (run / name).exists()]
    if missing:
        raise ReassemblyError(f"{len(missing)} rewrite file(s) missing: {', '.join(missing)}")
    return chunks, text


def reassemble(run_dir: PathLike, output: str = "03_reassembled.md",
               report: str = "03_reassembly_report.json") -> dict:
    """Join the chunks of <run_dir> into `output` and write the length report to `report`.

    Each body chunk's rewrite (02_chunk_NN_rewritten.txt) is stripped of surrounding whitespace and
    given back the whitespace of its source chunk; passthrough chunks are copied verbatim. A rewrite
    that is empty or whose length ratio is below RATIO_MIN or above RATIO_MAX is replaced by the
    source chunk. Returns the report: the vendor keys (source_chars, output_chars, total_ratio,
    warnings, chunks[index, passthrough, orig_chars, rewritten_chars, ratio]) plus, per body chunk,
    rolled_back and rollback_reason ("empty", "ratio_low", "ratio_high"), and at the top
    rolled_back_chunks and warning_codes. Raises ReassemblyError when the input changed since
    chunking (SHA-256), the spans do not cover it, or a rewrite file is missing."""
    run = Path(run_dir)
    chunks, text = _load_run(run)
    pieces: List[str] = []
    entries: List[dict] = []
    warnings: List[str] = []
    rolled_back: List[int] = []
    for c in chunks:
        orig = text[c["start"]:c["end"]]
        index = c["index"]
        if c["passthrough"]:
            pieces.append(orig)
            entries.append({"index": index, "passthrough": True, "orig_chars": len(orig)})
            continue
        core_orig = orig.strip()
        core_new = read_text(run / c["rewritten_file"]).strip()
        reason: Optional[str] = None
        ratio = 1.0
        if core_orig:
            ratio = len(core_new) / len(core_orig)
            reason = "empty" if not core_new else "ratio_low" if ratio < RATIO_MIN \
                else "ratio_high" if ratio > RATIO_MAX else None
        pieces.append(orig if reason or not core_orig else _leading_ws(orig) + core_new + _trailing_ws(orig))
        entry = {"index": index, "passthrough": False, "orig_chars": len(core_orig),
                 "rewritten_chars": len(core_new), "ratio": round(ratio, 3), "rolled_back": reason is not None}
        if reason is not None:
            entry["rollback_reason"] = reason
            rolled_back.append(index)
            what = {"empty": "윤문 결과가 비어 있음", "ratio_low": "유실 의심", "ratio_high": "증식 의심"}[reason]
            warnings.append(f"청크 {index}: 원문 {len(core_orig)}자 → {len(core_new)}자 ({ratio:.0%}) — {what}, 원문으로 되돌림")
        entries.append(entry)

    joined = "".join(pieces)
    write_text(run / output, joined)
    result = {
        "source_chars": len(text),
        "output_chars": len(joined),
        "total_ratio": round(len(joined) / len(text), 3) if text else None,
        "warnings": warnings,
        "rolled_back_chunks": rolled_back,
        "warning_codes": [ROLLBACK_CODE] if rolled_back else [],
        "chunks": entries,
    }
    write_json(run / report, result)
    return result
