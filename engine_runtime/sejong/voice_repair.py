"""Deterministic voice repair of Super Sejong Engine v2 (DESIGN.md 3.7 steps 2-3).

    repair_pair(src_unit, out_text, violations, *, fix_colloquial=False) -> (text, actions)
    repair(src, out, pairs=None, *, fix_colloquial=False) -> (text, actions)
    graft(src_text, out_text) -> Optional[str]
    restore_keep_tokens(src_text, out_text, *, fix_colloquial=False) -> Optional[str]

Port of docs/research/super-sejong/v2/prototypes/T2_repair.py. For one aligned sentence, in order:

  1. keep-token restore (voice_emoticon_dropped, voice_discourse_dropped): a CMC token or a
     sentence-initial discourse marker of the source that the rewrite deleted is put back at the
     corresponding place: after the same left context, or at the end (T2 restore_emoticons), or at
     the start for 사실/뭐. Only deletions are restored; a substitution (진짜 -> 정말, 걍 -> 그냥)
     is left to step 3.
  2. graft (voice_level, voice_hon_si_*, voice_stance, voice_colloquial_changed): the writer's own
     final eojeol and final punctuation replace the rewritten ones when both final eojeols have
     the same lemma key (ending syllables stripped, 해/했/합 -> 하, 돼/됐 -> 되 ...). Never for a
     mood change, a quotation (voice_quote_level, or a sentence that is or ends in a quotation) or
     a NOMINAL/NONE sentence on either side. Grafting copies the writer's own form, so it cannot
     invent a conjugation [T2 §4].
  3. anything still violated (hard or soft): the source sentence is returned with the action
     "voice_revert" (the revert marker the decide step acts on). A split or merge group that is
     violated is reverted as a whole.

Actions (lowercase codes for SentenceVerdict.repairs): voice_graft, cmc_restore, voice_revert.
The repair is idempotent: repairing a repaired text against the same source changes nothing,
because a repaired sentence has no voice violation left.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from . import align as A
from . import protect
from . import text as T
from . import voice as V
from . import voice_gate as G
from .types import Document, Unit, Violation

GRAFT, RESTORE, REVERT = "voice_graft", "cmc_restore", "voice_revert"
GRAFTABLE = ("voice_level", "voice_hon_si_dropped", "voice_hon_si_added", "voice_stance", "voice_colloquial_changed")
NO_GRAFT = ("voice_mood", "voice_quote_level")
RESTORABLE = ("voice_emoticon_dropped", "voice_discourse_dropped")

# Ending syllables stripped before two final eojeols are compared, and contractions folded to the
# stem syllable (T2 repair.END_SYL, CONTR).
_END_SYL = frozenset("니다요어아여세십시오까죠지습읍입군네구나거든잖더라고게께걸래대야당징용엉얌앙")
_CONTR = {"해": "하", "합": "하", "했": "하", "할": "하", "한": "하", "돼": "되", "됩": "되", "됐": "되", "될": "되",
          "된": "되", "려": "리", "혀": "히", "쳐": "치", "셔": "시", "워": "우", "와": "오", "봐": "보", "줘": "주",
          "꿔": "꾸", "써": "쓰", "겨": "기", "져": "지", "펴": "피", "켜": "키"}
_PERIOD_END = re.compile(r"[.。]\s*$")
_LEFT_CONTEXT = 8              # characters of left context used to place a deleted keep token


def _drop_b(ch: str) -> str:
    """걸립 -> 걸리: remove the ㅂ coda of an -ㅂ니다 syllable."""
    if V.is_hangul(ch) and V.jong(ch) == 17:
        return chr(ord(ch) - 17)
    return ch


def lemma_key(word: str) -> str:
    w = word
    while len(w) > 1 and w[-1] in _END_SYL:
        w = w[:-1]
    if not w:
        return ""
    return w[:-1] + _CONTR.get(w[-1], _drop_b(w[-1]))


# --------------------------------------------------------------------------
# graft
# --------------------------------------------------------------------------
def graft(src_text: str, out_text: str) -> Optional[str]:
    """out_text with its final eojeol and final punctuation replaced by the source's, or None
    when the lemma keys differ or either sentence is (or ends in) a quotation."""
    if V.whole_quote(src_text) is not None or V.whole_quote(out_text) is not None:
        return None
    ws, ts = V.final_eojeol(src_text)
    wo, to = V.final_eojeol(out_text)
    if not ws or not wo or V.QUOTE_TOKEN in (ws, wo):
        return None
    if ws == wo and ts.strip() == to.strip():
        return None
    if lemma_key(ws) != lemma_key(wo) or not lemma_key(ws):
        return None
    body = out_text.rstrip()
    trailing = out_text[len(body):]
    if not body.endswith(to):
        return None
    end = len(body) - len(to)
    start = end - len(wo)
    if start < 0 or body[start:end] != wo or not src_text.rstrip().endswith(ts):
        return None
    return body[:start] + ws + ts + trailing


# --------------------------------------------------------------------------
# keep-token restore
# --------------------------------------------------------------------------
def _keep_spans(sentence: str, fix_colloquial: bool) -> List[Tuple[int, int, str, str]]:
    """(start, end, kind, token) of the keep-token spans of one sentence."""
    doc = T.segment(sentence)
    out = []
    for span in protect.protected_spans(doc, fix_colloquial=fix_colloquial):
        if span.policy == protect.KEEP:
            out.append((span.start, span.end, span.kind, sentence[span.start:span.end]))
    return out


def restore_keep_tokens(src_text: str, out_text: str, *, fix_colloquial: bool = False) -> Optional[str]:
    """Put back CMC tokens and sentence-initial discourse markers that the rewrite deleted, or
    None when nothing could be restored. Only tokens missing from out_text are considered."""
    result = out_text
    changed = False
    for start, end, kind, token in reversed(_keep_spans(src_text, fix_colloquial)):
        if kind == "colloquial":
            continue                                     # substitutions are not restored
        if src_text.count(token) <= result.count(token):
            continue
        before = src_text[:start]
        after = src_text[end:]
        if kind == "discourse":
            if before.strip(" \t\"“‘'("):
                continue
            gap = re.match(r"[,\s]*", after).group(0) or " "
            lead = len(result) - len(result.lstrip())
            following = after[len(gap):].split()
            if not following or not result[lead:].startswith(following[0]):
                continue                                 # not a pure deletion (진짜 -> 정말)
            result = result[:lead] + token + gap + result[lead:]
            changed = True
            continue
        if not after.strip() or not V._TRAIL.sub("", after).strip():
            # trailing token: the rewrite's final period gives way to it (T2 restore_emoticons)
            body = _PERIOD_END.sub("", result.rstrip())
            space = before[len(before.rstrip()):]
            result = body + space + token + after.rstrip()
            changed = True
            continue
        context = before.rstrip()[-_LEFT_CONTEXT:]
        if context and result.count(context) == 1:
            at = result.index(context) + len(context)
            space = before[len(before.rstrip()):]
            tail = result[at:]
            if tail[:1] in ".。" and not after[:1] in ".。":
                tail = tail[1:]
            result = result[:at] + space + token + tail
            changed = True
    return result if changed else None


# --------------------------------------------------------------------------
# one aligned sentence
# --------------------------------------------------------------------------
def _codes(violations: Sequence[Violation]) -> set:
    return {v.code for v in violations if v.severity in ("hard", "soft") and v.code.startswith("voice_")}


def _residual(src_text: str, kind: str, out_text: str, fix_colloquial: bool) -> List[Violation]:
    return G.blocking(G.compare_texts(src_text, out_text, kind=kind, fix_colloquial=fix_colloquial))


def repair_pair(src_unit: Unit, out_text: str, violations: Sequence[Violation], *,
                fix_colloquial: bool = False) -> Tuple[str, List[str]]:
    """Repair one aligned sentence (DESIGN 3.7 steps 2-3). Returns the repaired text and the
    actions taken; with "voice_revert" the text is the source sentence (the revert marker).
    out_text may hold several sentences (a split); a violated split is reverted."""
    codes = _codes(violations)
    if not codes:
        return out_text, []
    src_text = src_unit.text
    if len(T.segment(out_text).units) > 1:
        return src_text, [REVERT]
    actions: List[str] = []
    text = out_text
    if codes & set(RESTORABLE):
        restored = restore_keep_tokens(src_text, text, fix_colloquial=fix_colloquial)
        if restored is not None:
            text = restored
            actions.append(RESTORE)
    if codes & set(GRAFTABLE) and not codes & set(NO_GRAFT):
        a = V.features(src_text, src_unit.kind).sig.level
        b = V.features(text, src_unit.kind).sig.level
        if a in V.FINITE and b in V.FINITE:
            grafted = graft(src_text, text)
            if grafted is not None:
                text = grafted
                actions.append(GRAFT)
    if text == src_text:
        return text, actions
    if _residual(src_text, src_unit.kind, text, fix_colloquial):
        return src_text, [REVERT]
    return text, actions


# --------------------------------------------------------------------------
# whole candidate
# --------------------------------------------------------------------------
def repair(src: Document, out: Document, pairs: Optional[Sequence[A.Pair]] = None, *,
           fix_colloquial: bool = False) -> Tuple[str, List[Tuple[str, str]]]:
    """Repair every violated aligned group of a candidate and return the new candidate text and
    the actions as (source sentence id, action). Unviolated text is kept byte for byte; a
    replaced group keeps the whitespace around it."""
    if pairs is None:
        pairs = A.align_documents(src, out)
    by_pair: Dict[int, List[Violation]] = {}
    for index, violation in G.check_pairs(src, out, pairs, fix_colloquial=fix_colloquial):
        by_pair.setdefault(index, []).append(violation)
    edits: List[Tuple[int, int, str]] = []          # (start, end, replacement) in out.text
    actions: List[Tuple[str, str]] = []
    for index, found in sorted(by_pair.items()):
        if not G.blocking(found):
            continue
        pair = pairs[index]
        if not pair.src or not pair.out:
            continue                                # inserted sentence: the flow/decide steps own it
        units_s = [src.units[i] for i in pair.src]
        units_o = [out.units[j] for j in pair.out]
        start, end = units_o[0].start, units_o[-1].end
        sid = units_s[-1].id
        if len(units_s) == 1:
            text, done = repair_pair(units_s[0], out.text[start:end], found, fix_colloquial=fix_colloquial)
        else:
            text, done = src.text[units_s[0].start:units_s[-1].end], [REVERT]
        if text != out.text[start:end]:
            edits.append((start, end, text))
        actions.extend((sid, action) for action in done)
    if not edits:
        return out.text, actions
    pieces, last = [], 0
    for start, end, text in edits:
        pieces.append(out.text[last:start])
        pieces.append(text)
        last = end
    pieces.append(out.text[last:])
    return "".join(pieces), actions
