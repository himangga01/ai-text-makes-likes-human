"""The vendor lexical layer on the skill Gateway path: hints on the first attempt, restore after every reply."""
import json
from pathlib import Path
import re
import subprocess
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
# The concept guard's case: 렌즈 is the flagged metaphor noun, 실적·흐름 are the sentence's other concepts.
EXEMPT_SOURCE = "이번 분기 실적을 세 가지 렌즈로 살펴보면 흐름이 달라 보인다. 참석자는 12명이었다. 다음 문장은 그대로 둔다.\n"
EXEMPT_LENS_ONLY = EXEMPT_SOURCE.replace("세 가지 렌즈로", "세 가지 관점에서")
EXEMPT_DROPS_CONCEPT = EXEMPT_LENS_ONLY.replace("실적을 ", "")
EXEMPT_DROPS_OTHER_CONCEPT = EXEMPT_LENS_ONLY.replace("흐름이 ", "")


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


# skill_gateway.main() with a spy on the bridge calls that take the concept guard's exemption. Each run writes the
# calls it saw to a record file. LEXICAL_TEST_NO_EXEMPTION=1 makes the Gateway pass no nouns (the old behavior);
# LEXICAL_TEST_FORCE_RETRY=1 turns the chunk gate's decision into a retry, the case that asks the bridge for a review.
SPY_DRIVER = """
import json, os, sys
sys.path.insert(0, __RUNTIME__)
import skill_gateway
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
calls = []
real_bridge, real_verify = skill_gateway.bridge, skill_gateway.verify
def bridge(operation, **payload):
    if operation in ("check", "review"):
        calls.append({"operation": operation, "lexicalNouns": payload.get("lexicalNouns", "absent")})
    return real_bridge(operation, **payload)
def verify(*args, **kwargs):
    gate = real_verify(*args, **kwargs)
    return {**gate, "gate": {"exit_code": 1}, "hardFailures": [], "policy": "retry"} if os.environ.get("LEXICAL_TEST_FORCE_RETRY") else gate
skill_gateway.bridge, skill_gateway.verify = bridge, verify
if os.environ.get("LEXICAL_TEST_NO_EXEMPTION"):
    skill_gateway.lexical_nouns = lambda *args, **kwargs: []
try:
    code = skill_gateway.main()
finally:
    open(__RECORD__, "w", encoding="utf-8").write(json.dumps(calls, ensure_ascii=False))
raise SystemExit(code)
"""


class DirectGatewayCase(unittest.TestCase):
    """Direct-text and strength-route jobs through the real Node bridge, with the host replies the tests write."""
    setUpClass = test_direct_gateway.DirectGatewayTest.setUpClass
    setUp = test_gateway.GatewayTest.setUp
    tearDown = test_gateway.GatewayTest.tearDown
    call = test_gateway.GatewayTest.call
    response = test_gateway.GatewayTest.response
    accept = test_gateway.GatewayTest.accept

    def prepare(self, source, kind="direct-text", strength="strong"):
        self.input.write_text(source, encoding="utf-8")
        return self.call("prepare", "--input", self.input, "--input-kind", kind, "--strength", strength)

    def spy(self, *args, **environment):
        """One gateway command run under the spy; returns (decoded stdout, bridge calls that carry the exemption)."""
        driver, record = self.root / "driver.py", self.root / "driver-calls.json"
        driver.write_text(SPY_DRIVER.replace("__RUNTIME__", repr(str(test_gateway.ROOT / "engine_runtime")))
                          .replace("__RECORD__", repr(str(record))), encoding="utf-8")
        record.unlink(missing_ok=True)
        result = subprocess.run([sys.executable, str(driver), "--workspace-root", str(self.root / "jobs"), *map(str, args)],
                                capture_output=True, encoding="utf-8", env={**test_gateway.legacy_environment(), **environment})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout), json.loads(record.read_text(encoding="utf-8"))

    def spy_accept(self, state, text, **environment):
        return self.spy("accept", "--job", state["job"], "--chunk", state["chunk"], "--attempt", state["attempt"],
                        "--source-hash", state["sourceHash"], "--response", self.response(state, text), **environment)


