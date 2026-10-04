"""Super Sejong Engine v2 norm and voice hardening (WP-10b): 뵈요 -> 봬요 and 뵜 -> 뵀 with the humble form kept,
the closed noun + 이였 -> 이었 fix with no up-shift, and the SSJ-A06 additions 별로, 도저히, 일절.

Every sentence here is constructed for the test.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine_runtime.sejong import config, diagnose as D, norms, text, voice  # noqa: E402
from engine_runtime.sejong import verify as VF  # noqa: E402

FLAGS = config.Flags.from_env({})
DATA = ROOT / "engine_runtime" / "sejong" / "data"


def fixed(source):
    return norms.fix_text(source)[0]


def lock(sentence):
    """What OD 4 locks: level, mood, -시- (final and anywhere), humble count, persona, up-shift count."""
    f = voice.features(sentence)
    return (f.sig.level, f.sig.mood, f.sig.hon_si, f.sig.si_count, f.humble_count, tuple(f.sig.persona), f.upshift)


def rules(source):
    return [f.rule for f in D.diagnose(text.segment(source), genre="general")]


class HumbleContractions(unittest.TestCase):
    CASES = [("그날 뵈요!", "그날 봬요!"), ("내일 학교에서 뵈요.", "내일 학교에서 봬요."), ("어제 뵜어요.", "어제 뵀어요."),
             ("처음 뵜을 때 긴장했습니다.", "처음 뵀을 때 긴장했습니다."), ("직접 뵈서 반가웠습니다.", "직접 봬서 반가웠습니다."),
             ("한번 뵈야 합니다.", "한번 봬야 합니다."), ("조만간 뵈야죠.", "조만간 봬야죠.")]

    def test_fix_keeps_the_voice_lock_and_verifies_clean(self):
        for wrong, right in self.CASES:
            with self.subTest(wrong=wrong):
                self.assertEqual(fixed(wrong), right)
                self.assertEqual(lock(wrong), lock(right))
                self.assertGreaterEqual(voice.features(right).humble_count, 1)
                result = VF.verify_document(wrong, right, flags=FLAGS)
                self.assertEqual((result["gate"]["exit_code"], result["hardFailures"], result["shadowFailures"]),
                                 (0, [], []))

    def test_contracted_forms_are_humble(self):
        for sentence in ("다음에 봬요.", "어제 뵀어요.", "처음 뵌 날이었다.", "꼭 봬야죠.", "직접 봬서 좋았어요."):
            self.assertTrue(voice.signature(sentence).humble, sentence)

    def test_dropping_the_humble_form_is_still_flagged(self):
        result = VF.verify_document("내일 봬요.", "내일 만나요.", flags=FLAGS)
        self.assertIn("voice_humble_dropped", result["shadowFailures"] + result["hardFailures"])

    def test_list_no_longer_excludes_it(self):
        data = json.loads((DATA / "misspellings.json").read_text(encoding="utf-8"))
        self.assertNotIn("뵈요→봬요", data["excluded_on_purpose"])
        self.assertLessEqual({"뵈요", "뵈서", "뵈야", "뵜"}, {e["wrong"] for e in data["entries"] if e["class"] == "error"})


class CopulaPast(unittest.TestCase):
    def test_closed_nouns_are_fixed_without_an_upshift(self):
        for wrong, right in (("진짜 맛있었는데 가격이 좀 비싼 편이였어.", "진짜 맛있었는데 가격이 좀 비싼 편이었어."),
                             ("그때 저는 학생이였다.", "그때 저는 학생이었다."), ("처음이였어요.", "처음이었어요.")):
            with self.subTest(wrong=wrong):
                self.assertEqual(fixed(wrong), right)
                self.assertEqual(lock(wrong), lock(right))
                result = VF.verify_document(wrong, right, flags=FLAGS)
                self.assertEqual((result["gate"]["exit_code"], result["shadowFailures"]), (0, []))
                self.assertNotIn("SSJ-N05", rules(wrong))           # no duplicate request for the same error

    def test_traps_and_vowel_final_nouns_are_not_deterministic(self):
        for safe in ("외톨이였던 시절", "고양이였다.", "친구이였다."):
            self.assertEqual(fixed(safe), safe)
        self.assertEqual(fixed("그는 남편이였다."), "그는 남편이였다.")
        self.assertIn("SSJ-N05", rules("그는 남편이였다."))            # outside the closed list: still a request

    def test_upshift_counter_reads_iyeoss_as_ieoss(self):
        self.assertEqual(voice.features("비싼 편이였어.").upshift, voice.features("비싼 편이었어.").upshift)
        self.assertGreater(voice.features("그것을 하였다.").upshift, voice.features("그것을 했다.").upshift)


class NoAnDoeFix(unittest.TestCase):
    def test_attached_an_doe_is_not_respaced(self):
        # 안되다 (참 안됐다) is a word; only the comparison spaces it (meaning._normalised).
        self.assertEqual(fixed("참 안됐다."), "참 안됐다.")
        self.assertEqual(fixed("그건 안되요."), "그건 안돼요.")


class NegativePolarityAdverbs(unittest.TestCase):
    def test_new_adverbs_without_negation(self):
        for sentence in ("가격이 별로 비싸요.", "도저히 혼자서 끝낼 수 있었다.", "첨가물을 일절 사용합니다."):
            self.assertIn("SSJ-A06", rules(sentence), sentence)

    def test_new_adverbs_with_negation_or_other_uses(self):
        for sentence in ("가격이 별로 비싸지 않아요.", "도저히 혼자서 끝낼 수 없었다.", "첨가물을 일절 사용하지 않습니다.",
                         "외부 음식 반입은 일절 금지입니다.", "애국가 일절을 불렀다.", "하늘이 별로 가득했다.",
                         "이 식당은 별로예요.", "거의 다 왔어요."):
            self.assertNotIn("SSJ-A06", rules(sentence), sentence)

    def test_guide_names_the_list(self):
        line = D.guide("SSJ-A06")
        for word in ("결코", "좀처럼", "차마", "전혀", "별로", "도저히", "일절"):
            self.assertIn(word, line)
        self.assertNotIn("거의", line)


if __name__ == "__main__":
    unittest.main()
