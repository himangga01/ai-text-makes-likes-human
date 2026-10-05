"""Super Sejong Engine v2 voice lock (WP-4, DESIGN.md 3.3, 3.7, 3.8, OD 1, OD 2, OD 4, 9.2a item 3).

Pair sets: tests/skills/data/sejong_voice_pairs.json (copies of the T2 prototypes' pair files,
with p19 relabelled as a hard drift by lead decision 9.2a item 3). The cases of the main-branch
voice lock (src/engine/direct-text-fidelity.ts preservesVoice, tests/unit/direct-text-fidelity.test.ts)
are ported so v2 is never weaker than it.
"""
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine_runtime"))
from sejong import io as sio  # noqa: E402
from sejong import text as T  # noqa: E402
from sejong import voice as V  # noqa: E402
from sejong import voice_gate as G  # noqa: E402
from sejong import voice_repair as R  # noqa: E402
from sejong.align import Pair, align_documents  # noqa: E402
from sejong.types import Profile, is_code  # noqa: E402

DATA = json.loads((ROOT / "tests" / "skills" / "data" / "sejong_voice_pairs.json").read_text(encoding="utf-8"))
SEED = ROOT / "docs" / "research" / "super-sejong" / "v2" / "benchmark"
PLAN_FIXTURE = ROOT / "tests" / "fixtures" / "sejong" / "plan-blog-medium.json"
# The chunk text the WP-0 plan fixture describes (tests/skills/test_sejong_text.py BLOG_SOURCE).
BLOG_SOURCE = ("오늘은 세미나 후기를 정리합니다. 왜냐하면 일정이 바뀌었습니다. 참가비는 3만 원이 됬습니다.\n\n"
               "현장 분위기가 좋았어요😀 ㅎㅎ 궁금한 점이 있으시면 댓글로 문의해 주세요.\n")

# A constructed post in the owner's published style (합쇼체 body, 해요체 CTAs and questions, -시-,
# 드리다, 저/저희, ^^ and ~). Written for this test; no owner text.
BLOG_POST = """## 영업신고 전에 꼭 확인할 세 가지

안녕하세요, ○○행정사사무소입니다. 오늘은 음식점 영업신고를 준비하시는 분들이 가장 많이 놓치는 부분을 정리해 드리겠습니다.

영업신고는 생각보다 간단해 보입니다. 하지만 시설 기준을 갖추지 못하면 신고가 반려될 수 있습니다. 실제로 저희 사무소에 오신 분들 가운데 절반 정도가 같은 문제로 다시 준비하셨습니다.

첫째, 건축물 용도를 확인하셔야 합니다. 일반음식점은 제2종 근린생활시설에서만 신고할 수 있습니다. 계약서에 서명하시기 전에 건축물대장을 꼭 떼어 보세요.

둘째, 위생교육 수료증이 필요합니다. 교육은 온라인으로도 들을 수 있고 보통 6시간 정도 걸립니다. 그렇다면 교육은 언제 받는 것이 좋을까요? 임대차계약을 마친 뒤 바로 받으시는 것을 권해 드립니다.

셋째, 정화조 용량을 살펴보셔야 합니다. 객석 면적이 늘어나면 정화조 기준도 달라집니다. 이 부분은 많은 분들이 혼동하시는 경우가 많습니다.

- 건축물대장 사본 1부
- 위생교육 수료증
- 영업장 평면도

서류가 준비되면 관할 구청 위생과에 접수하시면 됩니다. 처리 기간은 통상 3일 이내입니다. 다만 현장 확인이 필요한 경우에는 기간이 조금 늘어날 수 있습니다.

혼자 준비하시기 어려우시다면 언제든 편하게 문의해 주세요^^ 제가 직접 서류 목록부터 확인해 드릴게요~

궁금하신 점은 댓글로 남겨 주세요. 오늘도 끝까지 읽어 주셔서 감사합니다.
"""


def doc(text):
    return T.segment(text)


