"""Apply a writer reply to a chunk (DESIGN.md 3.6) and build candidate documents for verification.

    apply_response(plan, doc, response, start) -> ApplyResult    replacements by request or sentence id
    apply_full_text(plan, doc, text, start)    -> ApplyResult    full-text fallback and --candidate
    recover_texts(doc, text, fallback)         -> list[str]      per-sentence texts of a decided chunk
    assemble(doc, texts)                       -> (text, spans)  the candidate chunk
    candidate_document(doc, texts)             -> Candidate      segmented candidate + pairs by construction

A candidate is kept as one text per source sentence (`texts[i]` replaces plan sentence i); the text
between sentences (spaces, newlines, list markers outside units) is always the source's. Every decision
of the check step is per source sentence, so a revert is just `texts[i] = base[i]`.

Whole-reply rejection (MODEL_OUTPUT_UNUSABLE, ApplyResult.unusable): the reply fails the response schema,
an id is neither a request id nor (open review on) a sentence id of the plan, an id or a sentence is
named twice, or rewrittenText is used when the plan does not allow it or together with replacements.

Per-replacement rejection (ApplyResult.rejected[i] = (code, detail, retryable)):
  replacement_newline        the text holds a line break                              retry
  replacement_length_ratio   stripped length outside [0.5, 2.0] of the source sentence ([0.25, 4.0] for an
                             allowSplit request), or the text is blank                retry
  protected_span_changed     a freeze span of the sentence is not verbatim in it      retry
  replacement_split          more sentences than the source sentence without allowSplit  retry
  replacement_merge          full text only: the sentence was merged with another     retry
  sentence_dropped           full text only: a requested sentence vanished            retry
  replacement_frozen_unit    a nomination of a heading or a sentence with nothing editable  no retry
  open_review_limit          more nominations than openReview.maxSentences (the excess, in reply order)  no retry
A text equal to the source sentence is not a change (the request counts as untouched).

Full-text fallback (rewrittenText when plan.allowFullText, and the CLI's --candidate): the text is
sanitized like the source, segmented, and aligned with align.align_documents. An inserted sentence (0:1)
joins the source sentence before it in the same paragraph (the one after it at a paragraph start), as
meaning.groups does, so a split the aligner saw as 1:1 + 0:1 stays one replacement. A changed sentence
with a request becomes that request's replacement; a changed sentence without one is a collateral edit
(ApplyResult.collateral) and stays as it was.

Boundary stability. A replacement must not move the sentence boundaries of the chunk: when the assembled
candidate is segmented, every source sentence must still start and end on a unit boundary (a replacement
that drops its final period and glues itself to the next sentence, or opens a quotation that swallows the
rest of the paragraph, fails). candidate_document() reports the offending sentences and the check step
reverts them, so per-sentence verification, the decided text and a later re-segmentation always agree.
"""
from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from . import align as A
from . import io as IO
from . import protect as P
from . import text as T
from .types import Document, Plan, Unit

RATIO_MIN, RATIO_MAX = 0.5, 2.0
SPLIT_FACTOR = 2.0            # allowSplit requests get [RATIO_MIN / 2, RATIO_MAX * 2]
NO_RETRY = ("replacement_frozen_unit", "open_review_limit")
# Open-review reasons that license a connective change (prompt.ts NIKL_REVIEW_TYPES 11-13:
# 부적절한 연결(대등/종속 접속), 부적절한 접속어 사용, 부적절한 연결어미 사용).
CONNECTIVE_TYPES = (11, 12, 13)
REVIEW_TYPES = (
    "부적절한 높임법 사용", "어순의 부자연스러움", "부적절한 조사 사용", "부적절한 피동 표현 사용",
    "부적절한 사동 표현 사용", "주어와 서술어의 부적절한 호응", "목적어와 서술어의 부적절한 호응",
    "부사어와 서술어의 부적절한 호응", "수식어와 피수식어의 부적절한 호응", "지나치게 긴 수식어 사용",
    "부적절한 연결(대등/종속 접속)", "부적절한 접속어 사용", "부적절한 연결어미 사용", "부적절한 종결어미 사용",
    "부적절한 대용 표현 사용", "한글 맞춤법·표준어 규정 위반", "띄어쓰기 규정 위반", "문장 부호 생략·부적절 사용",
    "외래어 표기법 위반", "외국어·외래어 오남용", "문법상 잘못된 표현", "어휘상 잘못된 표현",
    "필요한 문장 성분 생략", "부적절한 시제 사용", "로마자 표기법 위반",
    "불필요한 명사화·번역 투(…이 가능하다, …이 이루어지다, …을 진행하다)", "군더더기·중복 표현")
