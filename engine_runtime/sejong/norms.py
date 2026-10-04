"""Norm layer of Super Sejong Engine v2: deterministic FIX fixes and the introduced-norm check.

apply_fixes() applies the FIX/deterministic findings of diagnose.diagnose() (SSJ-N01 bound-noun
spacing, SSJ-N02 -지 않 spacing, SSJ-N04 closed misspelling list, CTA-SP1/SP2 주다 spacing, and the
할께 family SSJ-N04C only under SUPER_SEJONG_FIX_COLLOQUIAL=1). It is the repair step 1 of DESIGN 3.7
and runs on source sentences too (OD 3), outside every protected span.

Guarantees, each pinned by tests/skills/test_sejong_diagnose.py:
  idempotent      fix_text(fix_text(x)) == fix_text(x): a fixed form never matches its rule again
                  (the syllable before 수/것/때/않/주 becomes a space; every misspelling's right-hand
                  side is outside its pattern)
  voice-neutral   no fix changes a sentence's level, mood, -시- (final or embedded), humble form or
                  persona (OD 4): fixes touch spacing, one stem syllable or a closed spelling, never an
                  ending's level or an honorific; a form whose spelling the voice regex reads differently
                  is kept out of the list until voice reads both spellings alike (뵈요 -> 봬요 and
                  뵜 -> 뵀 joined in WP-10b, once voice_lexicon.json listed 봬/뵀/뵜 as humble)
  protected       a finding that touches a freeze or keep-token span is never applied

introduced(src, out) is the "norms" verification family of 3.8: norm_introduced (hard) when the
rewrite adds an error of SSJ-N01..N06 or SSJ-A04 that the source did not have, and tell_introduced
(soft) when an LLM-tell count rises. Errors already in the source are not the writer's and are never
flagged, as in the josa gate. Violations carry the rule id as detail, never document text.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, List, Optional, Sequence, Tuple

from . import diagnose as D
from . import protect as P
from . import text as T
from .types import Document, Finding, Span, Violation

HAYEOT = re.compile(r"하였")


def apply_fixes(text: str, findings: Iterable[Finding], spans: Sequence[Span]) -> Tuple[str, List[str]]:
    """Apply the deterministic findings (offsets into `text`) outside `spans`.

    Returns (new text, rule ids of the applied fixes in text order). A finding without a fix, one that
    is not deterministic, one that touches a protected span, or one that overlaps an earlier applied
    finding is skipped."""
    ordered = sorted((f for f in findings if f.action == "deterministic" and f.fix is not None and f.end > f.start),
                     key=lambda f: (f.start, f.end))
    spans = sorted(spans, key=lambda s: (s.start, s.end))
    starts = [s.start for s in spans]
    out: List[str] = []
    applied: List[str] = []
    last = 0
    for finding in ordered:
        if finding.start < last or finding.end > len(text):
            continue
        if D._overlaps(starts, spans, finding.start, finding.end):
            continue
        out.append(text[last:finding.start])
        out.append(finding.fix)
        applied.append(finding.rule)
        last = finding.end
    out.append(text[last:])
    return "".join(out), applied


def fix_text(text: str, *, genre: str = "general", fix_colloquial: bool = False,
             doc: Optional[Document] = None, spans: Optional[Sequence[Span]] = None) -> Tuple[str, List[str]]:
    """Segment, protect, diagnose and apply every FIX/deterministic finding of `text` in one pass."""
    doc = doc if doc is not None else T.segment(text)
    if spans is None:
        spans = P.protected_spans(doc, fix_colloquial=fix_colloquial)
    findings = D.diagnose(doc, genre=genre, fix_colloquial=fix_colloquial, spans=spans)
    return apply_fixes(text, findings, spans)


def _keys(text: str, rule_ids: Sequence[str], with_text: bool) -> Counter:
    doc = T.segment(text)
    spans = P.protected_spans(doc)
    counts: Counter = Counter()
    for rule, start, end, _fix in D.raw_hits(doc, spans, rule_ids):
        counts[(rule, re.sub(r"\s+", "", text[start:end])) if with_text else rule] += 1
    return counts


def introduced(src_text: str, out_text: str, *, sentence: Optional[str] = None) -> List[Violation]:
    """Norm errors and LLM tells that `out_text` adds relative to `src_text` (3.8 norms family).

    A norm error is keyed by (rule, matched text without spaces), so fixing one 율/률 error while
    adding another still counts as introduced; tells are compared by count per rule (plus 하였). One
    Violation per rule, detail = rule id; `sentence` is copied to every violation."""
    if src_text == out_text:
        return []
    src_norms, out_norms = _keys(src_text, D.NORM_RULES, True), _keys(out_text, D.NORM_RULES, True)
    norm_rules = sorted({key[0] for key, n in out_norms.items() if n > src_norms.get(key, 0)})
    src_tells, out_tells = _keys(src_text, D.TELL_RULES, False), _keys(out_text, D.TELL_RULES, False)
    tell_rules = {rule for rule, n in out_tells.items() if n > src_tells.get(rule, 0)}
    if _hayeot(out_text) > _hayeot(src_text):
        tell_rules.add("HAYEOT")
    out = [Violation(code="norm_introduced", family="norms", severity="hard", sentence=sentence, detail=rule)
           for rule in norm_rules]
    out.extend(Violation(code="tell_introduced", family="norms", severity="soft", sentence=sentence, detail=rule)
               for rule in sorted(tell_rules))
    return out


def _hayeot(text: str) -> int:
    """하였 outside freeze spans (the vendor P3 "hayeot" counter)."""
    return len(HAYEOT.findall(D.masked_text(text, P.protected_spans(T.segment(text)))))
