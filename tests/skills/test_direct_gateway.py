import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import test_gateway

BRIDGE = test_gateway.ROOT / "build-resources/skill-bridge/skill-bridge.cjs"


class DirectGatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Direct text needs the Node bridge artifact; build it once so the suite runs on any OS with Node.
        if BRIDGE.is_file():
            return
        node = os.environ.get("NODE_COMMAND") or shutil.which("node")
        if not node:
            raise unittest.SkipTest("Node is required to build the skill bridge (node scripts/build-skill-bridge.mjs)")
        subprocess.run([node, str(test_gateway.ROOT / "scripts/build-skill-bridge.mjs")], check=True, cwd=test_gateway.ROOT)

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
        for options in (("--strength", "strong"), ("--input-kind", "text-file", "--strength", "other"),
                        ("--input-kind", "other"), ("--input-kind", "direct-text", "--strength", "other")):
            self.call("prepare", "--input", self.input, *options, succeeds=False)
        self.assertFalse((self.root / "jobs").exists())

    def test_text_file_above_normal_takes_the_direct_text_route(self):
        # Owner request 2026-10-10: a TXT/MD file takes every strength; above normal it gets the strength prompt,
        # the sentence map and the strict guard, at normal it keeps the file route.
        state = self.call("prepare", "--input", self.input, "--input-kind", "text-file", "--strength", "strong")
        self.assertEqual(state["rewriteOptions"], {"inputKind": "text-file", "strength": "strong"})
        self.assertIn("요청 강도: strong", Path(state["instructionsPath"]).read_text(encoding="utf-8"))
        self.assertTrue(Path(state["sentencesPath"]).is_file())
        text = Path(state["inputPath"]).read_text(encoding="utf-8").replace("12명", "13명")
        state = self.accept(state, text)
        self.assertEqual(state["decision"], "retry")
        self.assertIn("DIRECT_TEXT_FIDELITY_RESTRICTED", " ".join(state["warnings"]))
        self.call("cleanup", "--job", state["job"])
        rewrite = self.call("prepare", "--input", self.input, "--input-kind", "text-file", "--strength", "rewrite")
        self.assertIn("요청 강도: very-strong", Path(rewrite["instructionsPath"]).read_text(encoding="utf-8"))
        self.call("cleanup", "--job", rewrite["job"])
        plain = self.call("prepare", "--input", self.input, "--input-kind", "text-file")
        self.assertEqual(plain["rewriteOptions"], {"inputKind": "text-file", "strength": "normal"})
        self.assertNotIn("instructionsPath", plain)
        self.call("cleanup", "--job", plain["job"])

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

    def test_invalid_or_ambiguous_edits_retry_then_roll_back(self):
        # R2-5.4: an unusable reply costs the attempt instead of an opaque bridge error.
        self.input.write_text("회의는 오전에 열렸다. 회의는 오전에 열렸다고 적었다. 참석자들은 안건을 검토했다.\n", encoding="utf-8")
        state = self.prepare("normal")
        decisions = []
        for edit in ({"before": "회의는 오전에", "after": "회의가 오전에"}, {"before": "없는 구절", "after": "x"}):
            Path(state["responsePath"]).write_text(json.dumps({"rewrittenText": "", "edits": [edit], "warnings": []}, ensure_ascii=False), encoding="utf-8")
            state = self.call("accept", "--job", state["job"], "--chunk", state["chunk"], "--attempt", state["attempt"],
                              "--source-hash", state["sourceHash"], "--response", state["responsePath"])
            decisions.append(state["decision"])
        self.assertEqual(decisions, ["retry", "rollback"])
        self.assertIn("MODEL_OUTPUT_UNUSABLE", " ".join(state["warnings"]))

    def test_full_text_reply_without_outer_whitespace_is_accepted(self):
        # R2-5.2: very-strong asks for full text; a reply without the chunk's trailing
        # newlines must not fail the structural check.
        source = "첫 문단은 그대로 둔다. 회의는 오전에 열렸다.\n\n둘째 문단도 그대로 둔다. 결과는 다음 주에 공유된다.\n"
        self.input.write_text(source, encoding="utf-8")
        state = self.prepare("very-strong")
        state = self.accept(state, Path(state["inputPath"]).read_text(encoding="utf-8").strip())
        self.assertEqual(state["decision"], "accept")

    def test_file_mode_rejects_comparison(self):
        state = self.finish(self.call("prepare", "--input", self.input))
        self.call("finalize", "--job", state["job"], "--output", self.root / "final.md",
                  "--comparison-output", self.root / "compare.html", succeeds=False)

    def test_very_strong_keeps_valid_edits_including_a_protected_sentence_whose_elements_survive(self):
        source = "이번 검토에서 중요한 것은 자료의 정확성이다. 담당자는 자료의 정리 작업을 수행한다.\n\n이 방안은 강한 경쟁력을 가지고 있다. 운영 과정에 있어서 검토 기록은 중요한 역할을 수행한다.\n\n회의에서는 초안과 관련된 내용을 논의했다. 작성자는 검토 의견을 반영하는 작업을 진행했다.\n\n자료의 구분이 이루어지고 기록의 정리가 진행된다. 문서의 핵심은 검토 결과를 명확하게 전달하는 것이다.\n"
        candidate = "이번 검토에서는 자료의 정확성이 중요하다. 담당자는 자료를 정리한다.\n\n이 방안은 경쟁력이 강하다. 운영 과정에서 검토 기록의 역할은 중요하다.\n\n회의에서는 초안에 관한 내용을 논의했다. 작성자는 검토 의견을 반영했다.\n\n자료를 구분하고 기록을 정리한다. 검토 결과를 명확하게 전달하는 것이 문서의 핵심이다.\n"
        self.input.write_text(source, encoding="utf-8")
        state = self.accept(self.prepare("very-strong"), candidate)
        # "자료의 구분이 이루어지고 기록의 정리가 진행된다" keeps its nouns in order and has no protected marker to lose.
        self.assertEqual(state["restoration"]["restoredProtectedSentences"], 0)
        self.assertEqual(state["status"], "ready-to-finalize")
        output = self.root / "accepted.md"
        self.call("finalize", "--job", state["job"], "--output", output)
        self.assertEqual(output.read_text(encoding="utf-8"), candidate)

    def test_real_p1_only_candidate_is_accepted_without_review(self):
        # P1 alone is advisory: the gateway accepts the candidate instead of asking for a candidate review.
        fixture = json.loads((test_gateway.ROOT / "tests/fixtures/direct-live-quality.json").read_text(encoding="utf-8"))
        self.input.write_text(fixture["source"], encoding="utf-8")
        state = self.accept(self.prepare("very-strong"), fixture["candidate"])
        self.assertEqual(state["decision"], "accept")
        self.assertNotIn("DIRECT_TEXT_CANDIDATE_REVIEW_RETRY", " ".join(state["warnings"]))
        output = self.root / "accepted.md"
        self.call("finalize", "--job", state["job"], "--output", output)
        self.assertEqual(output.read_text(encoding="utf-8").strip(), fixture["candidate"].strip())

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
