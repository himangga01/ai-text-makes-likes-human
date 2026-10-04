"""Super Sejong Engine v2: product-owned Korean rewrite engine (docs/research/super-sejong/v2/DESIGN.md).

Standard library only, Python >= 3.9. Nothing here is wired into the running service yet:
SUPER_SEJONG_ENGINE defaults to legacy, and the legacy path never imports this package.

ENGINE_VERSION (next to this file) uses the vendor's key=value format:
    id=super-sejong      must equal ENGINE_ID
    version=X.Y.Z        semantic version, recorded in every plan ("engine.version")
    schema=N             contract version of plan/check JSON ("sejong-plan/N", "sejong-check/N")

Import modules as a package (engine_runtime/ on sys.path, then `import sejong.types`).
Never put this directory itself on sys.path: types.py and io.py would shadow the stdlib.
"""
from __future__ import annotations

import re
from pathlib import Path

ENGINE_ID = "super-sejong"
VERSION_FILE = Path(__file__).resolve().parent / "ENGINE_VERSION"
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?\Z")


def read_engine_version(path: Path = VERSION_FILE) -> dict:
    """{"id", "version", "schema"} from ENGINE_VERSION; any other shape is a packaging error."""
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition("=")
        if not sep or key in entries:
            raise ValueError(f"ENGINE_VERSION: malformed line {line!r}")
        entries[key] = value
    if sorted(entries) != ["id", "schema", "version"]:
        raise ValueError("ENGINE_VERSION: keys must be exactly id, version, schema")
    if entries["id"] != ENGINE_ID or not SEMVER.match(entries["version"]) \
            or not re.fullmatch(r"[1-9][0-9]{0,3}", entries["schema"]):
        raise ValueError("ENGINE_VERSION: invalid id, version or schema")
    return {"id": entries["id"], "version": entries["version"], "schema": int(entries["schema"])}


_VERSION = read_engine_version()
VERSION: str = _VERSION["version"]
SCHEMA_VERSION: int = _VERSION["schema"]
PLAN_SCHEMA = f"sejong-plan/{SCHEMA_VERSION}"
CHECK_SCHEMA = f"sejong-check/{SCHEMA_VERSION}"
