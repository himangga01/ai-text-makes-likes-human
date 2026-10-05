"""File-based humanize workflow for a host Claude/Codex session; never calls an LLM.

Two engines share this gateway. Without SUPER_SEJONG_ENGINE=v2 every job runs the vendored legacy engine, exactly
as before. With SUPER_SEJONG_ENGINE=v2 (read once, at `prepare`) the job runs Super Sejong Engine v2 in process
(DESIGN.md 4.3, WP-13): sejong.plan analyses each chunk into an edit plan, a chunk whose plan needs no model call
is decided without asking the host, the host replies with per-sentence replacements, sejong.check applies, repairs,
verifies and decides them, and finalize reassembles with the document gate. The job records the engine, its
ENGINE_VERSION and the SUPER_SEJONG_* settings it was prepared with; a later call that finds another engine or
version fails ("The engine changed during this job"). The legacy path never imports the sejong package.
"""
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
import types
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workflow import DEFAULT_VENDOR, restore, verify, validate_response
from skill_bridge import available as bridge_available, invoke as bridge, options as rewrite_options

DEFAULT_ROOT = Path(tempfile.gettempdir()) / "humanize-kr-skills"
EMPTY_REPLY = {"replacements": [], "rewrittenText": "", "warnings": []}   # what a chunk with nothing to ask is checked with
SKILL_GENRE = "blog"          # DESIGN 9.2a item 4: the agent-skill route sends blog unless SUPER_SEJONG_GENRE_DEFAULT is set


def write_json(file: Path, data: dict):
    temporary = file.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(file)


def digest(file: Path) -> str:
    return hashlib.sha256(file.read_bytes()).hexdigest()


def engine_switch() -> str:
    """'v2' only for SUPER_SEJONG_ENGINE=v2 (trimmed, lower-case), the rule of sejong.config; read here so that
    the legacy path never imports the sejong package."""
    return "v2" if os.environ.get("SUPER_SEJONG_ENGINE", "").strip().lower() == "v2" else "legacy"


_SEJONG = None


def sejong() -> types.SimpleNamespace:
    """The Super Sejong modules, imported on first use (engine_runtime is on sys.path, see above)."""
    global _SEJONG
    if _SEJONG is None:
        import sejong as package
        import sejong_cli
        from sejong import check, chunk, config, floor, io, verify
        from sejong.types import Options
        _SEJONG = types.SimpleNamespace(package=package, cli=sejong_cli, check=check, chunk=chunk, config=config, floor=floor,
                                        io=io, verify=verify, Options=Options)
    return _SEJONG


def engine_changed(state: dict) -> bool:
    """A job runs on the engine it was prepared with: the selected engine, and its version file, must be unchanged."""
    recorded = state.get("engine", "legacy")
    if recorded != engine_switch():
        return True
    if recorded != "v2":
        return (Path(state["vendor"]) / "ENGINE_VERSION").read_text(encoding="utf-8").strip() != state["engineVersion"]
    try:
        current = sejong().package.read_engine_version()
    except (OSError, ValueError):
        return True
    return (current["id"], current["version"], current["schema"]) != (state["engineId"], state["engineVersion"], state["engineSchema"])


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


def align_outer_whitespace(source: str, output: str) -> str:
    """Re-attach the source chunk's outer whitespace (str.strip semantics), as the
    reassembler does, so a reply that dropped a trailing newline passes every check."""
    core = output.strip()
    if not core or not source.strip():
        return output
    return source[:len(source) - len(source.lstrip())] + core + source[len(source.rstrip()):]


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


def stage_chunks(job: Path, manifest: dict) -> Path:
    """Check the manifest's offsets and write source-N.txt for every body chunk; returns the source file."""
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
    return source


