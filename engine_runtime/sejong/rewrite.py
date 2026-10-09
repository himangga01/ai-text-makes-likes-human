"""Rewrite mode of Super Sejong Engine v2: strength `rewrite`, 매우 강하게(다시쓰기) (WP-19).

    paragraphs_of(doc, spans)                 -> list[Para]            source paragraphs and their units
    dominant_level(levels)                    -> str                   the paragraph voice rule
    plan_paragraphs(doc, spans)               -> list[PlanParagraph]   plan.paragraphs of a rewrite plan
    violations(src, out, paras, *, ...)       -> list[Violation]       every family, per paragraph pair
    check(plan, source, *, response=None, candidate=None, attempt=1, base=None, document=None, flags=None)
                                              -> check.CheckOutcome
    document_violations(before, after, *, context=None, flags=None, genre="general") -> (violations, rate)
    floor_violations(before, after, *, context=None) -> list[Violation]   the floor of a whole text (finalize)

The four other strengths send single sentences to the writer and decide every sentence on its own (check.py). At
`rewrite` the owner wants broad rewriting (decision 2026-10-08): the writer rewrites the whole chunk paragraph by
paragraph (restructure, merge or split sentences inside a paragraph, reorder clauses) and this module decides every
PARAGRAPH on its own. Paragraphs are the blank-line paragraphs of text.segment; the paragraph count and order are the
contract, so source paragraph k is compared with output paragraph k and nothing else.

Reply (prompt.ts buildRewritePrompt). Attempt 1: rewrittenText = the whole chunk, replacements empty; a blank reply
means "nothing to change". Attempt 2 (the retry): replacements with paragraph ids P1.. (the failed paragraphs only),
each text = the whole paragraph, rewrittenText empty. Whole-reply rejection (MODEL_OUTPUT_UNUSABLE): the response
schema fails; attempt 1 uses replacements, or attempt 2 uses rewrittenText; an id is not a paragraph id of the plan
or is named twice; the full text has another paragraph count than the source. The CLI's --candidate (and the skill
gateway's legacy-shape reply) is a full text at either attempt. Per paragraph (retryable): a paragraph text with a
blank line (paragraph_split) or another number of lines than the source paragraph (paragraph_lines_changed); a
paragraph the plan marks as not editable (headings, wholly frozen text) that changed is a collateral edit.

Verification of one paragraph pair (source paragraph k against output paragraph k, sentences aligned inside the pair
with align.align; every family keeps its strictness except where the owner allowed the rewrite):

  floor     floor.check_pair on the paragraph pair (numbers, dates, weekdays, quotes, names, headings, footnotes,
            protected spans, josa at "certain"); sentence_dropped for a source sentence most of whose content words
            vanish from the whole output paragraph (dropped_sentences: floor.dropped_units reads a merge as a drop);
            floor.text_codes on the whole chunk at the end                         always enforced
  meaning   meaning.compare on the whole paragraph pair (polarity, modality, lexical polarity, roles, aspect, partial
            negation, temporal order, conditions, key words), plus the same guards per aligned group inside the pair
            for every code but the word drops (key_word_dropped, content_dropped, condition_dropped): a paragraph
            count can balance a negation removed in one sentence against one added in the next, while a word may
            legitimately move to another sentence of the paragraph. A conditional clause whose words vanish from the
            whole paragraph is condition_dropped even when the rewrite added another condition (dropped_conditions)
  voice     the paragraph rule (below) instead of the per-sentence level/mood/stance lock
  cta       cta_gate.compare on the paragraph-paired alignment (force, polarity, actions, condition, deadline,
            channel, benefit, invented CTAs: all unchanged)
  flow      flow.check on the same alignment, minus flow_transition_added and flow_sentence_added (a rewrite may add a
            connective or a sentence); flow_contrast_changed counted per paragraph instead of per pair (a contrast
            marker may move to the next sentence, but a lost one changes meaning); flow_order_changed only for a
            sentence that moved to another paragraph; duplicates, seam codes and context leaks unchanged
  clarity   clarity.check (shadow by default, as in the other strengths) minus clarity_longer_sentence: merging
            sentences inside a paragraph is allowed, and the paragraph length ratio bounds the result
  norms     norms.introduced on the paragraph pair (norm_introduced hard, tell_introduced soft)
  length    paragraph_length_ratio (family runaway, always enforced): stripped output/source length outside
            [RATIO_MIN, RATIO_MAX]. Replaces the chunk-level change-rate runaway guard, which a rewrite trips by design

Paragraph voice rule (owner decision): the paragraph's dominant level is the most frequent finite level of its source
sentences; a tie goes to the tied level used last (the level of the paragraph's last finite sentence when that
sentence is one of the tied). No finite sentence: NOMINAL when some sentence is nominal, else NONE. Then, per pair:
  voice_level       an output finite sentence at another level than the dominant one, or a nominal sentence more
                    than the source paragraph had (detail "HAPSYO->HAEYO"). Two exceptions: an output sentence that
                    ends exactly as one of the paragraph's own source sentences (or their base forms) does, same level
                    and same final eojeol, keeps that ending (the owner allows normalising to the dominant level, so
                    keeping a sentence's own ending is not drift; it also keeps verify(x, base(x)) clean and absorbs a
                    level the classifier reads the same wrong way on both sides); and in a paragraph that already uses
                    해체, 해체 and 해라체 count as one 반말 level (먹자, 맛있더라 inside casual speech)
  voice_mood        the number of questions, requests (imperative or 바랍니다-type) or proposals changed (detail
                    "questions:1->0")
  voice_hon_si_dropped/added, voice_humble_dropped, voice_hon_noun_changed, voice_persona_dropped/swap/added:
                    presence per paragraph (-시-, 드리다-type humble forms, 고객님-type address, 저/저희 vs 나/우리)
  voice_emoticon_*, voice_colloquial_*, voice_discourse_dropped, voice_written_upshift: the keep-token multiset
                    and the up-shift count per paragraph (voice_gate's group comparison on the whole paragraph); the
                    up-shift (했 -> 하였, 되어) only in a 해요체 or 해체 paragraph, as 합쇼체 and 해라체 prose write it

Decision per paragraph (decide.decide_sentence on the paragraph): unchanged / deterministic, accepted, or an enforced
violation -> retry once with the named violations (attempt 1), then the paragraph goes back to base(x) = its source
plus the deterministic fixes. A paragraph longer than RETRY_MAX_CHARS is reverted at once (its whole text would not
fit one reply item of the response schema). A violation on an unchanged paragraph (an invented CTA attached to the
nearest source sentence, a duplicate of the neighbour) is charged to the changed paragraphs next to it. The whole
chunk is never reverted for one paragraph; the chunk floor ladder (changed paragraphs, then the source) only runs
when a chunk-level floor code survives every paragraph decision.

Report: the CheckReport of check.py. Every sentence carries its paragraph's status and codes and the paragraph id
(P…) as its request; the retry list has one entry per failed paragraph (id P…, sentence = its first sentence).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from . import align as A
from . import clarity as CL
from . import config as C
from . import cta_gate as CG
from . import decide as DC
from . import diagnose as D
from . import floor as F
from . import flow as FL
from . import io as IO
from . import josa as J
from . import meaning as M
from . import norms as N
from . import protect as P
from . import text as T
from . import voice as V
from . import voice_gate as VG
from .types import (CheckReport, Document, Plan, PlanParagraph, RetryItem, SentenceVerdict, Span, Violation,
                    empty_counts, empty_request_status, is_code)

# Paragraph length ratio (stripped output / stripped source). Measured on constructed good rewrites and the seed gold
# texts (WP-19 report): good rewrites of the owner's genre stay inside it, a dropped half or a padded paragraph not.
RATIO_MIN, RATIO_MAX = 0.5, 1.8
# Longest source paragraph that gets a retry: its rewrite must fit one replacement text (response schema maxLength
# 4000) even at RATIO_MAX.
RETRY_MAX_CHARS = 2200
# A source sentence counts as dropped when more than DROP_SHARE of its content words (at least DROP_MIN_WORDS) are
# gone from the whole output paragraph.
DROP_MIN_WORDS, DROP_SHARE = 3, 0.6
MAX_ROUNDS = 3
MAX_RETRY_VIOLATIONS = 40
DETAIL_MAX = 200
REQUEST_CLASSES = ("questions", "requests", "proposals")
# Flow codes a rewrite may produce on purpose (owner decision: connectives and sentences may be added).
FLOW_ALLOWED = ("flow_transition_added", "flow_sentence_added")
# A merge inside a paragraph makes a longer sentence by design (26 of the 38 good constructed rewrites would report
# it); the paragraph length ratio bounds the paragraph instead.
CLARITY_ALLOWED = ("clarity_longer_sentence",)
# voice_gate group codes that stay per paragraph as they are (keep tokens, colloquial forms, up-shift).
KEEP_CODES = ("voice_emoticon_dropped", "voice_emoticon_added", "voice_colloquial_changed", "voice_discourse_dropped",
              "voice_colloquial_added", "voice_written_upshift")
SPOKEN_LEVELS = ("HAEYO", "HAE")
# Meaning codes compared on the whole paragraph only (the words may move to another sentence of the paragraph).
PARAGRAPH_ONLY_MEANING = ("key_word_dropped", "content_dropped", "condition_dropped")
POLARITY_RULES = ("SSJ-A06",)
LICENSED_BY_POLARITY_RULES = ("polarity_changed", "modality_changed", "lexical_polarity_changed")


# --------------------------------------------------------------------------
# paragraphs
# --------------------------------------------------------------------------
@dataclass
class Para:
    index: int                    # Document.paragraphs index
    id: str                       # P1, P2, ...
    start: int
    end: int
    units: List[int]              # unit indices, in order
    editable: bool


def paragraphs_of(doc: Document, spans: Sequence[Span]) -> List[Para]:
    """Every paragraph of the document with its units. A paragraph is editable when no unit is a heading and some unit
    has something the writer may change (plan.nominable: an editable kind, Hangul, not wholly frozen)."""
    from .plan import nominable                     # late: plan imports this module
    members: Dict[int, List[int]] = {}
    for index, unit in enumerate(doc.units):
        members.setdefault(unit.para, []).append(index)
    out: List[Para] = []
    for k, (start, end) in enumerate(doc.paragraphs):
        units = members.get(k, [])
        editable = bool(units) and all(doc.units[i].kind != "heading" for i in units) \
            and any(nominable(doc.units[i], spans) for i in units)
        out.append(Para(index=k, id=f"P{k + 1}", start=start, end=end, units=units, editable=editable))
    return out


def dominant_level(levels: Sequence[str]) -> str:
    """The paragraph's dominant level (module docstring): most frequent finite level, ties to the one used last."""
    finite = [level for level in levels if level in V.FINITE]
    if not finite:
        return V.NOMINAL if V.NOMINAL in levels else V.NONE
    counts = Counter(finite)
    top = max(counts.values())
    return next(level for level in reversed(finite) if counts[level] == top)


