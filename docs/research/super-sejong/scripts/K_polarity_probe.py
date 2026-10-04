#!/usr/bin/env python3
"""Research-only Korean polarity-signature probe; no product integration.

Run: python3 docs/research/super-sejong/scripts/K_polarity_probe.py --summary

The hand-written contrast set is illustrative, not a representative benchmark.
The regex rules do not implement a Korean morphological or syntactic parser.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
from engine_runtime.super_sejong import changed_polarity  # noqa: E402


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    source: str
    candidate: str
    drift: bool
    reason: str


# Gold labels judge polarity, ability, and negative-scope drift, not every
# possible change in meaning. These sentences are original, hand-written cases.
CASES = (
    Case("M1", "morphology", "민수는 신청하지 않는다.", "민수는 신청한다.", True, "long negative removed"),
    Case("M2", "morphology", "민수는 안 먹는다.", "민수는 먹는다.", True, "short negative removed"),
    Case("M3", "morphology", "민수는 못 걷는다.", "민수는 걷는다.", True, "inability removed"),
    Case("M4", "morphology", "민수는 먹지 못한다.", "민수는 먹는다.", True, "long inability removed"),
    Case("M5", "morphology", "민수는 안 먹는다.", "민수는 먹지 않는다.", False, "short/long equivalent in this context"),
    Case("M6", "morphology", "민수는 못 먹는다.", "민수는 먹지 못한다.", False, "short/long inability equivalent"),
    Case("M7", "morphology", "상자 안 자료를 읽는다.", "상자 안 자료를 확인한다.", False, "locative 안, not negation"),
    Case("M8", "morphology", "민수는 읽는다.", "민수는 천천히 읽는다.", False, "no polarity cue"),
    Case("L1", "lexical", "민수는 제안을 거부했다.", "민수는 제안을 승인했다.", True, "refusal replaced by approval"),
    Case("L2", "lexical", "담당자가 요청을 거절했다.", "담당자가 요청을 수락했다.", True, "refusal replaced by acceptance"),
    Case("L3", "lexical", "민수는 답을 모른다.", "민수는 답을 안다.", True, "not-knowing replaced by knowing"),
    Case("L4", "lexical", "규정은 사용을 금지한다.", "규정은 사용을 허용한다.", True, "prohibition replaced by permission"),
    Case("L5", "lexical", "민수는 제안을 거부했다.", "민수는 제안을 거절했다.", False, "refusal paraphrase in this context"),
    Case("L6", "lexical", "자료가 없다.", "자료가 존재하지 않는다.", False, "absence paraphrase"),
    Case("D1", "double_negation", "변화가 없지는 않다.", "변화가 없다.", True, "double negation collapsed to absence"),
    Case("D2", "double_negation", "민수는 찬성하지 않은 것은 아니다.", "민수는 찬성하지 않는다.", True, "metalinguistic double negation lost"),
    Case("D3", "double_negation", "민수는 반대하지 않는 것은 아니다.", "민수는 반대하지 않는다.", True, "double negation lost"),
    Case("D4", "double_negation", "변화가 없지는 않다.", "변화가 없지는 않아요.", False, "same cues, different politeness"),
    Case("D5", "double_negation", "민수는 안 먹지 않는다.", "민수는 먹지 않는다.", True, "one negative removed"),
    Case("D6", "double_negation", "변화가 없지는 않다.", "변화가 없다기보다는 적다.", True, "qualified positive changed to lack"),
    Case("S1", "scope", "민수는 먹고 자지 않는다.", "민수는 먹지 않고 잔다.", True, "negation moved from sleeping to eating"),
    Case("S2", "scope", "민수는 안 읽고 쓴다.", "민수는 읽고 안 쓴다.", True, "negation moved between verbs"),
    Case("S3", "scope", "민수는 오늘 안 간다.", "민수는 내일 안 간다.", True, "negative event time changed"),
    Case("S4", "scope", "민수는 일하지 않아도 된다.", "민수는 일해야 한다.", True, "absence of obligation changed to obligation"),
    Case("S5", "scope", "민수는 안 먹는다.", "민수는 먹지 않는다.", False, "negation form changed, target stable"),
    Case("S6", "scope", "오늘은 민수가 안 먹는다.", "민수는 오늘 안 먹는다.", False, "word order changed, target stable"),
    Case("C1", "contrast", "사과는 먹지만 배는 먹지 않는다.", "사과는 먹지 않지만 배는 먹는다.", True, "negation moved between contrastive clauses"),
    Case("C2", "contrast", "A안은 거부하지만 B안은 승인한다.", "A안은 승인하지만 B안은 거부한다.", True, "refusal moved between alternatives"),
    Case("C3", "contrast", "민수는 안 가지만 지영은 간다.", "민수는 가지만 지영은 안 간다.", True, "negative person swapped"),
    Case("C4", "contrast", "사과는 먹지만 배는 먹지 않는다.", "배는 먹지 않지만 사과는 먹는다.", False, "clauses reordered without meaning change"),
    Case("C5", "contrast", "민수는 안 먹지만 지영은 먹는다.", "민수는 먹지 않지만 지영은 먹는다.", False, "same first-clause negation"),
    Case("C6", "contrast", "사과는 먹지만 배는 먹지 않는다.", "사과는 먹지만 배는 먹지 않아요.", False, "politeness shift, polarity unchanged"),
    Case("P1", "prohibitive", "문을 열지 마라.", "문을 열어라.", True, "prohibition removed"),
    Case("P2", "prohibitive", "문을 열지 마라.", "문을 열지 마세요.", False, "politeness changed, prohibition retained"),
    Case("P3", "prohibitive", "문을 열지 마라.", "문을 닫지 마라.", True, "prohibited action changed"),
    Case("P4", "prohibitive", "문을 열지 마라.", "문을 열지 말아라.", False, "prohibition paraphrase"),
)


CLAUSE_BREAK = re.compile(r"(?<=지만)|반면|[.!?;]|\n")
LONG = re.compile(r"([가-힣]+?)지(?:는|도)?\s*(않|못)[가-힣]*")
PROHIBITIVE = re.compile(r"([가-힣]+?)지\s*(?:마|말)[가-힣]*")
SHORT = re.compile(r"(?<!\S)(안|못)\s+([가-힣]+)")
POSSIBILITY = re.compile(r"([가-힣]+)\s+수\s+없[가-힣]*")
LEXICAL = re.compile(r"(거부|거절|반대|금지|불허|없|아니|모르|모른|몰라)(?:[가-힣]*)")
FINITE = re.compile(r"(?:는다|한다|하다|다|요|고|지만|지|서|면|니|어|아)$")
LEX_KIND = {
    "거부": "REFUSE", "거절": "REFUSE", "반대": "OPPOSE",
    "금지": "PROHIBIT", "불허": "PROHIBIT", "없": "LACK",
    "아니": "NONIDENTITY", "모르": "IGNORANCE", "모른": "IGNORANCE", "몰라": "IGNORANCE",
}


def stem(surface: str) -> str:
    """Very rough ending stripping; not a lemmatizer."""
    token = surface.strip(".,!?; ")
    for ending in ("습니다", "어요", "아요", "는다", "한다", "하다", "지만", "다", "요", "고", "서", "면"):
        if token.endswith(ending) and len(token) > len(ending):
            return token[: -len(ending)]
    return token


def clause_signature(clause: str) -> tuple[tuple[str, str], ...]:
    events: list[tuple[str, str]] = []
    consumed: list[tuple[int, int]] = []

    for match in LONG.finditer(clause):
        events.append(("NEG" if match.group(2) == "않" else "UNABLE", stem(match.group(1))))
        consumed.append(match.span(2))
    for match in PROHIBITIVE.finditer(clause):
        events.append(("PROHIBIT_COMMAND", stem(match.group(1))))
    for match in POSSIBILITY.finditer(clause):
        events.append(("UNABLE", "수"))
        consumed.append(match.span())
    for match in SHORT.finditer(clause):
        target = match.group(2)
        if FINITE.search(target):
            events.append(("NEG" if match.group(1) == "안" else "UNABLE", stem(target)))
            consumed.append(match.span(1))
    for match in LEXICAL.finditer(clause):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        events.append((LEX_KIND[match.group(1)], ""))
    return tuple(sorted(events))


def signature(text: str) -> tuple[tuple[tuple[str, str], ...], ...]:
    return tuple(clause_signature(part.strip()) for part in CLAUSE_BREAK.split(text) if part.strip())


def predicted_drift(source: str, candidate: str) -> bool:
    return signature(source) != signature(candidate)


def metrics(rows: list[dict], key: str) -> dict:
    tp = sum(row["drift"] and row[key] for row in rows)
    fp = sum(not row["drift"] and row[key] for row in rows)
    fn = sum(row["drift"] and not row[key] for row in rows)
    tn = sum(not row["drift"] and not row[key] for row in rows)
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true", help="print metrics and error IDs only")
    args = parser.parse_args()
    rows = []
    for case in CASES:
        rows.append({"id": case.id, "category": case.category, "source": case.source,
                     "candidate": case.candidate, "drift": case.drift, "reason": case.reason,
                     "baseline": changed_polarity(case.source, case.candidate),
                     "prototype": predicted_drift(case.source, case.candidate),
                     "source_signature": signature(case.source),
                     "candidate_signature": signature(case.candidate)})
    output = {
        "case_count": len(rows),
        "baseline_file_sha256": hashlib.sha256((REPO / "engine_runtime/super_sejong.py").read_bytes()).hexdigest(),
        "case_set_sha256": hashlib.sha256("\n".join(
            f"{c.id}|{c.source}|{c.candidate}|{int(c.drift)}" for c in CASES
        ).encode()).hexdigest(),
        "baseline": metrics(rows, "baseline"),
        "prototype": metrics(rows, "prototype"),
        "by_category": {category: {"baseline": metrics([r for r in rows if r["category"] == category], "baseline"),
                                   "prototype": metrics([r for r in rows if r["category"] == category], "prototype")}
                        for category in sorted({r["category"] for r in rows})},
        "prototype_false_positives": [r["id"] for r in rows if not r["drift"] and r["prototype"]],
        "prototype_false_negatives": [r["id"] for r in rows if r["drift"] and not r["prototype"]],
        "baseline_false_positives": [r["id"] for r in rows if not r["drift"] and r["baseline"]],
        "baseline_false_negatives": [r["id"] for r in rows if r["drift"] and not r["baseline"]],
    }
    if not args.summary:
        output["cases"] = rows
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
