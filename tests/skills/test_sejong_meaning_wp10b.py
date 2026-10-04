"""Super Sejong Engine v2 meaning hardening (WP-10b): content_dropped, condition_dropped, temporal_order_changed,
participant roles per clause, the tense-aware progressive rule and the 안 + 되다 comparison spacing.

Every sentence here is constructed for the test; the seed benchmark and the 555 pairs are project-authored.
"""
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine_runtime"))
from sejong import config, meaning  # noqa: E402
from sejong import text as T  # noqa: E402
from sejong import verify as VF  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
BENCH = ROOT / "docs" / "research" / "super-sejong" / "v2" / "benchmark"
FLAGS = config.Flags.from_env({})
NEW = {"content_dropped", "condition_dropped", "temporal_order_changed"}

# Pure deletions of content words (and two name substitutions): content_dropped (or condition_dropped) must fire.
DROPS = [
    ("모임 장소는 시립도서관 3층 세미나실이고, 이번에 함께 읽을 책은 미리 공지된 대로 진행이 이루어질 예정입니다.",
     "모임 장소는 시립도서관 3층 세미나실이며, 이번에 읽을 책은 공지된 대로 진행합니다."),
    ("회의는 다음 주 화요일 오후에 본관 대회의실에서 열립니다.", "회의는 다음 주에 대회의실에서 열립니다."),
    ("신청서는 반드시 본인이 직접 작성해야 합니다.", "신청서는 반드시 작성해야 합니다."),
    ("이번 행사는 지역 주민과 함께 준비했습니다.", "이번 행사를 준비했습니다."),
    ("자세한 일정은 추후 홈페이지에 공지할 예정입니다.", "자세한 일정은 공지하겠습니다."),
    ("주차장은 협소하니 가급적 대중교통을 이용해 주세요.", "대중교통을 이용해 주세요."),
    ("모든 참가자에게 소정의 기념품을 무료로 드립니다.", "참가자에게 기념품을 드립니다."),
    ("처리 결과는 문자 메시지로 개별 안내해 드립니다.", "처리 결과를 안내해 드립니다."),
    ("아이와 함께 미리 연습해 보시면 좋습니다.", "연습해 보시면 좋습니다."),
    ("오늘은 날씨가 맑고 바람도 선선했어요.", "오늘은 날씨가 맑았어요."),
    ("새로 산 운동화가 생각보다 훨씬 편했어요.", "운동화가 편했어요."),
    ("서류는 오늘 중으로 꼭 제출해 주세요.", "서류는 꼭 제출해 주세요."),
    ("회원 가입은 무료이며 누구나 할 수 있습니다.", "회원 가입은 누구나 할 수 있습니다."),
    ("회원이면 무료로 이용할 수 있어요.", "무료로 이용할 수 있어요."),
    ("서울시청 앞에서 만나요.", "부산시청 앞에서 만나요."),
    ("10월 18일 토요일에 만나요.", "10월 18일 일요일에 만나요."),
    ("강남역 2번 출구에서 기다리겠습니다.", "역삼역 2번 출구에서 기다리겠습니다."),
    ("시립도서관 2층 열람실은 평일에만 엽니다.", "도서관 열람실은 엽니다."),
    ("택배는 경비실에 맡겨 주세요.", "택배는 맡겨 주세요."),
]
# Accepted miss, kept visible: 동시에 reads as verb-like (시 is an ending syllable), and its stem 도 occurs.
KNOWN_MISSES = [("강의는 온라인으로도 동시에 진행됩니다.", "강의는 온라인으로도 진행됩니다.")]
# Licensed fixes, inflection, spacing, synonyms, honorific suppletion, conditions said another way.
KEEPS = [
    ("모임은 진행이 이루어질 예정입니다.", "모임은 진행될 예정입니다."),
    ("매주 금요일에 점검을 진행합니다.", "매주 금요일에 점검합니다."),
    ("현장 접수도 가능합니다.", "현장에서도 접수할 수 있습니다."),
    ("감기는 미리 예방하는 것이 중요합니다.", "감기는 예방하는 것이 중요합니다."),
    ("함께 첨부한 파일을 확인해 주세요.", "첨부한 파일을 확인해 주세요."),
    ("약 200명 정도가 참석했습니다.", "약 200명이 참석했습니다."),
    ("이번 주에 함께 읽을 책입니다.", "이번 주에 같이 읽을 책입니다."),
    ("자료를 꼼꼼하게 검토했습니다.", "자료를 꼼꼼히 검토하였습니다."),
    ("시립 도서관에서 만납니다.", "시립도서관에서 만납니다."),
    ("할머니가 저녁을 먹었다.", "할머니께서 저녁을 드셨다."),
    ("왜냐하면 비가 왔습니다.", "비가 왔기 때문입니다."),
    ("도와주어서 고마웠어요.", "도와줘서 고마웠어요."),
    ("매일 운동하고 있어요.", "매일 운동을 하고 있어요."),
    ("회의가 끝난 뒤에 연락드리겠습니다.", "회의가 끝난 후에 연락드리겠습니다."),
    ("그 일은 어려웠다.", "그 일은 쉽지 않았다."),
    ("이 제품은 사용자에게 편리함을 제공하는 역할을 하고 있습니다.", "이 제품은 사용자에게 편리함을 줍니다."),
    ("저희 매장은 오전 10시부터 오후 9시까지 영업을 진행하고 있습니다.", "저희 매장은 오전 10시부터 오후 9시까지 영업합니다."),
    ("회원이면 무료로 이용할 수 있어요.", "회원은 무료로 이용할 수 있어요."),
    ("회원이면 무료로 이용할 수 있어요.", "회원인 경우 무료로 이용할 수 있어요."),
    ("시험 결과를 선택할 수 있다.", "시험 결과를 택할 수 있다."),
    ("이용자 수가 늘었다.", "사용자 수가 늘었다."),
    ("그는 질문에 대답하지 않았다.", "그는 질문에 답하지 않았다."),
    ("이 서류는 본인이 직접 제출하지 않으면 접수되지 않습니다.", "이 서류는 본인이 직접 내야 접수됩니다."),
]