def request_classes(features: Sequence[V.Features]) -> Dict[str, int]:
    """Questions, requests (imperative, or a declarative 바랍니다/부탁드립니다 request) and proposals of a paragraph."""
    counts = dict.fromkeys(REQUEST_CLASSES, 0)
    for f in features:
        mood, finite = f.sig.mood, f.sig.level in V.FINITE
        if (finite and mood == "INTERR") or (not finite and f.question):
            counts["questions"] += 1
        elif finite and (mood == "IMPER" or (mood == "DECL" and f.directive)):
            counts["requests"] += 1
        elif finite and mood == "PROPOS":
            counts["proposals"] += 1
    return counts


def _first_persons(features: Sequence[V.Features]) -> Set[str]:
    return {p for f in features for p in f.sig.persona} & set(V.FIRST_PERSONS)


def _features(doc: Document, indices: Sequence[int]) -> List[V.Features]:
    return [V.features(doc.units[i].text, doc.units[i].kind) for i in indices]


def plan_paragraphs(doc: Document, spans: Sequence[Span]) -> List[PlanParagraph]:
    out: List[PlanParagraph] = []
    u16 = T.Utf16Index(doc.text)
    for para in paragraphs_of(doc, spans):
        fs = _features(doc, para.units)
        classes = request_classes(fs)
        units = [doc.units[i] for i in para.units]
        out.append(PlanParagraph(
            id=para.id, para=para.index, start=para.start, end=para.end,
            start_u16=u16(para.start), end_u16=u16(para.end),
            sentences=[u.id for u in units], editable=para.editable,
            level=dominant_level([f.sig.level for f in fs]),
            hon_si=sum(f.sig.si_count for f in fs) > 0, humble=sum(f.humble_count for f in fs) > 0,
            persona=sorted(_first_persons(fs)), questions=classes["questions"], requests=classes["requests"],
            proposals=classes["proposals"]))
    return out


