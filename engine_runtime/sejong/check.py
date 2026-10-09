"""One check attempt of Super Sejong Engine v2: apply, repair, verify, decide (DESIGN.md 3.6-3.9).

    check(plan, source, *, response=None, candidate=None, attempt=1, base=None, document=None,
          flags=None) -> CheckOutcome(text, report)

`source` is the chunk the plan was built from (SHA-256 checked); exactly one of `response` (the writer's
reply, a dict) and `candidate` (a full rewritten chunk, handled as the full-text fallback) may be given,
and neither means "no model call" (plan.needsModel false): the outcome is then base(x), the source plus
the deterministic fixes. At attempt 2 `base` is the decided text of attempt 1 (the CLI's --base); its
per-sentence texts are recovered (apply.recover_texts), the retry replies land on them, and every
sentence is verified again against the source. `document` is the whole prepared source when the chunk
is part of a longer document (footnote markers and seam context).

Steps (each sentence is decided on its own; nothing ever fails the whole chunk for one sentence):
  1. apply      apply.apply_response / apply.apply_full_text: per-sentence candidate texts, rejections,
                collateral edits, open-review nominations
  2. repair     repair.repair_candidate on the sentences this attempt edited; untouched sentences take
                base(s) (attempt 1) or their attempt-1 decision (attempt 2)
  3. stability  a sentence whose replacement moved a sentence boundary is reverted (apply module docs)
  4. verify     verify.family_violations on the candidate with pairs by construction; enforced and
                shadow violations per source sentence; the runaway guard on the whole chunk
  5. decide     decide.decide_sentence per sentence; retry and revert both put base(s) in the decided
                text. The decided candidate is verified again (a revert can change a neighbour's
                context) until nothing new appears, at most MAX_ROUNDS times, then the floor runs on the
                whole chunk; anything it still finds reverts the sentences concerned, and in the end the
                source itself, which always passes
  6. report     the check report of DESIGN 3.12 (types.CheckReport), codes and counts only

A rewrite plan (strength rewrite, options.mode "rewrite") is decided per paragraph by rewrite.check instead, with the
same arguments and the same CheckOutcome.

Request status (plan requests only): DECLINED = no replacement was supplied (in this attempt, or for
attempt 2 in attempt 1 either); UNTOUCHED = the supplied text equals base(s); FIXED = the decided
sentence differs from base(s) and every rule of the request passes its success check
(diagnose.request_fixed; CLR-LONG: no piece is still long); STILL_PRESENT = anything else (the edit was
sent to retry, reverted or rejected, or a rule still fires). LOST is never produced: a sentence is never
delivered deleted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from . import apply as AP
from . import clarity as CL
from . import config as C
from . import decide as DC
from . import diagnose as D
from . import floor as F
from . import plan as PL
from . import repair as RP
from . import verify as VF
from .types import (CheckReport, Plan, RetryItem, SentenceVerdict, Violation, empty_counts,
                    empty_request_status, is_code)

MAX_ROUNDS = 3
MAX_RETRY_VIOLATIONS = 40
CONNECTIVE_LICENCE = ("flow_transition_added", "flow_contrast_changed")
DETAIL_MAX = 200
POLARITY_RULES = ("SSJ-A06",)
LICENSED_BY_POLARITY_RULES = ("polarity_changed", "modality_changed", "lexical_polarity_changed")


@dataclass
class CheckOutcome:
    text: str                      # the decided chunk (what attempt 2 or reassembly uses)
    report: CheckReport


def _violation(code: str, sentence: str, detail: str = "", family: Optional[str] = None,
               keep: Optional[str] = None) -> Violation:
    return Violation(code=code, family=family, severity="hard", sentence=sentence, detail=detail[:DETAIL_MAX],
                     keep=keep[:DETAIL_MAX] if keep else None)


def _request_fixed(rule: str, text: str, genre: str) -> bool:
    rule_def = D.RULES.get(rule)
    if rule_def is None:
        return True
    if rule == "CLR-LONG":
        return not CL.long_review(text, genre)
    try:
        return D.request_fixed(rule, text)
    except ValueError:                      # a paragraph-scope rule without its own success check
        return True


class _State:
    """Per-check working state: texts per sentence and every sentence's verdict so far."""

    def __init__(self, plan: Plan, source: str, document: Optional[str], flags: C.Flags, attempt: int):
        self.plan, self.flags, self.attempt = plan, flags, attempt
        self.doc = PL.source_document(plan, source)
        self.n = len(self.doc.units)
        self.src = [u.text for u in self.doc.units]
        self.base = PL.base_texts(plan, source, self.doc)
        self.index = {u.id: k for k, u in enumerate(self.doc.units)}
        self.request_at = {r.sentence: r for r in plan.requests}
        self.document = document
        self.seam = None
        if plan.chunk.total > 1 and document is not None:
            (a, b), (c, d) = plan.seam.prev, plan.seam.next
            if b <= len(document) and d <= len(document):
                self.seam = {"prev": document[a:b], "next": document[c:d]}

    def candidate(self, texts: Sequence[str]) -> AP.Candidate:
        return AP.candidate_document(self.doc, texts)

    def licensed_meaning(self, k: int, text: str) -> bool:
        """A request whose rule asks for a polarity repair (SSJ-A06: 결코/좀처럼/차마/전혀 without a
        negation) licenses the polarity and modality change its own fix makes, once the rule's success
        check passes on the candidate; nothing else in the sentence is licensed."""
        request = self.request_at.get(self.doc.units[k].id)
        return bool(request and set(request.rules) & set(POLARITY_RULES) and text != self.base[k]
                    and all(D.request_fixed(rule, text) for rule in request.rules if rule in POLARITY_RULES))

    def verify(self, cand: AP.Candidate, allow: Dict[str, List[str]]):
        found = VF.family_violations(self.doc, cand.doc, cand.pairs, flags=self.flags,
                                     genre=self.plan.options.genre, fix_colloquial=self.plan.options.fix_colloquial,
                                     spans=self.plan.protected, document=self.document, seam=self.seam,
                                     allow=allow)
        licensed = {}
        for v in found:
            k = self.index.get(v.sentence) if v.sentence else None
            if k is not None and v.code in LICENSED_BY_POLARITY_RULES and k not in licensed:
                a, b = cand.spans[k]
                licensed[k] = self.licensed_meaning(k, cand.text[a:b])
        found = [v for v in found if not (v.code in LICENSED_BY_POLARITY_RULES and licensed.get(self.index.get(v.sentence or "")))]
        enforced, shadow = VF.classify(self.flags, found)
        per: Dict[int, List[Violation]] = {}
        loose: List[Violation] = []
        for v in enforced:
            k = self.index.get(v.sentence) if v.sentence else None
            if k is None:
                loose.append(v)
            else:
                per.setdefault(k, []).append(v)
        return per, loose, shadow