def codes(source, candidate):
    return {code for code, _detail in meaning.codes(source, candidate)}


def gate(source, candidate):
    return VF.verify_document(source, candidate, flags=FLAGS)


class ContentDropped(unittest.TestCase):
    def test_lead_repro_names_the_dropped_words(self):
        source, candidate = DROPS[0]
        found = [v for v in meaning.compare(source, candidate) if v.code == "content_dropped"]
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].family, found[0].severity, found[0].detail, found[0].keep),
                         ("meaning", "soft", "3", "함께, 미리, 예정"))

    def test_constructed_drops_are_detected(self):
        for source, candidate in DROPS:
            with self.subTest(source=source):
                self.assertTrue(codes(source, candidate) & {"content_dropped", "condition_dropped"})
        for source, candidate in KNOWN_MISSES:
            self.assertFalse(codes(source, candidate) & NEW)

    def test_licensed_and_paraphrased_edits_pass(self):
        for source, candidate in KEEPS:
            with self.subTest(source=source, candidate=candidate):
                self.assertFalse(codes(source, candidate) & NEW, meaning.findings(source, candidate))

    def test_redundancy_licence_is_the_list_only(self):
        # 미리 예방 is in data/redundancy.json; 미리 공지 is not, so dropping 미리 there is a drop.
        self.assertNotIn("content_dropped", codes("미리 예방합니다.", "예방합니다."))
        self.assertIn("content_dropped", codes("미리 공지된 대로 합니다.", "공지된 대로 합니다."))

    def test_shadow_until_promoted(self):
        source, candidate = DROPS[0]
        result = gate(source, candidate)
        self.assertEqual((result["gate"]["exit_code"], result["hardFailures"]), (0, []))
        self.assertIn("content_dropped", result["shadowFailures"])
        self.assertIn("content_dropped", config.SHADOW_CODES)
        enforced, shadow = VF.classify(FLAGS, meaning.compare(source, candidate))
        self.assertEqual(([v.code for v in enforced], [v.code for v in shadow]), ([], ["content_dropped"]))

    def test_identical_and_deterministic_fixes_are_clean(self):
        for text in ("그날 뵈요!", "안 되요?", "할수 있습니다.", "가격이 좀 비싼 편이였어."):
            self.assertEqual(meaning.codes(text, text), [])