# --------------------------------------------------------------------------
# candidate: one text per source paragraph
# --------------------------------------------------------------------------
def gaps(doc: Document) -> List[str]:
    """Source text before, between and after the paragraphs (len(paragraphs) + 1 pieces)."""
    out, last = [], 0
    for start, end in doc.paragraphs:
        out.append(doc.text[last:start])
        last = end
    out.append(doc.text[last:])
    return out


def assemble(doc: Document, texts: Sequence[str]) -> str:
    between = gaps(doc)
    pieces: List[str] = []
    for gap, piece in zip(between, texts):
        pieces.append(gap)
        pieces.append(piece)
    pieces.append(between[-1])
    return "".join(pieces)


def _edges(text: str) -> Tuple[str, str]:
    core = text.strip()
    if not core:
        return text, ""
    head = text[:len(text) - len(text.lstrip())]
    return head, text[len(text.rstrip()):]


def _fit(source_paragraph: str, text: str) -> str:
    """The writer's paragraph with the source paragraph's leading and trailing whitespace (indentation is layout)."""
    head, tail = _edges(source_paragraph)
    return head + text.strip() + tail


def _lines(text: str) -> int:
    return len(text.strip().split("\n"))


def paragraph_pairs(src: Document, out: Document, paras: Sequence[Para]) -> List[List[A.Pair]]:
    """Sentence alignment inside every paragraph pair (indices of the whole documents). Needs equal paragraph counts."""
    out_members: Dict[int, List[int]] = {}
    for index, unit in enumerate(out.units):
        out_members.setdefault(unit.para, []).append(index)
    result: List[List[A.Pair]] = []
    for para in paras:
        si, oi = para.units, out_members.get(para.index, [])
        local = A.align([src.units[i].text for i in si], [out.units[j].text for j in oi])
        result.append([A.Pair(tuple(si[i] for i in p.src), tuple(oi[j] for j in p.out), p.score) for p in local])
    return result


def _out_members(out: Document) -> Dict[int, List[int]]:
    members: Dict[int, List[int]] = {}
    for index, unit in enumerate(out.units):
        members.setdefault(unit.para, []).append(index)
    return members


def _paragraph_text(doc: Document, index: int) -> str:
    start, end = doc.paragraphs[index]
    return doc.text[start:end]


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------
def _v(code: str, family: str, severity: str, sentence: Optional[str], detail: str = "",
       keep: Optional[str] = None) -> Violation:
    return Violation(code=code, family=family, severity=severity, sentence=sentence, detail=detail[:DETAIL_MAX],
                     keep=keep[:DETAIL_MAX] if keep else None)


def _ending(f: V.Features) -> str:
    """The final eojeol without trailing punctuation, marks and spaces (멋졌어요. / 멋졌어요! -> 멋졌어요)."""
    final = f.sig.final
    end = len(final)
    while end and not ("가" <= final[end - 1] <= "힣" or final[end - 1].isalnum()):
        end -= 1
    return final[:end]


def voice_violations(fs: Sequence[V.Features], fo: Sequence[V.Features], kept: Sequence[V.Features],
                     sid: Optional[str], *, fix_colloquial: bool = False) -> List[Violation]:
    """The paragraph voice rule (module docstring) for one paragraph pair: `fs` and `fo` are the features of the source
    and output sentences, `kept` those of the paragraph's source sentences and their base forms, whose own endings an
    output sentence may keep."""
    found: List[Violation] = []
    casual = any(f.sig.level == V.HAE for f in fs)

    def level_of(f: V.Features) -> str:
        # 반말: a paragraph that already uses 해체 mixes it with the 해라체 forms of casual speech (먹자, 맛있더라,
        # 가니?) on its own, so the two count as one level there; a pure 해라체 paragraph (written -다 prose) keeps
        # 해체 out, and 존댓말 levels are never merged (the owner's case: 합쇼체 paragraph, 해요체 CTA normalised).
        return V.HAE if casual and f.sig.level == V.HAERA else f.sig.level

    dominant = dominant_level([level_of(f) for f in fs])
    endings = {(level_of(f), _ending(f)) for f in kept}
    nominal_src = sum(1 for f in fs if f.sig.level == V.NOMINAL)
    nominal_out = 0
    for f in fo:
        level = level_of(f)
        if (level, _ending(f)) in endings:
            continue                       # ends exactly as one of the paragraph's own source sentences
        if level == V.NOMINAL:
            nominal_out += 1
            if dominant in V.FINITE and nominal_out > nominal_src:
                found.append(_v("voice_level", "voice", "hard", sid, f"{dominant}->{level}"))
                break
        elif level in V.FINITE and level != dominant:
            found.append(_v("voice_level", "voice", "hard", sid, f"{dominant}->{level}"))
            break
    before, after = request_classes(fs), request_classes(fo)
    for name in REQUEST_CLASSES:
        if before[name] != after[name]:
            found.append(_v("voice_mood", "voice", "hard", sid, f"{name}:{before[name]}->{after[name]}"))
    si_src, si_out = sum(f.sig.si_count for f in fs), sum(f.sig.si_count for f in fo)
    if si_src and not si_out:
        found.append(_v("voice_hon_si_dropped", "voice", "hard", sid, "paragraph"))
    elif si_out and not si_src:
        found.append(_v("voice_hon_si_added", "voice", "hard", sid, "paragraph"))
    if sum(f.humble_count for f in fs) and not sum(f.humble_count for f in fo):
        found.append(_v("voice_humble_dropped", "voice", "soft", sid, "paragraph"))
    if sum(f.hon_nouns for f in fs) and not sum(f.hon_nouns for f in fo):
        found.append(_v("voice_hon_noun_changed", "voice", "soft", sid, "paragraph"))
    ps, po = _first_persons(fs), _first_persons(fo)
    if ps and not po:
        found.append(_v("voice_persona_dropped", "voice", "soft", sid, "+".join(sorted(ps))))
    elif po - ps:
        code = "voice_persona_swap" if ps else "voice_persona_added"
        found.append(_v(code, "voice", "soft", sid, f"{'+'.join(sorted(ps))}->{'+'.join(sorted(po))}"))
    # Keep tokens, colloquial forms and the written up-shift: voice_gate's group comparison of the whole paragraph
    # (its -시-, persona, humble and address checks are replaced by the presence checks above).
    marked = [_v("voice_hon_si_dropped", "voice", "hard", sid)]          # silences its -시- count comparison
    for v in VG._compare_group(fs, fo, sid, marked, fix_colloquial):
        # 하였/되어 forms are the written register of 합쇼체 and 해라체 prose: an up-shift only in a spoken paragraph.
        if v.code in KEEP_CODES and (v.code != "voice_written_upshift" or dominant in SPOKEN_LEVELS):
            found.append(v)
    return found


