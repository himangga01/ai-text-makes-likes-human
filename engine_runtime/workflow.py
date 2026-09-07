"""Shared, deterministic portal/desktop/skill validation policy."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
import io
import json
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
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        code = gate.main(["--before", str(before), "--after", str(after), "--genre", "essay", "--json"])
    if code not in (0, 1, 2, 3):
        code = 3
    if codes and code != 3:
        code = 2
    return {"gate": {"exit_code": code}, "hardFailures": codes, "policy": decision(code, attempt)}


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
