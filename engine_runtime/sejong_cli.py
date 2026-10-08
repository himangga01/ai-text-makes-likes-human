"""Command line of Super Sejong Engine v2 (DESIGN.md 5.1), spawned by src/engine/sejong/python-adapter.ts.

    sejong_cli.py prepare  --run-dir D [--analyse --input-kind K --strength S --genre G]
    sejong_cli.py analyse  --source chunk.txt [--context 01_input.txt] --chunk-index i --chunk-total n
                           --input-kind K --strength S --genre G --out plan.json
    sejong_cli.py check    --plan plan.json --source chunk.txt (--response r.json | --candidate c.txt)
                           --attempt 1|2 [--base decided-1.txt] --out decided.txt --report check.json
    sejong_cli.py verify   --before B --after A [--context C] [--attempt 1|2] [--mode edit|rewrite]
                                                                               legacy gate JSON on stdout
    sejong_cli.py finalize --run-dir D --output 03_reassembled.md --report 03_reassembly_report.json

Exit codes: prepare, analyse and finalize 0 (done) or 1 (failed; the adapter raises ENGINE_OUTPUT_INVALID);
check and verify 0-3 equal to gate.exit_code, 3 = execution error (the adapter raises VALIDATION_FAILED).
Plans and check reports are validated against schemas/*.schema.json before they are written
(sejong.io.write_plan / write_check). Messages on stderr name steps and exception types only, never
document text.

prepare --analyse writes plan-NN.json (NN = chunk index, two digits) next to each body chunk and lists
them in manifest["sejong"]["plans"]; stale plan files of an earlier run are removed. The genre of
prepare without --genre is SUPER_SEJONG_GENRE_DEFAULT. check finds the whole prepared document (for
footnote markers and seam context) the way python-engine.ts documentContext does: chunk_manifest.json
next to --source names it. finalize reassembles (sejong.chunk.reassemble: a chunk whose rewrite fails the
length ratio goes back to its source, CHUNK_ROLLED_BACK), then verifies the whole document: seam
violations (flow.seam_check) revert the offending sentences to the source, and a floor failure that
remains puts the whole document back to the source (DIRECT_TEXT_DOCUMENT_ROLLED_BACK); a rewrite job (manifest
sejong.options.strength "rewrite", WP-19) checks that floor per paragraph (rewrite.floor_violations). The reassembly
report gains warning_codes, rolledBackChunks and a "sejong" block with the document gate (codes and
counts only).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

try:                 # imported as engine_runtime.sejong_cli
    from .sejong import align, check as check_mod, chunk, config, floor, flow, io, plan as plan_mod, text, verify
    from .sejong import rewrite as rewrite_mod
    from .sejong.types import ChunkInfo, Options
except ImportError:  # executed as a script: engine_runtime/ is sys.path[0] (Windows ._pth: add it)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sejong import align, check as check_mod, chunk, config, floor, flow, io, plan as plan_mod, text, verify
    from sejong import rewrite as rewrite_mod
    from sejong.types import ChunkInfo, Options

STRENGTHS = config.STRENGTHS          # normal, medium, strong, very-strong, rewrite (WP-19)
MODES = ("edit", "rewrite")
INPUT_KINDS = ("direct-text", "text-file")
GENRES = ("general", "blog", "essay", "report", "notice", "document")
PLAN_FILE = "plan-{index:02d}.json"
DOCUMENT_ROLLBACK = "DIRECT_TEXT_DOCUMENT_ROLLED_BACK"


def _fail(step: str, error: BaseException) -> None:
    print(f"sejong {step}: {type(error).__name__}", file=sys.stderr)


def _options(args: argparse.Namespace, flags: config.Flags) -> Options:
    return Options(input_kind=args.input_kind, strength=args.strength, genre=args.genre,
                   fix_colloquial=flags.fix_colloquial, deterministic_fix=flags.deterministic_fix)


def _manifest_document(directory: Path, exclude: Optional[Path] = None):
    """(manifest, document text) of the run directory, or (None, None)."""
    try:
        manifest = io.read_json(directory / chunk.MANIFEST_FILE)
        source = directory / manifest["source_file"]
        if exclude is not None and source.resolve() == exclude.resolve():
            return manifest, None
        return manifest, io.read_text(source)
    except (OSError, ValueError, KeyError, TypeError):
        return None, None


def analyse_chunk(source: Path, *, index: int, total: int, options: Options, flags: config.Flags,
                  manifest: Optional[dict] = None):
    chunk_text = io.read_text(source)
    seam = chunk.seam_ranges(manifest, index) if manifest is not None and total > 1 else None
    info = ChunkInfo(index=index, total=total, source_sha256=plan_mod._sha256(chunk_text), chars=len(chunk_text))
    return plan_mod.build_plan(chunk_text, options=options, chunk=info, seam=seam, flags=flags)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_prepare(args: argparse.Namespace) -> int:
    flags = config.Flags.from_env()
    run = Path(args.run_dir)
    genre = args.genre or flags.genre_default
    try:
        manifest = chunk.prepare(run, genre=genre)
        for stale in sorted(run.glob("plan-*.json")):
            stale.unlink()
        if args.analyse:
            options = _options(argparse.Namespace(input_kind=args.input_kind, strength=args.strength, genre=genre),
                               flags)
            body = [c for c in manifest["chunks"] if not c["passthrough"]]
            plans = []
            for entry in body:
                plan = analyse_chunk(run / entry["input_file"], index=entry["index"], total=manifest["chunk_count"],
                                     options=options, flags=flags, manifest=manifest)
                name = PLAN_FILE.format(index=entry["index"])
                io.write_plan(run / name, plan)
                plans.append({"chunk": entry["index"], "file": name, "needsModel": plan.needs_model})
            manifest["sejong"]["plans"] = plans
            manifest["sejong"]["options"] = {"inputKind": options.input_kind, "strength": options.strength}
            io.write_json(run / chunk.MANIFEST_FILE, manifest)
    except Exception as error:  # noqa: BLE001 - every failure is exit 1 for the adapter
        _fail("prepare", error)
        return 1
    return 0


def cmd_analyse(args: argparse.Namespace) -> int:
    flags = config.Flags.from_env()
    try:
        if not 1 <= args.chunk_index <= args.chunk_total:
            raise ValueError("chunk index outside 1..total")
        manifest = None
        if args.context:
            manifest, _document = _manifest_document(Path(args.context).resolve().parent)
        plan = analyse_chunk(Path(args.source), index=args.chunk_index, total=args.chunk_total,
                             options=_options(args, flags), flags=flags, manifest=manifest)
        io.write_plan(args.out, plan)
    except Exception as error:  # noqa: BLE001
        _fail("analyse", error)
        return 1
    return 0


def _error_gate() -> dict:
    return {"gate": {"exit_code": 3}, "hardFailures": [], "warningReasons": {"version": 1, "codes": []},
            "policy": "error", "shadowFailures": []}


def cmd_check(args: argparse.Namespace) -> int:
    try:
        if (args.response is None) == (args.candidate is None):
            raise ValueError("pass exactly one of --response and --candidate")
        if args.attempt == 2 and args.base is None:
            raise ValueError("attempt 2 needs --base")
        plan = io.read_plan(args.plan)
        source_path = Path(args.source)
        source = io.read_text(source_path)
        _manifest, document = _manifest_document(source_path.resolve().parent, exclude=source_path)
        response = candidate = None
        if args.response is not None:
            try:
                response = json.loads(io.read_text(args.response))
            except ValueError:
                response = "unparsable"          # an unusable reply, not an execution error (3.6)
        else:
            candidate = io.read_text(args.candidate)
        base = io.read_text(args.base) if args.base is not None else None
        outcome = check_mod.check(plan, source, response=response, candidate=candidate, attempt=args.attempt,
                                  base=base, document=document, flags=config.Flags.from_env())
        io.write_text(args.out, outcome.text)
        io.write_check(args.report, outcome.report)
        report = outcome.report.to_json()
    except Exception as error:  # noqa: BLE001
        _fail("check", error)
        print(json.dumps(_error_gate()))
        return 3
    print(json.dumps({key: report[key] for key in ("gate", "hardFailures", "warningReasons", "policy",
                                                    "shadowFailures")}, ensure_ascii=False))
    return report["gate"]["exit_code"]


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        report = verify.verify_document(Path(args.before), Path(args.after),
                                        context=Path(args.context) if args.context else None, attempt=args.attempt,
                                        mode=args.mode)
    except Exception as error:  # noqa: BLE001
        _fail("verify", error)
        report = _error_gate()
    print(json.dumps(report, ensure_ascii=False))
    return report["gate"]["exit_code"]


def finalize(run_dir: Path, output: str, report_name: str, *, flags: Optional[config.Flags] = None) -> dict:
    """Reassemble, verify the whole document, revert seam violations, roll back on a floor failure."""
    flags = flags if flags is not None else config.Flags.from_env()
    report = chunk.reassemble(run_dir, output, report_name)
    manifest = io.read_json(run_dir / chunk.MANIFEST_FILE)
    source = io.read_text(run_dir / manifest["source_file"])
    result = io.read_text(run_dir / output)
    seam_reverts = 0
    seam_codes: List[str] = []
    if manifest.get("processing_mode") == "chunked" and result != source:
        src_doc, out_doc = text.segment(source), text.segment(result)
        pairs = align.align_documents(src_doc, out_doc)
        found = flow.seam_check(src_doc, out_doc, manifest, pairs)
        enforced, _shadow = verify.classify(flags, found)
        seam_codes = verify.unique_codes(enforced)
        targets = {v.sentence for v in enforced if v.sentence}
        if targets:
            pieces, last = [], 0
            for pair in pairs:
                if not pair.src or not pair.out or not any(src_doc.units[i].id in targets for i in pair.src):
                    continue
                first, end = out_doc.units[min(pair.out)], out_doc.units[max(pair.out)]
                original = source[src_doc.units[min(pair.src)].start:src_doc.units[max(pair.src)].end]
                pieces.append(result[last:first.start])
                pieces.append(original)
                last = end.end
                seam_reverts += len(pair.src)
            pieces.append(result[last:])
            result = "".join(pieces)
    # A rewrite job (strength rewrite, WP-19) keeps the floor per paragraph: floor.check aligns sentence by sentence
    # and would read a merge inside a paragraph as a dropped sentence.
    rewrite = ((manifest.get("sejong") or {}).get("options") or {}).get("strength") == "rewrite"
    if result == source:
        floor_codes = []
    else:
        floor_codes = floor.codes(rewrite_mod.floor_violations(source, result) if rewrite else floor.check(source, result))
    rolled_back = bool(floor_codes)
    if rolled_back:
        result = source
    io.write_text(run_dir / output, result)
    codes = list(report.get("warning_codes", []))
    if rolled_back:
        codes.append(DOCUMENT_ROLLBACK)
    report["warning_codes"] = codes
    report["rolledBackChunks"] = list(report.get("rolled_back_chunks", []))
    report["output_chars"] = len(result)
    report["sejong"] = {"version": 1, "seamReverts": seam_reverts, "seamCodes": seam_codes,
                        "floorCodes": floor_codes, "documentRolledBack": rolled_back,
                        "changeRate": round(verify.change_rate(source, result), 3)}
    io.write_json(run_dir / report_name, report)
    return report


def cmd_finalize(args: argparse.Namespace) -> int:
    try:
        for name in (args.output, args.report):
            if not name or "/" in name or "\\" in name or name in (".", ".."):
                raise ValueError("output and report must be plain file names")
        finalize(Path(args.run_dir), args.output, args.report)
    except Exception as error:  # noqa: BLE001
        _fail("finalize", error)
        return 1
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="sejong_cli.py", description="Super Sejong Engine v2")
    sub = root.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--analyse", action="store_true")
    p.add_argument("--input-kind", choices=INPUT_KINDS, default="direct-text")
    p.add_argument("--strength", choices=STRENGTHS, default="medium")
    p.add_argument("--genre", choices=GENRES)
    p.set_defaults(run=cmd_prepare)

    p = sub.add_parser("analyse")
    p.add_argument("--source", required=True)
    p.add_argument("--context")
    p.add_argument("--chunk-index", type=int, required=True)
    p.add_argument("--chunk-total", type=int, required=True)
    p.add_argument("--input-kind", choices=INPUT_KINDS, required=True)
    p.add_argument("--strength", choices=STRENGTHS, required=True)
    p.add_argument("--genre", choices=GENRES, required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(run=cmd_analyse)

    p = sub.add_parser("check")
    p.add_argument("--plan", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--response")
    p.add_argument("--candidate")
    p.add_argument("--attempt", type=int, choices=(1, 2), required=True)
    p.add_argument("--base")
    p.add_argument("--out", required=True)
    p.add_argument("--report", required=True)
    p.set_defaults(run=cmd_check)

    p = sub.add_parser("verify")
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    p.add_argument("--context")
    p.add_argument("--attempt", type=int, choices=(1, 2), default=1)
    p.add_argument("--mode", choices=MODES, default="edit")     # rewrite: the paragraph rules of strength rewrite
    p.set_defaults(run=cmd_verify)

    p = sub.add_parser("finalize")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--output", default="03_reassembled.md")
    p.add_argument("--report", default="03_reassembly_report.json")
    p.set_defaults(run=cmd_finalize)
    return root


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser().parse_args(argv)
    except SystemExit as stop:
        if stop.code in (0, None):
            return 0
        # A usage error is an execution error: 3 for the gate steps (VALIDATION_FAILED), 1 for the others.
        return 3 if argv and argv[0] in ("check", "verify") else 1
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