def prepare(input_path: Path, root: Path, vendor: Path, input_kind=None, strength=None) -> dict:
    if engine_switch() == "v2":
        return prepare_v2(input_path, root, input_kind, strength)
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
        source = stage_chunks(job, manifest)
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
            if engine_changed(state):
                raise ValueError("The engine changed during this job (keep SUPER_SEJONG_ENGINE and the ENGINE_VERSION "
                                 "the same until the job ends, or start a new job)")
            if state.get("engine") == "v2":
                for chunk in bodies(manifest):
                    if digest(plan_file(job, chunk)) != state["planHashes"][str(chunk["index"])]:
                        raise ValueError("A chunk plan was modified")
        yield job, state, manifest
    finally:
        lock.unlink(missing_ok=True)


def bodies(manifest: dict) -> list:
    return [chunk for chunk in manifest["chunks"] if not chunk["passthrough"]]


def next_chunk(job: Path, state: dict, manifest: dict) -> dict:
    chunks = bodies(manifest)
    v2 = state.get("engine") == "v2"
    if v2:
        decide_empty_plans(job, state, manifest)
    common = {"job": job.name, "sourceHash": state["sourceHash"], "warnings": state["warnings"], "totalChunks": len(chunks)}
    if v2:
        common["engine"] = {"id": state["engineId"], "version": state["engineVersion"]}
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
    if v2:
        # No rulesPath and no sentencesPath: the prompt carries the contract, the requests and the source.
        instructions = job / f"instructions-{chunk['index']}-{state['attempt']}.md"
        instructions.write_text(writer_prompt_v2(job, state, manifest, chunk), encoding="utf-8")
        return {**common, "status": "rewrite", "chunk": chunk["index"], "attempt": state["attempt"],
                "inputPath": str(job / f"source-{chunk['index']}.txt"), "instructionsPath": str(instructions),
                "responsePath": str(job / f"response-{chunk['index']}-{state['attempt']}.json")}
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
    if state.get("engine") == "v2":
        return accept_v2(job, state, manifest, chunk_id, attempt, source_hash, response_path)
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
    vendor = Path(state["vendor"])
    report = {"restoredSentences": 0, "skippedSentences": 0, "removedCommas": 0}
    failed = False
    gate = None
    if response.get("invalid"):
        # An unusable reply (missing or ambiguous edit anchors) costs this attempt, as on the server.
        state["warnings"].append(f"MODEL_OUTPUT_UNUSABLE: {chunk_id}번 구간의 응답 편집을 적용할 수 없습니다(기준 문구가 없거나 여러 번 나옵니다).")
        failed = True
    else:
        text = align_outer_whitespace(source, response["rewrittenText"].replace("\r\n", "\n").replace("\r", "\n"))
        output.write_text(text, encoding="utf-8", newline="")
        protected = {"restoredProtectedSentences": 0}
        if direct:
            protected = bridge("protect", **options, source=source, candidate=output.read_text(encoding="utf-8"))
            output.write_text(protected["rewrittenText"], encoding="utf-8", newline="")
        report = restore(before, output, vendor)
        if direct:
            report["restoredProtectedSentences"] = protected["restoredProtectedSentences"]
            check = bridge("check", **options, source=source, candidate=output.read_text(encoding="utf-8"))
            failed = response.get("fidelityIssues", 0) > 0 or report["skippedSentences"] > 0 or check["violations"] > 0
            if protected["restoredProtectedSentences"]:
                state["warnings"].append(f"DIRECT_TEXT_PROTECTED_SENTENCES_RESTORED: {chunk_id}번 구간 보호 문장 {protected['restoredProtectedSentences']}개를 원문으로 복원했습니다.")
            if failed:
                state["warnings"].append(f"DIRECT_TEXT_FIDELITY_RESTRICTED: {chunk_id}번 구간의 문장·사실·개념 보존 또는 복원을 확인하지 못했습니다.")
        elif bridge_available():
            # Files and legacy jobs never lose, duplicate or move paragraphs or Markdown structure.
            structure = bridge("structure", **options, source=source, candidate=output.read_text(encoding="utf-8"))
            failed = structure["violations"] > 0
            if failed:
                state["warnings"].append(f"STRUCTURE_FIDELITY_RESTRICTED: {chunk_id}번 구간에서 문장·문단 구조 보존을 확인하지 못해 수정을 제한했습니다.")
        if report["restoredSentences"]:
            state["warnings"].append(f"{chunk_id}번 구간의 {report['restoredSentences']}개 문장을 원문으로 복원했습니다.")
        # Host warnings can contain raw source text. Direct jobs persist only a count.
        if direct and response["warnings"]:
            state["warnings"].append(f"HOST_REVIEW_WARNING: {len(response['warnings'])}개 보존 충돌 사유가 보고되었습니다.")
        elif not direct:
            state["warnings"].extend(response["warnings"])
        # The whole source gives a chunk the document's footnote markers.
        gate = verify(before, output, vendor, attempt, safe_leaf(job, manifest["source_file"]))
    action = gate["policy"] if gate else "retry"
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
    if state.get("engine") == "v2":
        result = reassemble_v2(job, state, manifest)
    else:
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


