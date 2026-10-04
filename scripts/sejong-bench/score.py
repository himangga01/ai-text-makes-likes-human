"""Independent Tier-1 scorer for the Super Sejong v2 seed benchmark (WP-15a).

Port and tidy-up of T7_score.py (docs/research/super-sejong/v2/prototypes/). It scores one writer
output against one seed record with deterministic checks only: no model call, no judge, and NO
engine code, so it stays an independent judge (DESIGN.md 7.1; T7 section 3.1). Nothing in an
engine's own gate is ever an outcome here.

What one record is scored on (all numbers are counts; see README.md):
  repair      per injection, FIXED_EXACT / FIXED_PROBABLE / REWRITTEN_ADJUDICATE / UNFIXED / DELETED;
              the headline is on "primary" injections only (high confidence, not genre-dependent,
              not an LLM tell, and the gold fix leaves the sentence's voice unchanged)
  collateral  sentences without an injection that the writer touched (over-editing)
  voice       per aligned sentence: level, ending class, honorifics, humble forms, first person;
              never a document register (OD 1). Sentences whose gold fix itself changes voice
              (사물 존칭 -시- removal, 하실게요 -> 해 주세요) are exempt and counted apart (OD 4)
  tokens      colloquial 할께-type spellings and CMC tokens (ㅋㅋ ㅎㅎ ㅠㅠ ^^ ~) are kept by default;
              changing one is over-editing (OD 2). The opt-in `fix_colloquial_spelling` config scores
              the opposite expectation on the same items
  quotes      quotations must stay verbatim
  cta         presence and force of each explicit CTA, invented CTA sentences in CTA-free items
  meaning     the regex tier of the item's invariants (require_all / forbid_any); the stronger tiers
              (Kiwi audit, LLM judges, humans) are separate and not implemented here
  numbers     digit tokens dropped or added anywhere (a cheap guard that also works on text without
              a ledger, such as a real draft)

CLI (run with the product Python; Kiwi is used only if importable):
  score.py selftest [--write] [--backend auto|on|off]
  score.py score --outputs OUT.jsonl --tag TAG [--arm ARM] [--include-composites] [--fix-colloquial]
  score.py natural (--source F --output F | --manifest M.jsonl) --tag TAG
  score.py hashes
See README.md. Metrics go to $BENCH only (bench_io.py) and contain ids, hashes and counts only.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_io  # noqa: E402
from bench_text import align, dice, sentences  # noqa: E402
import voicefeat  # noqa: E402
from voicefeat import CMC, diff_features, voice_profile  # noqa: E402

NUM = re.compile(r"\d[\d,.]*")
SEED_REL = ("docs", "research", "super-sejong", "v2", "benchmark")
PROBABLE_DICE = 0.6  # FIXED_PROBABLE needs Dice >= this against the gold sentence

# The 할께 family: a syllable with final ㄹ + 께 (+ 요) as a whole word. Deliberate colloquial
# spelling that OD 2 keeps by default.
_RIEUL = "".join(chr(0xAC00 + (initial * 21 + vowel) * 28 + 8) for initial in range(19) for vowel in range(21))
COLLOQUIAL_LGGE = re.compile(rf"(?<![가-힣])[가-힣]*[{_RIEUL}]께요?(?![가-힣])")


# ------------------------------------------------------------------------------------------------
# CTA force heuristic
# ------------------------------------------------------------------------------------------------
def force_of(sentence: str) -> int:
    """Heuristic CTA force 0-4 from the sentence tail.

    Written by T7 after reading the seed's CTA ledger (it agrees with it on 49/50 CTAs, so that is
    not an accuracy estimate). It is a stand-in, not the engine's detector: engine code cannot be
    imported here. 0 = no call to action (greeting formulas included).
    """
    s = sentence
    base = 0
    if s.strip().rstrip(".!") in ("안녕하세요", "수고하세요", "감사합니다"):
        return 0
    if s.rstrip().endswith("?"):
        return 1 if re.search(r"(하세요|해 주|알려|말씀)", s) else 0
    if re.search(r"([가-힣] 보(세요|시기 바랍니다|시길 바랍니다)|추천(합니다|해요|드려요)|편이 (좋|안전))", s):
        base = 2
    elif re.search(r"(주세요|주십시오|주시기 바랍니다|주시길 바랍니다|주시면|부탁|바랍니다|하실게요|하시기 바랍니다|바라겠습니다)", s):
        base = 3
    elif re.search(r"(해야 (합니다|해요|한다)|하여야 (합니다|한다|하겠습니다)|하셔야 합니다|하십시오|하세요|(?<!주)세요|지켜 주)", s):
        base = 4
    if base and base < 4 and re.search(r"(꼭|반드시|지금 바로|서둘러|즉시)", s):
        base += 1
    return base


# ------------------------------------------------------------------------------------------------
# seed data
# ------------------------------------------------------------------------------------------------
def seed_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    environ = os.environ if env is None else env
    override = environ.get("SEJONG_BENCH_SEED_DIR")
    return Path(override) if override else bench_io.repo_root().joinpath(*SEED_REL)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_seed(directory: Optional[Path] = None, composites: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """(records, hashes). Items first; the six composite documents only when asked for."""
    base = Path(directory) if directory else seed_dir()
    records = _read_jsonl(base / "seed_benchmark.jsonl")
    hashes = {"seed_benchmark": bench_io.sha256_file(base / "seed_benchmark.jsonl"),
              "seed_schema": bench_io.sha256_file(base / "seed_schema.json")}
    comp_path = base / "seed_composites.jsonl"
    if comp_path.exists():
        hashes["seed_composites"] = bench_io.sha256_file(comp_path)
        if composites:
            records += _read_jsonl(comp_path)
    return records, hashes


def validate_seed(records: List[Dict[str, Any]], directory: Optional[Path] = None) -> List[str]:
    """Problems of the seed records against seed_schema.json ([] = valid).

    Full JSON Schema validation when `jsonschema` is importable, otherwise the schema's
    top-level `required` keys only."""
    base = Path(directory) if directory else seed_dir()
    schema = json.loads((base / "seed_schema.json").read_text(encoding="utf-8"))
    problems: List[str] = []
    try:
        import jsonschema  # type: ignore
    except Exception:
        jsonschema = None
    validator = jsonschema.Draft202012Validator(schema) if jsonschema is not None else None
    for rec in records:
        if validator is not None:
            for err in validator.iter_errors(rec):
                problems.append(f"{rec.get('id')}: {'/'.join(str(p) for p in err.path)}: {err.validator}")
        else:
            problems += [f"{rec.get('id')}: missing {k}" for k in schema.get("required", []) if k not in rec]
    return problems


# ------------------------------------------------------------------------------------------------
# scoring one record
# ------------------------------------------------------------------------------------------------
def _number_tokens(text: str) -> "collections.Counter[str]":
    return collections.Counter(tok.rstrip(".,") for tok in NUM.findall(text) if tok.rstrip(".,"))


def _locate(S: List[Tuple[int, int, str]]):
    starts = [a for a, _, _ in S]
    ends = [b for _, b, _ in S]

    def sentence_index(pos: int) -> Optional[int]:
        k = bisect.bisect_right(starts, pos) - 1
        return k if k >= 0 and pos < ends[k] else None
    return sentence_index


def _score_repairs(rec, text, S, G, O, al, sentence_index):
    src = [t for _, _, t in S]
    oth = [t for _, _, t in O]
    gld = [t for _, _, t in G]
    spans, inj_sent = [], set()
    for inj in rec["injections"]:
        k = sentence_index(inj["span"][0])
        inj_sent.add(k)
        status = "DELETED"
        if k is not None and al[k] is not None:
            o = oth[al[k]]
            g = gld[k] if k < len(gld) and len(gld) == len(src) else None
            exact = g is not None and o.strip() == g.strip()
            for acc in inj["acceptable_fixes"]:
                a_, b_ = inj["span"]
                if acc.endswith("."):  # an acceptable fix that is a whole replacement sentence
                    alt = acc
                else:
                    sa, sb, _ = S[k]
                    alt = text[sa:a_] + acc + text[b_:sb]
                if o.strip() == alt.strip():
                    exact = True
            if exact:
                status = "FIXED_EXACT"
            elif re.search(inj["defect_regex"], o):
                status = "UNFIXED"
            elif g is not None and dice(o, g) >= PROBABLE_DICE:
                status = "FIXED_PROBABLE"
            else:
                status = "REWRITTEN_ADJUDICATE"
        spans.append({"id": inj["id"], "category": inj["category"], "primary": bool(inj["primary"]), "status": status})
    return spans, inj_sent


def _score_voice(rec, text, out, al, sentence_index):
    vp, ovp = voice_profile(text), voice_profile(out)
    exempt = {sentence_index(inj["span"][0]) for inj in rec["injections"] if inj.get("voice_effect")}
    comparable = violations = 0
    per: "collections.Counter[str]" = collections.Counter()
    for k, sv in enumerate(vp):
        if sv["kind"] != "prose" or sv["level"] == "quote_only" or k >= len(al):
            continue
        j = al[k]
        if j is None or j >= len(ovp):
            continue
        if k in exempt:
            per["exempt_voice_conflicting_fix"] += 1
            continue
        comparable += 1
        diffs = diff_features(sv["features"], ovp[j]["features"])
        if diffs:
            violations += 1
            per.update(diffs)
    return comparable, violations, dict(per)


def _score_tokens(rec, text, out, fix_colloquial):
    qspans = [p["span"] for p in rec["protected_spans"]]
    changed = fixed = 0
    for pt in rec["protected_tokens"]:
        first = pt["spans"][0] if pt["spans"] else None
        in_quote = bool(first) and any(a <= first[0] and first[1] <= b for a, b in qspans)
        lost = max(0, text.count(pt["text"]) - out.count(pt["text"]))
        optin = fix_colloquial and pt["kind"] == "colloquial_spelling" and pt["optional_fix"] and not in_quote
        if optin and pt["optional_fix"]["gold_fix"] in out and pt["text"] not in out:
            fixed += 1
        elif lost:
            changed += 1  # kept-by-default token altered or removed (under opt-in: removed without the fix)
    quotes = [text[p["span"][0]:p["span"][1]] for p in rec["protected_spans"]]
    return {"protected_tokens": len(rec["protected_tokens"]), "protected_tokens_changed": changed,
            "optin_colloquial_fixed": fixed, "quotes": len(quotes),
            "quotes_changed": sum(1 for q in quotes if q not in out)}


def _score_cta(rec, src, oth, al, sentence_index):
    ctas = []
    for c in rec["cta"]:
        k = sentence_index(c["span"][0])
        o = oth[al[k]] if k is not None and al[k] is not None else None
        f_out = force_of(o) if o else 0
        ctas.append({"id": c["id"], "cta_class": c["cta_class"], "force_gold": c["force"], "force_out": f_out,
                     "present": bool(o) and f_out > 0, "weakened": bool(o) and 0 < f_out < c["force"],
                     "strengthened": bool(o) and f_out > c["force"]})
    invented = 0
    if not rec["cta"] and rec["item_type"] != "composite_document":
        matched = {al[i] for i, s in enumerate(src) if al[i] is not None and force_of(s) > 0}
        invented = sum(1 for k, s in enumerate(oth) if force_of(s) > 0 and k not in matched)
    return ctas, invented


def _score_invariants(rec, out):
    bad = []
    for m in rec["meaning_invariants"]:
        if any(not re.search(x, out) for x in m["require_all"]) or any(re.search(x, out) for x in m["forbid_any"]):
            bad.append(m["id"])
    return len(rec["meaning_invariants"]), bad


def score_item(rec: Dict[str, Any], out: str, opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Metrics of one writer output `out` for seed record `rec`. opts: {"fix_colloquial_spelling": bool}
    (default False: colloquial spellings and CMC tokens are protected). Returns counts, ids and enum
    names only; the item text and the output text are not part of the result."""
    opts = opts or {}
    fix_colloquial = bool(opts.get("fix_colloquial_spelling"))
    text, gold = rec["text"], rec["gold_text"]
    if fix_colloquial and rec.get("gold_text_optin_colloquial_fix"):
        gold = rec["gold_text_optin_colloquial_fix"]
    S, skind = sentences(text)
    G, _ = sentences(gold)
    O, _ = sentences(out)
    src = [t for _, _, t in S]
    oth = [t for _, _, t in O]
    al = align(src, oth)
    sentence_index = _locate(S)
    res: Dict[str, Any] = {"id": rec["id"], "changed": out != text, "sentences": len(src),
                           "unaligned_source_sentences": sum(1 for a in al if a is None), "output_sentences": len(oth)}
    res["spans"], inj_sent = _score_repairs(rec, text, S, G, O, al, sentence_index)
    # collateral: prose sentences that carry no injection but were rewritten, split away or dropped
    clean = [k for k in range(len(src)) if k not in inj_sent and skind[k] == "prose"]
    touched = [k for k in clean if al[k] is None or oth[al[k]].strip() != src[k].strip()]
    res["clean_sentences"] = len(clean)
    res["clean_sentences_touched"] = len(touched)
    res["touched_sentence_index"] = touched
    res["voice_comparable"], res["voice_violations"], res["voice_violations_by_feature"] = _score_voice(rec, text, out, al, sentence_index)
    res.update(_score_tokens(rec, text, out, fix_colloquial))
    res["cta"], res["cta_invented_sentences"] = _score_cta(rec, src, oth, al, sentence_index)
    res["invariants"], bad = _score_invariants(rec, out)
    res["invariants_violated"] = len(bad)
    res["invariants_violated_ids"] = bad
    before, after = _number_tokens(text), _number_tokens(out)
    res["numbers_dropped"] = sum((before - after).values())
    res["numbers_added"] = sum((after - before).values())
    return res


