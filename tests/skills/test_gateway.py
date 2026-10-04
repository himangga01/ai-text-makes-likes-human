import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "engine_runtime/skill_gateway.py"


def legacy_environment():
    """These tests pin the legacy engine and its host protocol (rulesPath, rewrittenText replies, modality restore).
    The surrounding SUPER_SEJONG_ENGINE (v2 in the second pass of `npm run test:skills`) must not flip them: the v2
    path of the same gateway is covered by test_sejong_skill_path.py, which pins v2 the same way."""
    return {key: value for key, value in os.environ.items() if key != "SUPER_SEJONG_ENGINE"}


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="humanize-gateway-")
        self.root = Path(self.temp.name).resolve()
        self.input = self.root / "source.md"
        self.source = "# 회의\n\n이 수치는 낮은 것으로 판단된다. 참석자는 12명이었다. 다음 문장은 그대로 둔다. 마지막 문장도 그대로다. 😀\n"
        self.input.write_bytes(self.source.replace("\n", "\r\n").encode("utf-8"))

    def tearDown(self):
        if self.root.parent != Path(tempfile.gettempdir()).resolve() or not self.root.name.startswith("humanize-gateway-"):
            raise ValueError("Invalid cleanup root")
        self.temp.cleanup()

    def call(self, *args, succeeds=True):
        result = subprocess.run([sys.executable, str(GATEWAY), "--workspace-root", str(self.root / "jobs"), *map(str, args)],
                                capture_output=True, encoding="utf-8", env=legacy_environment())
        self.assertEqual(result.returncode, 0 if succeeds else 1, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def response(self, state, text):
        file = Path(state["responsePath"])
        file.write_text(json.dumps({"rewrittenText": text, "warnings": []}), encoding="utf-8")
        return file

    def accept(self, state, text):
        return self.call("accept", "--job", state["job"], "--chunk", state["chunk"], "--attempt", state["attempt"], "--source-hash", state["sourceHash"], "--response", self.response(state, text))

    def test_roundtrip_restores_modality_and_exports_without_overwriting(self):
        state = self.call("prepare", "--input", self.input)
        self.call("finalize", "--job", state["job"], "--output", self.root / "premature.md", succeeds=False)
        while state["status"] == "rewrite":
            text = Path(state["inputPath"]).read_text(encoding="utf-8")
            state = self.accept(state, text.replace("낮은 것으로 판단된다", "낮은 수치다"))
        self.assertTrue(any("복원" in warning for warning in state["warnings"]))
        self.call("finalize", "--job", state["job"], "--output", self.input, succeeds=False)
        output = self.root / "result.md"
        self.call("finalize", "--job", state["job"], "--output", output)
        self.assertEqual(output.read_text(encoding="utf-8"), self.source)
        self.assertIn(b"\r\n", self.input.read_bytes())
        self.call("cleanup", "--job", state["job"])
        self.assertEqual(list((self.root / "jobs").iterdir()), [])

    def test_changed_numbers_retry_then_rollback_and_duplicate_accept_fails(self):
        state = self.call("prepare", "--input", self.input)
        first = dict(state)
        text = Path(state["inputPath"]).read_text(encoding="utf-8").replace("12명", "13명")
        state = self.accept(state, text)
        self.assertEqual(state["decision"], "retry")
        self.call("accept", "--job", first["job"], "--chunk", first["chunk"], "--attempt", 1, "--source-hash", first["sourceHash"], "--response", first["responsePath"], succeeds=False)
        state = self.accept(state, text)
        self.assertEqual(state["decision"], "rollback")
        output = self.root / "result.md"
        self.call("finalize", "--job", state["job"], "--output", output)
        self.assertIn("12명", output.read_text(encoding="utf-8"))

    def test_file_structure_change_retries_then_rolls_back(self):
        # R2-5.1: TXT/MD jobs get the server's structural guard, not just the Python gate.
        source = "# 제목\n\n회의는 오전에 열렸다. 참석자들은 안건을 검토했다.\n\n회의는 오후에 끝났다. 결과는 다음 주에 공유된다.\n\n마지막 문단은 그대로 둔다.\n"
        self.input.write_text(source, encoding="utf-8")
        state = self.call("prepare", "--input", self.input)
        merged = Path(state["inputPath"]).read_text(encoding="utf-8").replace("검토했다.\n\n회의는", "검토했다. 회의는")
        state = self.accept(state, merged)
        self.assertEqual(state["decision"], "retry")
        self.assertIn("STRUCTURE_FIDELITY_RESTRICTED", " ".join(state["warnings"]))
        state = self.accept(state, merged)
        self.assertEqual(state["decision"], "rollback")
        output = self.root / "result.md"
        self.call("finalize", "--job", state["job"], "--output", output)
        self.assertEqual(output.read_text(encoding="utf-8"), source)

    def test_reply_without_the_chunk_outer_whitespace_is_accepted(self):
        # R2-5.2: the chunk's outer whitespace is re-attached before any check.
        source = "첫 문단은 그대로 둔다. 회의는 오전에 열렸다.\n\n둘째 문단도 그대로 둔다. 결과는 다음 주에 공유된다.\n"
        self.input.write_text(source, encoding="utf-8")
        state = self.call("prepare", "--input", self.input)
        state = self.accept(state, Path(state["inputPath"]).read_text(encoding="utf-8").strip())
        self.assertEqual(state["decision"], "accept")
        output = self.root / "result.md"
        self.call("finalize", "--job", state["job"], "--output", output)
        self.assertEqual(output.read_text(encoding="utf-8"), source)

    def test_footnote_definition_edit_in_a_later_chunk_is_caught_by_the_chunk_gate(self):
        # R2-3.1: markers in chunk 1, definitions (followed by an appendix, so they are not a
        # passthrough tail) in the last body chunk; the chunk gate must agree with the
        # full-document gate instead of letting finalize fail the whole job.
        paragraph = "회의는 오전에 열렸다. 참석자들은 안건을 차례로 검토했다. 결과는 다음 주에 공유된다. " * 12
        body = "선행 연구에 따르면 참여율은 높았다.1) 후속 조사에서도 비슷한 결과가 보고되었다.2)\n\n" + \
            "\n\n".join(f"{i}번째 문단입니다. {paragraph.strip()}" for i in range(1, 36))
        definitions = "1) 여기서 참여율은 전체 등록자 대비 실제 응답자의 비율을 말한다.\n2) 통계청, 2025년 조사 보고서.\n"
        source = body + "\n\n" + definitions + "\n## 부록\n\n설문지 원본을 싣는다. 응답자 명단은 따로 보관한다.\n"
        self.input.write_text(source, encoding="utf-8")
        state = self.call("prepare", "--input", self.input)
        self.assertGreater(state["totalChunks"], 1)
        decisions = []
        while state["status"] == "rewrite":
            text = Path(state["inputPath"]).read_text(encoding="utf-8")
            state = self.accept(state, text.replace("전체 등록자 대비 실제 응답자의 비율을 말한다", "등록자 가운데 실제로 응답한 사람의 비율이다"))
            decisions.append(state["decision"])
        self.assertIn("retry", decisions)
        self.assertEqual(decisions[-1], "rollback")
        output = self.root / "result.md"
        self.call("finalize", "--job", state["job"], "--output", output)
        self.assertEqual(output.read_text(encoding="utf-8"), source)

    def test_modified_source_and_unsafe_jobs_are_rejected(self):
        self.call("cleanup", "--job", "../../outside", succeeds=False)
        state = self.call("prepare", "--input", self.input)
        source = self.root / "jobs" / state["job"] / "01_input.txt"
        source.write_text("changed", encoding="utf-8")
        self.call("next", "--job", state["job"], succeeds=False)
        self.assertTrue(self.input.exists())
        self.call("cleanup", "--job", state["job"])
        self.assertEqual(list((self.root / "jobs").iterdir()), [])


if __name__ == "__main__": unittest.main()
