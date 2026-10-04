"""WP-8b calque requests: TR-GAJIDA, TR-JUNGE_ITDA, TR-DAEHAE, TR-ROBUTEO (SUGGEST in every genre).

Every text here is constructed for the test; no owner text and no corpus text. Precision and hit rates
come from the WP-8b hand-check (one LLM annotator) and are quoted in diagnose.py, not re-measured here.
"""
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine_runtime.sejong import diagnose as D  # noqa: E402
from engine_runtime.sejong import meaning as M  # noqa: E402
from engine_runtime.sejong import text  # noqa: E402

SEED = ROOT / "docs" / "research" / "super-sejong" / "v2" / "benchmark" / "seed_benchmark.jsonl"
NEW = ("TR-GAJIDA", "TR-JUNGE_ITDA", "TR-DAEHAE", "TR-ROBUTEO")
GENRES = ("general", "blog", "essay", "report", "notice", "document")


def found(source, genre="general"):
    return [(f.rule, source[f.start:f.end], f.tier, f.action)
            for f in D.diagnose(text.segment(source), genre=genre) if f.rule in NEW]


class Positives(unittest.TestCase):
    # (source, rule, span): the lead's run plus one case per form; the span never overlaps the noun's
    # eojeol except for 으로부터, which is written inside it
    CASES = [
        ("이 집은 넓은 공간을 가지고 있어서 가족이 지내기 좋습니다.", "TR-GAJIDA", "가지고 있"),
        ("이 앱은 다양한 기능을 가진 앱입니다.", "TR-GAJIDA", "가진"),
        ("이 제품은 세 가지 장점을 갖고 있어요.", "TR-GAJIDA", "갖고 있"),
        ("이 결정은 큰 의미를 갖습니다.", "TR-GAJIDA", "갖습니"),
        ("두 방식은 공통점을 많이 가지고 있다.", "TR-GAJIDA", "가지고 있"),
        ("현재 배송 준비중에 있습니다.", "TR-JUNGE_ITDA", "있습니"),
        ("해당 사안은 검토 중에 있으며 결과는 추후 안내드리겠습니다.", "TR-JUNGE_ITDA", "중에 있으며"),
        ("시는 새 청사 건립을 추진 중에 있다.", "TR-JUNGE_ITDA", "중에 있다"),
        ("주문 건에 대해서 안내드립니다.", "TR-DAEHAE", "대해서"),
        ("변경된 일정에 대해 자세히 설명드리겠습니다.", "TR-DAEHAE", "대해"),
        ("위원회는 예산안에 대해 논의를 했다.", "TR-DAEHAE", "대해"),
        ("이 글에서는 새 제도에 대하여 소개합니다.", "TR-DAEHAE", "대하여"),
        ("어제 고객으로부터 문의를 받았습니다.", "TR-ROBUTEO", "으로부터"),
        ("친구로부터 그 소식을 들었어요.", "TR-ROBUTEO", "로부터"),
        ("직원들로부터 건의 사항을 전달받았다.", "TR-ROBUTEO", "로부터"),
    ]

    def test_every_genre_gets_a_suggest_request(self):
        for genre in GENRES:
            for source, rule, span in self.CASES:
                with self.subTest(genre=genre, source=source):
                    self.assertEqual(found(source, genre), [(rule, span, "SUGGEST", "request")])
                    self.assertEqual(D.rule_tier(rule, genre), ("SUGGEST", "request"))

    def test_guides_exist_and_name_the_repair(self):
        for rule, needle in (("TR-GAJIDA", "N이 있다"), ("TR-JUNGE_ITDA", "N 중이다"), ("TR-DAEHAE", "N을 안내"),
                             ("TR-ROBUTEO", "N에게서")):
            self.assertIn(needle, D.guide(rule))


class Counterexamples(unittest.TestCase):
    def test_natural_collocations_instrument_negation_legal_and_quotes(self):
        for source in ("나는 그 문제에 관심을 가지고 있다.", "우리는 잠시 쉬는 시간을 가졌다.", "자신감을 갖고 도전하세요.",
                       "좋은 기회를 가졌다.", "책임감을 가지고 일한다.", "이 기능을 가지고 무엇을 할 수 있을까요?",
                       "그는 그 권한을 가지고 있지 않다.", "제3조에 따라 이사는 의결 권한을 가진다.",
                       "그는 \"이 제품은 다양한 기능을 가지고 있다\"고 말했다.",
                       "'전하다'라는 의미를 가진 단어입니다.", "회원님들께서 많은 관심을 가져 주셨습니다."):
            with self.subTest(source=source):
                self.assertEqual(found(source), [])

    def test_jung_e_itda_needs_a_verbal_noun_and_a_predicate(self):
        for source in ("회의 중에 있었던 일을 정리했다.", "학생들 중에 있는 친구를 찾았다.", "이 중에 있습니다.",
                       "부장님은 지금 회의 중에 계십니다.", "준비물 중에 있어요.", "공사 중에 있는 건물이다."):
            with self.subTest(source=source):
                self.assertEqual(found(source), [])

    def test_daehae_keeps_an_existing_object_persons_talk_verbs_and_topics(self):
        for source in ("그에 대해 설명했다.", "저에 대해 소개하겠습니다.", "질문에 대해 답변드립니다.",
                       "그 영화에 대해 이야기했다.", "폭력에 대해 교육해야 합니다.", "그 일에 대해서는 설명을 드리기 어렵습니다.",
                       "원리에 대해 자세한 내용을 설명했다.", "그 결정에 대해 설명을 들었다.",
                       "제5조에 대하여 검토한다."):
            with self.subTest(source=source):
                self.assertEqual(found(source), [])

    def test_robuteo_needs_a_person_giver(self):
        for source in ("부모로부터 독립했다.", "위협으로부터 시민을 보호한다.", "부모님으로부터 용돈을 받았다.",
                       "세무서로부터 안내문을 받았다.", "회사로부터 연락이 왔어요.", "그날로부터 사흘이 지났다.",
                       "친구로부터 시작된 소문이다.", "고객으로부터 멀어지는 서비스다."):
            with self.subTest(source=source):
                self.assertEqual(found(source), [])