def _content_words(text: str) -> int:
    """Content words of a sentence as meaning.drops reads them (quotations masked, idioms blanked)."""
    masked = M._blank_idioms(T.mask_quotes(text))
    return sum(1 for m in M._HANGUL_RUN.finditer(masked) if M._readings(m.group(0)) is not None)


def dropped_sentences(units: Sequence, out_text: str) -> List:
    """Source sentences of a paragraph whose content did not survive anywhere in the rewritten paragraph: of at least
    DROP_MIN_WORDS content words, more than DROP_SHARE have no trace in the whole output paragraph (meaning.drops,
    which reads inflection, particles and spacing as the same word). Replaces floor.dropped_units, whose bigram
    cover against the aligned neighbours blocks a legitimate merge (강의 시간은 총 90분입니다 -> ... 총 90분 동안 다룹니다)."""
    out: List = []
    for unit in units:
        total = _content_words(unit.text)
        if total < DROP_MIN_WORDS:
            continue
        if len(M.drops(unit.text, out_text).dropped) > DROP_SHARE * total:
            out.append(unit)
    return out


def dropped_conditions(units: Sequence, out_text: str) -> List[Violation]:
    """condition_dropped for a source conditional clause (meaning._conditions: -면, -다면, 경우, 만약 ...) whose content
    words have no trace in the whole rewritten paragraph. meaning.compare compares marker counts, and a rewrite that
    adds a condition elsewhere in the paragraph (버튼을 눌러 분리합니다 -> 버튼을 누르면 분리됩니다) would hide a dropped
    one (씻은 경우에는 ... 장착하십시오 -> 장착하십시오). As in meaning's content_dropped rule, the lost words must
    outnumber the content words the paragraph gained (계속되면 -> 이어지면 is a substitution, not a drop)."""
    added: Optional[int] = None
    for unit in units:
        for start, end in M._conditions(T.mask_quotes(unit.text)):        # quotations are frozen: never a drop
            lost = M.drops(unit.text[start:end], out_text).words
            if lost and added is None:
                added = len(M.drops(" ".join(u.text for u in units), out_text).added)
            if lost and len(lost) > (added or 0):
                return [_v("condition_dropped", "meaning", "hard", unit.id, "paragraph", ", ".join(lost))]
    return []


def _contrast(src: Document, out: Document, si: Sequence[int], oi: Sequence[int]) -> Tuple[Optional[str], Optional[str]]:
    return FL._contrast(FL._features([src.units[i] for i in si]), FL._features([out.units[j] for j in oi]))


def violations(src: Document, out: Document, paras: Sequence[Para], *, flags: C.Flags, genre: str = "general",
               fix_colloquial: bool = False, spans: Sequence[Span] = (), document: Optional[str] = None,
               seam: Optional[Dict[str, str]] = None, kept: Optional[Sequence[Sequence[str]]] = None) -> List[Violation]:
    """Every family's violations of `out` against `src` per paragraph pair (module docstring), all severities.
    `src` and `out` must have the same paragraph count. `kept[k]` are the base sentences of paragraph k
    (default: its source sentences), which keep their own speech level."""
    if src.text == out.text:
        return []
    groups = paragraph_pairs(src, out, paras)
    members = _out_members(out)
    found: List[Violation] = []
    changed: List[Para] = []
    for para, pairs in zip(paras, groups):
        oi = members.get(para.index, [])
        src_text, out_text = _paragraph_text(src, para.index), _paragraph_text(out, para.index)
        if src_text == out_text or not para.units:
            continue
        changed.append(para)
        units = [src.units[i] for i in para.units]
        sid = units[0].id
        # floor
        found.extend(F.check_pair(units if len(units) > 1 else units[0], out_text, spans, document=document,
                                  sentence=sid))
        found.extend(_v("sentence_dropped", "floor", "hard", unit.id) for unit in dropped_sentences(units, out_text))
        ratio = len(out_text.strip()) / max(1, len(src_text.strip()))
        if not RATIO_MIN <= ratio <= RATIO_MAX:
            found.append(_v("paragraph_length_ratio", "runaway", "hard", sid, f"ratio:{ratio:.2f}"))
        # norms
        if C.family_mode(flags, "norms") != "off":
            found.extend(N.introduced(src_text, out_text, sentence=sid))
        # meaning, on the whole paragraph
        if C.family_mode(flags, "meaning") != "off":
            hits = M.compare(units, [out.units[j] for j in oi], sentence=sid)
            found.extend(hits)
            # Counts that the whole paragraph balances out (a negation removed here and added there, a hedge dropped
            # while another CAN stays) still show per aligned group; drops do not, as words may move between sentences.
            codes = {v.code for v in hits}
            for si, oj in M.groups(pairs):
                for v in M.compare([src.units[i] for i in sorted(si)], [out.units[j] for j in sorted(oj)]):
                    if v.code not in codes and v.code not in PARAGRAPH_ONLY_MEANING:
                        codes.add(v.code)
                        found.append(v)
            if not any(v.code == "condition_dropped" for v in hits):
                found.extend(dropped_conditions(units, out_text))
        # voice, the paragraph rule
        if C.family_mode(flags, "voice") != "off" and oi:
            fs = _features(src, para.units)
            bases = kept[para.index] if kept is not None else [u.text for u in units]
            own = fs + [V.features(text, u.kind) for u, text in zip(units, bases) if text != u.text]
            found.extend(voice_violations(fs, _features(out, oi), own, sid, fix_colloquial=fix_colloquial))
        # flow: contrast markers counted on the whole paragraph
        if C.family_mode(flags, "flow") != "off":
            label, keep_marker = _contrast(src, out, para.units, oi)
            if label:
                found.append(_v("flow_contrast_changed", "flow", "hard", sid, label, keep_marker))
    if not changed:
        return found
    pairs = [pair for group in groups for pair in group]
    if C.family_mode(flags, "cta") != "off":
        result = CG.compare(src, out, pairs, paragraph_scope=True)
        found.extend(result["hard"])
        # A condition reworded with no evidence that its meaning changed (cta_gate.condition_check, soft "reworded")
        # is what a rewrite does; a changed or dropped condition stays.
        found.extend(v for v in result["soft"] if not (v.code == "cta_condition_changed" and v.detail == "reworded"))
    if C.family_mode(flags, "flow") != "off":
        cross = _cross_moves(src, out, pairs, groups)
        for v in FL.check(src, out, pairs, seam=seam):
            if v.code in FLOW_ALLOWED or v.code == "flow_contrast_changed":
                continue
            if v.code == "flow_order_changed" and v.sentence not in cross:
                continue
            found.append(v)
    if C.family_mode(flags, "clarity") != "off":
        found.extend(v for v in CL.check(src, out, pairs, genre=genre) if v.code not in CLARITY_ALLOWED)
    return found