def _charge(state: _State, per: Dict[int, List[Violation]], loose: Sequence[Violation],
            changed: Set[int]) -> Dict[int, List[Violation]]:
    """Enforced violations per changed sentence; a violation on an unchanged sentence goes to its changed
    neighbours (decide.attribute), an unattributed one to every changed sentence."""
    charged: Dict[int, List[Violation]] = {}
    for k, items in per.items():
        for target in DC.attribute(k, changed, state.doc) if changed else []:
            charged.setdefault(target, []).extend(items)
    for v in loose:
        for target in changed:
            charged.setdefault(target, []).append(v)
    return charged


def check(plan: Plan, source: str, *, response: Optional[object] = None, candidate: Optional[str] = None,
          attempt: int = 1, base: Optional[str] = None, document: Optional[str] = None,
          flags: Optional[C.Flags] = None) -> CheckOutcome:
    """Apply, repair, verify and decide one attempt (module docstring)."""
    if plan.options.mode == "rewrite":               # strength rewrite: decided per paragraph (WP-19)
        from . import rewrite as RW
        return RW.check(plan, source, response=response, candidate=candidate, attempt=attempt, base=base,
                        document=document, flags=flags)
    if response is not None and candidate is not None:
        raise ValueError("pass at most one of response and candidate")
    if attempt not in (1, 2):
        raise ValueError("attempt must be 1 or 2")
    if attempt == 2 and base is None:
        raise ValueError("attempt 2 needs the decided text of attempt 1")
    flags = flags if flags is not None else C.Flags.from_env()
    st = _State(plan, source, document, flags, attempt)
    n, doc = st.n, st.doc
    start = AP.recover_texts(doc, base, st.base) if attempt == 2 else list(st.src)
    previous = {k for k in range(n) if attempt == 2 and start[k] != st.base[k]}
    prev_nominated = {k for k in previous if doc.units[k].id not in st.request_at and plan.open_review.enabled}

    # 1. apply
    if response is not None:
        ar = AP.apply_response(plan, doc, response, start, nominated_before=len(prev_nominated))
    elif candidate is not None:
        ar = AP.apply_full_text(plan, doc, candidate, start)
    else:
        ar = AP.ApplyResult(texts=list(start))
    unusable = ar.unusable is not None
    if unusable:
        ar = AP.ApplyResult(texts=list(start), unusable=ar.unusable)
    edited = {k for k in range(n) if ar.texts[k] != start[k]}

    # 2. repair
    texts = [ar.texts[k] if k in edited else (start[k] if attempt == 2 else st.base[k]) for k in range(n)]
    rr = RP.repair_candidate(plan, doc, texts, edited, flags=flags)
    texts = rr.texts
    nominated = set(ar.nominated) | prev_nominated
    licensed = {k for k in range(n) if doc.units[k].id in st.request_at} | nominated
    allow: Dict[str, List[str]] = {}
    for k in nominated:
        if k in prev_nominated or AP.review_type(ar.reasons.get(k, "")) in AP.CONNECTIVE_TYPES:
            allow[doc.units[k].id] = list(CONNECTIVE_LICENCE)
    rejected: Dict[int, Tuple[str, str, bool]] = dict(ar.rejected)

    # 3. boundary stability
    cand = st.candidate(texts)
    while cand.unstable:
        bad = [k for k in cand.unstable if texts[k] != st.base[k]]
        if not bad:
            break
        for k in bad:
            texts[k] = st.base[k]
            rejected.setdefault(k, ("replacement_boundary", "boundary", k in edited))
        cand = st.candidate(texts)

    # 4. verify
    changed = {k for k in range(n) if texts[k] != st.base[k]}
    per, loose, shadow = st.verify(cand, allow) if changed or texts != st.src else ({}, [], [])
    charged = _charge(st, per, loose, changed)
    runaway = bool(changed) and VF.rate_of_texts(st.base, texts) >= VF.RUNAWAY

    # 5. decide
    verdicts: Dict[int, DC.Verdict] = {}
    reasons: Dict[int, List[Violation]] = {}
    for k in range(n):
        if k in ar.collateral:
            verdicts[k] = DC.Verdict("reverted", "revert", ["collateral_edit"])
            continue
        # A rejected replacement left the sentence at its start text; at attempt 2 that may be an accepted
        # attempt-1 edit, which is then verified like any other changed sentence.
        rejection = rejected.get(k) if texts[k] == st.base[k] else None
        verdicts[k] = DC.decide_sentence(changed=k in changed, deterministic=st.base[k] != st.src[k],
                                         licensed=k in licensed, rejection=rejection,
                                         enforced=charged.get(k, ()), attempt=attempt)
        reasons[k] = list(charged.get(k, ()))
        if rejection is not None:
            family = "floor" if rejection[0] == "protected_span_changed" else None
            reasons[k].insert(0, _violation(rejection[0], doc.units[k].id, rejection[1], family))
    if unusable and attempt == 1:
        for k in range(n):
            if doc.units[k].id in st.request_at:
                verdicts[k] = DC.Verdict("retry", "retry", ["model_output_unusable"])
                reasons[k] = [_violation("model_output_unusable", doc.units[k].id, ar.unusable or "")]
    if runaway:
        for k in sorted(changed):
            if verdicts[k].status in ("accepted", "retry"):
                verdicts[k] = (DC.Verdict("retry", "retry", ["change_rate_runaway"]) if attempt == 1
                               else DC.Verdict("reverted", "revert", ["change_rate_runaway"]))
                reasons.setdefault(k, []).append(Violation(code="change_rate_runaway", family="runaway",
                                                           severity="hard", sentence=doc.units[k].id,
                                                           detail="rate>=0.50"))
    for k, verdict in verdicts.items():
        if verdict.action != "keep":
            texts[k] = st.base[k]

    # Re-verify the decided candidate until no kept edit picks up a new enforced violation.
    final_shadow, dirty = shadow, False
    for _round in range(MAX_ROUNDS):
        kept = {k for k in range(n) if texts[k] != st.base[k]}
        if not kept:
            dirty = True
            break
        cand = st.candidate(texts)
        per, loose, final_shadow = st.verify(cand, allow)
        charged = _charge(st, per, loose, kept)
        if not charged:
            break
        for k, items in charged.items():
            verdicts[k] = DC.Verdict("reverted", "revert", list(dict.fromkeys(v.code for v in items)))
            reasons[k] = list(items)
            texts[k] = st.base[k]
    else:
        dirty = True
        for k in range(n):
            if texts[k] != st.base[k]:
                verdicts[k] = DC.Verdict("reverted", "revert", verdicts[k].codes or ["unstable_decision"])
                texts[k] = st.base[k]

    # Floor on the whole chunk: charged edits, then every edit, then the source itself (which passes).
    floor_failed: List[str] = []
    to_source = False                              # the ladder reached the source: base(x) itself failed the floor
    text = AP.assemble(doc, texts)[0]
    found = F.check(source, text, document=document, spans=plan.protected) if text != source else []
    for stage in ("charged", "edits", "source"):
        if not found:
            break
        dirty = True
        kept = {k for k in range(n) if texts[k] != st.base[k]}
        codes = VF.unique_codes(found)
        if stage == "source":
            to_source = True
            for k in range(n):
                if texts[k] != st.src[k]:
                    verdicts[k] = DC.Verdict("reverted", "revert", codes)
                    reasons[k] = list(found)
            texts = list(st.src)
        else:
            if stage == "charged":
                targets: Set[int] = set()
                for v in found:
                    k = st.index.get(v.sentence) if v.sentence else None
                    targets.update(DC.attribute(k, kept, doc) if k is not None and kept else kept)
            else:
                targets = kept
            for k in targets:
                verdicts[k] = DC.Verdict("reverted", "revert", codes)
                reasons[k] = list(found)
                texts[k] = st.base[k]
        text = AP.assemble(doc, texts)[0]
        found = F.check(source, text, document=document, spans=plan.protected) if text != source else []
    if found:
        floor_failed = VF.unique_codes(found)
    if dirty:
        final_shadow = st.verify(st.candidate(texts), allow)[2] if texts != st.src else []

    # 6. gate and report
    kept_edits = any(texts[k] != st.base[k] for k in range(n))
    retry_pending = any(v.status == "retry" for v in verdicts.values())
    gate = DC.chunk_gate(attempt, retry=retry_pending, runaway=runaway, unusable=unusable,
                         floor_failed=floor_failed, shadow=VF.unique_codes(final_shadow), kept_edits=kept_edits,
                         has_requests=bool(plan.requests))
    if gate.policy != "retry":                     # a retry only exists where the gate asks for one
        for k, verdict in verdicts.items():
            if verdict.status == "retry":
                verdicts[k] = DC.Verdict("rejected" if not reasons.get(k) else "reverted", "revert", verdict.codes)
    if gate.policy == "rollback" and not floor_failed and not to_source:
        # A rollback delivers base(x), the source plus the deterministic fixes, which verify clean by construction
        # (3.11): the chunk keeps its certain misspelling fixes. The reverts above already leave base(x); this
        # states it for every rollback reason (runaway, an unusable reply with nothing kept). Where the floor
        # ladder had to fall back to the source, base(x) failed the floor and the source stays.
        for k in range(n):
            if texts[k] != st.base[k]:
                verdicts[k] = DC.Verdict("reverted", "revert", verdicts[k].codes or list(gate.hard))
                texts[k] = st.base[k]
        text = AP.assemble(doc, texts)[0]
    report = _report(st, ar, rr, texts, verdicts, reasons, gate, attempt, nominated, previous)
    return CheckOutcome(text=text, report=report)