class Repairs(unittest.TestCase):
    """The canonical repair of each rule: the detector stops firing and the meaning family (including the
    content_dropped and key_word_dropped soft codes) stays silent."""

    PAIRS = [
        ("이 집은 넓은 공간을 가지고 있어서 가족이 지내기 좋습니다.", "이 집은 공간이 넓어서 가족이 지내기 좋습니다.", "TR-GAJIDA"),
        ("이 앱은 다양한 기능을 가진 앱입니다.", "이 앱은 기능이 다양한 앱입니다.", "TR-GAJIDA"),
        ("이 제품은 세 가지 장점을 갖고 있어요.", "이 제품은 장점이 세 가지 있어요.", "TR-GAJIDA"),
        ("관리자만 삭제 권한을 가지고 있습니다.", "관리자만 삭제 권한이 있습니다.", "TR-GAJIDA"),
        ("현재 배송 준비중에 있습니다.", "현재 배송 준비 중입니다.", "TR-JUNGE_ITDA"),
        ("현재 배송 준비중에 있습니다.", "현재 배송을 준비하고 있습니다.", "TR-JUNGE_ITDA"),
        ("해당 사안은 검토 중에 있으며 결과는 추후 안내드리겠습니다.", "해당 사안은 검토 중이며 결과는 추후 안내드리겠습니다.",
         "TR-JUNGE_ITDA"),
        ("주문 건에 대해서 안내드립니다.", "주문 건을 안내드립니다.", "TR-DAEHAE"),
        ("변경된 일정에 대해 자세히 설명드리겠습니다.", "변경된 일정을 자세히 설명드리겠습니다.", "TR-DAEHAE"),
        ("위원회는 예산안에 대해 논의했다.", "위원회는 예산안을 논의했다.", "TR-DAEHAE"),
        ("어제 고객으로부터 문의를 받았습니다.", "어제 고객에게서 문의를 받았습니다.", "TR-ROBUTEO"),
        ("친구로부터 그 소식을 들었어요.", "친구한테서 그 소식을 들었어요.", "TR-ROBUTEO"),
    ]

    def test_repairs_are_fixed_and_meaning_neutral(self):
        for source, repair, rule in self.PAIRS:
            with self.subTest(source=source, repair=repair):
                self.assertTrue(D.rule_fires(rule, source))
                self.assertTrue(D.request_fixed(rule, repair))
                self.assertEqual(M.findings(source, repair), [])

    def test_repairs_pass_the_whole_pipeline_in_one_call(self):
        import test_sejong_pipeline as TP
        for source, repair, rule in self.PAIRS:
            for genre in ("general", "blog"):
                with self.subTest(source=source, genre=genre):
                    plan = TP.plan_for(source, genre=genre)
                    self.assertIn(rule, {r for request in plan.requests for r in request.rules})
                    _first, outcome, calls = TP.run_writer(plan, source, repair)
                    self.assertEqual((outcome.text.strip(), outcome.report.policy, calls), (repair, "accept", 1))

    def test_spans_do_not_license_dropping_the_noun(self):
        # A writer that deletes the noun instead of rewording the frame is still a content drop.
        for source, candidate in (("이 앱은 다양한 기능을 가지고 있습니다.", "이 앱은 다양합니다."),
                                  ("주문 건에 대해서 안내드립니다.", "안내드립니다."),
                                  ("현재 배송 준비중에 있습니다.", "현재 배송 중입니다.")):
            with self.subTest(source=source):
                self.assertIn("content_dropped", [code for code, _detail, _keep in M.findings(source, candidate)])


class Seed(unittest.TestCase):
    def test_no_new_request_on_any_seed_record(self):
        rows = [json.loads(line) for line in SEED.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(rows), 206)
        for row in rows:
            for genre in ("general", "blog", "essay"):
                with self.subTest(item=row["id"], genre=genre):
                    self.assertEqual(found(row["text"], genre), [])


class Performance(unittest.TestCase):
    SHAPES = ("공간을 가지고 있", "기능을 가진 ", "준비중에 있", "진행 중에 ", "건에 대해서 안내", "에 대해 ",
              "고객으로부터 ", "고객으로부터", "의미를 갖는다는 라는 의미를 가진 ", "가")

    def test_linear_time_on_10k_and_100k(self):
        for unit in self.SHAPES:
            timings = []
            for size in (10_000, 100_000):
                source = (unit * (size // len(unit) + 1))[:size]
                started = time.perf_counter()
                D.diagnose(text.segment(source), genre="general")
                timings.append(time.perf_counter() - started)
            with self.subTest(shape=unit):
                self.assertLess(timings[1], 6.0)
                self.assertLess(timings[1], max(15 * timings[0], 0.5))


if __name__ == "__main__":
    unittest.main()