def _cross_moves(src: Document, out: Document, pairs: Sequence[A.Pair], groups: Sequence[Sequence[A.Pair]]) -> Set[str]:
    """Ids of source sentences that reappear in ANOTHER paragraph: moved in the whole chunk, not inside their own."""
    moved, _ = FL._moved(src.units, out.units, pairs)
    if not moved:
        return set()
    inside: Set[int] = set()
    for group in groups:
        local, _ = FL._moved(src.units, out.units, group)
        inside |= local
    return {src.units[i].id for i in moved - inside}


# --------------------------------------------------------------------------
# applying a reply
# --------------------------------------------------------------------------
@dataclass
class Applied:
    texts: List[str]                                              # per source paragraph, before repair
    supplied: Set[int] = field(default_factory=set)               # paragraphs the reply gave a text for
    rejected: Dict[int, Tuple[str, str, bool]] = field(default_factory=dict)
    collateral: Set[int] = field(default_factory=set)
    unusable: Optional[str] = None


class _State:
    def __init__(self, plan: Plan, source: str, document: Optional[str], flags: C.Flags):
        from . import plan as PL                    # late: plan imports this module
        self.plan, self.flags = plan, flags
        self.doc = PL.source_document(plan, source)
        self.paras = paragraphs_of(self.doc, plan.protected)
        if plan.paragraphs is not None and [(p.id, p.editable, p.sentences) for p in plan.paragraphs] != \
                [(p.id, p.editable, [self.doc.units[i].id for i in p.units]) for p in self.paras]:
            raise PL.PlanMismatch("the plan's paragraphs differ from this engine's segmentation of the source")
        self.n = len(self.paras)
        self.src = [_paragraph_text(self.doc, k) for k in range(self.n)]
        unit_base = PL.base_texts(plan, source, self.doc)
        self.unit_base = unit_base
        self.base = [self._base_paragraph(para, unit_base) for para in self.paras]
        self.kept = [[unit_base[i] for i in para.units] for para in self.paras]
        self.para_of = {}
        for para in self.paras:
            for i in para.units:
                self.para_of[self.doc.units[i].id] = para.index
        self.request_at = {r.sentence: r for r in plan.requests}
        self.document = document
        self.seam = None
        if plan.chunk.total > 1 and document is not None:
            (a, b), (c, d) = plan.seam.prev, plan.seam.next
            if b <= len(document) and d <= len(document):
                self.seam = {"prev": document[a:b], "next": document[c:d]}

    def _base_paragraph(self, para: Para, unit_base: Sequence[str]) -> str:
        text = self.src[para.index]
        offset = para.start
        pieces, last = [], 0
        for i in para.units:
            unit = self.doc.units[i]
            pieces.append(text[last:unit.start - offset])
            pieces.append(unit_base[i])
            last = unit.end - offset
        pieces.append(text[last:])
        return "".join(pieces)

    def retryable(self, k: int) -> bool:
        return self.paras[k].editable and len(self.src[k]) <= RETRY_MAX_CHARS

    def candidate(self, texts: Sequence[str]) -> Tuple[str, Document]:
        text = assemble(self.doc, texts)
        return text, (self.doc if text == self.doc.text else T.segment(text))

    def licensed_meaning(self, k: int, text: str) -> bool:
        """A paragraph holding an SSJ-A06 request (결코/좀처럼/차마/전혀 without a negation) licenses the polarity change
        its fix makes once the rule's success check passes on the paragraph (check.py, per sentence there)."""
        rules = {rule for i in self.paras[k].units for rule in getattr(self.request_at.get(self.doc.units[i].id),
                                                                         "rules", ())}
        return bool(rules & set(POLARITY_RULES)) and text != self.base[k] and \
            all(D.request_fixed(rule, text) for rule in rules & set(POLARITY_RULES))

    def verify(self, texts: Sequence[str]):
        """(enforced violations per paragraph, unattributed enforced violations, shadow violations)."""
        from . import verify as VF                  # late: verify imports this module for --mode rewrite
        text, out = self.candidate(texts)
        if len(out.paragraphs) != self.n:           # never by construction; a safe answer if it happens
            found = [_v("flow_paragraph_count_changed", "flow", "hard", None,
                        f"paragraphs:{self.n}->{len(out.paragraphs)}")]
        else:
            found = violations(self.doc, out, self.paras, flags=self.flags, genre=self.plan.options.genre,
                               fix_colloquial=self.plan.options.fix_colloquial, spans=self.plan.protected,
                               document=self.document, seam=self.seam, kept=self.kept)
        licensed: Dict[int, bool] = {}
        kept: List[Violation] = []
        for v in found:
            k = self.para_of.get(v.sentence or "")
            if k is not None and v.code in LICENSED_BY_POLARITY_RULES:
                if k not in licensed:
                    licensed[k] = self.licensed_meaning(k, texts[k])
                if licensed[k]:
                    continue
            kept.append(v)
        enforced, shadow = VF.classify(self.flags, kept)
        per: Dict[int, List[Violation]] = {}
        loose: List[Violation] = []
        for v in enforced:
            k = self.para_of.get(v.sentence or "")
            if k is None:
                loose.append(v)
            else:
                per.setdefault(k, []).append(v)
        return per, loose, shadow