# --------------------------------------------------------------------------
# Super Sejong v2 (SUPER_SEJONG_ENGINE=v2): analysis, check and reassembly run in this process
# --------------------------------------------------------------------------
def plan_file(job: Path, chunk: dict) -> Path:
    return job / f"plan-{chunk['index']:02d}.json"


def check_file(job: Path, chunk: dict, attempt: int) -> Path:
    return job / f"check-{chunk['index']:02d}-{attempt}.json"


def decided_file(job: Path, chunk: dict) -> Path:
    """The decided text of attempt 1: the --base of attempt 2 (sejong.check)."""
    return job / f"decided-{chunk['index']:02d}-1.txt"


def v2_flags(state: dict):
    """The SUPER_SEJONG_* settings the job was prepared with, so one job never mixes two configurations."""
    return sejong().config.Flags.from_env(state["sejongFlags"])


def warn_once(state: dict, message: str) -> None:
    if message not in state["warnings"]:
        state["warnings"].append(message)


def prepare_v2(input_path: Path, root: Path, input_kind=None, strength=None) -> dict:
    options = rewrite_options(input_kind, strength, offline=True)
    if input_path.suffix.lower() not in (".txt", ".md"):
        raise ValueError("Only TXT and MD are supported")
    text = decode_input(input_path.read_bytes())
    root.mkdir(parents=True, exist_ok=True)
    job = root / ("job-" + uuid.uuid4().hex)
    job.mkdir(mode=0o700)
    try:
        sj = sejong()
        environment = {key: value[:64] for key, value in os.environ.items() if key.startswith("SUPER_SEJONG_")}
        flags = sj.config.Flags.from_env(environment)
        genre = flags.genre_default if environment.get("SUPER_SEJONG_GENRE_DEFAULT", "").strip() else SKILL_GENRE
        (job / "01_input.txt").write_text(text, encoding="utf-8", newline="")
        manifest = sj.chunk.prepare(job, genre=genre)
        source = stage_chunks(job, manifest)
        # A file job (no input kind) is a text-file job: FIX requests only, no open review (DESIGN 3.4).
        plan_options = sj.Options(input_kind=(options or {}).get("inputKind", "text-file"),
                                  strength=(options or {}).get("strength", "normal"), genre=genre,
                                  fix_colloquial=flags.fix_colloquial, deterministic_fix=flags.deterministic_fix)
        plans = []
        for chunk in bodies(manifest):
            plan = sj.cli.analyse_chunk(job / f"source-{chunk['index']}.txt", index=chunk["index"],
                                        total=manifest["chunk_count"], options=plan_options, flags=flags, manifest=manifest)
            sj.io.write_plan(plan_file(job, chunk), plan)
            plans.append({"chunk": chunk["index"], "file": plan_file(job, chunk).name, "needsModel": plan.needs_model})
        manifest["sejong"]["plans"] = plans
        manifest["sejong"]["options"] = {"inputKind": plan_options.input_kind, "strength": plan_options.strength}
        sj.io.write_json(job / sj.chunk.MANIFEST_FILE, manifest)
        version = sj.package.read_engine_version()
        state = {"schemaVersion": 1, "job": job.name, "inputPath": str(input_path.resolve()), "engine": "v2",
                 "engineId": version["id"], "engineVersion": version["version"], "engineSchema": version["schema"],
                 "sejongFlags": environment, "genre": genre,
                 "sourceHash": digest(source), "manifestHash": digest(job / "chunk_manifest.json"),
                 "current": 0, "attempt": 1, "warnings": [], "status": "active"}
        if options:
            state["rewriteOptions"] = options
        state["chunkHashes"] = {str(chunk["index"]): digest(job / f"source-{chunk['index']}.txt") for chunk in bodies(manifest)}
        state["planHashes"] = {str(chunk["index"]): digest(plan_file(job, chunk)) for chunk in bodies(manifest)}
        write_json(job / "job.json", state)
        return next_chunk(job, state, manifest)
    except Exception:
        if job.resolve().parent == root.resolve() and job.name.startswith("job-"):
            shutil.rmtree(job)
        raise


