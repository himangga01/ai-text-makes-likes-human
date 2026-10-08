"""Edit plan of Super Sejong Engine v2 (DESIGN.md 3.3, 3.4, 3.12).

    build_plan(chunk_text, *, options, chunk=None, context=None, seam=None, flags=None) -> Plan
    source_document(plan, source) -> Document     the chunk segmented exactly as the plan describes it
    base_texts(plan, source)      -> list[str]    base(s) per sentence: source + deterministic fixes

The plan is everything the writer and the check step need, computed once per chunk from the WP-1..WP-8
modules (nothing here detects anything itself):

  sentences    text.segment units with the voice signature (voice.signature), the CTA ledger id
               (cta.detect), the meaning ledger (meaning.ledger) and the ids of their findings
  findings     diagnose.diagnose (3.3 table, genre-gated tiers), renumbered F1.. in text order; a
               paragraph-scope finding (CLR-LONG, CONNECTOR_RUN, clusters) is clipped to the sentence it
               starts in, so every finding lies inside one sentence
  requests     one per sentence (R1.. in sentence order) that has a request finding of a requested tier;
               tier FIX when any of its rules is FIX, else SUGGEST; guides from data/guides.ko.json
  deterministic  the FIX/deterministic findings with their before/after text, in the order and with the
               overlap rule of norms.apply_fixes, so base(s) is exactly what repair step 1 produces on an
               untouched sentence. Recorded for every scope; applied per SUPER_SEJONG_DETERMINISTIC_FIX
               (all: every sentence; edited-only: replaced sentences only; off: never). A sentence whose
               fixed form does not verify against its source (any enforced family) keeps no fix, so
               verify(x, base(x)) == [] holds by construction; stats.deterministicDropped counts them

Strength -> requested tiers (3.4 with lead decision 9.2a item 2):

  normal, and every text-file job     FIX
  medium, strong, very-strong         FIX + SUGGEST (SUGGEST off under SUPER_SEJONG_MODE=off)
  open review                         config.open_review_enabled (default: medium and up), never for a
                                      text-file job; maxSentences = max(3, ceil(0.1 * n)) over the n
                                      sentences the writer may nominate (body, list, quote or button units
                                      with Hangul, not wholly frozen). A chunk with no such sentence gets no
                                      open review, so it never costs a call for nothing
  allowSplit                          a request with a rule that allows splitting (CLR-LONG), strength
                                      medium and up
  allowFullText                       very-strong and rewrite

Strength rewrite (WP-19, 매우 강하게(다시쓰기)): FIX + SUGGEST requests are computed as above and sent as context
only, there is no open review, allowFullText is true, options.mode is "rewrite" and plan.paragraphs lists every
source paragraph with its voice rule (rewrite.plan_paragraphs); prompt, apply, verify and decide then work per
paragraph (rewrite.py). needsModel = some paragraph is editable.

needsModel = requests non-empty or openReview.enabled; when false the check step runs without a model call
and the candidate is base(x) [G6, 3.4 step 4].

Values the plan schema bounds (final eojeol, CTA components, list lengths) are clipped here, never
rejected, so a long run-on sentence cannot make analyse fail. Everything is linear in the chunk.
"""
from __future__ import annotations

import hashlib
import math
from typing import Dict, List, Optional, Sequence, Tuple

from . import config as C
from . import cta as CTA
from . import diagnose as D
from . import meaning as M
from . import protect as P
from . import text as T
from . import voice as V
from .types import (PLAN_SCHEMA, ChunkInfo, CtaUnit, DeterministicFix, Document, EngineInfo, Finding,
                    OpenReview, Options, Plan, PlanSentence, Profile, Request, Seam, Span, Unit, VoiceSig)

REVIEW_MIN = 3                 # open review: at least this many nominations ...
REVIEW_SHARE = 0.1             # ... or this share of the nominable sentences, rounded up
REVIEW_KINDS = ("body", "list", "quote", "button")
SPLIT_STRENGTHS = ("medium", "strong", "very-strong")
FULL_TEXT_STRENGTHS = ("very-strong", "rewrite")
TIER_ORDER = ("FIX", "SUGGEST", "LEAVE")

# Schema bounds (schemas/plan.schema.json): shortText 80, shortList 40 items, final 200, stance 40,
# condition 200, meaning entries 200, guide 300, finding fix and deterministic before/after 200.
_SHORT, _LIST, _FINAL, _STANCE, _COND, _GUIDE = 80, 40, 200, 40, 200, 300


