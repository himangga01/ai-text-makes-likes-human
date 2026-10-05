#!/usr/bin/env python3
"""Summary of Super Sejong v2 shadow recording from the portal log (codes and counts only).

    python3 scripts/sejong-shadow-report.py [--log runtime/hermes-service.log] [--json]

Reads every transform_complete event that carries diagnostics.v2ShadowCounts, i.e. the jobs the
legacy engine ran with SUPER_SEJONG_V2_SHADOW=1, and prints a Korean markdown summary: what v2
would have requested, how its gate judges the delivered (legacy) text, which checks fire, and the
overhead. The log holds no document text; neither does this report.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

DEFAULT_LOG = Path(__file__).resolve().parents[1] / "runtime" / "hermes-service.log"
FAMILY_KO = {"floor": "보존", "meaning": "의미", "voice": "말투", "cta": "행동 요청", "flow": "흐름",
             "clarity": "명료성", "norms": "맞춤법", "runaway": "변경량", "apply": "형식"}


RULE_PREFIXES = ("ssj", "tr", "clr", "cta")


def rule_id(key: str) -> str:
    """Display form of a sanitised rule key (the hook lower-cases ids and turns - and . into _):
    ssj_lv3 -> SSJ-LV3, tr_junge_itda -> TR-JUNGE_ITDA, public_language_frame -> PUBLIC_LANGUAGE_FRAME."""
    head, _, rest = key.partition("_")
    return (head + "-" + rest).upper() if head in RULE_PREFIXES and rest else key.upper()


def load(path: Path):
    total, jobs = 0, []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"transform_complete"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event") != "transform_complete":
                continue
            total += 1
            diagnostics = event.get("diagnostics") or {}
            counts = diagnostics.get("v2ShadowCounts")
            if counts:
                jobs.append((event, diagnostics, counts))
    return total, jobs


def summarise(total: int, jobs) -> dict:
    keys: Counter = Counter()
    overhead, prepare, check = [], [], []
    legacy = Counter()
    for event, diagnostics, counts in jobs:
        for key, value in counts.items():
            if isinstance(value, int) and not key.startswith("ms_"):
                keys[key] += value
        for name, bucket in (("ms_overhead", overhead), ("ms_prepare", prepare), ("ms_check", check)):
            if isinstance(counts.get(name), int):
                bucket.append(counts[name])
        legacy["jobs"] += 1
        legacy["engine_" + str(event.get("engine"))] += 1
        legacy["codexCalls"] += diagnostics.get("codexCalls") or 0
        legacy["retries"] += diagnostics.get("retries") or 0
        legacy["rolledBackJobs"] += 1 if (diagnostics.get("rolledBackChunks") or 0) > 0 else 0
        legacy["fullSourceRollbacks"] += diagnostics.get("fullSourceRollbacks") or 0
        legacy["sourceChars"] += event.get("sourceChars") or 0

    def pct(values, q):
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]

    def top(prefix, limit=10):
        found = [(key[len(prefix):], value) for key, value in keys.items() if key.startswith(prefix) and value]
        return sorted(found, key=lambda item: (-item[1], item[0]))[:limit]

    return {
        "logJobs": total, "shadowJobs": len(jobs), "keys": dict(keys), "legacy": dict(legacy),
        "overhead": {"p50": pct(overhead, 0.5), "p90": pct(overhead, 0.9), "max": max(overhead) if overhead else None},
        "prepareMedian": statistics.median(prepare) if prepare else None,
        "checkMedian": statistics.median(check) if check else None,
        "topRequestRules": top("request_rule_"), "topRetryCodes": top("retry_code_"),
        "topSentenceCodes": top("sentence_code_"), "retryFamilies": top("retry_family_"),
        "revertedFamilies": top("reverted_family_"), "hard": top("hard_"), "soft": top("soft_"),
    }


def render(s: dict) -> str:
    k, legacy = s["keys"], s["legacy"]
    n = s["shadowJobs"]
    lines = ["# 슈퍼세종엔진 v2 기록 모드 결과", ""]
    lines.append(f"- 로그의 전체 작업 {s['logJobs']}건 중 기록 모드 작업 **{n}건**")
    if not n:
        lines.append("- 아직 기록된 작업이 없습니다. 서버가 `SUPER_SEJONG_V2_SHADOW=1`로 실행 중인지 확인하세요.")
        return "\n".join(lines) + "\n"
    failed = sum(v for key, v in k.items() if key.startswith(("failed_", "timeout_", "aborted_")))
    lines.append(f"- 기록 성공 {k.get('shadow_ok', 0)}건, 기록 실패 {k.get('shadow_failed', 0)}건"
                 f" (단계별 실패·시간 초과·중단 {failed}회)")
    lines.append(f"- 처리한 원문 {legacy.get('sourceChars', 0):,}자, 기존 엔진 모델 호출 {legacy.get('codexCalls', 0)}회,"
                 f" 재시도 {legacy.get('retries', 0)}회, 구간 되돌림이 있었던 작업 {legacy.get('rolledBackJobs', 0)}건,"
                 f" 전체 원문 복원 {legacy.get('fullSourceRollbacks', 0)}건")
    lines += ["", "## v2 검사의 판정 (기존 엔진이 낸 결과물 기준)", ""]
    lines.append(f"- 그대로 받아들임: {k.get('would_accept', 0)}건 / 재시도 요청: {k.get('would_retry', 0)}건"
                 f" / 실패 처리: {k.get('would_fail', 0)}건 (판정 불가: 구간 경계 불일치 {k.get('chunks_unaligned', 0)}구간)")
    lines.append(f"- 문장 판정: 그대로 {k.get('sentences_unchanged', 0)} · 맞춤법 자동 수정 {k.get('sentences_deterministic', 0)}"
                 f" · 채택 {k.get('sentences_accepted', 0)} · 재시도 {k.get('sentences_retry', 0)}"
                 f" · 되돌림 {k.get('sentences_reverted', 0)} · 거부 {k.get('sentences_rejected', 0)}")
    lines.append(f"- 요청 밖 수정으로 되돌렸을 문장 {k.get('collateral_reverts', 0)}개, 확실한 맞춤법 수정 {k.get('norm_fixes', 0)}곳")
    if s["retryFamilies"]:
        lines.append("- 재시도 사유(검사 묶음): " + ", ".join(f"{FAMILY_KO.get(f, f)} {v}" for f, v in s["retryFamilies"]))
    if s["revertedFamilies"]:
        lines.append("- 되돌림 사유(검사 묶음): " + ", ".join(f"{FAMILY_KO.get(f, f)} {v}" for f, v in s["revertedFamilies"]))
    if s["topRetryCodes"]:
        lines.append("- 재시도 코드 상위: " + ", ".join(f"`{c}` {v}" for c, v in s["topRetryCodes"]))
    if s["topSentenceCodes"]:
        lines.append("- 문장 코드 상위: " + ", ".join(f"`{c}` {v}" for c, v in s["topSentenceCodes"]))
    if s["hard"] or s["soft"]:
        lines.append("- 구간 게이트 코드: " + ", ".join([f"`{c}`(hard) {v}" for c, v in s["hard"]]
                                                   + [f"`{c}`(soft) {v}" for c, v in s["soft"]]))
    lines += ["", "## v2였다면 보냈을 요청", ""]
    lines.append(f"- 구간 {k.get('chunks', 0)}개 중 모델이 필요한 구간 {k.get('chunks_need_model', 0)}개,"
                 f" 모델 없이 끝났을 구간 {k.get('chunks_no_model', 0)}개 (열린 검토 대상 {k.get('chunks_open_review', 0)}개)")
    lines.append(f"- 요청: 필수(FIX) {k.get('requests_fix', 0)} · 제안(SUGGEST) {k.get('requests_suggest', 0)}"
                 f" · 열린 검토 {k.get('requests_review', 0)}")
    if s["topRequestRules"]:
        lines.append("- 요청 규칙 상위: " + ", ".join(f"`{rule_id(r)}` {v}" for r, v in s["topRequestRules"]))
    lines.append(f"- 기존 엔진 결과에 비춘 요청 상태: 고쳐짐 {k.get('request_status_fixed', 0)}"
                 f" · 손대지 않음 {k.get('request_status_untouched', 0)} · 남아 있음 {k.get('request_status_still_present', 0)}"
                 f" · 해당 문장 미수정 {k.get('request_status_declined', 0)}")
    lines += ["", "## 추가 시간", ""]
    o = s["overhead"]
    lines.append(f"- 작업이 v2 기록을 기다린 시간: 중앙값 {o['p50']}ms, 90% {o['p90']}ms, 최대 {o['max']}ms"
                 f" (분석 중앙값 {s['prepareMedian']}ms, 검사 중앙값 {s['checkMedian']}ms, 둘 다 기존 엔진 작업과 겹쳐 실행)")
    lines += ["", "숫자는 코드와 개수만 모은 것이며 본문은 들어가지 않습니다. v2가 직접 고친 결과의 품질은 이 기록으로 알 수 없고,"
              " `SUPER_SEJONG_ENGINE=v2`로 전환해야 볼 수 있습니다."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--json", action="store_true", help="print the aggregated counts as JSON")
    args = parser.parse_args()
    if not args.log.is_file():
        print(f"로그 파일이 없습니다: {args.log}")
        return 1
    total, jobs = load(args.log)
    summary = summarise(total, jobs)
    print(json.dumps(summary, ensure_ascii=False, indent=1) if args.json else render(summary), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