def run_check_v2(job: Path, state: dict, manifest: dict, chunk: dict, attempt: int, response=None, candidate=None):
    """sejong.check on one chunk, as `sejong_cli.py check` runs it (same plan, source, document and base files);
    writes the check report (and, at attempt 1, the decided text) into the job."""
    sj = sejong()
    plan = sj.io.read_plan(plan_file(job, chunk))
    source = sj.io.read_text(job / f"source-{chunk['index']}.txt")
    document = sj.io.read_text(safe_leaf(job, manifest["source_file"]))
    base = sj.io.read_text(decided_file(job, chunk)) if attempt == 2 else None
    outcome = sj.check.check(plan, source, response=response, candidate=candidate, attempt=attempt, base=base,
                             document=document, flags=v2_flags(state))
    sj.io.write_check(check_file(job, chunk, attempt), outcome.report)
    if attempt == 1:
        sj.io.write_text(decided_file(job, chunk), outcome.text)
    return outcome


def finish_chunk_v2(job: Path, state: dict, chunk: dict, text: str) -> None:
    sejong().io.write_text(safe_leaf(job, chunk["rewritten_file"]), text)
    state["current"] += 1
    state["attempt"] = 1
    state.pop("baseHash", None)


def decide_empty_plans(job: Path, state: dict, manifest: dict) -> None:
    """A chunk whose plan needs no model call is decided here, without asking the host (DESIGN 3.4 step 4): its text
    is the source plus the deterministic fixes. Runs before every status answer, so a job whose plans are all empty
    goes from prepare straight to ready-to-finalize."""
    chunks = bodies(manifest)
    moved = []
    while state["status"] == "active" and state["current"] < len(chunks) and state["attempt"] == 1:
        chunk = chunks[state["current"]]
        if sejong().io.read_plan(plan_file(job, chunk)).needs_model:
            break
        outcome = run_check_v2(job, state, manifest, chunk, 1)
        # Nothing was replaced, so only an engine fault can make the gate ask for anything: keep the source then.
        text = outcome.text if outcome.report.policy == "accept" else (job / f"source-{chunk['index']}.txt").read_text(encoding="utf-8")
        finish_chunk_v2(job, state, chunk, text)
        moved.append(chunk["index"])
    if moved:
        state["noEditChunks"] = sorted(set(state.get("noEditChunks", [])) | set(moved))
        message = f"SEJONG_NO_EDIT_NEEDED: {', '.join(map(str, state['noEditChunks']))}번 구간은 모델에 요청할 곳이 없어 모델 호출 없이 통과했습니다(확실한 맞춤법 수정은 적용)."
        state["warnings"] = [w for w in state["warnings"] if not w.startswith("SEJONG_NO_EDIT_NEEDED")] + [message]
        write_json(job / "job.json", state)


