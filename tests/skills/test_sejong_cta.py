"""Super Sejong Engine v2 CTA ledger and gate (WP-6, DESIGN.md 3.3, 3.8; T6 report and prototypes).

Pair sets A, B, C are the T6 sets (tuned, so they pin behaviour and do not estimate it); D, E, F are the WP-6
condition sets (see tests/skills/data/sejong_cta_pairs.json). The T6 prototype is loaded from
docs/research/super-sejong/v2/prototypes to show, with the same sets, what the port changed.
"""
import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine_runtime"))
from sejong import cta, cta_gate  # noqa: E402
from sejong import io as sejong_io  # noqa: E402
from sejong import text as T  # noqa: E402
from sejong.align import align_documents  # noqa: E402
from sejong.types import CODE_RE  # noqa: E402

DATA = json.loads((ROOT / "tests" / "skills" / "data" / "sejong_cta_pairs.json").read_text(encoding="utf-8"))
PROTOTYPES = ROOT / "docs" / "research" / "super-sejong" / "v2" / "prototypes"
BENCHMARK = ROOT / "docs" / "research" / "super-sejong" / "v2" / "benchmark"
PLAN_SCHEMA = sejong_io.load_schema("plan")
CHECK_SCHEMA = sejong_io.load_schema("check")


def _protect_importable():
    # protect.py imports engine_runtime/quantities.py, which needs Python >= 3.10 (the product runs 3.11+)
    try:
        from sejong import protect  # noqa: F401
        return True
    except (ImportError, TypeError):
        return False


NEEDS_PROTECT = unittest.skipUnless(_protect_importable(), "sejong.protect needs Python >= 3.10")


def gate(src, out):
    a, b = T.segment(src), T.segment(out)
    return cta_gate.compare(a, b, align_documents(a, b))


def codes(result, *severities):
    return sorted({v.code for sev in (severities or result) for v in result[sev]})


def rows(*sets):
    return [(name, row) for name in sets for row in DATA[name]]


