"""Comma rule of Super Sejong Engine v2 (DESIGN.md 3.7 step 5, 4.1; T1 report 1.7 and 6 Improve 4).

A rewrite must not add connective-ending commas ("먹고, 자서,") that the writer model injects from
habit, and must never delete the commas the author wrote. The vendored stripper took any sentence that
differs from the source in any way as new and removed all of its connective-ending commas, so a one-word
edit also deleted the author's: 124 commas in 122 sentences on the blog posts, 100% of the author's
commas in every touched sentence (T1 1.7).

    strip_injected(src_text, out_text, *, restore_dropped=False)        -> (text, removed)
    strip_injected_report(src_text, out_text, *, restore_dropped=False) -> (text, report)
    count_connective_commas(sentence)                                   -> int

The rule, per aligned (source, candidate) sentence pair (1:1, and the joined sentences of a 1:2 split or
2:1 merge):

  k          the connective-ending commas of the source sentence (outside quotations; a noun-list comma
             counts, because whether a comma sits in a list depends on its neighbours)
  c          the same count for the candidate
  matched    a candidate comma that a character alignment (difflib) pairs with a source comma, or whose
             word and comma the source sentence also has (the writer moved the word)
  removal    only unmatched candidate commas outside noun lists, and only while c exceeds k
  initial    the comma after a sentence-initial 그리고/하지만/그러나/그런데 is outside the count; it is
             removed only if it is newly inserted, that is, not matched in the alignment
  new        a candidate sentence with no source sentence (0:1) or one that shares nothing with its
             partner (align score below MIN_SCORE) has no author commas: all of them are removed

Quotations and noun lists ("재고, 창고, 광고비") are never touched, as in the vendored module, whose
regexes and exceptions are copied below.

restore_dropped=True also reinserts a writer comma that the rewrite deleted between two words the source
sentence had around it ("A, B" -> "A B" with the same A and B). It is opt-in because a requested fix may
delete a comma on purpose.

Sentences are paired with align.align (banded, linear in the document); the character alignment runs on
one sentence pair, only when a removal is possible, and is capped by size and by a document-wide budget so
that adversarial input stays linear.
"""
from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .align import Pair, align

# Copied from vendor/humanize-engine/scripts/strip_injected_commas.py (MIT, (c) 2026 epoko77-ai):
# the connective-ending comma, the noun-list exception and its '고' noun list.
# '자,' is an interjection ("자, 이제") and the bare '서' of "~에서," is a josa, so neither is listed.
_CONN_COMMA = re.compile(r"(고|며|지만|면서|는데|아서|어서|여서|해서|져서),(\s)")
_NEXT_ITEM = re.compile(r"([^\s,.!?…]+),")
_PREV_ITEM = re.compile(r"([^\s,.!?…]+),\s*$")
_GO_NOUNS = ("재고", "창고", "광고", "최고", "경고", "원고", "잔고", "공고", "출고", "금고")

# Sentence-initial connectives whose comma is the writer's choice (T1 1.7). Optional bullet and opening
# quote or bracket in front; the comma must be followed by white space.
_INITIAL = re.compile(r"(?:[-*•·>]\s+)?[“‘\"'「『(\[]*(?:그리고|하지만|그러나|그런데),(?=\s)")
# A word that ends in a connective ending, for counting a restored comma as connective-ending.
_CONN_END = re.compile(r"(?:고|며|지만|면서|는데|아서|어서|여서|해서|져서)\Z")

_SPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"\S+")
_WORD_COMMA = re.compile(r"[^\s,]+,")
_TERMINATORS = ".!?…"
_CLOSERS = "\"'”’」』)]"
# Opening quotation mark -> closing mark (the ASCII quote closes itself).
_QUOTES = {"“": "”", "‘": "’", '"': '"', "「": "」", "『": "』"}
_OPENER = re.compile("[“‘\"「『]")

