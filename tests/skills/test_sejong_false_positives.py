"""Gate false positives seen on a legal-information blog post (2026-10-09); constructed sentences of the
same shape. Each fix keeps the real change of the same kind rejected."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine_runtime"))

from sejong import config as C, verify as V  # noqa: E402


def enforced(before: str, after: str):
    flags = C.Flags.from_env()
    found, _rate = V.document_violations(before, after, flags=flags, genre="blog")
    return sorted({v.code for v in V.classify(flags, found)[0]})


class Accepted(unittest.TestCase):
    def test_concessive_takes_over_from_do_with_iss_da(self):
        self.assertEqual(enforced("신고 면제도 있지만 대상이 적습니다.", "신고 면제가 있기는 하지만 그 대상은 적습니다."), [])

    def test_contracted_conjugation_keeps_the_cta_action(self):
        self.assertEqual(enforced("예전 양식은 내용이 다를 수 있으니 그대로 옮기지 마세요.",
                                  "예전 양식은 내용이 다를 수 있으니 그대로 옮겨 쓰지 마세요."), [])

    def test_sequence_connective_replaced_by_another(self):
        self.assertEqual(enforced("그다음 서류 목록을 차례로 확인하면 일정을 줄일 수 있습니다.",
                                  "이어서 서류 목록을 차례로 확인하면 일정을 줄일 수 있습니다."), [])


class StillRejected(unittest.TestCase):
    def test_additive_do_dropped(self):
        self.assertIn("participant_role_changed", enforced("철수도 왔다.", "철수가 왔다."))
        self.assertIn("participant_role_changed", enforced("철수도 왔지만 늦었다.", "철수가 오기는 했지만 늦었다."))

    def test_cta_action_really_replaced(self):
        codes = enforced("예전 양식은 그대로 옮기지 마세요.", "예전 양식은 그대로 버리지 마세요.")
        self.assertTrue({"cta_action_replaced", "cta_action_changed"} & set(codes), codes)

    def test_sequence_connective_added(self):
        self.assertIn("flow_transition_added", enforced("서류 목록을 차례로 확인하면 일정을 줄일 수 있습니다.",
                                                        "그다음 서류 목록을 차례로 확인하면 일정을 줄일 수 있습니다."))


if __name__ == "__main__":
    unittest.main()