def _split_paragraph(text: str) -> bool:
    return any(not line.strip() for line in text.strip().split("\n"))


def _take(st: _State, result: Applied, k: int, text: str) -> None:
    """One paragraph text of the reply (sanitized, layout checked) onto result.texts[k]."""
    para = st.paras[k]
    result.supplied.add(k)
    if not para.editable:
        if text.strip() != st.src[k].strip() and text.strip() != st.base[k].strip():
            result.collateral.add(k)
        return
    if not text.strip():
        result.rejected[k] = ("paragraph_length_ratio", "blank", True)
        return
    if _split_paragraph(text):
        result.rejected[k] = ("paragraph_split", "blank_line", True)
        return
    if _lines(text) != _lines(st.src[k]):
        result.rejected[k] = ("paragraph_lines_changed", f"lines:{_lines(st.src[k])}->{_lines(text)}", True)
        return
    fitted = _fit(st.src[k], text)
    if fitted.strip() != st.src[k].strip():
        result.texts[k] = fitted


def apply_full_text(st: _State, text: str, start: Sequence[str]) -> Applied:
    result = Applied(texts=list(start))
    clean, _report = T.sanitize(text)
    out = T.segment(clean)
    if not clean.strip():
        return result                               # nothing to change
    if len(out.paragraphs) != st.n:
        result.unusable = "paragraph_count"
        return result
    for k, (a, b) in enumerate(out.paragraphs):
        piece = clean[a:b]
        if piece.strip() in (start[k].strip(), st.src[k].strip()):
            continue
        _take(st, result, k, piece)
    return result


def apply_response(st: _State, response: object, start: Sequence[str], attempt: int) -> Applied:
    result = Applied(texts=list(start))
    problems = IO.response_problems(response) if isinstance(response, dict) else ["$: not an object"]
    if problems:
        result.unusable = "schema"
        return result
    replacements, rewritten = response["replacements"], response["rewrittenText"]
    if attempt == 1:
        if replacements:
            result.unusable = "replacements_not_allowed"
            return result
        return apply_full_text(st, rewritten, start)
    if rewritten.strip():
        result.unusable = "rewritten_text_not_allowed"
        return result
    index_of = {para.id: para.index for para in st.paras}
    seen: Set[str] = set()
    for item in replacements:
        pid = item["id"]
        if pid in seen:
            result.unusable = "duplicate_id"
            return result
        seen.add(pid)
        if pid not in index_of:
            result.unusable = "unknown_id"
            return result
    for item in replacements:
        k = index_of[item["id"]]
        if not st.paras[k].editable:
            result.supplied.add(k)
            result.rejected[k] = ("replacement_frozen_unit", "paragraph", False)
            continue
        text, _report = T.sanitize(item["text"])
        if text.strip() == start[k].strip():
            result.supplied.add(k)
            continue
        _take(st, result, k, text)
    return result


def recover(st: _State, text: str) -> List[str]:
    """Per-paragraph texts of the attempt-1 decision (assembled by this module with the source's gaps); any other
    shape gives base(x) back, which always verifies."""
    out = T.segment(text)
    if len(out.paragraphs) != st.n:
        return list(st.base)
    return [text[a:b] for a, b in out.paragraphs]


def _repair(st: _State, k: int, text: str) -> Tuple[str, List[str], Dict[str, int]]:
    """Deterministic repair of one edited paragraph: norm fixes, then particles the rewrite broke (DESIGN 3.7 steps 1
    and 4). The voice graft and the comma rule are per-sentence repairs and do not apply to a rewritten paragraph."""
    options = st.plan.options
    actions: List[str] = []
    counts = {"normFixes": 0, "repairedParticles": 0}
    if options.deterministic_fix != "off":
        fixed, applied = N.fix_text(text, genre=options.genre, fix_colloquial=options.fix_colloquial)
        if applied and fixed != text:
            text = fixed
            actions.append("norm_fix")
            counts["normFixes"] = len(applied)
    if text != st.src[k]:
        particles = J.gate(st.src[k], text, None, "likely")
        if particles:
            text = J.repair(text, particles)
            actions.append("josa_repair")
            counts["repairedParticles"] = len(particles)
    return text, actions, counts


def _charge(st: _State, per: Dict[int, List[Violation]], loose: Sequence[Violation],
            changed: Set[int]) -> Dict[int, List[Violation]]:
    """Violations per changed paragraph: one on an unchanged paragraph goes to the changed paragraphs next to it
    (else to every changed paragraph), an unattributed one to every changed paragraph."""
    charged: Dict[int, List[Violation]] = {}
    for k, items in per.items():
        if k in changed:
            targets = [k]
        else:
            targets = sorted(j for j in changed if abs(j - k) <= 1) or sorted(changed)
        for target in targets:
            charged.setdefault(target, []).extend(items)
    for v in loose:
        for target in changed:
            charged.setdefault(target, []).append(v)
    return charged


def _unique_codes(items: Sequence[Violation], limit: int = 100) -> List[str]:
    out: List[str] = []
    for v in items:
        if is_code(v.code) and v.code not in out:
            out.append(v.code)
    return out[:limit]


