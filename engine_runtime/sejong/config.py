"""Super Sejong Engine v2 configuration from environment variables (DESIGN.md 5.4).

Every variable is read the same way: trimmed, lower-cased, unset or empty means the default,
and an unknown value falls back to the default instead of failing the job (as
super_sejong.mode() does). Variables whose value was not used as given are listed in
Flags.rejected so diagnostics can report them; the values themselves are never logged.

    SUPER_SEJONG_ENGINE            legacy | v2                 engine that produces the delivered text
    SUPER_SEJONG_MODE              enforce | shadow | off      v2 family defaults; under legacy the v1
                                                               meaning guards read it via super_sejong.mode()
    SUPER_SEJONG_GATE_<FAMILY>     enforce | shadow | off      per-family override, FAMILY in OVERRIDABLE;
                                                               NLI=enforce is rejected and becomes shadow (OD 7)
    SUPER_SEJONG_V2_SHADOW         0 | 1                       legacy jobs also run v2 analyse/verify for logs
    SUPER_SEJONG_FIX_COLLOQUIAL    0 | 1                       OD 2 opt-in (할께 family -> FIX)
    SUPER_SEJONG_DETERMINISTIC_FIX all | edited-only | off     scope of deterministic FIX rules
    SUPER_SEJONG_OPEN_REVIEW       medium | strong | always | off   lowest strength with open review
    SUPER_SEJONG_GENRE_DEFAULT     general | blog | essay | report | notice | document
    SUPER_SEJONG_WORKER            off | on                    optional persistent Python worker
    SUPER_SEJONG_KIWI              off | worker                Kiwi only inside the worker; without it, off

The floor and runaway families are enforced in every mode and have no variable. Codes in SHADOW_CODES
never go above shadow, whatever their family's mode.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple

OVERRIDABLE = ("meaning", "voice", "cta", "flow", "clarity", "norms", "nli")
# Codes that stay in shadow while their family enforces (the flow family keeps its own list in flow.py).
# content_dropped (meaning, WP-10b): 14/374 seed gold replacements blocked (3.7%). WP-10d licensed the missing
# redundancy pairs, the light head noun of "N 작업을 진행하다", support verbs (결정을 내리다), postpositional verbs
# (에 대해서) and a purpose noun carried by 위해: 0/374 on gold. It still stays in shadow, because constructed
# fluency edits outside the seed (결론적으로 말하자면 -> 결론적으로, 매진을 기록했다 -> 매진되었다) drop words on
# purpose; the drops that matter are enforced as key_word_dropped (meaning.py). Promote it from real shadow counts.
SHADOW_CODES: Tuple[str, ...] = ("content_dropped",)
ALWAYS_ENFORCED = ("floor", "runaway")
FAMILY_MODES = ("enforce", "shadow", "off")
_CHOICES = {
    "SUPER_SEJONG_ENGINE": ("legacy", "v2"),
    "SUPER_SEJONG_MODE": FAMILY_MODES,
    "SUPER_SEJONG_V2_SHADOW": ("0", "1"),
    "SUPER_SEJONG_FIX_COLLOQUIAL": ("0", "1"),
    "SUPER_SEJONG_DETERMINISTIC_FIX": ("all", "edited-only", "off"),
    # Lead decision 2026-10-04 (DESIGN 9.2a item 2): medium gets the open review, so it is the default.
    "SUPER_SEJONG_OPEN_REVIEW": ("medium", "strong", "always", "off"),
    "SUPER_SEJONG_GENRE_DEFAULT": ("general", "blog", "essay", "report", "notice", "document"),
    "SUPER_SEJONG_WORKER": ("off", "on"),
    "SUPER_SEJONG_KIWI": ("off", "worker"),
}
# Strengths that get the open review for each SUPER_SEJONG_OPEN_REVIEW value.
_OPEN_REVIEW = {
    "medium": ("medium", "strong", "very-strong"),
    "strong": ("strong", "very-strong"),
    "always": ("normal", "medium", "strong", "very-strong"),
    "off": (),
}
# Family modes when no override is set (3.8, 5.4). clarity has no false-block estimate yet, so it
# starts in shadow; NLI is optional and needs a licence-clean model, so it starts off.
_DEFAULTS = {
    "enforce": {"meaning": "enforce", "voice": "enforce", "cta": "enforce", "flow": "enforce",
                "clarity": "shadow", "norms": "enforce", "nli": "off"},
    "shadow": {"meaning": "enforce", "voice": "shadow", "cta": "shadow", "flow": "shadow",
               "clarity": "shadow", "norms": "shadow", "nli": "off"},
    "off": {family: "off" for family in OVERRIDABLE},
}


@dataclass(frozen=True)
class Flags:
    engine: str = "legacy"
    mode: str = "enforce"
    gates: Dict[str, str] = field(default_factory=dict, hash=False)   # overrides only, family -> mode
    v2_shadow: bool = False
    fix_colloquial: bool = False
    deterministic_fix: str = "all"
    open_review: str = "medium"
    genre_default: str = "general"
    worker: bool = False
    kiwi: str = "off"
    rejected: Tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Flags":
        env = os.environ if env is None else env
        rejected: List[str] = []

        def choice(name: str) -> str:
            allowed = _CHOICES[name]
            value = (env.get(name) or "").strip().lower()
            if not value:
                return allowed[0]
            if value not in allowed:
                rejected.append(name)
                return allowed[0]
            return value

        values = {name: choice(name) for name in _CHOICES}
        gates: Dict[str, str] = {}
        for family in OVERRIDABLE:
            name = f"SUPER_SEJONG_GATE_{family.upper()}"
            value = (env.get(name) or "").strip().lower()
            if not value:
                continue
            if value not in FAMILY_MODES:
                rejected.append(name)
            elif family == "nli" and value == "enforce":
                rejected.append(name)          # no licence-clean NLI model: shadow at most (OD 7)
                gates[family] = "shadow"
            else:
                gates[family] = value
        worker = values["SUPER_SEJONG_WORKER"] == "on"
        kiwi = values["SUPER_SEJONG_KIWI"]
        if kiwi == "worker" and not worker:
            rejected.append("SUPER_SEJONG_KIWI")   # never per spawn (OD 7)
            kiwi = "off"
        return cls(engine=values["SUPER_SEJONG_ENGINE"], mode=values["SUPER_SEJONG_MODE"], gates=gates,
                   v2_shadow=values["SUPER_SEJONG_V2_SHADOW"] == "1",
                   fix_colloquial=values["SUPER_SEJONG_FIX_COLLOQUIAL"] == "1",
                   deterministic_fix=values["SUPER_SEJONG_DETERMINISTIC_FIX"],
                   open_review=values["SUPER_SEJONG_OPEN_REVIEW"],
                   genre_default=values["SUPER_SEJONG_GENRE_DEFAULT"],
                   worker=worker, kiwi=kiwi, rejected=tuple(rejected))


def select_engine(env: Optional[Mapping[str, str]] = None) -> str:
    """'legacy' | 'v2'; anything but v2 keeps the legacy engine (same as Flags.from_env(env).engine)."""
    return Flags.from_env(env).engine


def family_mode(flags: Flags, family: str) -> str:
    """'enforce' | 'shadow' | 'off' for one v2 verification family (any case: 'VOICE' == 'voice').

    Describes v2 only; the legacy engine keeps the v1 semantics of SUPER_SEJONG_MODE.
    """
    name = family.strip().lower()
    if name in ALWAYS_ENFORCED:
        return "enforce"
    if name not in OVERRIDABLE:
        raise ValueError(f"unknown Super Sejong family: {family!r}")
    return flags.gates.get(name, _DEFAULTS[flags.mode][name])


def suggest_requests_enabled(flags: Flags) -> bool:
    """SUPER_SEJONG_MODE=off keeps FIX requests and deterministic fixes only (5.4)."""
    return flags.mode != "off"


def open_review_enabled(flags: Flags, strength: str) -> bool:
    """Whether a chunk at this strength gets the open review (3.4). Off together with SUGGEST requests,
    because open-review nominations are optional edits like SUGGEST requests."""
    if strength not in _OPEN_REVIEW["always"]:
        raise ValueError(f"unknown strength: {strength!r}")
    return suggest_requests_enabled(flags) and strength in _OPEN_REVIEW[flags.open_review]
