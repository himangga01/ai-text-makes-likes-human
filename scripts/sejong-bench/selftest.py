"""Metamorphic self-test of the scorer and the seed set (WP-15a). No model call, no engine code.

Reproduces T7 section 7 (docs/research/super-sejong/v2/tracks/T7.md): five writers (identity, gold,
gold with the opt-in colloquial fix scored in both configurations, gold scored with the option on)
and the damage-detection table. EXPECTED holds T7's numbers; run() fails (exit 1) on any
difference. The numbers were measured by T7 with Kiwi; this port reproduces them with Kiwi and with
the regex backend (the backend name is printed, and tests pin both).

Beyond T7 it also checks what this port added: the six composite documents (identity and gold),
natural-text mode on the seed texts (identity must be clean, the same damages must be caught),
banded against full alignment, the metrics no-text guard, and the seed against seed_schema.json.

  python3 scripts/sejong-bench/selftest.py [--write]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_io  # noqa: E402
import damage  # noqa: E402
import score  # noqa: E402
import voicefeat  # noqa: E402
from bench_text import sentences  # noqa: E402

# T7 section 7 (results_selftest.txt). Voice counts include the exempt voice-conflicting fixes (7 items).
_IDENTITY = {"items": 206, "spans": 142, "span_status": {"UNFIXED": 142}, "primary": 92, "primary_fixed": 0,
             "changed_outputs": 0, "clean_sentences": 438, "clean_sentences_touched": 0,
             "voice_comparable": 571, "voice_violations": 0, "voice_by_feature": {"exempt_voice_conflicting_fix": 7},
             "quotes": 21, "quotes_changed": 0, "protected_tokens": 28, "protected_tokens_changed": 0,
             "optin_colloquial_fixed": 0, "cta_explicit": 46, "cta_present": 46, "cta_weakened": 0,
             "cta_invented_sentences": 0, "invariants": 40, "invariants_violated": 0}
_GOLD = dict(_IDENTITY, span_status={"FIXED_EXACT": 142}, primary_fixed=92, changed_outputs=115)
EXPECTED_ARMS: Dict[str, Dict[str, Any]] = {
    "identity writer, default config": _IDENTITY,
    "gold writer, default config": _GOLD,
    "gold writer + opt-in colloquial fix, scored in default config (should be over-editing)": dict(
        _GOLD, changed_outputs=125, clean_sentences_touched=10, quotes_changed=1, protected_tokens_changed=10),
    "gold writer + opt-in colloquial fix, scored with option ON": dict(
        _GOLD, changed_outputs=125, clean_sentences_touched=10, quotes_changed=1, protected_tokens_changed=1,
        optin_colloquial_fixed=9),
    "gold writer (no colloquial fix), scored with option ON (should miss the opt-in fixes)": dict(_GOLD),
}
# label -> (applicable items, detected, undetected keys); T7 section 7 damage table.
EXPECTED_DAMAGE: Dict[str, Tuple[int, int, List[str]]] = {
    "sentence level changed": (140, 134, ["J60", "J61", "J62", "J64", "A10", "V11"]),
    "ending style flattened (거든요/더라고요 -> 습니다)": (11, 11, []),
    "first-person marker dropped": (17, 17, []),
    "honorific -시- dropped": (3, 3, []),
    "meaning flip (regex tier)": (22, 20, ["T07", "T09"]),
    "explicit CTA replaced": (35, 35, []),
    "collateral edit in a clean sentence": (202, 202, []),
    "colloquial spelling corrected / CMC token stripped (default config)": (14, 14, []),
}
ARM_SLUGS = ["identity", "gold", "gold_optin_scored_default", "gold_optin_scored_optin", "gold_scored_optin"]  # for metrics files
EXPECTED_FORCE = (49, 50, [("A28", 2, 3)])  # force_of vs the hand-labelled ledger (not an accuracy estimate)
OPTIN = {"fix_colloquial_spelling": True}
_COMPARED = ("items", "spans", "span_status", "primary", "primary_fixed", "changed_outputs", "clean_sentences",
             "clean_sentences_touched", "voice_comparable", "voice_violations", "voice_by_feature", "quotes",
             "quotes_changed", "protected_tokens", "protected_tokens_changed", "optin_colloquial_fixed",
             "cta_explicit", "cta_present", "cta_weakened", "cta_invented_sentences", "invariants", "invariants_violated")


def seed_items(directory: Optional[Path] = None) -> List[Dict[str, Any]]:
    records, _ = score.load_seed(directory)
    return [r for r in records if r["item_type"] != "composite_document"]


def run_arms(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    def arm(output, opts=None):
        return score.aggregate([score.score_item(r, output(r), opts) for r in items])
    optin_text = lambda r: r["gold_text_optin_colloquial_fix"] or r["gold_text"]  # noqa: E731
    return {
        "identity writer, default config": arm(lambda r: r["text"]),
        "gold writer, default config": arm(lambda r: r["gold_text"]),
        "gold writer + opt-in colloquial fix, scored in default config (should be over-editing)": arm(optin_text),
        "gold writer + opt-in colloquial fix, scored with option ON": arm(optin_text, OPTIN),
        "gold writer (no colloquial fix), scored with option ON (should miss the opt-in fixes)": arm(lambda r: r["gold_text"], OPTIN),
    }


def run_damage(items: List[Dict[str, Any]]) -> Dict[str, Tuple[int, int, List[str]]]:
    table: Dict[str, Tuple[int, int, List[str]]] = {}
    for label, writer, detected in damage.DAMAGE:
        n, hit, miss = 0, 0, []
        for rec in items:
            output = writer(rec)
            if output is None:
                continue
            n += 1
            if detected(score.score_item(rec, output)):
                hit += 1
            else:
                miss.append(rec["key"])
        table[label] = (n, hit, miss)
    return table


def force_agreement(items: List[Dict[str, Any]]) -> Tuple[int, int, List[Tuple[str, int, int]]]:
    agree = total = 0
    mismatches: List[Tuple[str, int, int]] = []
    for rec in items:
        S, _ = sentences(rec["text"])
        for c in rec["cta"]:
            k = next(i for i, (a, b, _) in enumerate(S) if a <= c["span"][0] < b)
            f = score.force_of(S[k][2])
            total += 1
            agree += f == c["force"]
            if f != c["force"]:
                mismatches.append((rec["key"], c["force"], f))
    return agree, total, mismatches


def compare(arms, table, force) -> List[str]:
    """Differences from T7's numbers, as short messages ([] = reproduced exactly)."""
    problems: List[str] = []
    for name, expected in EXPECTED_ARMS.items():
        got = arms[name]
        for key in _COMPARED:
            if got[key] != expected[key]:
                problems.append(f"[{name}] {key}: expected {expected[key]!r}, got {got[key]!r}")
    for label, (n, hit, miss) in EXPECTED_DAMAGE.items():
        if table[label] != (n, hit, miss):
            problems.append(f"[damage: {label}] expected {(n, hit, miss)!r}, got {table[label]!r}")
    if force != EXPECTED_FORCE:
        problems.append(f"force_of vs ledger: expected {EXPECTED_FORCE!r}, got {force!r}")
    return problems


