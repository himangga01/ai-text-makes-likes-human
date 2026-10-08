"""File helpers and contract validation for Super Sejong Engine v2.

Text is UTF-8 and newline-preserving: \\r\\n and lone \\r survive a read/write round trip byte for
byte (open(..., newline="")), so offsets computed on read stay valid on write.

Plan, check and writer-reply JSON are validated against schemas/*.schema.json by a small
hand-written validator (no jsonschema at runtime). It implements exactly the keywords the
schemas use and raises SchemaError on any other keyword, so a schema edit can never be
silently ignored. On top of the schema, plan_problems() and check_problems() test the
cross-references a schema cannot express (ids resolve, offsets nest, needsModel agrees).
Problem messages name JSON paths and keywords only, never document text.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Union

from .types import CheckReport, Plan, gate_policy

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
PathLike = Union[str, Path]


class SchemaError(Exception):
    """The schema itself uses something this validator does not implement."""


class ContractError(ValueError):
    def __init__(self, what: str, problems: List[str]):
        super().__init__(f"{what}: " + "; ".join(problems[:5]) + (" ..." if len(problems) > 5 else ""))
        self.problems = problems


# --------------------------------------------------------------------------
# text files
# --------------------------------------------------------------------------
def read_text(path: PathLike) -> str:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def write_text(path: PathLike, text: str) -> None:
    """Atomic replace, so a reader never sees a half-written chunk."""
    target = Path(path)
    fd, temp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temp, target)
    except BaseException:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise


def read_json(path: PathLike) -> Any:
    return json.loads(read_text(path))


def write_json(path: PathLike, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


# --------------------------------------------------------------------------
# JSON Schema subset (draft 2020-12 keywords used by schemas/)
# --------------------------------------------------------------------------
_ANNOTATIONS = {"$schema", "$id", "$comment", "$defs", "title", "description", "default", "examples"}
_KEYWORDS = _ANNOTATIONS | {
    "type", "enum", "const", "pattern", "minLength", "maxLength", "minimum", "maximum",
    "minItems", "maxItems", "uniqueItems", "items", "properties", "required",
    "additionalProperties", "propertyNames", "anyOf", "$ref"}


@lru_cache(maxsize=None)
def load_schema(name: str) -> Dict[str, Any]:
    """name = "plan", "check" or "response"."""
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=256)
def _regex(pattern: str) -> "re.Pattern":
    # ECMA-262 "$" matches only at the end; Python's also matches before a final "\n".
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        pattern = pattern[:-1] + r"\Z"
    return re.compile(pattern)


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "integer" if value.is_integer() else "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _same(a: Any, b: Any) -> bool:
    """JSON equality: true and 1 differ, 1 and 1.0 do not."""
    ka, kb = _kind(a), _kind(b)
    if {ka, kb} <= {"integer", "number"}:
        return a == b
    if ka != kb:
        return False
    if ka == "array":
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if ka == "object":
        return a.keys() == b.keys() and all(_same(a[key], b[key]) for key in a)
    return a == b


def _resolve(root: Dict[str, Any], ref: str) -> Dict[str, Any]:
    if not ref.startswith("#/"):
        raise SchemaError(f"only local $ref is supported: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def validate(instance: Any, schema: Dict[str, Any], root: Union[Dict[str, Any], None] = None,
             path: str = "$") -> List[str]:
    """Problems of instance against schema; [] means valid."""
    root = schema if root is None else root
    unknown = set(schema) - _KEYWORDS
    if unknown:
        raise SchemaError(f"unsupported keywords {sorted(unknown)} at {path}")
    problems: List[str] = []
    if "$ref" in schema:
        problems += validate(instance, _resolve(root, schema["$ref"]), root, path)
    kind = _kind(instance)
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not (kind in allowed or (kind == "integer" and "number" in allowed)):
            return problems + [f"{path}: type must be {'/'.join(allowed)}"]
    if "const" in schema and not _same(instance, schema["const"]):
        problems.append(f"{path}: const mismatch")
    if "enum" in schema and not any(_same(instance, option) for option in schema["enum"]):
        problems.append(f"{path}: not one of the allowed values")
    if "anyOf" in schema and not any(not validate(instance, option, root, path) for option in schema["anyOf"]):
        problems.append(f"{path}: matches no anyOf branch")
    if kind == "string":
        if "minLength" in schema and len(instance) < schema["minLength"]:
            problems.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            problems.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not _regex(schema["pattern"]).search(instance):
            problems.append(f"{path}: does not match pattern")
    if kind in ("integer", "number"):
        if "minimum" in schema and instance < schema["minimum"]:
            problems.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            problems.append(f"{path}: above {schema['maximum']}")
    if kind == "array":
        if "minItems" in schema and len(instance) < schema["minItems"]:
            problems.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            problems.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems") and any(_same(instance[i], instance[j])
                                             for i in range(len(instance)) for j in range(i)):
            problems.append(f"{path}: items are not unique")
        if "items" in schema:
            for index, item in enumerate(instance):
                problems += validate(item, schema["items"], root, f"{path}[{index}]")
    if kind == "object":
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                problems.append(f"{path}: missing {key}")
        extra = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if "propertyNames" in schema and validate(key, schema["propertyNames"], root, path):
                problems.append(f"{path}: property name not allowed")
                continue
            if key in properties:
                problems += validate(value, properties[key], root, f"{path}.{key}")
            elif extra is False:
                problems.append(f"{path}: unknown property")
            elif isinstance(extra, dict):
                problems += validate(value, extra, root, f"{path}.{key}")
    return problems


# --------------------------------------------------------------------------
# contract checks beyond the schema
# --------------------------------------------------------------------------
def _duplicates(items: List[Dict[str, Any]], what: str) -> List[str]:
    seen, problems = set(), []
    for item in items:
        if item["id"] in seen:
            problems.append(f"$.{what}: duplicate id {item['id']}")
        seen.add(item["id"])
    return problems


def plan_problems(data: Any) -> List[str]:
    problems = validate(data, load_schema("plan"))
    if problems:
        return problems
    for key in ("sentences", "findings", "requests", "ctaLedger"):
        problems += _duplicates(data[key], key)
    chars = data["chunk"]["chars"]
    if data["chunk"]["index"] > data["chunk"]["total"]:
        problems.append("$.chunk: index above total")
    sentences = {s["id"]: s for s in data["sentences"]}
    findings = {f["id"]: f for f in data["findings"]}
    ledger = {c["id"]: c for c in data["ctaLedger"]}
    previous_end = 0
    for index, s in enumerate(data["sentences"]):
        where = f"$.sentences[{index}]"
        if not (previous_end <= s["start"] <= s["end"] <= chars) or s["startU16"] > s["endU16"] \
                or s["startU16"] < s["start"] or s["endU16"] < s["end"]:
            problems.append(f"{where}: offsets out of order")
        previous_end = s["end"]
        for fid in s["findings"]:
            if fid not in findings or findings[fid]["sentence"] != s["id"]:
                problems.append(f"{where}.findings: {fid} does not point back to {s['id']}")
        if s["cta"] is not None and (s["cta"] not in ledger or ledger[s["cta"]]["sentence"] != s["id"]):
            problems.append(f"{where}.cta: {s['cta']} does not point back to {s['id']}")

    def inside(item: Dict[str, Any], where: str) -> None:
        sentence = sentences.get(item["sentence"])
        if sentence is None:
            problems.append(f"{where}: unknown sentence {item['sentence']}")
        elif not (sentence["start"] <= item["start"] <= item["end"] <= sentence["end"]):
            problems.append(f"{where}: range outside sentence {item['sentence']}")

    for index, f in enumerate(data["findings"]):
        inside(f, f"$.findings[{index}]")
        if f["id"] not in sentences.get(f["sentence"], {}).get("findings", [f["id"]]):
            problems.append(f"$.findings[{index}]: not listed by sentence {f['sentence']}")
    for index, span in enumerate(data["protected"]):
        if not span["start"] < span["end"] <= chars:
            problems.append(f"$.protected[{index}]: empty or out of range")
    for index, c in enumerate(data["ctaLedger"]):
        if c["sentence"] not in sentences:
            problems.append(f"$.ctaLedger[{index}]: unknown sentence {c['sentence']}")
    requested = set()
    for index, r in enumerate(data["requests"]):
        where = f"$.requests[{index}]"
        if r["sentence"] not in sentences:
            problems.append(f"{where}: unknown sentence {r['sentence']}")
        if r["sentence"] in requested:
            problems.append(f"{where}: second request for {r['sentence']}")
        requested.add(r["sentence"])
        if r["tier"] != "REVIEW":
            rules = {f["rule"] for f in data["findings"] if f["sentence"] == r["sentence"] and f["action"] == "request"}
            if not r["rules"] or not set(r["rules"]) <= rules:
                problems.append(f"{where}: rules are not request findings of {r['sentence']}")
    for index, d in enumerate(data["deterministic"]):
        where = f"$.deterministic[{index}]"
        inside(d, where)
        finding = findings.get(d["finding"])
        if finding is None or finding["action"] != "deterministic" or finding["sentence"] != d["sentence"]:
            problems.append(f"{where}: finding is not a deterministic finding of {d['sentence']}")
        if d["end"] - d["start"] != len(d["before"]):
            problems.append(f"{where}: range length differs from before")
    review = data["openReview"]
    if data["options"]["openReview"] != review["enabled"]:
        problems.append("$.openReview.enabled: differs from options.openReview")
    if not review["enabled"] and review["maxSentences"] != 0:
        problems.append("$.openReview.maxSentences: must be 0 when disabled")
    rewrite = data["options"].get("mode") == "rewrite"
    if rewrite != (data["options"]["strength"] == "rewrite") or rewrite != ("paragraphs" in data):
        problems.append("$.options.mode: rewrite mode, strength rewrite and paragraphs go together")
    elif rewrite:
        problems += _paragraph_problems(data, chars)
        if data["needsModel"] != any(p["editable"] for p in data["paragraphs"]):
            problems.append("$.needsModel: must equal (some paragraph is editable) in rewrite mode")
    elif data["needsModel"] != (bool(data["requests"]) or review["enabled"]):
        problems.append("$.needsModel: must equal (requests non-empty or openReview.enabled)")
    return problems


def _paragraph_problems(data: Dict[str, Any], chars: int) -> List[str]:
    """Rewrite plans (WP-19): P1..Pn in order, each covering a run of the plan's sentences, all of them once."""
    problems: List[str] = []
    order = [s["id"] for s in data["sentences"]]
    spans = {s["id"]: (s["start"], s["end"]) for s in data["sentences"]}
    covered: List[str] = []
    previous_end = 0
    for index, p in enumerate(data["paragraphs"]):
        where = f"$.paragraphs[{index}]"
        if p["id"] != f"P{index + 1}":
            problems.append(f"{where}: ids must run P1, P2, ... in order")
        if not (previous_end <= p["start"] <= p["end"] <= chars) or p["startU16"] > p["endU16"] \
                or p["startU16"] < p["start"] or p["endU16"] < p["end"]:
            problems.append(f"{where}: offsets out of order")
        previous_end = p["end"]
        for sid in p["sentences"]:
            a, b = spans.get(sid, (-1, -1))
            if not p["start"] <= a <= b <= p["end"]:
                problems.append(f"{where}.sentences: {sid} is not inside the paragraph")
        covered += p["sentences"]
    if covered != order:
        problems.append("$.paragraphs: must list every sentence once, in order")
    return problems