def check(src, out, fix_colloquial=False):
    return G.check(doc(src), doc(out), fix_colloquial=fix_colloquial)


def blocking(src, out, fix_colloquial=False):
    return G.blocking(check(src, out, fix_colloquial))


def hard(src, out):
    return [v for v in check(src, out) if v.severity == "hard"]


def main_rows():
    """(id, label, expected severity or None, src, out) with the relabels applied."""
    relabel = DATA["relabel"]
    rows = []
    for label in ("preserve", "drift"):
        for r in DATA["main"][label]:
            if r["id"] in relabel:
                rows.append((r["id"], relabel[r["id"]]["to"], relabel[r["id"]]["sev"], r["src"], r["out"]))
            else:
                rows.append((r["id"], label, r.get("sev"), r["src"], r["out"]))
    return rows


def cmc_rows():
    out = []
    for row in DATA["cmc"]["preserve"]:
        out.append((row[0], "preserve", None, row[2], row[3]))
    for row in DATA["cmc"]["drift"]:
        out.append((row[0], "drift", row[2], row[3], row[4]))
    return out


class ClassifierTests(unittest.TestCase):
    def test_eight_levels(self):
        cases = {
            "서류를 미리 준비해야 합니다.": "HAPSYO", "계약 전에 꼭 확인하세요.": "HAEYO",
            "그는 결국 그 일을 포기했다.": "HAERA", "나도 그 영화 봤는데 진짜 재밌었어.": "HAE",
            "그대는 어디로 가시오?": "HAO", "자네 요즘 어떻게 지내는가?": "HAGE",
            "- 사업자등록증 사본 1부 제출 필요": "NOMINAL", "서류를 접수하면 담당자가 검토하고,": "NONE",
            "이제 함께 갑시다.": "HAO", "알겠습니당 ㅋㅋ": "HAPSYO", "오늘 처음 가 봤어여.": "HAEYO",
        }
        for sentence, level in cases.items():
            kind = "list" if sentence.startswith("- ") else "body"
            self.assertEqual(V.signature(sentence, kind).level, level, sentence)

    def test_mood_and_stance(self):
        self.assertEqual(V.signature("실적이 없어도 신청할 수 있을까요?").mood, "INTERR")
        self.assertEqual(V.signature("임대차계약 전에 꼭 확인하세요.").mood, "IMPER")
        self.assertEqual(V.signature("이제부터라도 환경을 생각하는 소비를 해 보자.").mood, "PROPOS")
        self.assertEqual(V.signature("안녕하세요.").mood, "DECL")
        self.assertEqual(V.signature("작년에 규정이 바뀌었더라고요.").stance, "더라고요")
        self.assertEqual(V.signature("이 마을에는 우물이 하나 있답니다.").stance, "답니다")
        self.assertEqual(V.signature("처리 기간은 20일입니다.").stance, "ㅂ니다")
        self.assertIsNone(V.signature("생각보다 장비가 필요하지 않았어요.").stance)

    def test_quotation_masked(self):
        sig = V.signature('그는 "빨리 와."라고 말하며 웃었다.')
        self.assertEqual(sig.level, "HAERA")
        self.assertEqual(V.signature("“그 집 부모가 원래 그렇습니다.”", "quote").level, "HAPSYO")
        self.assertEqual(V.features('그는 "빨리 와."라고 말하며 웃었다.').quote_levels, ("HAE",))

    def test_si_count_every_honorific(self):
        counts = {
            "궁금하신 점이 있으시다면 언제든지 편하게 문의해 주세요.": 3,
            "궁금한 점이 있으시면 언제든 편하게 문의해 주세요.": 2,
            "학부모님께서 서류를 작성하셔야 합니다.": 2, "학부모가 서류를 작성해야 합니다.": 0,
            "하실 수 있습니다.": 1, "할 수 있습니다.": 0, "주실테니 걱정 마세요.": 2,
            "하십시오.": 1, "함께 생각해 봅시다.": 0, "처음에는 다들 어렵게 느끼시죠.": 1,
            "여기 가 보신 분 계신가요?": 2, "음식을 드시고 가세요.": 2,
            # nouns, numerals and loanwords are not -시-
            "반드시 확인해야 합니다.": 0, "메시지를 남겼습니다.": 0, "오십 명이 왔습니다.": 0,
            "증시는 하락했습니다.": 0, "회의실까지 오세요.": 1, "임신 중에는 주의합니다.": 0,
            "당시에는 몰랐습니다.": 0, "럭셔리 브랜드입니다.": 0, "업그레이드시킬 예정입니다.": 0,
        }
        for sentence, count in counts.items():
            self.assertEqual(V.signature(sentence).si_count, count, (sentence, V.si_spans(sentence)))

    def test_honorific_address_count(self):
        counts = {"학부모님들께 알려 드립니다.": 2, "선생님께서 오셨습니다.": 1, "어른께 인사드렸다.": 1,
                  "내일 연락할께요.": 0, "15일께 도착합니다.": 0, "다음 주 초께 발표합니다.": 0,
                  "함께 확인해야 합니다.": 0}
        for sentence, count in counts.items():
            self.assertEqual(V.features(sentence).hon_nouns, count, sentence)
        self.assertEqual(blocking("기준을 함께 확인해야 합니다.", "기준을 확인해야 합니다."), [])
        self.assertEqual([v.code for v in blocking("원장님께서 학부모님들에게 인사드립니다.", "원장님께서 학부모님들께 인사드립니다.")],
                         ["voice_hon_noun_changed"])

    def test_keep_tokens_from_protect(self):
        sig = V.signature("넹 알겠습니당 ㅋㅋ")
        self.assertEqual(sorted(sig.cmc), ["ㅋㅋ", "넹", "니당"])
        self.assertEqual(V.signature("이 카페는 디저트가 진짜 맛있네요 ㅎㅎ").discourse, ["진짜"])
        self.assertEqual(V.signature("사실 저도 처음엔 걱정이 많았거든요^^").discourse, ["사실"])
        self.assertEqual(V.signature("진짜 맛있었어요.").discourse, ["진짜"])     # counted once

    def test_plan_fixture_voice_reproduced(self):
        plan = json.loads(PLAN_FIXTURE.read_text(encoding="utf-8"))
        units = doc(BLOG_SOURCE).units
        self.assertEqual(len(units), len(plan["sentences"]))
        for unit, sentence in zip(units, plan["sentences"]):
            self.assertEqual(V.signature(unit.text, unit.kind).to_json(), sentence["voice"], unit.text)

    def test_signature_matches_schema(self):
        schema = sio.load_schema("plan")
        for sentence in ("궁금하신 점은 댓글로 남겨 주세요^^", "## 신청 전 확인 사항", "그건 내가 알아서 할게 ㅋㅋ",
                         "저는 교사 출신 행정사입니다.", "x" * 500):
            problems = sio.validate(V.signature(sentence).to_json(), schema["$defs"]["voice"], schema)
            self.assertEqual(problems, [], sentence)

    def test_profile_and_sheet_line(self):
        d = doc(BLOG_POST)
        profile = V.profile(d)
        self.assertEqual(Profile.from_json(profile).to_json(), profile)
        self.assertEqual(profile["dominant"], "HAPSYO")
        self.assertTrue(profile["mixed"])
        self.assertTrue(profile["line"].startswith("합쇼 "))
        self.assertIn("해요", profile["line"])
        unit = next(u for u in d.units if u.text.startswith("궁금하신 점은"))
        self.assertEqual(V.sheet_line(unit, V.signature(unit.text)), f"{unit.id} 해요체·명령·시×2 「주세요」")
        # "…문의해 주세요^^ 제가 … 드릴게요~" is one WP-1 unit; the sheet shows its last ending, and the
        # clause closed by ^^ is locked through Features.inner
        unit = next(u for u in d.units if u.text.startswith("혼자 준비하시기"))
        self.assertEqual(V.sheet_line(unit, V.signature(unit.text)),
                         f"{unit.id} 해요체·평서·시×3·ㄹ게요 「드릴게요」 keep:[^^, ~, 드리다, 저]")
        self.assertEqual(V.features(unit.text).inner, (("HAEYO", "IMPER"),))
        self.assertEqual([v.code for v in hard(unit.text, unit.text.replace("주세요^^", "주십시오^^"))], ["voice_level"])