class LexicalNounsToBridgeTest(DirectGatewayCase):
    def test_the_strength_route_accept_passes_the_flagged_nouns_to_the_bridge_check(self):
        for kind, strength in (("direct-text", "normal"), ("direct-text", "very-strong"), ("text-file", "strong")):
            with self.subTest(kind=kind, strength=strength):
                state = self.prepare(EXEMPT_SOURCE, kind, strength)
                reply, calls = self.spy_accept(state, Path(state["inputPath"]).read_text(encoding="utf-8"))
                self.assertEqual(reply["decision"], "accept")
                self.assertEqual(calls, [{"operation": "check", "lexicalNouns": ["렌즈"]}])
                self.call("cleanup", "--job", state["job"])

    def test_a_chunk_without_lexicon_words_passes_an_empty_list_not_nothing(self):
        state = self.prepare(PLAIN_SOURCE)
        reply, calls = self.spy_accept(state, Path(state["inputPath"]).read_text(encoding="utf-8"))
        self.assertEqual(reply["decision"], "accept")
        self.assertEqual(calls, [{"operation": "check", "lexicalNouns": []}])
        self.call("cleanup", "--job", state["job"])

    def test_a_conditional_noun_is_passed_only_when_the_chunk_repeats_it(self):
        for source, expected in (("시장 역학이 크게 달라졌다. 참석자는 12명이었다.\n", []),
                                 ("시장 역학이 크게 달라졌다. 역학은 계속 바뀐다. 참석자는 12명이었다.\n", ["역학"])):
            with self.subTest(expected=expected):
                state = self.prepare(source)
                _reply, calls = self.spy_accept(state, source)
                self.assertEqual(calls, [{"operation": "check", "lexicalNouns": expected}])
                self.call("cleanup", "--job", state["job"])

    def test_a_noun_only_inside_a_direct_quotation_is_not_passed(self):
        # The only 렌즈 is quoted: no hint in the prompt and no exemption, so the concept stays protected.
        source = "그는 이번 분기 실적을 \"렌즈로 보면\" 달라진다고 적었다. 참석자는 12명이었다.\n"
        state = self.prepare(source)
        self.assertNotIn("lexical_check", Path(state["instructionsPath"]).read_text(encoding="utf-8"))
        _reply, calls = self.spy_accept(state, source)
        self.assertEqual(calls, [{"operation": "check", "lexicalNouns": []}])
        self.call("cleanup", "--job", state["job"])

    def test_the_file_route_has_no_concept_guard_and_passes_nothing(self):
        self.input.write_text(EXEMPT_SOURCE, encoding="utf-8")
        state = self.call("prepare", "--input", self.input)
        reply, calls = self.spy_accept(state, Path(state["inputPath"]).read_text(encoding="utf-8"))
        self.assertEqual(reply["decision"], "accept")
        self.assertEqual(calls, [])
        self.call("cleanup", "--job", state["job"])

    def test_the_candidate_review_gets_the_nouns_too(self):
        state = self.prepare(EXEMPT_SOURCE)
        reply, calls = self.spy_accept(state, EXEMPT_LENS_ONLY, LEXICAL_TEST_FORCE_RETRY="1")
        # A forced gate retry on a candidate the guard accepted asks the bridge for a review of that candidate.
        self.assertEqual((reply["decision"], reply["attempt"]), ("retry", 2))
        self.assertEqual(calls, [{"operation": "check", "lexicalNouns": ["렌즈"]},
                                 {"operation": "review", "lexicalNouns": ["렌즈"]}])
        self.call("cleanup", "--job", state["job"])

    def test_finalize_checks_the_whole_document_with_the_union_of_the_chunks_nouns(self):
        filler = "회의는 오전에 열렸다. 참석자들은 안건을 차례로 검토했다. 결과는 다음 주에 공유된다. " * 6
        paragraphs = ["이번 분기 실적을 세 가지 렌즈로 살펴보면 흐름이 달라 보인다. 참석자는 12명이었다."]
        paragraphs += [f"{i}번째 문단입니다. {filler.strip()}" for i in range(1, 50)]
        paragraphs += ["## 둘째 절\n\n시장 역학이 크게 달라졌다. 역학은 계속 바뀐다. 다음 문장은 그대로 둔다."]
        source = "\n\n".join(paragraphs) + "\n"
        state = self.prepare(source)
        self.assertGreater(state["totalChunks"], 1)
        per_chunk = []
        while state["status"] == "rewrite":
            state, calls = self.spy_accept(state, Path(state["inputPath"]).read_text(encoding="utf-8"))
            per_chunk.append(calls[0]["lexicalNouns"])
        # Chunk by chunk, each check names the nouns of its own chunk only; the last chunk's 역학 is not the first's 렌즈.
        self.assertEqual(per_chunk[0], ["렌즈"])
        self.assertEqual(per_chunk[-1], ["역학"])
        self.assertTrue(all(nouns == [] for nouns in per_chunk[1:-1]), per_chunk)
        output = self.root / "result.md"
        _done, calls = self.spy("finalize", "--job", state["job"], "--output", output)
        self.assertEqual(calls, [{"operation": "check", "lexicalNouns": ["렌즈", "역학"]}])
        self.assertEqual(output.read_text(encoding="utf-8"), source)
        self.call("cleanup", "--job", state["job"])