# A rewritten sentence whose align score (character-bigram Dice, align.similarity) is below this shares
# nothing with the source sentence it was paired with: it is new. Chosen on the T2 pair sets and the seed
# benchmark (tests/skills/test_sejong_commas.py, ScoreFloor): every rewrite scores far above it.
MIN_SCORE = 0.25
# difflib runs on one sentence pair only, each side at most this long (DESIGN.md 6); longer pairs are
# treated as changed (no character alignment: only the word rule and the count rule decide).
MAX_PIECE = 2000
# difflib's cost is the number of equal-character pairs (a, b) share, times the recursion depth: natural
# 60-character sentences have about 300 such pairs and cost 0.03 ms, a 1,300-character pair of repeating
# words has 390,000 and cost 1.2 s (measured). A pair above MAX_PAIR_WORK, and every pair once a document
# has used MAX_WORK, is treated as changed, which bounds the adversarial case at about a second.
MAX_PAIR_WORK = 100_000
MAX_WORK = 400_000
# Context (characters) looked at before a word for the noun-list test; a longer word cannot be an item.
_ITEM_WINDOW = 80


# --------------------------------------------------------------------------
# segmentation
# --------------------------------------------------------------------------
class _Sent:
    """One sentence: its text, its [start, end) in the document and its paragraph number
    (a blank line starts a paragraph). `text` and `para` are what align.align reads."""

    __slots__ = ("text", "para", "start", "end")

    def __init__(self, text: str, para: int, start: int, end: int):
        self.text, self.para, self.start, self.end = text, para, start, end


def _norm(sentence: str) -> str:
    return _SPACE.sub(" ", sentence.strip())


def _split(text: str) -> List[_Sent]:
    """Sentences of `text`, split where white space follows . ! ? … (a closing quote or bracket may sit
    between) and at every line break. One pass over the white-space runs, so it is linear."""
    sents: List[_Sent] = []
    n = len(text)
    lead = _SPACE.match(text)
    start = lead.end() if lead else 0
    para = 0
    for m in _SPACE.finditer(text, start):
        a, b = m.span()
        if b >= n:
            break
        run = m.group()
        prev = text[a - 1]
        if ("\n" in run or prev in _TERMINATORS
                or (prev in _CLOSERS and a >= 2 and text[a - 2] in _TERMINATORS)):
            sents.append(_Sent(text[start:a], para, start, a))
            if run.count("\n") >= 2:
                para += 1
            start = b
    if start < n:
        end = len(text.rstrip())
        if end > start:
            sents.append(_Sent(text[start:end], para, start, end))
    return sents


def _quote_spans(text: str) -> List[Tuple[int, int]]:
    """[start, end) of every quotation: “…” ‘…’ "…" 「…」 『…』, never across a line break; an ASCII quote
    after a digit (5" pipe) does not open one. The same spans as the vendored regex, found in linear time:
    one failed search per mark type and line, because a later opener of that type would fail too."""
    spans: List[Tuple[int, int]] = []
    offset = 0
    for line in text.split("\n"):
        if _OPENER.search(line):
            dead: Set[str] = set()
            i = 0
            while True:
                m = _OPENER.search(line, i)
                if not m:
                    break
                i = m.start()
                opener = line[i]
                closer = _QUOTES[opener]
                if closer in dead or (opener == '"' and i > 0 and line[i - 1].isdecimal()):
                    i += 1
                    continue
                j = line.find(closer, i + 1)
                if j < 0:
                    dead.add(closer)
                    i += 1
                    continue
                spans.append((offset + i, offset + j + 1))
                i = j + 1
        offset += len(line) + 1
    return spans


class _Spans:
    """Membership of a position in sorted, disjoint spans, O(log n)."""

    def __init__(self, spans: Sequence[Tuple[int, int]]):
        self.starts = [a for a, _ in spans]
        self.ends = [b for _, b in spans]

    def __contains__(self, pos: int) -> bool:
        i = bisect_right(self.starts, pos) - 1
        return i >= 0 and pos < self.ends[i]


def _in_noun_list(sent: str, m: "re.Match[str]") -> bool:
    """Vendored exception: the '고,' of a noun list ("재고, 창고, 광고비") is not a connective. A neighbouring
    item that ends with a comma and is a single word not ending in '고' makes it a list; "먹고, 자고,"
    stays a connective list. Looks at a bounded window, so a long run without spaces stays cheap."""
    if m.group(1) != "고":
        return False
    word_start = max(sent.rfind(" ", 0, m.start()), sent.rfind(",", 0, m.start())) + 1
    if sent[word_start:m.start() + 1].endswith(_GO_NOUNS):
        return True
    following = _NEXT_ITEM.match(sent, m.end())
    if following and not following.group(1).endswith("고"):
        return True
    preceding = _PREV_ITEM.search(sent, max(0, word_start - _ITEM_WINDOW), word_start)
    return bool(preceding and not preceding.group(1).endswith("고"))