_REVIEW_NUMBER = re.compile(r"\s*(?:NIKL[-\s]?)?0?([1-9]|1[0-9]|2[0-7])(?![0-9])")


def review_type(reason: str) -> Optional[int]:
    """Open-review reason -> type number 1..27 (port of prompt.ts reviewTypeOf), None when it names none."""
    numbered = _REVIEW_NUMBER.match(reason)
    if numbered:
        return int(numbered.group(1))
    for index, name in enumerate(REVIEW_TYPES):
        if name in reason:
            return index + 1
    return None


@dataclass
class ApplyResult:
    texts: List[str]                                            # per source sentence, before repair
    supplied: Dict[int, str] = field(default_factory=dict)      # sentence index -> id (R…/S…) of an applied text
    reasons: Dict[int, str] = field(default_factory=dict)       # sentence index -> the writer's reason
    rejected: Dict[int, Tuple[str, str, bool]] = field(default_factory=dict)
    collateral: Set[int] = field(default_factory=set)
    nominated: Set[int] = field(default_factory=set)            # open-review sentences (S ids) of this reply
    unusable: Optional[str] = None
    full_text: bool = False


# --------------------------------------------------------------------------
# candidate text and document
# --------------------------------------------------------------------------
def gaps(doc: Document) -> List[str]:
    """Source text before, between and after the units (len(units) + 1 pieces)."""
    out, last = [], 0
    for unit in doc.units:
        out.append(doc.text[last:unit.start])
        last = unit.end
    out.append(doc.text[last:])
    return out


def assemble(doc: Document, texts: Sequence[str]) -> Tuple[str, List[Tuple[int, int]]]:
    """The candidate chunk and the code-point span of every sentence in it."""
    pieces, spans, pos = [], [], 0
    between = gaps(doc)
    for gap, piece in zip(between, texts):
        pieces.append(gap)
        pos += len(gap)
        pieces.append(piece)
        spans.append((pos, pos + len(piece)))
        pos += len(piece)
    pieces.append(between[-1])
    return "".join(pieces), spans


@dataclass
class Candidate:
    text: str
    doc: Document
    pairs: List[A.Pair]
    spans: List[Tuple[int, int]]
    unstable: List[int]                     # sentences whose boundaries moved (see module docstring)


def candidate_document(doc: Document, texts: Sequence[str]) -> Candidate:
    """Segment the assembled candidate and pair every source sentence with the units inside its span."""
    text, spans = assemble(doc, texts)
    out = doc if text == doc.text else T.segment(text)
    starts = [u.start for u in out.units]
    ends = [u.end for u in out.units]
    pairs: List[A.Pair] = []
    unstable: List[int] = []
    for i, (a, b) in enumerate(spans):
        piece = text[a:b]
        a += len(piece) - len(piece.lstrip())
        b -= len(piece) - len(piece.rstrip())
        lo, hi = bisect_left(starts, a), bisect_right(ends, b)
        ok = lo < len(starts) and starts[lo] == a and hi > 0 and ends[hi - 1] == b and lo < hi
        if not ok:
            unstable.append(i)
            k = bisect_right(starts, a) - 1
            members = (max(k, 0),) if out.units else ()
        else:
            members = tuple(range(lo, hi))
        if members and len(members) == 1 and doc.units[i].text == out.units[members[0]].text:
            score = 1.0
        else:
            score = A.similarity(doc.units[i].text, " ".join(out.units[j].text for j in members)) if members else 0.0
        pairs.append(A.Pair(src=(i,), out=members, score=score))
    if len(out.paragraphs) != len(doc.paragraphs) and not unstable:
        unstable = [i for i, (t, u) in enumerate(zip(texts, doc.units)) if t != u.text]
    if unstable:
        # Pairs must cover every output unit exactly once for the family checks; an unstable candidate
        # is never verified (the check step reverts the offenders first), so a coarse cover is enough.
        pairs = _cover(pairs, len(out.units))
    return Candidate(text=text, doc=out, pairs=pairs, spans=spans, unstable=unstable)


