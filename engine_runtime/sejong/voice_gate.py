"""Per-sentence voice lock (말투 잠금) of Super Sejong Engine v2 (DESIGN.md 3.8, OD 1, OD 2, OD 4).

    check(src, out, pairs=None, *, fix_colloquial=False) -> list[Violation]
    check_pairs(src, out, pairs=None, *, fix_colloquial=False) -> list[tuple[int, Violation]]
    compare_texts(src_text, out_text, *, fix_colloquial=False) -> list[Violation]

Every source sentence keeps its own speech level, mood, honorific -시-, stance ending, persona,
humble forms and keep tokens; the document profile is never used (OD 1). Port of
docs/research/super-sejong/v2/prototypes/T2_gate.py on the WP-1 units and the WP-2 aligner.

Codes (family "voice", lowercase for the TS parser). Per aligned pair:

  hard  voice_level                 speech level changed (any of the 8, incl. NOMINAL <-> finite);
                                    not checked when the source sentence is NONE (a fragment)
        voice_mood                  sentence type changed (DECL <-> EXCL is soft); for non-finite
                                    sentences a final '?' added or removed; between two DECL
                                    sentences a request ending (바랍니다, 부탁드립니다) added or removed
        voice_hon_si_dropped/added  -시- of the final predicate changed, or (lead decision 9.2a
                                    item 3) the number of -시- anywhere in the sentence changed:
                                    궁금하신 점이 -> 궁금한 점이 is hard
        voice_quote_level           level inside a quotation changed (same number of quotations)
        voice_split_level           a split piece other than the last takes another level
        voice_merge_across_levels   two source sentences of different finite levels merged
        voice_merge_lost_mood       a merged question/request/proposal became the other's mood
        voice_merge_lost_hon_si     the merged sentence lost a -시- only the first sentence had
        voice_inserted_level        an inserted sentence's level differs from the source sentence
                                    before it
  soft  voice_stance                stance family changed (더라고요, 거든요, 잖아요, 네요, 죠, 답니다 ...)
        voice_persona_swap/dropped/added   저/제가/저희 vs 나/내가 vs 우리; persona marker lost or new
        voice_humble_dropped        fewer humble forms (드리다, 여쭙다, 뵙다, 모시다)
        voice_humble_added          more humble forms (the main-branch lock compares the count)
        voice_hon_noun_changed      number of honorific address nouns (고객님, 학부모님) or honorific
                                    datives (학부모님들께) changed
        voice_emoticon_dropped/added       CMC tokens (ㅋㅋ ㅎㅎ ㅠㅠ ^^ ~ emoji), as protect.keep_tokens
                                    normalises them, or the raw marks when only a run changed (ㅋㅋㅋ -> ㅋㅋ)
        voice_colloquial_changed    a 할께-family or colloquial spelling (넹, 걍, 습니당) lost
        voice_discourse_dropped     a discourse marker (사실, 뭐) or intensifier (진짜, 완전) lost
        voice_colloquial_added      a colloquial spelling or discourse marker that was not there
        voice_written_upshift       more 하였/되었/하여 forms (했 -> 하였)

With fix_colloquial (SUPER_SEJONG_FIX_COLLOQUIAL=1, OD 2 opt-in) voice_emoticon_dropped,
voice_colloquial_changed and voice_discourse_dropped are reported as info.

Group rules (T2): a 1:k split compares the source with the last piece and requires every other
piece to keep the source level; an n:1 merge compares the last source sentence with the output and
applies the merge rules; markers, -시- count, humble count and keep tokens are compared on the whole
group. A deleted source sentence is the floor family's business (sentence_dropped), not voice.
Identical pairs are skipped without analysis, so check(x, x) costs one alignment pass.
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple

from . import align as A
from . import text as T
from . import voice as V
from .types import Document, Unit, Violation

FAMILY = "voice"
HARD_CODES = ("voice_level", "voice_mood", "voice_hon_si_dropped", "voice_hon_si_added", "voice_quote_level",
              "voice_split_level", "voice_merge_across_levels", "voice_merge_lost_mood", "voice_merge_lost_hon_si",
              "voice_inserted_level")
SOFT_CODES = ("voice_stance", "voice_persona_swap", "voice_persona_dropped", "voice_persona_added",
              "voice_humble_dropped", "voice_humble_added", "voice_hon_noun_changed", "voice_emoticon_dropped",
              "voice_emoticon_added", "voice_colloquial_changed", "voice_discourse_dropped", "voice_colloquial_added",
              "voice_hon_si_elsewhere", "voice_written_upshift")
# Codes that become info under the OD 2 opt-in.
OPT_IN_INFO = ("voice_emoticon_dropped", "voice_colloquial_changed", "voice_discourse_dropped")
_REQUEST_MOODS = ("INTERR", "IMPER", "PROPOS")


class _Cache:
    """features() per unit, computed on first use."""

    def __init__(self, units: Sequence[Unit]):
        self.units = units
        self.values: Dict[int, V.Features] = {}

    def __getitem__(self, index: int) -> V.Features:
        value = self.values.get(index)
        if value is None:
            unit = self.units[index]
            value = self.values[index] = V.features(unit.text, unit.kind)
        return value


def _v(code: str, severity: str, sentence: Optional[str], detail: str = "", keep: Optional[str] = None) -> Violation:
    return Violation(code=code, family=FAMILY, severity=severity, sentence=sentence, detail=detail, keep=keep)


def _final_form(f: V.Features) -> Optional[str]:
    return f.sig.final or None


# --------------------------------------------------------------------------
# one sentence against one sentence (level, mood, final -시-, stance, quotes)
# --------------------------------------------------------------------------
def _compare_one(a: V.Features, b: V.Features, sid: Optional[str]) -> List[Violation]:
    out: List[Violation] = []
    sa, sb = a.sig, b.sig
    keep = _final_form(a)
    if a.quote_levels and len(a.quote_levels) == len(b.quote_levels):
        for x, y in zip(a.quote_levels, b.quote_levels):
            if x != y and x in V.FINITE:
                out.append(_v("voice_quote_level", "hard", sid, f"{x}->{y}"))
    if a.inner and len(a.inner) == len(b.inner):
        for (lx, mx), (ly, my) in zip(a.inner, b.inner):
            if lx != ly:
                out.append(_v("voice_level", "hard", sid, f"inner:{lx}->{ly}"))
            elif mx != my:
                out.append(_v("voice_mood", "hard", sid, f"inner:{mx}->{my}"))
    if sa.level != V.NONE and sa.level != sb.level:
        out.append(_v("voice_level", "hard", sid, f"{sa.level}->{sb.level}", keep))
    both_finite = sa.level in V.FINITE and sb.level in V.FINITE
    if both_finite and sa.mood != sb.mood:
        severity = "soft" if {sa.mood, sb.mood} == {"DECL", "EXCL"} else "hard"
        out.append(_v("voice_mood", severity, sid, f"{sa.mood}->{sb.mood}", keep))
    elif not both_finite and a.question != b.question:
        out.append(_v("voice_mood", "hard", sid, "INTERR->DECL" if a.question else "DECL->INTERR", keep))
    elif a.directive != b.directive:
        out.append(_v("voice_mood", "hard", sid, "DIRECTIVE->DECL" if a.directive else "DECL->DIRECTIVE", keep))
    if both_finite and sa.hon_si != sb.hon_si:
        out.append(_v("voice_hon_si_dropped" if sa.hon_si else "voice_hon_si_added", "hard", sid, "final", keep))
    if sa.level in V.FINITE and a.stance_family != b.stance_family:
        out.append(_v("voice_stance", "soft", sid, f"{a.stance_family}->{b.stance_family}", keep))
    return out


# --------------------------------------------------------------------------
# markers compared on a whole group (-시- count, persona, humble, keep tokens, up-shift)
# --------------------------------------------------------------------------
def _sum_keep(fs: Sequence[V.Features]) -> Counter:
    total: Counter = Counter()
    for f in fs:
        total.update(f.keep)
    return total


def _sum_marks(fs: Sequence[V.Features]) -> Counter:
    total: Counter = Counter()
    for f in fs:
        total.update(f.marks)
    return total


def _compare_group(src: Sequence[V.Features], out: Sequence[V.Features], sid: Optional[str],
                   prior: Sequence[Violation], fix_colloquial: bool) -> List[Violation]:
    found: List[Violation] = []
    relaxed = "info" if fix_colloquial else "soft"
    si_src, si_out = sum(f.sig.si_count for f in src), sum(f.sig.si_count for f in out)
    if si_src != si_out and not any(v.code.startswith("voice_hon_si") for v in prior):
        found.append(_v("voice_hon_si_dropped" if si_out < si_src else "voice_hon_si_added", "hard", sid,
                        f"count {si_src}->{si_out}"))
    ks, ko = _sum_keep(src), _sum_keep(out)
    lost, gained = ks - ko, ko - ks
    by_kind_lost: Dict[str, List[str]] = {}
    for (kind, token), n in lost.items():
        by_kind_lost.setdefault(kind, []).extend([token] * n)
    by_kind_gained: Dict[str, List[str]] = {}
    for (kind, token), n in gained.items():
        by_kind_gained.setdefault(kind, []).extend([token] * n)
    if "cmc" in by_kind_lost:
        found.append(_v("voice_emoticon_dropped", relaxed, sid, f"cmc:{len(by_kind_lost['cmc'])}",
                        " ".join(sorted(by_kind_lost["cmc"]))))
    elif "cmc" in by_kind_gained:
        found.append(_v("voice_emoticon_added", "soft", sid, f"cmc:{len(by_kind_gained['cmc'])}"))
    else:
        ms, mo = _sum_marks(src), _sum_marks(out)
        if ms != mo:
            dropped = sum(len(k) * n for k, n in mo.items()) <= sum(len(k) * n for k, n in ms.items())
            found.append(_v("voice_emoticon_dropped" if dropped else "voice_emoticon_added",
                            relaxed if dropped else "soft", sid, "marks"))
    if "colloquial" in by_kind_lost:
        found.append(_v("voice_colloquial_changed", relaxed, sid, f"colloquial:{len(by_kind_lost['colloquial'])}",
                        " ".join(sorted(by_kind_lost["colloquial"]))))
    if "discourse" in by_kind_lost:
        found.append(_v("voice_discourse_dropped", relaxed, sid, f"discourse:{len(by_kind_lost['discourse'])}",
                        " ".join(sorted(by_kind_lost["discourse"]))))
    added = len(by_kind_gained.get("colloquial", [])) + len(by_kind_gained.get("discourse", []))
    if added:
        found.append(_v("voice_colloquial_added", "soft", sid, f"added:{added}"))
    ps = {p for f in src for p in f.sig.persona}
    po = {p for f in out for p in f.sig.persona}
    firsts = set(V.FIRST_PERSONS)
    if (ps & firsts) and (po & firsts) and (ps & firsts) != (po & firsts):
        found.append(_v("voice_persona_swap", "soft", sid, f"{'+'.join(sorted(ps & firsts))}->{'+'.join(sorted(po & firsts))}"))
    elif ps - po:
        found.append(_v("voice_persona_dropped", "soft", sid, "+".join(sorted(ps - po))))
    elif (po - ps) & firsts:
        found.append(_v("voice_persona_added", "soft", sid, "+".join(sorted(po - ps))))
    hs, ho = sum(f.humble_count for f in src), sum(f.humble_count for f in out)
    if ho < hs:
        found.append(_v("voice_humble_dropped", "soft", sid, f"{hs}->{ho}"))
    elif ho > hs:
        found.append(_v("voice_humble_added", "soft", sid, f"{hs}->{ho}"))
    ns, no = sum(f.hon_nouns for f in src), sum(f.hon_nouns for f in out)
    if ns != no:
        found.append(_v("voice_hon_noun_changed", "soft", sid, f"{ns}->{no}"))
    spoken_src, spoken_out = sum(len(f.spoken) for f in src), sum(len(f.spoken) for f in out)
    geot_up = sum(f.geot for f in out) > sum(f.geot for f in src) and spoken_out < spoken_src
    if geot_up:
        # 거 같다 -> 것 같다: name the spoken form to keep (거 같아)
        found.append(_v("voice_written_upshift", "soft", sid, keep=next(form for f in src for form in f.spoken)))
    elif sum(f.upshift for f in out) > sum(f.upshift for f in src):
        found.append(_v("voice_written_upshift", "soft", sid))            # 했 -> 하였: the final form is kept
    return found


# --------------------------------------------------------------------------
# pairs
# --------------------------------------------------------------------------
def compare_group(src: Sequence[V.Features], out: Sequence[V.Features], sid: Optional[str] = None, *,
                  fix_colloquial: bool = False) -> List[Violation]:
    """Violations of one aligned group: n source sentences against m output sentences, n, m >= 1."""
    found: List[Violation] = []
    last_src, last_out = src[-1], out[-1]
    found += _compare_one(last_src, last_out, sid)
    if len(out) > 1 and last_src.sig.level in V.FINITE:          # split
        for piece in out[:-1]:
            if piece.sig.level != last_src.sig.level:
                found.append(_v("voice_split_level", "hard", sid, f"{last_src.sig.level}->{piece.sig.level}",
                                _final_form(last_src)))
                break
    if len(src) > 1:                                              # merge
        levels = {f.sig.level for f in src if f.sig.level in V.FINITE}
        if len(levels) > 1:
            found.append(_v("voice_merge_across_levels", "hard", sid, "+".join(f.sig.level for f in src)))
        else:
            lost_mood = next((f.sig.mood for f in src[:-1] if f.sig.level in V.FINITE
                              and f.sig.mood in _REQUEST_MOODS and f.sig.mood != last_out.sig.mood), None)
            if lost_mood:
                found.append(_v("voice_merge_lost_mood", "hard", sid, lost_mood))
            elif any(f.sig.hon_si for f in src[:-1]) and not last_out.sig.hon_si and not last_src.sig.hon_si:
                found.append(_v("voice_merge_lost_hon_si", "hard", sid))
    found += _compare_group(src, out, sid, found, fix_colloquial)
    return found


def check_pairs(src: Document, out: Document, pairs: Optional[Sequence[A.Pair]] = None, *,
                fix_colloquial: bool = False) -> List[Tuple[int, Violation]]:
    """(pair index, violation) for every violation; pairs default to align.align_documents."""
    if pairs is None:
        pairs = A.align_documents(src, out)
    fs, fo = _Cache(src.units), _Cache(out.units)
    found: List[Tuple[int, Violation]] = []
    prev_src: Optional[int] = None
    for index, pair in enumerate(pairs):
        si, oi = pair.src, pair.out
        if si:
            prev_src = si[-1]
        if not oi:
            continue                                   # deleted source sentence: floor family
        if not si:                                     # inserted sentence
            anchor = prev_src if prev_src is not None else _next_src(pairs, index)
            if anchor is None:
                continue
            level_out = fo[oi[0]].sig.level
            level_src = fs[anchor].sig.level
            if level_out in V.FINITE and level_src in V.FINITE and level_out != level_src:
                found.append((index, _v("voice_inserted_level", "hard", src.units[anchor].id,
                                        f"{level_src}->{level_out}")))
            continue
        if len(si) == 1 and len(oi) == 1 and src.units[si[0]].text == out.units[oi[0]].text:
            continue                                   # identical sentence
        sid = src.units[si[-1]].id
        for violation in compare_group([fs[i] for i in si], [fo[j] for j in oi], sid, fix_colloquial=fix_colloquial):
            found.append((index, violation))
    return found


def _next_src(pairs: Sequence[A.Pair], index: int) -> Optional[int]:
    for pair in pairs[index + 1:]:
        if pair.src:
            return pair.src[0]
    return None


def check(src: Document, out: Document, pairs: Optional[Sequence[A.Pair]] = None, *,
          fix_colloquial: bool = False) -> List[Violation]:
    """Voice violations of a candidate against its source, per aligned sentence group (DESIGN 3.8).
    Violation.sentence is the id of the (last) source sentence of the group."""
    return [violation for _, violation in check_pairs(src, out, pairs, fix_colloquial=fix_colloquial)]


def compare_texts(src_text: str, out_text: str, *, kind: str = "body", fix_colloquial: bool = False) -> List[Violation]:
    """Violations between one source sentence and its rewrite given as plain strings (the
    rewrite may hold several sentences; it is then split with the WP-1 splitter)."""
    out = [V.features(u.text, u.kind) for u in T.segment(out_text).units] or [V.features(out_text, kind)]
    return compare_group([V.features(src_text, kind)], out, None, fix_colloquial=fix_colloquial)


def blocking(violations: Sequence[Violation]) -> List[Violation]:
    """The hard and soft violations (the ones repair, retry or revert act on)."""
    return [v for v in violations if v.severity in ("hard", "soft")]
