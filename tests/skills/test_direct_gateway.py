import json
from pathlib import Path
import unittest
import test_gateway


class DirectGatewayTest(unittest.TestCase):
    setUp = test_gateway.GatewayTest.setUp
    tearDown = test_gateway.GatewayTest.tearDown
    call = test_gateway.GatewayTest.call
    response = test_gateway.GatewayTest.response
    accept = test_gateway.GatewayTest.accept

    def prepare(self, strength="normal"):
        return self.call("prepare", "--input", self.input, "--input-kind", "direct-text", "--strength", strength)

    def finish(self, state):
        while state["status"] == "rewrite":
            state = self.accept(state, Path(state["inputPath"]).read_text(encoding="utf-8"))
        return state

    def test_options_and_context_persist(self):
        for strength in ("normal", "medium", "strong", "very-strong"):
            state = self.prepare(strength)
            self.assertEqual(state["rewriteOptions"], {"inputKind": "direct-text", "strength": strength})
            self.assertIn("요청 강도: " + strength, Path(state["instructionsPath"]).read_text(encoding="utf-8"))
            spans = json.loads(Path(state["sentencesPath"]).read_text(encoding="utf-8"))
            self.assertTrue(any(sentence["protected"] for sentence in spans))
            next_state = self.call("next", "--job", state["job"])
            self.assertEqual(next_state["rewriteOptions"], state["rewriteOptions"])
            self.call("cleanup", "--job", state["job"])

    def test_invalid_options_create_no_jobs(self):
        for options in (("--strength", "strong"), ("--input-kind", "text-file", "--strength", "strong"),
                        ("--input-kind", "other"), ("--input-kind", "direct-text", "--strength", "other")):
            self.call("prepare", "--input", self.input, *options, succeeds=False)
        self.assertFalse((self.root / "jobs").exists())

    def test_protected_change_retries_then_rolls_back(self):
        state = self.prepare("strong")
        text = Path(state["inputPath"]).read_text(encoding="utf-8").replace("12명", "13명")
        state = self.accept(state, text)
        self.assertEqual(state["decision"], "retry")
        self.assertIn("DIRECT_TEXT_FIDELITY_RESTRICTED", " ".join(state["warnings"]))
        state = self.accept(state, text)
        self.assertEqual(state["decision"], "rollback")
        self.assertEqual(state["rewriteOptions"]["strength"], "strong")

    def test_comparison_failure_is_recoverable_and_exports_final_only(self):
        state = self.finish(self.prepare())
        output, html = self.root / "final.md", self.root / "compare.html"
        html.write_text("existing", encoding="utf-8")
        self.call("finalize", "--job", state["job"], "--output", output, "--comparison-output", html, succeeds=False)
        self.assertFalse(output.exists())
        self.assertEqual(html.read_text(), "existing")
        html.unlink()
        done = self.call("finalize", "--job", state["job"], "--output", output, "--comparison-output", html)
        self.assertEqual(done["comparisonPath"], str(html))
        self.assertEqual(output.read_text(encoding="utf-8"), self.source)
        self.assertIn("최종문", html.read_text(encoding="utf-8"))

    def test_final_guard_checks_entire_current_source(self):
        state = self.finish(self.prepare())
        job = self.root / "jobs" / state["job"]
        manifest = json.loads((job / "chunk_manifest.json").read_text(encoding="utf-8"))
        chunk = next(c for c in manifest["chunks"] if not c["passthrough"])
        rewritten = job / chunk["rewritten_file"]
        rewritten.write_text(rewritten.read_text(encoding="utf-8").replace("12명", "13명"), encoding="utf-8")
        output = self.root / "final.md"
        self.call("finalize", "--job", state["job"], "--output", output, succeeds=False)
        self.assertFalse(output.exists())

    def test_file_mode_rejects_comparison(self):
        state = self.finish(self.call("prepare", "--input", self.input))
        self.call("finalize", "--job", state["job"], "--output", self.root / "final.md",
                  "--comparison-output", self.root / "compare.html", succeeds=False)

    def test_very_strong_restores_protected_then_preserves_valid_edits(self):
        source = "이번 검토에서 중요한 것은 자료의 정확성이다. 담당자는 자료의 정리 작업을 수행한다.\n\n이 방안은 강한 경쟁력을 가지고 있다. 운영 과정에 있어서 검토 기록은 중요한 역할을 수행한다.\n\n회의에서는 초안과 관련된 내용을 논의했다. 작성자는 검토 의견을 반영하는 작업을 진행했다.\n\n자료의 구분이 이루어지고 기록의 정리가 진행된다. 문서의 핵심은 검토 결과를 명확하게 전달하는 것이다.\n"
        candidate = "이번 검토에서는 자료의 정확성이 중요하다. 담당자는 자료를 정리한다.\n\n이 방안은 경쟁력이 강하다. 운영 과정에서 검토 기록의 역할은 중요하다.\n\n회의에서는 초안에 관한 내용을 논의했다. 작성자는 검토 의견을 반영했다.\n\n자료를 구분하고 기록을 정리한다. 검토 결과를 명확하게 전달하는 것이 문서의 핵심이다.\n"
        self.input.write_text(source, encoding="utf-8")
        state = self.accept(self.prepare("very-strong"), candidate)
        self.assertEqual(state["restoration"]["restoredProtectedSentences"], 1)
        self.assertEqual(state["status"], "ready-to-finalize")
        output = self.root / "restored.md"
        self.call("finalize", "--job", state["job"], "--output", output)
        self.assertEqual(output.read_text(encoding="utf-8"), candidate.replace("자료를 구분하고 기록을 정리한다.", "자료의 구분이 이루어지고 기록의 정리가 진행된다."))

    def test_real_p1_review_uses_original_and_second_candidate(self):
        fixture = json.loads((test_gateway.ROOT / "tests/fixtures/direct-live-quality.json").read_text(encoding="utf-8"))
        self.input.write_text(fixture["source"], encoding="utf-8")
        state = self.accept(self.prepare("very-strong"), fixture["candidate"])
        self.assertEqual(state["decision"], "retry")
        prompt = Path(state["instructionsPath"]).read_text(encoding="utf-8")
        self.assertIn("BEGIN_CANDIDATE_", prompt)
        self.assertIn(fixture["source"], prompt)
        self.assertIn(fixture["candidate"], prompt)
        self.assertIn("DIRECT_TEXT_CANDIDATE_REVIEW_RETRY", " ".join(state["warnings"]))
        state = self.accept(state, fixture["source"])
        output = self.root / "reviewed.md"
        self.call("finalize", "--job", state["job"], "--output", output)
        self.assertEqual(output.read_text(encoding="utf-8"), fixture["source"])

    def test_failed_second_export_removes_owned_first_and_allows_retry(self):
        state = self.finish(self.prepare())
        output, missing = self.root / "final.md", self.root / "absent" / "compare.html"
        self.call("finalize", "--job", state["job"], "--output", output, "--comparison-output", missing, succeeds=False)
        self.assertFalse(output.exists())
        self.assertEqual(self.call("next", "--job", state["job"])["status"], "ready-to-finalize")
        missing.parent.mkdir()
        self.call("finalize", "--job", state["job"], "--output", output, "--comparison-output", missing)
        self.assertTrue(output.exists() and missing.exists())

    def test_office_options_rejected_before_job(self):
        office = test_gateway.ROOT / "tests/fixtures/documents/mixed.docx"
        for opts in (("--input-kind", "direct-text"), ("--input-kind", "text-file", "--strength", "strong")):
            self.call("prepare", "--input", office, *opts, succeeds=False)
        self.assertFalse((self.root / "jobs").exists())


if __name__ == "__main__":
    unittest.main()