def _clip(value: Optional[str], limit: int) -> Optional[str]:
    return value if value is None or len(value) <= limit else value[:limit]


def _clip_list(values: Sequence[str], limit: int = _SHORT, items: int = _LIST) -> List[str]:
    return [value[:limit] for value in list(values)[:items]]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# strength and options
# --------------------------------------------------------------------------
def requested_tiers(options: Options, flags: C.Flags) -> Tuple[str, ...]:
    """The finding tiers that become requests (3.4)."""
    if options.strength == "normal" or options.input_kind == "text-file":
        return ("FIX",)
    return ("FIX", "SUGGEST") if C.suggest_requests_enabled(flags) else ("FIX",)


def review_wanted(options: Options, flags: C.Flags) -> bool:
    return options.input_kind != "text-file" and C.open_review_enabled(flags, options.strength)


def review_limit(nominable: int) -> int:
    return max(REVIEW_MIN, math.ceil(REVIEW_SHARE * nominable))


def nominable(unit: Unit, spans: Sequence[Span]) -> bool:
    """A sentence the open review may nominate: an editable kind, some Hangul, not wholly frozen."""
    if unit.kind not in REVIEW_KINDS or not any("가" <= ch <= "힣" for ch in unit.text):
        return False
    frozen = sum(min(s.end, unit.end) - max(s.start, unit.start)
                 for s in P.spans_in(unit, spans, "freeze"))
    return frozen < len(unit.text.strip())


# --------------------------------------------------------------------------
# the plan
# --------------------------------------------------------------------------
def _voice(unit: Unit) -> VoiceSig:
    sig = V.signature(unit.text, unit.kind)
    sig.final = _clip(sig.final, _FINAL) or ""
    sig.stance = _clip(sig.stance, _STANCE)
    sig.persona, sig.cmc, sig.discourse = _clip_list(sig.persona), _clip_list(sig.cmc), _clip_list(sig.discourse)
    sig.addressee = _clip(sig.addressee, _STANCE)
    return sig


def _cta_units(doc: Document) -> List[CtaUnit]:
    units, _ = CTA.detect(doc)
    for unit in units:
        unit.action, unit.deadline = _clip_list(unit.action), _clip_list(unit.deadline)
        unit.channel, unit.benefit = _clip_list(unit.channel), _clip_list(unit.benefit)
        unit.intensity = _clip_list(unit.intensity)
        unit.object, unit.condition = _clip(unit.object, _SHORT), _clip(unit.condition, _COND)
    return units


def _findings(doc: Document, options: Options, spans: Sequence[Span]) -> List[Finding]:
    """diagnose() findings clipped to their sentence and renumbered F1.. (ids are local to diagnose)."""
    raw = D.diagnose(doc, genre=options.genre, fix_colloquial=options.fix_colloquial, spans=spans)
    by_id = {unit.id: unit for unit in doc.units}
    out: List[Finding] = []
    for finding in raw:
        unit = by_id[finding.sentence]
        start, end = max(finding.start, unit.start), min(finding.end, unit.end)
        if finding.action == "deterministic" and (start, end) != (finding.start, finding.end):
            continue                       # a deterministic edit across a sentence boundary is never applied
        if end < start:
            continue
        out.append(Finding(id=f"F{len(out) + 1}", rule=finding.rule, tier=finding.tier, action=finding.action,
                           sentence=finding.sentence, start=start, end=end, fix=_clip(finding.fix, 200)))
    return out


def _deterministic(text: str, findings: Sequence[Finding]) -> List[DeterministicFix]:
    """The fixes norms.apply_fixes applies, in its order and with its overlap rule (diagnose already
    dropped every deterministic finding that touches a protected span)."""
    ordered = sorted((f for f in findings if f.action == "deterministic" and f.fix is not None and f.end > f.start),
                     key=lambda f: (f.start, f.end))
    out: List[DeterministicFix] = []
    last = 0
    for f in ordered:
        if f.start < last or len(text[f.start:f.end]) > 200:
            continue
        out.append(DeterministicFix(finding=f.id, sentence=f.sentence, start=f.start, end=f.end,
                                    before=text[f.start:f.end], after=f.fix))
        last = f.end
    return out


