"""Super Sejong Engine v2 text, segmentation and protection (WP-1, DESIGN.md 3.1, 3.2)."""
import importlib.util
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine_runtime.sejong import protect, text, types  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
SEED = ROOT / "docs" / "research" / "super-sejong" / "v2" / "benchmark"
VENDOR_SANITIZE = ROOT / "vendor" / "humanize-engine" / "scripts" / "sanitize_text.py"
# The chunk texts the WP-0 plan fixtures describe (tests/skills/test_sejong_contracts.py).
BLOG_SOURCE = ("오늘은 세미나 후기를 정리합니다. 왜냐하면 일정이 바뀌었습니다. 참가비는 3만 원이 됬습니다.\n\n"
               "현장 분위기가 좋았어요😀 ㅎㅎ 궁금한 점이 있으시면 댓글로 문의해 주세요.\n")
NO_EDIT_SOURCE = "회의는 오전 10시에 시작합니다. 자료는 미리 읽어 오세요.\n"


def load_vendor_sanitize():
    saved = list(sys.path)
    try:
        spec = importlib.util.spec_from_file_location("vendor_sanitize_text_wp1", VENDOR_SANITIZE)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module          # dataclasses resolve the module by name
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


def strings_in(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)


def seed_rows():
    rows = []
    for name in ("seed_benchmark.jsonl", "seed_composites.jsonl"):
        for line in (SEED / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def fixture_texts():
    """Every string of every repository text fixture and every seed benchmark text."""
    out = []
    for path in sorted(list(FIXTURES.rglob("*.json")) + list((ROOT / "tests" / "skills" / "data").glob("*.json"))):
        out.extend(strings_in(json.loads(path.read_text(encoding="utf-8"))))
    for path in sorted(FIXTURES.rglob("*.txt")):
        out.append(path.read_text(encoding="utf-8"))
    for row in seed_rows():
        for key in ("text", "gold_text", "gold_text_optin_colloquial_fix"):
            if isinstance(row.get(key), str):
                out.append(row[key])
    return out


def adversarial_texts():
    """Constructed inputs for each sanitize rule (code points built with chr, never literals)."""
    zw, zwj, zwnj, bom, nbsp = chr(0x200B), chr(0x200D), chr(0x200C), chr(0xFEFF), chr(0x00A0)
    rlo, lrm, tag_a, shy = chr(0x202E), chr(0x200E), chr(0xE0041), chr(0x00AD)
    nfd = "".join(chr(c) for c in (0x1112, 0x1161, 0x11AB, 0x1100, 0x1173, 0x11AF))   # 한글 decomposed
    return [
        bom + "본문" + zw + "입니다." + shy,
        "가" + rlo + "나" + lrm + "다" + tag_a + "라",
        nfd + " 문장입니다.",
        "ㅋㅋ ㅠㅠ " + chr(0x3131) + chr(0x314F) + " 호환 자모는 그대로" + chr(0xF900),
        "a" + nbsp + "b" + chr(0x2003) + "c" + chr(0x202F) + "d" + chr(0x3000) + "전각",
        "줄1\r\n줄2\r줄3" + chr(0x2028) + "줄4" + chr(0x2029) + "줄5   \n끝\t",
        "👩" + zwj + "💻 와 가" + zwj + "나 그리고 " + zwnj + "x",
        "",
        "\n\n\n",
        "가" + zw + chr(0x1100) + chr(0x1161) + " 자모 사이 제로폭",
    ]


class SanitizeParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vendor = load_vendor_sanitize()

    def assert_parity(self, sample, **options):
        expected, report = self.vendor.sanitize(sample, **options)
        actual, ours = text.sanitize(sample, **options)
        self.assertEqual(actual.encode("utf-8"), expected.encode("utf-8"))
        self.assertEqual(ours, report.to_dict())

    def test_byte_parity_on_repository_fixtures_and_seed_texts(self):
        samples = fixture_texts()
        self.assertGreater(len(samples), 400)
        for i, sample in enumerate(samples):
            with self.subTest(sample=i):
                self.assert_parity(sample)

    def test_byte_parity_on_every_sanitize_rule_and_option(self):
        for i, sample in enumerate(adversarial_texts()):
            for options in ({}, {"normalize_ideographic_space": True, "collapse_blank_lines": True},
                            {"normalize_unicode": False, "strip_invisible": False},
                            {"normalize_spaces": False, "normalize_lines": False}):
                with self.subTest(sample=i, options=options):
                    self.assert_parity(sample, **options)

    def test_never_nfkc_and_idempotent(self):
        sample = "ㅋㅋ " + chr(0xF900) + " Å" + chr(0x212B) + " ①"
        clean, report = text.sanitize(sample)
        self.assertEqual(clean, sample)
        self.assertFalse(report["changed"])
        for sample in adversarial_texts():
            once = text.sanitize(sample)[0]
            self.assertEqual(text.sanitize(once)[0], once)


class SplitterTests(unittest.TestCase):
    def split(self, sample):
        return [u.text for u in text.split_sentences(sample)]

    def test_glued_terminators_split(self):
        self.assertEqual(self.split("연구가 진행된다.논문에서는 이를 다룬다."), ["연구가 진행된다.", "논문에서는 이를 다룬다."])
        self.assertEqual(self.split("결과를 보였다.2. 기존 방법은 느리다."), ["결과를 보였다.", "2. 기존 방법은 느리다."])
        self.assertEqual(self.split("평가하였다.CNN 모델은 빠르다."), ["평가하였다.", "CNN 모델은 빠르다."])
        self.assertEqual(self.split("정말요?그렇군요!다행이네요."), ["정말요?", "그렇군요!", "다행이네요."])
        self.assertEqual(self.split("주문했다.“세계 경제”가 화두였다."), ["주문했다.", "“세계 경제”가 화두였다."])

    def test_non_boundaries(self):
        cases = [
            "가격은 3.5배, 버전 1.2.3이다.",
            "U.S. 정부는 e.g. 이런 방식을 쓴다.",
            "Dr. Kim과 J. K. Rowling vs. 저자 etc. 목록이다.",
            "자세한 내용은 https://example.com/a.b?x=1에 있다.",
            "문의는 kim.lee@example.co.kr 로 보낸다.",
            "1. 첫 항목은 짧다.",
            "그는 “안녕. 반가워!”라고 말했다.",
            "그는 (아마?) 왔다.",
            "2024. 10. 4. 오전에 만났다.",
            "Node.js와 README.md 파일을 연다.",
            "음…그래서 결국 왔다.",
            "`a.b()` 함수를 부른다.",
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(self.split(case), [case])

    def test_whitespace_newline_and_cmc_boundaries(self):
        self.assertEqual(self.split("첫 문장. 둘째 문장! 셋째?"), ["첫 문장.", "둘째 문장!", "셋째?"])
        self.assertEqual(self.split("줄 하나\n줄 둘"), ["줄 하나", "줄 둘"])
        self.assertEqual(self.split("좋았어요😀 ㅎㅎ 궁금한 점은 문의해 주세요."), ["좋았어요😀 ㅎㅎ", "궁금한 점은 문의해 주세요."])
        self.assertEqual(self.split("비 온대ㅋㅋ 우산 챙겨."), ["비 온대ㅋㅋ", "우산 챙겨."])
        self.assertEqual(self.split("좋아요. ㅋㅋ 그런데 말이죠"), ["좋아요. ㅋㅋ", "그런데 말이죠"])
        # "~" and "^^" alone are not boundaries (seed benchmark convention)
        self.assertEqual(self.split("먹었어요 ^^ 양이 많아서 놀랐어요~ 다음에 또 갈게요."),
                         ["먹었어요 ^^ 양이 많아서 놀랐어요~ 다음에 또 갈게요."])
        self.assertEqual(self.split("오전 9시~오후 6시에 엽니다."), ["오전 9시~오후 6시에 엽니다."])

    def test_quotes_are_masked_per_paragraph_and_unclosed_runs_to_paragraph_end(self):
        self.assertEqual(self.split("“끝나지 않은 인용. 계속된다. 정말."), ["“끝나지 않은 인용. 계속된다. 정말."])
        doc = text.segment("“열린 인용. 계속.\n\n새 문단. 둘째.")
        self.assertEqual([u.text for u in doc.units], ["“열린 인용. 계속.", "새 문단.", "둘째."])
        masked = text.mask_quotes("그는 “가. 나.”라고 했다.\n\n‘열림 다.")
        self.assertEqual(len(masked), len("그는 “가. 나.”라고 했다.\n\n‘열림 다."))
        self.assertEqual(masked, "그는 “ㅇㅇㅇㅇㅇ”라고 했다.\n\n‘ㅇㅇㅇㅇㅇ")
        self.assertEqual(text.mask_quotes("I don't know it's fine"), "I don't know it's fine")
        self.assertEqual(text.mask_quotes('5" 화면'), '5" 화면')     # a lone straight quote is not a quotation

    def test_offsets_with_astral_characters(self):
        zwj = chr(0x200D)
        sample = "앞 😀😀 문장입니다. 뒤 문장 👩" + zwj + "💻 입니다.\n\n𝒳 마지막."
        doc = text.segment(sample)
        utf16 = sample.encode("utf-16-le")
        self.assertEqual([u.text for u in doc.units], ["앞 😀😀 문장입니다.", "뒤 문장 👩" + zwj + "💻 입니다.", "𝒳 마지막."])
        for unit in doc.units:
            self.assertEqual(sample[unit.start:unit.end], unit.text)
            self.assertEqual(utf16[2 * unit.start_u16:2 * unit.end_u16].decode("utf-16-le"), unit.text)
        self.assertEqual([u.start_u16 - u.start for u in doc.units], [0, 2, 4])
        self.assertEqual([u.para for u in doc.units], [0, 0, 1])
        self.assertEqual([u.id for u in doc.units], ["S1", "S2", "S3"])
        units = text.split_sentences("𝒳 둘. 셋.", base=10, base_u16=12)
        self.assertEqual([(u.start, u.end, u.start_u16, u.end_u16) for u in units], [(10, 14, 12, 17), (15, 17, 18, 20)])

    def test_unit_kinds(self):
        sample = ("## 소제목\n본문 문장입니다.\n- 목록 항목입니다. 둘째 문장.\n1. 번호 항목\n> 인용 블록\n"
                  "▶ 무료 상담 예약하기\n[상담 신청하기]\n“전부 인용입니다.”\n제3조(목적)\n\n"
                  "오늘의 메뉴\n\n오늘은 김치찌개를 끓였습니다. 아주 맛있었어요.\n\n정말 맛있었어요\n\n긴 문단이 뒤에 옵니다. 정말로요.")
        kinds = [(u.text, u.kind) for u in text.segment(sample).units]
        self.assertEqual(kinds, [
            ("## 소제목", "heading"), ("본문 문장입니다.", "body"), ("- 목록 항목입니다.", "list"), ("둘째 문장.", "list"),
            ("1. 번호 항목", "list"), ("> 인용 블록", "quote"), ("▶ 무료 상담 예약하기", "button"),
            ("[상담 신청하기]", "button"), ("“전부 인용입니다.”", "quote"), ("제3조(목적)", "heading"),
            ("오늘의 메뉴", "heading"), ("오늘은 김치찌개를 끓였습니다.", "body"), ("아주 맛있었어요.", "body"),
            ("정말 맛있었어요", "body"), ("긴 문단이 뒤에 옵니다.", "body"), ("정말로요.", "body")])
        for line in ("1. 개요", "1) 항목", "가. 항목", "(주)지혜상사"):
            self.assertFalse(text.unmarked_heading(line, 200), line)

    def test_code_fences_are_one_unit_per_line(self):
        sample = "설명입니다.\n```\nx = 1. y = 2.\n\nprint(x)\n```\n끝."
        units = [u.text for u in text.segment(sample).units]
        self.assertEqual(units, ["설명입니다.", "```", "x = 1. y = 2.", "print(x)", "```", "끝."])

    def test_wp0_plan_fixtures_are_reproduced(self):
        for name, source in (("plan-blog-medium.json", BLOG_SOURCE), ("plan-no-edit.json", NO_EDIT_SOURCE)):
            plan = types.Plan.from_json(json.loads((FIXTURES / "sejong" / name).read_text(encoding="utf-8")))
            doc = text.segment(source)
            with self.subTest(fixture=name):
                self.assertEqual([(u.id, u.start, u.end, u.start_u16, u.end_u16, u.para, u.kind) for u in doc.units],
                                 [(s.id, s.start, s.end, s.start_u16, s.end_u16, s.para, s.kind) for s in plan.sentences])
                self.assertEqual([s.to_json() for s in protect.protected_spans(doc)], [s.to_json() for s in plan.protected])

    def test_seed_benchmark_sentence_spans(self):
        rows = seed_rows()
        gold = found = both = 0
        for row in rows:
            expected = {tuple(s["span"]) for s in row["voice_profile"]["sentence_levels"]}
            mine = {(u.start, u.end) for u in text.segment(row["text"]).units}
            gold, found, both = gold + len(expected), found + len(mine), both + len(expected & mine)
        # measured 2026-10-04: 1632 / 1632 sentences of 212 items agree exactly
        self.assertGreaterEqual(both / gold, 0.99)
        self.assertGreaterEqual(both / found, 0.99)

    def test_package_import_with_engine_runtime_on_sys_path(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import sejong.protect as p, sejong.text as t; "
                "print(len(p.protected_spans(t.segment('참가비는 3만 원입니다.'))))")
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        out = subprocess.run([sys.executable, "-c", code, str(ROOT / "engine_runtime")], capture_output=True,
                             text=True, env=env, check=True)
        self.assertEqual(out.stdout.strip(), "1")


class ProtectTests(unittest.TestCase):
    SAMPLE = ("## 제목 *강조*\n"
              "사실 그는 “좋다. 정말.”고 말했다. 2024년 3월 5일 10시에 20%p, 3배, $5, 5,000원, 3만 원. 할께요 ㅋㅋㅋ\n"
              "문의: 02-123-4567, 010-1234-5678, a@b.com, https://ex.com/x. @wisdom #태그 Apple 李文學 `code` "
              "**굵게** [링크](http://a.b/c)\n"
              "연구 결과다1)\n\n"
              "1) 각주 정의.\n")

    def spans(self, sample, **kw):
        doc = text.segment(sample)
        return [(s.kind, s.policy, sample[s.start:s.end]) for s in protect.protected_spans(doc, **kw)]

    def test_each_span_kind(self):
        found = self.spans(self.SAMPLE)
        expected = [
            ("heading", "freeze", "## 제목 *강조*"), ("discourse", "keep-token", "사실"),
            ("quote", "freeze", "“좋다. 정말.”"), ("date", "freeze", "2024년 3월 5일"), ("number", "freeze", "10시"),
            ("number", "freeze", "20%p"), ("number", "freeze", "3배"), ("money", "freeze", "$5"),
            ("number", "freeze", "5,000원"), ("number", "freeze", "3만 원"), ("colloquial", "keep-token", "할께요"),
            ("cmc", "keep-token", "ㅋㅋㅋ"), ("phone", "freeze", "02-123-4567"), ("phone", "freeze", "010-1234-5678"),
            ("email", "freeze", "a@b.com"), ("url", "freeze", "https://ex.com/x"), ("handle", "freeze", "@wisdom"),
            ("hashtag", "freeze", "#태그"), ("name", "freeze", "Apple"), ("name", "freeze", "李文學"),
            ("code", "freeze", "`code`"), ("markdown", "freeze", "**"), ("markdown", "freeze", "**"),
            ("markdown", "freeze", "["), ("markdown", "freeze", "](http://a.b/c)"), ("footnote", "freeze", "1)"),
            ("footnote", "freeze", "1) 각주 정의.")]
        self.assertEqual(found, expected)
        # together with the fenced block in test_remaining_kinds this covers every SPAN_KINDS entry
        self.assertEqual({kind for kind, _, _ in found} | {"code"}, set(types.SPAN_KINDS))

    def test_remaining_kinds_and_policies(self):
        self.assertIn(("code", "freeze", "```\nx = 1\n```"), self.spans("설명.\n```\nx = 1\n```\n끝."))
        self.assertIn(("markdown", "freeze", "- "), self.spans("- 항목입니다."))
        self.assertIn(("markdown", "freeze", "> "), self.spans("> 인용 블록입니다."))
        self.assertIn(("money", "freeze", "10달러"), self.spans("값은 10달러입니다."))
        self.assertIn(("date", "freeze", "09:30"), self.spans("09:30에 만나요."))
        self.assertIn(("quote", "freeze", "‘열린 인용은 문단 끝까지"), self.spans("그는 ‘열린 인용은 문단 끝까지\n\n새 문단."))
        self.assertIn(("colloquial", "keep-token", "전화할께"), self.spans("이따 전화할께."))
        self.assertIn(("colloquial", "keep-token", "할 꺼야"), self.spans("내가 할 꺼야."))
        self.assertIn(("colloquial", "keep-token", "걍"), self.spans("걍 가자."))
        self.assertIn(("discourse", "keep-token", "진짜"), self.spans("진짜 맛있어요."))
        self.assertIn(("cmc", "keep-token", "😀"), self.spans("좋아요😀"))

    def test_counterexamples_are_not_protected(self):
        kinds = {kind for kind, _, _ in self.spans("선생님께 드렸다. 할아버지께서 오셨다. 사실을 확인했다. 3세대 기술.")}
        self.assertNotIn("colloquial", kinds)
        self.assertNotIn("discourse", kinds)
        self.assertNotIn(("number", "freeze", "3세"), self.spans("3세대 기술."))
        self.assertEqual([k for k, _, _ in self.spans("오전 9시~오후 6시")], ["number", "number"])
        # 할려면 is an error to fix (DESIGN 9.2a item 1), never a keep token
        self.assertNotIn("colloquial", {k for k, _, _ in self.spans("일찍 일어날려면 자야 해.")})
        self.assertEqual(self.spans("세 배로 늘었다."), [])       # number words are left to the quantities floor
        # false positives found on KatFish + KLUE MRC (2,432 documents) and fixed
        for sample in ("베이징에 간다.", "다음달께 착공한다.", "15일께 발표한다.", "어른들께 인사했다.", "유아용 세제다.",
                       "이세용 대표가 왔다.", "방어용 조치다.", "젤, 왁스 등이다."):
            with self.subTest(sample=sample):
                self.assertNotIn("colloquial", {k for k, _, _ in self.spans(sample)})
        for sample in ("5 ~ 6,000만원", "25~50%", "기원전 900년경 ~ 기원전 206년", "O ~ B 항성"):
            with self.subTest(sample=sample):
                self.assertNotIn("cmc", {k for k, _, _ in self.spans(sample)})
        self.assertNotIn("phone", {k for k, _, _ in self.spans("재위 1099-1118 시기")})
        self.assertNotIn("footnote", {k for k, _, _ in self.spans("지수(2002년=100)는 기준이다. 면적은 4,959m²다.")})
        self.assertIn(("footnote", "freeze", "¹"), self.spans("각주¹ 내용."))

    def test_fix_colloquial_drops_opt_in_kinds_only(self):
        kinds = {kind for kind, _, _ in self.spans(self.SAMPLE, fix_colloquial=True)}
        self.assertNotIn("colloquial", kinds)
        self.assertNotIn("discourse", kinds)
        self.assertIn("cmc", kinds)

    def test_freeze_spans_merge_and_keep_tokens_inside_them_are_dropped(self):
        found = self.spans("그는 “3만 원이야 ㅋㅋ”라고 했다.")
        self.assertEqual(found, [("quote", "freeze", "“3만 원이야 ㅋㅋ”")])
        spans = protect.protected_spans(text.segment(self.SAMPLE))
        for a, b in zip(spans, spans[1:]):
            self.assertLessEqual(a.end, b.start)

    def test_keep_tokens(self):
        tokens = protect.keep_tokens("사실 할께요 ㅋㅋㅋㅋ 😀😀 좋아요~~ 그는 “ㅎㅎ”라고 했다.")
        self.assertEqual(tokens, {("discourse", "사실"): 1, ("colloquial", "할께요"): 1, ("cmc", "ㅋㅋ"): 1,
                                  ("cmc", "😀"): 2, ("cmc", "~"): 1})
        self.assertEqual(protect.keep_tokens("ㅋㅋ 좋다"), protect.keep_tokens("좋다 ㅋㅋㅋㅋㅋ"))
        self.assertEqual(protect.keep_tokens("사실 할께요 ㅋㅋ", fix_colloquial=True), {("cmc", "ㅋㅋ"): 1})

    def test_freeze_intact(self):
        doc = text.segment("참가비는 3만 원이고 “꼭 오세요”라고 했다. 링크는 https://ex.com 입니다.")
        spans = protect.protected_spans(doc)
        first, second = doc.units
        self.assertTrue(protect.freeze_intact(first, first.text, spans))
        self.assertTrue(protect.freeze_intact(first, "“꼭 오세요”라는 말과 함께 참가비는 3만원이라고 했다.", spans))
        self.assertFalse(protect.freeze_intact(first, "참가비는 4만 원이고 “꼭 오세요”라고 했다.", spans))
        self.assertFalse(protect.freeze_intact(first, "참가비는 3만 원이고 “꼭 와 주세요”라고 했다.", spans))
        self.assertTrue(protect.freeze_intact(second, "링크는 https://ex.com 이에요.", spans))
        self.assertFalse(protect.freeze_intact(second, "링크는 https://ex.co 입니다.", spans))
        self.assertEqual([s.kind for s in protect.spans_in(second, spans)], ["url"])

    def test_seed_quotations_and_keep_tokens_are_covered(self):
        missing = []
        for row in seed_rows():
            spans = protect.protected_spans(text.segment(row["text"]))

            def covered(a, b):
                return any(s.start <= a and b <= s.end for s in spans)
            for quote in row["protected_spans"]:
                if not covered(*quote["span"]):
                    missing.append((row["id"], "quote"))
            for token in row["protected_tokens"]:
                if token["text"].endswith("려면"):
                    continue            # an error under DESIGN 9.2a item 1, not a keep token
                for a, b in token["spans"]:
                    if not covered(a, b):
                        missing.append((row["id"], token["kind"], token["text"]))
        self.assertEqual(missing, [])


def best_of(runs, fn, sample):
    best = None
    for _ in range(runs):
        start = time.perf_counter()
        fn(sample)
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    return best


def segment_and_protect(sample):
    protect.protected_spans(text.segment(sample))


class PerformanceTests(unittest.TestCase):
    BASE = ("오늘은 세미나 후기를 정리합니다.논문에서는 3.5배 증가했다고 합니다. 참가비는 3만 원이에요😀 ㅎㅎ "
            "문의는 02-123-4567, a@b.com, https://ex.com/x 로 주세요. 그는 “좋다. 정말.”이라고 말했다. "
            "U.S. 정부는 e.g. 이렇게 했다(아마?). **강조** [링크](http://a.b) 할께요 ㅋㅋ\n\n## 소제목\n- 항목입니다.\n")
    SHAPES = {
        "realistic": lambda n: (PerformanceTests.BASE * (n // len(PerformanceTests.BASE) + 1))[:n],
        "unclosed_quote": lambda n: "“" + "가나다라마. " * (n // 7),
        "one_sentence": lambda n: "가" * n,
        "tilde_run": lambda n: "좋아요" + "~" * n + "가",
        "laughter_run": lambda n: "ㅋ" * n + "x",
        "emphasis_marks": lambda n: "**a " * (n // 4),
        "many_quotes": lambda n: "“가.” " * (n // 5),
        "many_lines": lambda n: "가.\n" * (n // 3),
        "open_brackets": lambda n: "[" * n,
        "hyphen_chain": lambda n: "a-" * (n // 2),
    }

    def test_mask_quotes_on_a_100k_unclosed_quote(self):
        sample = "“" + "가나다라마 바사아. " * 10_000
        self.assertGreaterEqual(len(sample), 100_000)
        elapsed = best_of(3, text.mask_quotes, sample)
        self.assertLessEqual(elapsed, 0.050, f"{elapsed * 1000:.1f} ms")
        masked = text.mask_quotes(sample)
        self.assertEqual(len(masked), len(sample))
        self.assertEqual((masked[0], set(masked[1:])), ("“", {text.MASK_CHAR}))

    def test_no_superlinear_path(self):
        for name, build in self.SHAPES.items():
            small, large = build(10_000), build(100_000)
            t_small = max(best_of(3, segment_and_protect, small), 0.002)
            t_large = best_of(2, segment_and_protect, large)
            with self.subTest(shape=name):
                self.assertLessEqual(t_large / t_small, 15, f"{name}: {t_small * 1000:.1f} ms -> {t_large * 1000:.1f} ms")
                self.assertLessEqual(t_large, 2.0, name)


if __name__ == "__main__":
    unittest.main()


class VersionNumbers(unittest.TestCase):
    def test_a_dotted_version_is_frozen_whole(self):
        doc = text.segment("버전은 1.2.3입니다. 비율은 3.5%입니다.\n")
        frozen = [doc.text[s.start:s.end] for s in protect.protected_spans(doc) if s.policy == "freeze"]
        self.assertIn("1.2.3", frozen)
        self.assertIn("3.5%", frozen)
