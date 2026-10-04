"""Sentence alignment between a source chunk and a candidate rewrite (DESIGN.md 3.8, 6).

    align(src, out, *, band=None)          -> list[Pair]
    align_documents(src, out, *, band=None) -> list[Pair]
    Pair(src: tuple[int, ...], out: tuple[int, ...], score: float)

Inputs. A sentence is a str or any object with a `.text` attribute (types.Unit). align()
takes two flat sentence lists; when every item also has a `.para` attribute it is grouped
into paragraphs by that value and aligned paragraph-first, otherwise the lists are aligned
as one block. align_documents() takes, on each side, a types.Document (its units, grouped by
`.para`), a flat list of units with `.para`, or an explicit list of paragraphs (each a list of
sentences). Indices in a Pair always refer to the flattened sentence list of that side, in
order, so `Pair.src == (3,)` is the fourth source sentence of the chunk.

Output. Pairs are in document order and cover every source and candidate index exactly once.
Shapes: 1:1, 1:2 (split), 2:1 (merge), 1:0 (source sentence deleted), 0:1 (sentence
inserted). `score` is the character-bigram Dice of the paired texts (the two sides of a split
or merge are joined first), 0.0 for an insertion or a deletion.

Method (ported from T2 gate.align; scores and tie-breaking kept so results agree with it):
  similarity  Dice of character-bigram sets over Hangul syllables, compatibility jamo,
              Latin letters, digits and CJK ideographs (spaces and punctuation ignored, so
              particle and ending changes cost little)
  moves       1:1 = dice, 1:2 and 2:1 = 2*dice(joined) - 1, 1:0 and 0:1 = -0.15;
              forward relaxation in row-major order, first move wins a tie
  paragraphs  equal non-empty paragraph counts and no paragraph pair displaced (below) ->
              one DP per paragraph pair; otherwise one global DP over all sentences
  band        each DP only visits cells within `2*|n-m| + 8` of the scaled diagonal
              (round(i*m/n)), so the cost is O((n+m) * band) instead of O(n*m); a block
              is capped at MAX_CELLS cells, which narrows the band only when a long block
              gained or lost hundreds of sentences
  trimming    identical sentences at the start and end of a block are paired 1:1 before
              the DP runs (the replacement protocol leaves most sentences untouched)

A paragraph pair (i, i) counts as displaced when its paragraph-level Dice is below
PARA_FLOOR and a neighbouring paragraph on either side matches it better; that happens when
the writer merged one paragraph and split another, so the counts agree but the order does not.
A fully rewritten paragraph with no better neighbour stays paired by order.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Set, Tuple

# T2 gate.align move scores.
SKIP = -0.15
NEG = -1e9
BAND_BASE = 8
PARA_FLOOR = 0.3
# Cell budget of one DP block (about 1 s of Python). For 100k chars (3,442 sentences) the
# band 2*|n-m| + 8 fits up to |n-m| = 68; beyond that the band is narrowed to fit, and the
# alignment stays complete but may miss a pairing that lies far off the diagonal.
MAX_CELLS = 1_000_000
# Characters that carry content for the similarity; everything else (spaces, punctuation,
# emoji) is dropped before bigrams are taken.
_CONTENT = re.compile(r"[^가-힣\u3131-\u318eA-Za-z0-9\u4e00-\u9fff]")
_SPACE = re.compile(r"\s+")

# DP moves in T2's order; the order decides ties.
_MOVES = ((1, 1), (1, 2), (2, 1), (1, 0), (0, 1))


@dataclass(frozen=True)
class Pair:
    src: Tuple[int, ...]
    out: Tuple[int, ...]
    score: float

    @property
    def shape(self) -> str:
        """'1:1', '1:2', '2:1', '1:0' or '0:1'."""
        return f"{len(self.src)}:{len(self.out)}"


# --------------------------------------------------------------------------
# similarity
# --------------------------------------------------------------------------
def _text(item: Any) -> str:
    return item if isinstance(item, str) else item.text


def _norm(text: str) -> str:
    """Content characters only; a sentence with none (an emoji-only line, "...") keeps its
    non-space characters, so two such sentences do not score as identical (T2 gives them 1.0)."""
    core = _CONTENT.sub("", text)
    return core if core else _SPACE.sub("", text)


def _grams(core: str) -> Set[str]:
    if len(core) < 2:
        return {core} if core else set()
    return {core[i:i + 2] for i in range(len(core) - 1)}


def _dice(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def similarity(a: str, b: str) -> float:
    """Character-bigram Dice of two sentences, the score every alignment move uses."""
    return _dice(_grams(_norm(a)), _grams(_norm(b)))


class _Side:
    """Normalised text and bigram sets of one side: per sentence, and per adjacent pair joined
    the way T2 joins them (no separator, so the junction bigram counts)."""

    __slots__ = ("texts", "grams", "pair_grams")

    def __init__(self, texts: List[str]):
        cores = [_norm(text) for text in texts]
        self.texts = texts
        self.grams = [_grams(core) for core in cores]
        # pair_grams[k] = bigrams of sentence k joined with sentence k+1.
        self.pair_grams = [_grams(cores[k] + cores[k + 1]) for k in range(len(cores) - 1)]


# --------------------------------------------------------------------------
# banded DP over one block
# --------------------------------------------------------------------------
def band_width(n: int, m: int) -> int:
    """Half-width of the DP band for a block of n source and m candidate sentences:
    2*|n-m| + 8, narrowed so that the block visits at most MAX_CELLS cells."""
    width = 2 * abs(n - m) + BAND_BASE
    return max(BAND_BASE, min(width, (MAX_CELLS // (n + 1) - 1) // 2))


def _dp(src: _Side, out: _Side, s0: int, s1: int, o0: int, o1: int, band: Optional[int]) -> List[Pair]:
    """Monotone DP over src[s0:s1] x out[o0:o1] (indices into the whole side)."""
    n, m = s1 - s0, o1 - o0
    if n == 0 or m == 0:
        return [Pair((s0 + i,), (), 0.0) for i in range(n)] + [Pair((), (o0 + j,), 0.0) for j in range(m)]
    width = max(1, band) if band is not None else band_width(n, m)
    while True:
        pairs = _banded(src, out, s0, o0, n, m, width)
        if pairs is not None:
            return pairs
        # The end cell was unreachable: only possible for a very narrow band on a block whose
        # lengths differ a lot (each row moves the band by about m/n columns).
        width *= 2


def _banded(src: _Side, out: _Side, s0: int, o0: int, n: int, m: int, width: int) -> Optional[List[Pair]]:
    # lo[i]..hi[i] is the column range of row i; cells outside it are never visited.
    lo = [max(0, round(i * m / n) - width) for i in range(n + 1)]
    hi = [min(m, round(i * m / n) + width) for i in range(n + 1)]
    best = [[NEG] * (hi[i] - lo[i] + 1) for i in range(n + 1)]
    back = [[0] * (hi[i] - lo[i] + 1) for i in range(n + 1)]    # index into _MOVES, + 1
    best[0][0] = 0.0
    sg, sp, og, op = src.grams, src.pair_grams, out.grams, out.pair_grams
    # The moves are unrolled for speed. Every source cell is relaxed in row-major order, as in
    # T2, and its five moves reach five different cells, so ties resolve exactly as there.
    for i in range(n + 1):
        row, rb, li = best[i], back[i], lo[i]
        if i < n:
            r1, b1, l1, h1 = best[i + 1], back[i + 1], lo[i + 1], hi[i + 1]
            g1 = sg[s0 + i]
        if i + 1 < n:
            r2, b2, l2, h2 = best[i + 2], back[i + 2], lo[i + 2], hi[i + 2]
            g2 = sp[s0 + i]
        for j in range(li, hi[i] + 1):
            b = row[j - li]
            if b == NEG:
                continue
            oj = o0 + j
            if i < n:
                if j < m and l1 <= j + 1 <= h1:                       # 1:1
                    x = og[oj]
                    v = b + (2 * len(g1 & x) / (len(g1) + len(x)) if g1 and x else 0.0)
                    if v > r1[j + 1 - l1]:
                        r1[j + 1 - l1], b1[j + 1 - l1] = v, 1
                if j + 1 < m and l1 <= j + 2 <= h1:                   # 1:2 split
                    x = op[oj]
                    v = b + (4 * len(g1 & x) / (len(g1) + len(x)) if g1 and x else 0.0) - 1
                    if v > r1[j + 2 - l1]:
                        r1[j + 2 - l1], b1[j + 2 - l1] = v, 2
            if i + 1 < n and j < m and l2 <= j + 1 <= h2:             # 2:1 merge
                x = og[oj]
                v = b + (4 * len(g2 & x) / (len(g2) + len(x)) if g2 and x else 0.0) - 1
                if v > r2[j + 1 - l2]:
                    r2[j + 1 - l2], b2[j + 1 - l2] = v, 3
            if i < n and l1 <= j <= h1:                               # 1:0 deletion
                v = b + SKIP
                if v > r1[j - l1]:
                    r1[j - l1], b1[j - l1] = v, 4
            if j < m and j + 1 <= hi[i]:                              # 0:1 insertion
                v = b + SKIP
                if v > row[j + 1 - li]:
                    row[j + 1 - li], rb[j + 1 - li] = v, 5
    if not lo[n] <= m <= hi[n] or best[n][m - lo[n]] == NEG:
        return None
    pairs: List[Pair] = []
    i, j = n, m
    while i > 0 or j > 0:
        di, dj = _MOVES[back[i][j - lo[i]] - 1]
        si = tuple(range(s0 + i - di, s0 + i))
        oj = tuple(range(o0 + j - dj, o0 + j))
        pairs.append(Pair(si, oj, _pair_score(src, out, si, oj)))
        i, j = i - di, j - dj
    pairs.reverse()
    return pairs


def _pair_score(src: _Side, out: _Side, si: Tuple[int, ...], oj: Tuple[int, ...]) -> float:
    if not si or not oj:
        return 0.0
    a = src.grams[si[0]] if len(si) == 1 else src.pair_grams[si[0]]
    b = out.grams[oj[0]] if len(oj) == 1 else out.pair_grams[oj[0]]
    return _dice(a, b)


def _block(src: _Side, out: _Side, s0: int, s1: int, o0: int, o1: int, band: Optional[int]) -> List[Pair]:
    """Align one block: pair identical leading and trailing sentences, DP the middle."""
    head: List[Pair] = []
    while s0 < s1 and o0 < o1 and src.texts[s0] == out.texts[o0]:
        head.append(Pair((s0,), (o0,), 1.0 if src.grams[s0] else 0.0))
        s0, o0 = s0 + 1, o0 + 1
    tail: List[Pair] = []
    while s1 > s0 and o1 > o0 and src.texts[s1 - 1] == out.texts[o1 - 1]:
        s1, o1 = s1 - 1, o1 - 1
        tail.append(Pair((s1,), (o1,), 1.0 if src.grams[s1] else 0.0))
    tail.reverse()
    return head + _dp(src, out, s0, s1, o0, o1, band) + tail


# --------------------------------------------------------------------------
# paragraph-first driver
# --------------------------------------------------------------------------
def _ranges(paras: List[int]) -> List[Tuple[int, int]]:
    """[start, end) index ranges of consecutive equal paragraph keys."""
    out: List[Tuple[int, int]] = []
    start = 0
    for k in range(1, len(paras) + 1):
        if k == len(paras) or paras[k] != paras[start]:
            out.append((start, k))
            start = k
    return out


def _displaced(src: _Side, out: _Side, sr: List[Tuple[int, int]], orr: List[Tuple[int, int]]) -> bool:
    """True when pairing paragraphs by order puts some paragraph next to the wrong partner."""
    pg_src = [set().union(*src.grams[a:b]) for a, b in sr]
    pg_out = [set().union(*out.grams[a:b]) for a, b in orr]
    count = len(sr)
    for i in range(count):
        own = _dice(pg_src[i], pg_out[i])
        if own >= PARA_FLOOR:
            continue
        for k in (i - 1, i + 1):
            if 0 <= k < count and (_dice(pg_src[i], pg_out[k]) > own or _dice(pg_src[k], pg_out[i]) > own):
                return True
    return False


def _run(src_items: Sequence[Any], out_items: Sequence[Any], src_paras: Optional[List[int]],
         out_paras: Optional[List[int]], band: Optional[int]) -> List[Pair]:
    src = _Side([_text(item) for item in src_items])
    out = _Side([_text(item) for item in out_items])
    n, m = len(src.texts), len(out.texts)
    if src_paras is not None and out_paras is not None:
        sr, orr = _ranges(src_paras), _ranges(out_paras)
        if len(sr) == len(orr) and len(sr) > 1 and not _displaced(src, out, sr, orr):
            pairs: List[Pair] = []
            for (a, b), (c, d) in zip(sr, orr):
                pairs += _block(src, out, a, b, c, d, band)
            return pairs
    return _block(src, out, 0, n, 0, m, band)


def _para_keys(items: Sequence[Any]) -> Optional[List[int]]:
    if items and all(hasattr(item, "para") for item in items):
        return [item.para for item in items]
    return None


def align(src: Sequence[Any], out: Sequence[Any], *, band: Optional[int] = None) -> List[Pair]:
    """Align two sentence lists (str or objects with .text). Paragraph-first when both sides'
    items carry .para (types.Unit); `band` overrides the half-width 2*|n-m| + 8 of every DP."""
    src_paras, out_paras = _para_keys(src), _para_keys(out)
    if src_paras is None or out_paras is None:
        src_paras = out_paras = None
    return _run(src, out, src_paras, out_paras, band)


def _flatten(doc: Any) -> Tuple[List[Any], List[int]]:
    """Sentences and paragraph keys of a Document, a flat unit list or a list of paragraphs."""
    if hasattr(doc, "units"):
        doc = doc.units
    items = list(doc)
    if items and all(isinstance(item, (list, tuple)) for item in items):
        flat, keys = [], []
        for index, paragraph in enumerate(items):
            flat += list(paragraph)
            keys += [index] * len(paragraph)
        return flat, keys
    keys = _para_keys(items)
    return items, keys if keys is not None else [0] * len(items)


def align_documents(src: Any, out: Any, *, band: Optional[int] = None) -> List[Pair]:
    """Align two documents paragraph-first (see the module docstring for accepted shapes)."""
    src_items, src_paras = _flatten(src)
    out_items, out_paras = _flatten(out)
    return _run(src_items, out_items, src_paras, out_paras, band)
