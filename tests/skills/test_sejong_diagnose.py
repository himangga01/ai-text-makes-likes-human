"""Super Sejong Engine v2 diagnostics and norm layer (WP-8, DESIGN.md 3.3, 3.7 step 1, 9.2a).

Every text here is constructed for the test; no owner text and no corpus text.
"""
import importlib.util
import json
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine_runtime import super_sejong_josa  # noqa: E402
from engine_runtime.sejong import diagnose as D  # noqa: E402
from engine_runtime.sejong import io, josa, norms, text  # noqa: E402
from engine_runtime.sejong.types import Finding, Options, Span  # noqa: E402

DATA = ROOT / "engine_runtime" / "sejong" / "data"
SEED = ROOT / "docs" / "research" / "super-sejong" / "v2" / "benchmark" / "seed_benchmark.jsonl"
T2_VOICE = ROOT / "docs" / "research" / "super-sejong" / "v2" / "prototypes" / "T2_voice.py"
# Seed genres outside types.Genre run as general (only rules valid in every genre).
SEED_GENRE = {"casual": "general", "marketing": "general"}
LIGHT_VERB = ("SSJ-LV1", "SSJ-LV2", "SSJ-LV3", "SSJ-LV4")


def findings(source, genre="general", fix_colloquial=False):
    return D.diagnose(text.segment(source), genre=genre, fix_colloquial=fix_colloquial)


def rules(source, genre="general", fix_colloquial=False, tiers=("FIX", "SUGGEST")):
    return [f.rule for f in findings(source, genre, fix_colloquial) if f.tier in tiers]


def spans_of(source, rule, genre="general"):
    return [source[f.start:f.end] for f in findings(source, genre) if f.rule == rule]


def fixed(source, fix_colloquial=False):
    return norms.fix_text(source, fix_colloquial=fix_colloquial)[0]