class ConditionDropped(unittest.TestCase):
    def test_condition_clause_dropped_is_hard(self):
        found = meaning.compare("회원이면 무료로 이용할 수 있어요.", "무료로 이용할 수 있어요.")
        self.assertIn(("condition_dropped", "hard", "COND:1->0", "회원"),
                      [(v.code, v.severity, v.detail, v.keep) for v in found])
        self.assertEqual(gate("회원이면 무료로 이용할 수 있어요.", "무료로 이용할 수 있어요.")["hardFailures"],
                         ["condition_dropped"])

    def test_prohibition_and_nouns_in_myeon_are_not_conditions(self):
        self.assertEqual(meaning._conditions("여기서 담배를 피우면 안 된다."), [])
        self.assertEqual(meaning._conditions("비용을 줄이지 않으면 안 됩니다."), [])
        self.assertEqual(meaning._conditions("반면 화면은 작다."), [])
        self.assertEqual(len(meaning._conditions("늦으면 연락 주세요.")), 1)


class TemporalOrder(unittest.TestCase):
    def test_flips(self):
        for source, candidate in (("비가 그치기 전에는 떠나지 않겠다고 그는 말했다.", "비가 그친 뒤에는 떠나지 않겠다고 그는 말했다."),
                                  ("출발 전에 연락 주세요.", "출발 후에 연락 주세요."),
                                  ("먼저 서류를 확인하세요.", "나중에 서류를 확인하세요."),
                                  ("이전 버전에서는 지원하지 않습니다.", "이후 버전에서는 지원하지 않습니다."),
                                  ("앞서 말씀드린 내용입니다.", "뒤이어 말씀드린 내용입니다.")):
            with self.subTest(source=source):
                self.assertTrue(codes(source, candidate) & {"temporal_order_changed", "lexical_polarity_changed"})
        # v1 _order_swapped needs "전에" + space; "전에는" was the T20 miss and is the new code's alone
        self.assertEqual(meaning.codes("출발 전에는 연락 주세요.", "출발 후에는 연락 주세요."),
                         [("temporal_order_changed", "BEFORE->AFTER")])

    def test_same_direction_is_neutral(self):
        for source, candidate in (("3일 전에 신청하세요.", "3일 이전에 신청하세요."),
                                  ("끝난 다음에 정리합니다.", "끝난 뒤에 정리합니다."),
                                  ("출발하기 전에 확인하세요.", "출발에 앞서 확인하세요."),
                                  ("서류는 접수 전에 공증을 받아야 하고, 접수한 뒤에는 수정할 수 없어요.",
                                   "접수하기 전에 공증을 먼저 받아야 하고, 접수 후에는 고칠 수 없어요."),
                                  ("비가 그치기 전에는 떠나지 않겠다고 그는 말했다.", "그는 비가 그칠 때까지 떠나지 않겠다고 말했다."),
                                  ("전국 전체 일정은 전혀 바뀌지 않았다.", "전국 전체 일정은 전혀 바뀌지 않았다.")):
            with self.subTest(source=source):
                self.assertNotIn("temporal_order_changed", codes(source, candidate))

    def test_counts(self):
        self.assertEqual(meaning.temporal("식사하기 전에 손을 씻고, 식사한 뒤에 양치한다."), (1, 1))
        self.assertEqual(meaning.temporal("전국 전체 전문가가 전혀 모른다."), (0, 0))


class ClauseRoles(unittest.TestCase):
    def test_swap_across_two_clauses(self):
        source = "시청은 업체에 계약 해지를 통보했고, 업체는 이에 반발하여 소송을 제기했습니다."
        self.assertIn(("participant_role_changed", "clause_roles"),
                      meaning.codes(source, "업체는 시청에 계약 해지를 통보했고, 시청은 이에 반발하여 소송을 제기했습니다."))
        self.assertEqual(meaning.codes(source, "시청이 업체에 계약 해지를 알리자 업체는 반발하며 소송을 냈습니다."), [])
        self.assertIn("participant_role_changed",
                      codes("회사는 직원들에게 보너스를 지급했고, 직원들은 감사 인사를 전했다.",
                            "직원들은 회사에 보너스를 지급했고, 회사는 감사 인사를 전했다."))