class PairSetTests(unittest.TestCase):
    def test_preserving_pairs_no_hard_violation(self):
        preserve = [row for row in main_rows() if row[1] == "preserve"]
        self.assertEqual(len(preserve), 63)
        flagged = [row[0] for row in preserve if hard(row[3], row[4])]
        self.assertEqual(flagged, [])                                   # 0/63 (+ p19 relabelled)
        soft = [row[0] for row in preserve if blocking(row[3], row[4])]
        self.assertEqual(soft, ["p26", "p41"])                          # 진짜 -> 정말, OD 2 drift

    def test_drift_pairs_caught(self):
        drift = [row for row in main_rows() if row[1] == "drift"]
        self.assertEqual(len(drift), 65)
        expected_hard = [row for row in drift if row[2] == "hard"]
        self.assertEqual(len(expected_hard), 50)                        # 49 of T2 + p19
        missed = [row[0] for row in expected_hard if not hard(row[3], row[4])]
        self.assertEqual(missed, [])
        uncaught = [row[0] for row in drift if not blocking(row[3], row[4])]
        self.assertEqual(uncaught, [])
        over = [row[0] for row in drift if row[2] == "soft" and hard(row[3], row[4])]
        self.assertEqual(over, ["d29"])                                 # 느끼시죠 -> 느끼세요 reads as IMPER

    def test_cmc_pairs(self):
        rows = cmc_rows()
        self.assertEqual([row[0] for row in rows if row[1] == "preserve" and check(row[3], row[4])], [])
        self.assertEqual([row[0] for row in rows if row[1] == "drift" and not blocking(row[3], row[4])], [])
        # opt-in: every CMC drift of this set is reported as info only
        for row in rows:
            if row[1] == "drift":
                found = check(row[3], row[4], fix_colloquial=True)
                self.assertTrue(found, row[0])
                self.assertEqual(G.blocking(found), [], row[0])

    def test_repair_leaves_no_residual(self):
        rows = main_rows() + cmc_rows()
        altered = []
        for rid, label, _, src, out in rows:
            s, o = doc(src), doc(out)
            repaired, _ = R.repair(s, o)
            self.assertEqual(G.blocking(G.check(s, doc(repaired))), [], rid)
            again, actions = R.repair(s, doc(repaired))
            self.assertEqual(again, repaired, rid)                      # idempotent
            self.assertEqual(actions, [], rid)
            if label == "preserve" and repaired != out:
                altered.append(rid)
        self.assertEqual(altered, ["p26", "p41"])

    def test_codes_are_lowercase(self):
        for _, _, _, src, out in main_rows() + cmc_rows():
            for v in check(src, out):
                self.assertTrue(is_code(v.code), v.code)
                self.assertEqual(v.family, "voice")
                self.assertIn(v.code, G.HARD_CODES + G.SOFT_CODES)