def writer_prompt_v2(job: Path, state: dict, manifest: dict, chunk: dict) -> str:
    """The writer prompt of this chunk and attempt, rendered by src/engine/sejong/prompt.ts (bridge op context-v2)
    from the plan; attempt 2 carries only the failed requests of attempt 1 with their named violations."""
    sj = sejong()
    plan = sj.io.read_json(plan_file(job, chunk))
    source = sj.io.read_text(job / f"source-{chunk['index']}.txt")
    retry = sj.io.read_json(check_file(job, chunk, 1))["retry"] if state["attempt"] == 2 else None
    seam = None
    if plan["chunk"]["total"] > 1:
        # Read-only neighbours of this chunk, code-point ranges into the prepared document (plan.seam).
        document = sj.io.read_text(safe_leaf(job, manifest["source_file"]))
        (a, b), (c, d) = plan["seam"]["prev"], plan["seam"]["next"]
        if max(b, d) <= len(document):
            seam = {"prev": document[a:b], "next": document[c:d]}
    return bridge("context-v2", plan=plan, source=source, attempt=state["attempt"], retry=retry, seamContext=seam)["instructions"]


def read_reply_v2(response_path: Path):
    """(response, candidate, host warning count, raw reply text) of the host's reply. A reply that is not JSON is an
    unusable reply (the attempt is spent, as on the server): response "unparsable". A reply in the legacy shape
    (rewrittenText and no replacements) is read as a full-text candidate, the fallback of DESIGN 3.6: edits nobody
    asked for are reverted and requested ones verified like any replacement. Everything else goes to sejong.check
    as it is: apply.py is the one reader that decides, so this path and `sejong_cli.py check --response` cannot
    disagree about a reply."""
    try:
        raw_text = response_path.read_text(encoding="utf-8-sig")
        raw = json.loads(raw_text)
    except ValueError:
        return "unparsable", None, 0, None
    if not isinstance(raw, dict):
        return "unparsable", None, 0, raw_text
    reported = raw.get("warnings")
    reported = len(reported) if isinstance(reported, list) else 0
    full = raw.get("rewrittenText")
    if "replacements" not in raw and isinstance(full, str) and full.strip() and not raw.get("edits"):
        return None, full.replace("\r\n", "\n").replace("\r", "\n"), reported, raw_text
    return raw, None, reported, raw_text


def unusable_reason_v2(job: Path, state: dict, chunk: dict, raw_text) -> str:
    """Why the reply was unusable, for the warning: a code and a JSON path from the TypeScript reader of the server
    path (bridge op parse-v2), never reply text. Diagnostic only: the decision was made by sejong.check, and a
    bridge failure or a reader that finds nothing wrong leaves the generic wording."""
    if raw_text is None:
        return "not_json"
    sj = sejong()
    try:
        retry = sj.io.read_json(check_file(job, chunk, 1))["retry"] if state["attempt"] == 2 else None
        parsed = bridge("parse-v2", plan=sj.io.read_json(plan_file(job, chunk)), raw=raw_text, retry=retry)
    except ValueError:
        return ""
    return "" if parsed["ok"] else parsed["reason"] + (f" at {parsed['at']}" if parsed.get("at") else "")


def drop_not_in_retry(job: Path, chunk: dict, response: dict) -> dict:
    """Attempt 2 may touch only the failed requests (DESIGN 3.5): a replacement whose id is not on the retry list is
    dropped before the check, as the reader of the server path forwards the reply (response.ts, not_in_retry); an S id
    of a requested sentence may answer that request's retry entry. Ids the plan does not know stay in the reply, so
    sejong.check still calls it unusable."""
    items = response.get("replacements")
    if not isinstance(items, list):
        return response
    sj = sejong()
    retry = sj.io.read_json(check_file(job, chunk, 1))["retry"]
    plan = sj.io.read_plan(plan_file(job, chunk))
    listed, retried = {entry["id"] for entry in retry}, {entry["sentence"] for entry in retry}
    request_sentence = {request.id: request.sentence for request in plan.requests}
    sentences = {sentence.id for sentence in plan.sentences}
    requested = set(request_sentence.values())

    def kept(item) -> bool:
        rid = item.get("id") if isinstance(item, dict) else None
        if not isinstance(rid, str) or rid in listed or not (rid in request_sentence or rid in sentences):
            return True
        sentence = request_sentence.get(rid, rid)
        return sentence in requested and sentence in retried

    return {**response, "replacements": [item for item in items if kept(item)]}


