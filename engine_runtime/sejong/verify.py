"""Verification of Super Sejong Engine v2 (DESIGN.md 3.8, 3.10, 4.4).

    family_violations(src, out, pairs, *, flags, genre, fix_colloquial, spans, ...) -> list[Violation]
    classify(flags, violations)                  -> (enforced, shadow)
    verify_document(before, after, *, context=None, attempt=1, flags=None) -> dict   legacy gate JSON
    verify_block(source, result, *, flags=None)  -> list[Violation]                  Office (reject only)
    change_rate(a, b) -> float ; text_distance(a, b) -> float ; rate_of_texts(before, after) -> float

Every family runs on the same pairs (WP-2 alignment, or the pairs the check step builds by construction
from sentence ids) and skips identical pairs, so verify(x, x) costs one segmentation and no analysis:

  floor     floor.check_pair per changed pair (text-level codes, protected_span_changed, josa at
            "certain"); floor.check on the whole text in verify_document           always enforced
  meaning   meaning.check (groups unpaired sentences with their neighbours)        family mode
  voice     voice_gate.check                                                       family mode
  cta       cta_gate.compare: hard and soft (info is never acted on)              family mode
  flow      flow.check with the seam texts and the open-review licences; mode per violation from
            flow.violation_mode (flow_sentence_added stays shadow)
  clarity   clarity.check (default shadow), mode per violation like flow
  norms     norms.introduced per changed pair (norm_introduced hard, tell_introduced soft)
  runaway   change_rate >= RUNAWAY on the whole chunk or document                 always enforced

A violation of a family in mode "off" is dropped, one in "shadow" is reported in shadowFailures only, and
one in "enforce" (hard or soft) is acted on. Families whose mode is off are not computed at all.

Gate JSON (verify_document, the `verify` CLI and workflow.py under SUPER_SEJONG_ENGINE=v2): exactly the
legacy keys gate.exit_code, hardFailures, warningReasons {version: 1, codes}, policy, shadowFailures
(lowercase codes only), plus changeRate. Exit 2 = an enforced hard code (floor, meaning, voice, CTA,
flow, norms, runaway); exit 1 = enforced soft codes only (listed in shadowFailures, because hardFailures
may only accompany exit 2 or 3); exit 0 = nothing enforced. warningReasons.codes holds at most
P0_CHANGE_RATE, set exactly when the runaway guard fires; P1_STYLE_TARGET is never emitted (OD 8).

change_rate is sentence-segmented and linear: aligned sentence pairs, each compared by a character
alignment capped at SEQ_CAP code points per side (a longer pair counts as wholly changed), summed and
divided by the source length. There is no whole-text SequenceMatcher (DESIGN 6).
"""
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from . import align as A
from . import clarity as CL
from . import config as C
from . import cta_gate as CG
from . import floor as F
from . import flow as FL
from . import meaning as M
from . import norms as N
from . import protect as P
from . import text as T
from . import voice_gate as VG
from .io import read_text
from .types import Document, Span, Violation, gate_policy, is_code

RUNAWAY = 0.50
SEQ_CAP = 2000
MAX_CODES = 100
PathOrText = Union[str, Path]