def _verified(doc: Document, chunk_text: str, fixes: List[DeterministicFix], spans: Sequence[Span],
              options: Options, flags: C.Flags) -> Tuple[List[DeterministicFix], int]:
    """The fixes whose sentences still verify against the source (invariant verify(x, base(x)) == [],
    DESIGN 3.9). Fixes are meaning-, voice- and CTA-neutral by contract; a sentence on which some family
    disagrees keeps its source text instead of failing every later check, and the plan records only the
    fixes that are really applied. Returns (kept, dropped count)."""
    from . import apply as AP, decide as DC, floor as F, verify as VF   # late: these import plan helpers
    kept = list(fixes)
    for _round in range(2):
        if not kept:
            break
        by = deterministic_by_sentence_list(kept)
        texts = [apply_sentence_fixes(unit, by.get(unit.id, ())) for unit in doc.units]
        fixed = {k for k, unit in enumerate(doc.units) if texts[k] != unit.text}
        cand = AP.candidate_document(doc, texts)
        bad = {doc.units[k].id for k in cand.unstable}
        found = VF.family_violations(doc, cand.doc, cand.pairs, flags=flags, genre=options.genre,
                                     fix_colloquial=options.fix_colloquial, spans=spans)
        found += F.check(chunk_text, cand.text, spans=spans)
        enforced, _shadow = VF.classify(flags, found)
        index = {unit.id: k for k, unit in enumerate(doc.units)}
        for v in enforced:
            k = index.get(v.sentence) if v.sentence else None
            for target in (DC.attribute(k, fixed, doc) if k is not None else sorted(fixed)):
                bad.add(doc.units[target].id)
        if not bad:
            break
        kept = [f for f in kept if f.sentence not in bad]
    return kept, len(fixes) - len(kept)


def deterministic_by_sentence_list(fixes: Sequence[DeterministicFix]) -> Dict[str, List[DeterministicFix]]:
    out: Dict[str, List[DeterministicFix]] = {}
    for fix in fixes:
        out.setdefault(fix.sentence, []).append(fix)
    return out


def _requests(doc: Document, findings: Sequence[Finding], tiers: Sequence[str], strength: str) -> List[Request]:
    per_sentence: Dict[str, List[Finding]] = {}
    for f in findings:
        if f.action == "request" and f.tier in tiers:
            per_sentence.setdefault(f.sentence, []).append(f)
    out: List[Request] = []
    for unit in doc.units:
        hits = per_sentence.get(unit.id)
        if not hits:
            continue
        rules = list(dict.fromkeys(f.rule for f in hits))[:40]
        guides = [g[:_GUIDE] for g in dict.fromkeys(D.guide(rule) for rule in rules) if g and g.strip()][:40]
        split = strength in SPLIT_STRENGTHS and any(D.RULES[rule].allow_split for rule in rules)
        tier = "FIX" if any(f.tier == "FIX" for f in hits) else "SUGGEST"
        out.append(Request(id=f"R{len(out) + 1}", sentence=unit.id, rules=rules, tier=tier,
                           allow_split=split, guides=guides))
    return out