# --------------------------------------------------------------------------
# one check attempt
# --------------------------------------------------------------------------
def check(plan: Plan, source: str, *, response: Optional[object] = None, candidate: Optional[str] = None,
          attempt: int = 1, base: Optional[str] = None, document: Optional[str] = None,
          flags: Optional[C.Flags] = None):
    """Apply, repair, verify and decide one attempt of a rewrite plan, per paragraph (module docstring). Same
    arguments and result (check.CheckOutcome) as check.check, which dispatches here for rewrite plans."""
    from .check import CheckOutcome                 # late: check imports this module
    if response is not None and candidate is not None:
        raise ValueError("pass at most one of response and candidate")
    if attempt not in (1, 2):
        raise ValueError("attempt must be 1 or 2")
    if attempt == 2 and base is None:
        raise ValueError("attempt 2 needs the decided text of attempt 1")
    flags = flags if flags is not None else C.Flags.from_env()
    st = _State(plan, source, document, flags)
    n = st.n
    start = recover(st, base) if attempt == 2 else list(st.src)
    previous = {k for k in range(n) if attempt == 2 and start[k] != st.base[k]}

    # 1. apply
    if response is not None:
        ar = apply_response(st, response, start, attempt)
    elif candidate is not None:
        ar = apply_full_text(st, candidate, start)
    else:
        ar = Applied(texts=list(start))
    unusable = ar.unusable is not None
    if unusable:
        ar = Applied(texts=list(start), unusable=ar.unusable)
    edited = {k for k in range(n) if ar.texts[k] != start[k]}

    # 2. repair
    texts = [ar.texts[k] if k in edited else (start[k] if attempt == 2 else st.base[k]) for k in range(n)]
    repairs: Dict[int, List[str]] = {}
    repair_counts: Dict[int, Dict[str, int]] = {}
    for k in sorted(edited):
        texts[k], repairs[k], repair_counts[k] = _repair(st, k, texts[k])

    # 3. verify
    changed = {k for k in range(n) if texts[k] != st.base[k]}
    per, loose, shadow = st.verify(texts) if changed else ({}, [], [])
    charged = _charge(st, per, loose, changed)

    # 4. decide
    verdicts: Dict[int, DC.Verdict] = {}
    reasons: Dict[int, List[Violation]] = {}
    for k in range(n):
        sid = st.doc.units[st.paras[k].units[0]].id if st.paras[k].units else None
        if k in ar.collateral:
            verdicts[k] = DC.Verdict("reverted", "revert", ["collateral_edit"])
            continue
        rejection = ar.rejected.get(k) if texts[k] == st.base[k] else None
        if rejection is not None and not st.retryable(k):
            rejection = (rejection[0], rejection[1], False)
        verdict = DC.decide_sentence(changed=k in changed, deterministic=st.base[k] != st.src[k],
                                     licensed=st.paras[k].editable, rejection=rejection,
                                     enforced=charged.get(k, ()), attempt=attempt)
        if verdict.status == "retry" and not st.retryable(k):
            verdict = DC.Verdict("reverted", "revert", verdict.codes)
        verdicts[k] = verdict
        reasons[k] = list(charged.get(k, ()))
        if rejection is not None:
            family = "runaway" if rejection[0] == "paragraph_length_ratio" else None
            reasons[k].insert(0, Violation(code=rejection[0], family=family, severity="hard", sentence=sid,
                                           detail=rejection[1]))
    if unusable and attempt == 1:
        for k in range(n):
            if st.retryable(k):
                sid = st.doc.units[st.paras[k].units[0]].id
                verdicts[k] = DC.Verdict("retry", "retry", ["model_output_unusable"])
                reasons[k] = [Violation(code="model_output_unusable", severity="hard", sentence=sid,
                                        detail=ar.unusable or "")]
    for k, verdict in verdicts.items():
        if verdict.action != "keep":
            texts[k] = st.base[k]

    # Re-verify the decided candidate until no kept paragraph picks up a new enforced violation.
    final_shadow, dirty = shadow, False
    for _round in range(MAX_ROUNDS):
        kept = {k for k in range(n) if texts[k] != st.base[k]}
        if not kept:
            dirty = True
            break
        per, loose, final_shadow = st.verify(texts)
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

    # Text-level floor on the whole chunk (footnotes, headings, numbers across paragraphs): every edit, then the source.
    floor_failed: List[str] = []
    to_source = False
    text = assemble(st.doc, texts)
    codes = F.text_codes(source, text, document=document) if text != source else []
    for stage in ("edits", "source"):
        if not codes:
            break
        dirty = True
        found = [_v(code, "floor", "hard", None) for code in codes]
        if stage == "source":
            to_source = True
            for k in range(n):
                if texts[k] != st.src[k]:
                    verdicts[k] = DC.Verdict("reverted", "revert", list(codes))
                    reasons[k] = list(found)
            texts = list(st.src)
        else:
            for k in range(n):
                if texts[k] != st.base[k]:
                    verdicts[k] = DC.Verdict("reverted", "revert", list(codes))
                    reasons[k] = list(found)
                    texts[k] = st.base[k]
        text = assemble(st.doc, texts)
        codes = F.text_codes(source, text, document=document) if text != source else []
    if codes:
        floor_failed = list(codes)
    if dirty:
        final_shadow = st.verify(texts)[2] if texts != st.src else []

    # 5. gate and report
    kept_edits = any(texts[k] != st.base[k] for k in range(n))
    retry_pending = any(v.status == "retry" for v in verdicts.values())
    gate = DC.chunk_gate(attempt, retry=retry_pending, runaway=False, unusable=unusable, floor_failed=floor_failed,
                         shadow=_unique_codes(final_shadow), kept_edits=kept_edits,
                         has_requests=any(p.editable for p in st.paras))
    if gate.policy != "retry":
        for k, verdict in verdicts.items():
            if verdict.status == "retry":
                verdicts[k] = DC.Verdict("rejected" if not reasons.get(k) else "reverted", "revert", verdict.codes)
    if gate.policy == "rollback" and not floor_failed and not to_source:
        for k in range(n):
            if texts[k] != st.base[k]:
                verdicts[k] = DC.Verdict("reverted", "revert", verdicts[k].codes or list(gate.hard))
                texts[k] = st.base[k]
        text = assemble(st.doc, texts)
    report = _report(st, ar, texts, verdicts, reasons, repairs, repair_counts, gate, attempt, previous)
    return CheckOutcome(text=text, report=report)


