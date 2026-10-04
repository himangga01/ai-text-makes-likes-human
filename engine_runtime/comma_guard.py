"""Remove the connective-ending commas a rewrite injected, never the writer's own.

The vendored stripper (strip_injected_commas.py) treats every sentence that differs from the source in any way as
new and removes all of its connective-ending commas, so a one-word edit also deleted the commas the writer had put
there. Here each rewritten sentence is aligned with its most similar source sentence: a comma that the aligned
source sentence already had is kept, and only commas the rewrite added are removed. A sentence with no similar
source sentence is still treated as new. Quotation and noun-list exceptions come from the vendored module.

CLI (same contract as the vendored script):
    python engine_runtime/comma_guard.py --before a.txt --after b.txt --out b.txt --json
prints {"commas_removed": n, "sentences_touched": m} to stderr and always exits 0.
"""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import importlib.util
import json
from pathlib import Path
import re
import sys

DEFAULT_VENDOR = Path(__file__).resolve().parent.parent / "vendor/humanize-engine"
# A rewritten sentence this similar to a source sentence is an edit of it, not a new sentence.
MIN_SIMILARITY = 0.5
# Source sentences compared around the proportional position; keeps the work linear in document length.
WINDOW = 12
_WORD_COMMA = re.compile(r"[^\s,]+,")


def load_vendor(vendor: Path = DEFAULT_VENDOR):
    path = vendor.resolve() / "scripts" / "strip_injected_commas.py"
    spec = importlib.util.spec_from_file_location("vendor_strip_injected_commas", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _aligned_source(sources: list[str], index: int, total: int, sentence: str) -> str | None:
    if not sources:
        return None
    centre = round(index * len(sources) / max(1, total))
    best, best_ratio = None, MIN_SIMILARITY
    for source in sources[max(0, centre - WINDOW):centre + WINDOW + 1]:
        matcher = SequenceMatcher(None, source, sentence, autojunk=False)
        if matcher.real_quick_ratio() < best_ratio or matcher.quick_ratio() < best_ratio:
            continue
        ratio = matcher.ratio()
        if ratio >= best_ratio:
            best, best_ratio = source, ratio
    return best


def _writer_commas(source: str, sentence: str) -> set[int]:
    """Positions in ``sentence`` of commas the aligned source sentence already had."""
    kept = set()
    for tag, _, _, j1, j2 in SequenceMatcher(None, source, sentence, autojunk=False).get_opcodes():
        if tag == "equal":
            kept.update(k for k in range(j1, j2) if sentence[k] == ",")
    # A word that kept its comma but moved within the sentence is still the writer's comma.
    written = {m.group() for m in _WORD_COMMA.finditer(source)}
    kept.update(m.end() - 1 for m in _WORD_COMMA.finditer(sentence) if m.group() in written)
    return kept


def _strip(vendor, sentence: str, quote_spans, offset: int, keep: set[int]) -> tuple[str, int]:
    removed, out, last = 0, [], 0
    for m in vendor._CONN_COMMA_RE.finditer(sentence):
        comma = m.start() + len(m.group(1))
        if (comma in keep or any(a <= offset + m.start() < b for a, b in quote_spans)
                or vendor._in_noun_list(sentence, m)):
            continue
        out.append(sentence[last:m.start()])
        out.append(m.group(1) + m.group(2))
        last = m.end()
        removed += 1
    out.append(sentence[last:])
    return "".join(out), removed


def strip_injected(before: str, after: str, vendor=None) -> tuple[str, dict]:
    vendor = vendor or load_vendor()
    sources = [vendor._norm(s) for s in vendor._sentences(before)]
    originals = set(sources)
    quote_spans = [m.span() for m in vendor._QUOTE_RE.finditer(after)]
    pieces = vendor._SENT_SPLIT.split(after)
    separators = vendor._SENT_SPLIT.findall(after)
    parts, offset, total_removed, touched = [], 0, 0, 0
    for index, piece in enumerate(pieces):
        if piece.strip() and vendor._norm(piece) not in originals:
            source = _aligned_source(sources, index, len(pieces), vendor._norm(piece))
            keep = _writer_commas(source, piece) if source else set()
            fixed, removed = _strip(vendor, piece, quote_spans, offset, keep)
            if removed:
                total_removed += removed
                touched += 1
            parts.append(fixed)
        else:
            parts.append(piece)
        offset += len(piece)
        if index < len(separators):
            parts.append(separators[index])
            offset += len(separators[index])
    return "".join(parts), {"commas_removed": total_removed, "sentences_touched": touched}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove connective-ending commas a rewrite injected")
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--out")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--vendor-root", type=Path, default=DEFAULT_VENDOR)
    args = parser.parse_args(argv)
    with open(args.before, encoding="utf-8", newline="") as file:
        before = file.read()
    with open(args.after, encoding="utf-8", newline="") as file:
        after = file.read()
    fixed, report = strip_injected(before, after, load_vendor(args.vendor_root))
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as file:
            file.write(fixed)
    else:
        sys.stdout.write(fixed)
    if args.json:
        print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
