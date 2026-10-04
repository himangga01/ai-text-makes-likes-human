"""Sentence segmentation and alignment for the independent scorer (WP-15a).

This module is a port of the helpers the T7 prototype took from its seed builder (`segment`,
`voice_profile` lives in voicefeat.py) and from `T7_score.py` (`bigrams`, `dice`, `align`). It
deliberately does NOT use the engine's splitter or aligner (engine_runtime/sejong/text.py,
align.py): an evaluation judge that shared code with the thing it judges would stop being
independent (T7 section 3.1, DESIGN.md 7.1). Behaviour is frozen to T7's so the self-test
numbers stay comparable; changes here need a new self-test baseline.

Standard library only.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

QUOTE = re.compile(r'“[^”]*”|‘[^’]*’|「[^」]*」|"[^"\n]*"')
EMO = re.compile(r'[ㅎㅋㅠㅜ]{2,}(?=\s)')
_LIST_LINE = re.compile(r"\s*([-*]|\d+\.)\s")

Segment = Tuple[int, int, str]  # (start, end, kind) with kind in prose | heading | list


def segment(text: str) -> List[Segment]:
    """Sentence spans of `text` as code-point offsets. Boundaries only fall outside quotations.

    Heading ("#") and list ("- ", "* ", "1. ") lines are one segment each; every other line is cut
    after . ? ! followed by whitespace or end of line, and after a run of ㅋㅎㅠㅜ before whitespace.
    """
    out: List[Segment] = []
    pos = 0
    for line in text.split("\n"):
        start = pos
        pos += len(line) + 1
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            out.append((start, start + len(line), "heading"))
            continue
        if _LIST_LINE.match(line):
            out.append((start, start + len(line), "list"))
            continue
        n = len(line)
        in_quote = [False] * n
        for m in QUOTE.finditer(line):
            for i in range(m.start(), m.end()):
                in_quote[i] = True
        cuts = []
        for i, ch in enumerate(line):
            if ch in ".?!" and not in_quote[i] and (i + 1 >= n or line[i + 1].isspace()):
                cuts.append(i + 1)
        for m in EMO.finditer(line):
            if not in_quote[m.start()]:
                cuts.append(m.end())
        prev = 0
        for cut in sorted(set(cuts)) + [n]:
            seg = line[prev:cut]
            if seg.strip():
                a = prev + (len(seg) - len(seg.lstrip()))
                b = prev + len(seg.rstrip())
                out.append((start + a, start + b, "prose"))
            prev = cut
    return out


def sentences(text: str) -> Tuple[List[Tuple[int, int, str]], List[str]]:
    """([(start, end, sentence_text)], [kind]) for `text`."""
    segs = segment(text)
    return [(a, b, text[a:b]) for a, b, _ in segs], [kind for _, _, kind in segs]


# ---- alignment --------------------------------------------------------------------------------
_WS = re.compile(r"\s+")


def bigrams(s: str) -> Set[str]:
    s = _WS.sub("", s)
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def dice_sets(x: Set[str], y: Set[str]) -> float:
    if not x or not y:
        return 0.0
    return 2 * len(x & y) / (len(x) + len(y))


def dice(a: str, b: str) -> float:
    return dice_sets(bigrams(a), bigrams(b))


# Full DP up to this many cells (every seed item and every owner draft); banded beyond it.
FULL_DP_CELLS = 250_000
BAND_SLACK = 24
_NEG = -1e18


def align(src: Sequence[str], out: Sequence[str], floor: float = 0.3) -> List[Optional[int]]:
    """Monotone alignment of two sentence lists on character-bigram Dice.

    Returns m with m[i] = index into `out` of the sentence matched to src[i], or None. A pair needs
    Dice >= floor; the DP maximises the summed Dice. Up to FULL_DP_CELLS cells the DP is exact
    (identical to T7's). Larger inputs fill only a diagonal band of half-width |n - m| + BAND_SLACK
    around the line from (0, 0) to (n, m), so a long document costs O((n + m) * band) similarity
    evaluations instead of O(n * m); a pair outside the band stays unmatched.
    """
    n, m = len(src), len(out)
    xs = [bigrams(s) for s in src]
    ys = [bigrams(s) for s in out]
    banded = n * m > FULL_DP_CELLS
    band = abs(n - m) + BAND_SLACK

    def window(i: int) -> Tuple[int, int]:
        if not banded:
            return 1, m
        centre = i + ((m - n) * i) // max(n, 1)
        return max(1, centre - band), min(m, centre + band)

    sim_cache: Dict[Tuple[int, int], float] = {}

    def sim(i: int, j: int) -> float:
        v = sim_cache.get((i, j))
        if v is None:
            v = sim_cache[(i, j)] = dice_sets(xs[i], ys[j])
        return v

    best = [[0.0] * (m + 1)] + [([_NEG] * (m + 1) if banded else [0.0] * (m + 1)) for _ in range(n)]
    for i in range(1, n + 1):
        row, prev_row = best[i], best[i - 1]
        row[0] = 0.0
        lo, hi = window(i)
        for j in range(lo, hi + 1):
            s = sim(i - 1, j - 1)
            take = prev_row[j - 1] + s if s >= floor else -1.0
            row[j] = max(prev_row[j], row[j - 1], take)
    res: List[Optional[int]] = [None] * n
    i, j = n, m
    while i > 0 and j > 0:
        lo, hi = window(i)
        s = sim(i - 1, j - 1) if lo <= j <= hi else -1.0
        if s >= floor and abs(best[i][j] - (best[i - 1][j - 1] + s)) < 1e-9:
            res[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif best[i][j] == best[i - 1][j]:
            i -= 1
        else:
            j -= 1
    return res