class AspectAndSpacing(unittest.TestCase):
    def test_progressive_to_simple_non_past_is_neutral(self):
        for source, candidate in (("이 제품은 사용자에게 편리함을 제공하는 역할을 하고 있습니다.", "이 제품은 사용자에게 편리함을 줍니다."),
                                  ("저희 매장은 오전 10시부터 오후 9시까지 영업을 진행하고 있습니다.",
                                   "저희 매장은 오전 10시부터 오후 9시까지 영업합니다.")):
            with self.subTest(source=source):
                result = gate(source, candidate)
                self.assertEqual((result["gate"]["exit_code"], result["hardFailures"], result["shadowFailures"]),
                                 (0, [], []))

    def test_progressive_to_past_or_future_still_flags(self):
        self.assertEqual(meaning.codes("물가가 계속 오르고 있다.", "물가가 계속 올랐다."), [("aspect_changed", "PROG:1->PAST")])
        self.assertEqual(meaning.codes("물가가 계속 오르고 있다.", "물가가 계속 오를 것이다."),
                         [("aspect_changed", "PROG:1->FUTURE")])
        self.assertIn("aspect_changed", codes("창문이 열려 있다.", "창문이 열렸다."))

    def test_an_doe_spacing_is_neutral(self):
        for source, candidate in (("그건 안되요.", "그건 안 돼요."), ("그건 안돼요.", "그건 안 돼요."),
                                  ("지금은 안됩니다.", "지금은 안 됩니다.")):
            with self.subTest(source=source):
                self.assertEqual(gate(source, candidate)["hardFailures"], [])
        self.assertEqual(meaning.codes("참 안됐다.", "참 안됐다."), [])
        self.assertIn("polarity_changed", codes("그건 안 돼요.", "그건 돼요."))


class Measurements(unittest.TestCase):
    """Pinned WP-10b measurements (report numbers); a change here needs a new measurement."""

    def test_555_pairs_gain_no_preserve_flag_from_the_new_codes(self):
        pairs = json.loads((DATA / "super_sejong_pairs.json").read_text(encoding="utf-8"))["pairs"]
        extra = 0
        for pair in (p for p in pairs if p["label"] == "preserve"):
            found = meaning.check(T.segment(pair["source"]), T.segment(pair["rewrite"]))
            new = {v.code for v in found} & NEW | {"clause" for v in found if v.detail == "clause_roles"}
            old = {v.code for v in found if v.code not in NEW and v.detail != "clause_roles"}
            extra += bool(new and not old)
        self.assertEqual(extra, 0)

    def test_seed_gold_sentence_pairs(self):
        rows = [json.loads(line) for line in (BENCH / "seed_benchmark.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        hits = {"content_dropped": 0, "condition_dropped": 0, "temporal_order_changed": 0}
        pairs = 0
        for record in rows:
            src, gold = T.segment(record["text"]), T.segment(record["gold_text"])
            if len(src.units) != len(gold.units):
                continue
            for a, b in zip(src.units, gold.units):
                if a.text != b.text:
                    pairs += 1
                    for code in codes(a.text, b.text) & set(hits):
                        hits[code] += 1
        self.assertGreater(pairs, 100)
        # six redundancy deletions outside data/redundancy.json and restructurings (WP-10b report)
        self.assertLessEqual(hits["content_dropped"], 6)
        self.assertEqual((hits["condition_dropped"], hits["temporal_order_changed"]), (0, 0))


class Performance(unittest.TestCase):
    def test_long_inputs_stay_fast(self):
        unit = "회원이면 함께 미리 공지된 대로 시립도서관 세미나실에서 진행하기 전에 확인하고, "
        for size in (10_000, 100_000):
            text = (unit * (size // len(unit) + 1))[:size]
            started = time.perf_counter()
            meaning.codes(text, text.replace("함께 ", "", 50))
            self.assertLess(time.perf_counter() - started, 5.0, size)


if __name__ == "__main__":
    unittest.main()