class _Side:
    """A document (source or candidate): its sentences, quotation spans and, per sentence, the connective
    commas the rule looks at."""

    def __init__(self, text: str):
        self.text = text
        self.sents = _split(text)
        self.quotes = _Spans(_quote_spans(text))
        self._info: Dict[int, Tuple[List[int], List[int], int]] = {}

    def info(self, index: int) -> Tuple[List[int], List[int], int]:
        """(eligible, counted, initial) of one sentence, as absolute indices of the comma characters.
        counted = every connective-ending comma outside quotations except the initial one; this is what k
        and the candidate's count are made of. eligible = the counted commas outside noun lists, the only
        ones that may be removed. initial = the comma after a sentence-initial connective, or -1."""
        cached = self._info.get(index)
        if cached is not None:
            return cached
        s = self.sents[index]
        initial_at = -1
        lead = _INITIAL.match(s.text)
        if lead:
            initial_at = s.start + lead.end() - 1
        # The separator that follows the sentence is part of the scan: a comma that ends a line
        # ("…하고,\n") is followed by white space like any other.
        scan = s.text + self.text[s.end:s.end + 1]
        eligible, counted = [], []
        for m in _CONN_COMMA.finditer(scan):
            comma = s.start + m.start() + len(m.group(1))
            if comma == initial_at or (s.start + m.start()) in self.quotes:
                continue
            counted.append(comma)
            if not _in_noun_list(scan, m):
                eligible.append(comma)
        initial = initial_at if initial_at >= 0 and initial_at not in self.quotes else -1
        self._info[index] = result = (eligible, counted, initial)
        return result


# --------------------------------------------------------------------------
# character alignment
# --------------------------------------------------------------------------
@dataclass
class _Budget:
    work: int = MAX_WORK
    skipped: int = 0                       # pairs treated as changed because of size or budget


def _char_match(a: str, b: str, budget: _Budget) -> Optional[Tuple[Set[int], Set[int]]]:
    """Comma positions of b (and of a) that fall inside a matching block of the difflib alignment of a
    to b, relative to the strings; None when the pair is too big to align (see MAX_PAIR_WORK)."""
    if len(a) <= MAX_PIECE and len(b) <= MAX_PIECE:
        count_b = Counter(b)
        work = sum(n * count_b.get(ch, 0) for ch, n in Counter(a).items())
        if work <= MAX_PAIR_WORK and work <= budget.work:
            budget.work -= work
            return _blocks(a, b)
    budget.skipped += 1
    return None


def _blocks(a: str, b: str) -> Tuple[Set[int], Set[int]]:
    in_b: Set[int] = set()
    in_a: Set[int] = set()
    for i, j, size in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for text, start, found in ((b, j, in_b), (a, i, in_a)):
            at = text.find(",", start, start + size)
            while at >= 0:
                found.add(at)
                at = text.find(",", at + 1, start + size)
    return in_b, in_a


def _word_commas(piece: str) -> Dict[int, str]:
    """{index of the comma: the word with its comma} for every "word," of the piece."""
    return {m.end() - 1: m.group() for m in _WORD_COMMA.finditer(piece)}


# --------------------------------------------------------------------------
# restoring a dropped comma
# --------------------------------------------------------------------------
def _anchor(word: str) -> str:
    """The left word of a comma slot. A connective ending stands for the whole word, so a comma after a
    rewritten clause is still found: "가능하며, 서류가" → "진행할 수 있으며 서류가" (live check, 2026-10-04)."""
    ending = _CONN_END.search(word)
    return "~" + ending.group() if ending else word


