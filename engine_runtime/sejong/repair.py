"""Deterministic repair of a candidate, per source sentence, in the order of DESIGN.md 3.7.

    repair_candidate(plan, doc, texts, edited, *, flags=None) -> RepairResult

Only sentences the writer changed (`edited`) are repaired; every other sentence is base(s) or an earlier
decision and is left alone. For one edited sentence, against its SOURCE sentence:

  1. norm fixes   norms.fix_text on the candidate sentence: every FIX/deterministic rule (N01, N02, N04,
                  CTA-SP1/SP2; the 할께 family only with SUPER_SEJONG_FIX_COLLOQUIAL=1), outside protected
                  spans; skipped when SUPER_SEJONG_DETERMINISTIC_FIX=off. norms is the single owner of
                  the CTA spacing fix, so cta.safe_repair is not called here
  2+3. voice      voice_gate.compare_texts, then voice_repair.repair_pair: keep-token restore (a CMC token
                  or discourse marker the writer deleted is put back), then graft of the writer's own final
                  eojeol. When repair_pair returns its revert marker the candidate is left unrepaired: the
                  verify step reports the violation and the decide step retries or reverts the sentence
                  (DESIGN 3.9), so a revert is never decided here. Skipped when the voice family is off
  4. josa         super_sejong_josa.gate at "likely" (only mismatches the rewrite introduced) and repair
  5. commas       commas.strip_injected_report(restore_dropped=True): injected connective commas removed
                  down to the source count, the writer's own commas never removed and a deleted one put
                  back (OD 8, WP-9)

Every step is idempotent on its own output, so repairing a repaired sentence changes nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set

from . import commas as K
from . import config as C
from . import josa as J
from . import norms as N
from . import voice_gate as VG
from . import voice_repair as VR
from .types import Document, Plan

COUNT_KEYS = ("normFixes", "voiceGrafts", "cmcRestored", "repairedParticles", "removedCommas", "restoredCommas")


@dataclass
class RepairResult:
    texts: List[str]
    repairs: Dict[int, List[str]] = field(default_factory=dict)     # sentence index -> action codes
    counts: Dict[int, Dict[str, int]] = field(default_factory=dict)  # sentence index -> COUNT_KEYS


def repair_sentence(plan: Plan, src_text: str, kind: str, text: str, unit, *,
                    flags: C.Flags) -> (str, List[str], Dict[str, int]):
    """Repair one edited sentence; returns (text, actions, counts)."""
    actions: List[str] = []
    counts = {key: 0 for key in COUNT_KEYS}
    options = plan.options
    if options.deterministic_fix != "off":
        fixed, applied = N.fix_text(text, genre=options.genre, fix_colloquial=options.fix_colloquial)
        if applied and fixed != text:
            text = fixed
            actions.append("norm_fix")
            counts["normFixes"] = len(applied)
    if text != src_text and C.family_mode(flags, "voice") != "off":
        violations = VG.blocking(VG.compare_texts(src_text, text, kind=kind, fix_colloquial=options.fix_colloquial))
        if violations:
            repaired, done = VR.repair_pair(unit, text, violations, fix_colloquial=options.fix_colloquial)
            if VR.REVERT not in done and repaired != text:
                text = repaired
                for action in done:
                    actions.append(action)
                    if action == VR.GRAFT:
                        counts["voiceGrafts"] += 1
                    elif action == VR.RESTORE:
                        counts["cmcRestored"] += 1
    if text != src_text:
        particles = J.gate(src_text, text, None, "likely")
        if particles:
            text = J.repair(text, particles)
            actions.append("josa_repair")
            counts["repairedParticles"] = len(particles)
    if text != src_text:
        text, report = K.strip_injected_report(src_text, text, restore_dropped=True)
        if report["commas_removed"]:
            actions.append("comma_strip")
            counts["removedCommas"] = report["commas_removed"]
        if report["commas_restored"]:
            actions.append("comma_restore")
            counts["restoredCommas"] = report["commas_restored"]
    return text, actions, counts


def repair_candidate(plan: Plan, doc: Document, texts: Sequence[str], edited: Set[int], *,
                     flags: Optional[C.Flags] = None) -> RepairResult:
    """Repair every edited sentence of a candidate (3.7). `doc` is the source chunk (plan.source_document)."""
    flags = flags if flags is not None else C.Flags.from_env()
    result = RepairResult(texts=list(texts))
    for index in sorted(edited):
        unit = doc.units[index]
        text, actions, counts = repair_sentence(plan, unit.text, unit.kind, texts[index], unit, flags=flags)
        result.texts[index] = text
        if actions:
            result.repairs[index] = actions
        result.counts[index] = counts
    return result