class OwnerDecisionTests(unittest.TestCase):
    def test_od4_honorific_changes_are_hard(self):
        cases = [
            ("오늘 안에 서류를 보내 주실게요.", "오늘 안에 서류를 보내 주세요."),
            ("하실게요.", "해 주세요."),
            ("학부모님께서 신청서를 직접 작성하셔야 합니다.", "학부모가 신청서를 직접 작성해야 합니다."),
            ("궁금하신 점이 있으시면 연락해 주세요.", "궁금한 점이 있으시면 연락해 주세요."),
            ("하실 수 있습니다.", "할 수 있습니다."),
        ]
        for src, out in cases:
            self.assertTrue(hard(src, out), (src, out))

    def test_od2_colloquial_kept_by_default(self):
        cases = {
            ("이 카페는 디저트가 진짜 맛있네요.", "이 카페는 디저트가 정말 맛있네요."): "voice_discourse_dropped",
            ("그건 내가 알아서 할게 ㅋㅋ", "그건 내가 알아서 할게."): "voice_emoticon_dropped",
            ("내일 꼭 연락할께요.", "내일 꼭 연락할게요."): "voice_colloquial_changed",
            # spoken -구 of -고 (2026-10-04 real-model run)
            ("다음에는 평일 오전에 가 보려구요.", "다음에는 평일 오전에 가 보려고요."): "voice_colloquial_changed",
            ("밥은 먹었구요, 이제 나가요.", "밥은 먹었고요, 이제 나가요."): "voice_colloquial_changed",
        }
        for (src, out), code in cases.items():
            default = check(src, out)
            self.assertEqual([(v.code, v.severity) for v in default], [(code, "soft")], src)
            opted = check(src, out, fix_colloquial=True)
            self.assertEqual([(v.code, v.severity) for v in opted], [(code, "info")], src)

    def test_spoken_geo_gat_upshift_only_in_casual_levels(self):
        # 거 같다 -> 것 같다 is a written upshift in 해체/해요체 (keep the spacing fix, not the register change)
        self.assertEqual([v.code for v in check("역시 가을 산이 최고인거 같아ㅎㅎ", "역시 가을 산이 최고인 것 같아ㅎㅎ")],
                         ["voice_written_upshift"])
        self.assertEqual([v.code for v in check("비가 올 거 같아요.", "비가 올 것 같아요.")], ["voice_written_upshift"])
        # the retry is told which spoken form to keep (not the sentence's final 같아)
        self.assertEqual([v.keep for v in check("역시 가을 산이 최고인거 같아ㅎㅎ", "역시 가을 산이 최고인 것 같아ㅎㅎ")],
                         ["거 같아"])
        self.assertEqual(check("역시 가을 산이 최고인거 같아ㅎㅎ", "역시 가을 산이 최고인 거 같아ㅎㅎ"), [])
        # a new 것 같다 where the source had no spoken 거 같다 is a hedge change, not a register change
        self.assertEqual(check("아마 그럴 수도 있어요.", "아마 그럴 것 같아요."), [])
        # 이었 after a final consonant is the only spelling (the TR-JUNGE_ITDA repair in the past tense); the other
        # upshifts still count
        self.assertEqual(check("공사가 진행 중에 있었다.", "공사가 진행 중이었다."), [])
        self.assertEqual([v.code for v in check("그는 그 일을 했다.", "그는 그 일을 하였다.")], ["voice_written_upshift"])
        # in 합쇼체 and 해라체 것 같다 is the expected form
        self.assertEqual(check("내일은 비가 올거 같습니다.", "내일은 비가 올 것 같습니다."), [])
        self.assertEqual(check("그는 이미 떠난 거 같다.", "그는 이미 떠난 것 같다."), [])

    def test_od1_document_profile_never_decides(self):
        # a 해요체 CTA inside a 합쇼체 paragraph keeps its own level; normalising it is a violation
        src = "등록 요건을 갖추려면 시간이 걸립니다. 여유를 두고 준비하세요."
        self.assertEqual(check(src, src), [])
        self.assertTrue(hard(src, "등록 요건을 갖추려면 시간이 걸립니다. 여유를 두고 준비하십시오."))