class DirectTextLexicalExemptionTest(DirectGatewayCase):
    """End to end on the real bridge: the owner-approved exemption lets 렌즈 go and nothing else."""

    def test_replacing_only_the_flagged_noun_is_accepted_and_exported(self):
        for kind, strength in (("direct-text", "normal"), ("direct-text", "very-strong"), ("text-file", "strong")):
            with self.subTest(kind=kind, strength=strength):
                state = self.accept(self.prepare(EXEMPT_SOURCE, kind, strength), EXEMPT_LENS_ONLY)
                self.assertEqual(state["decision"], "accept")
                self.assertNotIn("DIRECT_TEXT_FIDELITY_RESTRICTED", " ".join(state["warnings"]))
                self.assertEqual(state["status"], "ready-to-finalize")
                output = self.root / f"{kind}-{strength}.md"
                # The full-document guard at finalize is exempted the same way.
                self.call("finalize", "--job", state["job"], "--output", output)
                self.assertEqual(output.read_text(encoding="utf-8"), EXEMPT_LENS_ONLY)
                self.call("cleanup", "--job", state["job"])

    def test_without_the_exemption_the_same_replacement_is_restricted(self):
        # The control: the Gateway passes no nouns (what it did before) and the very same reply is rejected.
        state = self.prepare(EXEMPT_SOURCE)
        reply, _calls = self.spy_accept(state, EXEMPT_LENS_ONLY, LEXICAL_TEST_NO_EXEMPTION="1")
        self.assertEqual((reply["decision"], reply["attempt"]), ("retry", 2))
        self.assertIn("DIRECT_TEXT_FIDELITY_RESTRICTED", " ".join(reply["warnings"]))
        self.call("cleanup", "--job", state["job"])

    def test_dropping_another_concept_noun_is_still_restricted_then_rolled_back(self):
        for name, candidate in (("실적", EXEMPT_DROPS_CONCEPT), ("흐름", EXEMPT_DROPS_OTHER_CONCEPT)):
            with self.subTest(dropped=name):
                state = self.prepare(EXEMPT_SOURCE)
                retry = self.accept(state, candidate)
                self.assertEqual((retry["decision"], retry["attempt"]), ("retry", 2))
                self.assertIn("DIRECT_TEXT_FIDELITY_RESTRICTED", " ".join(retry["warnings"]))
                rollback = self.accept(retry, candidate)
                self.assertEqual(rollback["decision"], "rollback")
                output = self.root / f"dropped-{name}.md"
                self.call("finalize", "--job", state["job"], "--output", output)
                self.assertEqual(output.read_text(encoding="utf-8"), EXEMPT_SOURCE)
                self.call("cleanup", "--job", state["job"])

    def test_a_conditional_noun_is_exempt_only_when_it_is_repeated(self):
        once, twice = ("시장 역학이 크게 달라졌다. 참석자는 12명이었다.\n",
                       "시장 역학이 크게 달라졌다. 역학은 계속 바뀐다. 참석자는 12명이었다.\n")
        retry = self.accept(self.prepare(once), once.replace("역학", "구도"))
        self.assertEqual(retry["decision"], "retry")
        self.assertIn("DIRECT_TEXT_FIDELITY_RESTRICTED", " ".join(retry["warnings"]))
        self.call("cleanup", "--job", retry["job"])
        accepted = self.accept(self.prepare(twice), twice.replace("역학", "구도"))
        self.assertEqual(accepted["decision"], "accept")
        self.assertNotIn("DIRECT_TEXT_FIDELITY_RESTRICTED", " ".join(accepted["warnings"]))
        self.call("cleanup", "--job", accepted["job"])


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
