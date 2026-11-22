"""The vendor lexical layer's check for one source text, as the portal and the skill Gateway use it.

Returns the `[어휘 점검]` block (vendor `lexical_layer.render_hint_block`, unchanged) and the nouns the
direct-text concept guard may let the rewrite replace (`replaceableNouns`). Without them the guard rejects
the very edit the block asks for: "세 가지 렌즈로" → "세 가지 관점에서" drops the source noun 렌즈, and a
dropped source noun is a concept violation (src/engine/direct-text-fidelity.ts). Owner decision 2026-11-22:
allow only that noun, nothing around it.

A noun is replaceable when a lexicon entry shown in the block matched it in the source as one whole Hangul
word (a phrase match such as "미묘한 접근" names no replaceable noun, so 접근 stays protected), outside
direct quotations, and the entry asks for the change: every 'change' (바꿈 우선) entry, and a 'conditional'
entry only when the source uses it at least twice, the repetition its own guidance names as the reason to
change it.

    python engine_runtime/lexical_check.py --input chunk.txt --vendor-root vendor/humanize-engine [--genre essay]

prints {"block": ..., "replaceableNouns": [...]} and exits 0, or exits 1 when the layer cannot run.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import re
import sys

DEFAULT_VENDOR = Path(__file__).resolve().parent.parent / "vendor" / "humanize-engine"
WORD = re.compile(r"[가-힣]{2,}")
# A conditional entry is changed when it is repeated (its "[조건부]" guidance); one use is left alone.
CONDITIONAL_MIN_USES = 2


def _layer(vendor: Path):
    scripts = Path(vendor).resolve() / "scripts"
    if not (scripts / "lexical_layer.py").is_file():
        raise ValueError("Humanize lexical layer is missing")
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    return importlib.import_module("lexical_layer")


def lexical_check(text: str, vendor: Path = DEFAULT_VENDOR, genre: str = "essay") -> dict:
    layer = _layer(vendor)
    hits = layer.find_hits(text, genre)
    shown = hits[: layer.MAX_HINTS]
    eligible = {hit["id"] for hit in shown
                if hit["tier"] == "change" or (hit["tier"] == "conditional" and hit["count"] >= CONDITIONAL_MIN_USES)}
    quotes = layer.quote_spans(text)
    nouns: set[str] = set()
    for entry in layer.load_lexicon()["entries"]:
        if entry["id"] not in eligible:
            continue
        for match in layer._outside_quotes(layer._matches(entry, text, detect=True), quotes):
            surface = text[match.start():match.end()]
            if WORD.fullmatch(surface):
                nouns.add(surface)
    return {"block": layer.render_hint_block(hits), "replaceableNouns": sorted(nouns)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--input", required=True)
    parser.add_argument("--vendor-root", default=str(DEFAULT_VENDOR))
    parser.add_argument("--genre", default="essay")
    args = parser.parse_args(argv)
    try:
        with open(args.input, encoding="utf-8", newline="") as file:
            text = file.read()
        result = lexical_check(text, Path(args.vendor_root), args.genre)
    except Exception:  # noqa: BLE001 — the caller counts the failure; no source text is printed
        print("[lexical-check] failed", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
