#!/usr/bin/env python3
"""Small, dependency-free Korean *constructed-style* diagnostic.

All sample texts below were composed for this probe by an AI assistant. Neither
style label denotes human authorship or a particular generator. No external
corpus or personal data is loaded. Run: python3 I_corpus_probe.py
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from statistics import mean


SAMPLES = [
    {
        "topic": "meeting",
        "style": "concrete",
        "text": "회의는 열 분 늦게 시작했다. 민지가 지난주 자료를 꺼내자 빠진 숫자가 보여서, 우리는 표부터 다시 확인했다.",
    },
    {
        "topic": "meeting",
        "style": "formulaic",
        "text": "회의는 예정된 시간보다 늦게 시작되었습니다. 또한, 자료 검토 과정에서 누락된 수치를 확인하였으며, 이를 다시 점검하였습니다.",
    },
    {
        "topic": "delivery",
        "style": "concrete",
        "text": "택배가 온다는 문자를 받고 집에 남았다. 오후 네 시가 지나도 소식이 없어서 기사님께 문자를 보냈다.",
    },
    {
        "topic": "delivery",
        "style": "formulaic",
        "text": "택배 도착 안내를 받은 뒤 배송을 기다렸습니다. 또한, 예정 시간이 지나도 도착하지 않아 배송 담당자에게 문의하였습니다.",
    },
    {
        "topic": "rain",
        "style": "concrete",
        "text": "점심을 먹고 나오니 비가 쏟아졌다. 우산이 없어 가게 처마 아래서 기다렸는데, 십 분쯤 지나자 빗줄기가 잦아들었다.",
    },
    {
        "topic": "rain",
        "style": "formulaic",
        "text": "점심 식사 후 갑자기 비가 내리기 시작했습니다. 또한, 우산이 없는 상황이었으므로 비가 그칠 때까지 잠시 대기하였습니다.",
    },
    {
        "topic": "class",
        "style": "concrete",
        "text": "처음에는 분수 문제가 잘 안 풀렸다. 선생님이 그림으로 나누어 보여 주니, 같은 크기로 쪼개야 한다는 뜻을 알았다.",
    },
    {
        "topic": "class",
        "style": "formulaic",
        "text": "처음에는 분수 문제를 이해하는 데 어려움이 있었습니다. 또한, 그림을 활용한 설명을 통해 동일한 크기로 나누는 원리를 이해하였습니다.",
    },
    {
        "topic": "reservation",
        "style": "concrete",
        "text": "토요일 저녁 자리를 예약하려고 전화했다. 여섯 시는 꽉 찼다기에, 일곱 시 반으로 시간을 바꾸었다.",
    },
    {
        "topic": "reservation",
        "style": "formulaic",
        "text": "토요일 저녁 식사 예약을 위해 전화로 문의하였습니다. 또한, 희망 시간에는 예약이 어려워 이용 시간을 변경하였습니다.",
    },
    {
        "topic": "repair",
        "style": "concrete",
        "text": "노트북 전원이 자꾸 꺼져서 수리점에 가져갔다. 기사님은 배터리가 부풀었다며, 오늘은 켜지 말고 교체하자고 했다.",
    },
    {
        "topic": "repair",
        "style": "formulaic",
        "text": "노트북의 전원이 반복적으로 꺼지는 문제가 발생하였습니다. 또한, 점검 결과 배터리 교체가 필요한 상태로 확인되었습니다.",
    },
    {
        "topic": "library",
        "style": "concrete",
        "text": "도서관에서 찾던 책이 대출 중이었다. 반납 예정일이 다음 주라서 예약만 걸고 다른 책을 빌려 왔다.",
    },
    {
        "topic": "library",
        "style": "formulaic",
        "text": "도서관에서 필요한 도서의 대출 여부를 확인하였습니다. 또한, 해당 도서가 대출 중이어서 예약을 진행하고 다른 도서를 이용하였습니다.",
    },
    {
        "topic": "walk",
        "style": "concrete",
        "text": "퇴근길에 한 정거장 먼저 내려 걸었다. 골목 빵집 앞에서 막 구운 냄새가 나서, 저녁거리로 작은 식빵을 샀다.",
    },
    {
        "topic": "walk",
        "style": "formulaic",
        "text": "퇴근 후 한 정거장 먼저 내려 주변을 걸었습니다. 또한, 지나가던 빵집에서 저녁 식사용 빵을 구매하였습니다.",
    },
]

TRANSITIONS = ("또한", "따라서", "이러한 점에서", "이를 통해", "한편")
SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")


def features(s: str) -> dict[str, float]:
    text = s.strip()
    chars = len(re.sub(r"\s", "", text))
    eojeol = text.split()
    sentences = [x.strip() for x in SENTENCE_RE.findall(text) if x.strip()]
    sentence_lengths = [len(re.sub(r"\s", "", x)) for x in sentences]
    return {
        "chars": chars,
        "eojeol": len(eojeol),
        "sentences": len(sentences),
        "mean_sentence_chars": round(mean(sentence_lengths), 3) if sentences else 0.0,
        "commas_per_100_chars": round(100 * text.count(",") / chars, 3) if chars else 0.0,
        "transitions_per_100_chars": round(
            100 * sum(text.count(item) for item in TRANSITIONS) / chars, 3
        ) if chars else 0.0,
        "eojeol_type_token_ratio": round(len(set(eojeol)) / len(eojeol), 3) if eojeol else 0.0,
    }


def main() -> None:
    canonical = json.dumps(SAMPLES, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    groups: dict[str, list[dict[str, float]]] = defaultdict(list)
    by_topic: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for sample in SAMPLES:
        values = features(sample["text"])
        groups[sample["style"]].append(values)
        by_topic[sample["topic"]][sample["style"]] = values
    metrics = tuple(next(iter(groups.values()))[0])
    means = {
        style: {key: round(mean(row[key] for row in rows), 3) for key in metrics}
        for style, rows in sorted(groups.items())
    }
    pair_ratios = [
        round(rows["formulaic"]["chars"] / rows["concrete"]["chars"], 3)
        for rows in by_topic.values()
    ]
    result = {
        "provenance": "All 16 Korean texts constructed by an AI assistant for this probe; style labels only",
        "canonicalization": "json.dumps(SAMPLES, ensure_ascii=False, sort_keys=True, separators=(',', ':')) encoded UTF-8",
        "sample_sha256": digest,
        "sample_count": len(SAMPLES),
        "topic_pairs": len(by_topic),
        "group_means": means,
        "formulaic_to_concrete_character_ratios_by_topic": pair_ratios,
        "mean_character_ratio": round(mean(pair_ratios), 3),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
