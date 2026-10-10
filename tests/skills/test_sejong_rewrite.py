"""Strength rewrite, 매우 강하게(다시쓰기) (WP-19): the paragraph mode of Super Sejong Engine v2 (engine_runtime/sejong/
rewrite.py) with stub writers, on constructed multi-paragraph pairs (tests/skills/data/sejong_rewrite_pairs.json,
project-authored), on the seed benchmark and composites (original project text), through the CLI and the agent-skill
gateway. Nothing calls a model.

The pair file holds 38 good rewrites (26 written while the rules were tuned, G01-G26, and 12 written afterwards and
measured once, H01-H12) and 41 damaged ones (D01-D29, HD01-HD12), each one good rewrite with one named damage. The
numbers asserted below are the measured ones of the WP-19 report; a change that moves them must say why.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine_runtime import sejong_cli  # noqa: E402
from engine_runtime.sejong import check as CK  # noqa: E402
from engine_runtime.sejong import config, io, plan as PL, rewrite as RW, text as T, verify as VF  # noqa: E402
from engine_runtime.sejong.types import Options  # noqa: E402
import test_sejong_pipeline as TP  # noqa: E402
from test_sejong_skill_path import SkillPathCase, environment  # noqa: E402
import score  # noqa: E402

FLAGS = config.Flags.from_env({})
PAIRS = {p["id"]: p for p in json.loads((ROOT / "tests/skills/data/sejong_rewrite_pairs.json").read_text(encoding="utf-8"))["pairs"]}
MIXED = ("저희 베이커리는 매일 아침 7시에 문을 엽니다. 모든 빵은 당일 생산, 당일 판매를 원칙으로 합니다.\n\n"
         "오늘은 새로 나온 무화과 깜빠뉴를 소개해 드릴게요. 겉은 바삭하고 속은 촉촉해요. 하나에 6,500원이에요.\n")


def rewrite_plan(text, genre="blog"):
    return PL.build_plan(text, options=Options(input_kind="direct-text", strength="rewrite", genre=genre), flags=FLAGS)


def full(text):
    return {"replacements": [], "rewrittenText": text, "warnings": []}


def by_paragraph(items):
    """A retry reply: one whole paragraph per paragraph id."""
    return {"replacements": [{"id": pid, "text": t, "reason": "retry"} for pid, t in items], "rewrittenText": "",
            "warnings": []}


def paragraphs(text):
    return [text[a:b] for a, b in T.segment(text).paragraphs]


def statuses(report):
    out = {}
    for s in report.sentences:
        out.setdefault(s.request, (s.status, s.codes))
    return out


def run_pair(pair):
    """Attempt 1 with the whole rewrite; attempt 2 (when asked) with the same paragraphs again, by paragraph id."""
    plan = rewrite_plan(pair["source"], pair["genre"])
    first = CK.check(plan, pair["source"], response=full(pair["rewrite"]), flags=FLAGS)
    final = first
    if first.report.policy == "retry":
        out = paragraphs(pair["rewrite"])
        items = [(r.id, out[int(r.id[1:]) - 1]) for r in first.report.retry if len(out) == len(plan.paragraphs)]
        final = CK.check(plan, pair["source"], response=by_paragraph(items), attempt=2, base=first.text,
                         flags=FLAGS)
    for report in (first.report, final.report):
        assert io.check_problems(report.to_json()) == [], pair["id"]
    return plan, first, final


def changed_paragraphs(pair, plan):
    src, out = paragraphs(pair["source"]), paragraphs(pair["rewrite"])
    if len(src) != len(out):
        return [p.id for p in plan.paragraphs]
    return [p.id for k, p in enumerate(plan.paragraphs) if src[k].strip() != out[k].strip()]


# ==========================================================================
# plan
# ==========================================================================
class RewritePlanTests(unittest.TestCase):
    def test_plan_is_in_rewrite_mode_with_one_entry_per_paragraph(self):
        plan = rewrite_plan(MIXED)
        data = plan.to_json()
        self.assertEqual(io.plan_problems(data), [])
        self.assertEqual((data["options"]["mode"], data["options"]["allowFullText"], data["options"]["openReview"]),
                         ("rewrite", True, False))
        self.assertTrue(plan.needs_model)
        self.assertEqual([(p.id, p.sentences, p.level, p.editable) for p in plan.paragraphs],
                         [("P1", ["S1", "S2"], "HAPSYO", True), ("P2", ["S3", "S4", "S5"], "HAEYO", True)])
        self.assertTrue(plan.paragraphs[1].humble)                         # 소개해 드릴게요
        self.assertEqual(io.read_plan.__name__, "read_plan")
        # requests stay in the plan as context (FIX + SUGGEST), never an open review
        self.assertEqual(plan.open_review.max_sentences, 0)

    def test_edit_plans_keep_their_exact_json(self):
        for strength in ("normal", "medium", "strong", "very-strong"):
            data = TP.plan_for(MIXED, strength, "blog").to_json()
            self.assertNotIn("mode", data["options"], strength)
            self.assertNotIn("paragraphs", data, strength)
            self.assertEqual(data["options"]["allowFullText"], strength == "very-strong")

    def test_dominant_level_rule(self):
        self.assertEqual(RW.dominant_level(["HAPSYO", "HAPSYO", "HAEYO"]), "HAPSYO")
        self.assertEqual(RW.dominant_level(["HAPSYO", "HAEYO"]), "HAEYO")              # tie: the level used last
        self.assertEqual(RW.dominant_level(["HAEYO", "HAPSYO", "NOMINAL"]), "HAPSYO")  # non-finite never counts
        self.assertEqual(RW.dominant_level(["HAEYO", "HAEYO", "HAPSYO", "HAPSYO", "HAE"]), "HAPSYO")
        self.assertEqual(RW.dominant_level(["NOMINAL", "NONE"]), "NOMINAL")
        self.assertEqual(RW.dominant_level(["NONE"]), "NONE")
        tie = rewrite_plan("신규 회원께는 첫 달 이용료를 50% 할인해 드립니다. 할인 쿠폰은 가입 즉시 문자로 보내 드려요.\n")
        self.assertEqual(tie.paragraphs[0].level, "HAEYO")

    def test_request_classes_per_paragraph(self):
        plan = rewrite_plan("혹시 시간 괜찮으세요? 괜찮으시면 내일 오전에 연락 주세요. 함께 해 봅시다.\n")
        p = plan.paragraphs[0]
        self.assertEqual((p.questions, p.requests, p.proposals), (1, 1, 1))
        self.assertTrue(p.hon_si)

    def test_headings_and_frozen_paragraphs_are_not_editable(self):
        plan = rewrite_plan("# 공지\n\n회의는 오전 10시에 시작합니다. 자료를 미리 읽어 오세요.\n")
        self.assertEqual([p.editable for p in plan.paragraphs], [False, True])
        only_heading = rewrite_plan("# 공지\n")
        self.assertFalse(only_heading.needs_model)
        self.assertEqual(io.plan_problems(only_heading.to_json()), [])

    def test_plan_contract_ties_mode_strength_and_paragraphs(self):
        data = rewrite_plan(MIXED).to_json()
        broken = json.loads(json.dumps(data))
        del broken["options"]["mode"]
        self.assertTrue(any("rewrite mode" in p for p in io.plan_problems(broken)))
        broken = json.loads(json.dumps(data))
        broken["paragraphs"][1]["id"] = "P7"
        self.assertTrue(any("P1, P2" in p for p in io.plan_problems(broken)))
        broken = json.loads(json.dumps(data))
        broken["needsModel"] = False
        self.assertTrue(any("needsModel" in p for p in io.plan_problems(broken)))

    def test_rewrite_has_no_open_review_under_any_setting(self):
        for setting in ("medium", "strong", "always"):
            flags = config.Flags.from_env({"SUPER_SEJONG_OPEN_REVIEW": setting})
            self.assertFalse(config.open_review_enabled(flags, "rewrite"))
        with self.assertRaises(ValueError):
            config.open_review_enabled(FLAGS, "extreme")


# ==========================================================================
# the constructed pairs (measured numbers of the WP-19 report)
# ==========================================================================
class RewritePairTests(unittest.TestCase):
    maxDiff = None

    def test_good_rewrites_false_blocks(self):
        blocked, changed = [], 0
        for pair in PAIRS.values():
            if pair["kind"] != "good":
                continue
            plan, first, _final = run_pair(pair)
            got = statuses(first.report)
            for pid in changed_paragraphs(pair, plan):
                changed += 1
                if got[pid][0] != "accepted":
                    blocked.append((pair["id"], pid, tuple(got[pid][1])))
        # 96 changed paragraphs (69 tuned + 27 held-out). The four blocks are guards every strength has, on natural
        # paraphrases: 중단됩니다 -> 운행되지 않으니 (polarity; 정전되는 동안에는 also reads as a new deadline), 무료입니다
        # -> 무료로 참여할 수 있습니다 (CAN added), 편하게 -> 부담 없이 (polarity), two facts joined with -지만 (contrast).
        self.assertEqual(changed, 96)
        self.assertEqual(blocked, [("G07", "P3", ("polarity_changed", "cta_deadline_changed")),
                                   ("G11", "P2", ("modality_changed",)),
                                   ("G19", "P2", ("polarity_changed",)),
                                   ("G23", "P2", ("flow_contrast_changed",))])

    def test_damaged_rewrites_are_caught_per_paragraph(self):
        missed, wrong_code, collateral = [], [], []
        for pair in PAIRS.values():
            if pair["kind"] != "damage":
                continue
            plan, first, final = run_pair(pair)
            a1, a2 = statuses(first.report), statuses(final.report)
            for pid in pair["damaged"]:
                if a2[pid][0] == "accepted":
                    missed.append((pair["id"], pid))
                if not (set(a1[pid][1]) | set(a2[pid][1])) & set(pair["expect"]):
                    wrong_code.append(pair["id"])
            for pid in changed_paragraphs(pair, plan):
                if pid not in pair["damaged"] and a2[pid][0] != "accepted":
                    collateral.append((pair["id"], pid))
        # 42 damaged paragraphs. The one miss: a giver/receiver swap with a topic-marked subject (저희는 기업에 ...
        # 제공했으며 -> 기업이 저희에게 ...), which meaning.py misses sentence by sentence too. D09 (two cooking steps
        # swapped) is caught as cta_action_replaced, not as temporal_order_changed.
        self.assertEqual(missed, [("D10", "P2")])
        self.assertEqual(wrong_code, ["D09", "D10"])
        # Undamaged changed paragraphs of the damaged documents: the four good-set blocks again, and D24, whose
        # merged paragraphs make the whole reply unusable (attempt 2 of this stub cannot answer by paragraph).
        self.assertEqual(sorted(collateral), [("D03", "P2"), ("D04", "P2"), ("D15", "P2"), ("D24", "P1"), ("D28", "P2")])

    def test_mixed_paragraph_levels_keep_their_mix(self):
        plan, first, _ = run_pair(PAIRS["G13"])
        self.assertEqual(first.report.policy, "accept")
        self.assertEqual(first.text, PAIRS["G13"]["rewrite"])
        self.assertIn("원칙으로 합니다.", first.text)
        self.assertIn("6,500원이에요.", first.text)

    def test_paragraph_normalised_to_its_dominant_level_passes(self):
        for key in ("G12", "G19", "G20", "H06"):
            plan, first, _ = run_pair(PAIRS[key])
            self.assertEqual(statuses(first.report)["P1"], ("accepted", []), key)

    def test_level_drift_is_retried_then_reverted_alone(self):
        pair = PAIRS["D21"]
        plan, first, final = run_pair(pair)
        self.assertEqual(first.report.policy, "retry")
        self.assertEqual([(r.id, r.sentence, [v.code for v in r.violations]) for r in first.report.retry],
                         [("P2", plan.paragraphs[1].sentences[0], ["voice_level"])])
        self.assertEqual(first.report.retry[0].violations[0].detail, "HAEYO->HAPSYO")
        got = statuses(final.report)
        self.assertEqual({k: v[0] for k, v in got.items()}, {"P1": "accepted", "P2": "reverted", "P3": "accepted"})
        out = paragraphs(final.text)
        self.assertEqual(out[1], paragraphs(pair["source"])[1])
        self.assertEqual((out[0], out[2]), (paragraphs(pair["rewrite"])[0], paragraphs(pair["rewrite"])[2]))
        self.assertEqual(final.report.policy, "accept")

    def test_losses_are_caught_in_their_paragraph_only(self):
        cases = {"D01": "number_dropped", "D04": "protected_span_changed", "D12": "cta_channel_changed",
                 "D15": "voice_hon_si_dropped", "D18": "voice_emoticon_dropped", "D11": "cta_deadline_changed",
                 "D16": "voice_humble_dropped", "D29": "voice_colloquial_changed"}
        for key, code in cases.items():
            pair = PAIRS[key]
            plan, first, _ = run_pair(pair)
            got = statuses(first.report)
            damaged = pair["damaged"][0]
            self.assertEqual(got[damaged][0], "retry", key)
            self.assertIn(code, got[damaged][1], key)

    def test_merges_and_splits_inside_a_paragraph_pass(self):
        for key in ("G03", "G21", "G26"):
            plan, first, _ = run_pair(PAIRS[key])
            self.assertEqual(first.report.policy, "accept", key)
            self.assertEqual(first.text, PAIRS[key]["rewrite"], key)

    def test_paragraph_count_change_makes_the_reply_unusable(self):
        pair = PAIRS["D24"]
        plan = rewrite_plan(pair["source"])
        first = CK.check(plan, pair["source"], response=full(pair["rewrite"]), flags=FLAGS)
        self.assertEqual((first.report.policy, first.report.hard_failures), ("retry", ["model_output_unusable"]))
        self.assertEqual([r.id for r in first.report.retry], ["P1", "P2", "P3"])
        self.assertEqual(first.text, pair["source"])
        # a retry that answers every paragraph by id is applied paragraph by paragraph
        good = paragraphs(PAIRS["G01"]["rewrite"])
        second = CK.check(plan, pair["source"], response=by_paragraph(list(zip(("P1", "P2", "P3"), good))),
                          attempt=2, base=first.text, flags=FLAGS)
        self.assertEqual((second.report.policy, second.text), ("accept", PAIRS["G01"]["rewrite"]))

    def test_whole_reply_rules(self):
        pair = PAIRS["G01"]
        plan = rewrite_plan(pair["source"])
        p1 = paragraphs(pair["rewrite"])[0]
        unusable = {
            "replacements at attempt 1": (1, by_paragraph([("P1", p1)])),
            "a sentence request id": (1, {"replacements": [{"id": "R1", "text": p1, "reason": ""}], "rewrittenText": "", "warnings": []}),
        }
        for label, (attempt, response) in unusable.items():
            outcome = CK.check(plan, pair["source"], response=response, flags=FLAGS)
            self.assertIn("model_output_unusable", outcome.report.hard_failures, label)
        first = CK.check(plan, pair["source"], response=full(pair["rewrite"].replace("9,000원", "8,000원")), flags=FLAGS)
        self.assertEqual(first.report.policy, "retry")
        for label, response in {"full text at attempt 2": full(pair["rewrite"]),
                                "an unknown paragraph id": by_paragraph([("P9", p1)]),
                                "a sentence id": {"replacements": [{"id": "S1", "text": p1, "reason": ""}],
                                                  "rewrittenText": "", "warnings": []},
                                "an id twice": by_paragraph([("P2", p1), ("P2", p1)])}.items():
            second = CK.check(plan, pair["source"], response=response, attempt=2, base=first.text, flags=FLAGS)
            self.assertIn("model_output_unusable", second.report.hard_failures + second.report.shadow_failures, label)
            self.assertEqual(io.check_problems(second.report.to_json()), [], label)

    def test_paragraph_layout_rejections(self):
        pair = PAIRS["G01"]
        plan = rewrite_plan(pair["source"])
        first = CK.check(plan, pair["source"], response=full(pair["rewrite"].replace("9,000원", "8,000원")), flags=FLAGS)
        p2 = paragraphs(pair["rewrite"])[1]
        split = p2.replace(" 장칼국수가", "\n\n장칼국수가")
        lines = p2.replace(" 장칼국수가", "\n장칼국수가")
        for text, code in ((split, "paragraph_split"), (lines, "paragraph_lines_changed")):
            second = CK.check(plan, pair["source"], response=by_paragraph([("P2", text)]), attempt=2,
                              base=first.text, flags=FLAGS)
            self.assertEqual(statuses(second.report)["P2"], ("rejected", [code]))

    def test_frozen_heading_paragraph_is_never_rewritten(self):
        source = "# 이번 주 소식\n\n회의는 오전 10시에 시작합니다. 자료를 미리 읽어 오세요.\n"
        plan = rewrite_plan(source)
        target = "# 이번 주의 소식\n\n회의는 오전 10시에 시작하니 자료를 미리 읽어 오세요.\n"
        outcome = CK.check(plan, source, response=full(target), flags=FLAGS)
        got = statuses(outcome.report)
        self.assertEqual(got[None], ("reverted", ["collateral_edit"]))
        self.assertEqual(got["P2"], ("accepted", []))
        self.assertTrue(outcome.text.startswith("# 이번 주 소식\n\n회의는 오전 10시에 시작하니"))

    def test_length_ratio_bound(self):
        plan, first, _ = run_pair(PAIRS["D25"])
        self.assertIn("paragraph_length_ratio", statuses(first.report)["P3"][1])
        self.assertEqual(statuses(first.report)["P3"][0], "retry")

    def test_identity_and_empty_replies_change_nothing_but_the_fixes(self):
        source = "참가비는 3만 원이 됬습니다. 자료는 미리 읽어 오세요.\n\n궁금하신 점은 댓글로 남겨 주세요.\n"
        plan = rewrite_plan(source)
        for response in (full(source), full("")):
            outcome = CK.check(plan, source, response=response, flags=FLAGS)
            self.assertEqual((outcome.report.policy, outcome.text), ("accept", source.replace("됬", "됐")))
            self.assertEqual(outcome.report.counts["normFixes"], 1)

    def test_voice_rule_allows_kept_endings_and_casual_mixes(self):
        # a paragraph keeps its own minority ending (the 해요 CTA of a 합쇼 paragraph) when the writer keeps it
        source = "행사는 토요일에 열립니다. 장소는 시민회관입니다. 늦지 않게 오세요.\n"
        plan = rewrite_plan(source)
        kept = CK.check(plan, source, response=full("행사는 토요일에 시민회관에서 열립니다. 늦지 않게 오세요.\n"), flags=FLAGS)
        self.assertEqual(kept.report.policy, "accept")
        new = CK.check(plan, source, response=full("행사는 토요일에 시민회관에서 열려요. 늦지 않게 오세요.\n"), flags=FLAGS)
        self.assertEqual(statuses(new.report)["P1"], ("retry", ["voice_level"]))
        # 반말: a paragraph that already mixes 해체 and 해라체 may come back in either
        casual = "어제 라멘집 가 봤는데 진짜 맛있더라. 국물도 진했어.\n"
        plan = rewrite_plan(casual)
        out = CK.check(plan, casual, response=full("어제 라멘집에 가 봤는데 진짜 맛있었어. 국물도 진하더라.\n"), flags=FLAGS)
        self.assertEqual(out.report.policy, "accept")
        written = "회의는 오전에 열렸다. 결론은 다음 주에 나온다.\n"
        plan = rewrite_plan(written, "essay")
        drift = CK.check(plan, written, response=full("회의는 오전에 열렸어. 결론은 다음 주에 나온다.\n"), flags=FLAGS)
        self.assertEqual(statuses(drift.report)["P1"][0], "retry")

    def test_verify_document_in_rewrite_mode(self):
        pair = PAIRS["G01"]
        gate = VF.verify_document(pair["source"], pair["rewrite"], flags=FLAGS, mode="rewrite")
        self.assertEqual((gate["gate"]["exit_code"], gate["hardFailures"], gate["warningReasons"]["codes"]), (0, [], []))
        bad = VF.verify_document(pair["source"], PAIRS["D01"]["rewrite"], flags=FLAGS, mode="rewrite")
        self.assertEqual(bad["gate"]["exit_code"], 2)
        merged = VF.verify_document(pair["source"], PAIRS["D24"]["rewrite"], flags=FLAGS, mode="rewrite")
        self.assertIn("flow_paragraph_count_changed", merged["hardFailures"])


# ==========================================================================
# the seed benchmark and composites in rewrite mode
# ==========================================================================
class RewriteSeedTests(unittest.TestCase):
    def test_invariants_and_identity_on_every_seed_record(self):
        for record in TP.SEED + TP.COMPOSITES:
            gate = VF.verify_document(record["text"], record["text"], flags=FLAGS, mode="rewrite")
            self.assertEqual((gate["gate"]["exit_code"], gate["hardFailures"], gate["shadowFailures"]), (0, [], []))
            plan = TP.plan_for(record["text"], "rewrite", TP.GENRE.get(record["genre"], "general"))
            base = TP.base_text(plan, record["text"])
            gate = VF.verify_document(record["text"], base, flags=FLAGS, mode="rewrite")
            self.assertEqual((gate["gate"]["exit_code"], gate["shadowFailures"]), (0, []), record["id"])
            outcome = CK.check(plan, record["text"], candidate=record["text"], flags=FLAGS)
            self.assertEqual(outcome.text, base, record["id"])

    def test_gold_rewrites_of_the_seed(self):
        rows, changed, blocked = [], 0, 0
        for record in TP.SEED + TP.COMPOSITES:
            plan = TP.plan_for(record["text"], "rewrite", TP.GENRE.get(record["genre"], "general"))
            first, final, _calls = TP.run_writer(plan, record["text"], record["gold_text"], mode="candidate")
            for report in (first.report, final.report):
                self.assertEqual(io.check_problems(report.to_json()), [], record["id"])
            a1, a2 = statuses(first.report), statuses(final.report)
            for pid, (status, _codes) in a1.items():
                if pid is not None and status not in ("unchanged", "deterministic"):
                    changed += 1
                    blocked += a2[pid][0] != "accepted"
            if record["item_type"] != "composite_document":
                rows.append((record, final.text))
        agg = score.aggregate([score.score_item(r, o) for r, o in rows])
        # Measured: 331 paragraphs the gold text changes, 22 not accepted (the same wrong-connective, polarity and
        # 문의하실게요 cases the edit strengths revert); 91 of 92 primary injections fixed, as at medium.
        self.assertEqual((changed, blocked), (331, 22))
        self.assertEqual((agg["primary"], agg["primary_fixed"]), (92, 91))
        self.assertEqual({k: agg[k] for k in ("voice_violations", "invariants_violated", "numbers_dropped", "numbers_added",
                                               "cta_weakened", "cta_invented_sentences", "quotes_changed")},
                         dict.fromkeys(("voice_violations", "invariants_violated", "numbers_dropped", "numbers_added",
                                        "cta_weakened", "cta_invented_sentences", "quotes_changed"), 0))


class RewriteFixtureTests(unittest.TestCase):
    """tests/fixtures/sejong/plan-rewrite.json and check-rewrite-retry.json feed the TypeScript prompt, reply and adapter
    tests; they must be what this engine writes (SEJONG_WRITE_FIXTURES=1 regenerates them)."""
    SOURCE = ("# 이번 주 소식\n\n저희 베이커리는 매일 아침 7시에 문을 엽니다. 왜냐하면 반죽을 매일 새로 합니다. "
              "모든 빵은 당일 판매를 원칙으로 합니다.\n\n오늘은 새로 나온 무화과 깜빠뉴를 소개해 드릴게요ㅋㅋ 하나에 6,500원이에요. "
              "궁금하신 점은 댓글로 남겨 주세요.\n")
    DAMAGED = ("# 이번 주 소식\n\n저희 베이커리는 반죽을 매일 새로 하기 때문에 매일 아침 8시에 문을 엽니다. 모든 빵은 당일 판매를 "
               "원칙으로 합니다.\n\n오늘은 새로 나온 무화과 깜빠뉴를 소개해 드릴게요ㅋㅋ 가격은 하나에 6,500원입니다. 궁금하신 점은 "
               "댓글로 남겨 주세요.\n")

    def test_fixtures_are_the_engine_output(self):
        import os
        plan = rewrite_plan(self.SOURCE)
        report = CK.check(plan, self.SOURCE, response=full(self.DAMAGED), flags=FLAGS).report
        fixtures = {"plan-rewrite.json": plan.to_json(), "check-rewrite-retry.json": report.to_json()}
        for name, data in fixtures.items():
            path = ROOT / "tests" / "fixtures" / "sejong" / name
            if os.environ.get("SEJONG_WRITE_FIXTURES") == "1":
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), data, name)
        self.assertEqual([(r.id, r.sentence) for r in report.retry], [("P2", "S2"), ("P3", "S5")])


# ==========================================================================
# CLI, skill bridge, skill gateway
# ==========================================================================
class RewriteCliTests(unittest.TestCase):
    def test_cli_accepts_rewrite_and_verifies_by_paragraph(self):
        import tempfile
        pair = PAIRS["G12"]                       # a 해요 request normalised to 하십시오 in a 합쇼 paragraph
        with tempfile.TemporaryDirectory(prefix="sejong-rewrite-cli-") as temp:
            before, after = Path(temp) / "before.txt", Path(temp) / "after.txt"
            before.write_text(pair["source"], encoding="utf-8")
            after.write_text(pair["rewrite"], encoding="utf-8")
            cli = str(ROOT / "engine_runtime" / "sejong_cli.py")
            edit = subprocess.run([sys.executable, cli, "verify", "--before", str(before), "--after", str(after)],
                                  capture_output=True, encoding="utf-8")
            rewrite = subprocess.run([sys.executable, cli, "verify", "--before", str(before), "--after", str(after),
                                      "--mode", "rewrite"], capture_output=True, encoding="utf-8")
            self.assertEqual(rewrite.returncode, 0, rewrite.stdout)
            self.assertEqual(json.loads(rewrite.stdout)["gate"]["exit_code"], 0)
            self.assertEqual(edit.returncode, 2)             # the per-sentence lock reports the normalised level
            self.assertIn("voice_level", json.loads(edit.stdout)["hardFailures"])
            out = Path(temp) / "plan.json"
            done = subprocess.run([sys.executable, cli, "analyse", "--source", str(before), "--chunk-index", "1",
                                   "--chunk-total", "1", "--input-kind", "direct-text", "--strength", "rewrite",
                                   "--genre", "blog", "--out", str(out)], capture_output=True, encoding="utf-8")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["options"]["mode"], "rewrite")
        self.assertIn("rewrite", sejong_cli.STRENGTHS)

    def test_skill_bridge_options_accept_rewrite(self):
        sys.path.insert(0, str(ROOT / "engine_runtime"))
        try:
            import skill_bridge
        finally:
            sys.path.remove(str(ROOT / "engine_runtime"))
        self.assertEqual(skill_bridge.options("direct-text", "rewrite", offline=True),
                         {"inputKind": "direct-text", "strength": "rewrite"})
        self.assertEqual(skill_bridge.options("text-file", "rewrite", offline=True),
                         {"inputKind": "text-file", "strength": "rewrite"})
        with self.assertRaises(ValueError):
            skill_bridge.options("direct-text", "rewrite-all", offline=True)


class RewriteSkillPathTests(SkillPathCase):
    def test_v2_rewrite_job_retries_by_paragraph_and_gates_by_paragraph(self):
        pair = PAIRS["D21"]
        state = self.prepare(pair["source"], strength="rewrite")
        prompt = Path(state["instructionsPath"]).read_text(encoding="utf-8")
        self.assertIn("문단별로 다시 쓴다", prompt)
        self.assertIn("[문단 말투]", prompt)
        plan = self.plan_of(state)
        self.assertEqual(plan.options.mode, "rewrite")
        state = self.accept(state, {"replacements": [], "rewrittenText": pair["rewrite"], "warnings": []})
        self.assertEqual((state["status"], state["attempt"]), ("rewrite", 2))
        retry_prompt = Path(state["instructionsPath"]).read_text(encoding="utf-8")
        self.assertIn("P2 이전 답:", retry_prompt)
        self.assertIn("검증에 걸린 문단 1개만", " ".join(state["warnings"]))
        good = paragraphs(PAIRS["G04"]["rewrite"])[1]
        state = self.accept(state, {"replacements": [{"id": "P2", "text": good, "reason": "말투"},
                                                     {"id": "P1", "text": "엉뚱한 문단", "reason": ""}],
                                    "rewrittenText": "", "warnings": []})
        self.assertEqual(state["status"], "ready-to-finalize")
        done, output = self.finalize(state)
        self.assertEqual(output, PAIRS["G04"]["rewrite"])             # P1 off the retry list was dropped
        self.assertFalse(any(w.startswith("DOCUMENT_REVIEW_RECOMMENDED") for w in self.job_state(state)["warnings"]))

    def test_legacy_engine_runs_rewrite_as_very_strong(self):
        env = environment(engine="legacy")
        self.input.write_text(PAIRS["G01"]["source"], encoding="utf-8", newline="")
        state = self.call("prepare", "--input", self.input, "--input-kind", "direct-text", "--strength", "rewrite", env=env)
        self.assertEqual(state["rewriteOptions"], {"inputKind": "direct-text", "strength": "rewrite"})
        instructions = Path(state["instructionsPath"]).read_text(encoding="utf-8")
        self.assertIn("요청 강도: very-strong.", instructions)
        self.assertNotIn("요청 강도: rewrite", instructions)


if __name__ == "__main__":
    unittest.main()