class MainBranchParityTests(unittest.TestCase):
    """tests/unit/direct-text-fidelity.test.ts voice cases, plus what preservesVoice compares."""

    REJECT = [
        ("honorific -시- dropped", "궁금하신 점이 있으시면 사무소로 문의해 주세요.", "궁금한 점이 있으시면 사무소로 문의해 주세요."),
        ("해요체 request to 합쇼체", "서류는 사무소로 보내 주세요.", "서류는 사무소로 보내 주시기 바랍니다."),
        ("request weakened", "계약 전에 꼭 확인하세요.", "계약 전에 꼭 확인하시는 것이 좋아요."),
        ("question to statement", "실적이 없어도 신청할 수 있을까요?", "실적이 없어도 신청할 수 있어요."),
        ("합쇼체 to 해라체", "등록 요건은 업종마다 다릅니다.", "등록 요건은 업종마다 다르다."),
        ("stance ending flattened", "작년에 규정이 바뀌었더라고요.", "작년에 규정이 바뀌었어요."),
        ("humble verb dropped", "필요한 서류는 상담할 때 안내해 드리겠습니다.", "필요한 서류는 상담할 때 안내하겠습니다."),
        ("CMC mark dropped", "이 카페는 디저트가 정말 맛있어요 ㅎㅎ", "이 카페는 디저트가 정말 맛있어요."),
        # what preservesVoice also compares: humble count, raw mark runs, request endings, a bare '?'
        ("humble verb added", "서류 목록은 상담할 때 안내하겠습니다.", "서류 목록은 상담할 때 안내해 드리겠습니다."),
        ("second humble verb dropped", "자료를 보내 드리고 설명해 드리겠습니다.", "자료를 보내고 설명해 드리겠습니다."),
        ("laughter shortened", "그건 내가 알아서 할게 ㅋㅋㅋ", "그건 내가 알아서 할게 ㅋㅋ"),
        ("tilde run shortened", "다음에 또 올게요~~", "다음에 또 올게요~"),
        ("request ending dropped", "서류를 미리 보내 주시기 바랍니다.", "서류를 미리 보내 주시면 좋겠습니다."),
        ("fragment question to statement", "그래서 결론은?", "그래서 결론은."),
        ("propositive to statement", "이제 함께 시작합시다.", "이제 함께 시작합니다."),
    ]
    KEEP = [
        ("합쇼체 rewording", "신청서를 제출하기 전에 서류의 유효기간을 반드시 확인하는 것이 필요합니다.",
         "신청서를 내기 전에 서류의 유효기간을 반드시 확인해야 합니다."),
        ("해요체 CTA rewording", "궁금하신 점이 있으시다면 언제든지 편하게 문의해 주세요.",
         "궁금하신 점이 있으시면 언제든 편하게 문의해 주세요."),
        ("question kept", "그렇다면 매출액 기준은 어떻게 판단하는 것일까요?", "그렇다면 매출액 기준은 어떻게 판단할까요?"),
    ]

    def test_rejects_voice_changes(self):
        for label, src, out in self.REJECT:
            self.assertTrue(blocking(src, out), label)

    def test_keeps_voice_preserving_rewrites(self):
        for label, src, out in self.KEEP:
            self.assertEqual(blocking(src, out), [], label)