def _cover(pairs: List[A.Pair], n_out: int) -> List[A.Pair]:
    seen: Set[int] = set()
    out: List[A.Pair] = []
    for pair in pairs:
        members = tuple(j for j in pair.out if j not in seen)
        seen.update(members)
        out.append(A.Pair(src=pair.src, out=members, score=pair.score))
    missing = [j for j in range(n_out) if j not in seen]
    for j in missing:
        out.append(A.Pair(src=(), out=(j,), score=0.0))
    return out


# --------------------------------------------------------------------------
# one replacement
# --------------------------------------------------------------------------
def _validate(unit: Unit, text: str, spans, allow_split: bool) -> Optional[Tuple[str, str]]:
    if "\n" in text or "\r" in text:
        return "replacement_newline", "newline"
    core, src = text.strip(), unit.text.strip()
    if not core:
        return "replacement_length_ratio", "blank"
    low, high = (RATIO_MIN / SPLIT_FACTOR, RATIO_MAX * SPLIT_FACTOR) if allow_split else (RATIO_MIN, RATIO_MAX)
    ratio = len(core) / max(1, len(src))
    if not low <= ratio <= high:
        return "replacement_length_ratio", f"ratio:{ratio:.2f}"
    if not P.freeze_intact(unit, core, spans):
        return "protected_span_changed", "freeze"
    if not allow_split and len(T.split_sentences(core)) > max(1, len(T.split_sentences(src))):
        return "replacement_split", "split"
    return None


def _frozen_unit(unit: Unit, spans) -> bool:
    # local import keeps apply importable without the plan module's heavier dependencies at load time
    from .plan import nominable
    return not nominable(unit, spans)


def apply_response(plan: Plan, doc: Document, response: object, start: Sequence[str], *,
                   nominated_before: int = 0) -> ApplyResult:
    """Apply a writer reply (3.6). `start` is the per-sentence text the replacements land on (the source
    at attempt 1, the recovered attempt-1 decision at attempt 2); `nominated_before` counts open-review
    sentences already accepted, which use up openReview.maxSentences."""
    result = ApplyResult(texts=list(start))
    problems = IO.response_problems(response) if isinstance(response, dict) else ["$: not an object"]
    if problems:
        result.unusable = "schema"
        return result
    replacements = response["replacements"]
    rewritten = response["rewrittenText"]
    if rewritten.strip():
        if replacements or not plan.options.allow_full_text:
            result.unusable = "rewritten_text_not_allowed"
            return result
        return apply_full_text(plan, doc, rewritten, start)
    index_of = {unit.id: k for k, unit in enumerate(doc.units)}
    request_of = {r.id: r for r in plan.requests}
    request_at = {r.sentence: r for r in plan.requests}
    targets: List[Tuple[int, str, str, str, bool]] = []      # (index, id, text, reason, nominated)
    seen_ids: Set[str] = set()
    seen_sentences: Set[int] = set()
    for item in replacements:
        rid = item["id"]
        if rid in seen_ids:
            result.unusable = "duplicate_id"
            return result
        seen_ids.add(rid)
        if rid.startswith("R"):
            request = request_of.get(rid)
            if request is None:
                result.unusable = "unknown_id"
                return result
            index, nominated = index_of[request.sentence], False
        else:
            if not plan.open_review.enabled or rid not in index_of:
                result.unusable = "unknown_id"
                return result
            index = index_of[rid]
            nominated = doc.units[index].id not in request_at
        if index in seen_sentences:
            result.unusable = "duplicate_sentence"
            return result
        seen_sentences.add(index)
        targets.append((index, rid, item["text"], item["reason"], nominated))

    budget = max(0, plan.open_review.max_sentences - nominated_before)
    spans = plan.protected
    for index, rid, text, reason, nominated in targets:
        unit = doc.units[index]
        if nominated:
            if _frozen_unit(unit, spans):
                result.rejected[index] = ("replacement_frozen_unit", "unit", False)
                continue
            if budget <= 0:
                result.rejected[index] = ("open_review_limit", f"max:{plan.open_review.max_sentences}", False)
                continue
            budget -= 1
            result.nominated.add(index)
        request = request_at.get(unit.id)
        problem = _validate(unit, text, spans, bool(request and request.allow_split))
        result.supplied[index] = request.id if request is not None else rid
        result.reasons[index] = reason
        if problem is not None:
            result.rejected[index] = (problem[0], problem[1], True)
            continue
        core = text.strip()
        if core != unit.text:
            result.texts[index] = core
    return result


