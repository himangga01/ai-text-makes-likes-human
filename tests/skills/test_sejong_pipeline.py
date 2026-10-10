"""Super Sejong Engine v2 core glue and CLI (WP-10): plan, apply, repair, verify, decide, check, the CLI and
the workflow.py dispatch, end to end on the seed benchmark with Python stub writers (no model call anywhere).

Text in this file is constructed; the seed benchmark (docs/research/super-sejong/v2/benchmark) is original
project text. Outcomes on the seed set are scored with the independent scorer (scripts/sejong-bench), never
with the engine's own gate. Set SEJONG_WRITE_FIXTURES=1 to regenerate tests/fixtures/sejong/cli-contract.json
(the CLI outputs the TypeScript contract test feeds to the current parsers).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BENCH_DIR = ROOT / "scripts" / "sejong-bench"
sys.path.insert(0, str(BENCH_DIR))
from engine_runtime import sejong_cli, workflow  # noqa: E402
from engine_runtime.sejong import apply as AP  # noqa: E402
from engine_runtime.sejong import check as CK  # noqa: E402
from engine_runtime.sejong import chunk, config, decide as DC, io, meaning, plan as PL, verify as VF  # noqa: E402
from engine_runtime.sejong.types import ChunkInfo, Options, Violation  # noqa: E402
import damage  # noqa: E402
import score  # noqa: E402
import voicefeat  # noqa: E402

voicefeat.set_backend("off")            # pin the scorer's regex backend: results must not depend on Kiwi
PYTHON = sys.executable
CLI = ROOT / "engine_runtime" / "sejong_cli.py"
FIXTURE = ROOT / "tests" / "fixtures" / "sejong" / "cli-contract.json"
FLAGS = config.Flags.from_env({})
BLOG = ("오늘은 세미나 후기를 정리합니다. 왜냐하면 일정이 바뀌었습니다. 참가비는 3만 원이 됬습니다.\n\n"
        "현장 분위기가 좋았어요😀 ㅎㅎ 궁금한 점이 있으시면 댓글로 문의해 주세요.\n")
NO_EDIT = "회의는 오전 10시에 시작합니다. 자료는 미리 읽어 오세요.\n"
# Seed genres the engine does not have map to the nearest engine genre.
GENRE = {"blog": "blog", "report": "report", "essay": "essay", "notice": "notice", "casual": "blog",
         "marketing": "general"}
SEED, _ = score.load_seed()
COMPOSITES = [r for r in score.load_seed(composites=True)[0] if r["item_type"] == "composite_document"]


def options(strength="medium", genre="general", kind="direct-text", **extra):
    return Options(input_kind=kind, strength=strength, genre=genre, **extra)


def reply(*items, rewritten=""):
    return {"replacements": [{"id": i, "text": t, "reason": r} for i, t, r in items], "rewrittenText": rewritten,
            "warnings": []}


def plan_for(text, strength="medium", genre="general", flags=FLAGS, **extra):
    return PL.build_plan(text, options=options(strength, genre, **extra), flags=flags)


def target_reply(plan, text, target, only=None, reason="22 어휘상 잘못된 표현"):
    """A stub writer: every sentence that differs in `target` becomes a replacement under its request id,
    or its own id when open review is on (aligned with the engine's aligner, as a writer would see it)."""
    doc = PL.source_document(plan, text)
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
        items.append((rid, piece.strip(), reason))
    return reply(*items)


def run_writer(plan, text, target, *, mode="replace", flags=FLAGS):
    """Attempt 1 and, when the gate asks for it, attempt 2 with the same writer on the retry list only."""
    if mode == "replace":
        first = CK.check(plan, text, response=target_reply(plan, text, target), flags=flags)
    else:
        first = CK.check(plan, text, candidate=target, flags=flags)
    outcome, calls = first, 1
    if first.report.policy == "retry":
        calls += 1
        if mode == "replace":
            only = {item.id for item in first.report.retry}
            outcome = CK.check(plan, text, response=target_reply(plan, text, target, only), attempt=2, base=first.text,
                               flags=flags)
        else:
            outcome = CK.check(plan, text, candidate=target, attempt=2, base=first.text, flags=flags)
    return first, outcome, calls


def base_text(plan, text):
    doc = PL.source_document(plan, text)
    return AP.assemble(doc, PL.base_texts(plan, text, doc))[0]


# ==========================================================================
# plan: strength -> tiers, needsModel, deterministic fixes
# ==========================================================================
class PlanTests(unittest.TestCase):
    TEXT = ("서류가 제출되어집니다. 대리인은 위임장을 필요로 합니다. 그는 결코 약속을 어기는 사람이다. "
            "오늘은 날씨가 맑습니다.\n")

    def tiers(self, plan):
        return sorted({r.tier for r in plan.requests})

    def test_strength_to_tier_mapping(self):
        normal = plan_for(self.TEXT, "normal", "report")
        medium = plan_for(self.TEXT, "medium", "report")
        strong = plan_for(self.TEXT, "strong", "report")
        very = plan_for(self.TEXT, "very-strong", "report")
        self.assertEqual(self.tiers(normal), ["FIX"])
        self.assertEqual(self.tiers(medium), ["FIX", "SUGGEST"])           # TR-PILYO_RO is SUGGEST in report
        self.assertEqual((normal.open_review.enabled, medium.open_review.enabled, strong.open_review.enabled),
                         (False, True, True))                                # 9.2a item 2: medium has open review
        self.assertEqual(medium.open_review.max_sentences, 3)               # max(3, ceil(0.1 * 4))
        self.assertEqual([p.options.allow_full_text for p in (normal, medium, strong, very)], [False, False, False, True])
        # A text file is planned like direct text at its strength (owner request 2026-10-10); at normal it keeps the
        # file route: FIX only and no open review, even when SUPER_SEJONG_OPEN_REVIEW=always reviews direct text.
        text_file = plan_for(self.TEXT, "very-strong", "report", kind="text-file")
        self.assertEqual((self.tiers(text_file), text_file.open_review.enabled, text_file.options.allow_full_text),
                         (self.tiers(very), very.open_review.enabled, True))
        always = config.Flags.from_env({"SUPER_SEJONG_OPEN_REVIEW": "always"})
        plain_file = plan_for(self.TEXT, "normal", "report", kind="text-file", flags=always)
        self.assertEqual((self.tiers(plain_file), plain_file.open_review.enabled), (["FIX"], False))
        self.assertTrue(plan_for(self.TEXT, "normal", "report", flags=always).open_review.enabled)
        off = plan_for(self.TEXT, "medium", "report", flags=config.Flags.from_env({"SUPER_SEJONG_MODE": "off"}))
        self.assertEqual((self.tiers(off), off.open_review.enabled), (["FIX"], False))
        late = plan_for(self.TEXT, "medium", "report", flags=config.Flags.from_env({"SUPER_SEJONG_OPEN_REVIEW": "strong"}))
        self.assertFalse(late.open_review.enabled)

    def test_requests_one_per_sentence_and_findings_renumbered(self):
        plan = plan_for(self.TEXT, "medium", "report")
        self.assertEqual(len({r.sentence for r in plan.requests}), len(plan.requests))
        self.assertEqual([r.id for r in plan.requests], [f"R{i + 1}" for i in range(len(plan.requests))])
        self.assertEqual([f.id for f in plan.findings], [f"F{i + 1}" for i in range(len(plan.findings))])
        self.assertEqual(io.plan_problems(plan.to_json()), [])
        a06 = next(r for r in plan.requests if "SSJ-A06" in r.rules)
        self.assertEqual((a06.tier, a06.sentence), ("FIX", "S3"))

    def test_empty_plan_needs_no_model(self):
        plan = plan_for(NO_EDIT, "normal")
        self.assertEqual((plan.requests, plan.needs_model, plan.open_review.enabled), ([], False, False))
        outcome = CK.check(plan, NO_EDIT, flags=FLAGS)
        self.assertEqual((outcome.text, outcome.report.gate["exit_code"], outcome.report.retry), (NO_EDIT, 0, []))
        # a chunk with nothing the open review could nominate never costs a call either
        headings = plan_for("# 제목\n\n## 2024\n", "medium")
        self.assertEqual((headings.open_review.enabled, headings.needs_model), (False, False))

    def test_deterministic_fixes_apply_without_a_model_call(self):
        text = "참가비는 3만 원이 됬습니다. 현장에서 결제할수 있습니다. 궁금하면 문의해주세요.\n"
        plan = plan_for(text, "normal", "blog")
        self.assertEqual([(d.before, d.after) for d in plan.deterministic], [("됬", "됐"), ("수", " 수"), ("주", " 주")])
        self.assertFalse(plan.needs_model)
        outcome = CK.check(plan, text, flags=FLAGS)
        self.assertEqual(outcome.text, "참가비는 3만 원이 됐습니다. 현장에서 결제할 수 있습니다. 궁금하면 문의해 주세요.\n")
        self.assertEqual([s.status for s in outcome.report.sentences], ["deterministic"] * 3)
        self.assertEqual(outcome.report.counts["normFixes"], 3)
        for scope in ("off", "edited-only"):
            scoped = plan_for(text, "normal", "blog", deterministic_fix=scope)
            self.assertEqual(CK.check(scoped, text, flags=FLAGS).text, text)
        edited = plan_for(BLOG, "medium", "blog", deterministic_fix="edited-only")
        fixed = CK.check(edited, BLOG, response=reply(("S3", "참가비가 3만 원이 됬습니다.", "03")), flags=FLAGS)
        self.assertIn("참가비가 3만 원이 됐습니다.", fixed.text)        # fixed inside the edited sentence
        self.assertEqual(fixed.report.sentences[2].repairs, ["norm_fix"])

    def test_plans_validate_on_every_seed_record(self):
        for record in SEED + COMPOSITES:
            for strength in ("normal", "medium"):
                plan = plan_for(record["text"], strength, GENRE.get(record["genre"], "general"))
                with self.subTest(id=record["id"], strength=strength):
                    self.assertEqual(io.plan_problems(plan.to_json()), [])
                    self.assertEqual(plan.stats["deterministicDropped"], 0)

    def test_source_must_match_the_plan(self):
        plan = plan_for(BLOG)
        with self.assertRaises(PL.PlanMismatch):
            CK.check(plan, BLOG + " ", flags=FLAGS)


# ==========================================================================
# invariants: verify(x, x) and verify(x, base(x)) are clean
# ==========================================================================
class InvariantTests(unittest.TestCase):
    def test_verify_document_identity_is_clean(self):
        for record in SEED + COMPOSITES:
            gate = VF.verify_document(record["text"], record["text"], flags=FLAGS)
            with self.subTest(id=record["id"]):
                self.assertEqual((gate["gate"]["exit_code"], gate["hardFailures"], gate["shadowFailures"]), (0, [], []))
                self.assertEqual(gate["warningReasons"], {"version": 1, "codes": []})

    def test_base_verifies_against_the_source(self):
        with_fixes = 0
        for record in SEED + COMPOSITES:
            plan = plan_for(record["text"])
            base = base_text(plan, record["text"])
            with_fixes += base != record["text"]
            gate = VF.verify_document(record["text"], base, flags=FLAGS)
            with self.subTest(id=record["id"]):
                self.assertEqual((gate["gate"]["exit_code"], gate["shadowFailures"]), (0, []))
                # and the check step without a model call delivers exactly base(x)
                outcome = CK.check(plan, record["text"], flags=FLAGS)
                self.assertEqual((outcome.text, outcome.report.gate["exit_code"]), (base, 0))
        self.assertEqual(with_fixes, 19)                      # 35 deterministic fixes in 19 of the 212 records

    def test_meaning_family_is_neutral_to_deterministic_fixes(self):
        # Regression (WP-10 fix in meaning.codes): N01 spacing and N04 spelling fixes flagged polarity/modality.
        for before, after in (("점검일이 지난 소화기는 사용할수 없으므로 즉시 교체해야 합니다.",
                               "점검일이 지난 소화기는 사용할 수 없으므로 즉시 교체해야 합니다."),
                              ("기한을 넘기면 접수할수 없습니다.", "기한을 넘기면 접수할 수 없습니다."),
                              ("방문하실수 있습니다.", "방문하실 수 있습니다."),
                              ("안 되요?", "안 돼요?"),
                              ("지키지 않으면 수거가 안되요.", "지키지 않으면 수거가 안돼요.")):
            with self.subTest(before=before):
                self.assertEqual(meaning.codes(before, after), [])
        # ... and still sees real changes
        self.assertEqual(meaning.codes("사용할 수 있습니다.", "사용할수 없습니다."), [("modality_changed", "modality")])
        self.assertEqual(meaning.codes("방문할 수 없습니다.", "방문할 수 있습니다."), [("modality_changed", "modality")])

    def test_meaning_family_is_neutral_to_the_double_passive_fix(self):
        # Regression (WP-10 fix in meaning.codes): the SSJ-A04 repair read as participant_role_changed.
        self.assertEqual(meaning.codes("점검 결과는 담당자에게 보고되어집니다.", "점검 결과는 담당자에게 보고됩니다."), [])
        for double, single in (("되어집니다", "됩니다"), ("되어진", "된"), ("되어졌다", "되었다"), ("보여지는", "보이는"),
                               ("쓰여진", "쓰인"), ("나뉘어졌다", "나뉘었다"), ("읽혀질", "읽힐"), ("불려져", "불려")):
            self.assertEqual(meaning._single_passive(double), single)
        self.assertEqual(meaning._single_passive("돼지가 보인다"), "돼지가 보인다")


# ==========================================================================
# apply: whole-reply and per-replacement rejection, full-text fallback
# ==========================================================================
class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan_for(BLOG, "medium", "blog")
        self.doc = PL.source_document(self.plan, BLOG)
        self.start = [u.text for u in self.doc.units]

    def apply(self, response, plan=None):
        return AP.apply_response(plan or self.plan, self.doc, response, self.start)

    def test_whole_reply_rejections(self):
        self.assertEqual(self.apply({"replacements": []}).unusable, "schema")
        self.assertEqual(self.apply(reply(("R9", "x 문장입니다.", ""))).unusable, "unknown_id")
        self.assertEqual(self.apply(reply(("R1", "a 문장입니다.", ""), ("R1", "b 문장입니다.", ""))).unusable, "duplicate_id")
        self.assertEqual(self.apply(reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다.", ""),
                                          ("S2", "왜냐하면 일정이 바뀌었기 때문입니다.", ""))).unusable, "duplicate_sentence")
        self.assertEqual(self.apply(reply(rewritten=BLOG)).unusable, "rewritten_text_not_allowed")
        closed = plan_for(BLOG, "normal", "blog")
        self.assertEqual(self.apply(reply(("S1", "오늘은 세미나 후기를 정리해 둡니다.", "")), closed).unusable, "unknown_id")

    def test_per_replacement_rejections(self):
        result = self.apply(reply(("R1", "왜냐하면\n일정이 바뀌었기 때문입니다.", ""),
                                  ("S1", "오늘.", ""),
                                  ("S3", "참가비는 4만 원이 됐습니다.", ""),
                                  ("S5", "궁금한 점은 댓글로 남겨 주세요. 바로 답해 드립니다.", "")))
        self.assertEqual({k: v[0] for k, v in result.rejected.items()},
                         {1: "replacement_newline", 0: "replacement_length_ratio", 2: "protected_span_changed",
                          4: "replacement_split"})
        self.assertTrue(all(v[2] for v in result.rejected.values()))
        self.assertEqual(result.texts, self.start)

    def test_open_review_limit_and_frozen_units(self):
        text = "".join(f"{n}번째 문장은 짧습니다. " for n in range(1, 6)).strip() + "\n"
        plan = plan_for(text, "medium")
        doc = PL.source_document(plan, text)
        items = [(u.id, u.text.replace("짧습니다", "짧아 보입니다"), "22") for u in doc.units]
        result = AP.apply_response(plan, doc, reply(*items), [u.text for u in doc.units])
        self.assertEqual(plan.open_review.max_sentences, 3)
        self.assertEqual(sorted(result.nominated), [0, 1, 2])
        self.assertEqual({k: v[0] for k, v in result.rejected.items()}, {3: "open_review_limit", 4: "open_review_limit"})
        headed = "# 제목\n\n본문은 여기에 있습니다.\n"
        hplan = plan_for(headed, "medium")
        hdoc = PL.source_document(hplan, headed)
        hres = AP.apply_response(hplan, hdoc, reply(("S1", "# 새 제목", "22")), [u.text for u in hdoc.units])
        self.assertEqual(hres.rejected[0][:1], ("replacement_frozen_unit",))

    def test_full_text_fallback_reverts_collateral_edits(self):
        candidate = (BLOG.replace("오늘은", "오늘도")
                     .replace("왜냐하면 일정이 바뀌었습니다.", "왜냐하면 일정이 바뀌었기 때문입니다.")
                     .replace("현장 분위기가", "현장의 분위기가"))
        outcome = CK.check(self.plan, BLOG, candidate=candidate, flags=FLAGS)
        statuses = {s.id: (s.status, s.codes) for s in outcome.report.sentences}
        self.assertEqual(statuses["S1"], ("reverted", ["collateral_edit"]))
        self.assertEqual(statuses["S4"], ("reverted", ["collateral_edit"]))
        self.assertEqual(statuses["S2"][0], "accepted")
        self.assertEqual(outcome.text, BLOG.replace("됬", "됐").replace("왜냐하면 일정이 바뀌었습니다.",
                                                                         "왜냐하면 일정이 바뀌었기 때문입니다."))
        self.assertEqual(outcome.report.counts["collateralReverts"], 2)
        allowed = plan_for(BLOG, "very-strong", "blog")
        via_reply = CK.check(allowed, BLOG, response=reply(rewritten=candidate), flags=FLAGS)
        self.assertEqual(via_reply.text, outcome.text)

    def test_boundary_breaking_replacement_is_reverted(self):
        # dropping the final period glues S2 to S3 when the candidate is segmented again
        outcome = CK.check(self.plan, BLOG, response=reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다", "")), flags=FLAGS)
        s2 = outcome.report.sentences[1]
        self.assertEqual((s2.status, s2.codes), ("retry", ["replacement_boundary"]))
        self.assertEqual(outcome.text, BLOG.replace("됬", "됐"))


# ==========================================================================
# decide: the decision table, gate mapping, OD 8 regressions
# ==========================================================================
class DecideTests(unittest.TestCase):
    V = [Violation(code="voice_level", family="voice", severity="hard", sentence="S1", detail="HAPSYO->HAEYO")]

    def test_decision_table(self):
        d = DC.decide_sentence
        self.assertEqual(d(changed=False, deterministic=False, licensed=True, rejection=None, enforced=[], attempt=1).status,
                         "unchanged")
        self.assertEqual(d(changed=False, deterministic=True, licensed=False, rejection=None, enforced=[], attempt=1).status,
                         "deterministic")
        for attempt in (1, 2):
            collateral = d(changed=True, deterministic=False, licensed=False, rejection=None, enforced=[], attempt=attempt)
            self.assertEqual((collateral.status, collateral.codes), ("reverted", ["collateral_edit"]))
            self.assertEqual(d(changed=True, deterministic=False, licensed=True, rejection=None, enforced=[],
                               attempt=attempt).status, "accepted")
        self.assertEqual(d(changed=True, deterministic=False, licensed=True, rejection=None, enforced=self.V,
                           attempt=1).status, "retry")
        self.assertEqual(d(changed=True, deterministic=False, licensed=True, rejection=None, enforced=self.V,
                           attempt=2).status, "reverted")
        rejected = ("replacement_newline", "newline", True)
        self.assertEqual(d(changed=False, deterministic=False, licensed=True, rejection=rejected, enforced=[],
                           attempt=1).status, "retry")
        self.assertEqual(d(changed=False, deterministic=False, licensed=True, rejection=rejected, enforced=[],
                           attempt=2).status, "rejected")
        self.assertEqual(d(changed=False, deterministic=False, licensed=True, rejection=("open_review_limit", "", False),
                           enforced=[], attempt=1).status, "rejected")

    def test_gate_mapping_matches_the_legacy_table(self):
        g = DC.chunk_gate
        common = dict(runaway=False, unusable=False, floor_failed=[], kept_edits=True, has_requests=True)
        self.assertEqual((g(1, retry=False, shadow=["clarity_longer_sentence"], **common).exit_code), 0)
        self.assertEqual(g(1, retry=True, shadow=[], **common).policy, "retry")
        self.assertEqual(g(2, retry=False, shadow=["clarity_longer_sentence"], **common).policy, "accept-with-warning")
        self.assertEqual(g(2, retry=False, shadow=[], **common).policy, "accept")
        runaway = dict(common, runaway=True)
        self.assertEqual([g(a, retry=False, shadow=[], **runaway).policy for a in (1, 2)], ["retry", "rollback"])
        unusable = dict(common, unusable=True, kept_edits=False)
        self.assertEqual([g(a, retry=False, shadow=[], **unusable).policy for a in (1, 2)], ["retry", "rollback"])
        kept = dict(common, unusable=True)
        self.assertEqual(g(2, retry=False, shadow=[], **kept).exit_code, 1)

    def test_unchanged_text_is_never_retried(self):
        # OD 8 / P1 regression: an identity reply (or no reply) never costs a retry
        plan = plan_for(BLOG, "medium", "blog")
        doc = PL.source_document(plan, BLOG)
        identity = reply(*[(r.id, doc.units[int(r.sentence[1:]) - 1].text, "") for r in plan.requests])
        for response in (identity, reply()):
            outcome = CK.check(plan, BLOG, response=response, flags=FLAGS)
            self.assertEqual((outcome.report.gate["exit_code"], outcome.report.retry), (0, []))
            self.assertTrue(all(s.status in ("unchanged", "deterministic") for s in outcome.report.sentences))
        self.assertEqual(CK.check(plan, BLOG, response=identity, flags=FLAGS).report.request_status["UNTOUCHED"], 1)
        self.assertEqual(CK.check(plan, BLOG, response=reply(), flags=FLAGS).report.request_status["DECLINED"], 1)

    def test_no_p1_and_runaway_only_at_half(self):
        text = ("가을 축제는 다음 주 토요일에 열립니다. 행사장은 시청 앞 광장입니다. 주차 공간은 넉넉하지 않습니다. "
                "대중교통을 이용하시면 편합니다.\n")
        self.assertEqual(VF.change_rate(text, text), 0.0)
        mild = text.replace("넉넉하지 않습니다", "충분하지 않습니다")
        gate = VF.verify_document(text, mild, flags=FLAGS)
        self.assertLess(gate["changeRate"], 0.5)
        self.assertEqual(gate["warningReasons"]["codes"], [])
        heavy = "전혀 다른 글입니다. 내용도 바뀌었습니다.\n"
        rewritten = VF.verify_document(text, heavy, flags=FLAGS)
        self.assertIn("change_rate_runaway", rewritten["hardFailures"])
        self.assertEqual(rewritten["warningReasons"]["codes"], ["P0_CHANGE_RATE"])
        for record in SEED:
            self.assertNotIn("P1_STYLE_TARGET", VF.verify_document(record["text"], record["gold_text"],
                                                                   flags=FLAGS)["warningReasons"]["codes"])

    def test_retry_then_revert_with_named_violations(self):
        plan = plan_for(BLOG, "medium", "blog")
        bad = reply(("R1", "왜냐하면 일정이 바뀌었기 때문이에요.", "SSJ-A01"), ("S1", "오늘은 세미나 후기를 정리할까요?", "14"))
        first = CK.check(plan, BLOG, response=bad, flags=FLAGS)
        self.assertEqual((first.report.gate["exit_code"], first.report.policy), (1, "retry"))
        retry = {item.id: [v.code for v in item.violations] for item in first.report.retry}
        self.assertEqual(retry, {"S1": ["voice_level", "voice_mood"], "R1": ["voice_level"]})
        self.assertEqual(first.report.retry[1].violations[0].keep, "바뀌었습니다.")
        self.assertEqual(first.text, BLOG.replace("됬", "됐"))                 # retry sentences carry base(s)
        self.assertEqual(io.check_problems(first.report.to_json()), [])
        second = CK.check(plan, BLOG, response=reply(("R1", "왜냐하면 일정이 바뀌었기 때문이에요.", "")), attempt=2,
                          base=first.text, flags=FLAGS)
        s2 = second.report.sentences[1]
        self.assertEqual((second.report.gate["exit_code"], s2.status, s2.codes), (0, "reverted", ["voice_level"]))
        self.assertEqual(second.report.counts["revertedByFamily"], {"voice": 1})
        good = CK.check(plan, BLOG, response=reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다.", "")), attempt=2,
                        base=first.text, flags=FLAGS)
        self.assertEqual((good.report.sentences[1].status, good.report.request_status["FIXED"]), ("accepted", 1))

    def test_attempt_two_keeps_attempt_one_edits(self):
        plan = plan_for(BLOG, "medium", "blog")
        first = CK.check(plan, BLOG, response=reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다.", ""),
                                                    ("S5", "궁금한 점이 있으시면 댓글로 문의해 주세요요?", "14")), flags=FLAGS)
        self.assertEqual(first.report.policy, "retry")
        second = CK.check(plan, BLOG, response=reply(), attempt=2, base=first.text, flags=FLAGS)
        self.assertIn("바뀌었기 때문입니다.", second.text)
        self.assertEqual(second.report.sentences[1].status, "accepted")
        # an unusable retry reply keeps the attempt-1 edits (exit 1); with nothing kept it rolls back
        unusable = CK.check(plan, BLOG, response="not json", attempt=2, base=first.text, flags=FLAGS)
        self.assertEqual((unusable.report.gate["exit_code"], unusable.report.shadow_failures[0]), (1, "model_output_unusable"))
        nothing = CK.check(plan, BLOG, response="not json", attempt=2, base=BLOG.replace("됬", "됐"), flags=FLAGS)
        self.assertEqual((nothing.report.policy, nothing.report.hard_failures), ("rollback", ["model_output_unusable"]))
        # a rollback delivers base(x): the certain misspelling fix (됬 -> 됐) survives it
        self.assertEqual(nothing.text, base_text(plan, BLOG))
        self.assertIn("됐", nothing.text)
        self.assertGreater(nothing.report.counts["normFixes"], 0)

    def test_polarity_rule_licenses_its_own_repair_only(self):
        text = "그는 결코 약속을 어기는 사람이다. 그는 늘 일찍 온다.\n"
        plan = plan_for(text, "medium")
        fixed = CK.check(plan, text, response=reply(("R1", "그는 결코 약속을 어기는 사람이 아니다.", "")), flags=FLAGS)
        self.assertEqual(fixed.report.sentences[0].status, "accepted")
        # the same polarity flip on a sentence without an SSJ-A06 request is a meaning violation
        flipped = CK.check(plan, text, response=reply(("S2", "그는 늘 일찍 오지 않는다.", "08")), flags=FLAGS)
        self.assertEqual((flipped.report.sentences[1].status, flipped.report.sentences[1].codes),
                         ("retry", ["polarity_changed"]))