def build_plan(chunk_text: str, *, options: Options, chunk: Optional[ChunkInfo] = None,
               context: Optional[str] = None, seam: Optional[Tuple[Tuple[int, int], Tuple[int, int]]] = None,
               flags: Optional[C.Flags] = None) -> Plan:
    """The edit plan of one chunk (DESIGN 3.4). `options` carries input kind, strength and genre (and
    fix_colloquial / deterministic_fix, which the CLI takes from the environment); open_review and
    allow_full_text are decided here and returned in plan.options. `chunk` defaults to 1 of 1; `seam` is
    the chunk's ((prev_start, prev_end), (next_start, next_end)) code-point ranges into the prepared
    document (chunk.seam_ranges), `context` that document (only its presence is recorded: footnotes and
    seam texts are resolved by the check step)."""
    del context
    flags = flags if flags is not None else C.Flags.from_env()
    if chunk is None:
        chunk = ChunkInfo(index=1, total=1, source_sha256=_sha256(chunk_text), chars=len(chunk_text))
    doc = T.segment(chunk_text)
    if len(doc.units) > 9999:
        raise ValueError("chunk has more than 9999 sentences")
    spans = P.protected_spans(doc, fix_colloquial=options.fix_colloquial)
    findings = _findings(doc, options, spans)
    requests = _requests(doc, findings, requested_tiers(options, flags), options.strength)
    deterministic, dropped = _verified(doc, chunk_text, _deterministic(chunk_text, findings), spans, options, flags)

    review_count = sum(1 for unit in doc.units if nominable(unit, spans)) if review_wanted(options, flags) else 0
    review = OpenReview(enabled=review_count > 0, max_sentences=review_limit(review_count) if review_count else 0)
    rewrite = options.strength == "rewrite"
    resolved = Options(input_kind=options.input_kind, strength=options.strength, genre=options.genre,
                       fix_colloquial=options.fix_colloquial, deterministic_fix=options.deterministic_fix,
                       open_review=review.enabled, allow_full_text=options.strength in FULL_TEXT_STRENGTHS,
                       mode="rewrite" if rewrite else None)
    paragraphs = None
    if rewrite:
        from . import rewrite as RW                 # late: rewrite reads plan helpers
        paragraphs = RW.plan_paragraphs(doc, spans)

    ctas = _cta_units(doc)
    cta_of = {c.sentence: c.id for c in ctas}
    findings_of: Dict[str, List[str]] = {}
    for f in findings:
        findings_of.setdefault(f.sentence, []).append(f.id)
    sentences = [PlanSentence(id=u.id, start=u.start, end=u.end, start_u16=u.start_u16, end_u16=u.end_u16,
                              para=u.para, kind=u.kind, voice=_voice(u), cta=cta_of.get(u.id),
                              meaning=M.ledger(u.text)[:200], findings=findings_of.get(u.id, [])[:200])
                 for u in doc.units]
    prof = V.profile(doc)
    by_tier = {tier: 0 for tier in TIER_ORDER}
    for f in findings:
        by_tier[f.tier] += 1
    by_request = {"FIX": 0, "SUGGEST": 0}
    for r in requests:
        by_request[r.tier] += 1
    (prev, nxt) = seam if seam is not None else ((0, 0), (0, 0))
    return Plan(schema=PLAN_SCHEMA, engine=EngineInfo(), chunk=chunk, options=resolved, sentences=sentences,
                protected=list(spans), cta_ledger=ctas, findings=findings, requests=requests,
                deterministic=deterministic,
                profile=Profile(dominant=prof["dominant"], share=prof["share"], mixed=prof["mixed"],
                                line=_clip(prof["line"], 200) or ""),
                seam=Seam(prev=tuple(prev), next=tuple(nxt)), open_review=review,
                needs_model=any(p.editable for p in paragraphs) if paragraphs is not None
                else bool(requests) or review.enabled, paragraphs=paragraphs,
                stats={"findingsByTier": by_tier, "requestsByTier": by_request,
                       "deterministicFixes": len(deterministic), "deterministicDropped": dropped,
                       "nominable": review_count})


# --------------------------------------------------------------------------
# reading a plan back against its chunk
# --------------------------------------------------------------------------
class PlanMismatch(ValueError):
    """The source text is not the chunk the plan was built from."""


def source_document(plan: Plan, source: str) -> Document:
    """The chunk as a Document whose units are exactly plan.sentences (same ids, offsets and kinds).
    Raises PlanMismatch when the source differs from the plan's chunk (SHA-256 or segmentation)."""
    if _sha256(source) != plan.chunk.source_sha256 or len(source) != plan.chunk.chars:
        raise PlanMismatch("source does not match plan.chunk.sourceSha256")
    doc = T.segment(source)
    if [(u.id, u.start, u.end) for u in doc.units] != [(s.id, s.start, s.end) for s in plan.sentences]:
        raise PlanMismatch("the plan's sentences differ from this engine's segmentation of the source")
    for unit, sentence in zip(doc.units, plan.sentences):
        unit.kind = sentence.kind
    return doc


def deterministic_by_sentence(plan: Plan) -> Dict[str, List[DeterministicFix]]:
    return deterministic_by_sentence_list(plan.deterministic)


def apply_sentence_fixes(unit: Unit, fixes: Sequence[DeterministicFix]) -> str:
    """The unit's text with its plan fixes applied (offsets are chunk offsets)."""
    text, pieces, last = unit.text, [], 0
    for fix in sorted(fixes, key=lambda f: f.start):
        a, b = fix.start - unit.start, fix.end - unit.start
        if a < last or text[a:b] != fix.before:
            continue
        pieces.append(text[last:a])
        pieces.append(fix.after)
        last = b
    pieces.append(text[last:])
    return "".join(pieces)


def base_texts(plan: Plan, source: str, doc: Optional[Document] = None) -> List[str]:
    """base(s) for every sentence: the source sentence plus its deterministic fixes when the scope is
    `all` (edited-only and off leave untouched sentences as they are)."""
    doc = doc if doc is not None else source_document(plan, source)
    if plan.options.deterministic_fix != "all":
        return [unit.text for unit in doc.units]
    fixes = deterministic_by_sentence(plan)
    return [apply_sentence_fixes(unit, fixes.get(unit.id, ())) for unit in doc.units]