def seed_rows():
    return [json.loads(line) for line in SEED.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_voice():
    """sejong.voice once WP-4 is merged, else the T2 regex prototype it is ported from."""
    if importlib.util.find_spec("engine_runtime.sejong.voice") is not None:
        from engine_runtime.sejong import voice  # noqa: WPS433

        def sig(sentence):
            v = voice.signature(sentence)
            squeezed = re.sub(r"\s+", "", sentence)
            return (v.level, v.mood, v.hon_si, v.humble, tuple(v.persona), voice.signature(squeezed).si_count)
        return sig
    spec = importlib.util.spec_from_file_location("t2_voice_wp8", T2_VOICE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    def sig(sentence):
        v = module.signature(sentence)
        # every -시- of the sentence (9.2a item 3), counted without spaces: 하실수 / 하실 수 is one -시-
        squeezed = module.HON_SI_NOUN.sub(" ", re.sub(r"\s+", "", sentence))
        return (v["level"], v["mood"], v["hon_si"], v["humble"], tuple(v["persona"]),
                len(module.HON_SI_PRED.findall(squeezed)))
    return sig


class DataFiles(unittest.TestCase):
    def test_every_misspelling_entry_fixes_its_examples_and_spares_its_exclusions(self):
        data = json.loads((DATA / "misspellings.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data["entries"]), 30)
        for entry in data["entries"]:
            opt_in = entry["class"] == "colloquial"
            self.assertIn(entry["class"], ("error", "colloquial"))
            self.assertTrue(entry["norm"])
            for wrong, right in entry["examples"]:
                with self.subTest(entry=entry["id"], example=wrong):
                    self.assertEqual(fixed(wrong, fix_colloquial=opt_in), right)
            for safe in entry["exclusions"]:
                with self.subTest(entry=entry["id"], exclusion=safe):
                    self.assertEqual(fixed(safe, fix_colloquial=True), safe)

    def test_only_the_hal_kke_family_is_colloquial(self):
        data = json.loads((DATA / "misspellings.json").read_text(encoding="utf-8"))
        colloquial = {e["wrong"] for e in data["entries"] if e["class"] == "colloquial"}
        self.assertEqual(colloquial, {"-ㄹ께", "-ㄹ꺼", "-ㄹ껄", "-ㄹ껀"})
        errors = {e["wrong"] for e in data["entries"] if e["class"] == "error"}
        for owner_error in ("되요", "됬", "몇일", "금새", "할려-", "웬지"):
            self.assertIn(owner_error, errors)

    def test_redundancy_lexicon_drops_the_t3_false_positives(self):
        data = json.loads((DATA / "redundancy.json").read_text(encoding="utf-8"))
        ids = {e["id"] for e in data["entries"]}
        self.assertNotIn("RD_haebyeon_ga", ids)
        self.assertNotIn("RD_busang_danghada", ids)
        self.assertEqual(rules("해변가에서 놀았다. 그는 부상당했다."), [])

    def test_one_korean_guide_per_rule_and_no_authority_claim_for_suggest_rules(self):
        guides = D.guides()
        self.assertEqual(set(guides), set(D.RULES))
        for rule_id, line in guides.items():
            with self.subTest(rule=rule_id):
                self.assertNotIn("\n", line)
                self.assertRegex(line, "[가-힣]")
                self.assertLessEqual(len(line), 300)              # plan schema guide maxLength
                if D.RULES[rule_id].tier != "FIX":
                    self.assertNotRegex(line, "국립국어원|NIKL|맞춤법|표준어|규범|어문 규정")

    def test_rule_ids_fit_the_plan_schema(self):
        pattern = io.load_schema("plan")["$defs"]["ruleId"]["pattern"]
        for rule_id in D.RULES:
            self.assertRegex(rule_id, pattern)


class T3Exclusions(unittest.TestCase):
    """The false-positive classes the T3 hand-check found must stay silent (T3 §3-4)."""

    def test_named_exclusions(self):
        for source in ("머지않아 봄이 온다.", "그는 누구 못지않게 성실하다.", "외톨이였던 그가 웃었다.",
                       "실수 없이 끝냈다.", "할수록 어렵다.", "해변가에서 놀았다.", "돈은 받지 않되 일은 한다.",
                       "그러기를 바라 마지않는다.", "별수 없이 돌아왔다.", "날것을 먹었다.", "물때가 끼었다.",
                       "볼때기가 빨갛다.", "가을 시작되면 떠난다.", "일관되게 말했다.", "제품이 만들어지는 과정이다.",
                       "따뜻하게 느껴진다.", "김율 선수가 뛰었다.", "그 일을 하게 되면 알려 줘.", "토박이였던 할머니"):
            with self.subTest(source=source):
                self.assertEqual(rules(source), [])

    def test_lexical_ireoji_is_not_a_double_passive_but_is_a_light_verb_suggestion(self):
        got = {f.rule: f.tier for f in findings("합의가 이루어졌다.")}
        self.assertEqual(got, {"SSJ-LV3": "SUGGEST"})

    def test_kept_rule_positives(self):
        cases = [("할수 있다.", "SSJ-N01"), ("하는것이 낫다.", "SSJ-N01"), ("할때 말해.", "SSJ-N01"),
                 ("하지않고 갔다.", "SSJ-N02"), ("인식율이 높다.", "SSJ-N03"), ("개선률이 낮다.", "SSJ-N03"),
                 ("그는 남편이였다.", "SSJ-N05"), ("이건 사랑이예요.", "SSJ-N05"), ("인간으로써 부끄럽다.", "SSJ-N06"),
                 ("측정함으로서 알았다.", "SSJ-N06"), ("이로서 끝났다.", "SSJ-N06"),
                 ("왜냐하면 처벌이 무서워서 안 할 수도 있다.", "SSJ-A01"),
                 ("제 생각은 미디어를 제한해야 한다고 생각합니다.", "SSJ-A02"),
                 ("개정안이 국무회의를 통과되면서 바뀌었다.", "SSJ-A03"), ("연구가 진행되어지고 있다.", "SSJ-A04"),
                 ("학교에서 미리 예방해야 한다.", "SSJ-A05"), ("그는 결코 약속을 어기는 사람이다.", "SSJ-A06"),
                 ("비록 비가 왔다.", "SSJ-A07"), ("아무리 바쁘다.", "SSJ-A07"), ("만약 비가 온다.", "SSJ-A07")]
        for source, rule in cases:
            with self.subTest(source=source):
                self.assertIn(rule, rules(source))

    def test_expected_form_rides_on_ryul_and_roseo_requests(self):
        [ryul] = [f for f in findings("인식율이 높다.") if f.rule == "SSJ-N03"]
        self.assertEqual((ryul.tier, ryul.action, ryul.fix), ("FIX", "request", "식률"))
        [roseo] = [f for f in findings("인간으로써 부끄럽다.") if f.rule == "SSJ-N06"]
        self.assertEqual(roseo.fix, "인간으로서")

    def test_a01_success_needs_a_reason_ending(self):
        self.assertTrue(D.request_fixed("SSJ-A01", "왜냐하면 처벌이 무서워서 안 할 수도 있기 때문이다."))
        self.assertFalse(D.request_fixed("SSJ-A01", "처벌이 무서워서 안 할 수도 있다."))
        self.assertTrue(D.request_fixed("SSJ-N03", "인식률이 높다."))
        self.assertFalse(D.request_fixed("SSJ-N03", "인식율이 높다."))

    def test_negative_polarity_and_jeonhyeo_exceptions(self):
        self.assertEqual(rules("그는 결코 포기하지 않는다. 전혀 다른 이야기다. 차마 말을 못 했다."), [])

    def test_inside_quotes_headings_and_code_nothing_fires(self):
        for source in ("그는 “할수 있다”고 말했다.", "# 할수 있는 일\n\n본문은 깨끗하다.", "`할수 있다`를 썼다.",
                       "> 왜냐하면 그렇다.", "| 항목 | 할수 있다 |\n| --- | --- |"):
            with self.subTest(source=source):
                self.assertEqual([f for f in findings(source) if f.tier != "LEAVE"], [])


class OwnerDecisions(unittest.TestCase):
    """OD 2, OD 3, OD 4 and lead decision 9.2a item 1."""

    def test_od3_errors_are_fixed_deterministically(self):
        cases = {"안 되요?": "안 돼요?", "잘 됬습니다.": "잘 됐습니다.", "몇일 동안 쉬었다.": "며칠 동안 쉬었다.",
                 "금새 끝났다.": "금세 끝났다.", "지금 할려면 늦는다.": "지금 하려면 늦는다.", "웬지 불안했다.": "왠지 불안했다."}
        for source, expected in cases.items():
            with self.subTest(source=source):
                found = [f for f in findings(source) if f.rule == "SSJ-N04"]
                self.assertTrue(found)
                self.assertTrue(all(f.tier == "FIX" and f.action == "deterministic" for f in found))
                self.assertEqual(fixed(source), expected)

    def test_od2_hal_kke_is_kept_unless_the_opt_in_is_on(self):
        source = "내일 연락할께요. 다 할꺼야."
        default = findings(source)
        self.assertTrue(default)
        self.assertTrue(all(f.rule == "SSJ-N04C" and (f.tier, f.action) == ("LEAVE", "report") for f in default))
        self.assertEqual(fixed(source), source)
        opt_in = findings(source, fix_colloquial=True)
        self.assertTrue(all((f.tier, f.action) == ("FIX", "deterministic") for f in opt_in if f.rule == "SSJ-N04C"))
        self.assertEqual(fixed(source, fix_colloquial=True), "내일 연락할게요. 다 할 거야.")

    def test_barae_is_suggest_and_spares_fading(self):
        [barae] = [f for f in findings("빨리 낫기를 바래요.") if f.rule == "CTA-BARAE"]
        self.assertEqual((barae.tier, barae.action), ("SUGGEST", "request"))
        self.assertEqual(rules("오래된 사진은 빛이 바래요."), [])

    def test_silge_is_report_only_and_never_changed(self):
        source = "이쪽으로 오실게요."
        found = findings(source, fix_colloquial=True)
        self.assertEqual([(f.rule, f.tier, f.action) for f in found], [("CTA-SILGE", "LEAVE", "report")])
        self.assertEqual(fixed(source, fix_colloquial=True), source)

    def test_cta_spacing(self):
        self.assertEqual(fixed("내용을 확인해주세요."), "내용을 확인해 주세요.")
        self.assertEqual(fixed("궁금하면 연락주세요."), "궁금하면 연락 주세요.")
        self.assertEqual(fixed("말해주세요."), "말해주세요.")       # two-syllable form may attach (제47항)

    def test_od4_no_fix_changes_the_voice_signature(self):
        signature = load_voice()
        fixtures = ["안 되요?", "잘 됬습니다.", "몇일 동안 쉬셨어요?", "금새 끝내셨네요.", "지금 할려면 늦습니다.",
                    "웬지 오실 것 같아요.", "할 거에요.", "이게 뭐에요?", "그건 아니예요.", "사실이 아니였다.",
                    "번번히 늦으셨지요.", "꼼꼼이 확인하십시오.", "이제 어떻해?", "오랫만에 뵙겠습니다.",
                    "참 희안한 일이네요.", "중요한 역활을 하십니다.", "갯수를 세어 주세요.", "윗층에 사십니다.",
                    "노력의 댓가를 받으셨습니다.", "인삿말을 드립니다.", "잘 받았읍니다.", "재고 없슴.",
                    "늦게 되서 죄송합니다.", "꼭 되야 합니다.", "품게 돼었습니다.", "발전돼면 안 됩니다.",
                    "하실수 있습니다.", "제가 할수 있어요.", "드릴수 있습니다.", "보실때 알려 주세요.",
                    "하는것이 좋겠습니다.", "하지않으셨습니다.", "할수밖에 없었어요.", "할 수 밖에 없습니다.",
                    "내용을 확인해주세요.", "언제든 연락주십시오.", "답변주시면 감사하겠습니다.", "확인해주실래요?",
                    "저희가 안내해주시기를 바랍니다.", "선생님께서 말씀해주시면 좋겠습니다.", "오실수 없으세요?"]
        for source in fixtures:
            after = fixed(source)
            with self.subTest(source=source):
                self.assertNotEqual(after, source)
                before_units = text.segment(source).units
                after_units = text.segment(after).units
                self.assertEqual(len(before_units), len(after_units))
                for a, b in zip(before_units, after_units):
                    self.assertEqual(signature(a.text), signature(b.text), (a.text, b.text))

    def test_od4_opt_in_colloquial_fix_keeps_level_mood_and_honorifics(self):
        signature = load_voice()
        for source in ("연락할께요.", "보내 드릴께요.", "제가 갈께요!", "미리 말할껄요."):
            after = fixed(source, fix_colloquial=True)
            with self.subTest(source=source):
                self.assertNotEqual(after, source)
                self.assertEqual(signature(source), signature(after))
        # Bare -ㄹ께/-ㄹ껄: the T2 regex reads the colloquial spelling as NOMINAL and the fixed one as HAE,
        # so only the honorific and humble parts are compared (the voice module must read 갈께 as HAE).
        for source in ("제가 갈께!", "미리 할껄."):
            a, b = signature(source), signature(fixed(source, fix_colloquial=True))
            with self.subTest(source=source):
                self.assertEqual((a[2], a[3], a[5]), (b[2], b[3], b[5]))
                self.assertEqual(b[0], "HAE")


class LightVerb(unittest.TestCase):
    """Light-verb nominalisation: SUGGEST in every genre, blog included (DESIGN 3.3, lead decision 2026-10-04)."""

    POSITIVE = [("소득이 있으면 인정이 됩니다.", "SSJ-LV2", "인정이 됩"),
                ("주말에도 진행이 가능하며 비용은 같습니다.", "SSJ-LV1", "진행이 가능하"),
                ("세탁하는 것이 가능합니다.", "SSJ-LV1", "세탁하는 것이 가능합"),
                ("서류 요청이 이루어질 예정입니다.", "SSJ-LV3", "요청이 이루어질"),
                ("매달 점검을 진행합니다.", "SSJ-LV4", "점검을 진행합"),
                ("주민을 대상으로 조사를 실시했다.", "SSJ-LV4", "조사를 실시했"),
                ("반려동물 동반이 가능해요.", "SSJ-LV1", "동반이 가능해")]

    def test_positives_in_every_genre(self):
        for genre in ("general", "blog", "essay", "report", "notice", "document"):
            for source, rule, span in self.POSITIVE:
                with self.subTest(genre=genre, source=source):
                    hits = [f for f in findings(source, genre) if f.rule == rule]
                    self.assertEqual([source[f.start:f.end] for f in hits], [span])
                    self.assertEqual((hits[0].tier, hits[0].action), ("SUGGEST", "request"))

    def test_counterexamples(self):
        for source in ("이 책은 큰 도움이 됩니다.", "그는 의사가 되었다.", "드디어 꿈이 이루어졌다.",
                       "주말에 행사를 진행합니다.", "그것이 가능합니까?", "좋은 기록이 되었다.",
                       "그는 “진행이 가능하다”고 말했다.", "제3조에 따라 양도가 가능하다.",
                       "약관에 따라 해지가 가능합니다.", "지금은 진행이 가능하지 않습니다.", "현금이 가능합니다.",
                       "물은 산소와 수소로 이루어져 있다."):
            with self.subTest(source=source):
                self.assertFalse([r for r in rules(source) if r in LIGHT_VERB])


class GenreGating(unittest.TestCase):
    def test_blog_keeps_boilerplate_and_importance_as_leave(self):
        source = "오늘은 세 가지를 살펴보겠습니다. 꾸준히 운동하는 것이 중요합니다."
        blog = {f.rule: f.tier for f in findings(source, "blog")}
        self.assertEqual(blog["BOILERPLATE_ANNOUNCE"], "LEAVE")
        self.assertEqual(blog["IMPORTANCE_FORMULA"], "LEAVE")
        essay = {f.rule: f.tier for f in findings(source, "essay")}
        self.assertEqual(essay["BOILERPLATE_ANNOUNCE"], "SUGGEST")
        self.assertEqual(essay["IMPORTANCE_FORMULA"], "SUGGEST")

    def test_general_requests_only_rules_valid_in_every_genre(self):
        source = ("결론적으로, 이를 통해 교육에 있어서는 신분증을 필요로 합니다. 학생을 소개시키다. "
                  "체계적인 접근으로 지속적인 개선을 위해 적극적으로 움직인다.")
        general = [f for f in findings(source, "general") if f.tier != "LEAVE"]
        self.assertEqual(general, [])
        report = {f.rule for f in findings(source, "report") if f.tier == "SUGGEST"}
        self.assertTrue({"CONCLUDING_SIGNPOST", "DEMONSTRATIVE_THROUGH", "PUBLIC_LANGUAGE_FRAME",
                         "TR-PILYO_RO", "TR-SIKIDA"} <= report)
        self.assertIn("JEOK_CLUSTER", {f.rule for f in findings(source, "essay") if f.tier == "SUGGEST"})

    def test_rule_tier_table(self):
        self.assertEqual(D.rule_tier("SSJ-N01", "blog"), ("FIX", "deterministic"))
        self.assertEqual(D.rule_tier("SSJ-N04C", "blog"), ("LEAVE", "report"))
        self.assertEqual(D.rule_tier("SSJ-N04C", "blog", fix_colloquial=True), ("FIX", "deterministic"))
        self.assertEqual(D.rule_tier("SSJ-A01", "notice"), ("FIX", "request"))
        self.assertEqual(D.rule_tier("CTA-SILGE", "essay", True), ("LEAVE", "report"))
        self.assertEqual(D.rule_tier("ENDING_MONOTONY", "essay"), ("LEAVE", "report"))
        self.assertEqual(D.rule_tier("TR-LIST_AND", "document"), ("SUGGEST", "request"))
        self.assertEqual(D.rule_tier("TR-LIST_AND", "blog"), ("LEAVE", "report"))
        for rule in LIGHT_VERB + ("CONNECTOR_RUN", "SSJ-A05", "CLR-LONG"):
            self.assertEqual(D.rule_tier(rule, "blog"), ("SUGGEST", "request"))
        self.assertTrue(D.RULES["CLR-LONG"].allow_split)

    def test_options_supply_genre_and_opt_in(self):
        source = "꾸준히 운동하는 것이 중요합니다. 연락할께요."
        doc = text.segment(source)
        options = Options(input_kind="direct-text", strength="medium", genre="essay", fix_colloquial=True)
        got = {f.rule: (f.tier, f.action) for f in D.diagnose(doc, options)}
        self.assertEqual(got["IMPORTANCE_FORMULA"], ("SUGGEST", "request"))
        self.assertEqual(got["SSJ-N04C"], ("FIX", "deterministic"))


class V1RulePort(unittest.TestCase):
    """Cases of tests/unit/super-sejong.test.ts, run in essay genre where the v1 rules are SUGGEST.
    Differences on purpose: every newline is a sentence boundary in v2 (no match across a soft wrap);
    ROLE_FORMULA is narrowed to adjective + 역할 (T3); DOUBLE_PASSIVE is the closed list SSJ-A04 and
    잊혀지다 is SSJ-A04S; ENDING_MONOTONY, INTENSIFIER_CLUSTER and CAPABILITY_HEDGE_CLUSTER are LEAVE."""

    def ids(self, source):
        return [f.rule for f in findings(source, "essay")]

    def texts(self, source):
        return [source[f.start:f.end] for f in findings(source, "essay")]

    def test_process_and_public_frame_keep_the_governing_word(self):
        self.assertEqual(self.texts("자료를 검토하는 과정에서 오류를 발견했다. 교육에 있어서는 기초가 중요하다."),
                         ["검토하는 과정에서", "교육에 있어서"])
        self.assertEqual(self.texts("정책을 결정함에 있어서 신중해야 한다."), ["결정함에 있어서"])
        self.assertEqual(self.texts("문제를 해결하는 데 있어서 시간이 걸렸다."), ["데 있어서"])
        self.assertEqual(self.texts("행정에 있어서의 원칙을 지킨다."), ["행정에 있어서"])
        for locative in ("나는 집에 있어서 나가지 않았다.", "열쇠가 서랍에 있어서 찾았다.", "회의실에 있어서 전화를 못 받았다."):
            self.assertNotIn("PUBLIC_LANGUAGE_FRAME", self.ids(locative))

    def test_code_quotes_and_blank_lines(self):
        source = "`검토하는 과정에서`와 “검토하는 과정에서”를 기록했다.\n```\n검토하는 과정에서\n```\n"
        self.assertEqual(self.ids(source), [])
        self.assertEqual(self.ids("자료를 검토하는\n\n과정에서 오류를 찾았다."), [])
        self.assertEqual(self.ids("자료를 검토하는\n과정에서 오류를 찾았다."), [])     # v2: a newline is a boundary

    def test_single_phrase_rules(self):
        self.assertEqual(self.ids("꾸준히 운동하는 것이 중요합니다."), ["IMPORTANCE_FORMULA"])
        self.assertIn("IMPORTANCE_FORMULA", self.ids("교육은 사회 발전에 중요한 역할을 합니다."))
        self.assertEqual(self.ids("이 문제는 중요하다. 중요한 것은 시간이다."), [])
        self.assertEqual(self.ids("이상입니다. 결론적으로, 우리는 계속해야 합니다."), ["CONCLUDING_SIGNPOST"])
        self.assertEqual(self.ids("그는 결론적으로 옳았다고 말했다."), [])
        self.assertEqual(self.texts("실험을 반복했다. 이를 통해 오차를 줄였다."), ["이를 통해"])
        self.assertEqual(self.ids("실험을 통해 오차를 줄였다."), [])
        self.assertEqual(self.ids("그 제도는 안전망 역할을 한다."), [])                 # narrowed (T3)
        self.assertEqual(self.ids("그 제도는 핵심적인 역할을 한다."), ["ROLE_FORMULA"])
        self.assertEqual(self.ids("그는 영화에서 주인공 역할을 맡았고 악역 역할을 하기도 했다."), [])
        self.assertEqual(self.ids("지금부터 세 가지를 살펴보겠습니다."), ["BOILERPLATE_ANNOUNCE"])
        self.assertEqual(self.ids("지금부터 어떻게 되는지 알아볼까요."), ["BOILERPLATE_ANNOUNCE"])
        self.assertEqual(self.ids("우리는 결과를 살펴보았다."), [])
        self.assertEqual(self.ids("“면밀히 살펴보겠다”고 말했다."), [])
        self.assertEqual(self.texts("이 조치가 차질로 이어질 것이다."), ["차질로 이어질"])

    def test_double_passive_closed_list(self):
        self.assertEqual(self.ids("연구가 많이 진행되어지고 있다."), ["SSJ-A04"])
        self.assertEqual(self.ids("이렇게 보여진다. 책에 쓰여진 글이다."), ["SSJ-A04", "SSJ-A04"])
        passive = lambda source: [r for r in self.ids(source) if r.startswith("SSJ-A04")]  # noqa: E731
        self.assertEqual(passive("합의가 이루어졌다. 제품이 만들어지는 과정이다. 지난 일이 잊혀졌다고 본다."), ["SSJ-A04S"])
        self.assertEqual(self.ids("돼지가 보인다. 이 이야기는 믿어지지 않는다."), [])

    def test_cluster_and_run_rules(self):
        self.assertEqual(self.ids("다양한 방법을 매우 효과적으로 적용한다."), ["INTENSIFIER_CLUSTER"])
        self.assertEqual(self.ids("다양한 방법을 적용한다."), [])
        far = "다양한 방법을 쓴다. " + "가" * 300 + " 매우 빠르다. " + "나" * 300 + " 효과적인 방법이다."
        self.assertEqual(self.ids(far), [])
        self.assertEqual(self.ids("조사를 통해 자료를 모으고 분석을 통해 결론을 냈다."), ["THROUGH_CLUSTER"])
        self.assertEqual(self.ids("조사를 통해 자료를 모았다."), [])
        self.assertEqual(self.ids("조사를 했다. 이를 통해 알았고 이를 통해 확인했다."),
                         ["DEMONSTRATIVE_THROUGH", "DEMONSTRATIVE_THROUGH"])
        self.assertIn("JEOK_CLUSTER", self.ids("체계적인 접근으로 지속적인 개선을 위해 적극적으로 움직인다."))
        self.assertEqual(self.ids("이 목적은 성적 향상이며 실적이 면적과 무관하다."), [])
        self.assertIn("CAPABILITY_HEDGE_CLUSTER", self.ids("쓸 수 있다. 볼 수 있다. 갈 수 있다. 할 수 있다."))
        self.assertEqual(self.ids("쓸 수 있다. 볼 수 있다."), [])
        self.assertEqual(self.texts("비용이 늘었다. 또한 기간도 길어졌다. 따라서 계획을 바꾼다."), ["따라서"])
        self.assertEqual(self.ids("비용이 늘었다. 또한 기간도 길어졌다. 계획을 바꾼다. 그래서 끝냈다."), [])
        self.assertEqual(self.ids("따라서 비용이 늘었다.\n\n따라서 기간도 길어졌다."), [])

    def test_ending_monotony_on_the_fifth_identical_ending(self):
        run = lambda n: " ".join(f"{i + 1}번째 일이 있습니다." for i in range(n))  # noqa: E731
        self.assertEqual(self.ids(run(4)), [])
        self.assertEqual(self.texts(run(5)), ["있습니다."])
        self.assertEqual(self.ids(run(3) + "\n\n" + run(3)), [])
        self.assertEqual([f.tier for f in findings(run(5), "essay")], ["LEAVE"])

    def test_protected_ranges(self):
        frame = "자료를 검토하는 과정에서 오류를 찾았다."
        self.assertEqual(self.ids('그는 “그가 ‘자료를 검토하는 과정에서’ 쓴 말”이라 했다.'), [])
        self.assertEqual(self.ids(f"Korea's economy isn't simple. {frame} It's fine."), ["PROCESS_NOMINALIZATION"])
        self.assertEqual(self.ids(f"| 항목 | 설명 |\n| --- | --- |\n| {frame} | 값 |"), [])
        self.assertEqual(self.ids("[문서](https://example.com/검토하는-과정에서) 참고"), [])
        self.assertEqual(self.ids(f"문단이다.\n\n    {frame}\n\n본문 끝."), [])
        self.assertEqual(self.ids(f"# {frame}\n\n> {frame}"), [])
        self.assertEqual(self.ids(f"- {frame}\n1. {frame}"), ["PROCESS_NOMINALIZATION"] * 2)

    def test_offsets_are_code_points_into_the_chunk(self):
        chunk = "자료를 검토하는 과정에서 오류가 났다."
        doc = "😀 머리말입니다.\n\n" + chunk
        [a] = findings(chunk, "essay")
        [b] = findings(doc, "essay")
        self.assertEqual(chunk[a.start:a.end], "검토하는 과정에서")
        self.assertEqual(doc[b.start:b.end], "검토하는 과정에서")
        self.assertEqual(b.start - a.start, len(doc) - len(chunk))

    def test_ordinary_prose_stays_clean(self):
        source = ("어제 비가 와서 우산을 챙겼다. 버스를 기다리는 동안 친구에게서 전화가 왔다. 점심은 국수로 했고, "
                  "오후에는 도서관에서 책을 빌렸다. 저녁이 되자 바람이 잦아들었다.")
        for genre in ("general", "blog", "essay"):
            self.assertEqual(findings(source, genre), [])


class NormLayer(unittest.TestCase):
    def test_apply_fixes_is_idempotent_on_every_fixture_and_seed_text(self):
        sources = ["할수있다. 하는것 같다. 하지않고 할때 몇일 되요 됬다 확인해주세요 연락주세요 할수 밖에 없다.",
                   "몇 일째 금새 웬지 왠일 번번히 꼼꼼이 갯수 윗층 머릿말 있었읍니다 없슴."]
        sources += [row["text"] for row in seed_rows()]
        for source in sources:
            for opt_in in (False, True):
                once = fixed(source, opt_in)
                with self.subTest(source=source[:40], opt_in=opt_in):
                    self.assertEqual(fixed(once, opt_in), once)

    def test_fixes_skip_protected_spans_and_overlaps(self):
        source = "할수 있다."
        found = findings(source)
        self.assertEqual([(f.rule, f.fix) for f in found], [("SSJ-N01", " 수")])
        frozen = [Span(kind="quote", start=0, end=len(source), policy="freeze")]
        self.assertEqual(norms.apply_fixes(source, found, frozen), (source, []))
        keep = [Span(kind="cmc", start=1, end=2, policy="keep-token")]
        self.assertEqual(norms.apply_fixes(source, found, keep), (source, []))
        twice = found + [Finding(id="F9", rule="SSJ-N04", tier="FIX", action="deterministic", sentence="S1",
                                 start=1, end=3, fix="X")]
        self.assertEqual(norms.apply_fixes(source, twice, []), ("할 수 있다.", ["SSJ-N01"]))
        request = [Finding(id="F1", rule="SSJ-N03", tier="FIX", action="request", sentence="S1", start=0, end=1,
                           fix="Y")]
        self.assertEqual(norms.apply_fixes(source, request, []), (source, []))

    def test_deterministic_findings_never_have_an_empty_before(self):
        source = "할수있다 하는것 할때 하지않아 확인해주세요 연락주세요 할 수 밖에 없다 몇일 되요 번번히"
        for f in findings(source):
            if f.action == "deterministic":
                self.assertGreater(f.end, f.start)
                self.assertIsNotNone(f.fix)

    def test_findings_validate_against_the_plan_schema(self):
        schema = io.load_schema("plan")
        source = ("제 생각은 미디어를 제한해야 한다고 생각합니다. 왜냐하면 악플이 많습니다. 학교에서 미리 예방하는것이 "
                  "중요합니다. 인식율은 85%였습니다. 몇일 동안 되요? 확인해주세요. 연락할께요. 진행이 가능하며 인정이 됩니다.")
        found = findings(source, "essay")
        self.assertGreaterEqual(len(found), 10)
        for f in found:
            self.assertEqual(io.validate(f.to_json(), schema["$defs"]["finding"], schema), [])
        self.assertEqual([f.id for f in found], [f"F{i + 1}" for i in range(len(found))])

    def test_wp0_plan_fixture_findings(self):
        source = ("오늘은 세미나 후기를 정리합니다. 왜냐하면 일정이 바뀌었습니다. 참가비는 3만 원이 됬습니다.\n\n"
                  "현장 분위기가 좋았어요😀 ㅎㅎ 궁금한 점이 있으시면 댓글로 문의해 주세요.\n")
        got = [(f.rule, f.tier, f.action, f.sentence) for f in findings(source, "blog")]
        self.assertEqual(got, [("SSJ-A01", "FIX", "request", "S2"), ("SSJ-N04", "FIX", "deterministic", "S3")])
        n04 = findings(source, "blog")[1]
        self.assertEqual((n04.start, n04.end, source[n04.start:n04.end], n04.fix), (47, 48, "됬", "됐"))
        self.assertEqual(findings("회의는 오전 10시에 시작합니다. 자료는 미리 읽어 오세요.\n", "blog"), [])


class Introduced(unittest.TestCase):
    def test_a_new_ryul_error_is_flagged(self):
        got = norms.introduced("인식률은 85%였다.", "인식율은 85%였다.", sentence="S3")
        self.assertEqual([(v.code, v.family, v.severity, v.detail, v.sentence) for v in got],
                         [("norm_introduced", "norms", "hard", "SSJ-N03", "S3")])

    def test_nothing_on_an_unchanged_or_fixed_source(self):
        source = "인식율은 85%였다. 할수 있다. 연구가 진행되어지고 있다."
        self.assertEqual(norms.introduced(source, source), [])
        self.assertEqual(norms.introduced(source, source.replace("85%였다", "85%이다")), [])
        self.assertEqual(norms.introduced(source, fixed(source)), [])
        self.assertEqual(norms.introduced(source, "인식률은 85%였다. 할 수 있다. 연구가 진행되고 있다."), [])

    def test_trading_one_error_for_another_still_counts(self):
        got = norms.introduced("인식율이 높다.", "성장율이 높다.")
        self.assertEqual([v.detail for v in got], ["SSJ-N03"])

    def test_tells_are_soft(self):
        got = norms.introduced("운동은 좋다.", "꾸준히 운동하는 것이 중요하였다.")
        self.assertEqual({(v.code, v.severity) for v in got}, {("tell_introduced", "soft")})
        self.assertEqual({v.detail for v in got}, {"IMPORTANCE_FORMULA", "HAYEOT"})
        self.assertTrue(all(re.fullmatch(r"[a-z_]{1,60}", v.code) for v in got))

    def test_errors_inside_a_new_quote_are_not_the_writers(self):
        self.assertEqual(norms.introduced("그가 말했다.", "그가 “인식율이 높다”고 말했다."), [])


class SeedAcceptance(unittest.TestCase):
    """WP-8 acceptance: 0 FIX findings and 0 SUGGEST requests (light-verb hits reported apart) on the 49
    natural controls of the seed benchmark, in their own genre and in general, blog and essay."""

    def test_natural_controls(self):
        controls = [row for row in seed_rows() if row["item_type"] == "natural_control"]
        self.assertEqual(len(controls), 49)
        for mode in ("own", "general", "blog", "essay"):
            for row in controls:
                genre = SEED_GENRE.get(row["genre"], row["genre"]) if mode == "own" else mode
                got = [f for f in findings(row["text"], genre) if f.tier != "LEAVE" and f.rule not in LIGHT_VERB]
                with self.subTest(mode=mode, item=row["id"]):
                    self.assertEqual([(f.rule, row["text"][f.start:f.end]) for f in got], [])

    def test_quote_protected_and_colloquial_controls_stay_untouched(self):
        for row in seed_rows():
            if row["item_type"] == "natural_control":
                with self.subTest(item=row["id"]):
                    self.assertEqual(fixed(row["text"]), row["text"])


class Performance(unittest.TestCase):
    SHAPES = {
        "unmatched hangul": "가",
        "llm text": "결론적으로, 다양한 방법을 통해 효과적인 결과를 얻는 것이 중요합니다. 이를 통해 연구가 진행되어지고 있습니다. "
                    "또한 체계적인 접근을 할 수 있습니다. 진행이 가능하며 인정이 됩니다. ",
        "quote openers": "\"가 ", "curly openers": "“가 ‘나 ", "one-char sentences": "가. ",
        "soft wraps": "자료를 검토하는\n", "many jeok words": "체계적인 ", "table rows": "| 가 | 나 |\n",
        "norm errors": "할수있다 하는것 몇일 되요 확인해주세요 ", "numbered list": "1. 다양한 효과적인 매우 방법\n",
        "one long sentence": "그리고 가는 것이 가능하며 ",
    }

    def test_linear_time_on_10k_and_100k(self):
        for name, unit in self.SHAPES.items():
            timings = []
            for size in (10_000, 100_000):
                source = (unit * (size // len(unit) + 1))[:size]
                started = time.perf_counter()
                found = findings(source, "essay")
                fixed(source)
                timings.append(time.perf_counter() - started)
                self.assertIsInstance(found, list)
            with self.subTest(shape=name):
                self.assertLess(timings[1], 6.0)                    # diagnose + fix_text, 100k chars
                self.assertLess(timings[1], max(15 * timings[0], 0.5))


class JosaReexport(unittest.TestCase):
    def test_v2_module_reexports_the_legacy_implementation(self):
        for name in ("check", "gate", "repair", "Lexicon", "Finding", "syl_class", "_decide", "main", "FAMILIES"):
            self.assertIs(getattr(josa, name), getattr(super_sejong_josa, name))
        self.assertEqual(josa.gate("URL을 확인했다.", "URL를 확인했다.")[0].expected, "을")

    def test_package_import_path_works_too(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import sejong.josa as j, super_sejong_josa as s; "
                "print(j.gate is s.gate)")
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(ROOT / "engine_runtime")],
                                capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "True", result.stderr)


if __name__ == "__main__":
    unittest.main()
