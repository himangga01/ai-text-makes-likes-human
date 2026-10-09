"""JSON-file adapter to the bundled shared TypeScript policies; no model or server."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def _runtime():
    packaged = ROOT / "engine_runtime/skill-bridge.cjs"
    bridge = packaged if packaged.is_file() else ROOT / "build-resources/skill-bridge/skill-bridge.cjs"
    # Bundled runtime first; hosts and the portal server may pass their own Node via NODE_COMMAND.
    node = ROOT / ("node/node.exe" if os.name == "nt" else "node/node")
    configured = os.environ.get("NODE_COMMAND")
    executable = str(node) if node.is_file() else configured if configured and Path(configured).is_file() else \
        (None if packaged.is_file() and os.name == "nt" else shutil.which("node"))
    return executable, bridge


def available() -> bool:
    """File jobs use the bridge's structural guard when Node and the bridge exist."""
    executable, bridge = _runtime()
    return bool(executable) and bridge.is_file()


def invoke(operation, **payload):
    executable, bridge = _runtime()
    if not executable or not bridge.is_file():
        # Direct text always needs it; under SUPER_SEJONG_ENGINE=v2 every job whose chunk needs a writer prompt
        # (context-v2) does too, TXT/MD files included (code review 2026-10-05: the message named direct text only).
        raise ValueError("Direct text and Super Sejong v2 prompts require the bundled Node bridge "
                         "(development: node scripts/build-skill-bridge.mjs; Node >=24.19.0)")
    with tempfile.TemporaryDirectory(prefix="humanize-bridge-") as temporary:
        source, output = Path(temporary) / "request.json", Path(temporary) / "response.json"
        source.write_text(json.dumps({"operation": operation, **payload}, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([executable, str(bridge), str(source), str(output)], capture_output=True, timeout=120,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            raise ValueError("Local text bridge failed; no unvalidated result was accepted")
        return json.loads(output.read_text(encoding="utf-8"))


def options(input_kind=None, strength=None, offline=False):
    # Preserve file/legacy operation without installing or starting Node. `offline` (Super Sejong v2 jobs) also
    # answers direct text from the checks below, which are exactly parseRewriteOptions: v2 starts Node only for a
    # job that needs a writer prompt or a reply check.
    if input_kind not in (None, "direct-text", "text-file"):
        raise ValueError("Invalid input kind")
    if strength is not None and strength not in ("normal", "medium", "strong", "very-strong", "rewrite"):
        raise ValueError("Invalid strength")
    if input_kind is None:
        if strength is not None:
            raise ValueError("Strength requires explicit input kind")
        return None
    if input_kind == "text-file":
        if strength not in (None, "normal"):
            raise ValueError("Strength is available for direct text only")
        return {"inputKind": input_kind, "strength": "normal"}
    if offline:
        return {"inputKind": input_kind, "strength": strength or "normal"}
    return invoke("options", inputKind=input_kind, strength=strength or "normal")["options"]