# ==========================================================================
# end to end on the seed benchmark (stub writers; scored by scripts/sejong-bench)
# ==========================================================================
def seed_run(writer, mode="replace", strength="medium"):
    rows, calls, retries = [], 0, 0
    for record in [r for r in SEED if r["item_type"] != "composite_document"]:
        plan = plan_for(record["text"], strength, GENRE[record["genre"]])
        target = writer(record)
        if target is None:
            continue
        if plan.needs_model:
            first, outcome, n = run_writer(plan, record["text"], target, mode=mode)
            calls += n
            retries += n - 1
            for report in (first.report, outcome.report):
                assert io.check_problems(report.to_json()) == [], record["id"]
        else:
            outcome = CK.check(plan, record["text"], flags=FLAGS)
        rows.append((record, outcome.text))
    return rows, calls, retries


class SeedEndToEndTests(unittest.TestCase):
    maxDiff = None

    def test_identity_writer_changes_nothing_but_deterministic_fixes(self):
        rows, calls, retries = seed_run(lambda r: r["text"])
        self.assertEqual(retries, 0)                                     # OD 8: unchanged text is never retried
        for record, output in rows:
            plan = plan_for(record["text"], "medium", GENRE[record["genre"]])
            self.assertEqual(output, base_text(plan, record["text"]), record["id"])
        agg = score.aggregate([score.score_item(r, o) for r, o in rows])
        self.assertEqual((agg["clean_sentences_touched"], agg["voice_violations"], agg["cta_present"]), (0, 0, 46))

    def test_gold_writer_fixes_primary_injections_without_violations(self):
        rows, calls, retries = seed_run(lambda r: r["gold_text"])
        agg = score.aggregate([score.score_item(r, o) for r, o in rows])
        unfixed = sorted({r["id"] for r, o in rows for s in score.score_item(r, o)["spans"]
                          if s["primary"] and s["status"] not in score.PRIMARY_FIXED})
        # Measured residual: WP-10 left five AGREE gold fixes blocked (87/92) because they flip the literal
        # polarity of a negative-polarity adverb outside SSJ-A06's closed list. WP-10b added 별로, 도저히 and 일절
        # (each gold fix adds the negation, so the request's polarity licence applies); 거의 stays out of the
        # list ("거의 다", "거의 모든" are positive uses), so SSB-186 is the one primary injection left.
        self.assertEqual(agg["primary"], 92)
        self.assertEqual(unfixed, ["SSB-186"])
        self.assertEqual(agg["primary_fixed"], 91)
        self.assertEqual({k: agg[k] for k in ("clean_sentences_touched", "voice_violations", "quotes_changed",
                                               "protected_tokens_changed", "cta_weakened", "cta_strengthened",
                                               "cta_invented_sentences", "invariants_violated", "numbers_dropped",
                                               "numbers_added")}, dict.fromkeys(
            ("clean_sentences_touched", "voice_violations", "quotes_changed", "protected_tokens_changed",
             "cta_weakened", "cta_strengthened", "cta_invented_sentences", "invariants_violated",
             "numbers_dropped", "numbers_added"), 0))
        self.assertEqual((agg["cta_explicit"], agg["cta_present"]), (46, 46))
        self.assertLessEqual(calls, 2 * 206)

    def test_damaged_writers_are_reverted_or_retried(self):
        delivered = {}
        for label, writer, detected in damage.DAMAGE:
            for mode in ("replace", "candidate"):
                rows, _calls, _retries = seed_run(writer, mode)
                hits = sorted(r["key"] for r, o in rows if detected(score.score_item(r, o)))
                delivered[(damage.SLUGS[label], mode)] = (len(rows), hits)
        # WP-10 missed T08 (role swap across two clauses) and T20 (전에 -> 뒤에); WP-10b catches both
        # (participant_role_changed per clause, temporal_order_changed).
        expected_misses = {}
        for key, (n, hits) in delivered.items():
            with self.subTest(damage=key, sites=n):
                self.assertEqual(hits, expected_misses.get(key, []))

    def test_extra_damage_classes(self):
        def transition(r):
            first = r["gold_text"].split(" ", 1)
            return "따라서 " + r["gold_text"] if len(first) == 2 and "따라서" not in r["text"] else None

        def number(r):
            m = re.search(r"\d+", r["gold_text"])
            return None if not m else r["gold_text"][:m.start()] + str(int(m.group()) + 1) + r["gold_text"][m.end():]

        def invented_cta(r):
            return None if r["cta"] else r["gold_text"].rstrip() + " 지금 바로 신청하세요.\n"

        for name, writer, bad in (("transition", transition, lambda r, o: "따라서 " in o),
                                  ("number", number, lambda r, o: score.score_item(r, o)["numbers_added"] > 0),
                                  ("invented_cta", invented_cta, lambda r, o: "지금 바로 신청하세요" in o)):
            for mode in ("replace", "candidate"):
                rows, _c, _r = seed_run(writer, mode)
                hits = sorted(r["key"] for r, o in rows if bad(r, o))
                expected = ["J14"] if (name, mode) == ("transition", "replace") else []
                with self.subTest(damage=name, mode=mode, sites=len(rows)):
                    # J14: 비록 … 때문에 -> 비록 … 지만 (SSJ-A07) plus 따라서 swaps one causal marker for another,
                    # which the flow family treats as neutral by design.
                    self.assertEqual(hits, expected)

    def test_composites_through_prepare_check_finalize(self):
        for record in COMPOSITES:
            with tempfile.TemporaryDirectory() as tmp, self.subTest(id=record["id"]):
                run = Path(tmp)
                (run / chunk.SOURCE_FILE).write_text(record["text"], encoding="utf-8")
                self.assertEqual(sejong_cli.main(["prepare", "--run-dir", tmp, "--analyse", "--input-kind",
                                                  "direct-text", "--strength", "medium", "--genre", "general"]), 0)
                manifest = io.read_json(run / chunk.MANIFEST_FILE)
                document = io.read_text(run / chunk.SOURCE_FILE)
                for entry in manifest["sejong"]["plans"]:
                    plan = io.read_plan(run / entry["file"])
                    chunk_entry = manifest["chunks"][entry["chunk"] - 1]
                    source = io.read_text(run / chunk_entry["input_file"])
                    outcome = CK.check(plan, source, response=target_reply(plan, source, record["gold_text"]),
                                       document=document if manifest["chunk_count"] > 1 else None, flags=FLAGS)
                    io.write_text(run / chunk_entry["rewritten_file"], outcome.text)
                report = sejong_cli.finalize(run, "03_reassembled.md", "03_reassembly_report.json", flags=FLAGS)
                output = io.read_text(run / "03_reassembled.md")
                self.assertFalse(report["sejong"]["documentRolledBack"])
                scored = score.score_item(record, output)
                self.assertEqual((scored["clean_sentences_touched"], scored["voice_violations"]), (0, 0))
                self.assertEqual((report["sejong"]["floorCodes"], report["sejong"]["seamCodes"]), ([], []))
                # Without the plan, the document gate cannot know that an SSJ-A06 request licensed its own
                # polarity repair (결코 … 이월됩니다 -> 이월되지 않습니다; since WP-10b also 별로 비싸요 -> 비싸지
                # 않아요 and 도저히 … 수 있었다 -> 수 없었다, which read as lexical and modality changes too);
                # nothing else may remain: these are exactly check.LICENSED_BY_POLARITY_RULES.
                gate = VF.verify_document(record["text"], output, flags=FLAGS)
                self.assertLessEqual(set(gate["hardFailures"]), set(CK.LICENSED_BY_POLARITY_RULES))