def _report(st: _State, ar: Applied, texts: Sequence[str], verdicts: Dict[int, DC.Verdict],
            reasons: Dict[int, List[Violation]], repairs: Dict[int, List[str]],
            repair_counts: Dict[int, Dict[str, int]], gate: DC.Gate, attempt: int, previous: Set[int]) -> CheckReport:
    from . import plan as PL
    plan, doc = st.plan, st.doc
    counts = empty_counts()
    sentences: List[SentenceVerdict] = []
    retry: List[RetryItem] = []
    fixes_by_sentence = PL.deterministic_by_sentence(plan)
    for k, para in enumerate(st.paras):
        verdict = verdicts[k]
        codes = [c for c in dict.fromkeys(verdict.codes) if is_code(c)][:100]
        request = para.id if para.editable else None
        if verdict.status == "accepted":
            for key, value in repair_counts.get(k, {}).items():
                counts[key] += value
        families = sorted({v.family for v in reasons.get(k, []) if v.family})
        for i in para.units:
            unit = doc.units[i]
            status = verdict.status
            unit_repairs: List[str] = []
            if status == "accepted":
                unit_repairs = [r for r in repairs.get(k, []) if is_code(r)]
            elif texts[k] == st.base[k] and st.unit_base[i] != unit.text:
                unit_repairs = ["norm_fix"]
                if plan.options.deterministic_fix == "all":
                    counts["normFixes"] += len(fixes_by_sentence.get(unit.id, ()))
            if status in ("unchanged", "deterministic"):
                status = "deterministic" if st.unit_base[i] != unit.text and texts[k] != st.src[k] else "unchanged"
            if status in ("reverted", "rejected"):
                counts["revertedSentences"] += 1
                if "collateral_edit" in codes:
                    counts["collateralReverts"] += 1
                for family in families:
                    counts["revertedByFamily"][family] = counts["revertedByFamily"].get(family, 0) + 1
                if "meaning" in families:
                    counts["restoredSentences"] += 1
            sentences.append(SentenceVerdict(id=unit.id, request=request, status=status, codes=codes,
                                             repairs=list(dict.fromkeys(unit_repairs))[:100]))
        if verdict.status == "retry" and request is not None and para.units:
            first = doc.units[para.units[0]].id
            items: List[Violation] = []
            seen = set()
            for v in reasons.get(k, []):
                key = (v.code, v.detail)
                if key in seen or not is_code(v.code):
                    continue
                seen.add(key)
                sid = v.sentence if v.sentence and v.sentence in st.para_of else first
                items.append(Violation(code=v.code, family=v.family, severity=v.severity, sentence=sid,
                                       detail=(v.detail or "")[:DETAIL_MAX], keep=v.keep[:DETAIL_MAX] if v.keep else None))
            if not items:
                items = [Violation(code=codes[0] if codes else "model_output_unusable", severity="hard", sentence=first)]
            retry.append(RetryItem(id=request, sentence=first, violations=items[:MAX_RETRY_VIOLATIONS]))
    status_counts = empty_request_status()
    supplied = set(ar.supplied) | previous
    for request in plan.requests:
        k = st.para_of[request.sentence]
        if k not in supplied:
            status_counts["DECLINED"] += 1
        elif texts[k] == st.base[k]:
            status_counts["UNTOUCHED" if verdicts[k].status in ("unchanged", "deterministic") else "STILL_PRESENT"] += 1
        elif all(_request_fixed(rule, texts[k], plan.options.genre) for rule in request.rules):
            status_counts["FIXED"] += 1
        else:
            status_counts["STILL_PRESENT"] += 1
    from . import verify as VF
    return CheckReport(gate={"exit_code": gate.exit_code}, hard_failures=gate.hard[:100],
                       warning_reasons={"version": 1, "codes": []}, policy=gate.policy,
                       shadow_failures=gate.shadow[:100], attempt=attempt, sentences=sentences,
                       retry=retry if gate.policy == "retry" else [], request_status=status_counts, counts=counts,
                       change_rate=round(VF.rate_of_texts(st.src, texts), 3))


def _request_fixed(rule: str, text: str, genre: str) -> bool:
    from .check import _request_fixed as fixed
    return fixed(rule, text, genre)


# --------------------------------------------------------------------------
# whole documents (verify --mode rewrite)
# --------------------------------------------------------------------------
def floor_violations(before: str, after: str, *, context: Optional[str] = None) -> List[Violation]:
    """The floor of a whole rewritten text (sejong_cli finalize): the text-level codes (footnotes, headings, numbers,
    quotes, names, weekdays) and, per paragraph pair, floor.check_pair and dropped_sentences. floor.check would align
    the texts sentence by sentence and read a merged sentence as dropped. Another paragraph count: floor.check."""
    if before == after:
        return []
    src, out = T.segment(before), T.segment(after)
    spans = P.protected_spans(src)
    if len(src.paragraphs) != len(out.paragraphs):
        return list(F.check(before, after, document=context, spans=spans))
    found = [_v(code, "floor", "hard", None) for code in F.text_codes(before, after, document=context)]
    for para in paragraphs_of(src, spans):
        src_text, out_text = _paragraph_text(src, para.index), _paragraph_text(out, para.index)
        if src_text == out_text or not para.units:
            continue
        units = [src.units[i] for i in para.units]
        found.extend(F.check_pair(units if len(units) > 1 else units[0], out_text, spans, document=context,
                                  sentence=units[0].id))
        found.extend(_v("sentence_dropped", "floor", "hard", unit.id) for unit in dropped_sentences(units, out_text))
    return found


def document_violations(before: str, after: str, *, context: Optional[str] = None, flags: Optional[C.Flags] = None,
                        genre: str = "general") -> Tuple[List[Violation], float]:
    """(violations, change rate) of a whole rewritten document: the text-level floor on the whole text and the
    paragraph families of `violations`; another paragraph count is flow_paragraph_count_changed plus the full floor.
    There is no change-rate runaway in rewrite mode (the rate is reported only)."""
    from . import verify as VF
    flags = flags if flags is not None else C.Flags.from_env()
    if before == after:
        return [], 0.0
    src, out = T.segment(before), T.segment(after)
    spans = P.protected_spans(src, fix_colloquial=flags.fix_colloquial)
    rate = VF.change_rate(before, after, src=src, out=out)
    if len(src.paragraphs) != len(out.paragraphs):
        found = list(F.check(before, after, document=context, spans=spans))
        found.append(_v("flow_paragraph_count_changed", "flow", "hard", None,
                        f"paragraphs:{len(src.paragraphs)}->{len(out.paragraphs)}"))
        return found, rate
    found = [_v(code, "floor", "hard", None) for code in F.text_codes(before, after, document=context)]
    found.extend(violations(src, out, paragraphs_of(src, spans), flags=flags, genre=genre,
                            fix_colloquial=flags.fix_colloquial, spans=spans, document=context))
    return found, rate