def check_problems(data: Any) -> List[str]:
    problems = validate(data, load_schema("check"))
    if problems:
        return problems
    exit_code, attempt = data["gate"]["exit_code"], data["attempt"]
    if data["policy"] != gate_policy(exit_code, attempt):
        problems.append("$.policy: differs from the legacy decision table")
    if data["hardFailures"] and exit_code not in (2, 3):
        problems.append("$.hardFailures: present with exit code 0 or 1")
    if set(data["warningReasons"]["codes"]) - {"P0_CHANGE_RATE"}:
        problems.append("$.warningReasons.codes: v2 emits at most P0_CHANGE_RATE")
    problems += _duplicates(data["sentences"], "sentences") + _duplicates(data["retry"], "retry")
    retrying = {s["id"]: s["request"] for s in data["sentences"] if s["status"] == "retry"}
    if data["retry"] and (attempt != 1 or data["policy"] != "retry"):
        problems.append("$.retry: only at attempt 1 with policy retry")
    # One entry per retried request: a sentence or open-review request names its one sentence; a paragraph of rewrite
    # mode (P…, WP-19) names its first sentence and stands for every sentence of the paragraph.
    if {r["id"] for r in data["retry"]} != set(retrying.values()) \
            or any(retrying.get(r["sentence"]) != r["id"] for r in data["retry"]) \
            or any(not str(request).startswith("P") and sentence not in {r["sentence"] for r in data["retry"]}
                   for sentence, request in retrying.items()):
        problems.append("$.retry: must list exactly the sentences with status retry and their requests")
    return problems


def response_problems(data: Any) -> List[str]:
    """Schema only; ids against the plan and the rewrittenText rule are checked by apply (3.6)."""
    return validate(data, load_schema("response"))


# --------------------------------------------------------------------------
# typed read/write
# --------------------------------------------------------------------------
def read_plan(path: PathLike) -> Plan:
    data = read_json(path)
    problems = plan_problems(data)
    if problems:
        raise ContractError("invalid plan", problems)
    return Plan.from_json(data)


def write_plan(path: PathLike, plan: Plan) -> None:
    data = plan.to_json()
    problems = plan_problems(data)
    if problems:
        raise ContractError("invalid plan", problems)
    write_json(path, data)


def read_check(path: PathLike) -> CheckReport:
    data = read_json(path)
    problems = check_problems(data)
    if problems:
        raise ContractError("invalid check report", problems)
    return CheckReport.from_json(data)


def write_check(path: PathLike, report: CheckReport) -> None:
    data = report.to_json()
    problems = check_problems(data)
    if problems:
        raise ContractError("invalid check report", problems)
    write_json(path, data)