# --------------------------------------------------------------------------
# full text
# --------------------------------------------------------------------------
def distribute(doc: Document, text: str) -> Dict[int, Optional[str]]:
    """Per source sentence, its text in `text` (aligned with align.align_documents): the joined span of
    its output units; None when it was merged with another sentence, "" when it was deleted. Inserted sentences join
    their neighbour in the same paragraph (the one before, else the one after)."""
    out = T.segment(text)
    pairs = A.align_documents(doc, out)
    groups: List[Tuple[List[int], List[int]]] = [(list(p.src), list(p.out)) for p in pairs]
    # attach insertions (0:1) to a neighbour group that has a source sentence in the same paragraph
    merged: List[Tuple[List[int], List[int]]] = []
    pending: List[int] = []
    for src, outs in groups:
        if not src:
            j = outs[0]
            if merged and merged[-1][0] and merged[-1][1] and out.units[merged[-1][1][-1]].para == out.units[j].para:
                merged[-1][1].append(j)
            else:
                pending.append(j)
            continue
        if pending and outs and out.units[outs[0]].para == out.units[pending[0]].para:
            outs = pending + outs
        pending = []
        merged.append((src, outs))
    result: Dict[int, Optional[str]] = {}
    for src, outs in merged:
        if len(src) != 1 or not outs:
            for i in src:
                result[i] = None if outs else ""      # None: merged with another sentence; "": deleted
            continue
        first, last = out.units[min(outs)], out.units[max(outs)]
        result[src[0]] = text[first.start:last.end]
    return result


def apply_full_text(plan: Plan, doc: Document, rewritten: str, start: Sequence[str]) -> ApplyResult:
    """Full-text fallback (3.6): changed requested sentences become replacements, every other changed
    sentence is a collateral edit and keeps its start text."""
    result = ApplyResult(texts=list(start), full_text=True)
    text, _report = T.sanitize(rewritten)
    request_at = {r.sentence: r for r in plan.requests}
    spans = plan.protected
    for index, piece in sorted(distribute(doc, text).items()):
        unit = doc.units[index]
        request = request_at.get(unit.id)
        if piece is not None and (piece.strip() == unit.text or piece.strip() == start[index]):
            continue
        if request is None:
            result.collateral.add(index)
            continue
        result.supplied[index] = request.id
        if not piece:
            code = "replacement_merge" if piece is None else "sentence_dropped"
            result.rejected[index] = (code, "full_text", True)
            continue
        problem = _validate(unit, piece, spans, request.allow_split)
        if problem is not None:
            result.rejected[index] = (problem[0], problem[1], True)
            continue
        result.texts[index] = piece.strip()
    return result


def recover_texts(doc: Document, text: str, fallback: Sequence[str]) -> List[str]:
    """Per-sentence texts of a chunk decided earlier (attempt 2 reads the attempt-1 decision): the
    candidate this module assembled, so boundaries are stable and the alignment is 1:1 or a split.
    A sentence the alignment cannot give back (merged, deleted, or a paragraph break inside) takes
    `fallback[i]` (base(s)), which always verifies."""
    texts = list(fallback)
    for index, piece in distribute(doc, text).items():
        if piece is not None and "\n" not in piece and piece.strip():
            texts[index] = piece.strip()
    return texts
