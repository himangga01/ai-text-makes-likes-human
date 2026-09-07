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


def prepare(input_path: Path, root: Path, vendor: Path) -> dict:
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
    if state["status"] == "done":
        return {**common, "status": "done", "outputPath": state["outputPath"]}
    if state["status"] == "failed":
        return {**common, "status": "failed"}
    if state["current"] >= len(chunks):
        return {**common, "status": "ready-to-finalize"}
    chunk = chunks[state["current"]]
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
    response = validate_response(json.loads(response_path.read_text(encoding="utf-8-sig")))
    before = job / f"source-{chunk_id}.txt"
    output = safe_leaf(job, chunk["rewritten_file"])
    output.write_text(response["rewrittenText"].replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8", newline="")
    vendor = Path(state["vendor"])
    report = restore(before, output, vendor)
    if report["restoredSentences"]:
        state["warnings"].append(f"{chunk_id}번 구간의 {report['restoredSentences']}개 문장을 원문으로 복원했습니다.")
    state["warnings"].extend(response["warnings"])
    gate = verify(before, output, vendor, attempt)
    action = gate["policy"]
    if action == "error":
        raise ValueError("Validation could not run")
    if action == "retry":
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


def finalize(job: Path, state: dict, manifest: dict, destination: Path) -> dict:
    if state["status"] != "active" or state["current"] != len(bodies(manifest)):
        raise ValueError("All chunks must be accepted before finalizing")
    destination = destination.resolve()
    if destination == Path(state["inputPath"]) or destination.is_relative_to(job) or destination.exists():
        raise ValueError("Choose a new output file outside the job; original files are never overwritten")
    vendor = Path(state["vendor"])
    script(vendor, "reassemble_chunks.py", "--run-dir", job, "--output", "final.md", "--report", "assembly.json", "--strict")
    result = job / "final.md"
    gate = verify(safe_leaf(job, manifest["source_file"]), result, vendor, 2)
    if gate["gate"]["exit_code"] in (2, 3):
        state["status"] = "failed"
        write_json(job / "job.json", state)
        raise ValueError("Full document validation failed; no output was exported")
    if gate["gate"]["exit_code"] == 1:
        state["warnings"].append("전체 문서를 최종 사용 전에 검토해 주세요.")
    with destination.open("xb") as file:
        file.write(result.read_bytes())
    state.update(status="done", outputPath=str(destination))
    write_json(job / "job.json", state)
    return next_chunk(job, state, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--vendor-root", type=Path, default=DEFAULT_VENDOR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare").add_argument("--input", type=Path, required=True)
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
    args = parser.parse_args()
    root, vendor = args.workspace_root.resolve(), args.vendor_root.resolve()
    try:
        if args.command == "prepare":
            result = prepare(args.input, root, vendor)
        else:
            with transaction(root, args.job, verify_content=args.command != "cleanup") as (job, state, manifest):
                if args.command == "next":
                    result = next_chunk(job, state, manifest)
                elif args.command == "accept":
                    result = accept(job, state, manifest, args.chunk, args.attempt, args.source_hash, args.response)
                elif args.command == "finalize":
                    result = finalize(job, state, manifest, args.output)
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
