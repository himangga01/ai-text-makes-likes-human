"""Per-sentence decisions and the chunk gate of Super Sejong Engine v2 (DESIGN.md 3.9).

    decide_sentence(*, changed, licensed, rejection, enforced, attempt) -> Verdict
    chunk_gate(attempt, *, retry, runaway, unusable, floor_failed, shadow, kept_edits) -> Gate
    attribute(index, changed, doc) -> list[int]

Decision table for one source sentence s with candidate c(s), base(s) = source + deterministic fixes:

  situation                                          attempt 1                     attempt 2
  c(s) == base(s)                                    unchanged / deterministic     same
  changed, no request and not an open-review         reverted (collateral_edit)    reverted
    nomination
  replacement rejected in apply (retryable)          retry                         rejected
  replacement rejected (frozen unit, review limit)   rejected                      rejected
  changed, an enforced hard or soft code left after  retry                         reverted
    repair (3.7)
  clean (shadow-mode codes only)                     accepted                      accepted

A sentence that is reverted, rejected or sent to retry carries base(s) in the decided text, so the decided
chunk always verifies (invariant verify(x, base(x)) == []). A violation reported on a sentence that did
not change (a neighbour's edit caused it: a duplicate, an invented CTA attached to the nearest source
sentence) is charged to the changed sentences next to it (attribute()).

Chunk gate, mapped to the legacy contract (types.gate_policy):

  exit 0  accept: possibly with reverted sentences (the engine reports SEJONG_SENTENCES_REVERTED from
          counts.revertedSentences); at attempt 1 also with shadow-only findings, so they never cost a call
  exit 1  attempt 1: some sentence has status retry (policy retry, the targeted retry call);
          attempt 2: accepted with residual shadow-only findings (CHUNK_WARNING_ACCEPTED), or the retry
          reply was unusable while attempt-1 edits are kept
  exit 2  change_rate_runaway (attempt 1: retry every changed sentence once; attempt 2: rollback), an
          unusable reply (attempt 1: retry every request; attempt 2 with no attempt-1 edit left: rollback),
          or a floor failure that survives reverting every sentence to the source
  exit 3  execution error (the CLI, never this module)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Set, Tuple

from .types import Document, Violation, gate_policy


@dataclass
class Verdict:
    status: str                                  # types.SentenceStatus
    action: str                                  # keep | revert | retry
    codes: List[str] = field(default_factory=list)


def decide_sentence(*, changed: bool, deterministic: bool, licensed: bool,
                    rejection: Optional[Tuple[str, str, bool]], enforced: Sequence[Violation],
                    attempt: int) -> Verdict:
    """One row of the decision table above."""
    if rejection is not None:
        code, _detail, retryable = rejection
        if retryable and attempt == 1:
            return Verdict("retry", "retry", [code])
        return Verdict("rejected", "revert", [code])
    if not changed:
        return Verdict("deterministic" if deterministic else "unchanged", "keep")
    if not licensed:
        return Verdict("reverted", "revert", ["collateral_edit"])
    if enforced:
        codes = list(dict.fromkeys(v.code for v in enforced))
        return Verdict("retry", "retry", codes) if attempt == 1 else Verdict("reverted", "revert", codes)
    return Verdict("accepted", "keep")


def attribute(index: int, changed: Set[int], doc: Document) -> List[int]:
    """Changed sentences a violation on unchanged sentence `index` is charged to: the changed sentences
    within two positions in the same paragraph, else every changed sentence of that paragraph, else every
    changed sentence of the chunk."""
    if index in changed:
        return [index]
    para = doc.units[index].para
    near = [k for k in changed if abs(k - index) <= 2 and doc.units[k].para == para]
    if near:
        return sorted(near)
    same = [k for k in changed if doc.units[k].para == para]
    return sorted(same) if same else sorted(changed)


@dataclass
class Gate:
    exit_code: int
    policy: str
    hard: List[str]
    shadow: List[str]
    runaway: bool


def chunk_gate(attempt: int, *, retry: bool, runaway: bool, unusable: bool, floor_failed: Sequence[str],
               shadow: Sequence[str], kept_edits: bool, has_requests: bool) -> Gate:
    """Exit code, policy and the gate code lists of one check (see the module docstring)."""
    hard: List[str] = []
    shadow = list(shadow)
    if floor_failed:
        hard.extend(floor_failed)
        code = 2
    elif runaway:
        hard.append("change_rate_runaway")
        code = 2
    elif unusable:
        if attempt == 1 and has_requests:
            hard.append("model_output_unusable")
            code = 2
        elif attempt == 2 and not kept_edits:
            hard.append("model_output_unusable")
            code = 2
        else:
            shadow.insert(0, "model_output_unusable")
            code = 1 if attempt == 2 else 0
    elif attempt == 1:
        code = 1 if retry else 0
    else:
        code = 1 if shadow else 0
    shadow = list(dict.fromkeys(shadow))
    return Gate(exit_code=code, policy=gate_policy(code, attempt), hard=list(dict.fromkeys(hard)),
                shadow=shadow, runaway=runaway)