def load_t6():
    """The T6 prototype detector and gate (the gate imports the detector as `cta_detect`)."""
    saved = sys.modules.get("cta_detect")
    try:
        modules = {}
        for name, file in (("cta_detect", "T6_cta_detect_final.py"), ("t6_cta_gate", "T6_cta_gate_final.py")):
            spec = importlib.util.spec_from_file_location(name, PROTOTYPES / file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            modules[name] = module
        return modules["t6_cta_gate"]
    finally:
        sys.modules.pop("t6_cta_gate", None)
        if saved is None:
            sys.modules.pop("cta_detect", None)
        else:
            sys.modules["cta_detect"] = saved


def best_of(runs, fn):
    best = None
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    return best


class DataTests(unittest.TestCase):
    def test_sets_a_b_c_are_verbatim_copies_of_the_t6_files(self):
        for name in "ABC":
            with self.subTest(set=name):
                prototype = json.loads((PROTOTYPES / f"T6_pairs_{name}.json").read_text(encoding="utf-8"))
                self.assertEqual(DATA[name], prototype)

    def test_set_sizes(self):
        preserving = [r for _, r in rows("A", "B", "C") if r["label"] == "preserve"]
        violating = [r for _, r in rows("A", "B", "C") if r["label"] != "preserve"]
        self.assertEqual((len(preserving), len(violating)), (108, 113))
        self.assertEqual([len(DATA[k]) for k in "DEF"], [66, 53, 32])


class T6PairSetTests(unittest.TestCase):
    """DESIGN 8.2 acceptance: 0/108 preserving pairs hard-blocked, >= 102/113 violating pairs blocked,
    >= 112/113 flagged."""

    NOT_BLOCKED = ["A086", "A088", "A089", "A090", "A091", "B033", "B052", "B053", "B060", "C030"]
    SOFT_ONLY_PRESERVING = ["A014", "B007", "B009", "B010", "B030", "C003"]

    @classmethod
    def setUpClass(cls):
        cls.results = {r["id"]: (r, gate(r["source"], r["rewrite"])) for _, r in rows("A", "B", "C")}

    def test_no_preserving_pair_is_hard_blocked(self):
        blocked = [(i, codes(res, "hard")) for i, (r, res) in self.results.items()
                   if r["label"] == "preserve" and res["hard"]]
        self.assertEqual(blocked, [])

    def test_violating_pairs_blocked_and_flagged(self):
        violating = [(i, res) for i, (r, res) in self.results.items() if r["label"] != "preserve"]
        blocked = [i for i, res in violating if res["hard"]]
        flagged = [i for i, res in violating if res["hard"] or res["soft"]]
        self.assertEqual(len(violating), 113)
        self.assertGreaterEqual(len(blocked), 102)
        self.assertGreaterEqual(len(flagged), 112)
        # exact pins: a change in either direction must be looked at
        self.assertEqual(len(blocked), 103)
        self.assertEqual(len(flagged), 113)
        self.assertEqual([i for i, _ in violating if i not in blocked], self.NOT_BLOCKED)

    def test_preserving_pairs_flagged_soft_are_the_t6_synonym_substitutions(self):
        soft_only = [i for i, (r, res) in self.results.items() if r["label"] == "preserve" and res["soft"]]
        self.assertEqual(soft_only, self.SOFT_ONLY_PRESERVING)

    def test_every_category_but_the_open_class_ones_is_blocked(self):
        by = {}
        for _, (r, res) in self.results.items():
            if r["label"] != "preserve":
                by.setdefault(r["category"], []).append(bool(res["hard"]))
        weak = {k: v for k, v in by.items() if not all(v)}
        self.assertEqual(sorted(weak), ["action", "drop", "moved", "object"])
        self.assertEqual({k: (sum(v), len(v)) for k, v in weak.items()},
                         {"action": (3, 7), "drop": (10, 11), "moved": (0, 1), "object": (0, 4)})

    def test_the_expected_t6_code_is_among_the_findings(self):
        missing = []
        for i, (r, res) in self.results.items():
            if r["label"] == "preserve":
                continue
            found = {v.code for sev in res.values() for v in sev}
            if not ({c.lower() for c in r["expect_codes"]} & found):
                missing.append(i)
        # open-class action swaps are reported as cta_action_replaced (soft) instead of cta_action_changed
        self.assertEqual(missing, ["A086", "A088", "A105", "B033", "B052"])

    def test_negated_condition_that_keeps_its_word_is_blocked(self):
        # T6's known miss: 준비되셨다면 -> 준비되지 않았다면
        res = self.results["B046"][1]
        self.assertEqual(codes(res, "hard"), ["cta_condition_changed"])
        self.assertEqual(res["hard"][0].detail, "negation")


class ConditionSetTests(unittest.TestCase):
    """Condition sets D, E, F: what the port changed against the T6 prototype on the same pairs."""

    # (hard false positives of the T6 prototype, violating pairs it blocks) per set
    T6_BEFORE = {"D": (14, 12), "E": (14, 9), "F": (11, 6)}
    KNOWN_MISSES = {"D049"}                    # condition restated as a noun phrase that keeps its word
    SOFT_ONLY_PRESERVING = {"D": ["D040", "D042"],
                            "E": ["E016", "E017", "E027", "E028", "E029", "E033"],
                            "F": ["F009", "F017", "F018"]}

    @classmethod
    def setUpClass(cls):
        cls.t6 = load_t6()
        cls.new, cls.old = {}, {}
        for name in "DEF":
            cls.new[name] = [(r, gate(r["source"], r["rewrite"])) for r in DATA[name]]
            cls.old[name] = [(r, cls.t6.compare(r["source"], r["rewrite"])) for r in DATA[name]]

    def test_t6_prototype_numbers_are_reproduced(self):
        for name, (false_positives, blocked) in self.T6_BEFORE.items():
            with self.subTest(set=name):
                preserving = [res for r, res in self.old[name] if r["label"] == "preserve"]
                violating = [res for r, res in self.old[name] if r["label"] != "preserve"]
                self.assertEqual(sum(bool(res["hard"]) for res in preserving), false_positives)
                self.assertEqual(sum(bool(res["hard"]) for res in violating), blocked)

    def test_no_preserving_pair_is_hard_blocked(self):
        for name in "DEF":
            with self.subTest(set=name):
                blocked = [r["id"] for r, res in self.new[name] if r["label"] == "preserve" and res["hard"]]
                self.assertEqual(blocked, [])

    def test_preserving_pairs_reported_soft_are_open_class_rewordings(self):
        for name in "DEF":
            with self.subTest(set=name):
                soft = [r["id"] for r, res in self.new[name] if r["label"] == "preserve" and res["soft"]]
                self.assertEqual(soft, self.SOFT_ONLY_PRESERVING[name])
                for r, res in self.new[name]:
                    for v in res["soft"]:
                        if r["label"] == "preserve":
                            self.assertEqual((v.code, v.detail), ("cta_condition_changed", "reworded"))

    def test_violating_pairs_are_blocked_or_flagged_as_expected(self):
        for name in "DEF":
            with self.subTest(set=name):
                for r, res in self.new[name]:
                    if r["label"] == "preserve":
                        continue
                    if r["expect"] == "hard" and r["id"] not in self.KNOWN_MISSES:
                        self.assertTrue(res["hard"], r["id"])
                    if r["expect"] == "flag" or r["id"] not in self.KNOWN_MISSES:
                        self.assertTrue(res["hard"] or res["soft"], r["id"])

    def test_pooled_numbers(self):
        preserving = [res for n in "DEF" for r, res in self.new[n] if r["label"] == "preserve"]
        violating = [res for n in "DEF" for r, res in self.new[n] if r["label"] != "preserve"]
        old_preserving = [res for n in "DEF" for r, res in self.old[n] if r["label"] == "preserve"]
        old_violating = [res for n in "DEF" for r, res in self.old[n] if r["label"] != "preserve"]
        self.assertEqual((len(preserving), len(violating)), (95, 56))
        self.assertEqual(sum(bool(r["hard"]) for r in old_preserving), 39)      # T6 prototype
        self.assertEqual(sum(bool(r["hard"]) for r in preserving), 0)
        self.assertEqual(sum(bool(r["hard"]) for r in old_violating), 27)
        self.assertEqual(sum(bool(r["hard"]) for r in violating), 47)
        self.assertEqual(sum(bool(r["hard"] or r["soft"]) for r in violating), 55)

    def test_condition_synonym_is_no_longer_blocked(self):
        src, out = "서류가 준비되면 신청서를 제출하세요.", "서류가 갖춰지면 신청서를 제출하세요."
        self.assertTrue(self.t6.compare(src, out)["hard"])                      # T6: cta_condition_changed
        self.assertEqual(gate(src, out), {"hard": [], "soft": [], "info": []})

    def test_condition_changes_keep_their_label(self):
        cases = [("서류가 준비되셨다면 접수하세요.", "서류가 준비되지 않았다면 접수하세요.", "hard", "negation"),
                 ("서류가 부족하다면 보완을 요청하세요.", "서류가 충분하다면 보완을 요청하세요.", "hard", "presence"),
                 ("5명 이상이라면 단체 신청을 하세요.", "10명 이상이라면 단체 신청을 하세요.", "hard", "number"),
                 ("3개월 이상 남았다면 지금 신청하세요.", "3개월 이하 남았다면 지금 신청하세요.", "hard", "bound"),
                 ("계약 전이라면 먼저 확인하세요.", "계약 후라면 먼저 확인하세요.", "hard", "timing"),
                 ("이해가 어려우시면 상담을 신청하세요.", "이해가 쉬우시면 상담을 신청하세요.", "hard", "ease"),
                 ("증상이 있으면 즉시 병원을 방문하십시오.", "즉시 병원을 방문하십시오.", "hard", "dropped"),
                 ("학생이라면 할인 신청을 하세요.", "직장인이라면 할인 신청을 하세요.", "soft", "reworded"),
                 ("대리 신청이라면 위임장을 함께 제출하세요.", "직접 신청이라면 위임장을 함께 제출하세요.", "soft", "reworded")]
        for src, out, severity, detail in cases:
            with self.subTest(src=src):
                res = gate(src, out)
                found = [(sev, v.detail) for sev in ("hard", "soft") for v in res[sev]
                         if v.code == "cta_condition_changed"]
                self.assertEqual(found, [(severity, detail)])

    def test_a_condition_the_rewrite_adds_is_hard(self):
        res = gate("연락 주세요.", "서류가 필요하시면 연락 주세요.")
        self.assertEqual([(v.code, v.detail) for v in res["hard"]], [("cta_condition_changed", "added")])

    def test_condition_stems(self):
        tokens = cta_gate.cond_tokens
        self.assertEqual(tokens("서류가 준비되면"), tokens("서류가 준비되셨다면"))
        self.assertEqual(tokens("준비가 되면")[-1], "준비")
        self.assertEqual(tokens("급하시면")[-1], "급하")             # T6 lost one-syllable stems before 하
        self.assertEqual(tokens("기한이 지났다면")[-1], tokens("기한이 지나셨다면")[-1])
        self.assertTrue(cta_gate._key_in("나오", "공고가나온다면"))
        self.assertTrue(cta_gate._key_in("급하", "일정이급할때"))
        self.assertTrue(cta_gate._key_in("정하", "점포를정하지않았다면"))
        self.assertFalse(cta_gate._key_in("나오", "공고가게시되면"))


class DetectorTests(unittest.TestCase):
    def ledger(self, text_):
        units, deontic = cta.detect(T.segment(text_))
        return units, deontic

    def one(self, text_):
        units, _ = self.ledger(text_)
        self.assertEqual(len(units), 1, text_)
        return units[0]

    def test_forms_and_force_ladder(self):
        cases = [("서류를 확인하세요.", "imperative", 4), ("서류를 확인해 주세요.", "request", 4),
                 ("서류를 확인해 보세요.", "trial", 3), ("서류를 확인하는 편이 좋습니다.", "advisory", 2),
                 ("서류를 확인하셔도 됩니다.", "option", 1), ("서류를 확인하지 마세요.", "prohibitive", 4),
                 ("꼭 확인하세요.", "imperative", 5), ("함께 살펴봅시다.", "suggestion", 3),
                 ("연락 주시면 안내해 드립니다.", "conditional_offer", 3),
                 ("공감과 댓글 부탁드립니다.", "request", 4)]
        for text_, form, force in cases:
            with self.subTest(text=text_):
                unit = self.one(text_)
                self.assertEqual((unit.form, unit.force), (form, force))

    def test_polarity_level_and_honorific(self):
        self.assertEqual(self.one("서류를 확인하지 마세요.").polarity, "neg")
        self.assertEqual(self.one("서류를 확인하세요.").polarity, "pos")
        self.assertEqual(self.one("서류를 확인하십시오.").level, "hapsyo")
        self.assertEqual(self.one("서류를 확인해 주세요.").level, "haeyo")
        self.assertEqual(self.one("서류를 확인해라.").level, "haera")
        self.assertTrue(self.one("서류를 확인하세요.").hon_si)

    def test_components(self):
        unit = self.one("궁금한 점이 있으시면 02-123-4567로 4월 30일까지 무료로 전화해 주세요.")
        self.assertEqual(unit.action, ["전화"])
        self.assertEqual(unit.condition, "궁금한 점이 있으시면")
        self.assertEqual(unit.deadline, ["4월 30일까지"])
        self.assertIn("02-123-4567", unit.channel)
        self.assertEqual(unit.benefit, ["무료"])
        self.assertEqual(unit.tier, "contact")
        self.assertEqual(self.one("꼭 확인하세요.").intensity, ["necessity"])
        self.assertEqual(self.one("서류를 준비하고 제출하세요.").action, ["준비", "제출"])
        self.assertEqual(self.one("공감과 댓글 부탁드립니다.").action, ["공감", "댓글"])

    def test_not_a_cta(self):
        for text_ in ["안녕하세요.", "좋은 하루 되세요.", "행복하시길 바랍니다.", "건강하세요.",
                      "정리해 보겠습니다.", "자료는 검토해 드립니다.", "서류 제출이 필요합니다.",
                      "서류를 제출해야 합니다.", "신청은 온라인으로 가능합니다.",
                      "직원이 “서류를 확인하세요”라고 안내합니다.", "“서류를 확인하세요.”",
                      "그는 서류를 확인하라고 말했다.", "이 논문은 새로운 방법을 제안합니다."]:
            with self.subTest(text=text_):
                self.assertEqual(self.ledger(text_)[0], [])

    def test_quotation_spanning_lines_is_not_the_authors_call(self):
        units, _ = self.ledger("직원이 말했다.\n“오늘 서류를 확인하세요.\n내일은 문의하세요.”\n")
        self.assertEqual(units, [])

    def test_deontic_statements_are_returned_as_units(self):
        units, deontic = self.ledger("서류를 제출해야 합니다. 서류를 확인하세요. 접수가 필요합니다.")
        self.assertEqual([u.form for u in units], ["imperative"])
        self.assertEqual([u.text for u in deontic], ["서류를 제출해야 합니다.", "접수가 필요합니다."])

    def test_bulleted_cta_keeps_its_core(self):
        # the T6 prototype applied cue offsets to the unstripped text, so a bullet cut the core short
        for lead in ("- ", "1. ", "▶ ", "* "):
            with self.subTest(lead=lead):
                unit = self.one(f"{lead}신청서를 작성하세요.")
                self.assertEqual((unit.action, unit.object), (["작성"], "신청서"))

    def test_button_and_heading_lines(self):
        unit = self.one("▶ 무료 상담 예약하기")
        self.assertEqual((unit.form, unit.force, unit.action), ("nominal", 3, ["예약"]))
        self.assertEqual(self.ledger("지금 바로 신청하기\n")[0][0].form, "nominal")
        self.assertEqual(self.one("## 서류를 확인하세요").form, "imperative")
        self.assertEqual(self.ledger("오늘도 감사합니다. 공감 구독\n")[0], [])      # a button needs its own line

    def test_light_verb_before_the_cue_is_not_an_action(self):
        unit = self.one("아래 연락처로 연락을 하여 주시기 바랍니다.")
        self.assertEqual(unit.action, ["연락"])
        self.assertEqual(self.one("문의를 해 주세요.").action, ["문의"])
        # 바라겠습니다 and 바랍니다 are one force
        self.assertEqual(self.one("확인해 보시길 바라겠습니다.").force, self.one("확인해 보시기 바랍니다.").force)

    def test_request_with_a_consequence_clause(self):
        for text_ in ["공감을 눌러 주시면 큰 힘이 됩니다.", "댓글을 남겨 주시면 힘이 나요.", "알려 주시면 정말 감사하겠습니다."]:
            with self.subTest(text=text_):
                self.assertEqual(self.one(text_).form, "request")

    def test_condition_clause_ignores_nouns_that_end_in_myeon(self):
        for text_ in ["도면을 확인하세요.", "면허를 갱신하세요.", "화면에서 확인하세요.", "서면으로 제출하세요."]:
            with self.subTest(text=text_):
                self.assertIsNone(self.one(text_).condition)
        self.assertEqual(self.one("도움이 필요한 경우 전화해 주세요.").condition, "도움이 필요한 경우")
        self.assertEqual(self.one("서류를 제출하실 때 신분증을 지참하세요.").condition, "서류를 제출하실 때")
        self.assertIsNone(self.one("신분증을 지참하는 것이 좋습니다.").condition)

    def test_ids_and_sentences(self):
        doc = T.segment("오늘은 소개합니다. 서류를 확인하세요. 안내입니다. 문의해 주세요.")
        units, _ = cta.detect(doc)
        self.assertEqual([(u.id, u.sentence) for u in units], [("C1", "S2"), ("C2", "S4")])

    def test_units_follow_the_plan_schema(self):
        text_ = ("궁금한 점이 있으시면 02-123-4567로 4월 30일까지 무료로 전화해 주세요.\n\n▶ 무료 상담 예약하기\n"
                 + "서류를 확인하세요. " * 3)
        units, _ = cta.detect(T.segment(text_))
        self.assertGreaterEqual(len(units), 5)
        for unit in units:
            self.assertEqual(sejong_io.validate(unit.to_json(), {"$ref": "#/$defs/cta"}, PLAN_SCHEMA), [])

    def test_a_run_on_is_read_by_its_tail(self):
        unit = self.one("가나다라마바 " * 600 + "서류를 확인하세요.")
        self.assertEqual(unit.form, "imperative")

    def test_long_components_are_cut_to_the_schema_limits(self):
        for text_ in ["가나다라마바사 " * 60 + "필요하시면 " + "다양한 " * 30 + "서류를 확인하세요.",
                      "http://" + "a" * 150 + ".com 에서 신청하세요.", "x" * 300 + " 4월 30일까지 문의해 주세요."]:
            for unit in cta.detect(T.segment(text_))[0]:
                self.assertEqual(sejong_io.validate(unit.to_json(), {"$ref": "#/$defs/cta"}, PLAN_SCHEMA), [])


@NEEDS_PROTECT
class FindingTests(unittest.TestCase):
    def findings(self, text_):
        return cta.wording_findings(T.segment(text_))

    def test_spacing_findings_carry_the_spaced_form(self):
        text_ = "서류를 확인해주세요. 언제든 연락주세요."
        found = self.findings(text_)
        self.assertEqual([(f.rule, f.tier, f.action, f.fix) for f in found],
                         [("CTA-SP1", "FIX", "deterministic", "확인해 주"), ("CTA-SP2", "FIX", "deterministic", "연락 주")])
        for f in found:
            self.assertEqual(text_[f.start:f.end], {"CTA-SP1": "확인해주", "CTA-SP2": "연락주"}[f.rule])
            self.assertEqual(sejong_io.validate(f.to_json(), {"$ref": "#/$defs/finding"}, PLAN_SCHEMA), [])

    def test_silge_is_reported_and_never_repaired(self):
        found = self.findings("서류를 준비하실게요. 상담을 받아 보실게요.")
        self.assertEqual([(f.rule, f.tier, f.action, f.fix) for f in found],
                         [("CTA-SILGE", "LEAVE", "report", None)] * 2)

    def test_barae_is_a_suggestion(self):
        found = self.findings("건강하시기를 바래요.")
        self.assertEqual([(f.rule, f.tier, f.action) for f in found], [("CTA-BARAE", "SUGGEST", "request")])

    def test_quotes_and_frozen_headings_are_skipped(self):
        self.assertEqual(self.findings("직원이 “확인해주세요”라고 했다."), [])
        self.assertEqual(self.findings("## 확인해주세요\n\n본문입니다.\n"), [])


class SafeRepairTests(unittest.TestCase):
    def test_safe_repair_spacing(self):
        fixed, applied = cta.safe_repair("서류를 확인해주세요. 연락주세요. 문의해주시기 바랍니다.")
        self.assertEqual(fixed, "서류를 확인해 주세요. 연락 주세요. 문의해 주시기 바랍니다.")
        self.assertEqual(applied, ["cta_spacing_juseyo", "cta_spacing_noun_juseyo", "cta_spacing_juseyo"])
        self.assertEqual(cta.safe_repair("직원이 “확인해주세요”라고 했다.")[0], "직원이 “확인해주세요”라고 했다.")

    def test_safe_repair_never_applies_silge(self):
        for text_ in ["서류를 준비하실게요.", "상담을 받아 보실게요.", "확인하실께요.", "연락 주실게요 ㅎㅎ", "하실게요, 보실게요."]:
            for opt_in in (False, True):
                with self.subTest(text=text_, fix_colloquial=opt_in):
                    fixed, applied = cta.safe_repair(text_, fix_colloquial=opt_in)
                    self.assertEqual(fixed, text_)
                    self.assertEqual(applied, [])

    def test_lgge_only_with_the_colloquial_opt_in(self):
        text_ = "내일 연락드릴께요. 서류는 제가 볼께요. 이따 전화할께요. 곧 올께요."
        self.assertEqual(cta.safe_repair(text_), (text_, []))
        self.assertEqual(cta.safe_repair(text_, fix_colloquial=False), (text_, []))
        fixed, applied = cta.safe_repair(text_, fix_colloquial=True)
        self.assertEqual(fixed, "내일 연락드릴게요. 서류는 제가 볼게요. 이따 전화할게요. 곧 올게요.")
        self.assertEqual(applied, ["cta_lgge"] * 4)
        quoted = "직원은 “연락드릴께요”라고 했다."
        self.assertEqual(cta.safe_repair(quoted, fix_colloquial=True)[0], quoted)

    def test_no_repair_in_the_lexicon_touches_the_honorific(self):
        repairs = [w for w in cta.LEX["wording"] if w["action"] == "deterministic"] + [cta.LEX["safe_repair"]["lgge"]]
        self.assertEqual(sorted(w["repair"] for w in repairs),
                         ["cta_lgge", "cta_spacing_juseyo", "cta_spacing_noun_juseyo"])
        for w in repairs:
            self.assertNotIn("세요", w["repl"])
            self.assertNotIn("실", w["repl"])
        silge = [w for w in cta.LEX["wording"] if w["rule"] == "CTA-SILGE"][0]
        self.assertEqual((silge["tier"], silge["action"], silge["repl"], silge["repair"]), ("LEAVE", "report", None, None))

    def test_safe_repair_is_idempotent_and_changes_only_spaces_or_the_ge_spelling(self):
        samples = [r[key] for _, r in rows("A", "B", "C") for key in ("source", "rewrite")]
        samples += ["할께요 연락드릴께요 확인해주세요", "연락주세요\n문의주시면 확인해주시기 바랍니다"]
        for sample in samples:
            for opt_in in (False, True):
                fixed, _ = cta.safe_repair(sample, fix_colloquial=opt_in)
                self.assertEqual(cta.safe_repair(fixed, fix_colloquial=opt_in), (fixed, []), sample)
                if not opt_in:
                    # nothing but spaces: no ending, honorific or syllable can have changed
                    self.assertEqual(fixed.replace(" ", ""), sample.replace(" ", ""), sample)

    def test_the_gate_accepts_a_repaired_sentence(self):
        # T6 section 1c: compare(x, safe_repair(x)) has no hard and no soft finding
        samples = [r[key] for _, r in rows("A", "B", "C", "D", "E", "F") for key in ("source", "rewrite")]
        samples += ["서류를 확인해주세요. 언제든 연락주세요.", "내일 연락드릴께요. 서류는 제가 볼께요."]
        for sample in samples:
            for opt_in in (False, True):
                fixed, _ = cta.safe_repair(sample, fix_colloquial=opt_in)
                res = gate(sample, fixed)
                self.assertEqual((res["hard"], res["soft"]), ([], []), sample)


class GateStructureTests(unittest.TestCase):
    def test_identity_is_empty(self):
        samples = [r[key] for _, r in rows("A", "B", "C", "D", "E", "F") for key in ("source", "rewrite")]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(gate(sample, sample), {"hard": [], "soft": [], "info": []})

    def test_identity_on_long_mixed_documents(self):
        for name in "ABCDEF":
            for key in ("source", "rewrite"):
                doc = "\n\n".join(r[key] for r in DATA[name])
                with self.subTest(set=name, side=key):
                    self.assertEqual(gate(doc, doc), {"hard": [], "soft": [], "info": []})

    def test_a_whole_set_as_one_document_keeps_the_per_pair_verdicts(self):
        # sources and rewrites of the preserving pairs of set A, interleaved with neutral sentences
        pres = [r for r in DATA["A"] if r["label"] == "preserve" and "\n" not in r["source"]]
        src = "\n\n".join(f"오늘의 안내입니다. {r['source']} 감사합니다." for r in pres)
        out = "\n\n".join(f"오늘의 안내입니다. {r['rewrite']} 감사합니다." for r in pres)
        self.assertEqual(gate(src, out)["hard"], [])

    def test_split_merge_and_move(self):
        self.assertEqual(gate("문의하세요. 신청하세요.", "문의하고 신청하세요."), {"hard": [], "soft": [], "info": []})
        self.assertEqual(codes(gate("문의하고 신청하세요.", "문의하세요. 신청하세요.")), [])
        self.assertEqual(codes(gate("서류를 준비하고 신청서를 작성한 뒤 제출하세요.",
                                    "서류를 준비하고 신청서를 작성하세요. 그다음 제출하세요.")), [])
        res = gate("가나다 라마바. 안내입니다.\n\n궁금하시면 문의해 주세요.",
                   "궁금하시면 문의해 주세요.\n\n가나다 라마바. 안내입니다.")
        self.assertEqual(codes(res), ["cta_moved"])
        self.assertEqual(codes(res, "soft"), ["cta_moved"])
        # two CTAs swapped in place stay paired by alignment, not reported as moved
        self.assertEqual(codes(gate("서류를 확인하세요. 안내입니다. 예약하세요.", "서류를 확인하세요. 안내입니다. 예약하세요.")), [])

    def test_a_merge_that_loses_an_action_is_a_drop(self):
        res = gate("문의하세요. 신청하세요.", "문의하세요.")
        self.assertEqual(codes(res, "hard"), ["cta_dropped"])

    def test_invented_and_dropped(self):
        res = gate("안내입니다.", "안내입니다. 지금 바로 문의하세요.")
        self.assertEqual([(v.code, v.sentence, v.detail) for v in res["hard"]],
                         [("cta_invented", "S1", "new imperative force 5")])
        res = gate("서류를 확인하세요. 예약하세요.", "서류를 확인하세요.")
        self.assertEqual([(v.code, v.sentence) for v in res["hard"]], [("cta_dropped", "S2")])
        self.assertEqual(res["hard"][0].keep, "예약하세요.")

    def test_a_cta_before_everything_is_invented_against_the_first_source_sentence(self):
        res = gate("안내입니다. 감사합니다.", "지금 바로 문의하세요. 안내입니다. 감사합니다.")
        self.assertEqual([(v.code, v.sentence) for v in res["hard"]], [("cta_invented", "S1")])

    def test_deontic_bridging(self):
        res = gate("이 제도는 시행되었습니다. 서류 제출이 필요합니다.", "이 제도는 시행되었습니다. 서류를 제출해 주세요.")
        self.assertEqual(codes(res), ["cta_from_deontic"])
        res = gate("서류를 제출하세요.", "서류를 제출해야 합니다.")
        self.assertEqual(codes(res), ["cta_to_deontic"])

    def test_offer_dropped(self):
        self.assertEqual(codes(gate("검토 후 안내해 드립니다.", "검토 후 연락드립니다.")), ["cta_offer_dropped"])

    def test_components(self):
        cases = [("신청서는 3월 31일까지 제출하세요.", "신청서는 3월 30일까지 제출하세요.", "cta_deadline_changed", "hard"),
                 ("마감 전에 꼭 제출하세요.", "꼭 제출하세요.", "cta_deadline_changed", "hard"),
                 ("02-123-4567로 전화해 주세요.", "02-123-4568로 전화해 주세요.", "cta_channel_changed", "hard"),
                 ("프로필의 링크로 예약하세요.", "댓글로 예약하세요.", "cta_channel_changed", "hard"),
                 ("무료로 상담해 보세요.", "상담해 보세요.", "cta_benefit_dropped", "hard"),
                 ("서류를 확인하세요.", "서류를 확인하는 것도 좋습니다.", "cta_force_weakened", "hard"),
                 ("확인해 보세요.", "반드시 확인하십시오.", "cta_force_strengthened", "hard"),
                 ("서류를 제출하지 마세요.", "서류를 제출하세요.", "cta_polarity_flipped", "hard"),
                 ("구독해 주세요.", "공유해 주세요.", "cta_action_changed", "hard"),
                 ("서류를 준비하고 제출하세요.", "서류를 제출하세요.", "cta_action_count_changed", "hard"),
                 ("서류를 제출하세요.", "서류를 접수하세요.", "cta_action_replaced", "soft"),
                 ("사업자등록증을 제출하세요.", "신분증을 제출하세요.", "cta_object_changed", "soft")]
        for src, out, code, severity in cases:
            with self.subTest(src=src, out=out):
                self.assertIn(code, codes(gate(src, out), severity))

    def test_info_codes(self):
        res = gate("꼭 확인하세요.", "반드시 확인하십시오.")
        self.assertEqual(codes(res, "hard", "soft"), [])
        self.assertEqual(codes(res, "info"), ["cta_speech_level_changed"])
        self.assertEqual(codes(gate("서류를 확인하세요.", "서류를 확인해 주세요."), "info"),
                         ["cta_form_changed_same_force"])
        self.assertEqual(codes(gate("서류를 확인하세요.", "꼭 서류를 확인하세요."), "hard", "info"),
                         ["cta_force_strengthened"])

    def test_pairs_may_be_given_or_computed(self):
        a, b = T.segment("서류를 확인하세요. 안내입니다."), T.segment("서류를 확인하는 것도 좋습니다. 안내입니다.")
        self.assertEqual(cta_gate.compare(a, b), cta_gate.compare(a, b, align_documents(a, b)))

    def test_findings_are_lowercase_ascii_labels_for_the_right_sentences(self):
        seen = set()
        for _, r in rows("A", "B", "C", "D", "E", "F"):
            res = gate(r["source"], r["rewrite"])
            for severity, items in res.items():
                for v in items:
                    seen.add(v.code)
                    self.assertRegex(v.code, CODE_RE)
                    self.assertIn(v.code, cta_gate.CODES)
                    self.assertEqual((v.family, v.severity), ("cta", severity))
                    self.assertTrue(v.detail.isascii(), v.detail)        # labels and numbers, never document text
                    self.assertLessEqual(len(v.detail), 200)
                    self.assertLessEqual(len(v.keep or ""), 200)
                    self.assertRegex(v.sentence or "S1", r"^S[0-9]{1,4}$")
                    self.assertEqual(sejong_io.validate(v.to_json(), {"$ref": "#/$defs/violation"}, CHECK_SCHEMA), [])
                    if severity == "hard" and v.code != "cta_condition_changed":
                        self.assertIn(v.code, cta_gate.HARD)
        self.assertTrue(all(c == c.lower() for c in cta_gate.CODES))
        self.assertGreaterEqual(len(seen), 14)

    def test_severity_tables_are_disjoint_and_match_design_3_8(self):
        self.assertFalse(cta_gate.HARD & cta_gate.SOFT)
        self.assertFalse(cta_gate.HARD & cta_gate.INFO)
        self.assertFalse(cta_gate.SOFT & cta_gate.INFO)
        self.assertEqual(sorted(cta_gate.HARD), sorted([
            "cta_dropped", "cta_invented", "cta_force_weakened", "cta_force_strengthened", "cta_polarity_flipped",
            "cta_action_changed", "cta_action_count_changed", "cta_condition_changed", "cta_deadline_changed",
            "cta_channel_changed", "cta_benefit_dropped"]))
        self.assertEqual(sorted(cta_gate.SOFT), sorted([
            "cta_object_changed", "cta_action_replaced", "cta_moved", "cta_to_deontic", "cta_from_deontic",
            "cta_offer_dropped"]))

    def test_deadline_skeleton_ignores_the_words_t6_captured_after_마감(self):
        res = gate("접수 마감이 다가오면 서둘러 제출하세요.", "접수 마감이 다가온다면 서둘러 제출하세요.")
        self.assertEqual(codes(res, "hard"), [])
        res = gate("접수 마감 3일 전까지 제출하세요.", "접수 마감일에 제출하세요.")
        self.assertEqual(codes(res, "hard"), ["cta_deadline_changed"])
        res = gate("이번 주 안에 연락 주세요.", "이번 달 안에 연락 주세요.")
        self.assertEqual(codes(res, "hard"), ["cta_deadline_changed"])


class SeedBenchmarkTests(unittest.TestCase):
    """The seed benchmark (original text, written for T7) is independent of the T6 pair sets: its gold rewrites
    are the fixes a reviewer wants, so none of them may be blocked, and its CTA annotations check the detector."""

    @classmethod
    def setUpClass(cls):
        paths = [BENCHMARK / "seed_benchmark.jsonl", BENCHMARK / "seed_composites.jsonl"]
        if not all(p.exists() for p in paths):
            raise unittest.SkipTest("seed benchmark not present")
        cls.rows = [json.loads(line) for p in paths for line in p.read_text(encoding="utf-8").splitlines() if line]

    def test_gold_rewrites_are_not_blocked(self):
        self.assertEqual(len(self.rows), 212)
        flagged = []
        for row in self.rows:
            res = gate(row["text"], row["gold_text"])
            if res["hard"] or res["soft"]:
                flagged.append((row["id"], codes(res, "hard", "soft")))
        self.assertEqual(flagged, [])

    def test_identity_on_texts_and_gold_texts(self):
        for row in self.rows:
            for key in ("text", "gold_text"):
                self.assertEqual(gate(row[key], row[key]), {"hard": [], "soft": [], "info": []}, row["id"])

    def test_annotated_ctas_are_found(self):
        total = found = 0
        for row in self.rows:
            doc = T.segment(row["text"])
            spans = [(doc.units[c.index].start, doc.units[c.index].end) for c in cta.analyse(doc).ctas]
            for annotation in row.get("cta") or []:
                if annotation["form"] == "obligation":
                    continue               # plain deontic statements are tracked in the meaning ledger, not here
                total += 1
                a, b = annotation["span"]
                found += any(x < b and a < y for x, y in spans)
        self.assertEqual(total, 159)
        self.assertGreaterEqual(found, 150)


class PerformanceTests(unittest.TestCase):
    """DESIGN 6 and 8.2: adversarial inputs at most 0.6 s (best of three, documents already segmented and
    aligned: segmentation and alignment have their own budgets in WP-1 and WP-2)."""

    LIMIT = 0.6

    def timed(self, src, out):
        a, b = T.segment(src), T.segment(out)
        pairs = align_documents(a, b)
        return (best_of(3, lambda: cta.detect(a)), best_of(3, lambda: cta_gate.compare(a, b, pairs)),
                cta_gate.compare(a, b, pairs))

    def check(self, name, src, out, expect_hard=None):
        detect_time, compare_time, res = self.timed(src, out)
        self.assertLess(detect_time, self.LIMIT, f"{name} detect")
        self.assertLess(compare_time, self.LIMIT, f"{name} compare")
        if expect_hard is not None:
            self.assertEqual(len(res["hard"]), expect_hard, name)

    def test_8000_cta_lines(self):
        same = "확인하세요\n" * 8000                       # the T6 shape: identical lines
        self.check("lines same", same, same + " 추가 문장입니다.", 0)
        self.check("lines same, all dropped", same, "안내입니다\n" * 8000, 8000)
        src = "".join(f"{i}번 서류를 확인하세요.\n" for i in range(8000))
        self.check("distinct lines, form changed", src,
                   "".join(f"{i}번 서류를 확인해 주세요.\n" for i in range(8000)), 0)
        self.check("distinct lines, weakened", src,
                   "".join(f"{i}번 서류를 확인하는 것도 좋습니다.\n" for i in range(8000)), 8000)
        self.check("distinct lines, dropped", src, "".join(f"{i}번 안내입니다.\n" for i in range(8000)), 8000)

    def test_8000_cta_lines_with_conditions(self):
        src = "".join(f"{i}번 도움이 필요하시면 연락해 주세요.\n" for i in range(8000))
        out = "".join(f"{i}번 도움을 원하시면 연락해 주세요.\n" for i in range(8000))
        self.check("condition synonyms", src, out, 0)

    def test_32k_repeated_jusimyeon(self):
        for n in (4000, 12500):                         # 32k and 100k characters, one run-on sentence
            shape = "문의해 주시면 " * n
            self.check(f"repeated 문의해 주시면 x{n}", shape, shape + " 추가 문장입니다.")

    def test_other_adversarial_shapes(self):
        shapes = {"hangul run": "가나다라마바사" * 7200, "open quotes": "“" * 50000, "nested quotes": "“a‘b’" * 5000,
                  "munui": "문의해 " * 8000, "butak": "부탁 " * 12000, "colon list": "서류를 준비하세요: " * 3000,
                  "conditions": ("필요하시면 " * 6000) + "주세요", "run-on deadline": ("가나다" * 15000) + "까지 신청하세요.",
                  "run-on condition": ("도움이 필요하시면 " * 2500) + "연락 주시면 안내해 드립니다.",
                  "run-on obligation": ("가나다라" * 12000) + " 해야 합니다.",
                  "long CTA sentences": "".join(("가나다라마바사아자차카타파하" * 28) + " 서류를 확인하세요.\n" for _ in range(250))}
        for name, shape in shapes.items():
            with self.subTest(shape=name):
                self.check(name, shape, shape + " 추가 문장입니다.")

    def test_time_grows_linearly(self):
        def make(n):
            return "".join(f"{i}번 도움이 필요하시면 02-123-{i:04d}로 {i % 28 + 1}일까지 전화해 주세요.\n" for i in range(n))
        timings = {}
        for n in (120, 1200):                           # about 10k and 100k characters
            src, out = make(n), make(n).replace("전화해 주세요", "연락해 주세요")
            a, b = T.segment(src), T.segment(out)
            pairs = align_documents(a, b)
            cta._classify.cache_clear()
            timings[n] = best_of(2, lambda: (cta._classify.cache_clear(), cta_gate.compare(a, b, pairs)))
        self.assertLess(timings[1200] / max(timings[120], 1e-4), 15)


if __name__ == "__main__":
    unittest.main()
