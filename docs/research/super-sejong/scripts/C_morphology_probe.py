#!/usr/bin/env python3
"""Small, transparent Kiwi/MeCab-ko morphology probe; no product integration.

Install in a throwaway virtual environment:
  python3.11 -m venv /tmp/sejong-morph-venv
  /tmp/sejong-morph-venv/bin/python -m pip install \
      'kiwipiepy==0.24.0' 'kiwipiepy-model==0.24.0' \
      'python-mecab-ko==1.3.7' 'python-mecab-ko-dic==2.1.1.post2'
  /tmp/sejong-morph-venv/bin/python C_morphology_probe.py --repeats 100 --trials 5

The sentence references below are hand-written. The MeCab boundary result is a
simple diagnostic based on punctuation tagged SF, not a MeCab sentence splitter.
This is a local API/latency probe, not an accuracy benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from importlib.metadata import version


CASES = (
    ("long_negation", "그는 신청하지 않았다.", ("그는 신청하지 않았다.",)),
    ("short_negation", "그는 신청을 안 했다.", ("그는 신청을 안 했다.",)),
    ("inability", "그는 신청할 수 없었다.", ("그는 신청할 수 없었다.",)),
    ("lexical_refusal", "그는 신청을 거부했다.", ("그는 신청을 거부했다.",)),
    ("subject_shift", "민수는 보고서를 읽었다. 지영이 검토했다.",
     ("민수는 보고서를 읽었다.", "지영이 검토했다.")),
    ("contrastive_topic", "사과는 먹었지만 배는 먹지 않았다.",
     ("사과는 먹었지만 배는 먹지 않았다.",)),
    ("quantity", "이 약은 세 시간마다 복용한다.",
     ("이 약은 세 시간마다 복용한다.",)),
    ("quoted_negation", "그는 '안 간다'고 말했다. 나는 남았다.",
     ("그는 '안 간다'고 말했다.", "나는 남았다.")),
    ("decimal", "가격은 3.14만 원이다. 내일 다시 보자.",
     ("가격은 3.14만 원이다.", "내일 다시 보자.")),
    ("question_answer", "정말 왔나요? 네, 지금 도착했습니다!",
     ("정말 왔나요?", "네, 지금 도착했습니다!")),
    ("particle_change", "서울과 부산은 다르다. 서울이 더 크다.",
     ("서울과 부산은 다르다.", "서울이 더 크다.")),
    ("obligation", "이용하지 않아도 됩니다. 반드시 신청해야 합니다.",
     ("이용하지 않아도 됩니다.", "반드시 신청해야 합니다.")),
    ("newline_boundary", "사업은 종료됐다\n다음 단계는 검토 중이다",
     ("사업은 종료됐다", "다음 단계는 검토 중이다")),
    ("sentence_inside_quote", '그는 말했다. "안 간다." 나는 남았다.',
     ("그는 말했다.", '"안 간다."', "나는 남았다.")),
)


def expected_spans(text: str, parts: tuple[str, ...]) -> list[list[int]]:
    spans = []
    cursor = 0
    for part in parts:
        start = text.find(part, cursor)
        if start < 0:
            raise ValueError(f"Expected segment not found: {part!r}")
        end = start + len(part)
        spans.append([start, end])
        cursor = end
    return spans


def sf_spans(text: str, tokens: list[dict]) -> list[list[int]]:
    """Punctuation-tag heuristic; intentionally not credited to MeCab."""
    result = []
    cursor = 0
    for token in tokens:
        if token["tag"] != "SF" or token["surface"] not in (".", "?", "!"):
            continue
        start = cursor
        while start < len(text) and text[start].isspace():
            start += 1
        end = token["end"]
        if start < end:
            result.append([start, end])
        cursor = end
    start = cursor
    while start < len(text) and text[start].isspace():
        start += 1
    if start < len(text):
        result.append([start, len(text)])
    return result


def summarize_tokens(tokens: list[dict]) -> dict:
    return {
        "tokens": [[t["surface"], t["tag"], t["start"], t["end"]] for t in tokens],
        "particle_tokens": [[t["surface"], t["tag"]] for t in tokens
                            if t["tag"].startswith("J")],
        # Surface/POS cues only. They do not establish semantic negation or scope.
        "negative_cue_tokens": [[t["surface"], t["tag"]] for t in tokens
                                if t["surface"] in {"안", "못", "않", "없"}],
    }


def benchmark(tag, texts: list[str], repeats: int, trials: int) -> dict:
    for text in texts:
        tag(text)
    durations = []
    for _ in range(trials):
        start = time.perf_counter()
        for _ in range(repeats):
            for text in texts:
                tag(text)
        durations.append(time.perf_counter() - start)
    median = statistics.median(durations)
    characters = repeats * sum(len(s) for s in texts)
    return {
        "trials_s": [round(v, 6) for v in durations],
        "median_s": round(median, 6),
        "calls_per_trial": repeats * len(texts),
        "characters_per_trial": characters,
        "median_characters_per_s": round(characters / median, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--trials", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1 or args.trials < 1:
        parser.error("--repeats and --trials must be positive")

    from kiwipiepy import Kiwi
    from mecab import MeCab

    kiwi = Kiwi(num_workers=1)
    mecab = MeCab()

    def kiwi_tag(text: str) -> list[dict]:
        return [{"surface": t.form, "tag": t.tag, "start": t.start,
                 "end": t.start + t.len} for t in kiwi.tokenize(text)]

    def mecab_tag(text: str) -> list[dict]:
        return [{"surface": t.surface, "tag": t.feature.pos,
                 "start": t.span.start, "end": t.span.end} for t in mecab.parse(text)]

    records = []
    exact = {"kiwi_sentence_splitter": 0, "mecab_sf_heuristic": 0}
    for name, text, expected in CASES:
        gold = expected_spans(text, expected)
        ktokens = kiwi_tag(text)
        mtokens = mecab_tag(text)
        kspans = [[s.start, s.end] for s in kiwi.split_into_sents(text)]
        mspans = sf_spans(text, mtokens)
        exact["kiwi_sentence_splitter"] += kspans == gold
        exact["mecab_sf_heuristic"] += mspans == gold
        records.append({
            "id": name,
            "text": text,
            "expected_sentence_spans": gold,
            "kiwi": {**summarize_tokens(ktokens), "sentence_spans": kspans},
            "mecab": {**summarize_tokens(mtokens),
                      "sf_heuristic_sentence_spans": mspans},
        })

    texts = [text for _, text, _ in CASES]
    fingerprint = hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()
    result = {
        "environment": {"python": platform.python_version(),
                        "platform": platform.platform(),
                        "machine": platform.machine()},
        "versions": {p: version(p) for p in (
            "kiwipiepy", "kiwipiepy-model", "python-mecab-ko",
            "python-mecab-ko-dic")},
        "sample_set_sha256": fingerprint,
        "sample_count": len(CASES),
        "sentence_exact_match_counts": exact,
        "benchmark": {
            "kiwi": benchmark(kiwi_tag, texts, args.repeats, args.trials),
            "mecab": benchmark(mecab_tag, texts, args.repeats, args.trials),
        },
        "samples": records,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