# ==========================================================================
# CLI and the gate JSON contract
# ==========================================================================
def cli(*args, cwd=None, env=None):
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", **(env or {})}
    for key in [k for k in environment if k.startswith("SUPER_SEJONG_")]:
        if not env or key not in env:
            environment.pop(key)
    return subprocess.run([PYTHON, str(CLI), *args], capture_output=True, text=True, encoding="utf-8", cwd=cwd,
                          env=environment)


def legacy_gate_problems(stdout: str, exit_code: int, attempt: int) -> list:
    """The checks python-engine.ts verify() and python-adapter.ts verifyDocument() apply to the gate JSON."""
    starts = [m.start() for m in re.finditer(r"^\{", stdout, re.M)]
    if not starts:
        return ["no line-starting JSON object"]
    report = json.loads(stdout[starts[-1]:])
    problems = []
    if report.get("gate", {}).get("exit_code") != exit_code:
        problems.append("exit code mismatch")
    reasons = report.get("warningReasons")
    if not (isinstance(reasons, dict) and sorted(reasons) == ["codes", "version"] and reasons["version"] == 1
            and set(reasons["codes"]) <= {"P0_CHANGE_RATE"}):
        problems.append("warningReasons")
    if report.get("policy") != {0: "accept", 3: "error"}.get(exit_code, "retry" if attempt == 1 else
                                                             ("rollback" if exit_code == 2 else "accept-with-warning")):
        problems.append("policy")
    for key in ("hardFailures", "shadowFailures"):
        values = report.get(key, [])
        if not (isinstance(values, list) and len(values) <= 100 and all(re.fullmatch(r"[a-z_]{1,60}", v) for v in values)):
            problems.append(key)
    if report.get("hardFailures") and exit_code not in (2, 3):
        problems.append("hardFailures with exit 0/1")
    return problems


