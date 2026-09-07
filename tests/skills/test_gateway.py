import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "engine_runtime/skill_gateway.py"


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
        result = subprocess.run([sys.executable, str(GATEWAY), "--workspace-root", str(self.root / "jobs"), *map(str, args)], capture_output=True, encoding="utf-8")
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