class GroupRuleTests(unittest.TestCase):
    def test_split_merge_insert(self):
        self.assertEqual([v.code for v in hard("이 부분은 많은 분들이 놓치는 부분인데 꼭 확인하셔야 해요.",
                                                "이 부분은 많은 분들이 놓치는 부분입니다. 꼭 확인하셔야 해요.")],
                         ["voice_split_level"])
        self.assertEqual(blocking("이 부분은 많은 분들이 놓치는 부분인데 꼭 확인하셔야 해요.",
                                  "이 부분은 많은 분들이 놓쳐요. 꼭 확인하셔야 해요."), [])
        codes = [v.code for v in hard("등록 요건을 갖추는 데는 시간이 걸립니다. 여유를 두고 준비하세요.",
                                      "등록 요건을 갖추는 데 시간이 걸리니 여유를 두고 준비하세요.")]
        self.assertEqual(codes, ["voice_merge_across_levels"])
        src = doc("서류를 접수합니다. 결과는 20일 안에 나옵니다.")
        out = doc("서류를 접수합니다. 궁금하면 물어봐요. 결과는 20일 안에 나옵니다.")
        pairs = [Pair((0,), (0,), 1.0), Pair((), (1,), 0.0), Pair((1,), (2,), 1.0)]
        found = G.check(src, out, pairs)
        self.assertEqual([(v.code, v.sentence) for v in found], [("voice_inserted_level", "S1")])

    def test_quote_level(self):
        self.assertEqual([v.code for v in hard('그는 "빨리 와."라고 말하며 웃었다.', '그는 "빨리 오세요."라고 말하며 웃었다.')],
                         ["voice_quote_level"])

    def test_violation_carries_sentence_and_keep(self):
        found = check("처리 기간은 보통 20일 정도 걸립니다.", "처리 기간은 보통 20일 정도 걸려요.")
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].code, found[0].sentence, found[0].detail, found[0].keep),
                         ("voice_level", "S1", "HAPSYO->HAEYO", "걸립니다."))


