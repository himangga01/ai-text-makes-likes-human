#!/usr/bin/env python3
"""Read the portal pin and the fork's remote ref without changing either repo."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

DEFAULT_PROJECT = Path("C:/project/2026/ai-text-makes-likes-human")
DEFAULT_UPSTREAM = "https://github.com/himangga01/im-not-ai_fork.git"
OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z", re.IGNORECASE)


def git(*args: str) -> str:
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=45, env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Git command timed out; check repository access") from error
    if result.returncode != 0:
        # Avoid echoing remotes, credentials, or arbitrary stderr in JSON logs.
        raise RuntimeError(f"Git command failed (exit {result.returncode}); check repository access and the requested ref")
    return result.stdout


def normalized_source(value: str) -> str:
    return value.strip().rstrip("/").removesuffix(".git")


def inspect(project: Path, upstream: str, ref: str = "HEAD") -> dict:
    project = project.resolve()
    package = json.loads((project / "package.json").read_text(encoding="utf-8-sig"))
    if package.get("name") != "ai-text-makes-likes-human":
        raise ValueError("The target is not the ai-text-makes-likes-human service")
    if not (project / "scripts/sync-engine.ps1").is_file():
        raise ValueError("The service sync-engine.ps1 is missing")
    if not upstream or upstream.startswith("-") or any(c in upstream for c in "\r\n"):
        raise ValueError("Invalid upstream location")
    if ref != "HEAD" and not ref.startswith("refs/heads/"):
        raise ValueError("Use HEAD or a full refs/heads/branch ref")
    if any(c in ref for c in "*?[\r\n"):
        raise ValueError("Ref patterns are not supported")

    vendor = project / "vendor/humanize-engine"
    pin = {}
    for line in (vendor / "ENGINE_VERSION").read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            if key.strip() in pin:
                raise ValueError("Duplicate ENGINE_VERSION field")
            pin[key.strip()] = value.strip()
    if not OID.fullmatch(pin.get("commit", "")) or not pin.get("version"):
        raise ValueError("ENGINE_VERSION must contain a version and full commit hash")
    provenance = (vendor / "UPSTREAM.md").read_text(encoding="utf-8-sig")
    match = re.search(r"^Source:\s*(\S+)\s*$", provenance, re.MULTILINE)
    recorded_source = match.group(1) if match else None

    # ls-remote does not fetch objects or update the service's FETCH_HEAD/refs.
    output = git("ls-remote", "--symref", "--exit-code", "--", upstream, ref)
    latest = None
    resolved_ref = ref
    for line in output.splitlines():
        value, separator, name = line.partition("\t")
        if not separator or name != ref:
            continue
        if value.startswith("ref: "):
            resolved_ref = value[5:]
        elif OID.fullmatch(value):
            latest = value.lower()
    if latest is None:
        raise ValueError("The remote did not return an exact matching commit")

    pinned_commit = pin["commit"].lower()
    provenance_changed = normalized_source(recorded_source or "") != normalized_source(upstream)
    update_available = pinned_commit != latest
    status = (
        "update_available" if update_available else
        "provenance_update_required" if provenance_changed else "up_to_date"
    )
    worktree_status = git("-C", str(project), "status", "--porcelain=v1", "--untracked-files=normal")
    return {
        "status": status,
        "project_root": str(project),
        "upstream_url": upstream,
        "requested_ref": ref,
        "resolved_ref": resolved_ref,
        "pinned_version": pin["version"],
        "pinned_commit": pinned_commit,
        "latest_commit": latest,
        "recorded_source": recorded_source,
        "source_migration_required": provenance_changed,
        "update_available": update_available,
        "worktree_dirty": bool(worktree_status.strip()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--upstream-url", default=DEFAULT_UPSTREAM)
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()
    try:
        result = inspect(args.project_root, args.upstream_url, args.ref)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