def _sentence_request(st: _State, k: int, nominated: Set[int]) -> Optional[str]:
    unit = st.doc.units[k]
    request = st.request_at.get(unit.id)
    if request is not None:
        return request.id
    return unit.id if k in nominated else None


def _keep_for(st: _State, v: Violation, k: int) -> Optional[str]:
    if v.keep:
        return v.keep[:DETAIL_MAX]
    if (v.family or "").startswith("voice") or v.code.startswith("voice_"):
        return st.plan.sentences[k].voice.final[:DETAIL_MAX] or None
    return None


def _report(st: _State, ar: AP.ApplyResult, rr: RP.RepairResult, texts: Sequence[str],
            verdicts: Dict[int, DC.Verdict], reasons: Dict[int, List[Violation]], gate: DC.Gate,
            attempt: int, nominated: Set[int], previous: Set[int]) -> CheckReport:
    plan, doc = st.plan, st.doc
    counts = empty_counts()
    sentences: List[SentenceVerdict] = []
    retry: List[RetryItem] = []
    fixes_by_sentence = PL.deterministic_by_sentence(plan)
    for k in range(st.n):
        unit = doc.units[k]
        verdict = verdicts[k]
        repairs: List[str] = []
        if verdict.status == "accepted":
            repairs = [r for r in rr.repairs.get(k, []) if is_code(r)]
            for key, value in rr.counts.get(k, {}).items():
                if key in counts:
                    counts[key] += value
        elif texts[k] == st.base[k] and st.base[k] != st.src[k]:
            repairs = ["norm_fix"]
            if plan.options.deterministic_fix == "all":
                counts["normFixes"] += len(fixes_by_sentence.get(unit.id, ()))
        status = verdict.status
        if status == "unchanged" and texts[k] != st.src[k]:
            status = "deterministic"
        codes = [c for c in dict.fromkeys(verdict.codes) if is_code(c)][:VF.MAX_CODES]
        if status in ("reverted", "rejected"):
            counts["revertedSentences"] += 1
            if "collateral_edit" in codes:
                counts["collateralReverts"] += 1
            families = sorted({v.family for v in reasons.get(k, []) if v.family})
            for family in families:
                counts["revertedByFamily"][family] = counts["revertedByFamily"].get(family, 0) + 1
            if "meaning" in families:
                counts["restoredSentences"] += 1
        request = _sentence_request(st, k, nominated)
        sentences.append(SentenceVerdict(id=unit.id, request=request, status=status, codes=codes,
                                         repairs=list(dict.fromkeys(repairs))[:VF.MAX_CODES]))
        if status == "retry" and request is not None:
            items: List[Violation] = []
            seen = set()
            for v in reasons.get(k, []) or [_violation(codes[0] if codes else "collateral_edit", unit.id)]:
                key = (v.code, v.detail)
                if key in seen or not is_code(v.code):
                    continue
                seen.add(key)
                items.append(Violation(code=v.code, family=v.family, severity=v.severity, sentence=unit.id,
                                       detail=(v.detail or "")[:DETAIL_MAX], keep=_keep_for(st, v, k)))
            if not items:
                items = [_violation(codes[0] if codes else "model_output_unusable", unit.id)]
            retry.append(RetryItem(id=request, sentence=unit.id, violations=items[:MAX_RETRY_VIOLATIONS]))
    status_counts = empty_request_status()
    supplied = set(ar.supplied) | previous
    for request in plan.requests:
        k = st.index[request.sentence]
        final = texts[k]
        if k not in supplied:
            status_counts["DECLINED"] += 1
        elif final == st.base[k]:
            if verdicts[k].status in ("unchanged", "deterministic"):
                status_counts["UNTOUCHED"] += 1
            else:
                status_counts["STILL_PRESENT"] += 1
        elif all(_request_fixed(rule, final, plan.options.genre) for rule in request.rules):
            status_counts["FIXED"] += 1
        else:
            status_counts["STILL_PRESENT"] += 1
    return CheckReport(gate={"exit_code": gate.exit_code}, hard_failures=gate.hard[:VF.MAX_CODES],
                       warning_reasons={"version": 1, "codes": ["P0_CHANGE_RATE"] if gate.runaway else []},
                       policy=gate.policy, shadow_failures=gate.shadow[:VF.MAX_CODES], attempt=attempt,
                       sentences=sentences, retry=retry if gate.policy == "retry" else [],
                       request_status=status_counts, counts=counts,
                       change_rate=round(VF.rate_of_texts(st.src, texts), 3))