def _dropped(a: str, b: str, offset: int) -> Tuple[List[int], int]:
    """Insertion points (absolute, after offset) for the commas the source piece `a` has between two words
    and the candidate piece `b` lacks between the same two words (a connective-ending left word matches by
    its ending), and how many of them end a connective."""
    wanted: Counter = Counter()
    tokens = [m.group() for m in _TOKEN.finditer(a)]
    for word, following in zip(tokens, tokens[1:]):
        core, nxt = word[:-1], following.rstrip(",")
        if word.endswith(",") and core and not core.endswith(",") and nxt:
            wanted[(_anchor(core), nxt)] += 1
    if not wanted:
        return [], 0
    spots = [(m.end(), m.group()) for m in _TOKEN.finditer(b)]
    have: Counter = Counter()
    for (_, word), (_, following) in zip(spots, spots[1:]):
        if word.endswith(",") and len(word) > 1:
            have[(_anchor(word[:-1]), following.rstrip(","))] += 1
    missing = wanted - have
    points, connective = [], 0
    for (end, word), (_, following) in zip(spots, spots[1:]):
        key = (_anchor(word), following.rstrip(","))
        if not word.endswith(",") and missing[key] > 0:
            missing[key] -= 1
            points.append(offset + end)
            connective += bool(_CONN_END.search(word))
    return points, connective


# --------------------------------------------------------------------------
# one aligned pair
# --------------------------------------------------------------------------
def _closest(candidates: List[int], anchors: List[float], where, keep: int) -> List[int]:
    """The `keep` candidates whose relative position is nearest to an anchor (ties: leftmost)."""
    def gap(position: int) -> float:
        x = where(position)
        i = bisect_left(anchors, x)
        near = [anchors[k] for k in (i - 1, i) if 0 <= k < len(anchors)]
        return min(abs(x - y) for y in near)
    return sorted(sorted(candidates), key=gap)[:keep]


def _freed(out: _Side, pair: Pair, exempt: Set[int], gone: Set[int]) -> Set[int]:
    """Exempt commas of the candidate that no longer sit in a noun list once the commas in `gone` are
    deleted: "A고, B며," read as a list only because of the comma after B며. Without this a second pass
    would remove more than the first, and the rule would not be idempotent."""
    freed: Set[int] = set()
    for i in pair.out:
        s = out.sents[i]
        chars = list(s.text + out.text[s.end:s.end + 1])
        for position in gone:
            if s.start <= position < s.start + len(chars):
                chars[position - s.start] = "\0"        # deleted: neither a comma nor a word character
        virtual = "".join(chars)
        for m in _CONN_COMMA.finditer(virtual):
            comma = s.start + m.start() + len(m.group(1))
            if comma in exempt and not _in_noun_list(virtual, m):
                freed.add(comma)
    return freed


