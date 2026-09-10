"""Shared, deterministic portal/desktop/skill validation policy."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import math
from pathlib import Path
import sys

DEFAULT_VENDOR = Path(__file__).resolve().parent.parent / "vendor/humanize-engine"


def modules(vendor: Path):
    scripts = vendor.resolve() / "scripts"
    if not (scripts / "verify_gates.py").is_file():
        raise ValueError("Humanize runtime is missing")
    sys.path.insert(0, str(scripts))
    import verify_gates
    import checks
    import restore_modality
    import strip_injected_commas
    return verify_gates, checks, restore_modality, strip_injected_commas


def decision(exit_code: int, attempt: int) -> str:
    if exit_code == 3:
        return "error"
    if exit_code == 0:
        return "accept"
    if attempt == 1:
        return "retry"
    return "rollback" if exit_code == 2 else "accept-with-warning"


def warning_reasons(report: object, exit_code: int, stderr: str = "") -> dict:
    """Bounded evidence, never gate policy. Unknown/missing axes fail closed.

    No source, candidate, upstream messages or metric values cross this boundary.
    P4/P5 observations also block the optional style-only candidate review.
    """
    unknown = {"version": 1, "codes": ["UNKNOWN"]}
    expected = {"genre", "change_rate", "s1_targets", "antithesis", "golden",
                "sentence_touch", "numbers_dropped", "modality", "gate"}
    if stderr or not isinstance(report, dict) or set(report) != expected:
        return unknown
    reasons = []
    try:
        if report["gate"]["exit_code"] != exit_code:
            return unknown
        rate = report["change_rate"]["rate"]
        if type(rate) not in (int, float) or not math.isfinite(rate) or not 0 <= rate <= 1:
            return unknown
        # Use verdict as well as rounded rate; a rounded boundary must never
        # promote a candidate. Thresholds and upstream gate remain unchanged.
        if rate >= .3 or report["change_rate"]["verdict"] != "OK":
            reasons.append("P0_CHANGE_RATE")
        targets = report["s1_targets"]
        metrics = {"comma_inclusion_rate", "comma_usage_rate", "ending_comma_rate",
                   "comma_segment_length", "hanja_nominalizer_density"}
        if not isinstance(targets, list) or len(targets) > len(metrics):
            return unknown
        seen = set()
        for target in targets:
            if not isinstance(target, dict) or set(target) != {"metric", "z_before", "z_after", "verdict"}:
                return unknown
            metric = target["metric"]
            if metric not in metrics or metric in seen:
                return unknown
            seen.add(metric)
            if any(type(target[key]) not in (int, float) or not math.isfinite(target[key])
                   for key in ("z_before", "z_after")):
                return unknown
            verdict = target["verdict"]
            if verdict in ("미달", "과교정"):
                if "P1_STYLE_TARGET" not in reasons:
                    reasons.append("P1_STYLE_TARGET")
            elif verdict not in ("달성", "부분 개선"):
                return unknown
        anti = report["antithesis"]
        if any(type(anti[key]) is not int or anti[key] < 0 for key in ("before", "after")):
            return unknown
        if anti["before"] >= 5 and anti["after"] == 0:
            reasons.append("P2_ANTITHESIS")
        elif anti["verdict"] not in ("OK", "스킵 (원문 대구 < 5)"):
            return unknown
        modality = report["modality"]
        if not modality["lost_pairs"] and modality["verdict"] != "OK":
            return unknown
        for values, reason in ((report["golden"], "P3_GOLDEN"),
                               (report["numbers_dropped"], "P4_NUMBER_DROPPED"),
                               (modality["lost_pairs"], "P5_MODALITY"),
                               (modality["uncertain_pairs"], "P5_UNCERTAIN")):
            if not isinstance(values, list):
                return unknown
            if values:
                reasons.append(reason)
        if exit_code == 3 or (exit_code == 1 and not reasons):
            return unknown
    except (KeyError, TypeError, ValueError):
        return unknown
    return {"version": 1, "codes": reasons}


def verify(before: Path, after: Path, vendor: Path = DEFAULT_VENDOR, attempt: int = 1) -> dict:
    gate, checks, _, _ = modules(vendor)
    source = before.read_text(encoding="utf-8")
    output = after.read_text(encoding="utf-8")
    # Upstream treats some factual failures as advisory. The product must not
    # deliver a changed number/quote simply because the text-change rate is low.
    hard = checks.check_numbers(source, output) + checks.check_quotes(source, output)
    hard += checks.check_headings(source, output) + checks.check_footnotes(source, output)
    codes = sorted({failure.code for failure in hard})
    if checks.dropped_numbers(source, output):
        codes.append("number_dropped")
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = gate.main(["--before", str(before), "--after", str(after), "--genre", "essay", "--json"])
    try:
        # Upstream emits prose then one indented JSON object. Its zero-indent
        # opening brace is distinct from nested objects and escaped text data.
        raw = stdout.getvalue()
        detail = json.loads(raw[raw.rindex("\n{\n") + 1:])
    except (ValueError, TypeError):
        detail = None
    reasons = warning_reasons(detail, code, stderr.getvalue())
    if code not in (0, 1, 2, 3):
        code = 3
    if codes and code != 3:
        code = 2
    return {"gate": {"exit_code": code}, "hardFailures": codes,
            "warningReasons": reasons, "policy": decision(code, attempt)}


def restore(before: Path, after: Path, vendor: Path = DEFAULT_VENDOR) -> dict:
    _, _, modality, commas = modules(vendor)
    with before.open(encoding="utf-8", newline="") as file:
        source = file.read()
    with after.open(encoding="utf-8", newline="") as file:
        output = file.read()
    output, restored, skipped = modality.restore(source, output)
    output, report = commas.strip_injected(source, output, all_sentences=False)
    with after.open("w", encoding="utf-8", newline="") as file:
        file.write(output)
    return {"restoredSentences": len(restored), "skippedSentences": len(skipped), "removedCommas": report["commas_removed"]}


def validate_response(value: object) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("rewrittenText"), str) or not value["rewrittenText"].strip():
        raise ValueError("rewrittenText must be nonempty text")
    warnings = value.get("warnings")
    if not isinstance(warnings, list) or len(warnings) > 20 or any(not isinstance(w, str) or len(w) > 300 for w in warnings):
        raise ValueError("warnings must be a bounded string array")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--vendor-root", type=Path, default=DEFAULT_VENDOR)
    parser.add_argument("--attempt", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    try:
        report = verify(args.before, args.after, args.vendor_root, args.attempt)
    except Exception:
        report = {"gate": {"exit_code": 3}, "hardFailures": [], "policy": "error"}
    print(json.dumps(report, ensure_ascii=False))
    return report["gate"]["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
