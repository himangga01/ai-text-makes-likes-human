"""The vendor lexical layer on the skill Gateway path: hints on the first attempt, restore after every reply."""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

import test_gateway
import test_direct_gateway

sys.path.insert(0, str(test_gateway.ROOT))
from engine_runtime import workflow  # noqa: E402

LENS_SOURCE = "이 문제를 세 가지 렌즈로 본다. 참석자는 12명이었다. 다음 문장은 그대로 둔다.\n"
PLAIN_SOURCE = "오늘은 비가 왔다. 참석자는 12명이었다. 다음 문장은 그대로 둔다.\n"
INJECT_SOURCE = "올해 매출은 크게 늘었다. 이 결과를 여러 관점에서 살펴본다. 비용은 조금 줄었다.\n"
INJECTED = "올해 매출은 크게 늘었다. 이 결과를 여러 렌즈로 살펴본다. 비용은 조금 줄었다.\n"


class FileRouteLexicalTest(unittest.TestCase):
    setUp = test_gateway.GatewayTest.setUp
    tearDown = test_gateway.GatewayTest.tearDown
    call = test_gateway.GatewayTest.call
    response = test_gateway.GatewayTest.response
    accept = test_gateway.GatewayTest.accept

    def prepare(self, source):
        self.input.write_text(source, encoding="utf-8")
        return self.call("prepare", "--input", self.input)

    def test_first_attempt_gets_the_block_and_the_retry_does_not(self):
        state = self.prepare(LENS_SOURCE)
        block = Path(state["lexicalHintsPath"]).read_text(encoding="utf-8")
        self.assertTrue(block.startswith("[어휘 점검]\n") and block.endswith("[어휘 점검 끝]\n"))
        self.assertIn("[우선] 렌즈", block)
        self.assertEqual(Path(state["lexicalHintsPath"]).parent, Path(state["inputPath"]).parent)
        self.assertEqual(self.call("next", "--job", state["job"])["lexicalHintsPath"], state["lexicalHintsPath"])
        # A changed number fails the gate: the conservative retry gets no block.
        retry = self.accept(state, Path(state["inputPath"]).read_text(encoding="utf-8").replace("12명", "13명"))
        self.assertEqual((retry["decision"], retry["attempt"]), ("retry", 2))
        self.assertNotIn("lexicalHintsPath", retry)
        self.assertNotIn("lexicalHintsPath", self.call("next", "--job", state["job"]))
        self.call("cleanup", "--job", state["job"])

    def test_a_chunk_without_lexicon_words_gets_no_block(self):
        state = self.prepare(PLAIN_SOURCE)
        self.assertNotIn("lexicalHintsPath", state)
        self.assertEqual(list(Path(state["inputPath"]).parent.glob("lexical-*")), [])
        self.call("cleanup", "--job", state["job"])

    def test_an_injected_word_is_restored_and_only_counted(self):
        state = self.prepare(INJECT_SOURCE)
        job = Path(state["inputPath"]).parent
        state = self.accept(state, INJECTED)
        self.assertEqual(state["decision"], "accept")
        self.assertEqual(state["restoration"]["restoredLexicalSentences"], 1)
        self.assertEqual(state["restoration"]["lexicalRestoreFailures"], 0)
        warnings = " ".join(state["warnings"])
        self.assertIn("LEXICAL_RESTORED: 1번 구간에서 원문에 없던 어색한 어휘가 들어간 1개 문장을 원문으로 되돌렸습니다.", warnings)
        # Counts only: no restored or rewritten sentence text in the reply, the warnings or the job state.
        self.assertNotIn("렌즈로 살펴본다", json.dumps(state, ensure_ascii=False))
        self.assertNotIn("렌즈로 살펴본다", (job / "job.json").read_text(encoding="utf-8"))
        output = self.root / "result.md"
        self.call("finalize", "--job", state["job"], "--output", output)
        self.assertEqual(output.read_text(encoding="utf-8"), INJECT_SOURCE)
        self.call("cleanup", "--job", state["job"])