def _group(src: _Side, out: _Side, pair: Pair, restore: bool, budget: _Budget,
           originals: Set[str]) -> Tuple[List[int], List[int]]:
    """(candidate comma indices to delete, indices where a comma is to be inserted) for one aligned pair."""
    sents = [out.sents[i] for i in pair.out]
    o0, o1 = sents[0].start, sents[-1].end
    cand: List[int] = []                   # eligible: the commas that may be removed
    counted: List[int] = []                # c: every connective-ending comma of the candidate
    initials: List[int] = []
    for i in pair.out:
        if _norm(out.sents[i].text) in originals:
            continue                       # a sentence the source has verbatim is the writer's, wherever it is
        eligible, every, initial = out.info(i)
        cand += eligible
        counted += every
        if initial >= 0:
            initials.append(initial)
    b = out.text[o0:o1]
    if not pair.src:                       # a new sentence has none of the author's commas
        return sorted(cand + initials), []
    s0, s1 = src.sents[pair.src[0]].start, src.sents[pair.src[-1]].end
    a = src.text[s0:s1]
    if a == b:
        return [], []
    inserts: List[int] = []
    restored_connective = 0
    if restore:
        inserts, restored_connective = _dropped(a, b, o0)
    if not cand and not initials:
        return [], inserts
    if pair.score < MIN_SCORE:             # paired by position only: nothing in common with the source
        return sorted(cand + initials), inserts
    source = [p for i in pair.src for p in src.info(i)[1]]
    k = len(source)
    source_initial = any(src.info(i)[2] >= 0 for i in pair.src)
    excess = len(counted) + restored_connective - k
    if excess <= 0 and not initials:
        return [], inserts                 # the count never exceeds the author's: nothing to remove
    match = _char_match(a, b, budget)
    in_b, in_a = match if match is not None else (set(), set())
    removed: List[int] = []
    for position in initials:
        # Newly inserted = not matched in the alignment. Without an alignment the only evidence is
        # whether the source sentence had an initial comma of its own.
        if (position - o0 not in in_b) if match is not None else not source_initial:
            removed.append(position)
    if excess > 0:
        words = _word_commas(b)
        known = Counter(m.group() for m in _WORD_COMMA.finditer(a))
        for position in counted:           # alignment-matched commas use up the source's word commas first
            if position - o0 in in_b:
                known[words.get(position - o0, "")] -= 1
        unmatched = []
        for position in counted:
            if position - o0 in in_b:
                continue
            word = words.get(position - o0, "")
            if known[word] > 0:            # the writer's word and comma, moved within the sentence
                known[word] -= 1
            else:
                unmatched.append(position)
        lost = [(p - s0) / len(a) for p in source if p - s0 not in in_a] or [(p - s0) / len(a) for p in source]
        eligible = set(cand)
        exempt = set(unmatched) - eligible
        gone: Set[int] = set()
        while excess > 0:
            removable = [p for p in unmatched if p in eligible and p not in gone]
            if not removable:
                break
            drop = min(len(removable), excess)
            if drop < len(removable):      # k > 0 here: keep the commas nearest to one the rewrite lost
                kept = set(_closest(removable, sorted(lost), lambda p: (p - o0) / len(b), len(removable) - drop))
                removable = [p for p in removable if p not in kept]
            gone.update(removable)
            excess -= len(removable)
            if excess > 0 and exempt:      # deleting commas can end a noun list: look again
                eligible = _freed(out, pair, exempt, gone)
                exempt -= eligible
            else:
                eligible = set()
        removed += sorted(gone)
    return sorted(removed), inserts


# --------------------------------------------------------------------------
# document level
# --------------------------------------------------------------------------
def _apply(text: str, deletions: Sequence[int], insertions: Sequence[int]) -> str:
    edits = sorted([(i, False) for i in deletions] + [(i, True) for i in insertions])
    parts, last = [], 0
    for index, insert in edits:
        parts.append(text[last:index])
        if insert:
            parts.append(",")
            last = index
        else:
            last = index + 1
    parts.append(text[last:])
    return "".join(parts)


def strip_injected_report(src_text: str, out_text: str, *, restore_dropped: bool = False) -> Tuple[str, Dict[str, int]]:
    """Fix the commas of `out_text` against `src_text`; returns (text, {"commas_removed", "commas_restored",
    "sentences_touched", "pairs_unaligned"}); the last counts the pairs that were too big for a character
    alignment. Only comma characters are deleted or inserted; everything else is untouched."""
    src, out = _Side(src_text), _Side(out_text)
    originals = {_norm(sent.text) for sent in src.sents}
    budget = _Budget()
    deletions: List[int] = []
    insertions: List[int] = []
    touched = 0
    for pair in align(src.sents, out.sents):
        if not pair.out:
            continue
        gone, added = _group(src, out, pair, restore_dropped, budget, originals)
        deletions += gone
        insertions += added
        touched += bool(gone or added)
    if not deletions and not insertions:
        return out_text, {"commas_removed": 0, "commas_restored": 0, "sentences_touched": 0,
                          "pairs_unaligned": budget.skipped}
    return _apply(out_text, deletions, insertions), {
        "commas_removed": len(deletions), "commas_restored": len(insertions), "sentences_touched": touched,
        "pairs_unaligned": budget.skipped}


def strip_injected(src_text: str, out_text: str, *, restore_dropped: bool = False) -> Tuple[str, int]:
    """(text, number of commas removed): `out_text` without the connective-ending commas the rewrite added
    to `src_text`. The author's commas stay; see the module docstring for the rule."""
    text, report = strip_injected_report(src_text, out_text, restore_dropped=restore_dropped)
    return text, report["commas_removed"]


def count_connective_commas(sentence: str) -> int:
    """k of a sentence: its connective-ending commas outside quotations, except the initial comma. A comma in
    a noun list counts too, although it is never removed."""
    side = _Side(sentence)
    return sum(len(side.info(i)[1]) for i in range(len(side.sents)))
