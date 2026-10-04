#!/usr/bin/env python3
"""Deterministic descriptors for eight constructed Korean examples.

No grade level, readability score, external corpus, or third-party package is used.
Run: python3 docs/research/super-sejong/scripts/S_readability_probe.py
"""

from __future__ import annotations

import hashlib
import json
import re
from statistics import mean


SAMPLES = [
    {
        "id": "notice_split",
        "genre": "public_notice",
        "text": "신청은 금요일 오후 여섯 시에 끝납니다. 서류가 빠졌다면 그전에 다시 내세요.",
    },
    {
        "id": "notice_joined",
        "genre": "public_notice",
        "text": "신청은 금요일 오후 여섯 시에 끝나므로, 서류가 빠졌다면 그전에 다시 내시기 바랍니다.",
    },
    {
        "id": "report_split",
        "genre": "work_report",
        "text": "장비를 점검했다. 배터리는 정상이고 센서가 고장 났다.",
    },
    {
        "id": "report_joined",
        "genre": "work_report",
        "text": "장비를 점검한 결과, 배터리는 정상으로 확인되었지만 센서는 고장 난 것으로 나타났다.",
    },
    {
        "id": "technical_short",
        "genre": "technical",
        "text": "p값이 0.05보다 작다.",
    },
    {
        "id": "narrative_long",
        "genre": "literary",
        "text": "비가 그친 뒤 골목에 늦은 햇살이 들고, 젖은 벽돌마다 작은 빛이 남았다.",
    },
    {
        "id": "headline_fragment",
        "genre": "headline",
        "text": "신청 마감: 금요일 18시",
    },
    {
        "id": "decimal_boundary",
        "genre": "technical",
        "text": "수치는 3.5다. 다시 확인했다.",
    },
]

HANGUL = re.compile(r"[가-힣]")
BOUNDARY = re.compile(r"(?<=[.!?])\s+")
CONNECTIVE_CUE = re.compile(r"[가-힣]+(?:지만|으므로|므로|어서|면서|는데|더라도|다면)(?=\s|[,.;!?]|$)")


def describe(text: str) -> dict[str, int | float]:
    text = text.strip()
    sentences = [part.strip() for part in BOUNDARY.split(text) if part.strip()]
    # Text lacking terminal punctuation is one orthographic span, not a verified
    # grammatical sentence; this is why the headline example is retained.
    if not sentences and text:
        sentences = [text]
    eojeol_by_sentence = [len(part.split()) for part in sentences]
    hangul_by_sentence = [len(HANGUL.findall(part)) for part in sentences]
    return {
        "orthographic_spans": len(sentences),
        "eojeol": len(text.split()),
        "hangul_syllable_blocks": len(HANGUL.findall(text)),
        "mean_eojeol_per_span": round(mean(eojeol_by_sentence), 3) if sentences else 0.0,
        "max_eojeol_per_span": max(eojeol_by_sentence, default=0),
        "mean_hangul_blocks_per_span": round(mean(hangul_by_sentence), 3) if sentences else 0.0,
        "commas": text.count(","),
        "connective_cue_hits": len(CONNECTIVE_CUE.findall(text)),
    }


def main() -> None:
    canonical = json.dumps(SAMPLES, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    print(json.dumps({
        "provenance": "All eight examples constructed by an AI assistant for this probe",
        "canonicalization": "json.dumps(SAMPLES, ensure_ascii=False, sort_keys=True, separators=(',', ':')) encoded UTF-8",
        "sample_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "measurements": [
            {"id": sample["id"], "genre": sample["genre"], **describe(sample["text"])}
            for sample in SAMPLES
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