class RepairTests(unittest.TestCase):
    def repaired(self, src, out, fix_colloquial=False):
        return R.repair(doc(src), doc(out), fix_colloquial=fix_colloquial)

    def test_graft_restores_writer_ending(self):
        text, actions = self.repaired("처리 기간은 통상적으로 약 20일 정도 소요됩니다.", "처리 기간은 보통 20일쯤 소요돼요.")
        self.assertEqual(text, "처리 기간은 보통 20일쯤 소요됩니다.")
        self.assertEqual(actions, [("S1", "voice_graft")])
        text, _ = self.repaired("내일 꼭 연락할께요 ㅎㅎ", "내일 꼭 연락할게요 ㅎㅎ")
        self.assertEqual(text, "내일 꼭 연락할께요 ㅎㅎ")

    def test_cmc_restore(self):
        text, actions = self.repaired("오늘도 끝까지 읽어 주셔서 감사해요^^", "오늘도 끝까지 읽어 주셔서 정말 감사해요.")
        self.assertEqual(text, "오늘도 끝까지 읽어 주셔서 정말 감사해요^^")
        self.assertEqual(actions, [("S1", "cmc_restore")])
        text, _ = self.repaired("사실 저도 처음엔 걱정이 많았어요.", "저도 처음엔 걱정이 많았어요.")
        self.assertEqual(text, "사실 저도 처음엔 걱정이 많았어요.")

    def test_no_graft_on_mood_or_honorific_inside(self):
        src = "궁금하신 점이 있으시면 연락해 주세요."
        text, actions = self.repaired(src, "궁금한 점이 있으시면 연락해 주세요.")
        self.assertEqual((text, actions), (src, [("S1", "voice_revert")]))
        src = "그렇다면 매출액 기준은 어떻게 판단할까요?"
        text, actions = self.repaired(src, "매출액 기준은 다음과 같이 판단합니다.")
        self.assertEqual((text, actions), (src, [("S1", "voice_revert")]))

    def test_repair_pair_api(self):
        unit = doc("필요한 서류는 상담할 때 안내해 드리겠습니다.").units[0]
        found = G.compare_texts(unit.text, "필요한 서류는 상담할 때 안내하겠습니다.")
        self.assertEqual(R.repair_pair(unit, "필요한 서류는 상담할 때 안내하겠습니다.", found),
                         (unit.text, ["voice_revert"]))
        self.assertEqual(R.repair_pair(unit, unit.text, []), (unit.text, []))

    def test_whitespace_around_repairs_kept(self):
        src = "첫 문장입니다.\n둘째 문장은 확인하세요.\n\n셋째 문단입니다."
        out = "첫 문장입니다.\n둘째 문장은 확인하십시오.\n\n셋째 문단입니다."
        text, _ = self.repaired(src, out)
        self.assertEqual(text, src)