def note_check_v2(state: dict, chunk_id: int, attempt: int, report, reported: int, reason) -> None:
    """Warnings of one check: codes and counts only, never document or host text."""
    reverted = report.counts["revertedSentences"]
    if reverted:
        families = ", ".join(f"{name} {count}" for name, count in sorted(report.counts["revertedByFamily"].items()))
        state["warnings"].append(f"SEJONG_SENTENCES_REVERTED: {chunk_id}번 구간 {attempt}차 검증에서 {reverted}개 문장을 원문으로 되돌렸습니다"
                                 + (f"({families})." if families else "."))
    if "model_output_unusable" in report.hard_failures + report.shadow_failures:
        state["warnings"].append(f"MODEL_OUTPUT_UNUSABLE: {chunk_id}번 구간의 응답을 쓸 수 없었습니다({reason or '형식 오류 또는 알 수 없는 ID'}).")
    if reported:
        state["warnings"].append(f"HOST_REVIEW_WARNING: {reported}개 보존 충돌 사유가 보고되었습니다.")


def accept_v2(job: Path, state: dict, manifest: dict, chunk_id: int, attempt: int, source_hash: str, response_path: Path) -> dict:
    chunks = bodies(manifest)
    if state["status"] != "active" or state["current"] >= len(chunks):
        raise ValueError("No chunk is awaiting a response")
    chunk = chunks[state["current"]]
    if chunk["index"] != chunk_id or state["attempt"] != attempt or state["sourceHash"] != source_hash:
        raise ValueError("Response belongs to another chunk, attempt, or input")
    if attempt == 2 and digest(decided_file(job, chunk)) != state.get("baseHash"):
        raise ValueError("The attempt-1 result was modified")
    response, candidate, reported, raw_text = read_reply_v2(response_path)
    if attempt == 2 and isinstance(response, dict):
        response = drop_not_in_retry(job, chunk, response)
    outcome = run_check_v2(job, state, manifest, chunk, attempt, response=response, candidate=candidate)
    report = outcome.report
    if report.policy == "error":
        raise ValueError("Validation could not run")
    unusable = "model_output_unusable" in report.hard_failures + report.shadow_failures
    note_check_v2(state, chunk_id, attempt, report, reported, unusable_reason_v2(job, state, chunk, raw_text) if unusable else "")
    if report.policy == "retry" and attempt == 1 and not report.retry:
        # Nothing is left to ask the writer (no request failed): settle the gate on the attempt-1 decision with an
        # empty reply at attempt 2, as the server does.
        state["baseHash"] = digest(decided_file(job, chunk))
        attempt = 2
        outcome = run_check_v2(job, state, manifest, chunk, 2, response=EMPTY_REPLY)
        report = outcome.report
        if report.policy == "error":
            raise ValueError("Validation could not run")
        note_check_v2(state, chunk_id, 2, report, 0, "")
    if report.policy == "retry" and attempt == 1:
        # Only the sentences named in the check report go back to the host, once (DESIGN 3.9).
        state["baseHash"] = digest(decided_file(job, chunk))
        state["attempt"] = 2
        action = "retry"
        state["warnings"].append(f"CHUNK_RETRY: {chunk_id}번 구간에서 검증에 걸린 문장 {len(report.retry)}개만 보수적으로 다시 다듬어 주세요.")
    else:
        # The decided text holds the source plus the edits that passed (a sentence that failed is back to its
        # source text plus the deterministic fixes). A rollback delivers base(x), the source plus the deterministic
        # fixes, as the server does.
        action = report.policy if report.policy in ("accept", "accept-with-warning", "rollback") else "accept-with-warning"
        finish_chunk_v2(job, state, chunk, outcome.text)
        if action == "rollback":
            fixes = report.counts["normFixes"]
            reason = ("모델 응답을 쓸 수 없어" if "model_output_unusable" in report.hard_failures
                      else "바뀐 양이 너무 많아" if "change_rate_runaway" in report.hard_failures
                      else "내용 보존을 확인하지 못해")
            state["warnings"].append(f"CHUNK_ROLLED_BACK: {chunk_id}번 구간은 {reason} 원문을 유지했습니다."
                                     + (f" 확실한 맞춤법 오류 {fixes}곳만 고쳤습니다." if fixes else ""))
        elif action == "accept-with-warning":
            state["warnings"].append(f"CHUNK_WARNING_ACCEPTED: {chunk_id}번 구간은 사람의 검토가 권장됩니다.")
    write_json(job / "job.json", state)
    counts = report.counts
    return {**next_chunk(job, state, manifest), "decision": action,
            "restoration": {"restoredSentences": counts["restoredSentences"], "skippedSentences": 0,
                            "removedCommas": counts["removedCommas"], "repairedParticles": counts["repairedParticles"]},
            "sejong": {"policy": report.policy, "exitCode": report.gate["exit_code"], "revertedSentences": counts["revertedSentences"],
                       "requestStatus": report.request_status, "changeRate": report.change_rate}}