# --------------------------------------------------------------------------
# change rate
# --------------------------------------------------------------------------
def text_distance(a: str, b: str) -> float:
    """Half the symmetric difference of the characters of a and b under a character alignment
    ((len a + len b - 2 * matched) / 2); a pair longer than SEQ_CAP on either side counts as wholly changed."""
    if a == b:
        return 0.0
    if len(a) > SEQ_CAP or len(b) > SEQ_CAP:
        return float(max(len(a), len(b)))
    matched = sum(block.size for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    return (len(a) + len(b) - 2 * matched) / 2


def rate_of_texts(before: Sequence[str], after: Sequence[str]) -> float:
    """Change rate of two sentence lists that correspond index by index."""
    total = sum(len(x) for x in before)
    return sum(text_distance(a, b) for a, b in zip(before, after)) / max(1, total)


def _joined(doc: Document, indices: Sequence[int]) -> str:
    if not indices:
        return ""
    first, last = doc.units[min(indices)], doc.units[max(indices)]
    return doc.text[first.start:last.end]


def change_rate(a: str, b: str, *, src: Optional[Document] = None, out: Optional[Document] = None,
                pairs: Optional[Sequence[A.Pair]] = None) -> float:
    """Sentence-segmented change rate of b against a (0.0 for identical texts)."""
    if a == b:
        return 0.0
    src = src if src is not None else T.segment(a)
    out = out if out is not None else T.segment(b)
    pairs = pairs if pairs is not None else A.align_documents(src, out)
    distance = sum(text_distance(_joined(src, p.src), _joined(out, p.out)) for p in pairs)
    return distance / max(1, sum(len(u.text) for u in src.units))


# --------------------------------------------------------------------------
# families
# --------------------------------------------------------------------------
def mode_of(flags: C.Flags, violation: Violation) -> str:
    family = violation.family or "floor"
    if family in ("flow", "clarity"):
        return FL.violation_mode(flags, violation)
    if family in C.OVERRIDABLE:
        return C.family_mode(flags, family)
    return "enforce"                       # floor, runaway and the check step's own codes


def classify(flags: C.Flags, violations: Sequence[Violation]) -> Tuple[List[Violation], List[Violation]]:
    """(enforced, shadow) violations; info severity and families in mode off are dropped."""
    enforced: List[Violation] = []
    shadow: List[Violation] = []
    for v in violations:
        if v.severity == "info":
            continue
        mode = mode_of(flags, v)
        if mode == "enforce":
            enforced.append(v)
        elif mode == "shadow":
            shadow.append(v)
    return enforced, shadow


def _on(flags: C.Flags, family: str) -> bool:
    return C.family_mode(flags, family) != "off"


def changed_pairs(src: Document, out: Document, pairs: Sequence[A.Pair]) -> List[A.Pair]:
    return [p for p in pairs if p.src and p.out and _joined(src, p.src) != _joined(out, p.out)]


def family_violations(src: Document, out: Document, pairs: Sequence[A.Pair], *, flags: C.Flags,
                      genre: str = "general", fix_colloquial: bool = False, spans: Sequence[Span] = (),
                      document: Optional[str] = None, seam: Optional[Mapping[str, str]] = None,
                      allow: Optional[Mapping[str, Sequence[str]]] = None) -> List[Violation]:
    """Every family's violations of `out` against `src` on `pairs` (all severities; see classify)."""
    if src.text == out.text:
        return []
    found: List[Violation] = []
    norms_on = _on(flags, "norms")
    for pair in changed_pairs(src, out, pairs):
        units = [src.units[i] for i in pair.src]
        out_text = _joined(out, pair.out)
        sid = units[0].id
        found.extend(F.check_pair(units if len(units) > 1 else units[0], out_text, spans, document=document,
                                  sentence=sid))
        if norms_on:
            found.extend(N.introduced(_joined(src, pair.src), out_text, sentence=sid))
    if _on(flags, "voice"):
        found.extend(VG.check(src, out, pairs, fix_colloquial=fix_colloquial))
    if _on(flags, "meaning"):
        found.extend(M.check(src, out, pairs))
    if _on(flags, "cta"):
        result = CG.compare(src, out, pairs)
        found.extend(result["hard"])
        found.extend(result["soft"])
    if _on(flags, "flow"):
        found.extend(FL.check(src, out, pairs, seam=seam, allow=allow))
    if _on(flags, "clarity"):
        found.extend(CL.check(src, out, pairs, genre=genre))
    return found


def unique_codes(violations: Sequence[Violation], limit: int = MAX_CODES) -> List[str]:
    out: List[str] = []
    for v in violations:
        if is_code(v.code) and v.code not in out:
            out.append(v.code)
    return out[:limit]


# --------------------------------------------------------------------------
# document gate (legacy JSON)
# --------------------------------------------------------------------------
def _read(value: Optional[PathOrText]) -> Optional[str]:
    if value is None:
        return None
    return read_text(value) if isinstance(value, Path) else value


def gate_json(exit_code: int, attempt: int, hard: Sequence[str], shadow: Sequence[str],
              runaway: bool, rate: float) -> Dict[str, Any]:
    return {"gate": {"exit_code": exit_code}, "hardFailures": list(hard)[:MAX_CODES],
            "warningReasons": {"version": 1, "codes": ["P0_CHANGE_RATE"] if runaway else []},
            "policy": gate_policy(exit_code, attempt), "shadowFailures": list(shadow)[:MAX_CODES],
            "changeRate": round(rate, 3)}


def document_violations(before: str, after: str, *, context: Optional[str] = None,
                        flags: Optional[C.Flags] = None, genre: str = "general") -> Tuple[List[Violation], float]:
    """(violations of every family, change rate) of a whole text pair, aligned with align_documents."""
    flags = flags if flags is not None else C.Flags.from_env()
    if before == after:
        return [], 0.0
    src, out = T.segment(before), T.segment(after)
    pairs = A.align_documents(src, out)
    spans = P.protected_spans(src, fix_colloquial=flags.fix_colloquial)
    found = list(F.check(before, after, document=context, spans=spans))
    found.extend(family_violations(src, out, pairs, flags=flags, genre=genre, fix_colloquial=flags.fix_colloquial,
                                   spans=spans, document=context))
    rate = change_rate(before, after, src=src, out=out, pairs=pairs)
    if rate >= RUNAWAY:
        found.append(Violation(code="change_rate_runaway", family="runaway", severity="hard",
                               detail=f"rate:{rate:.2f}"))
    return found, rate


def verify_document(before: PathOrText, after: PathOrText, *, context: Optional[PathOrText] = None,
                    attempt: int = 1, flags: Optional[C.Flags] = None, genre: Optional[str] = None) -> Dict[str, Any]:
    """Legacy gate JSON of `after` against `before` (paths or texts); `context` is the whole document
    when `before` is one chunk of it (footnote markers). verify_document(x, x) is exit 0 with no code."""
    flags = flags if flags is not None else C.Flags.from_env()
    source, output = _read(before), _read(after)
    found, rate = document_violations(source, output, context=_read(context), flags=flags,
                                      genre=genre or flags.genre_default)
    enforced, shadow = classify(flags, found)
    hard = unique_codes([v for v in enforced if v.severity == "hard"])
    soft = unique_codes([v for v in enforced if v.severity != "hard"])
    exit_code = 2 if hard else 1 if soft else 0
    shadow_codes = unique_codes([*(v for v in enforced if v.severity != "hard"), *shadow])
    runaway = any(v.code == "change_rate_runaway" for v in found)
    return gate_json(exit_code, attempt, hard, shadow_codes, runaway, rate)


def verify_block(source: str, result: str, *, flags: Optional[C.Flags] = None,
                 genre: str = "document") -> List[Violation]:
    """Enforced violations (hard and soft) of one Office block rewrite: the caller rejects the edit when
    the list is non-empty and never repairs it (DESIGN 4.3, WP-12)."""
    flags = flags if flags is not None else C.Flags.from_env()
    found, _rate = document_violations(source, result, flags=flags, genre=genre)
    enforced, _shadow = classify(flags, found)
    return [v for v in enforced if v.code != "change_rate_runaway"]