# ------------------------------------------------------------------------------------------------
# natural text (a real draft): no injections, no gold, the source is the gold
# ------------------------------------------------------------------------------------------------
def natural_record(text: str, doc_id: str) -> Dict[str, Any]:
    """A pseudo seed record for text that has no ledger (an owner draft, an already-processed post).

    Every prose sentence is a clean sentence; quotations, CMC tokens and 할께-type spellings found
    in the source become protected spans/tokens; every sentence with a CTA force > 0 becomes an
    explicit CTA. The record is built in memory and is not persisted.
    """
    S, _ = sentences(text)
    vp = voice_profile(text)
    quotes = [{"span": q["span"], "reason": "quotation"} for s in vp for q in s["quotes"]]
    tokens: List[Dict[str, Any]] = []
    by_token: Dict[str, List[List[int]]] = collections.OrderedDict()
    for m in CMC.finditer(text):
        by_token.setdefault(m.group(0), []).append([m.start(), m.end()])
    for n, (tok, spans) in enumerate(by_token.items(), 1):
        tokens.append({"id": f"k{n}", "kind": "cmc", "text": tok, "spans": spans, "optional_fix": None})
    colloquial: Dict[str, List[List[int]]] = collections.OrderedDict()
    for m in COLLOQUIAL_LGGE.finditer(text):
        colloquial.setdefault(m.group(0), []).append([m.start(), m.end()])
    for n, (tok, spans) in enumerate(colloquial.items(), len(tokens) + 1):
        fixed = tok[:-2] + "게요" if tok.endswith("께요") else tok[:-1] + "게"
        tokens.append({"id": f"k{n}", "kind": "colloquial_spelling", "text": tok, "spans": spans,
                       "optional_fix": {"option": "fix_colloquial_spelling", "gold_fix": fixed}})
    ctas = []
    for a, b, sentence in S:
        f = force_of(sentence)
        if f > 0:
            ctas.append({"id": f"c{len(ctas) + 1}", "span": [a, b], "force": f, "cta_class": "explicit"})
    return {"id": doc_id, "key": doc_id, "family": doc_id, "item_type": "natural_draft", "genre": "unknown",
            "voice_stratum": "unknown", "text": text, "gold_text": text, "gold_text_optin_colloquial_fix": None,
            "expect_edit": False, "injections": [], "protected_spans": quotes, "protected_tokens": tokens,
            "cta": ctas, "meaning_invariants": [], "probes": []}


