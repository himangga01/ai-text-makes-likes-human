"""scripts/sejong-shadow-report.py: aggregation of diagnostics.v2ShadowCounts from a portal log (constructed log)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sejong-shadow-report.py"


def event(chars, diagnostics):
    return json.dumps({"event": "transform_complete", "engine": "codex", "sourceChars": chars, "diagnostics": diagnostics})


class ShadowReport(unittest.TestCase):
    def run_report(self, lines, *extra):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "hermes-service.log"
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            return subprocess.run([sys.executable, str(SCRIPT), "--log", str(log), *extra], capture_output=True,
                                  text=True, env=env, timeout=60)

    def test_aggregates_only_shadow_jobs_and_skips_broken_lines(self):
        lines = [
            '{"event":"service_start"}', 'not json {"transform_complete"',
            event(100, {"codexCalls": 1}),
            event(3000, {"codexCalls": 2, "retries": 1, "rolledBackChunks": 1, "v2ShadowCounts": {
                "shadow_ok": 1, "chunks": 1, "chunks_checked": 1, "gate_exit_2": 1, "would_retry": 1,
                "requests_suggest": 2, "request_rule_tr_junge_itda": 1, "request_rule_public_language_frame": 1,
                "sentences_retry": 2, "retry_family_voice": 2, "retry_code_voice_level": 2,
                "ms_overhead": 20, "ms_prepare": 200, "ms_check": 220}}),
            event(800, {"codexCalls": 1, "v2ShadowCounts": {"shadow_failed": 1, "timeout_check": 1, "chunks": 1,
                                                           "chunks_skipped": 1, "ms_overhead": 5000}}),
            event(500, {"codexCalls": 1, "v2ShadowCounts": {"shadow_ok": 1, "chunks": 1, "chunks_checked": 1,
                                                           "gate_exit_0": 1, "would_accept": 1, "ms_overhead": 0}}),
            event(400, {"codexCalls": 1, "v2ShadowCounts": {"shadow_ok": 1, "chunks": 1, "chunks_checked": 1,
                                                           "gate_exit_0": 1, "would_accept": 1, "ms_overhead": 420}}),
        ]
        result = self.run_report(lines)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn("전체 작업 5건 중 기록 모드 작업 **4건**", out)
        self.assertIn("기록 성공 3건, 기록 실패 1건", out)
        self.assertIn("시간 초과 check 1", out)
        self.assertIn("받아들임 2건(일부 문장 되돌림 포함) / 재시도 1건 / 되돌림 0건", out)
        self.assertIn("시간 초과로 건너뜀 1개", out)
        self.assertIn("`TR-JUNGE_ITDA` 1", out)
        self.assertIn("`PUBLIC_LANGUAGE_FRAME` 1", out)
        self.assertIn("말투 2", out)
        # medians over [0, 20, 420, 5000] and the single prepare/check timings, all in whole milliseconds
        self.assertIn("중앙값 220ms, 90% 5000ms, 최대 5000ms", out)
        self.assertIn("분석 중앙값 200ms, 검사 중앙값 220ms", out)

        raw = json.loads(self.run_report(lines, "--json").stdout)
        self.assertEqual((raw["logJobs"], raw["shadowJobs"]), (5, 4))

    def test_no_timings_and_no_jobs_are_rendered_plainly(self):
        out = self.run_report([event(10, {"v2ShadowCounts": {"shadow_failed": 1, "failed_prepare": 1}})]).stdout
        self.assertIn("분석 중앙값 -, 검사 중앙값 -", out)
        self.assertNotIn("None", out)
        empty = self.run_report([event(10, {"codexCalls": 1})]).stdout
        self.assertIn("아직 기록된 작업이 없습니다", empty)

    def test_missing_log_exits_1(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--log", "/nonexistent/hermes-service.log"],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertIn("로그 파일이 없습니다", result.stdout)


if __name__ == "__main__":
    unittest.main()
