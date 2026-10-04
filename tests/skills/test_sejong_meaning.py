"""Super Sejong Engine v2 meaning and floor families (WP-5, DESIGN.md 3.3, 3.8, 8.2).

meaning.compare/check must keep the v1 guard rates of the 555 evaluation pairs (they reuse
engine_runtime/super_sejong.py unchanged), add the aspect and partial-negation axes, and never
flag an unchanged text. floor.check must report the legacy gate's codes (vendor checks.py and
workflow.verify) without importing the vendor module; the differential tests import the vendor
only to compare and are skipped once vendor/ is removed (WP-18).
"""
import json
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine_runtime"))
from engine_runtime import super_sejong as ss  # noqa: E402
from sejong import floor, meaning, protect  # noqa: E402
from sejong import text as T  # noqa: E402
from sejong.types import CODE_RE, Violation  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
BENCH = ROOT / "docs" / "research" / "super-sejong" / "v2" / "benchmark"
VENDOR = ROOT / "vendor" / "humanize-engine"
NEW_AXES = {"aspect_changed", "partial_negation_changed"}


def seed_records():
    rows = []
    for name in ("seed_benchmark.jsonl", "seed_composites.jsonl"):
        rows += [json.loads(line) for line in (BENCH / name).read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def seed_texts():
    for record in seed_records():
        for key in ("text", "gold_text", "gold_text_optin_colloquial_fix"):
            if record.get(key):
                yield record["id"], key, record[key]


def legacy_flagged(source, candidate):
    """test_super_sejong_guards.flagged(): the four workflow guards plus the Office drift guard."""
    return any((ss.changed_polarity(source, candidate), ss.changed_sentence_modality(source, candidate),
                ss.changed_lexical_polarity(source, candidate), ss.changed_participant_roles(source, candidate),
                ss.document_sentence_drift(source, candidate)))


def v2_flagged(source, candidate):
    return bool(meaning.check(T.segment(source), T.segment(candidate)))


class NewAxes(unittest.TestCase):
    def test_aspect_and_partial_negation_pairs(self):
        pairs = json.loads((DATA / "sejong_aspect_pairs.json").read_text(encoding="utf-8"))["pairs"]
        self.assertGreaterEqual(len(pairs), 40)
        for pair in pairs:
            with self.subTest(source=pair["source"], rewrite=pair["rewrite"]):
                code = "aspect_changed" if pair["axis"] == "aspect" else "partial_negation_changed"
                found = {v.code for v in meaning.compare(pair["source"], pair["rewrite"])}
                self.assertEqual(code in found, pair["expect"] == "flag", found)
                # the other new axis never fires on these pairs
                self.assertFalse(found & NEW_AXES - {code}, found)

    def test_design_examples(self):
        # DESIGN 8.2 WP-5 flagged 읽고 있다 -> 읽는다; WP-10b (lead item A) makes progressive -> simple non-past
        # neutral and keeps progressive -> past/future flagged. 읽고 있다 -> 읽는 중이다 stays accepted.
        self.assertEqual(meaning.compare("그는 책을 읽고 있다.", "그는 책을 읽는다."), [])
        flagged = meaning.compare("그는 책을 읽고 있다.", "그는 책을 읽었다.")
        self.assertEqual([v.code for v in flagged], ["aspect_changed"])
        self.assertEqual((flagged[0].family, flagged[0].severity, flagged[0].detail), ("meaning", "hard", "PROG:1->PAST"))
        self.assertEqual(meaning.compare("그는 책을 읽고 있다.", "그는 책을 읽는 중이다."), [])
        # "모든 …는 것은 아니다" must stay partial.
        self.assertIn("partial_negation_changed",
                      {v.code for v in meaning.compare("모든 사람이 동의하는 것은 아니다.", "모든 사람이 동의하지 않는다.")})
        self.assertNotIn("partial_negation_changed",
                         {v.code for v in meaning.compare("모든 사람이 동의하는 것은 아니다.", "모든 사람이 동의하지는 않는다.")})

    def test_violation_shape_and_sentence_ids(self):
        src = T.segment("첫 문장은 그대로다. 그는 책을 읽고 있다.")
        out = T.segment("첫 문장은 그대로다. 그는 책을 읽었다.")
        found = meaning.check(src, out)
        self.assertEqual([(v.code, v.sentence) for v in found], [("aspect_changed", "S2")])
        for v in found:
            self.assertIsInstance(v, Violation)
            self.assertTrue(CODE_RE.match(v.code))
            self.assertIn(v.code, meaning.CODES)

    def test_unpaired_half_of_a_split_is_compared_with_its_neighbour(self):
        # WP-2 aligns this as 1:1 + 0:1; the moved clause must not count as lost.
        self.assertEqual(meaning.check(T.segment("이 앱은 빠르고 가볍지만 기능이 적다."),
                                       T.segment("이 앱은 빠르고 가볍다. 다만 기능은 적다.")), [])


class OrderSwapRegression(unittest.TestCase):
    """OD 8 / T1 §1.9: an unchanged sentence with two 전에/후에 frames is not an order swap."""
    SENTENCE = "보고서를 제출하기 전에 내용을 확인하고 제출한 후에 결과를 공유합니다."

    @staticmethod
    def old_rule(before, after):
        # The pre-fix _order_swapped compared every ordering with every other.
        ra, rb = ss._orderings(before), ss._orderings(after)
        return any(ss._overlap(e1, l2) + ss._overlap(l1, e2) > ss._overlap(e1, e2) + ss._overlap(l1, l2)
                   and ss._overlap(e1, l2) + ss._overlap(l1, e2) >= 1.0
                   for e1, l1 in ra for e2, l2 in rb)

    def test_identical_sentence_with_two_frames(self):
        self.assertTrue(self.old_rule(self.SENTENCE, self.SENTENCE))      # the sentence reproduces the old bug
        self.assertFalse(ss._order_swapped(self.SENTENCE, self.SENTENCE))
        self.assertEqual(meaning.codes(self.SENTENCE, self.SENTENCE), [])
        edited = self.SENTENCE.replace("내용을", "내용을 꼼꼼히")
        self.assertEqual(meaning.codes(self.SENTENCE, edited), [])

    def test_real_swap_still_caught(self):
        for source, candidate in [("식사하기 전에 손을 씻는다.", "식사한 후에 손을 씻는다."),
                                  ("손을 씻은 뒤에 식사를 한다.", "식사를 한 뒤에 손을 씻는다.")]:
            with self.subTest(source=source):
                self.assertIn("lexical_polarity_changed", {code for code, _ in meaning.codes(source, candidate)})


class Identity(unittest.TestCase):
    """compare(x, x) and floor(x, x) are empty on every seed benchmark text (DESIGN 3.9 invariant)."""

    def test_seed_texts(self):
        texts = list(seed_texts())
        self.assertGreaterEqual(len(texts), 600)
        units = 0
        for rid, key, text in texts:
            with self.subTest(record=rid, field=key):
                self.assertEqual(floor.check(text, text), [])
                doc = T.segment(text)
                spans = protect.protected_spans(doc)
                self.assertEqual(meaning.check(doc, doc), [])
                for unit in doc.units:
                    units += 1
                    # codes() runs every guard, without compare()'s identical-text shortcut
                    self.assertEqual(meaning.codes(unit.text, unit.text), [], unit.id)
                    self.assertEqual(floor.text_codes(unit.text, unit.text), [], unit.id)
                    self.assertTrue(protect.freeze_intact(unit, unit.text, spans), unit.id)
        self.assertGreater(units, 3000)


class Rates555(unittest.TestCase):
    """The v2 meaning family on WP-1 segments + WP-2 alignment must not regress the 555-pair rates.
    Measured 2026-10-04 (legacy = v2): lead 1/20 over, 0/20 unsafe; res1 7/60, 11/60; code1 8/207, 0/188."""

    def test_no_regression_per_set(self):
        pairs = json.loads((DATA / "super_sejong_pairs.json").read_text(encoding="utf-8"))["pairs"]
        for name in ("lead", "res1", "code1"):
            rows = [p for p in pairs if p["set"] == name]
            preserve = [p for p in rows if p["label"] == "preserve"]
            change = [p for p in rows if p["label"] == "change"]
            legacy_over = sum(legacy_flagged(p["source"], p["rewrite"]) for p in preserve)
            legacy_unsafe = sum(not legacy_flagged(p["source"], p["rewrite"]) for p in change)
            over = sum(v2_flagged(p["source"], p["rewrite"]) for p in preserve)
            unsafe = sum(not v2_flagged(p["source"], p["rewrite"]) for p in change)
            with self.subTest(set=name):
                self.assertLessEqual(over, legacy_over)
                self.assertLessEqual(unsafe, legacy_unsafe)


class Ledger(unittest.TestCase):
    PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*(:[^\s]{1,80})?$")      # plan.schema.json sentence.meaning

    def test_entries(self):
        entries = meaning.ledger("모든 학생이 지금 시험을 보고 있지 않은 것은 아니다.")
        self.assertIn("ASPECT_PROG:1", entries)
        self.assertIn("PARTIAL_NEG:1", entries)
        self.assertTrue(any(e.startswith("NEG:") for e in entries))
        self.assertIn("BOUND:GE:30.0", meaning.ledger("참가자는 30명 이상이어야 한다."))
        self.assertIn("OBLIG:1", meaning.ledger("참가자는 30명 이상이어야 한다."))
        self.assertEqual(meaning.ledger("오늘은 맑다."), [])
        for _, _, text in list(seed_texts())[:80]:
            for unit in T.segment(text).units:
                for entry in meaning.ledger(unit.text):
                    self.assertRegex(entry, self.PATTERN)

    def test_legacy_wrappers(self):
        for name in ("changed_polarity", "changed_sentence_modality", "changed_lexical_polarity",
                     "changed_participant_roles", "document_sentence_drift", "polarity_count", "sentences"):
            self.assertTrue(callable(getattr(meaning, name)), name)


class FloorCodes(unittest.TestCase):
    EXPECTED = ("empty_output", "quote_altered", "heading_lost", "heading_absorbed", "footnote_count",
                "footnote_numbers", "footnote_def", "footnote_anchor", "number_injected", "number_dropped",
                "quantity_changed", "name_changed", "sentence_dropped", "protected_span_changed", "josa_mismatch")

    def test_design_row(self):
        self.assertEqual(floor.CODES, self.EXPECTED)
        self.assertTrue(all(CODE_RE.match(code) for code in floor.CODES))

    @unittest.skipUnless((VENDOR / "scripts" / "checks.py").is_file(), "vendor removed")
    def test_names_identical_to_legacy(self):
        vendor = (VENDOR / "scripts" / "checks.py").read_text(encoding="utf-8")
        workflow = (ROOT / "engine_runtime" / "workflow.py").read_text(encoding="utf-8")
        legacy = set(re.findall(r'Failure\(\s*"([a-z_]+)"', vendor)) | set(re.findall(r'append\("([a-z_]+)"\)', workflow))
        for code in floor.CODES:
            if code == "protected_span_changed":      # new in v2 (DESIGN 3.1)
                continue
            self.assertIn(code, legacy)
        self.assertNotIn("protected_span_changed", legacy)

    def test_floor_module_does_not_import_the_vendor(self):
        source = (ROOT / "engine_runtime" / "sejong" / "floor.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^\s*(?:import|from)\s+(?:checks|verify_gates|restore_modality)\b")
        self.assertNotRegex(source, r"sys\.path\.(?:insert|append)|importlib")


class FloorPair(unittest.TestCase):
    def test_sentence_pair_codes(self):
        doc = T.segment("참가비는 3만 원입니다. 그는 “오늘까지 신청하세요”라고 말했다.")
        spans = protect.protected_spans(doc)
        first, second = doc.units
        self.assertEqual(floor.check_pair(first, "참가비는 3만원입니다.", spans), [])
        self.assertEqual(floor.codes(floor.check_pair(first, "참가비는 4만 원입니다.", spans)),
                         ["number_injected", "quantity_changed", "number_dropped", "protected_span_changed"])
        self.assertEqual(floor.codes(floor.check_pair(second, "그는 “내일까지 신청하세요”라고 말했다.", spans)),
                         ["quote_altered", "protected_span_changed"])
        self.assertEqual([(v.code, v.sentence) for v in floor.check_pair(first, "", spans)], [("sentence_dropped", "S1")])
        self.assertEqual(floor.codes(floor.check_pair("서버가 API를 호출한다.", "서버가 API을 호출한다.")), ["josa_mismatch"])
        self.assertEqual(floor.codes(floor.check_pair("Apple이 발표했다.", "애플이 발표했다.")), ["name_changed"])

    def test_document_codes(self):
        self.assertEqual(floor.codes(floor.check("본문입니다.", "  ")), ["empty_output"])
        self.assertEqual(floor.check("", ""), [])
        found = floor.check("# 안내\n\n본문입니다.", "본문입니다.")
        self.assertEqual(floor.codes(found)[0], "heading_lost")
        dropped = floor.check("서버가 멈췄다. 원인을 찾았다. 조치를 완료했다.", "서버가 멈췄다. 조치를 완료했다.")
        self.assertEqual([(v.code, v.sentence) for v in dropped], [("sentence_dropped", "S2")])
        # a merge keeps the absorbed sentence's words
        self.assertEqual(floor.check("비가 많이 왔다. 행사는 연기되었다.", "비가 많이 와서 행사는 연기되었다."), [])

    def test_repeated_footnote_marker_is_not_an_anchor_move(self):
        text = "2020년 매출이 늘었다.1) 2021년에도 늘었다.1)\n\n1) 연례 보고서"
        self.assertEqual(floor.footnote_codes(text, text), [])
        self.assertEqual(floor.check(text, text), [])


@unittest.skipUnless((VENDOR / "scripts" / "checks.py").is_file(), "vendor removed")
class FloorDifferential(unittest.TestCase):
    """floor.check against the legacy floor (workflow.verify's codes) on seed rewrites and mutations."""

    @classmethod
    def setUpClass(cls):
        from engine_runtime import workflow
        from engine_runtime import super_sejong_josa as josa
        from engine_runtime.quantities import fold_width, number_words, signed_quantities
        _, checks, modality, _ = workflow.modules(workflow.DEFAULT_VENDOR)

        def legacy(source, output):
            wide_source, wide_output = fold_width(source), fold_width(output)
            word_source = {str(int(value)) for value, _ in number_words(wide_source)}
            word_output = {str(int(value)) for value, _ in number_words(wide_output)}
            hard = checks.check_quotes(source, output) + checks.check_headings(source, output)
            hard += checks.check_footnotes(source, output, None)
            codes = sorted({failure.code for failure in hard})
            if checks._number_values(wide_output) - checks._number_values(wide_source) - word_source:
                codes.append("number_injected")
            if signed_quantities(source) != signed_quantities(output):
                codes.append("quantity_changed")
            if any(q not in output and checks._is_protected_quote(source, q)
                   for q in checks.extract_quotes(source, min_len=1)) and "quote_altered" not in codes:
                codes.append("quote_altered")
            if set(checks.dropped_numbers(wide_source, wide_output)) - word_output:
                codes.append("number_dropped")
            if workflow.names(source, checks) != workflow.names(output, checks):
                codes.append("name_changed")
            if workflow.dropped_sentences(source, output, checks, modality):
                codes.append("sentence_dropped")
            if josa.gate(source, output, None, "certain"):
                codes.append("josa_mismatch")
            return codes

        cls.legacy = staticmethod(legacy)
        cls.checks = checks

    @staticmethod
    def mutations(text):
        doc = T.segment(text)
        body = [u for u in doc.units if u.kind == "body"]
        out = {}
        m = re.search(r"\d+", text)
        if m:
            out["number"] = text[:m.start()] + str(int(m.group()) + 7) + text[m.end():]
        m = re.search(r"“([^”]{2,})”", text)
        if m:
            out["quote"] = text[:m.start(1)] + "바뀐 " + m.group(1)[1:] + text[m.end(1):]
        m = re.search(r"(?m)^#{1,6} .*\n?", text)
        if m:
            out["heading"] = text[:m.start()] + text[m.end():]
        if len(body) >= 3:
            out["drop"] = text[:body[1].start] + text[body[1].end:]
        m = re.search(r"(?<=\S)(\d{1,3})\)", text)
        if m:
            out["footnote"] = text[:m.start()] + text[m.end():]
        return out

    def test_text_level_codes_agree(self):
        sentence_level = {"sentence_dropped", "protected_span_changed"}
        compared = drops = 0
        for record in seed_records():
            cases = [(record["text"], record["gold_text"]), (record["gold_text"], record["text"])]
            cases += [(record["text"], output) for output in self.mutations(record["text"]).values()]
            for source, output in cases:
                if source == output:
                    continue
                compared += 1
                legacy = set(self.legacy(source, output))
                v2 = set(floor.codes(floor.check(source, output)))
                with self.subTest(record=record["id"]):
                    self.assertEqual(legacy - sentence_level, v2 - sentence_level)
                    if "sentence_dropped" in legacy:
                        drops += 1
                        self.assertIn("sentence_dropped", v2)
        self.assertGreater(compared, 300)
        self.assertGreater(drops, 50)

    def test_quote_extraction_matches_vendor(self):
        import random
        rng = random.Random(3)
        alphabet = "“”「」『』\"가나 \n"
        for _ in range(3000):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
            self.assertEqual(floor.extract_quotes(text, 1), self.checks.extract_quotes(text, 1), repr(text))


class Performance(unittest.TestCase):
    """100k-character adversarial shapes stay linear (DESIGN 6: ≤ 2 s per stage; 3 s here for CI noise)."""
    N = 100_000

    def test_adversarial_100k(self):
        rep = lambda unit: (unit * (self.N // len(unit) + 1))[:self.N]
        shapes = {"progressive": rep("하고 있 "), "resultative": rep("앉아 있"), "jung": rep("진행 중이 "),
                  "partial": rep("모든 것은 아니 "), "existential": rep("않는 사람도 있"), "open_quote": rep("“가나다라 "),
                  "markers": rep("다.1) "), "tiny_sentences": rep("가. "), "short_neg": rep("안 ")}
        for name, text in shapes.items():
            other = text[:-12] + " 바뀐 끝 문장이다."
            with self.subTest(shape=name):
                started = time.perf_counter()
                meaning.compare(text, other)
                self.assertLess(time.perf_counter() - started, 3.0)
                started = time.perf_counter()
                floor.check(text, other)
                self.assertLess(time.perf_counter() - started, 3.0)


if __name__ == "__main__":
    unittest.main()