# ---- what the port added beyond T7 -------------------------------------------------------------
# composite id -> (injections, primary injections, explicit CTAs); counted from seed_composites.jsonl.
EXPECTED_COMPOSITES = {"SSB-D01": (21, 16, 16), "SSB-D02": (22, 13, 10), "SSB-D03": (24, 16, 0),
                       "SSB-D04": (15, 13, 9), "SSB-D05": (15, 11, 29), "SSB-D06": (142, 92, 46)}
# natural-text mode on the 206 seed texts (the text is its own gold): damage -> (applicable, detected).
EXPECTED_NATURAL = {"sentence level changed": (140, 140), "ending style flattened (거든요/더라고요 -> 습니다)": (11, 11),
                    "first-person marker dropped": (17, 17), "honorific -시- dropped": (3, 3),
                    "meaning flip (regex tier)": (0, 0), "explicit CTA replaced": (40, 40),
                    "collateral edit in a clean sentence": (205, 205),
                    "colloquial spelling corrected / CMC token stripped (default config)": (15, 15)}


def run_composites(directory: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    records, _ = score.load_seed(directory, composites=True)
    result: Dict[str, Dict[str, Any]] = {}
    for rec in (r for r in records if r["item_type"] == "composite_document"):
        identity = score.aggregate([score.score_item(rec, rec["text"])])
        gold = score.aggregate([score.score_item(rec, rec["gold_text"])])
        result[rec["id"]] = {"injections": gold["spans"], "primary": gold["primary"], "cta": gold["cta_explicit"],
                             "identity_fixed": identity["primary_fixed"], "gold_fixed": gold["primary_fixed"],
                             "gold_exact": gold["span_status"].get("FIXED_EXACT", 0),
                             "gold_dirty": gold["clean_sentences_touched"] + gold["voice_violations"] + gold["protected_tokens_changed"]
                             + gold["quotes_changed"] + gold["unaligned_source_sentences"] + gold["numbers_dropped"] + gold["numbers_added"],
                             "gold_cta_present": gold["cta_present"], "identity_changed": identity["changed_outputs"]}
    return result


def run_natural(items: List[Dict[str, Any]]) -> Tuple[int, Dict[str, Tuple[int, int]]]:
    """(records that were not clean under the identity writer, damage -> (applicable, detected))."""
    dirty = 0
    for rec in items:
        _, m = score.score_natural(rec["gold_text"], rec["gold_text"], "N-" + rec["key"])
        if (m["changed"] or m["clean_sentences_touched"] or m["voice_violations"] or m["protected_tokens_changed"]
                or m["quotes_changed"] or m["numbers_dropped"] or m["numbers_added"] or m["cta_invented_sentences"]
                or any(not c["present"] for c in m["cta"])):
            dirty += 1
    table: Dict[str, Tuple[int, int]] = {}
    for label, writer, detected in damage.DAMAGE:
        n = hit = 0
        for rec in items:
            natural = score.natural_record(rec["gold_text"], "N-" + rec["key"])
            output = writer(natural)
            if output is None:
                continue
            n += 1
            hit += bool(detected(score.score_item(natural, output)))
        table[label] = (n, hit)
    return dirty, table


def banded_matches_full(directory: Optional[Path] = None) -> List[str]:
    """Problems where the banded alignment differs from the full DP on the long composite document."""
    import bench_text
    records, _ = score.load_seed(directory, composites=True)
    rec = next(r for r in records if r["id"] == "SSB-D06")
    src = [t for _, _, t in sentences(rec["text"])[0]]
    half = len(src) // 2
    variants = {
        "identity": list(src),
        "gold": [t for _, _, t in sentences(rec["gold_text"])[0]],
        "first half dropped": src[half:],
        "every 7th dropped": [t for i, t in enumerate(src) if i % 7],
        "prefixed": [("물론 " + t if i % 5 == 0 else t) for i, t in enumerate(src)],
    }
    problems: List[str] = []
    saved = bench_text.FULL_DP_CELLS
    try:
        for name, out in variants.items():
            bench_text.FULL_DP_CELLS = 10 ** 9
            full = bench_text.align(src, out)
            bench_text.FULL_DP_CELLS = 0
            banded = bench_text.align(src, out)
            if full != banded:
                problems.append(f"banded alignment differs from the full DP: {name} ({sum(a != b for a, b in zip(full, banded))} of {len(src)})")
    finally:
        bench_text.FULL_DP_CELLS = saved
    return problems


def extra_problems(items: List[Dict[str, Any]], directory: Optional[Path] = None) -> List[str]:
    problems: List[str] = []
    for cid, row in run_composites(directory).items():
        inj, prim, cta = EXPECTED_COMPOSITES[cid]
        want = {"injections": inj, "primary": prim, "cta": cta, "identity_fixed": 0, "gold_fixed": prim, "gold_exact": inj,
                "gold_dirty": 0, "gold_cta_present": cta, "identity_changed": 0}
        if row != want:
            problems.append(f"[composite {cid}] expected {want!r}, got {row!r}")
    dirty, table = run_natural(items)
    if dirty:
        problems.append(f"[natural] {dirty} identity record(s) are not clean")
    if table != EXPECTED_NATURAL:
        problems.append(f"[natural damage] expected {EXPECTED_NATURAL!r}, got {table!r}")
    problems += banded_matches_full(directory)
    records, _ = score.load_seed(directory, composites=True)
    problems += [f"[seed schema] {p}" for p in score.validate_seed(records, directory)]
    return problems


def _line(name: str, a: Dict[str, Any]) -> str:
    return (f"[{name}] items={a['items']} spans={a['spans']} {a['span_status']} primary fixed {a['primary_fixed']}/{a['primary']}\n"
            f"   changed outputs {a['changed_outputs']}; clean sentences touched {a['clean_sentences_touched']}/{a['clean_sentences']}; "
            f"voice-violating sentences {a['voice_violations']}/{a['voice_comparable']} {a['voice_by_feature']}; "
            f"quotes changed {a['quotes_changed']}/{a['quotes']}; protected tokens changed {a['protected_tokens_changed']}/{a['protected_tokens']}; "
            f"opt-in colloquial fixed {a['optin_colloquial_fixed']}; CTA present {a['cta_present']}/{a['cta_explicit']} weakened {a['cta_weakened']}; "
            f"invented-CTA sentences {a['cta_invented_sentences']}; invariants violated {a['invariants_violated']}/{a['invariants']}")


def render(arms, table, force) -> str:
    lines = [f"voice backend: {voicefeat.backend_name()}"]
    lines += [_line(name, a) for name, a in arms.items()]
    agree, total, mismatches = force
    lines.append(f"force_of agrees with the hand-labelled ledger on {agree}/{total} CTAs (heuristic written after reading "
                 f"the ledger, so not an accuracy estimate); mismatches (key, ledger force, heuristic force): {mismatches}")
    for label, (n, hit, miss) in table.items():
        lines.append(f"[damage: {label}] applicable items {n}, detected {hit}; undetected: {miss}")
    return "\n".join(lines)


def run(write: bool = False, directory: Optional[Path] = None) -> int:
    items = seed_items(directory)
    arms, table, force = run_arms(items), run_damage(items), force_agreement(items)
    print(render(arms, table, force))
    problems = compare(arms, table, force)
    extras = extra_problems(items, directory)
    print(f"added checks (composites, natural mode, banded alignment, seed schema): {'ok' if not extras else str(len(extras)) + ' problem(s)'}")
    problems += extras
    if write:
        record = {"schema": bench_io.SUMMARY_SCHEMA, "tag": "selftest", "voice_backend": voicefeat.backend_name(),
                  "scorer": bench_io.scorer_sha256(), "reproduced": not problems,
                  "arms": dict(zip(ARM_SLUGS, arms.values())),
                  "damage": {damage.SLUGS[k]: {"applicable": v[0], "detected": v[1], "undetected": v[2]} for k, v in table.items()},
                  "force_agreement": {"agree": force[0], "total": force[1]}}
        print("written:", bench_io.write_metrics_json(f"selftest/selftest-{voicefeat.backend_name()}.json", record))
    if problems:
        print(f"\nSELF-TEST FAILED: {len(problems)} problem(s)", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    print("\nself-test: T7 section 7 reproduced exactly; added checks pass")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run(write="--write" in sys.argv[1:]))
    except bench_io.BenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
