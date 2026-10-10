"""Super Sejong v2 on the agent-skill path (WP-13): engine_runtime/skill_gateway.py with SUPER_SEJONG_ENGINE=v2.

Every gateway call here is a real subprocess with the switch set explicitly, so the tests do not depend on the
engine of the surrounding run (test_gateway.py pins the legacy engine the same way). Text is constructed, except
the six seed composites of the benchmark (original project text, docs/research/super-sejong/v2/benchmark), which
only feed the equivalence test between this path and `sejong_cli.py check`. The stub writer replies are built
from the engine's own plan, as a model that follows the prompt would build them; nothing calls a model.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine_runtime import sejong as sejong_package  # noqa: E402
from engine_runtime.sejong import apply as AP  # noqa: E402
from engine_runtime.sejong import floor as FLOOR  # noqa: E402
from engine_runtime.sejong import io as sio  # noqa: E402
from engine_runtime.sejong import plan as PL  # noqa: E402

GATEWAY = ROOT / "engine_runtime/skill_gateway.py"
CLI = ROOT / "engine_runtime/sejong_cli.py"
BRIDGE = ROOT / "build-resources/skill-bridge/skill-bridge.cjs"
TSX = ROOT / "node_modules/.bin/tsx"
SEED_COMPOSITES = ROOT / "docs/research/super-sejong/v2/benchmark/seed_composites.jsonl"
BLOG = ("오늘은 세미나 후기를 정리합니다. 왜냐하면 일정이 바뀌었습니다. 참가비는 3만 원이 됬습니다.\n\n"
        "현장 분위기가 좋았어요😀 ㅎㅎ 궁금한 점이 있으시면 댓글로 문의해 주세요.\n")
CLEAN = "회의는 오전 10시에 시작합니다. 자료는 미리 읽어 오세요.\n"
REASON = "22 어휘상 잘못된 표현"


def composites():
    rows = [json.loads(line) for line in SEED_COMPOSITES.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row["item_type"] == "composite_document"]


def environment(engine="v2", **extra):
    env = {key: value for key, value in os.environ.items() if not key.startswith("SUPER_SEJONG_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    if engine:
        env["SUPER_SEJONG_ENGINE"] = engine
    env.update(extra)
    return env


def long_document(request_in=None):
    """Constructed text of about 17,000 characters (several chunks) of plain 합쇼체 sentences that raise no finding,
    with one SSJ-A01 sentence (왜냐하면 without a reason ending) in paragraph `request_in` when given."""
    paragraph = "회의는 오전에 열렸습니다. 참석자들은 안건을 차례로 검토했습니다. 결과는 다음 주에 공유됩니다. " * 12
    paragraphs = [f"{i}번째 문단입니다. {paragraph.strip()}" for i in range(1, 26)]
    if request_in is not None:
        paragraphs[request_in - 1] += " 왜냐하면 일정이 바뀌었습니다."
    return "\n\n".join(paragraphs) + "\n"


def reply(*items, rewritten="", warnings=()):
    return {"replacements": [{"id": i, "text": t, "reason": r} for i, t, r in items], "rewrittenText": rewritten,
            "warnings": list(warnings)}


def stub_reply(plan, source, target, only=None):
    """What a writer that rewrote the chunk into `target` would answer: every sentence that differs becomes one
    replacement under its request id, or its own id when open review is on (the engine's aligner finds them)."""
    doc = PL.source_document(plan, source)
    pieces = AP.distribute(doc, target)
    requests = {r.sentence: r.id for r in plan.requests}
    items = []
    for k, unit in enumerate(doc.units):
        piece = pieces.get(k)
        if not piece or not piece.strip() or piece.strip() == unit.text:
            continue
        rid = requests.get(unit.id) or (unit.id if plan.open_review.enabled else None)
        if rid is None or (only is not None and rid not in only):
            continue
        items.append((rid, piece.strip(), REASON))
    return reply(*items)


def damage(response):
    """The first replacement that holds a number comes back with the number changed (a floor failure)."""
    out = json.loads(json.dumps(response))
    for item in out["replacements"]:
        match = re.search(r"\d+", item["text"])
        if match:
            item["text"] = item["text"][:match.start()] + str(int(match.group()) + 1) + item["text"][match.end():]
            return out, True
    return out, False


class BridgeAccess:
    """skill_bridge.invoke without leaving engine_runtime on sys.path for the other test modules."""
    @staticmethod
    def invoke(operation, **payload):
        sys.path.insert(0, str(ROOT / "engine_runtime"))
        try:
            import skill_bridge
        finally:
            sys.path.remove(str(ROOT / "engine_runtime"))
        return skill_bridge.invoke(operation, **payload)


class SkillPathCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The bridge is a bundle of src/**; a bundle older than the sources it was built from lacks the v2 ops.
        sources = [ROOT / "scripts/skill-bridge.ts", *(ROOT / "src/engine/sejong").glob("*.ts")]
        newest = max(path.stat().st_mtime for path in sources)
        if BRIDGE.is_file() and BRIDGE.stat().st_mtime >= newest:
            return
        node = os.environ.get("NODE_COMMAND") or shutil.which("node")
        if not node:
            raise unittest.SkipTest("Node is required to build the skill bridge (node scripts/build-skill-bridge.mjs)")
        subprocess.run([node, str(ROOT / "scripts/build-skill-bridge.mjs")], check=True, cwd=ROOT, capture_output=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="humanize-sejong-skill-")
        self.root = Path(self.temp.name).resolve()
        self.input = self.root / "source.txt"
        self.jobs = self.root / "jobs"

    def tearDown(self):
        if self.root.parent != Path(tempfile.gettempdir()).resolve() or not self.root.name.startswith("humanize-sejong-skill-"):
            raise ValueError("Invalid cleanup root")
        self.temp.cleanup()

    # ---- gateway ----
    def run_gateway(self, *args, env=None, driver=None):
        command = [sys.executable, *([str(driver)] if driver else [str(GATEWAY)]), "--workspace-root", str(self.jobs),
                   *map(str, args)]
        return subprocess.run(command, capture_output=True, encoding="utf-8", env=env or environment())

    def call(self, *args, succeeds=True, env=None, driver=None):
        result = self.run_gateway(*args, env=env, driver=driver)
        self.assertEqual(result.returncode, 0 if succeeds else 1, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def prepare(self, text=BLOG, kind="direct-text", strength=None, env=None):
        """strength None: medium for direct text, none (normal) for a file."""
        self.input.write_text(text, encoding="utf-8", newline="")
        args = ["prepare", "--input", self.input]
        if kind:
            args += ["--input-kind", kind]
            if kind == "direct-text" or strength:
                args += ["--strength", strength or "medium"]
        return self.call(*args, env=env)

    def write_reply(self, state, response):
        Path(state["responsePath"]).write_text(response if isinstance(response, str) else json.dumps(response, ensure_ascii=False),
                                               encoding="utf-8")

    def accept(self, state, response=None, env=None):
        if response is not None:
            self.write_reply(state, response)
        return self.call("accept", "--job", state["job"], "--chunk", state["chunk"], "--attempt", state["attempt"],
                         "--source-hash", state["sourceHash"], "--response", state["responsePath"], env=env)

    def job_dir(self, state):
        return self.jobs / state["job"]

    def job_state(self, state):
        return json.loads((self.job_dir(state) / "job.json").read_text(encoding="utf-8"))

    def finalize(self, state):
        self.exports = getattr(self, "exports", 0) + 1
        output = self.root / f"final-{self.exports}.md"
        done = self.call("finalize", "--job", state["job"], "--output", output)
        return done, output.read_text(encoding="utf-8")

    def source_of(self, state):
        return (self.job_dir(state) / f"source-{state['chunk']}.txt").read_text(encoding="utf-8")

    def plan_of(self, state):
        return sio.read_plan(self.job_dir(state) / f"plan-{state['chunk']:02d}.json")


# ==========================================================================
# the host protocol
# ==========================================================================
class ProtocolTests(SkillPathCase):
    def test_prepare_records_engine_flags_and_hands_the_host_a_prompt_without_rules(self):
        state = self.prepare(env=environment(SUPER_SEJONG_MODE="shadow"))
        self.assertEqual(state["status"], "rewrite")
        self.assertEqual(state["engine"], {"id": "super-sejong", "version": sejong_package.VERSION})
        self.assertNotIn("rulesPath", state)
        self.assertNotIn("sentencesPath", state)
        record = self.job_state(state)
        self.assertEqual((record["engine"], record["engineId"], record["engineVersion"], record["engineSchema"]),
                         ("v2", "super-sejong", sejong_package.VERSION, sejong_package.SCHEMA_VERSION))
        self.assertEqual(record["genre"], "blog")                       # the skill route sends blog (DESIGN 9.2a item 4)
        self.assertEqual(record["sejongFlags"], {"SUPER_SEJONG_ENGINE": "v2", "SUPER_SEJONG_MODE": "shadow"})
        self.assertEqual(sorted(record["planHashes"]), ["1"])
        prompt = Path(state["instructionsPath"]).read_text(encoding="utf-8")
        self.assertIn("너는 한국어 교정 보조자다.", prompt)
        self.assertRegex(prompt, r"BEGIN_SOURCE_[0-9A-Za-z]{32}\n")
        self.assertIn('"id":"R1"', prompt)
        self.assertNotIn("quick-rules", prompt)                           # no rulebook, on any attempt
        self.assertNotIn("룰북", prompt)
        plan = self.plan_of(state)
        self.assertEqual((plan.options.genre, plan.options.strength, plan.options.input_kind), ("blog", "medium", "direct-text"))
        manifest = json.loads((self.job_dir(state) / "chunk_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["sejong"]["plans"], [{"chunk": 1, "file": "plan-01.json", "needsModel": True}])

    def test_genre_follows_an_explicit_default_and_is_recorded(self):
        state = self.prepare(env=environment(SUPER_SEJONG_GENRE_DEFAULT="report"))
        self.assertEqual(self.job_state(state)["genre"], "report")
        self.assertEqual(self.plan_of(state).options.genre, "report")

    def test_v2_reply_is_parsed_applied_and_finalized(self):
        state = self.prepare()
        plan = self.plan_of(state)
        self.assertEqual([(r.id, r.sentence, r.rules) for r in plan.requests], [("R1", "S2", ["SSJ-A01"])])
        state = self.accept(state, reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다.", "SSJ-A01")))
        self.assertEqual((state["status"], state["decision"]), ("ready-to-finalize", "accept"))
        self.assertNotIn("rulesPath", state)
        self.assertEqual(state["sejong"]["requestStatus"]["FIXED"], 1)
        self.assertEqual(state["sejong"]["revertedSentences"], 0)
        self.assertEqual(state["warnings"], [])
        done, output = self.finalize(state)
        self.assertEqual(done["status"], "done")
        # the request is applied and the deterministic fix (됬 -> 됐, OD 3) came with the chunk, outside any request
        self.assertEqual(output, BLOG.replace("왜냐하면 일정이 바뀌었습니다", "왜냐하면 일정이 바뀌었기 때문입니다").replace("됬", "됐"))
        self.call("cleanup", "--job", state["job"])
        self.assertEqual(list(self.jobs.iterdir()), [])

    def test_open_review_nomination_by_sentence_id(self):
        state = self.prepare()
        report_path = self.job_dir(state) / "check-01-1.json"
        # S1 has no request; the plan enables the open review (medium), so naming it by its sentence id is licensed
        state = self.accept(state, reply(("S1", "오늘은 세미나의 후기를 정리합니다.", "03 부적절한 조사 사용")))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(state["decision"], "accept")
        self.assertEqual({s["id"]: (s["request"], s["status"]) for s in report["sentences"]}["S1"], ("S1", "accepted"))
        done, output = self.finalize(state)
        self.assertTrue(output.startswith("오늘은 세미나의 후기를 정리합니다."))

    def test_no_rules_path_or_sentences_path_anywhere_in_a_v2_job(self):
        outputs = []
        state = self.prepare()
        outputs.append(state)
        self.write_reply(state, reply())
        outputs.append(self.call("next", "--job", state["job"]))
        outputs.append(self.accept(state))
        done = self.call("finalize", "--job", state["job"], "--output", self.root / "x.md")
        outputs.append(done)
        for answer in outputs:
            self.assertNotIn("rulesPath", answer)
            self.assertNotIn("sentencesPath", answer)
            self.assertNotIn("rulesPath", json.dumps(answer))

    def test_roundtrip_keeps_crlf_input_and_never_overwrites(self):
        text = "# 회의\n\n회의는 오전에 열렸습니다. 왜냐하면 일정이 바뀌었습니다. 참석자는 12명이었습니다.\n"
        self.input.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        state = self.call("prepare", "--input", self.input, "--input-kind", "direct-text", "--strength", "medium")
        self.call("finalize", "--job", state["job"], "--output", self.root / "premature.md", succeeds=False)
        state = self.accept(state, reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다.", "SSJ-A01")))
        self.call("finalize", "--job", state["job"], "--output", self.input, succeeds=False)
        done, output = self.finalize(state)
        self.assertEqual(output, text.replace("일정이 바뀌었습니다", "일정이 바뀌었기 때문입니다"))
        self.assertIn(b"\r\n", self.input.read_bytes())                  # the original is untouched
        self.call("cleanup", "--job", state["job"])

    def test_duplicate_accept_and_wrong_chunk_attempt_or_hash_fail(self):
        state = self.prepare()
        first = dict(state)
        self.write_reply(state, reply())
        moved = self.accept(state)
        self.assertEqual(moved["status"], "ready-to-finalize")
        for override in ({"chunk": 2}, {"attempt": 2}, {"sourceHash": "0" * 64}, {}):
            args = {**first, **override}
            self.call("accept", "--job", args["job"], "--chunk", args["chunk"], "--attempt", args["attempt"],
                      "--source-hash", args["sourceHash"], "--response", first["responsePath"], succeeds=False)

    def test_modified_source_plan_and_unsafe_jobs_are_rejected(self):
        self.call("cleanup", "--job", "../../outside", succeeds=False)
        state = self.prepare()
        job = self.job_dir(state)
        plan = job / "plan-01.json"
        original = plan.read_text(encoding="utf-8")
        plan.write_text(original.replace('"needsModel": true', '"needsModel": false'), encoding="utf-8")
        self.call("next", "--job", state["job"], succeeds=False)
        plan.write_text(original, encoding="utf-8")
        self.call("next", "--job", state["job"])
        (job / "01_input.txt").write_text("changed", encoding="utf-8")
        self.call("next", "--job", state["job"], succeeds=False)
        self.call("cleanup", "--job", state["job"])
        self.assertEqual(list(self.jobs.iterdir()), [])

    def test_comparison_export_is_final_only_and_recoverable(self):
        state = self.accept(self.prepare(), reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다.", "SSJ-A01")))
        output, html = self.root / "final.md", self.root / "compare.html"
        html.write_text("existing", encoding="utf-8")
        self.call("finalize", "--job", state["job"], "--output", output, "--comparison-output", html, succeeds=False)
        self.assertFalse(output.exists())
        html.unlink()
        done = self.call("finalize", "--job", state["job"], "--output", output, "--comparison-output", html)
        self.assertEqual(done["comparisonPath"], str(html))
        self.assertIn("기 때문입니다", output.read_text(encoding="utf-8"))
        self.assertIn("최종문", html.read_text(encoding="utf-8"))

    def test_a_text_file_job_at_normal_gets_only_fix_requests(self):
        state = self.prepare(BLOG, kind="text-file")
        self.assertEqual(state["rewriteOptions"], {"inputKind": "text-file", "strength": "normal"})
        plan = self.plan_of(state)
        self.assertEqual((plan.options.input_kind, plan.open_review.enabled, [r.tier for r in plan.requests]),
                         ("text-file", False, ["FIX"]))
        legacy_file = self.prepare(BLOG, kind=None)                      # no input kind: a file job, the same plan
        self.assertNotIn("rewriteOptions", legacy_file)
        self.assertEqual(self.plan_of(legacy_file).options.input_kind, "text-file")

    def test_a_text_file_job_above_normal_is_planned_like_direct_text(self):
        # Owner request 2026-10-10: the file takes the strength; its plan matches the direct-text plan at it.
        file_state = self.prepare(BLOG, kind="text-file", strength="strong")
        self.assertEqual(file_state["rewriteOptions"], {"inputKind": "text-file", "strength": "strong"})
        direct_state = self.prepare(BLOG, kind="direct-text", strength="strong")
        file_plan, direct_plan = self.plan_of(file_state), self.plan_of(direct_state)
        self.assertEqual((file_plan.options.input_kind, file_plan.options.strength), ("text-file", "strong"))
        self.assertEqual(([(r.sentence, r.tier) for r in file_plan.requests], file_plan.open_review.enabled),
                         ([(r.sentence, r.tier) for r in direct_plan.requests], direct_plan.open_review.enabled))


# ==========================================================================
# preservation through the gateway (v2 variants of the legacy gateway cases)
# ==========================================================================
class PreservationTests(SkillPathCase):
    def test_a_footnote_definition_edit_in_a_later_chunk_never_reaches_the_output(self):
        paragraph = "회의는 오전에 열렸습니다. 참석자들은 안건을 차례로 검토했습니다. 결과는 다음 주에 공유됩니다. " * 12
        body = "선행 연구에 따르면 참여율은 높았습니다.1) 후속 조사에서도 비슷한 결과가 보고되었습니다.2)\n\n" + \
            "\n\n".join(f"{i}번째 문단입니다. {paragraph.strip()}" for i in range(1, 36))
        definitions = "1) 여기서 참여율은 전체 등록자 대비 실제 응답자의 비율을 말한다.\n2) 통계청, 2025년 조사 보고서.\n"
        source = body + "\n\n" + definitions + "\n## 부록\n\n설문지 원본을 싣는다. 응답자 명단은 따로 보관한다.\n"
        state = self.prepare(source, kind="direct-text", strength="medium")
        self.assertGreater(state["totalChunks"], 1)
        edited = {"1) 여기서 참여율은 전체 등록자 대비 실제 응답자의 비율을 말한다.": "1) 여기서 참여율은 등록자 가운데 실제로 응답한 사람의 비율이다."}
        decisions = []
        while state["status"] == "rewrite":
            plan, chunk_text = self.plan_of(state), self.source_of(state)
            items = [(unit.id, edited[unit.text], REASON) for unit in PL.source_document(plan, chunk_text).units if unit.text in edited]
            state = self.accept(state, reply(*items))
            decisions.append((bool(items), state["decision"]))
        # the chunk with the definition is asked twice: the edit fails the floor (footnote_def), and the retry repeats it
        self.assertEqual([decision for asked, decision in decisions if asked], ["retry", "accept"])
        done, output = self.finalize(state)
        self.assertIn("전체 등록자 대비 실제 응답자의 비율을 말한다", output)
        self.assertNotIn("등록자 가운데", output)

    def test_a_writer_that_merges_two_paragraphs_gets_them_back_apart(self):
        source = "# 제목\n\n회의는 오전에 열렸습니다. 참석자들은 안건을 검토했습니다.\n\n회의는 오후에 끝났습니다. 결과는 다음 주에 공유됩니다.\n\n마지막 문단은 그대로 둡니다.\n"
        state = self.prepare(source)
        merged = self.source_of(state).replace("검토했습니다.\n\n회의는", "검토했습니다. 회의는")
        self.assertNotEqual(merged, source)
        state = self.accept(state, {"rewrittenText": merged, "warnings": []})        # a legacy-shaped full-text reply
        while state["status"] == "rewrite":
            state = self.accept(state, reply())
        done, output = self.finalize(state)
        self.assertEqual(output.count("\n\n"), source.count("\n\n"))
        self.assertEqual(output, source)

    def test_a_changed_number_in_a_requested_sentence_is_retried_and_then_reverted(self):
        text = "참석자는 12명이었습니다. 왜냐하면 일정이 바뀌었습니다. 회의는 오전에 열렸습니다.\n"
        state = self.prepare(text, kind="text-file")
        changed = reply(("R1", "왜냐하면 일정이 13명 때문에 바뀌었습니다.", "SSJ-A01"))
        state = self.accept(state, changed)
        self.assertEqual((state["decision"], state["attempt"]), ("retry", 2))
        state = self.accept(state, changed)
        self.assertEqual(state["status"], "ready-to-finalize")
        done, output = self.finalize(state)
        self.assertEqual(output, text)
        self.assertNotIn("13명", output)


# ==========================================================================
# empty plans, deterministic fixes, and the Node-free path
# ==========================================================================
class EmptyPlanTests(SkillPathCase):
    def test_empty_plan_chunks_auto_advance_without_asking_the_host(self):
        text = long_document(request_in=24)
        state = self.prepare(text, kind=None)
        self.assertGreater(state["totalChunks"], 2)
        self.assertEqual(state["status"], "rewrite")
        self.assertGreater(state["chunk"], 1)                              # chunk 1 (and any other empty one) was decided here
        record = self.job_state(state)
        self.assertEqual(record["current"], state["chunk"] - 1)
        self.assertEqual(record["noEditChunks"], list(range(1, state["chunk"])))
        notes = [w for w in state["warnings"] if w.startswith("SEJONG_NO_EDIT_NEEDED")]
        self.assertEqual(len(notes), 1)
        for index in record["noEditChunks"]:
            written = (self.job_dir(state) / f"02_chunk_{index:02d}_rewritten.txt").read_text(encoding="utf-8")
            self.assertEqual(written, (self.job_dir(state) / f"source-{index}.txt").read_text(encoding="utf-8"))
            report = json.loads((self.job_dir(state) / f"check-{index:02d}-1.json").read_text(encoding="utf-8"))
            self.assertEqual((report["gate"]["exit_code"], report["policy"], report["counts"]["revertedSentences"]), (0, "accept", 0))
        # the host is asked only for the chunk that has a request, then the job is ready to finalize
        calls = 0
        while state["status"] == "rewrite":
            calls += 1
            plan, source = self.plan_of(state), self.source_of(state)
            target = source.replace("왜냐하면 일정이 바뀌었습니다.", "왜냐하면 일정이 바뀌었기 때문입니다.")
            state = self.accept(state, stub_reply(plan, source, target))
            self.assertEqual(state["decision"], "accept")
        self.assertEqual((calls, state["status"]), (1, "ready-to-finalize"))
        done, output = self.finalize(state)
        self.assertEqual(output, text.replace("왜냐하면 일정이 바뀌었습니다.", "왜냐하면 일정이 바뀌었기 때문입니다."))

    def test_job_with_every_plan_empty_needs_neither_host_nor_node(self):
        env = environment()
        env.pop("NODE_COMMAND", None)
        env["PATH"] = str(self.root)                                         # no node on the path
        text = long_document()
        self.input.write_text(text, encoding="utf-8", newline="")
        state = self.call("prepare", "--input", self.input, env=env)
        self.assertGreater(state["totalChunks"], 1)
        self.assertEqual(state["status"], "ready-to-finalize")               # straight from prepare
        self.assertEqual(self.job_state(state)["current"], state["totalChunks"])
        output = self.root / "final.md"
        done = self.call("finalize", "--job", state["job"], "--output", output, env=env)
        self.assertEqual((done["status"], output.read_text(encoding="utf-8")), ("done", text))
        self.call("cleanup", "--job", state["job"], env=env)

    def test_deterministic_fixes_apply_when_no_model_call_is_made(self):
        text = "참가비는 3만 원이 됬습니다. 자리는 몇일 전에 정했습니다.\n"
        state = self.prepare(text, kind="text-file")
        self.assertEqual(state["status"], "ready-to-finalize")
        done, output = self.finalize(state)
        self.assertEqual(output, "참가비는 3만 원이 됐습니다. 자리는 며칠 전에 정했습니다.\n")

    def test_open_review_off_turns_a_medium_job_without_findings_into_a_no_call_job(self):
        state = self.prepare(CLEAN, env=environment(SUPER_SEJONG_OPEN_REVIEW="off"))
        self.assertEqual(state["status"], "ready-to-finalize")
        asked = self.prepare(CLEAN)                                          # the default: medium has the open review
        self.assertEqual(asked["status"], "rewrite")


# ==========================================================================
# retries, unusable replies, rollback
# ==========================================================================
class RetryTests(SkillPathCase):
    def damaged_attempt(self):
        state = self.prepare()
        plan, source = self.plan_of(state), self.source_of(state)
        gold = source.replace("왜냐하면 일정이 바뀌었습니다", "왜냐하면 일정이 바뀌었기 때문입니다").replace("3만", "3만")
        good = stub_reply(plan, source, gold)
        # the number of the fee changes in the damaged reply: S3 is not a request, so it is a nomination here
        bad = reply(*[(item["id"], item["text"], item["reason"]) for item in good["replacements"]],
                    ("S3", "참가비는 4만 원이 됐습니다.", "16 한글 맞춤법·표준어 규정 위반"))
        return state, good, bad

    def test_a_failed_sentence_is_retried_once_with_a_prompt_naming_only_it(self):
        state, good, bad = self.damaged_attempt()
        state = self.accept(state, bad)
        self.assertEqual((state["decision"], state["status"], state["attempt"]), ("retry", "rewrite", 2))
        self.assertTrue(any(w.startswith("CHUNK_RETRY") for w in state["warnings"]))
        retry = Path(state["instructionsPath"]).read_text(encoding="utf-8")
        self.assertIn("[재시도]", retry)
        self.assertIn("S3 이전 답:", retry)
        self.assertIn("S3 이전 답: [보호] 구간이 바뀌었다(protected_span_changed).", retry)   # the named violation, in Korean
        self.assertNotIn('"id":"R1"', retry)                                 # the accepted request is not asked again
        self.assertNotIn("quick-rules", retry)
        report = json.loads((self.job_dir(state) / "check-01-1.json").read_text(encoding="utf-8"))
        self.assertEqual([item["sentence"] for item in report["retry"]], ["S3"])
        state = self.accept(state, reply(("S3", "참가비는 3만 원이 됐습니다.", "16 한글 맞춤법·표준어 규정 위반")))
        self.assertEqual(state["decision"], "accept")
        done, output = self.finalize(state)
        self.assertIn("3만 원이 됐습니다", output)
        self.assertIn("기 때문입니다", output)                               # the attempt-1 acceptance was kept

    def test_attempt_2_touches_only_the_failed_requests(self):
        state, good, bad = self.damaged_attempt()
        state = self.accept(state, bad)
        self.assertEqual(state["attempt"], 2)
        # the retry reply fixes S3 but also rewrites R1 again: R1 passed at attempt 1 and is not on the retry list
        again = reply(("R1", "왜냐하면 일정이 바뀌어서입니다.", "SSJ-A01"), ("S3", "참가비는 3만 원이 됐습니다.", "16 한글 맞춤법·표준어 규정 위반"))
        plan_json = json.loads((self.job_dir(state) / "plan-01.json").read_text(encoding="utf-8"))
        retry = json.loads((self.job_dir(state) / "check-01-1.json").read_text(encoding="utf-8"))["retry"]
        parsed = BridgeAccess.invoke("parse-v2", plan=plan_json, raw=json.dumps(again, ensure_ascii=False), retry=retry)
        if parsed["ok"] and "not_in_retry" in json.dumps(parsed["rejected"]):   # the reader of the merged engine drops it too
            self.assertEqual([item["id"] for item in parsed["forward"]["replacements"]], ["S3"])
        state = self.accept(state, again)
        self.assertEqual(state["decision"], "accept")
        done, output = self.finalize(state)
        self.assertIn("기 때문입니다", output)                               # the attempt-1 edit stays
        self.assertNotIn("바뀌어서입니다", output)
        self.assertIn("3만 원이 됐습니다", output)

    def test_second_failure_keeps_the_verified_sentences_and_records_rollback_or_warning(self):
        state, good, bad = self.damaged_attempt()
        state = self.accept(state, bad)
        state = self.accept(state, reply(("S3", "참가비는 4만 원이 됐습니다.", "16 한글 맞춤법·표준어 규정 위반")))
        self.assertEqual(state["status"], "ready-to-finalize")
        self.assertIn(state["decision"], ("accept-with-warning", "accept"))
        self.assertTrue(any(w.startswith("SEJONG_SENTENCES_REVERTED") for w in state["warnings"]))
        done, output = self.finalize(state)
        self.assertIn("3만 원이 됐습니다", output)                            # the damaged number never reaches the output
        self.assertNotIn("4만", output)
        self.assertIn("기 때문입니다", output)

    def test_unusable_replies_cost_the_attempt_then_roll_back_to_base(self):
        state = self.prepare()
        state = self.accept(state, "not json at all")
        self.assertEqual((state["decision"], state["attempt"]), ("retry", 2))
        self.assertTrue(any(w.startswith("MODEL_OUTPUT_UNUSABLE") and "not_json" in w for w in state["warnings"]))
        state = self.accept(state, reply(("R9", "x", "unknown id")))
        self.assertEqual((state["decision"], state["status"]), ("rollback", "ready-to-finalize"))
        self.assertTrue(any(w.startswith("CHUNK_ROLLED_BACK") and "맞춤법 오류 1곳만 고쳤습니다" in w for w in state["warnings"]))
        self.assertTrue(any(w.startswith("MODEL_OUTPUT_UNUSABLE") and "unknown_id" in w for w in state["warnings"]))
        done, output = self.finalize(state)
        self.assertEqual(output, BLOG.replace("됬", "됐"))                   # a rollback delivers base(x), as the server does

    def test_reply_in_the_legacy_shape_is_read_as_a_full_text_candidate(self):
        state = self.prepare()
        candidate = BLOG.replace("왜냐하면 일정이 바뀌었습니다", "왜냐하면 일정이 바뀌었기 때문입니다").replace(
            "현장 분위기가 좋았어요", "현장 분위기가 매우 좋았어요")
        state = self.accept(state, {"rewrittenText": candidate, "warnings": []})
        # the requested sentence is verified and kept; the sentence nobody asked about is a collateral edit: reverted
        report = json.loads((self.job_dir(state) / "check-01-1.json").read_text(encoding="utf-8"))
        self.assertEqual((state["decision"], report["counts"]["collateralReverts"], report["requestStatus"]["FIXED"]), ("accept", 1, 1))
        done, output = self.finalize(state)
        self.assertIn("기 때문입니다", output)
        self.assertNotIn("매우", output)

    def test_host_warnings_are_counted_never_copied(self):
        state = self.prepare()
        state = self.accept(state, reply(warnings=["원문 문장 전체를 여기에 붙여 넣음 — 참가비는 3만 원이 됬습니다."]))
        text = json.dumps(state, ensure_ascii=False)
        self.assertIn("HOST_REVIEW_WARNING: 1개", text)
        self.assertNotIn("참가비는", text)


# ==========================================================================
# engine id and version
# ==========================================================================
DRIVER = """
import json, os, sys
sys.path.insert(0, {runtime!r})
import skill_gateway
sj = skill_gateway.sejong()
seen = []
real = sj.verify.verify_document
def spy(*args, **kwargs):
    seen.append(kwargs.get("attempt"))
    gate = real(*args, **kwargs)
    forced = os.environ.get("FORCE_GATE_EXIT")
    if forced:
        hard = [code for code in os.environ.get("FORCE_GATE_HARD", "").split(",") if code]
        gate = {{**gate, "gate": {{"exit_code": int(forced)}}, "hardFailures": hard,
                "policy": {{"1": "accept-with-warning", "2": "rollback"}}[forced]}}
    return gate
sj.verify.verify_document = spy
fake = os.environ.get("FAKE_ENGINE_VERSION")
if fake:
    real_version = sj.package.read_engine_version
    sj.package.read_engine_version = lambda *a, **k: {{**real_version(*a, **k), "version": fake}}
try:
    code = skill_gateway.main()
finally:
    open({record!r}, "w").write(json.dumps(seen))
raise SystemExit(code)
"""


class EngineTests(SkillPathCase):
    def driver(self):
        path = self.root / "driver.py"
        record = self.root / "driver-calls.json"
        path.write_text(DRIVER.format(runtime=str(ROOT / "engine_runtime"), record=str(record)), encoding="utf-8")
        return path, record

    def test_a_changed_engine_version_fails_the_job(self):
        state = self.prepare()
        driver, _record = self.driver()
        stale = self.run_gateway("next", "--job", state["job"], driver=driver, env=environment(FAKE_ENGINE_VERSION="9.9.9"))
        self.assertEqual(stale.returncode, 1)
        self.assertIn("The engine changed during this job", stale.stdout)
        self.call("next", "--job", state["job"])                            # the real version still works
        job = self.job_dir(state) / "job.json"
        record = json.loads(job.read_text(encoding="utf-8"))
        for key, value in (("engineVersion", "1.0.0"), ("engineId", "other"), ("engineSchema", 2)):
            job.write_text(json.dumps({**record, key: value}), encoding="utf-8")
            result = self.run_gateway("next", "--job", state["job"])
            self.assertEqual(result.returncode, 1, key)
            self.assertIn("The engine changed during this job", result.stdout, key)
            accepted = self.run_gateway("accept", "--job", state["job"], "--chunk", 1, "--attempt", 1,
                                        "--source-hash", state["sourceHash"], "--response", state["responsePath"])
            self.assertEqual(accepted.returncode, 1, key)
        job.write_text(json.dumps(record), encoding="utf-8")
        self.call("next", "--job", state["job"])
        self.call("cleanup", "--job", state["job"])

    def test_the_job_keeps_the_engine_it_was_prepared_with(self):
        state = self.prepare()
        for engine in (None, "legacy"):
            result = self.run_gateway("next", "--job", state["job"], env=environment(engine))
            self.assertEqual(result.returncode, 1)
            self.assertIn("The engine changed during this job", result.stdout)
        self.call("cleanup", "--job", state["job"], env=environment(None))   # cleanup never needs the engine
        self.input.write_text(CLEAN, encoding="utf-8")
        legacy = self.call("prepare", "--input", self.input, env=environment(None))
        self.assertIn("rulesPath", legacy)                                   # an unset switch is the legacy engine, unchanged
        self.assertNotIn("engine", legacy)
        result = self.run_gateway("next", "--job", legacy["job"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("The engine changed during this job", result.stdout)
        self.call("cleanup", "--job", legacy["job"], env=environment(None))

    def test_the_legacy_default_never_imports_the_sejong_package(self):
        script = self.root / "import-probe.py"
        script.write_text(f"""
import json, sys
sys.path.insert(0, {str(ROOT / "engine_runtime")!r})
import skill_gateway
code = skill_gateway.main()
loaded = sorted(name for name in sys.modules if name in ("sejong", "sejong_cli") or name.startswith("sejong."))
print(json.dumps(loaded), file=sys.stderr)
raise SystemExit(code)
""", encoding="utf-8")
        self.input.write_text(CLEAN, encoding="utf-8")
        for engine, expect_loaded in ((None, False), ("legacy", False), ("v2", True)):
            result = self.run_gateway("prepare", "--input", self.input, driver=script, env=environment(engine))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            loaded = json.loads(result.stderr.strip().splitlines()[-1])
            self.assertEqual(bool(loaded), expect_loaded, (engine, loaded))

    def test_finalize_gates_the_whole_document_at_attempt_2(self):
        state = self.accept(self.prepare(), reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다.", "SSJ-A01")))
        driver, record = self.driver()
        output = self.root / "final.md"
        self.call("finalize", "--job", state["job"], "--output", output, driver=driver)
        self.assertEqual(json.loads(record.read_text(encoding="utf-8")), [2])
        self.assertIn("기 때문입니다", output.read_text(encoding="utf-8"))

    def finalize_forced(self, exit_code, hard=""):
        state = self.accept(self.prepare(), reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다.", "SSJ-A01")))
        driver, _record = self.driver()
        output = self.root / f"forced-{exit_code}-{hard or 'none'}.md"
        done = self.call("finalize", "--job", state["job"], "--output", output, driver=driver,
                         env=environment(FORCE_GATE_EXIT=str(exit_code), FORCE_GATE_HARD=hard))
        return done["warnings"], output.read_text(encoding="utf-8")

    def test_the_full_gate_warns_on_exit_1_and_on_codes_a_plan_could_have_licensed(self):
        edited = BLOG.replace("일정이 바뀌었습니다", "일정이 바뀌었기 때문입니다").replace("됬", "됐")
        warnings, output = self.finalize_forced(1)
        self.assertTrue(any(w.startswith("DOCUMENT_REVIEW_RECOMMENDED") and "검토해 주세요" in w for w in warnings), warnings)
        self.assertEqual(output, edited)
        # exit 2 with a code of a plan-licensed family (what an SSJ-A06 repair gives): delivered, with the code named
        warnings, output = self.finalize_forced(2, "polarity_changed")
        self.assertTrue(any(w.startswith("DOCUMENT_REVIEW_RECOMMENDED") and "polarity_changed" in w for w in warnings), warnings)
        self.assertEqual(output, edited)

    def test_a_floor_code_at_the_full_gate_restores_the_whole_source(self):
        # the gateway reads the floor codes from sejong.floor.CODES, so a code added there (weekday_changed) counts too
        for code in [c for c in ("number_dropped", "weekday_changed", "josa_mismatch") if c in FLOOR.CODES]:
            with self.subTest(code=code):
                warnings, output = self.finalize_forced(2, code)
                self.assertTrue(any(w.startswith("DIRECT_TEXT_DOCUMENT_ROLLED_BACK") for w in warnings), warnings)
                self.assertEqual(output, BLOG)                             # nothing is exported half-checked


# ==========================================================================
# the prompt and the reply reader are the TypeScript ones
# ==========================================================================
PROMPT_SCRIPT = """import { readFileSync, writeFileSync } from 'node:fs';
import { buildSejongPrompt, seamContextFrom } from '__PROMPT__';
const input = JSON.parse(readFileSync(process.argv[2]!, 'utf8'));
const seamContext = input.document === undefined ? undefined : seamContextFrom(input.plan, input.document);
writeFileSync(process.argv[3]!, buildSejongPrompt({ plan: input.plan, source: input.source, nonce: input.nonce,
  attempt: input.attempt, retry: input.retry ?? undefined, seamContext }), 'utf8');
"""


class BridgeParityTests(SkillPathCase):
    def render(self, state, attempt, retry=None, document=None):
        """src/engine/sejong/prompt.ts run directly (tsx) on the job's plan, source and nonce."""
        if not TSX.is_file():
            self.skipTest("tsx is not installed")
        job = self.job_dir(state)
        prompt = (job / f"instructions-{state['chunk']}-{attempt}.md").read_text(encoding="utf-8")
        nonce = re.search(r"BEGIN_SOURCE_([0-9A-Za-z]+)", prompt).group(1)
        script, data, out = self.root / "prompt.mts", self.root / "prompt-in.json", self.root / "prompt-out.txt"
        script.write_text(PROMPT_SCRIPT.replace("__PROMPT__", (ROOT / "src/engine/sejong/prompt.ts").as_posix()), encoding="utf-8")
        payload = {"plan": json.loads((job / f"plan-{state['chunk']:02d}.json").read_text(encoding="utf-8")),
                   "source": (job / f"source-{state['chunk']}.txt").read_text(encoding="utf-8"), "nonce": nonce,
                   "attempt": attempt, "retry": retry}
        if document is not None:
            payload["document"] = document
        data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        subprocess.run([str(TSX), str(script), str(data), str(out)], check=True, cwd=ROOT, capture_output=True)
        return prompt, out.read_text(encoding="utf-8")

    def test_context_v2_is_the_prompt_ts_prompt_on_attempts_1_and_2(self):
        state = self.prepare()
        prompt, expected = self.render(state, 1)
        self.assertEqual(prompt, expected)
        plan, source = self.plan_of(state), self.source_of(state)
        bad = reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다.", "SSJ-A01"), ("S3", "참가비는 4만 원이 됐습니다.", REASON))
        state = self.accept(state, bad)
        self.assertEqual(state["attempt"], 2)
        retry = json.loads((self.job_dir(state) / "check-01-1.json").read_text(encoding="utf-8"))["retry"]
        prompt, expected = self.render(state, 2, retry=retry)
        self.assertEqual(prompt, expected)
        self.assertIn("[재시도]", prompt)

    def test_context_v2_carries_the_seam_context_of_a_chunked_document(self):
        text = long_document(request_in=24)
        state = self.prepare(text, kind=None)
        self.assertGreater(state["chunk"], 1)
        document = (self.job_dir(state) / "01_input.txt").read_text(encoding="utf-8")
        prompt, expected = self.render(state, 1, document=document)
        self.assertEqual(prompt, expected)
        self.assertIn("[경계 문맥]", prompt)
        self.assertRegex(prompt, r"BEGIN_SEAM_PREV_[0-9A-Za-z]+\n")

    def bridge(self, operation, **payload):
        return BridgeAccess.invoke(operation, **payload)

    def test_parse_v2_reads_replies_like_the_python_apply_step(self):
        state = self.prepare()
        plan, source = self.plan_of(state), self.source_of(state)
        plan_json = json.loads((self.job_dir(state) / "plan-01.json").read_text(encoding="utf-8"))
        doc = PL.source_document(plan, source)
        cases = {
            "empty": (reply(), True),
            "request": (reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다.", "x")), True),
            "nomination": (reply(("S3", "참가비는 3만 원이 됐습니다.", REASON)), True),
            "unknown id": (reply(("R9", "x", "x")), False),
            "unknown sentence": (reply(("S99", "x", "x")), False),
            "duplicate id": (reply(("R1", "가", "x"), ("R1", "나", "x")), False),
            "request and its own sentence": (reply(("R1", "가나다", "x"), ("S2", "라마바", "x")), False),
            "full text not allowed": (reply(rewritten="전체 글"), False),
            "full text with replacements": (reply(("R1", "가", "x"), rewritten="전체 글"), False),
            "extra key": ({**reply(), "extra": 1}, False),
            "missing key": ({"replacements": [], "warnings": []}, False),
            "empty text": ({**reply(), "replacements": [{"id": "R1", "text": "", "reason": ""}]}, False),
        }
        for name, (response, usable) in cases.items():
            with self.subTest(case=name):
                parsed = self.bridge("parse-v2", plan=plan_json, raw=json.dumps(response, ensure_ascii=False), retry=None)
                self.assertEqual(parsed["ok"], usable, parsed)
                python_usable = AP.apply_response(plan, doc, response, [u.text for u in doc.units]).unusable is None
                self.assertEqual(python_usable, usable)                      # the two readers agree on these replies
        self.assertEqual(self.bridge("parse-v2", plan=plan_json, raw="{", retry=None)["reason"], "not_json")
        newline = self.bridge("parse-v2", plan=plan_json, raw=json.dumps(reply(("R1", "가\n나", "x"))), retry=None)
        self.assertEqual((newline["ok"], newline["rejected"]), (True, [{"id": "R1", "code": "replacement_newline"}]))

    def test_the_excess_of_open_review_nominations_is_rejected_one_by_one_like_the_cli(self):
        # apply.py (so `sejong_cli.py check`, and this gateway) rejects nominations beyond openReview.maxSentences
        # one by one and keeps the rest. The first TypeScript reader called such a reply unusable as a whole; the
        # merged one agrees with apply.py (the branch below accepts either), the gateway never depended on it.
        state = self.prepare()
        plan, source = self.plan_of(state), self.source_of(state)
        plan_json = json.loads((self.job_dir(state) / "plan-01.json").read_text(encoding="utf-8"))
        edits = {"S1": "오늘은 세미나의 후기를 정리합니다.", "S3": "참가비는 3만 원이 됐습니다.",
                 "S4": "현장의 분위기가 좋았어요😀 ㅎㅎ", "S5": "궁금한 점이 있으시면 댓글로 문의해 주세요."}
        self.assertEqual(plan.open_review.max_sentences, 3)
        too_many = reply(*[(sid, text, REASON) for sid, text in edits.items()])
        parsed = self.bridge("parse-v2", plan=plan_json, raw=json.dumps(too_many), retry=None)
        if parsed["ok"]:          # the reader of the merged engine (WP-11b) rejects the excess one by one, like apply.py
            self.assertEqual(parsed["rejected"], [{"id": "S5", "code": "open_review_limit"}])
        else:                     # the first reader called the whole reply unusable
            self.assertEqual(parsed["reason"], "review_limit")
        doc = PL.source_document(plan, source)
        self.assertIsNone(AP.apply_response(plan, doc, too_many, [u.text for u in doc.units]).unusable)
        answered = self.accept(state, too_many)
        report = json.loads((self.job_dir(state) / "check-01-1.json").read_text(encoding="utf-8"))
        codes = {s["id"]: s["codes"] for s in report["sentences"]}
        self.assertEqual(codes["S5"], ["open_review_limit"])              # the fourth nomination, in reply order
        self.assertFalse(any(w.startswith("MODEL_OUTPUT_UNUSABLE") for w in answered["warnings"]))
        self.assertNotEqual(answered["decision"], "rollback")


# ==========================================================================
# this path and `sejong_cli.py check` decide the same
# ==========================================================================
class EquivalenceTests(SkillPathCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, encoding="utf-8",
                              env=environment())

    def cli_run(self, run, text, replies, plans):
        """The same job through the CLI: prepare --analyse, check attempts 1 and 2 with the recorded replies, finalize."""
        run.mkdir()
        (run / "01_input.txt").write_text(text, encoding="utf-8", newline="")
        done = self.cli("prepare", "--run-dir", run, "--analyse", "--input-kind", "direct-text", "--strength", "medium",
                        "--genre", "blog")
        self.assertEqual(done.returncode, 0, done.stderr)
        manifest = json.loads((run / "chunk_manifest.json").read_text(encoding="utf-8"))
        outcomes = {}
        for entry in [c for c in manifest["chunks"] if not c["passthrough"]]:
            index = entry["index"]
            plan_file = run / f"plan-{index:02d}.json"
            self.assertEqual(json.loads(plan_file.read_text(encoding="utf-8")), plans[index])
            source = run / entry["input_file"]
            decided = run / f"decided-{index:02d}-1.txt"
            attempts = [a for (i, a) in replies if i == index]
            for attempt in attempts or [None]:
                args = ["check", "--plan", plan_file, "--source", source, "--attempt", attempt or 1,
                        "--out", decided if attempt in (None, 1) else run / f"decided-{index:02d}-2.txt",
                        "--report", run / f"check-{index:02d}-{attempt or 1}.json"]
                if attempt:
                    path = run / f"reply-{index:02d}-{attempt}.json"
                    path.write_text(json.dumps(replies[(index, attempt)], ensure_ascii=False), encoding="utf-8")
                    args += ["--response", path]
                else:
                    args += ["--candidate", source]                          # no model call: the plan is empty
                if attempt == 2:
                    args += ["--base", decided]
                result = self.cli(*args)
                report = json.loads((run / f"check-{index:02d}-{attempt or 1}.json").read_text(encoding="utf-8"))
                self.assertEqual(result.returncode, report["gate"]["exit_code"], result.stderr)
                outcomes[(index, attempt or 1)] = report
            final = run / (f"decided-{index:02d}-2.txt" if 2 in attempts else f"decided-{index:02d}-1.txt")
            last = outcomes[(index, 2 if 2 in attempts else 1)]
            kept = final                                                    # a rollback's decided text is base(x)
            (run / entry["rewritten_file"]).write_text(kept.read_text(encoding="utf-8"), encoding="utf-8", newline="")
        self.assertEqual(self.cli("finalize", "--run-dir", run, "--output", "final.md", "--report", "assembly.json").returncode, 0)
        return outcomes, (run / "final.md").read_text(encoding="utf-8")

    def gateway_run(self, record, damaged):
        """The job through the gateway with stub replies from the engine's plan; returns what the CLI run replays."""
        state = self.prepare(record["text"], strength="medium")
        replies, plans, reports, decided = {}, {}, {}, {}
        job = self.job_dir(state)
        while state["status"] == "rewrite":
            index, attempt = state["chunk"], state["attempt"]
            plans[index] = json.loads((job / f"plan-{index:02d}.json").read_text(encoding="utf-8"))
            plan, source = self.plan_of(state), self.source_of(state)
            if attempt == 1:
                response = stub_reply(plan, source, record["gold_text"])
                if damaged:
                    response, _hit = damage(response)
            else:
                retrying = {item["id"] for item in json.loads((job / f"check-{index:02d}-1.json").read_text(encoding="utf-8"))["retry"]}
                response = stub_reply(plan, source, record["gold_text"], only=retrying)
            replies[(index, attempt)] = response
            state = self.accept(state, response)
            reports[(index, attempt)] = json.loads((job / f"check-{index:02d}-{attempt}.json").read_text(encoding="utf-8"))
            self.assertEqual(state["sejong"]["exitCode"], reports[(index, attempt)]["gate"]["exit_code"])
        for path in sorted(job.glob("plan-*.json")):
            plans.setdefault(int(path.stem.split("-")[1]), json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(job.glob("check-*-1.json")):
            index = int(path.stem.split("-")[1])
            reports.setdefault((index, 1), json.loads(path.read_text(encoding="utf-8")))   # chunks decided without a call
        done, output = self.finalize(state)
        return replies, plans, reports, output

    def assert_equivalent(self, record, damaged=False):
        replies, plans, reports, output = self.gateway_run(record, damaged)
        shutil.rmtree(self.jobs, ignore_errors=True)
        outcomes, cli_output = self.cli_run(self.root / "cli-run", record["text"], replies, plans)
        self.assertEqual(sorted(outcomes), sorted(reports), "same chunks and attempts")
        for key in sorted(outcomes):
            self.assertEqual(outcomes[key], reports[key], f"check report of chunk {key[0]} attempt {key[1]}")
        self.assertEqual(cli_output, output, "delivered document")
        return replies, reports

    def test_in_process_and_cli_decisions_are_identical_on_the_six_seed_composites(self):
        rows = composites()
        self.assertEqual(len(rows), 6)
        for record in rows:
            with self.subTest(id=record["id"], writer="gold"):
                _replies, reports = self.assert_equivalent(record)
                # every chunk ends accepted: its last check is exit 0, or exit 1 with the attempt-2 policy accept-with-warning
                last = {}
                for (index, attempt), report in sorted(reports.items()):
                    last[index] = report
                self.assertTrue(all(report["policy"] in ("accept", "accept-with-warning") for report in last.values()), last)
            shutil.rmtree(self.root / "cli-run", ignore_errors=True)

    def test_in_process_and_cli_decisions_are_identical_when_a_damaged_reply_forces_a_retry(self):
        retried = 0
        for record in composites()[:3]:
            with self.subTest(id=record["id"], writer="damaged"):
                replies, reports = self.assert_equivalent(record, damaged=True)
                retried += sum(1 for (_index, attempt) in replies if attempt == 2)
            shutil.rmtree(self.root / "cli-run", ignore_errors=True)
        self.assertGreater(retried, 0, "the retry path (attempt 2 with --base) was exercised")


if __name__ == "__main__":
    unittest.main()