class StrengthRouteLexicalTest(unittest.TestCase):
    setUpClass = test_direct_gateway.DirectGatewayTest.setUpClass
    setUp = test_gateway.GatewayTest.setUp
    tearDown = test_gateway.GatewayTest.tearDown
    call = test_gateway.GatewayTest.call
    response = test_gateway.GatewayTest.response
    accept = test_gateway.GatewayTest.accept

    def prepare(self, source, kind="direct-text", strength="strong"):
        self.input.write_text(source, encoding="utf-8")
        return self.call("prepare", "--input", self.input, "--input-kind", kind, "--strength", strength)

    def test_the_prompt_carries_the_block_on_the_first_attempt_only(self):
        for kind in ("direct-text", "text-file"):
            with self.subTest(kind=kind):
                state = self.prepare(LENS_SOURCE, kind)
                self.assertNotIn("lexicalHintsPath", state)
                instructions = Path(state["instructionsPath"]).read_text(encoding="utf-8")
                self.assertIn("<lexical_check>\n[어휘 점검]\n", instructions)
                self.assertIn("[우선] 렌즈", instructions)
                retry = self.accept(state, Path(state["inputPath"]).read_text(encoding="utf-8").replace("12명", "13명"))
                self.assertEqual((retry["decision"], retry["attempt"]), ("retry", 2))
                self.assertNotIn("lexical_check", Path(retry["instructionsPath"]).read_text(encoding="utf-8"))
                self.call("cleanup", "--job", state["job"])

    def test_no_block_without_lexicon_words(self):
        state = self.prepare(PLAIN_SOURCE)
        self.assertNotIn("lexical_check", Path(state["instructionsPath"]).read_text(encoding="utf-8"))
        self.call("cleanup", "--job", state["job"])


class WorkflowRestoreLexicalTest(unittest.TestCase):
    def run_restore(self, source, candidate):
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / "before.txt", Path(folder) / "after.txt"
            before.write_text(source, encoding="utf-8")
            after.write_text(candidate, encoding="utf-8")
            report = workflow.restore(before, after)
            return report, after.read_text(encoding="utf-8")

    def test_lexical_restore_runs_after_the_commas_and_before_the_particles(self):
        calls = []
        real_commas, real_lexical, real_josa = workflow.strip_commas, workflow.lexical, workflow.josa.gate

        def commas(*args):
            calls.append("commas")
            return real_commas(*args)

        class Layer:
            @staticmethod
            def restore(source, output):
                calls.append("lexical")
                return real_lexical(workflow.DEFAULT_VENDOR).restore(source, output)

        def josa(*args):
            calls.append("josa")
            return real_josa(*args)

        with mock.patch.object(workflow, "strip_commas", commas), mock.patch.object(workflow, "lexical", lambda vendor: Layer), \
                mock.patch.object(workflow.josa, "gate", josa), mock.patch.object(workflow, "super_sejong_mode", lambda: "on"):
            report, text = self.run_restore(INJECT_SOURCE, INJECTED)
        self.assertEqual(calls, ["commas", "lexical", "josa"])
        self.assertEqual(text, INJECT_SOURCE)
        self.assertEqual((report["restoredLexicalSentences"], report["skippedLexicalSentences"], report["lexicalRestoreFailures"]), (1, 0, 0))

    def test_a_failing_lexical_layer_never_blocks_and_is_counted(self):
        class Broken:
            @staticmethod
            def restore(source, output):
                raise RuntimeError("lexicon unreadable")

        with mock.patch.object(workflow, "lexical", lambda vendor: Broken):
            report, text = self.run_restore(INJECT_SOURCE, INJECTED)
        self.assertEqual(text, INJECTED)
        self.assertEqual((report["restoredLexicalSentences"], report["lexicalRestoreFailures"]), (0, 1))

    def test_hints_degrade_to_nothing_without_the_layer(self):
        self.assertIn("[우선] 렌즈", workflow.lexical_hints(LENS_SOURCE))
        self.assertEqual(workflow.lexical_hints(PLAIN_SOURCE), "")
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "scripts").mkdir()
            (Path(folder) / "scripts/verify_gates.py").write_text("", encoding="utf-8")
            self.assertEqual(workflow.lexical_hints(LENS_SOURCE, Path(folder)), "")


class PackagingLexicalTest(unittest.TestCase):
    def test_the_vendor_tree_ships_whole_with_the_lexical_layer(self):
        vendor = test_gateway.ROOT / "vendor/humanize-engine"
        for relative in ("scripts/lexical_layer.py", "skills/humanize-korean/references/lexicon.json"):
            self.assertTrue((vendor / relative).is_file(), relative)
        # Skill ZIPs and the desktop app copy the vendor folder whole (no file list that could drop the lexicon).
        skills = (test_gateway.ROOT / "scripts/package-skills.mjs").read_text(encoding="utf-8")
        self.assertIn('await cp("vendor/humanize-engine", path.join(destination, "vendor/humanize-engine"), { recursive: true, filter });', skills)
        builder = (test_gateway.ROOT / "electron-builder.yml").read_text(encoding="utf-8")
        self.assertRegex(builder, re.compile(r"- from: vendor/humanize-engine\n\s+to: engine/vendor/humanize-engine\n\s+filter: \['\*\*/\*', "))
        verifier = (test_gateway.ROOT / "scripts/verify-skill-packages.mjs").read_text(encoding="utf-8")
        self.assertIn("vendor/humanize-engine/scripts/lexical_layer.py", verifier)
        self.assertIn("vendor/humanize-engine/skills/humanize-korean/references/lexicon.json", verifier)


if __name__ == "__main__":
    unittest.main()