def score_natural(source: str, output: str, doc_id: str, opts: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(record, metrics) for an output rewritten from `source` (read-only text, never stored)."""
    rec = natural_record(source, doc_id)
    metrics = score_item(rec, output, opts)
    S, _ = sentences(source)
    metrics["touched_offsets"] = [[S[k][0], S[k][1]] for k in metrics["touched_sentence_index"]]
    return rec, metrics


# ------------------------------------------------------------------------------------------------
# aggregation
# ------------------------------------------------------------------------------------------------
PRIMARY_FIXED = ("FIXED_EXACT", "FIXED_PROBABLE")


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Totals over score_item results (the figures of T7's self-test lines)."""
    spans = [s for r in rows for s in r["spans"]]
    primary = [s for s in spans if s["primary"]]
    ctas = [c for r in rows for c in r["cta"] if c["cta_class"] == "explicit"]
    voice: "collections.Counter[str]" = collections.Counter()
    for r in rows:
        voice.update(r["voice_violations_by_feature"])

    def total(key: str) -> int:
        return sum(r[key] for r in rows)
    return {
        "items": len(rows), "spans": len(spans), "span_status": dict(collections.Counter(s["status"] for s in spans)),
        "primary": len(primary), "primary_status": dict(collections.Counter(s["status"] for s in primary)),
        "primary_fixed": sum(s["status"] in PRIMARY_FIXED for s in primary),
        "changed_outputs": sum(1 for r in rows if r["changed"]),
        "clean_sentences": total("clean_sentences"), "clean_sentences_touched": total("clean_sentences_touched"),
        "voice_comparable": total("voice_comparable"), "voice_violations": total("voice_violations"),
        "voice_by_feature": dict(voice),
        "quotes": total("quotes"), "quotes_changed": total("quotes_changed"),
        "protected_tokens": total("protected_tokens"), "protected_tokens_changed": total("protected_tokens_changed"),
        "optin_colloquial_fixed": total("optin_colloquial_fixed"),
        "cta_explicit": len(ctas), "cta_present": sum(c["present"] for c in ctas),
        "cta_weakened": sum(c["weakened"] for c in ctas), "cta_strengthened": sum(c["strengthened"] for c in ctas),
        "cta_invented_sentences": total("cta_invented_sentences"),
        "invariants": total("invariants"), "invariants_violated": total("invariants_violated"),
        "numbers_dropped": total("numbers_dropped"), "numbers_added": total("numbers_added"),
        "unaligned_source_sentences": total("unaligned_source_sentences"),
    }


def aggregate_by(rows: List[Dict[str, Any]], records: Dict[str, Dict[str, Any]], field: str) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = collections.OrderedDict()
    for r in rows:
        groups.setdefault(str(records[r["id"]].get(field)), []).append(r)
    return {name: aggregate(group) for name, group in sorted(groups.items())}


def over_editing(rows: List[Dict[str, Any]], records: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Over-editing on records that should come back unchanged (natural controls, voice traps, CTA-free
    items with no injection): how many outputs changed at all, how many clean sentences were touched."""
    keep = [r for r in rows if not records[r["id"]]["injections"]]
    return {"records": len(keep), "changed": sum(1 for r in keep if r["changed"]),
            "clean_sentences": sum(r["clean_sentences"] for r in keep),
            "clean_sentences_touched": sum(r["clean_sentences_touched"] for r in keep),
            "protected_tokens_changed": sum(r["protected_tokens_changed"] for r in keep),
            "quotes_changed": sum(r["quotes_changed"] for r in keep),
            "voice_violations": sum(r["voice_violations"] for r in keep)}


# ------------------------------------------------------------------------------------------------
# metrics records (ids, hashes, counts only)
# ------------------------------------------------------------------------------------------------
def metrics_record(rec: Dict[str, Any], scored: Dict[str, Any], out: str, *, tag: str, arm: Optional[str] = None,
                   opts: Optional[Dict[str, Any]] = None, scorer: Optional[str] = None) -> Dict[str, Any]:
    """One JSONL line: identity, hashes and the counts of score_item. No text, by construction and by
    bench_io.check_metrics_record (which rejects any string that is not short printable ASCII)."""
    record: Dict[str, Any] = {
        "schema": bench_io.METRICS_SCHEMA, "tag": bench_io.check_label(tag, "tag"),
        "id": rec["id"], "key": rec.get("key"), "item_type": rec.get("item_type"), "genre": rec.get("genre"),
        "voice_stratum": rec.get("voice_stratum"), "family": rec.get("family"),
        "config": {"fix_colloquial_spelling": bool((opts or {}).get("fix_colloquial_spelling"))},
        "voice_backend": voicefeat.backend_name(), "scorer": (scorer or bench_io.scorer_sha256())[:16],
        "sha256": {"input": bench_io.sha256_text(rec["text"]), "output": bench_io.sha256_text(out),
                   "gold": bench_io.sha256_text(rec["gold_text"])},
        "chars": {"input": len(rec["text"]), "output": len(out)},
    }
    if arm is not None:
        record["arm"] = bench_io.check_label(arm, "arm")
    record.update({k: v for k, v in scored.items() if k != "id"})
    return record


def summary_record(rows: List[Dict[str, Any]], records: Dict[str, Dict[str, Any]], *, tag: str, arm: Optional[str],
                   opts: Optional[Dict[str, Any]], hashes: Dict[str, str], missing: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "schema": bench_io.SUMMARY_SCHEMA, "tag": tag, "arm": arm,
        "config": {"fix_colloquial_spelling": bool((opts or {}).get("fix_colloquial_spelling"))},
        "voice_backend": voicefeat.backend_name(), "scorer": bench_io.scorer_sha256(), "seed": hashes,
        "records_scored": len(rows), "records_without_output": missing,
        "total": aggregate(rows), "over_editing": over_editing(rows, records),
        "by_item_type": aggregate_by(rows, records, "item_type"),
        "by_genre": aggregate_by(rows, records, "genre"),
    }
    return out


# ------------------------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------------------------
def _cmd_score(args: argparse.Namespace) -> int:
    opts = {"fix_colloquial_spelling": args.fix_colloquial}
    records, hashes = load_seed(Path(args.seed_dir) if args.seed_dir else None, args.include_composites)
    by_id = {r["id"]: r for r in records}
    outputs: Dict[str, str] = {}
    outputs_path = bench_io.require_outside_repo(args.outputs, "--outputs")
    with open(outputs_path, encoding="utf-8") as handle:  # read-only; this file is the writer's text
        for line in handle:
            if line.strip():
                row = json.loads(line)
                outputs[row["id"]] = row["output"]
    unknown = sorted(set(outputs) - set(by_id))
    if unknown:
        print(f"error: {len(unknown)} output id(s) are not seed ids (first: {unknown[0]})", file=sys.stderr)
        return 2
    rows, lines = [], []
    scorer = bench_io.scorer_sha256()
    for rec in records:
        if rec["id"] in outputs:
            scored = score_item(rec, outputs[rec["id"]], opts)
            rows.append(scored)
            lines.append(metrics_record(rec, scored, outputs[rec["id"]], tag=args.tag, arm=args.arm, opts=opts, scorer=scorer))
    missing = len(records) - len(rows)
    summary = summary_record(rows, by_id, tag=args.tag, arm=args.arm, opts=opts, hashes=hashes, missing=missing)
    path = bench_io.write_metrics_jsonl(f"metrics/{args.tag}.jsonl", lines)
    bench_io.write_metrics_json(f"metrics/{args.tag}.summary.json", summary)
    print(f"scored {len(rows)} record(s), {missing} without output; metrics: {path}")
    return 0


def _cmd_natural(args: argparse.Namespace) -> int:
    opts = {"fix_colloquial_spelling": args.fix_colloquial}
    pairs: List[Tuple[Optional[str], str, str]] = []
    if args.manifest:
        for row in _read_jsonl(Path(args.manifest)):
            pairs.append((row.get("id"), row["source"], row["output"]))
    elif args.source and args.output:
        pairs.append((args.id, args.source, args.output))
    else:
        print("error: give --source and --output, or --manifest", file=sys.stderr)
        return 2
    lines, rows, recs = [], [], {}
    scorer = bench_io.scorer_sha256()
    for doc_id, src_path, out_path in pairs:
        src_path = bench_io.require_outside_repo(src_path, "a draft source")
        out_path = bench_io.require_outside_repo(out_path, "a draft output")
        with open(src_path, encoding="utf-8", newline="") as handle:  # read-only; bodies stay in memory
            source = handle.read()
        with open(out_path, encoding="utf-8", newline="") as handle:
            output = handle.read()
        doc_id = doc_id or "N-" + bench_io.sha256_text(source)[:12]
        rec, scored = score_natural(source, output, doc_id, opts)
        recs[doc_id] = rec
        rows.append(scored)
        lines.append(metrics_record(rec, scored, output, tag=args.tag, arm=args.arm, opts=opts, scorer=scorer))
    summary = summary_record(rows, recs, tag=args.tag, arm=args.arm, opts=opts, hashes={}, missing=0)
    path = bench_io.write_metrics_jsonl(f"metrics/{args.tag}.jsonl", lines)
    bench_io.write_metrics_json(f"metrics/{args.tag}.summary.json", summary)
    print(f"scored {len(rows)} draft(s); metrics: {path}")
    return 0


def _cmd_hashes(_: argparse.Namespace) -> int:
    records, hashes = load_seed()
    out = {"scorer": bench_io.scorer_sha256(), "voice_backend": voicefeat.backend_name(),
           "files": {p.name: bench_io.sha256_file(p) for p in bench_io.scorer_files()}, "seed": hashes}
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="score.py", description="Independent scorer for the Super Sejong v2 seed benchmark.")
    ap.add_argument("--backend", choices=["auto", "on", "off"], default=None,
                    help="voice backend: Kiwi if importable (auto), required (on) or regex only (off); default $SEJONG_BENCH_KIWI or auto")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("score", help="score writer outputs against the seed set")
    p.add_argument("--outputs", required=True, help="JSONL of {\"id\": seed id, \"output\": text}; read only")
    p.add_argument("--tag", required=True)
    p.add_argument("--arm")
    p.add_argument("--seed-dir")
    p.add_argument("--include-composites", action="store_true")
    p.add_argument("--fix-colloquial", action="store_true", help="opt-in config: the 할께 family is fixed, not kept")
    p.set_defaults(func=_cmd_score)
    p = sub.add_parser("natural", help="score rewrites of real text that has no gold (hashes and counts only)")
    p.add_argument("--source")
    p.add_argument("--output")
    p.add_argument("--id")
    p.add_argument("--manifest", help="JSONL of {\"id\", \"source\": path, \"output\": path}")
    p.add_argument("--tag", required=True)
    p.add_argument("--arm")
    p.add_argument("--fix-colloquial", action="store_true")
    p.set_defaults(func=_cmd_natural)
    p = sub.add_parser("hashes", help="print the scorer and seed hashes to pin")
    p.set_defaults(func=_cmd_hashes)
    p = sub.add_parser("selftest", help="metamorphic self-test (identity, gold and damaged writers)")
    p.add_argument("--write", action="store_true", help="also write the aggregate result to $BENCH/selftest/")
    p.set_defaults(func=None)
    args = ap.parse_args(argv)
    if args.backend:
        voicefeat.set_backend(args.backend)
    try:
        if args.cmd == "selftest":
            import selftest
            return selftest.run(write=args.write)
        return args.func(args)
    except bench_io.BenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
