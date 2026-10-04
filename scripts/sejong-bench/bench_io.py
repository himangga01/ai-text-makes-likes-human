"""Where the harness may write, and what it may write (WP-15a).

Rules, enforced in code so a mistake fails loudly instead of leaking text:
  * Every output goes under $BENCH, a directory OUTSIDE any git work tree (never the repository,
    never a worktree). resolve_bench() refuses anything else; bench_path() refuses paths that
    escape $BENCH.
  * Metrics records carry ids, hashes, counts, labels and enum names only. check_metrics_record()
    rejects every string that is not short printable ASCII, so no Korean text (a Hermes draft, a
    model output, a seed sentence) can be written by this module, whatever a caller passes in.
  * Text inputs (writer outputs, Hermes drafts) are only ever READ, from wherever the caller says.
    Anything a later stage must keep as text belongs in $BENCH/private/, which this module never
    writes to.

This module imports no engine code. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

# Session scratchpad of the work that introduced the harness; override with BENCH=/some/dir.
DEFAULT_BENCH = ("/private/tmp/claude-501/-Users-wisdom-wisdom-project-gpt-ai-text-makes-likes-human/"
                 "e70a7860-b0c8-4bf4-999b-63b4ba6d0a8c/scratchpad/bench")
METRICS_SCHEMA = "sejong-bench-metrics/1"
SUMMARY_SCHEMA = "sejong-bench-summary/1"
HERE = Path(__file__).resolve().parent
LABEL = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_SAFE_STRING = re.compile(r"^[\x20-\x7e]{0,120}$")
PathLike = Union[str, Path]


class BenchError(RuntimeError):
    """A write location or a record that the harness refuses."""


def repo_root() -> Path:
    """The checkout (or worktree) this file lives in: scripts/sejong-bench/ is two levels below it."""
    return HERE.parents[1]


# ---- hashes -----------------------------------------------------------------------------------
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# Files that are not part of the judge: the self-test and the damage writers it drives.
_NOT_THE_JUDGE = {"selftest.py", "damage.py"}


def scorer_files() -> List[Path]:
    return sorted(p for p in HERE.glob("*.py") if p.name not in _NOT_THE_JUDGE)


def scorer_sha256() -> str:
    """One hash over the scorer's own source files (every .py here except the self-test and the
    damage writers), so a metrics record names the exact judge. A sealed run pins this value."""
    digest = hashlib.sha256()
    for path in scorer_files():
        digest.update(path.name.encode("ascii") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


# ---- $BENCH -----------------------------------------------------------------------------------
def _inside_git_worktree(path: Path) -> bool:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    for ancestor in [probe, *probe.parents]:
        if (ancestor / ".git").exists():
            return True
    return False


def resolve_bench(env: Optional[Mapping[str, str]] = None) -> Path:
    """$BENCH (or DEFAULT_BENCH) as an absolute path, refused when it is inside a git work tree."""
    environ = os.environ if env is None else env
    raw = (environ.get("BENCH") or DEFAULT_BENCH).strip()
    if not raw:
        raise BenchError("BENCH is empty")
    root = Path(raw).expanduser().resolve()
    repo = repo_root().resolve()
    if root == repo or repo in root.parents or root in repo.parents:
        raise BenchError("BENCH must be outside the repository")
    if _inside_git_worktree(root):
        raise BenchError("BENCH must not be inside a git work tree")
    return root


def bench_path(*parts: str, env: Optional[Mapping[str, str]] = None) -> Path:
    """A path under $BENCH built from relative parts; ".." and absolute parts are refused."""
    root = resolve_bench(env)
    target = root.joinpath(*parts).resolve()
    if target != root and root not in target.parents:
        raise BenchError("path escapes BENCH")
    return target


def require_outside_repo(path: PathLike, what: str) -> Path:
    """Writer outputs and drafts are text the repository must never hold: refuse a path inside it."""
    resolved = Path(path).expanduser().resolve()
    repo = repo_root().resolve()
    if resolved == repo or repo in resolved.parents:
        raise BenchError(f"{what} must live outside the repository (use $BENCH/private/)")
    return resolved


# ---- what a metrics record may contain --------------------------------------------------------
def check_metrics_record(value: Any, path: str = "$") -> None:
    """Raise BenchError unless `value` is made of None/bool/int/float and short printable-ASCII
    strings, in lists and dicts with printable-ASCII keys. Korean text cannot pass."""
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise BenchError(f"{path}: non-finite number")
        return
    if isinstance(value, str):
        if not _SAFE_STRING.match(value):
            raise BenchError(f"{path}: string is not short printable ASCII (length {len(value)})")
        return
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            check_metrics_record(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not _SAFE_STRING.match(key):
                raise BenchError(f"{path}: key is not short printable ASCII")
            check_metrics_record(item, f"{path}.{key}")
        return
    raise BenchError(f"{path}: unsupported type {type(value).__name__}")


def check_label(value: str, what: str) -> str:
    if not LABEL.match(value):
        raise BenchError(f"{what} must match {LABEL.pattern}")
    return value


# ---- writing ----------------------------------------------------------------------------------
def _atomic_write(target: Path, data: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
        os.replace(temp, target)
    except BaseException:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise


def write_metrics_jsonl(rel: str, records: Iterable[Dict[str, Any]], env: Optional[Mapping[str, str]] = None) -> Path:
    """Write metrics records (one JSON object per line) to $BENCH/<rel>. Every record is checked
    with check_metrics_record first; nothing is written when one fails."""
    target = bench_path(*rel.split("/"), env=env)
    lines: List[str] = []
    for n, record in enumerate(records):
        check_metrics_record(record, f"record[{n}]")
        lines.append(json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    _atomic_write(target, "".join(line + "\n" for line in lines))
    return target


def write_metrics_json(rel: str, record: Dict[str, Any], env: Optional[Mapping[str, str]] = None) -> Path:
    target = bench_path(*rel.split("/"), env=env)
    check_metrics_record(record)
    _atomic_write(target, json.dumps(record, ensure_ascii=True, sort_keys=True, indent=2) + "\n")
    return target
