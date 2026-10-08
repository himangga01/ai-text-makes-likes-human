"""Data contracts of Super Sejong Engine v2 (DESIGN.md 3.12).

Each JSON type maps one object of plan-<chunk>.json (schema sejong-plan/1), of
check-<chunk>-<attempt>.json (sejong-check/1) or of their nested values. Python fields are
snake_case and JSON keys camelCase (start_u16 <-> startU16); to_json() and from_json() do the
conversion so no other module spells a JSON key. Fields typed Dict[str, ...] are copied as they
are (gate, counts, stats, requestStatus keep their own key spelling).

Offsets: start/end are code-point offsets into the chunk text (Python string indices);
start_u16/end_u16 are the same positions in UTF-16 code units, for TypeScript.
The JSON Schemas in schemas/ are the contract; io.py validates against them, and
src/engine/sejong/types.ts mirrors these types.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple, Union, get_args, get_origin, get_type_hints

from . import CHECK_SCHEMA, ENGINE_ID, PLAN_SCHEMA, VERSION

# --------------------------------------------------------------------------
# closed vocabularies (the schemas list the same values)
# --------------------------------------------------------------------------
Level = Literal["HAPSYO", "HAEYO", "HAERA", "HAE", "HAO", "HAGE", "NOMINAL", "NONE"]
Mood = Literal["DECL", "INTERR", "IMPER", "PROPOS", "EXCL"]
UnitKind = Literal["body", "heading", "list", "quote", "button"]
InputKind = Literal["direct-text", "text-file"]
Strength = Literal["normal", "medium", "strong", "very-strong", "rewrite"]
# Plan mode: absent = the minimal-edit protocol of the four strengths; "rewrite" = strength rewrite (WP-19),
# decided per paragraph (rewrite.py). Only "rewrite" is ever written, so edit plans keep their exact JSON.
PlanMode = Literal["edit", "rewrite"]
Genre = Literal["general", "blog", "essay", "report", "notice", "document"]
DeterministicScope = Literal["all", "edited-only", "off"]
Tier = Literal["FIX", "SUGGEST", "LEAVE"]
RequestTier = Literal["FIX", "SUGGEST", "REVIEW"]          # REVIEW = open-review nomination
FindingAction = Literal["deterministic", "request", "report"]
SpanPolicy = Literal["freeze", "keep-token"]
Severity = Literal["hard", "soft", "info"]
SentenceStatus = Literal["unchanged", "deterministic", "accepted", "retry", "rejected", "reverted"]
GatePolicy = Literal["accept", "retry", "rollback", "accept-with-warning", "error"]

LEVELS = get_args(Level)
MOODS = get_args(Mood)
UNIT_KINDS = get_args(UnitKind)
INPUT_KINDS = get_args(InputKind)
STRENGTHS = get_args(Strength)
PLAN_MODES = get_args(PlanMode)
GENRES = get_args(Genre)
DETERMINISTIC_SCOPES = get_args(DeterministicScope)
TIERS = get_args(Tier)
REQUEST_TIERS = get_args(RequestTier)
FINDING_ACTIONS = get_args(FindingAction)
SPAN_POLICIES = get_args(SpanPolicy)
SEVERITIES = get_args(Severity)
SENTENCE_STATUSES = get_args(SentenceStatus)
GATE_POLICIES = get_args(GatePolicy)
SPAN_KINDS = ("quote", "number", "date", "money", "url", "email", "phone", "handle", "hashtag", "name",
              "code", "markdown", "heading", "footnote", "cmc", "colloquial", "discourse")
# Verification families (3.8). floor and runaway are always enforced; the rest have a mode.
FAMILIES = ("floor", "meaning", "voice", "cta", "flow", "clarity", "norms", "runaway", "nli")
REQUEST_OUTCOMES = ("FIXED", "UNTOUCHED", "STILL_PRESENT", "LOST", "DECLINED")
COUNT_KEYS = ("revertedSentences", "revertedByFamily", "collateralReverts", "voiceGrafts", "cmcRestored",
              "normFixes", "repairedParticles", "removedCommas", "restoredSentences")
# The legacy closed list parsed by candidate-review.ts; v2 emits at most P0_CHANGE_RATE.
LEGACY_REASONS = ("P0_CHANGE_RATE", "P1_STYLE_TARGET", "P2_ANTITHESIS", "P3_GOLDEN",
                  "P4_NUMBER_DROPPED", "P5_MODALITY", "P5_UNCERTAIN", "UNKNOWN")
# Violation, repair and shadow codes. The TS gate parser drops any other shadowFailures entry.
CODE_RE = re.compile(r"[a-z_]{1,60}\Z")


def is_code(value: object) -> bool:
    return isinstance(value, str) and CODE_RE.match(value) is not None


def gate_policy(exit_code: int, attempt: int) -> str:
    """Legacy decision table (engine_runtime/workflow.decision), kept by v2 (3.9)."""
    if exit_code == 3:
        return "error"
    if exit_code == 0:
        return "accept"
    if attempt == 1:
        return "retry"
    return "rollback" if exit_code == 2 else "accept-with-warning"


# --------------------------------------------------------------------------
# JSON conversion shared by every contract type
# --------------------------------------------------------------------------
def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _dump(value: Any) -> Any:
    if isinstance(value, _Json):
        return value.to_json()
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    return value


def _load(hint: Any, value: Any) -> Any:
    origin, args = get_origin(hint), get_args(hint)
    if hint is Any or origin is Literal:
        return value
    if origin is Union:                       # only Optional[X] is used
        if value is None:
            return None
        return _load(next(arg for arg in args if arg is not type(None)), value)
    if origin in (list, List):
        return [_load(args[0], item) for item in value]
    if origin in (tuple, Tuple):
        return tuple(_load(args[0], item) for item in value)
    if origin in (dict, Dict):
        return {key: _load(args[1], item) for key, item in value.items()}
    if isinstance(hint, type) and issubclass(hint, _Json):
        return hint.from_json(value)
    return value


class _Json:
    # Optional fields left out of the JSON when None; every other None is written as null.
    _OMIT_NONE: ClassVar[Tuple[str, ...]] = ()

    def to_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            if value is None and item.name in self._OMIT_NONE:
                continue
            out[_camel(item.name)] = _dump(value)
        return out

    @classmethod
    def from_json(cls, data: Dict[str, Any]):
        if not isinstance(data, dict):
            raise TypeError(f"{cls.__name__}: expected an object")
        hints = get_type_hints(cls)
        names = {_camel(item.name): item.name for item in fields(cls)}
        unknown = sorted(set(data) - set(names))
        if unknown:
            raise ValueError(f"{cls.__name__}: unknown keys {unknown}")
        return cls(**{names[key]: _load(hints[names[key]], value) for key, value in data.items()})


# --------------------------------------------------------------------------
# text model (internal; produced by text.segment in WP-1)
# --------------------------------------------------------------------------
@dataclass
class Unit(_Json):
    id: str                       # "S1", "S2", ... in document order
    start: int
    end: int
    start_u16: int
    end_u16: int
    para: int                     # paragraph index, 0-based
    kind: UnitKind
    text: str


@dataclass
class Document(_Json):
    text: str
    paragraphs: List[Tuple[int, int]]   # (start, end) code-point offsets
    units: List[Unit]


@dataclass
class Span(_Json):
    kind: str                     # one of SPAN_KINDS
    start: int
    end: int
    policy: SpanPolicy


# --------------------------------------------------------------------------
# plan (sejong-plan/1)
# --------------------------------------------------------------------------
@dataclass
class EngineInfo(_Json):
    id: str = ENGINE_ID
    version: str = VERSION


@dataclass
class ChunkInfo(_Json):
    index: int                    # 1-based
    total: int
    source_sha256: str            # of the chunk text as UTF-8
    chars: int                    # code points


@dataclass
class Options(_Json):
    input_kind: InputKind
    strength: Strength
    genre: Genre
    fix_colloquial: bool = False
    deterministic_fix: DeterministicScope = "all"
    open_review: bool = False
    allow_full_text: bool = False
    mode: Optional[PlanMode] = None
    _OMIT_NONE: ClassVar[Tuple[str, ...]] = ("mode",)


@dataclass
class VoiceSig(_Json):
    level: Level
    mood: Mood
    hon_si: bool                  # -시- on the final predicate
    si_count: int                 # -시- anywhere in the sentence (all of them are locked, 9.2a item 3)
    stance: Optional[str]         # ending family (ㅂ니다, 더라고요, 잖아요, ...); None when there is none
    persona: List[str]
    humble: bool
    cmc: List[str]
    discourse: List[str]
    final: str                    # final eojeol
    addressee: Optional[str] = None
    _OMIT_NONE: ClassVar[Tuple[str, ...]] = ("addressee",)


@dataclass
class PlanSentence(_Json):
    id: str
    start: int
    end: int
    start_u16: int
    end_u16: int
    para: int
    kind: UnitKind
    voice: VoiceSig
    cta: Optional[str] = None     # CTA ledger id ("C1") when the sentence is a CTA unit
    meaning: List[str] = field(default_factory=list)    # ledger entries such as "NEG:1"
    findings: List[str] = field(default_factory=list)   # finding ids


@dataclass
class CtaUnit(_Json):
    id: str
    sentence: str
    form: str                     # T6 forms: request, imperative, suggestion, ...
    force: int                    # 0-5
    tier: str                     # engage, contact, navigate, task
    polarity: str                 # pos, neg
    action: List[str]
    object: Optional[str]
    condition: Optional[str]
    deadline: List[str]
    channel: List[str]
    benefit: List[str]
    intensity: List[str]
    level: str                    # T6 speech level: hapsyo, haeyo, haera, hae, other
    hon_si: bool


@dataclass
class Finding(_Json):
    id: str                       # "F1", ...
    rule: str                     # "SSJ-A01", "CTA-SP1", "PROCESS_NOMINALIZATION", ...
    tier: Tier
    action: FindingAction
    sentence: str
    start: int
    end: int
    fix: Optional[str] = None     # expected form when the rule knows it (N03)


@dataclass
class Request(_Json):
    id: str                       # "R1", ...; one request per sentence
    sentence: str
    rules: List[str]
    tier: RequestTier
    allow_split: bool = False
    guides: List[str] = field(default_factory=list)


@dataclass
class DeterministicFix(_Json):
    finding: str
    sentence: str
    start: int
    end: int
    before: str
    after: str


@dataclass
class Profile(_Json):
    dominant: Level
    share: float
    mixed: bool
    line: str                     # one Korean context line for the prompt; never used in a decision


@dataclass
class Seam(_Json):
    prev: Tuple[int, int] = (0, 0)
    next: Tuple[int, int] = (0, 0)


@dataclass
class OpenReview(_Json):
    enabled: bool = False
    max_sentences: int = 0


@dataclass
class PlanParagraph(_Json):
    """One source paragraph of a rewrite plan (WP-19). The voice fields are the paragraph rule of rewrite.py:
    `level` is the dominant finite level of the source sentences (ties: the level used last), or NOMINAL/NONE when
    no sentence is finite; the counts are the questions, requests (imperative or 바랍니다-type) and proposals."""
    id: str                       # "P1", ... in document order
    para: int                     # Document.paragraphs index, 0-based
    start: int
    end: int
    start_u16: int
    end_u16: int
    sentences: List[str]          # ids of its units, in order
    editable: bool                # False for headings and wholly frozen paragraphs (kept verbatim)
    level: Level
    hon_si: bool                  # some -시- in the paragraph
    humble: bool                  # some humble form (드리다, 여쭙다, 뵙다, 모시다)
    persona: List[str]            # first-person classes used (voice.FIRST_PERSONS)
    questions: int
    requests: int
    proposals: int


@dataclass
class Plan(_Json):
    schema: str                   # PLAN_SCHEMA
    engine: EngineInfo
    chunk: ChunkInfo
    options: Options
    sentences: List[PlanSentence]
    protected: List[Span]
    cta_ledger: List[CtaUnit]
    findings: List[Finding]
    requests: List[Request]
    deterministic: List[DeterministicFix]
    profile: Profile
    seam: Seam
    open_review: OpenReview
    needs_model: bool
    stats: Dict[str, Any]
    paragraphs: Optional[List[PlanParagraph]] = None     # rewrite mode only
    _OMIT_NONE: ClassVar[Tuple[str, ...]] = ("paragraphs",)


# --------------------------------------------------------------------------
# check report (sejong-check/1)
# --------------------------------------------------------------------------
@dataclass
class Violation(_Json):
    code: str                     # lowercase, CODE_RE
    family: Optional[str] = None  # one of FAMILIES
    severity: Optional[Severity] = None
    sentence: Optional[str] = None
    detail: str = ""              # codes and labels only (e.g. "HAPSYO->HAEYO"), never document text
    keep: Optional[str] = None    # form the retry prompt asks the writer to keep
    _OMIT_NONE: ClassVar[Tuple[str, ...]] = ("family", "severity", "sentence", "keep")


@dataclass
class SentenceVerdict(_Json):
    id: str
    request: Optional[str]
    status: SentenceStatus
    codes: List[str] = field(default_factory=list)
    repairs: List[str] = field(default_factory=list)


@dataclass
class RetryItem(_Json):
    id: str                       # request id
    sentence: str
    violations: List[Violation]


def empty_request_status() -> Dict[str, int]:
    return {key: 0 for key in REQUEST_OUTCOMES}


def empty_counts() -> Dict[str, Any]:
    return {key: ({} if key == "revertedByFamily" else 0) for key in COUNT_KEYS}


@dataclass
class CheckReport(_Json):
    # The first five fields are the legacy gate JSON, unchanged, in the same order.
    gate: Dict[str, int]
    hard_failures: List[str]
    warning_reasons: Dict[str, Any]
    policy: GatePolicy
    shadow_failures: List[str]
    schema: str = CHECK_SCHEMA
    attempt: int = 1
    sentences: List[SentenceVerdict] = field(default_factory=list)
    retry: List[RetryItem] = field(default_factory=list)
    request_status: Dict[str, int] = field(default_factory=empty_request_status)
    counts: Dict[str, Any] = field(default_factory=empty_counts)
    change_rate: float = 0.0