def contract_fixture() -> dict:
    """Run the CLI on the constructed blog chunk and collect what the TypeScript parsers must accept."""
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp)
        (run / "01_input.txt").write_text(BLOG, encoding="utf-8")
        assert cli("prepare", "--run-dir", tmp, "--analyse", "--input-kind", "direct-text", "--strength", "medium",
                   "--genre", "blog").returncode == 0
        manifest = io.read_json(run / "chunk_manifest.json")
        manifest.pop("created")
        plan = io.read_json(run / "plan-01.json")
        source = run / "01_chunk_01_input.txt"
        checks, gates = {}, {}

        def check(name, response, attempt=1, base=None):
            (run / f"{name}.json").write_text(json.dumps(response, ensure_ascii=False) if not isinstance(response, str)
                                              else response, encoding="utf-8")
            args = ["check", "--plan", str(run / "plan-01.json"), "--source", str(source), "--response",
                    str(run / f"{name}.json"), "--attempt", str(attempt), "--out", str(run / f"{name}.txt"),
                    "--report", str(run / f"{name}-check.json")]
            if base:
                args += ["--base", str(run / f"{base}.txt")]
            result = cli(*args, cwd=tmp)
            report = io.read_json(run / f"{name}-check.json")
            assert result.returncode == report["gate"]["exit_code"], (name, result.returncode, result.stderr)
            checks[name] = report

        check("accept", reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다.", "SSJ-A01")))
        check("retry", reply(("R1", "왜냐하면 일정이 바뀌었기 때문이에요.", "SSJ-A01"),
                             ("S1", "오늘은 세미나 후기를 정리할까요?", "14 부적절한 종결어미 사용")))
        check("attempt2", reply(("R1", "왜냐하면 일정이 바뀌었기 때문입니다.", "SSJ-A01")), 2, "retry")
        check("rollback", "not json", 2, "retry")
        (run / "same.txt").write_text(BLOG, encoding="utf-8")
        (run / "number.txt").write_text(BLOG.replace("3만", "4만"), encoding="utf-8")
        (run / "emoticon.txt").write_text(BLOG.replace("좋았어요😀 ㅎㅎ", "좋았어요😀"), encoding="utf-8")
        for name in ("same", "number", "emoticon"):
            result = cli("verify", "--before", str(run / "01_input.txt"), "--after", str(run / f"{name}.txt"), cwd=tmp)
            gates[name] = {"exitCode": result.returncode, "stdout": result.stdout}
        return {"source": BLOG, "manifest": manifest, "plan": plan, "checks": checks, "gates": gates}


class CliTests(unittest.TestCase):
    def test_contract_fixture_is_current(self):
        fresh = contract_fixture()
        if os.environ.get("SEJONG_WRITE_FIXTURES") == "1":
            FIXTURE.write_text(json.dumps(fresh, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        self.assertEqual(json.loads(FIXTURE.read_text(encoding="utf-8")), fresh)
        self.assertEqual([fresh["checks"][k]["gate"]["exit_code"] for k in ("accept", "retry", "attempt2", "rollback")],
                         [0, 1, 0, 2])
        self.assertEqual([fresh["gates"][k]["exitCode"] for k in ("same", "number", "emoticon")], [0, 2, 1])
        for name, report in fresh["checks"].items():
            self.assertEqual(io.check_problems(report), [], name)
        for name, gate in fresh["gates"].items():
            self.assertEqual(legacy_gate_problems(gate["stdout"], gate["exitCode"], 1), [], name)
        self.assertEqual(io.plan_problems(fresh["plan"]), [])

    def test_exit_codes_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.assertEqual(cli("prepare", "--run-dir", tmp).returncode, 1)          # no 01_input.txt
            self.assertEqual(cli("check", "--plan", "x").returncode, 3)                 # usage error
            self.assertEqual(cli("analyse", "--source", "x").returncode, 1)
            (run / "01_input.txt").write_text(BLOG, encoding="utf-8")
            self.assertEqual(cli("prepare", "--run-dir", tmp, "--analyse").returncode, 0)
            # a source that is not the plan's chunk is an execution error (exit 3), not a gate result
            (run / "other.txt").write_text(NO_EDIT, encoding="utf-8")
            (run / "r.json").write_text(json.dumps(reply()), encoding="utf-8")
            result = cli("check", "--plan", str(run / "plan-01.json"), "--source", str(run / "other.txt"), "--response",
                         str(run / "r.json"), "--attempt", "1", "--out", str(run / "o.txt"), "--report",
                         str(run / "c.json"))
            self.assertEqual(result.returncode, 3)
            self.assertNotIn("회의", result.stderr)                                    # no document text in messages
            self.assertFalse((run / "c.json").exists())
            self.assertEqual(cli("finalize", "--run-dir", tmp).returncode, 1)          # rewrites missing
            analysed = cli("analyse", "--source", str(run / "01_chunk_01_input.txt"), "--context",
                           str(run / "01_input.txt"), "--chunk-index", "1", "--chunk-total", "1", "--input-kind",
                           "text-file", "--strength", "normal", "--genre", "general", "--out", str(run / "p.json"))
            self.assertEqual(analysed.returncode, 0)
            plan = io.read_plan(run / "p.json")
            # text-file: FIX requests only (SSJ-A01 here) and never the open review
            self.assertEqual((plan.options.input_kind, plan.options.strength, plan.open_review.enabled,
                              [r.rules for r in plan.requests]), ("text-file", "normal", False, [["SSJ-A01"]]))

    def test_finalize_rolls_back_chunks_and_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "01_input.txt").write_text(BLOG, encoding="utf-8")
            sejong_cli.main(["prepare", "--run-dir", tmp])
            (run / "02_chunk_01_rewritten.txt").write_text("짧음", encoding="utf-8")          # ratio < 0.5
            report = sejong_cli.finalize(run, "03_reassembled.md", "03_reassembly_report.json", flags=FLAGS)
            self.assertEqual((report["warning_codes"], report["rolledBackChunks"]), (["CHUNK_ROLLED_BACK"], [1]))
            self.assertEqual(io.read_text(run / "03_reassembled.md"), BLOG)
            (run / "02_chunk_01_rewritten.txt").write_text(BLOG.replace("3만", "5만"), encoding="utf-8")
            report = sejong_cli.finalize(run, "03_reassembled.md", "03_reassembly_report.json", flags=FLAGS)
            self.assertEqual(report["warning_codes"], ["DIRECT_TEXT_DOCUMENT_ROLLED_BACK"])
            self.assertTrue(report["sejong"]["documentRolledBack"])
            self.assertEqual(io.read_text(run / "03_reassembled.md"), BLOG)
            self.assertEqual(io.read_json(run / "03_reassembly_report.json")["sejong"]["floorCodes"][:1], ["number_injected"])


class WorkflowDispatchTests(unittest.TestCase):
    def run_workflow(self, before, after, env):
        environment = {k: v for k, v in os.environ.items() if not k.startswith("SUPER_SEJONG_")}
        environment.update(env, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        return subprocess.run([PYTHON, str(ROOT / "engine_runtime" / "workflow.py"), "--before", str(before), "--after",
                               str(after)], capture_output=True, text=True, encoding="utf-8", env=environment)

    def test_v2_dispatch_and_legacy_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            before, after = Path(tmp) / "b.txt", Path(tmp) / "a.txt"
            before.write_text(BLOG, encoding="utf-8")
            after.write_text(BLOG.replace("3만", "4만"), encoding="utf-8")
            v2 = self.run_workflow(before, after, {"SUPER_SEJONG_ENGINE": "v2"})
            self.assertEqual(json.loads(v2.stdout), VF.verify_document(before, after, flags=FLAGS))
            self.assertEqual(v2.returncode, 2)
            legacy = self.run_workflow(before, after, {})
            with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("SUPER_SEJONG_")},
                                 clear=True):
                expected = workflow.verify(before, after)
            self.assertEqual(legacy.stdout, json.dumps(expected, ensure_ascii=False) + "\n")
            self.assertEqual(legacy.returncode, expected["gate"]["exit_code"])
            self.assertNotIn("changeRate", expected)                       # the legacy shape, untouched
            explicit = self.run_workflow(before, after, {"SUPER_SEJONG_ENGINE": "legacy"})
            self.assertEqual(explicit.stdout, legacy.stdout)


# ==========================================================================
# performance (DESIGN 6; budgets x2 so a loaded CI machine does not flake; measured values in the report)
# ==========================================================================
def corpus(chars):
    pieces, size, i = [], 0, 0
    while size < chars:
        text = SEED[i % len(SEED)]["text"].strip()
        pieces.append(text)
        size += len(text) + 2
        i += 1
    return "\n\n".join(pieces) + "\n"


class PerformanceTests(unittest.TestCase):
    BUDGET = {3000: (0.060, 0.150, 0.300), 15000: (0.300, 0.600, 1.0), 100000: (2.0, 0.600, 5.0)}
    SLACK = 2.0

    def stages(self, text, edit=None):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "01_input.txt").write_text(text, encoding="utf-8")
            manifest = chunk.prepare(run)
            document = io.read_text(run / "01_input.txt")
            body = [c for c in manifest["chunks"] if not c["passthrough"]]
            t0 = time.perf_counter()
            plans = []
            for entry in body:
                source = io.read_text(run / entry["input_file"])
                info = ChunkInfo(index=entry["index"], total=manifest["chunk_count"], source_sha256=PL._sha256(source),
                                 chars=len(source))
                plans.append((entry, source, PL.build_plan(source, options=options(), chunk=info,
                                                           seam=chunk.seam_ranges(manifest, entry["index"]), flags=FLAGS)))
            analyse = time.perf_counter() - t0
            checks = []
            for entry, source, plan in plans:
                response = target_reply(plan, source, edit(source)) if edit else reply()
                response["replacements"] = response["replacements"][:200]
                t0 = time.perf_counter()
                outcome = CK.check(plan, source, response=response, document=document if len(body) > 1 else None,
                                   flags=FLAGS)
                checks.append(time.perf_counter() - t0)
                io.write_text(run / entry["rewritten_file"], outcome.text)
            t0 = time.perf_counter()
            sejong_cli.finalize(run, "03_reassembled.md", "03_reassembly_report.json", flags=FLAGS)
            return analyse, max(checks), time.perf_counter() - t0

    def test_budgets(self):
        gold = {r["text"].strip(): r["gold_text"].strip() for r in SEED}

        def edit(source):
            out = source
            for src, dst in gold.items():
                if src != dst and src in out:
                    out = out.replace(src, dst)
            return out
        for chars, (b_analyse, b_check, b_finalize) in self.BUDGET.items():
            analyse, check, finalize = self.stages(corpus(chars), edit)
            with self.subTest(chars=chars):
                self.assertLess(analyse, b_analyse * self.SLACK)
                self.assertLess(check, b_check * self.SLACK)
                self.assertLess(finalize, b_finalize * self.SLACK)

    def test_adversarial_shapes(self):
        shapes = {"unclosed_quote": "그는 “" + ("가나다라 마바사 아자차카. " * 6700)[:99990] + "\n",
                  "one_sentence": ("가나다라 마바사 아자차카 타파하 " * 6000)[:99998] + ".\n",
                  "cta_lines": "궁금한 점이 있으시면 댓글로 문의해 주세요.\n" * 4000,
                  "repeated_tokens": ("문의해 주시면 " * 14300)[:99999] + "\n"}
        for name, text in shapes.items():
            analyse, check, finalize = self.stages(text)
            with self.subTest(shape=name, chars=len(text)):
                self.assertLess(max(analyse, check, finalize), 2.0 * self.SLACK)


if __name__ == "__main__":
    unittest.main()