class IdempotenceTests(unittest.TestCase):
    def test_check_identity_is_empty(self):
        texts = [BLOG_POST, BLOG_SOURCE] + [row[3] for row in main_rows() + cmc_rows()]
        for name in ("seed_benchmark.jsonl", "seed_composites.jsonl"):
            for line in (SEED / name).read_text(encoding="utf-8").splitlines():
                item = json.loads(line)
                texts.append(item["text"])
                if item.get("gold_text"):
                    texts.append(item["gold_text"])
        for value in texts:
            d = doc(value)
            self.assertEqual(G.check(d, d), [], value[:60])
            self.assertEqual(R.repair(d, d), (value, []))

    def test_blog_post_round_trip(self):
        src = doc(BLOG_POST)
        drifted = (BLOG_POST.replace("떼어 보세요.", "떼어 보시기 바랍니다.")
                   .replace("걸립니다.", "걸려요.")
                   .replace("문의해 주세요^^", "문의해 주세요.")
                   .replace("확인해 드릴게요~", "확인하겠습니다.")
                   .replace("궁금하신 점은", "궁금한 점은"))
        out = doc(drifted)
        found = G.blocking(G.check(src, out))
        self.assertGreaterEqual(len(found), 5)
        repaired, _ = R.repair(src, out)
        self.assertEqual(repaired, BLOG_POST)
        self.assertEqual(R.repair(src, doc(repaired)), (BLOG_POST, []))

    def test_voice_neutral_edits_pass(self):
        src = doc(BLOG_POST)
        edited = (BLOG_POST.replace("생각보다 간단해 보입니다.", "생각보다 쉬워 보입니다.")
                  .replace("통상 3일 이내입니다.", "보통 3일 안쪽입니다.")
                  .replace("가장 많이 놓치는 부분을", "자주 놓치는 부분을"))
        self.assertEqual(G.check(src, doc(edited)), [])


class PerformanceTests(unittest.TestCase):
    def test_30k_chars_within_budget(self):
        seed = [json.loads(line) for line in (SEED / "seed_composites.jsonl").read_text(encoding="utf-8").splitlines()]
        base = "\n\n".join(item["text"] for item in seed)
        src_text = ((base + "\n\n") * 2)[:30000]
        src = doc(src_text)
        pieces, last = [], 0
        for unit in src.units:                 # every sentence changed: the worst case for the gate
            pieces.append(src_text[last:unit.start])
            pieces.append("정말 " + unit.text)
            last = unit.end
        pieces.append(src_text[last:])
        out = doc("".join(pieces))
        best = None
        for _ in range(3):
            start = time.perf_counter()
            G.check(src, out, align_documents(src, out))
            elapsed = time.perf_counter() - start
            best = elapsed if best is None else min(best, elapsed)
        self.assertLessEqual(best, 0.3, best)

    def test_adversarial_sentences_linear(self):
        for sentence in ("가" * 100000 + "습니다.", "ㅋ" * 100000 + "x", "하시고 " * 15000 + "합니다.", "“" + "가" * 100000):
            start = time.perf_counter()
            V.signature(sentence)
            self.assertLess(time.perf_counter() - start, 0.5, sentence[:5])


if __name__ == "__main__":
    unittest.main()


class SpacingFixesAreVoiceNeutral(unittest.TestCase):
    def test_bound_noun_spacing_does_not_change_the_honorific_count(self):
        from sejong.voice_gate import compare_texts
        for before, after in (("신청하실수 있습니다.", "신청하실 수 있습니다."), ("방문하실때 연락 주세요.", "방문하실 때 연락 주세요."),
                              ("말씀하신것을 확인했습니다.", "말씀하신 것을 확인했습니다."), ("확인해주세요.", "확인해 주세요.")):
            with self.subTest(before=before):
                self.assertEqual(compare_texts(before, after), [])
        self.assertTrue(compare_texts("신청하실 수 있습니다.", "신청할 수 있습니다."))
