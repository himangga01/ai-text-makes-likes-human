"""File-based humanize workflow for a host Claude/Codex session; never calls an LLM."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workflow import DEFAULT_VENDOR, restore, verify, validate_response
from skill_bridge import invoke as bridge, options as rewrite_options

DEFAULT_ROOT = Path(tempfile.gettempdir()) / "humanize-kr-skills"


def write_json(file: Path, data: dict):
    temporary = file.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(file)


def digest(file: Path) -> str:
    return hashlib.sha256(file.read_bytes()).hexdigest()


def safe_leaf(job: Path, leaf: str) -> Path:
    if not isinstance(leaf, str) or Path(leaf).name != leaf or leaf in (".", "..") or "\\" in leaf:
        raise ValueError("Unsafe manifest filename")
    result = (job / leaf).resolve()
    if result.parent != job.resolve():
        raise ValueError("Unsafe workspace path")
    return result


def script(vendor: Path, name: str, *args: str):
    result = subprocess.run(
        [sys.executable, str(vendor / "scripts" / name), *map(str, args)],
        capture_output=True, encoding="utf-8", timeout=120,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise ValueError(f"Humanize {name} failed ({result.returncode})")


def decode_input(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp949")
    if "\x00" in text or not text.strip():
        raise ValueError("Input must be nonempty TXT/MD text")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def prepare(input_path: Path, root: Path, vendor: Path, input_kind=None, strength=None) -> dict:
    options = rewrite_options(input_kind, strength)
    if input_path.suffix.lower() not in (".txt", ".md"):
        raise ValueError("Only TXT and MD are supported")
    text = decode_input(input_path.read_bytes())
    root.mkdir(parents=True, exist_ok=True)
    job = root / ("job-" + uuid.uuid4().hex)
    job.mkdir(mode=0o700)
    try:
        source = job / "01_input.txt"
        source.write_text(text, encoding="utf-8", newline="")
        script(vendor, "prepare_monolith_input.py", "--chunk", "--portal-auto-route", "--run-dir", job, "--genre", "essay")
        manifest = json.loads((job / "chunk_manifest.json").read_text(encoding="utf-8"))
        source = safe_leaf(job, manifest["source_file"])
        text = source.read_text(encoding="utf-8")
        position = 0
        for chunk in manifest["chunks"]:
            if chunk["start"] != position or chunk["end"] < position or chunk["end"] > len(text):
                raise ValueError("Manifest offsets are invalid")
            position = chunk["end"]
            if not chunk["passthrough"]:
                safe_leaf(job, chunk["rewritten_file"])
                (job / f"source-{chunk['index']}.txt").write_text(text[chunk["start"]:chunk["end"]], encoding="utf-8", newline="")
        if position != len(text):
            raise ValueError("Manifest does not cover the input")
        state = {"schemaVersion": 1, "job": job.name, "inputPath": str(input_path.resolve()),
                 "vendor": str(vendor), "engineVersion": (vendor / "ENGINE_VERSION").read_text(encoding="utf-8").strip(),
                 "sourceHash": digest(source), "manifestHash": digest(job / "chunk_manifest.json"),
                 "current": 0, "attempt": 1, "warnings": [], "status": "active"}
        if options:
            state["rewriteOptions"] = options
        state["chunkHashes"] = {str(chunk["index"]): digest(job / f"source-{chunk['index']}.txt") for chunk in bodies(manifest)}
        write_json(job / "job.json", state)
        return next_chunk(job, state, manifest)
    except Exception:
        if job.resolve().parent == root.resolve() and job.name.startswith("job-"):
            shutil.rmtree(job)
        raise


@contextmanager
def transaction(root: Path, job_id: str, verify_content: bool = True):
    if len(job_id) != 36 or not job_id.startswith("job-") or any(c not in "0123456789abcdef" for c in job_id[4:]):
        raise ValueError("Invalid job ID")
    job = (root / job_id).resolve()
    if job.parent != root.resolve():
        raise ValueError("Invalid job directory")
    lock = job / "operation.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        state = json.loads((job / "job.json").read_text(encoding="utf-8"))
        manifest = json.loads((job / "chunk_manifest.json").read_text(encoding="utf-8"))
        if state["schemaVersion"] != 1 or state["job"] != job_id:
            raise ValueError("Job state is invalid")
        if verify_content and (digest(safe_leaf(job, manifest["source_file"])) != state["sourceHash"] or digest(job / "chunk_manifest.json") != state["manifestHash"]):
            raise ValueError("Original input or manifest changed")
        if verify_content:
            for chunk in bodies(manifest):
                if digest(job / f"source-{chunk['index']}.txt") != state["chunkHashes"][str(chunk["index"])]:
                    raise ValueError("A source chunk was modified")
            if (Path(state["vendor"]) / "ENGINE_VERSION").read_text(encoding="utf-8").strip() != state["engineVersion"]:
                raise ValueError("The engine changed during this job")
        yield job, state, manifest
    finally:
        lock.unlink(missing_ok=True)


def bodies(manifest: dict) -> list:
    return [chunk for chunk in manifest["chunks"] if not chunk["passthrough"]]


def next_chunk(job: Path, state: dict, manifest: dict) -> dict:
    chunks = bodies(manifest)
    common = {"job": job.name, "sourceHash": state["sourceHash"], "warnings": state["warnings"], "totalChunks": len(chunks)}
    if state.get("rewriteOptions"):
        common["rewriteOptions"] = state["rewriteOptions"]
    if state["status"] == "done":
        return {**common, "status": "done", "outputPath": state["outputPath"],
                **({"comparisonPath": state["comparisonPath"]} if state.get("comparisonPath") else {})}
    if state["status"] == "failed":
        return {**common, "status": "failed"}
    if state["current"] >= len(chunks):
        return {**common, "status": "ready-to-finalize"}
    chunk = chunks[state["current"]]
    if state.get("rewriteOptions", {}).get("inputKind") == "direct-text":
        context = bridge("context", **state["rewriteOptions"], attempt=state["attempt"],
                         source=(job / f"source-{chunk['index']}.txt").read_text(encoding="utf-8"),
                         quickRules=(Path(state["vendor"]) / "skills/humanize-korean/references/quick-rules.md").read_text(encoding="utf-8"),
                         candidateReview=state.get("candidateReview"))
        instructions = job / f"instructions-{chunk['index']}-{state['attempt']}.md"
        instructions.write_text(context["instructions"], encoding="utf-8")
        sentences = job / f"sentences-{chunk['index']}.json"
        write_json(sentences, context["sentences"])
        common.update(instructionsPath=str(instructions), sentencesPath=str(sentences))
    return {**common, "status": "rewrite", "chunk": chunk["index"], "attempt": state["attempt"],
            "inputPath": str(job / f"source-{chunk['index']}.txt"),
            "responsePath": str(job / f"response-{chunk['index']}-{state['attempt']}.json"),
            "rulesPath": str(Path(state["vendor"]) / "skills/humanize-korean/references/quick-rules.md")}


def accept(job: Path, state: dict, manifest: dict, chunk_id: int, attempt: int, source_hash: str, response_path: Path) -> dict:
    chunks = bodies(manifest)
    if state["status"] != "active" or state["current"] >= len(chunks):
        raise ValueError("No chunk is awaiting a response")
    chunk = chunks[state["current"]]
    if chunk["index"] != chunk_id or state["attempt"] != attempt or state["sourceHash"] != source_hash:
        raise ValueError("Response belongs to another chunk, attempt, or input")
    before = job / f"source-{chunk_id}.txt"
    source = before.read_text(encoding="utf-8")
    options = state.get("rewriteOptions", {})
    direct = options.get("inputKind") == "direct-text"
    raw = json.loads(response_path.read_text(encoding="utf-8-sig"))
    response = bridge("parse", **options, source=source, response=raw) if direct else validate_response(raw)
    output = safe_leaf(job, chunk["rewritten_file"])
    output.write_text(response["rewrittenText"].replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8", newline="")
    vendor = Path(state["vendor"])
    protected = {"restoredProtectedSentences": 0}
    if direct:
        protected = bridge("protect", **options, source=source, candidate=output.read_text(encoding="utf-8"))
        output.write_text(protected["rewrittenText"], encoding="utf-8", newline="")
    report = restore(before, output, vendor)
    failed = False
    if direct:
        report["restoredProtectedSentences"] = protected["restoredProtectedSentences"]
        check = bridge("check", **options, source=source, candidate=output.read_text(encoding="utf-8"))
        failed = response.get("fidelityIssues", 0) > 0 or report["skippedSentences"] > 0 or check["violations"] > 0
        if protected["restoredProtectedSentences"]:
            state["warnings"].append(f"DIRECT_TEXT_PROTECTED_SENTENCES_RESTORED: {chunk_id}번 구간 보호 문장 {protected['restoredProtectedSentences']}개를 원문으로 복원했습니다.")
        if failed:
            state["warnings"].append(f"DIRECT_TEXT_FIDELITY_RESTRICTED: {chunk_id}번 구간의 문장·사실·개념 보존 또는 복원을 확인하지 못했습니다.")
    if report["restoredSentences"]:
        state["warnings"].append(f"{chunk_id}번 구간의 {report['restoredSentences']}개 문장을 원문으로 복원했습니다.")
    # Host warnings can contain raw source text. Direct jobs persist only a count.
    if direct and response["warnings"]:
        state["warnings"].append(f"HOST_REVIEW_WARNING: {len(response['warnings'])}개 보존 충돌 사유가 보고되었습니다.")
    elif not direct:
        state["warnings"].extend(response["warnings"])
    gate = verify(before, output, vendor, attempt)
    action = gate["policy"]
    if action == "error":
        raise ValueError("Validation could not run")
    if failed:
        action = "retry" if attempt == 1 else "rollback"
    state.pop("candidateReview", None)
    if action == "retry":
        if direct and not failed and attempt == 1:
            review = bridge("review", **options, source=source, candidate=output.read_text(encoding="utf-8"),
                            gate=gate, parserIssues=response.get("fidelityIssues", 0), skippedSentences=report["skippedSentences"])
            if review.get("candidateReview"):
                state["candidateReview"] = review["candidateReview"]
                state["warnings"].append(f"DIRECT_TEXT_CANDIDATE_REVIEW_RETRY: {chunk_id}번 구간의 이전 후보를 원문과 보수적으로 대조합니다. 불확실한 수정은 되돌립니다.")
        state["attempt"] = 2
        state["warnings"].append(f"{chunk_id}번 구간을 보수적으로 다시 다듬어 주세요.")
    else:
        if action == "rollback":
            shutil.copyfile(before, output)
            state["warnings"].append(f"{chunk_id}번 구간은 내용 보존을 위해 원문을 유지했습니다.")
        elif action == "accept-with-warning":
            state["warnings"].append(f"{chunk_id}번 구간은 사람의 검토가 권장됩니다.")
        state["current"] += 1
        state["attempt"] = 1
    write_json(job / "job.json", state)
    return {**next_chunk(job, state, manifest), "decision": action, "restoration": report}


def finalize(job: Path, state: dict, manifest: dict, destination: Path, comparison: Path | None = None) -> dict:
    if state["status"] != "active" or state["current"] != len(bodies(manifest)):
        raise ValueError("All chunks must be accepted before finalizing")
    destination = destination.resolve()
    if destination == Path(state["inputPath"]) or destination.is_relative_to(job) or destination.exists():
        raise ValueError("Choose a new output file outside the job; original files are never overwritten")
    direct = state.get("rewriteOptions", {}).get("inputKind") == "direct-text"
    if comparison is not None:
        comparison = comparison.resolve()
        if not direct:
            raise ValueError("Comparison export is available for direct text only")
        if (comparison == destination or comparison == Path(state["inputPath"]) or comparison.is_relative_to(job)
                or comparison.exists() or comparison.suffix.lower() != ".html"):
            raise ValueError("Choose a new HTML comparison file outside the job")
    vendor = Path(state["vendor"])
    script(vendor, "reassemble_chunks.py", "--run-dir", job, "--output", "final.md", "--report", "assembly.json", "--strict")
    result = job / "final.md"
    if direct and bridge("check", **state["rewriteOptions"],
                         source=safe_leaf(job, manifest["source_file"]).read_text(encoding="utf-8"),
                         candidate=result.read_text(encoding="utf-8"))["violations"]:
        raise ValueError("Full source fidelity validation failed; no output was exported")
    gate = verify(safe_leaf(job, manifest["source_file"]), result, vendor, 2)
    if gate["gate"]["exit_code"] in (2, 3):
        state["status"] = "failed"
        write_json(job / "job.json", state)
        raise ValueError("Full document validation failed; no output was exported")
    if gate["gate"]["exit_code"] == 1:
        state["warnings"].append("전체 문서를 최종 사용 전에 검토해 주세요.")
    html = None
    if comparison is not None:
        html = bridge("comparison", **state["rewriteOptions"],
                      source=safe_leaf(job, manifest["source_file"]).read_text(encoding="utf-8"),
                      candidate=result.read_text(encoding="utf-8"))["html"]
    created = []
    previous = dict(state)
    try:
        for path, content in [(destination, result.read_bytes()), *([(comparison, html.encode("utf-8"))] if html is not None else [])]:
            with path.open("xb") as file:
                created.append(path)
                file.write(content)
        state.update(status="done", outputPath=str(destination))
        if comparison is not None:
            state["comparisonPath"] = str(comparison)
        write_json(job / "job.json", state)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        state.clear()
        state.update(previous)
        raise
    return next_chunk(job, state, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--vendor-root", type=Path, default=DEFAULT_VENDOR)
    sub = parser.add_subparsers(dest="command", required=True)
    preparation = sub.add_parser("prepare")
    preparation.add_argument("--input", type=Path, required=True)
    preparation.add_argument("--input-kind")
    preparation.add_argument("--strength")
    for name in ("next", "accept", "finalize", "cleanup"):
        command = sub.add_parser(name)
        command.add_argument("--job", required=True)
        if name == "accept":
            command.add_argument("--chunk", type=int, required=True)
            command.add_argument("--attempt", type=int, choices=(1, 2), required=True)
            command.add_argument("--source-hash", required=True)
            command.add_argument("--response", type=Path, required=True)
        if name == "finalize":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--comparison-output", type=Path)
    args = parser.parse_args()
    root, vendor = args.workspace_root.resolve(), args.vendor_root.resolve()
    try:
        document = args.command == "prepare" and Path(args.input).suffix.lower() in (".docx", ".pptx")
        if args.command != "prepare" and len(args.job) == 36 and args.job.startswith("job-") and all(c in "0123456789abcdef" for c in args.job[4:]):
            state_file = root / args.job / "job.json"
            if state_file.is_file():
                document = json.loads(state_file.read_text(encoding="utf-8")).get("kind") == "document"
        if document:
            if args.command == "prepare":
                if args.input_kind == "direct-text":
                    raise ValueError("Office files cannot be direct text")
                rewrite_options(args.input_kind, args.strength)
            if args.command == "finalize" and args.comparison_output is not None:
                raise ValueError("Comparison export is available for direct text only")
            from documents.workflow import dispatch
            print(json.dumps(dispatch(args, root, vendor), ensure_ascii=False))
            return 0
        if args.command == "prepare":
            result = prepare(args.input, root, vendor, args.input_kind, args.strength)
        else:
            with transaction(root, args.job, verify_content=args.command != "cleanup") as (job, state, manifest):
                if args.command == "next":
                    result = next_chunk(job, state, manifest)
                elif args.command == "accept":
                    result = accept(job, state, manifest, args.chunk, args.attempt, args.source_hash, args.response)
                elif args.command == "finalize":
                    result = finalize(job, state, manifest, args.output, args.comparison_output)
                else:
                    result = {"status": "cleaned", "job": job.name}
            if args.command == "cleanup":
                # transaction has validated the exact UUID directory and ownership.
                if job.parent != root or not job.name.startswith("job-"):
                    raise ValueError("Unsafe cleanup target")
                shutil.rmtree(job)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