def reassemble_v2(job: Path, state: dict, manifest: dict) -> Path:
    """Reassemble the decided chunks into final.md and gate the whole document (DESIGN 3.10). sejong_cli.finalize
    does the enforced part: a chunk whose length ratio is off goes back to its source, seam violations revert their
    sentences, and a floor failure restores the whole source (DIRECT_TEXT_DOCUMENT_ROLLED_BACK). Then the full gate
    runs at attempt 2, like the legacy finalize. It has no plan, so it cannot know a change a plan licensed (an
    SSJ-A06 repair makes polarity_changed: 4 of the 6 seed composites, accepted by every chunk check, get exit 2
    from it), which is why only its floor codes act (the whole source is restored, as above) and every other
    code or exit 1 only adds DOCUMENT_REVIEW_RECOMMENDED; exit 3 fails the job."""
    sj = sejong()
    flags = v2_flags(state)
    report = sj.cli.finalize(job, "final.md", "assembly.json", flags=flags)
    source, result = safe_leaf(job, manifest["source_file"]), job / "final.md"
    rolled = bool(report["sejong"]["documentRolledBack"])
    gate = sj.verify.verify_document(source, result, attempt=2, flags=flags, genre=state["genre"])
    code = gate["gate"]["exit_code"]
    if code == 3:
        state["status"] = "failed"
        write_json(job / "job.json", state)
        raise ValueError("Full document validation failed; no output was exported")
    if set(gate["hardFailures"]) & set(sj.floor.CODES) and not rolled:
        sj.io.write_text(result, sj.io.read_text(source))
        rolled = True
    if report["rolledBackChunks"]:
        warn_once(state, f"CHUNK_ROLLED_BACK: {', '.join(map(str, report['rolledBackChunks']))}번 구간은 길이 비율이 맞지 않아 원문을 유지했습니다.")
    if report["sejong"]["seamReverts"]:
        warn_once(state, f"SEJONG_SENTENCES_REVERTED: 구간 경계 검증에서 {report['sejong']['seamReverts']}개 문장을 원문으로 되돌렸습니다.")
    if rolled:
        warn_once(state, "DIRECT_TEXT_DOCUMENT_ROLLED_BACK: 전체 글의 내용 보존을 확인하지 못해 원문을 유지했습니다.")
    elif code in (1, 2):
        codes = ", ".join(dict.fromkeys([*gate["hardFailures"], *gate["shadowFailures"]]))
        warn_once(state, "DOCUMENT_REVIEW_RECOMMENDED: 전체 문서를 최종 사용 전에 검토해 주세요" + (f"({codes})." if codes else "."))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--vendor-root", type=Path, default=DEFAULT_VENDOR)
    sub = parser.add_subparsers(dest="command", required=True)
    preparation = sub.add_parser("prepare")
    preparation.add_argument("--input", type=Path, required=True)
    preparation.add_argument("--input-kind")
    preparation.add_argument("--strength")
    preparation.add_argument("--job-id")
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
            if args.job_id is not None:
                raise ValueError("Explicit job IDs are supported for Office service jobs only")
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
