"""Metamorphic writers for the scorer self-test (WP-15a): each turns a seed record's gold text into
a damaged output with one known defect, so the test can ask whether the scorer notices it.

Port of the damage writers in T7's selftest.py. They are test machinery for the scorer, not part
of the judge (they are left out of bench_io.scorer_sha256). A writer returns None when the record
has no site for its damage. No engine code is imported.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from bench_text import segment, sentences
from voicefeat import voice_profile

Record = Dict[str, Any]


def sent_replace(text: str, k: int, new: str) -> str:
    a, b = [(a, b) for a, b, _ in segment(text)][k]
    return text[:a] + new + text[b:]


def first_sentence_edit(rec: Record, predicate: Callable[[str, Dict[str, Any]], Any], edit: Callable[[str], str]) -> Optional[str]:
    gold = rec["gold_text"]
    for k, s in enumerate(voice_profile(gold)):
        if s["kind"] == "prose" and predicate(gold[s["span"][0]:s["span"][1]], s):
            a, b = s["span"]
            new = edit(gold[a:b])
            if new != gold[a:b]:
                return sent_replace(gold, k, new)
    return None


def dmg_level(rec: Record) -> Optional[str]:
    """합쇼체 -> 해라체 or 해요체 -> 해라체 on the first such sentence."""
    return first_sentence_edit(
        rec, lambda t, s: s["level"] in ("haeyo", "hapsyo"),
        lambda t: re.sub(r"(?:습|ㅂ)?니다(?=[.?!]?$)", "다", t) if t.rstrip(".?! ").endswith("니다") else re.sub(r"요(?=[.?!]?$)", "다", t))


def dmg_ending(rec: Record) -> Optional[str]:
    """더라고요 / 거든요 / 잖아요 / 네요 flattened to 습니다."""
    return first_sentence_edit(rec, lambda t, s: re.search(r"(더라고요|거든요|잖아요|네요)[.?!]?$", t),
                               lambda t: re.sub(r"(더라고요|거든요|잖아요|네요)(?=[.?!]?$)", "습니다", t))


def dmg_persona(rec: Record) -> Optional[str]:
    """First-person subject (저는, 제가) dropped."""
    return first_sentence_edit(rec, lambda t, s: re.search(r"(?<![가-힣])(저는|제가) ", t),
                               lambda t: re.sub(r"(?<![가-힣])(저는|제가) ", "", t, count=1))


def dmg_honorific(rec: Record) -> Optional[str]:
    """-시- dropped (하셨 -> 했)."""
    return first_sentence_edit(rec, lambda t, s: "하셨" in t, lambda t: t.replace("하셨", "했", 1))


def dmg_meaning(rec: Record) -> Optional[str]:
    """A hand-written change probe (negation, modality, number, role ...) spliced into the gold text."""
    for p in rec["probes"]:
        if p["label"] == "change":
            gold = rec["gold_text"]
            src = [t for _, _, t in sentences(rec["text"])[0]]
            if p["source_sentence"] in src and len(sentences(gold)[0]) == len(src):
                return sent_replace(gold, src.index(p["source_sentence"]), p["rewrite"])
    return None


def dmg_cta(rec: Record) -> Optional[str]:
    """The first explicit CTA sentence replaced by a neutral statement at the same level."""
    explicit = [c for c in rec["cta"] if c["cta_class"] == "explicit"]
    if not explicit:
        return None
    gold = rec["gold_text"]
    src = sentences(rec["text"])[0]
    k = [i for i, (a, b, _) in enumerate(src) if a <= explicit[0]["span"][0] < b][0]
    if len(sentences(gold)[0]) != len(src):
        return None
    return sent_replace(gold, k, "자세한 내용은 아래와 같습니다." if rec["voice_stratum"] in ("hapsyo",) else "자세한 내용은 아래와 같아요.")


def dmg_collateral(rec: Record) -> Optional[str]:
    """A connective added in front of the first sentence that carries no injection."""
    gold = rec["gold_text"]
    src, kinds = sentences(rec["text"])
    injected = {next(i for i, (a, b, _) in enumerate(src) if a <= x["span"][0] < b) for x in rec["injections"]}
    for k, (_, _, t) in enumerate(src):
        if k not in injected and kinds[k] == "prose" and len(sentences(gold)[0]) == len(src):
            return sent_replace(gold, k, "물론 " + t)
    return None


def dmg_colloquial(rec: Record) -> Optional[str]:
    """Colloquial spellings corrected and CMC tokens stripped (over-editing under the default config)."""
    if not rec["protected_tokens"]:
        return None
    gold = rec["gold_text"]
    for pt in rec["protected_tokens"]:
        if pt["kind"] == "colloquial_spelling" and pt["optional_fix"]:
            gold = gold.replace(pt["text"], pt["optional_fix"]["gold_fix"])
        elif pt["kind"] == "cmc":
            gold = gold.replace(pt["text"], "")
    return gold if gold != rec["gold_text"] else None


# (label, writer, detector over score_item's result). Order is T7's section 7 table.
DAMAGE: List[Tuple[str, Callable[[Record], Optional[str]], Callable[[Dict[str, Any]], bool]]] = [
    ("sentence level changed", dmg_level, lambda s: s["voice_violations_by_feature"].get("level", 0) > 0),
    ("ending style flattened (거든요/더라고요 -> 습니다)", dmg_ending, lambda s: s["voice_violations_by_feature"].get("ending", 0) > 0),
    ("first-person marker dropped", dmg_persona, lambda s: s["voice_violations_by_feature"].get("persona", 0) > 0),
    ("honorific -시- dropped", dmg_honorific, lambda s: s["voice_violations_by_feature"].get("honorific", 0) > 0),
    ("meaning flip (regex tier)", dmg_meaning, lambda s: s["invariants_violated"] > 0),
    ("explicit CTA replaced", dmg_cta,
     lambda s: any(c["weakened"] or not c["present"] for c in s["cta"] if c["cta_class"] == "explicit")),
    ("collateral edit in a clean sentence", dmg_collateral, lambda s: s["clean_sentences_touched"] > 0),
    ("colloquial spelling corrected / CMC token stripped (default config)", dmg_colloquial,
     lambda s: s["protected_tokens_changed"] > 0),
]


# ASCII names for the damage labels, for metrics files (a metrics record carries no Korean).
SLUGS = {"sentence level changed": "level", "ending style flattened (거든요/더라고요 -> 습니다)": "ending",
         "first-person marker dropped": "persona", "honorific -시- dropped": "honorific",
         "meaning flip (regex tier)": "meaning", "explicit CTA replaced": "cta",
         "collateral edit in a clean sentence": "collateral",
         "colloquial spelling corrected / CMC token stripped (default config)": "protected_token"}
