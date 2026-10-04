"""Super Sejong Engine v2 chunking, seams and reassembly (WP-3, DESIGN.md 3.2, 3.10, 4.4).

Constructed text only. Small `max_single`/`target`/`cap` values keep the fixtures short; the rules do
not depend on the absolute sizes. The vendor chunker (vendor/humanize-engine) and T5's connective
functions (docs/research/super-sejong/v2/prototypes/T5_flowlib.py) are loaded as references.
"""
import hashlib
import importlib.util
import json
import math
import random
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine_runtime"))
from sejong import chunk  # noqa: E402

SEED = ROOT / "docs" / "research" / "super-sejong" / "v2" / "benchmark"
PROTOTYPES = ROOT / "docs" / "research" / "super-sejong" / "v2" / "prototypes"
VENDOR_PREPARE = ROOT / "vendor" / "humanize-engine" / "scripts" / "prepare_monolith_input.py"
PYTHON_ENGINE_TS = ROOT / "src" / "engine" / "python-engine.ts"

SMALL = dict(max_single=1500, target=1000, cap=1300)        # the floor of a moved cut is then 500
MANIFEST_KEYS = {"version", "created", "source_file", "source_chars", "source_sha256", "genre", "target_chunk_chars",
                 "max_chunk_chars", "route_hint", "route_reason", "processing_mode", "chunk_count", "body_chunk_count",
                 "passthrough_chunk_count", "lossless_check", "warnings", "chunks"}
ENTRY_KEYS = {"index", "start", "end", "char_count", "starts_with_heading", "heading", "passthrough", "input_file",
              "rewritten_file"}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def para(n, tag="알파"):
    """A paragraph of exactly n characters that opens with `tag` and ends like a sentence."""
    filler = ("가나다라마바사아자차카타파하" * (n // 14 + 2))[:max(0, n - len(tag) - 1)]
    out = tag + filler + "."
    assert len(out) == n, (len(out), n)
    return out


def doc(*paragraphs):
    return "\n\n".join(paragraphs) + "\n"


def exact_doc(size):
    """A document of exactly `size` characters made of 300-character paragraphs and a last, longer one."""
    count = (size - 100) // 302
    paragraphs = [para(300, f"가{i:03d}") for i in range(count)]
    paragraphs.append(para(size - count * 302, "끝"))
    text = "\n\n".join(paragraphs)
    assert len(text) == size
    return text


def sentence_paragraph(n):
    """A paragraph of about n characters made of whole sentences (for sentence-level cuts)."""
    templates = ["자료는 공유 폴더에 올려 두었습니다.", "다음 일정은 목요일 오후에 정해집니다.", "참석하지 못한 분들도 내용을 확인할 수 있어요.",
                 "준비물은 따로 없으니 편하게 오시면 됩니다.", "회의실 예약은 총무팀에서 맡고 있어요.", "의견은 메일로 보내 주시면 정리하겠습니다.",
                 "점심은 근처 식당에서 함께 먹었어요.", "장소는 지난번과 같은 건물 삼 층입니다."]
    out, i = [], 0
    while sum(len(s) + 1 for s in out) < n:
        out.append(templates[i % len(templates)])
        i += 1
    return " ".join(out)


class RunDir:
    """A temporary run directory holding 01_input.txt."""

    def __init__(self, text):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        with open(self.path / "01_input.txt", "w", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def close(self):
        self._tmp.cleanup()

    def source(self):
        with open(self.path / "01_input.txt", encoding="utf-8", newline="") as handle:
            return handle.read()


class ChunkCase(unittest.TestCase):
    def prepared(self, text, **options):
        run = RunDir(text)
        self.addCleanup(run.close)
        return run, chunk.prepare(run.path, **options)

    @staticmethod
    def pieces_of(run, manifest):
        source = run.source()
        return [source[c["start"]:c["end"]] for c in manifest["chunks"]]

    @staticmethod
    def first_line(text):
        return next((line for line in text.split("\n") if line.strip()), "").strip()

    @staticmethod
    def last_line(text):
        return next((line for line in reversed(text.split("\n")) if line.strip()), "").strip()


# ==========================================================================
# lossless, single span, footnotes
# ==========================================================================
class LosslessTests(ChunkCase):
    def test_spans_tile_the_text_and_sha_matches(self):
        rows = [json.loads(line) for line in (SEED / "seed_composites.jsonl").read_text(encoding="utf-8").splitlines()]
        long_doc = "\n\n".join(r["text"] for r in rows)
        astral = doc(*[para(300, "😀사진") for _ in range(12)])
        for label, text, options in (("composites", long_doc, {}), ("composites small", long_doc, SMALL),
                                     ("astral", astral, dict(max_single=800, target=700, cap=900)),
                                     ("no trailing newline", long_doc.rstrip("\n"), SMALL)):
            with self.subTest(label):
                run, manifest = self.prepared(text, **options)
                source = run.source()
                self.assertEqual(hashlib.sha256(source.encode("utf-8")).hexdigest(), manifest["source_sha256"])
                self.assertEqual(manifest["source_chars"], len(source))
                chunks = manifest["chunks"]
                self.assertEqual(chunks[0]["start"], 0)
                self.assertEqual(chunks[-1]["end"], len(source))
                for a, b in zip(chunks, chunks[1:]):
                    self.assertEqual(a["end"], b["start"])
                for c in chunks:
                    self.assertEqual(c["char_count"], c["end"] - c["start"])
                self.assertEqual("".join(self.pieces_of(run, manifest)), source)

    def test_sanitize_in_place_then_chunk_the_cleaned_file(self):
        dirty = "첫 문단입니다.\r\n\r\n" + "둘째" + chr(0x200B) + " 문단입니다.\r\n\r\n" + "셋째 문단입니다.   \r\n"
        run, manifest = self.prepared(dirty)
        source = run.source()
        self.assertNotIn("\r", source)
        self.assertNotIn(chr(0x200B), source)
        report = json.loads((run.path / "00_sanitize.json").read_text(encoding="utf-8"))
        self.assertTrue(report["changed"])
        self.assertEqual(manifest["source_chars"], len(source))
        self.assertEqual(hashlib.sha256(source.encode("utf-8")).hexdigest(), manifest["source_sha256"])

    def test_clean_input_writes_no_sanitize_report(self):
        run, _ = self.prepared(doc(para(200), para(200)))
        self.assertFalse((run.path / "00_sanitize.json").exists())

    def test_sanitize_can_be_switched_off_and_offsets_stay_valid(self):
        text = "첫 문단입니다.\r\n\r\n둘째 문단입니다.\r\n"
        run, manifest = self.prepared(text, sanitize_input=False)
        self.assertEqual(run.source(), text)
        self.assertEqual("".join(self.pieces_of(run, manifest)), text)

    def test_empty_and_blank_input_fail(self):
        for text in ("", "\n\n  \n"):
            with self.subTest(text=text):
                run = RunDir(text)
                self.addCleanup(run.close)
                with self.assertRaises(chunk.ChunkingError):
                    chunk.prepare(run.path)

    def test_lossless_self_check_raises(self):
        original = chunk._Scan

        class Broken(original):
            def _pieces(self):
                pieces = super()._pieces()
                pieces[-1].end -= 1                      # a gap at the end
                return pieces

        chunk._Scan = Broken
        try:
            with self.assertRaises(chunk.ChunkingError):
                chunk.compute_spans(doc(para(400), para(400)), **SMALL)
        finally:
            chunk._Scan = original

    def test_re_chunking_removes_stale_files_and_is_stable(self):
        run, first = self.prepared(doc(*[para(300) for _ in range(10)]), **SMALL)
        stale = ("02_chunk_01_rewritten.txt", "03_reassembled.md", "03_reassembly_report.json", "00_chunk_01_metrics.json",
                 "01_chunk_09_input_with_metrics.txt")
        for name in stale:
            (run.path / name).write_text("stale", encoding="utf-8")
        second = chunk.prepare(run.path, **SMALL)
        for name in stale:
            self.assertFalse((run.path / name).exists(), name)
        for key in first:
            if key != "created":
                self.assertEqual(first[key], second[key], key)

    def test_chunk_input_files_hold_the_plain_chunk_text(self):
        run, manifest = self.prepared(doc(*[para(300) for _ in range(10)]), **SMALL)
        source = run.source()
        for c in manifest["chunks"]:
            if not c["passthrough"]:
                self.assertEqual((run.path / c["input_file"]).read_text(encoding="utf-8"), source[c["start"]:c["end"]])
        self.assertFalse(list(run.path.glob("00_chunk_*")))
        self.assertFalse(list(run.path.glob("*with_metrics*")))


class SingleSpanTests(ChunkCase):
    def test_up_to_15000_is_single_and_above_is_chunked(self):
        for size, mode in ((14999, "single"), (15000, "single"), (15001, "chunked")):
            with self.subTest(size=size):
                run, manifest = self.prepared(exact_doc(size))
                self.assertEqual(len(run.source()), size)
                self.assertEqual(manifest["processing_mode"], mode)
                self.assertEqual(manifest["route_reason"], f"sejong:{mode}")
                self.assertIsNone(manifest["route_hint"])
                if mode == "single":
                    self.assertEqual((manifest["chunk_count"], manifest["chunks"][0]["char_count"]), (1, size))
                else:
                    self.assertGreater(manifest["body_chunk_count"], 1)

    def test_heading_dense_document_under_the_limit_is_still_one_chunk(self):
        body = []
        for i in range(30):
            body += [f"## 소제목 {i}", para(300, f"본문{i}")]
        run, manifest = self.prepared(doc(*body))
        self.assertLessEqual(len(run.source()), 15000)
        self.assertEqual((manifest["processing_mode"], manifest["body_chunk_count"]), ("single", 1))

    def test_single_keeps_the_footnote_passthrough_chunk(self):
        text = doc(para(500), para(500)) + "\n1) 첫째 각주 설명입니다\n2) 둘째 각주 설명입니다\n"
        _, manifest = self.prepared(text)
        self.assertEqual(manifest["processing_mode"], "single")
        self.assertEqual([c["passthrough"] for c in manifest["chunks"]], [False, True])
        self.assertEqual(manifest["passthrough_chunk_count"], 1)
        self.assertEqual(manifest["sejong"]["seams"], [])

    def test_genre_and_parameters_are_recorded_and_validated(self):
        _, manifest = self.prepared(doc(para(300)), genre="blog", target=800, cap=1200)
        self.assertEqual((manifest["genre"], manifest["sejong"]["genre"], manifest["sejong"]["version"]), ("blog", "blog", 1))
        self.assertEqual((manifest["target_chunk_chars"], manifest["max_chunk_chars"]), (800, 1200))
        run = RunDir(doc(para(300)))
        self.addCleanup(run.close)
        with self.assertRaises(ValueError):
            chunk.prepare(run.path, genre="news")
        with self.assertRaises(ValueError):
            chunk.prepare(run.path, target=2000, cap=1000)


class FootnoteTests(ChunkCase):
    def test_trailing_definition_block_is_one_passthrough_chunk(self):
        text = doc(*[para(300) for _ in range(8)]) + "\n1) 첫째 각주입니다\n[2] 둘째 각주입니다\n\n"
        run, manifest = self.prepared(text, **SMALL)
        last = manifest["chunks"][-1]
        self.assertTrue(last["passthrough"])
        self.assertEqual(run.source()[last["start"]:last["end"]], "1) 첫째 각주입니다\n[2] 둘째 각주입니다\n\n")
        self.assertIsNone(last["input_file"])
        self.assertIsNone(last["rewritten_file"])
        self.assertTrue(all(not c["passthrough"] for c in manifest["chunks"][:-1]))

    def test_footnote_block_detection(self):
        self.assertIsNone(chunk.find_footnote_block_start("본문입니다.\n\n1) 각주\n\n마지막 문단입니다.\n"))
        self.assertEqual(chunk.find_footnote_block_start("본문입니다.\n1) 각주\n"), len("본문입니다.\n"))
        self.assertIsNone(chunk.find_footnote_block_start(""))

    def test_footnote_block_detection_matches_the_vendor(self):
        vendor = load("vendor_prepare_wp3c", VENDOR_PREPARE)
        rng = random.Random(5)
        pieces = ["본문입니다.", "", "1) 각주", "[2] 각주", "12) 각주", "1)각주", "3) ", "다음 문단", "  ", "[x] 아님", "(1) 아님"]
        for _ in range(400):
            text = rng.choice(["\n", "\n\n"]).join(rng.choice(pieces) for _ in range(rng.randint(1, 8))) + rng.choice(["", "\n"])
            self.assertEqual(chunk.find_footnote_block_start(text), vendor.find_footnote_block_start(text), repr(text))

    def test_seams_never_reach_into_the_footnote_block(self):
        text = doc(*[para(300) for _ in range(8)]) + "\n1) 각주입니다\n"
        _, manifest = self.prepared(text, **SMALL)
        footnote_start = manifest["chunks"][-1]["start"]
        for seam in manifest["sejong"]["seams"]:
            self.assertLessEqual(seam["next"][1], footnote_start)
            self.assertLessEqual(seam["prev"][1], footnote_start)
        self.assertEqual(chunk.seam_ranges(manifest, manifest["body_chunk_count"])[1], (0, 0))


# ==========================================================================
# headings
# ==========================================================================
class HeadingRuleTests(ChunkCase):
    def test_numbered_and_company_lines_never_force_a_cut(self):
        marks = ["1. 준비물", "2) 진행 순서", "가. 신청 방법", "(주)한빛마트 제공", "3. 유의 사항", "나) 결과"]
        parts = []
        for i in range(36):
            parts += [marks[i % len(marks)], para(300, f"본문{i}")]
        text = doc(*parts)
        run, manifest = self.prepared(text, max_single=1200, target=1000, cap=1300)
        sizes = [c["char_count"] for c in manifest["chunks"]]
        self.assertLessEqual(manifest["body_chunk_count"], math.ceil(len(text) / 1000) + 1)
        self.assertTrue(all(size >= 500 for size in sizes[:-1]), sizes)
        for c in manifest["chunks"]:
            self.assertFalse(c["starts_with_heading"], c["heading"])
        vendor = load("vendor_prepare_wp3", VENDOR_PREPARE)             # it cuts before 5 of every 6 of those lines
        vendor_spans, _ = vendor.compute_chunk_spans(text, target=1000, max_chunk=1300)
        self.assertGreater(len(vendor_spans), 2 * manifest["body_chunk_count"])

    def test_markdown_chapter_and_roman_headings_start_chunks_and_are_reported(self):
        parts = []
        for i, mark in enumerate(["# 첫 장", "## 둘째 절", "제3장 결과", "Ⅳ. 마무리", "### 부록", "# 끝"]):
            parts += [mark, para(450, f"내용{i}")]
        run, manifest = self.prepared(doc(*parts), max_single=800, target=1000, cap=1300)
        source = run.source()
        self.assertGreater(manifest["body_chunk_count"], 1)
        for c in manifest["chunks"]:
            self.assertEqual(c["starts_with_heading"], c["heading"] is not None)
            self.assertEqual(c["heading"], self.first_line(source[c["start"]:c["end"]]))
        self.assertEqual(manifest["chunks"][0]["heading"], "# 첫 장")

    def test_small_sections_share_a_chunk(self):
        parts = []
        for i in range(12):
            parts += [f"## 절 {i}", para(150, f"짧은{i}")]
        _, manifest = self.prepared(doc(*parts), max_single=1000, target=1000, cap=1300)
        self.assertLess(manifest["body_chunk_count"], 6)             # 12 sections, not 12 chunks
        self.assertTrue(all(c["char_count"] >= 500 for c in manifest["chunks"][:-1]))

    def test_cut_prefers_a_section_start_inside_the_window(self):
        parts = ["## A", para(200, "가"), para(200, "나"), para(200, "다"), "## B", para(200, "라"), para(200, "마"),
                 para(200, "바"), "## C", para(200, "사")]
        run, manifest = self.prepared(doc(*parts), max_single=800, target=1000, cap=1300)
        starts = [self.first_line(piece) for piece in self.pieces_of(run, manifest)]
        self.assertEqual(starts[:2], ["## A", "## B"])               # the greedy cut would have been before 마
        self.assertGreaterEqual(manifest["chunks"][0]["char_count"], 500)

    def test_unmarked_heading_stays_with_its_body(self):
        # 300 + 300 + (heading + 400): without the glue the fill would stop right after the heading line
        text = doc(para(300, "가"), para(300, "나"), "배송 안내", para(400, "다"), para(300, "라"), para(300, "마"))
        run, manifest = self.prepared(text, max_single=800, target=700, cap=1000)
        chunks = self.pieces_of(run, manifest)
        self.assertGreater(len(chunks), 1)
        for index, piece in enumerate(chunks):
            self.assertNotEqual(self.last_line(piece), "배송 안내", f"chunk {index + 1} ends on the heading")
        owner = next(i for i, piece in enumerate(chunks) if "배송 안내" in piece)
        self.assertIn(para(400, "다"), chunks[owner])
        self.assertEqual(manifest["chunks"][owner]["heading"], "배송 안내")          # and the chunk starts with it
        self.assertEqual(self.first_line(chunks[owner]), "배송 안내")

    def test_headings_the_text_module_refuses_are_still_glued(self):
        # text.unmarked_heading rejects a line ending in a prose syllable (개요, 다음, 필요) or in a colon
        for heading in ("행사 개요", "다음", "필요", "주의할 점:"):
            with self.subTest(heading=heading):
                text = doc(para(300, "가"), para(300, "나"), heading, para(400, "다"), para(300, "라"))
                run, manifest = self.prepared(text, max_single=800, target=700, cap=1000)
                for piece in self.pieces_of(run, manifest):
                    self.assertNotEqual(self.last_line(piece), heading)

    def test_short_line_ending_like_a_sentence_is_not_glued(self):
        text = doc(para(300, "가"), para(300, "나"), "배송은 내일 시작합니다.", para(400, "다"), para(300, "라"))
        run, manifest = self.prepared(text, max_single=800, target=700, cap=1000)
        self.assertTrue(any(self.last_line(piece) == "배송은 내일 시작합니다." for piece in self.pieces_of(run, manifest)))
        self.assertFalse(chunk._glue_line("짧은 줄", 3))             # not before a shorter paragraph
        self.assertTrue(chunk._glue_line("짧은 줄", 30))
        self.assertFalse(chunk._glue_line("짧은 문장입니다.", 300))
        self.assertFalse(chunk._glue_line("*" * 10, 300))

    def test_a_title_stays_with_an_oversize_paragraph_that_follows_it(self):
        long_paragraph = sentence_paragraph(3000)                       # above cap, so it is cut into sentences
        for title in ("배송 안내", "개요", "“정말 그럴까요?” 그가 물었다. 점심은 먹었어요 ㅎㅎ", "## 소제목"):
            with self.subTest(title=title):
                text = doc(para(300, "가"), para(300, "나"), title, long_paragraph, para(200, "다"))
                run, manifest = self.prepared(text, max_single=800, target=700, cap=1000)
                chunks = self.pieces_of(run, manifest)
                self.assertGreater(len(chunks), 3)
                for piece in chunks:
                    self.assertNotEqual(self.last_line(piece), title)
                owner = next(piece for piece in chunks if title in piece)
                self.assertGreater(len(owner.split(title, 1)[1].strip()), 20)       # a sentence follows it in its chunk

    def test_a_heading_inside_a_paragraph_starts_its_own_piece_and_keeps_its_body(self):
        text = "알파 문단입니다.\n" + para(300, "가") + "\n# 소제목\n" + para(300, "나") + "\n\n" + para(300, "다") + "\n"
        scan = chunk._Scan(text, 1300)
        heading = next(p for p in scan.pieces if p.heading == "# 소제목")
        self.assertTrue(heading.section)
        self.assertIn(para(300, "나"), text[heading.start:heading.end])

    def test_document_ending_in_a_heading_is_reported(self):
        text = doc(*[para(300, f"가{i}") for i in range(8)]) + "\n## 맺음\n"
        run, manifest = self.prepared(text, **SMALL)
        self.assertTrue(any("헤딩으로 끝남" in w for w in manifest["warnings"]), manifest["warnings"])
        self.assertEqual("".join(self.pieces_of(run, manifest)), run.source())

    def test_fenced_code_is_never_cut_and_its_hash_comments_are_not_headings(self):
        code = "```python\n" + "\n\n".join(f"# 주석 {i}\nprint({i})" for i in range(40)) + "\n```"
        run, manifest = self.prepared(doc(para(300, "가"), code, para(300, "나")), max_single=500, target=700, cap=1000)
        source = run.source()
        start, end = source.index("```python"), source.rindex("```") + 3
        for c in manifest["chunks"]:
            self.assertFalse(start < c["start"] < end, "a cut inside the fence")
            self.assertFalse(c["starts_with_heading"])


# ==========================================================================
# packing and seam rules
# ==========================================================================
class PackingTests(ChunkCase):
    def test_cuts_fall_on_paragraph_starts_and_chunks_stay_within_target(self):
        text = doc(*[para(120 + 37 * (i % 7), f"문단{i}") for i in range(60)])
        run, manifest = self.prepared(text, max_single=1000, target=1000, cap=1300)
        source = run.source()
        for c in manifest["chunks"][1:]:
            self.assertEqual(source[c["start"] - 2:c["start"]], "\n\n")
            self.assertNotIn(source[c["start"]], " \n")
        for c in manifest["chunks"]:
            self.assertLessEqual(c["char_count"], 1300)

    def test_a_paragraph_above_cap_is_cut_at_sentence_starts(self):
        text = doc(para(200, "가"), sentence_paragraph(3200), para(200, "나"))
        run, manifest = self.prepared(text, max_single=1000, target=1000, cap=1300)
        source = run.source()
        self.assertGreaterEqual(manifest["body_chunk_count"], 3)
        for c in manifest["chunks"]:
            self.assertLessEqual(c["char_count"], 1300)
        for c in manifest["chunks"][1:]:
            self.assertRegex(source[c["start"] - 2:c["start"]], r"(\.\s|\n\n)")     # right after a sentence end
        self.assertEqual("".join(self.pieces_of(run, manifest)), source)

    def test_an_unsplittable_run_is_kept_whole_and_reported(self):
        run, manifest = self.prepared(doc(para(200, "가"), "나다라 " * 600, para(200, "마")), max_single=1000,
                                      target=1000, cap=1300)
        self.assertTrue(any("초장 구간" in w for w in manifest["warnings"]), manifest["warnings"])
        self.assertEqual("".join(self.pieces_of(run, manifest)), run.source())

    def test_a_tiny_last_chunk_joins_the_one_before_when_it_fits_the_cap(self):
        def count(*paragraphs):
            spans, _ = chunk.compute_spans(doc(*paragraphs), max_single=500, target=1000, cap=1300)
            return len(spans)
        four = [para(480, f"가{i}") for i in range(4)]
        self.assertEqual(count(*four, para(100, "끝")), 2)             # 100 < 250 and 962 + 102 <= 1300
        self.assertEqual(count(*four, para(300, "끝")), 3)             # 300 is a real chunk
        self.assertEqual(count(para(480, "가"), para(480, "나"), para(1250, "다"), para(100, "끝")), 3)   # 1252 + 100 > cap


class SeamRuleTests(ChunkCase):
    def cut_before(self, *paragraphs, **options):
        run, manifest = self.prepared(doc(*paragraphs), **{**dict(max_single=800, target=1000, cap=1300), **options})
        return [self.first_line(piece) for piece in self.pieces_of(run, manifest)], manifest

    def test_starts_dependent_table(self):
        yes = ["그러나 결과는 달랐다.", "하지만, 그는 갔다.", "예를 들어 이런 경우다.", "이는 중요한 점이다.", "이러한 변화는 크다.",
               "이 방법은 간단하다.", "그는 웃었다.", "이곳은 서울에서 가장 오래된 서점이다.", "“그런데 말이야.”", "- 또한 확인한다.",
               "1. 따라서 신청한다.", "**결국** 같은 이야기다.", "그 사람은 말이 없었다.", "이것이 문제다.", "다만 예외가 있다."]
        no = ["오늘은 비가 왔어요.", "알파문단입니다.", "이웃에게 인사를 건넸다.", "그릇을 샀다.", "그림을 그렸다.", "저는 학생입니다.",
              "이번 주에는 쉬어요.", "그리움이 컸다.", "## 그러나", ""]
        for line in yes:
            with self.subTest(line=line):
                self.assertTrue(chunk.starts_dependent(line))
        for line in no:
            with self.subTest(line=line):
                self.assertFalse(chunk.starts_dependent(line))

    def test_cut_moves_one_paragraph_earlier_off_a_connective_or_demonstrative(self):
        for opener in ("그러나 결과는 달랐다. ", "이는 중요한 점이다. ", "이 방법은 간단하다. ", "그는 웃었다. ", "예를 들어 이렇다. "):
            with self.subTest(opener=opener):
                dependent = opener + para(200 - len(opener), "라")
                lines, manifest = self.cut_before(para(300, "가"), para(300, "나"), para(300, "다"), dependent, para(300, "마"))
                self.assertFalse(chunk.starts_dependent(lines[1]), lines)
                self.assertTrue(lines[1].startswith("다"), lines)               # one paragraph earlier
                self.assertGreaterEqual(manifest["chunks"][0]["char_count"], 500)

    def test_floor_blocks_the_earlier_move_so_the_cut_moves_later_within_cap(self):
        lines, manifest = self.cut_before(para(450, "가"), para(450, "나"), "그러나 " + para(193, "다"), para(300, "라"))
        self.assertTrue(lines[1].startswith("라"), lines)                 # 452 + 452 + 202 = 1106 <= cap 1300
        self.assertLessEqual(manifest["chunks"][0]["char_count"], 1300)

    def test_cut_stays_when_no_alternative_exists(self):
        lines, manifest = self.cut_before(para(450, "가"), para(450, "나"), "그러나 " + para(493, "다"), "그리고 " + para(293, "라"))
        self.assertTrue(lines[1].startswith("그러나"), lines)             # earlier < 50% of target, later > cap
        self.assertEqual(manifest["body_chunk_count"], 2)

    def test_a_section_start_is_never_dependent(self):
        lines, manifest = self.cut_before(para(300, "가"), para(300, "나"), para(300, "다"), "## 그러나 결론", para(300, "라"))
        self.assertEqual(lines[1], "## 그러나 결론")
        self.assertGreaterEqual(manifest["chunks"][0]["char_count"], 900)    # not moved earlier

    def test_dependent_pieces_inside_an_oversize_paragraph_are_avoided_too(self):
        alpha = "알파 문장이 이어집니다."
        body = " ".join([alpha] * 40 + ["그러나 이 문장은 앞 문장에 기댑니다."] + ["베타 문장이 이어집니다."] * 40)
        run, manifest = self.prepared(doc(body), max_single=500, target=570, cap=1000)
        chunks = self.pieces_of(run, manifest)
        self.assertGreater(len(chunks), 1)
        for piece in chunks[1:]:
            self.assertFalse(chunk.starts_dependent(piece.strip()), piece[:30])
        self.assertTrue(chunks[1].lstrip().startswith("알파"))             # the cut moved one sentence earlier


# ==========================================================================
# seam context
# ==========================================================================
class SeamContextTests(ChunkCase):
    @staticmethod
    def long_doc(count=24, size=330):
        return doc(*[para(size + 11 * (i % 5), f"{i:02d}번문단") for i in range(count)])

    def test_sizes_positions_and_trimming(self):
        run, manifest = self.prepared(self.long_doc(), **SMALL)
        source = run.source()
        seams = {s["chunk"]: s for s in manifest["sejong"]["seams"]}
        self.assertGreater(manifest["body_chunk_count"], 3)
        for c in manifest["chunks"]:
            prev, nxt = chunk.seam_ranges(manifest, c["index"])
            self.assertEqual(c["index"] in seams, (prev, nxt) != ((0, 0), (0, 0)))
            self.assertLessEqual(prev[1] - prev[0], chunk.PREV_CONTEXT_CHARS)
            self.assertLessEqual(nxt[1] - nxt[0], chunk.NEXT_CONTEXT_CHARS)
            if prev != (0, 0):
                self.assertLessEqual(prev[1], c["start"])
                self.assertEqual(source[prev[1]:c["start"]].strip(), "")          # directly before the chunk
                self.assertEqual(source[prev[0]:prev[1]], source[prev[0]:prev[1]].strip())
            if nxt != (0, 0):
                self.assertGreaterEqual(nxt[0], c["end"])
                self.assertEqual(source[c["end"]:nxt[0]].strip(), "")             # directly after the chunk
                self.assertEqual(source[nxt[0]:nxt[1]], source[nxt[0]:nxt[1]].strip())
        self.assertEqual(chunk.seam_ranges(manifest, 1)[0], (0, 0))
        self.assertEqual(chunk.seam_ranges(manifest, manifest["body_chunk_count"])[1], (0, 0))
        self.assertNotEqual(chunk.seam_ranges(manifest, 2)[0], (0, 0))
        self.assertNotEqual(chunk.seam_ranges(manifest, 1)[1], (0, 0))

    def test_contexts_come_from_the_source_and_stop_at_paragraph_edges(self):
        run, manifest = self.prepared(self.long_doc(size=150), **SMALL)
        source = run.source()
        paragraphs = [p.strip() for p in source.split("\n\n")]
        checked = 0
        for c in manifest["chunks"]:
            prev, nxt = chunk.seam_ranges(manifest, c["index"])
            if prev != (0, 0):
                context = source[prev[0]:prev[1]]
                self.assertTrue(prev[0] == 0 or source[prev[0] - 2:prev[0]] == "\n\n")
                self.assertTrue(any(context.endswith(p) for p in paragraphs))
                self.assertLessEqual(context.count("\n\n"), 1)                    # at most two paragraphs
                checked += 1
            if nxt != (0, 0):
                context = source[nxt[0]:nxt[1]]
                self.assertIn(context, paragraphs)                                # one whole paragraph (it fits)
                checked += 1
        self.assertGreater(checked, 4)

    def test_two_paragraphs_when_they_fit_else_one(self):
        small = doc(*[para(200, f"작은{i}") for i in range(9)])
        start = small.index(para(200, "작은5"))
        (ps, pe), (ns, ne) = chunk.seam_context(small, start, start + 2 * 202)
        self.assertEqual(small[ps:pe], para(200, "작은3") + "\n\n" + para(200, "작은4"))
        self.assertEqual(small[ns:ne], para(200, "작은7"))
        big = doc(*[para(400, f"큰{i}") for i in range(9)])
        start = big.index(para(400, "큰3"))
        (ps, pe), _ = chunk.seam_context(big, start, start + 2 * 402)
        self.assertEqual(big[ps:pe], para(400, "큰2"))                            # two would be 802 > 600

    def test_a_long_paragraph_gives_its_last_whole_sentences_before_and_first_after(self):
        long_paragraph = sentence_paragraph(1800)
        text = doc(para(200, "앞"), long_paragraph, para(200, "뒤"))
        begin = text.index(long_paragraph)
        stop = begin + len(long_paragraph)
        (ps, pe), _ = chunk.seam_context(text, stop + 2, len(text))
        context = text[ps:pe]
        self.assertEqual(pe, stop)
        self.assertLessEqual(len(context), 600)
        self.assertGreater(len(context), 300)
        self.assertEqual(text[ps - 2], ".")                                       # starts right after a sentence end
        self.assertTrue(context.endswith("."))
        _, (ns, ne) = chunk.seam_context(text, 0, begin)
        head = text[ns:ne]
        self.assertEqual(ns, begin)
        self.assertLessEqual(len(head), 300)
        self.assertGreater(len(head), 100)
        self.assertTrue(head.endswith("."))
        self.assertTrue(long_paragraph.startswith(head))

    def test_a_sentence_longer_than_the_limit_is_cut_at_a_word_boundary(self):
        run_on = " ".join(f"단어{i}" for i in range(500))
        text = doc(para(100, "앞"), run_on, para(100, "뒤"))
        begin = text.index(run_on)
        stop = begin + len(run_on)
        (ps, pe), _ = chunk.seam_context(text, stop + 2, len(text))
        self.assertEqual(pe, stop)
        self.assertLessEqual(pe - ps, 600)
        self.assertEqual(text[ps - 1], " ")
        _, (ns, ne) = chunk.seam_context(text, 0, begin)
        self.assertLessEqual(ne - ns, 300)
        self.assertEqual(text[ns:ne], text[ns:ne].strip())
        self.assertEqual(text[ne], " ")

    def test_the_next_context_of_a_heading_includes_the_paragraph_after_it(self):
        text = doc(para(300, "앞"), "## 소제목", para(250, "본문"), para(300, "뒤"))
        _, (ns, ne) = chunk.seam_context(text, 0, text.index("## 소제목"))
        context = text[ns:ne]
        self.assertTrue(context.startswith("## 소제목"))
        self.assertIn(para(250, "본문"), context)

    def test_offsets_are_code_points_not_utf16_units(self):
        emoji = "😀" * 30
        run, manifest = self.prepared(doc(*[para(300, f"{emoji}{i}") for i in range(12)]), **SMALL)
        source = run.source()
        points = list(source)                                    # what Array.from(documentText) gives in TypeScript
        self.assertGreater(len(source.encode("utf-16-le")) // 2, len(source))
        checked = 0
        for seam in manifest["sejong"]["seams"]:
            for key in ("prev", "next"):
                s, e = seam[key]
                if (s, e) != (0, 0):
                    self.assertEqual("".join(points[s:e]), source[s:e])
                    self.assertEqual(source[s:e], source[s:e].strip())
                    self.assertLessEqual(e - s, chunk.PREV_CONTEXT_CHARS if key == "prev" else chunk.NEXT_CONTEXT_CHARS)
                    checked += 1
        self.assertGreater(checked, 4)
        for c in manifest["chunks"]:
            self.assertEqual(c["char_count"], len(source[c["start"]:c["end"]]))

    def test_seam_ranges_defaults(self):
        manifest = {"sejong": {"version": 1, "genre": "blog", "seams": [{"chunk": 2, "prev": [3, 9], "next": [20, 30]}]}}
        self.assertEqual(chunk.seam_ranges(manifest, 2), ((3, 9), (20, 30)))
        self.assertEqual(chunk.seam_ranges(manifest, 1), ((0, 0), (0, 0)))
        self.assertEqual(chunk.seam_ranges({}, 1), ((0, 0), (0, 0)))


# ==========================================================================
# reassembly
# ==========================================================================
class ReassembleTests(ChunkCase):
    def setUp(self):
        self.run, self.manifest = self.prepared(doc(*[para(300, f"문단{i:02d}") for i in range(12)]), **SMALL)
        self.source = self.run.source()
        self.chunks = self.manifest["chunks"]
        self.assertGreaterEqual(len(self.chunks), 3)

    def write_rewrites(self, transform=lambda index, piece: piece):
        for c in self.chunks:
            if not c["passthrough"]:
                piece = self.source[c["start"]:c["end"]]
                (self.run.path / c["rewritten_file"]).write_text(transform(c["index"], piece), encoding="utf-8")

    def output(self):
        return (self.run.path / "03_reassembled.md").read_text(encoding="utf-8")

    def test_identity_rewrite_reassembles_to_the_source_byte_for_byte(self):
        self.write_rewrites()
        report = chunk.reassemble(self.run.path)
        self.assertEqual(self.output(), self.source)
        self.assertEqual((report["rolled_back_chunks"], report["warning_codes"], report["warnings"]), ([], [], []))
        self.assertEqual(report["total_ratio"], 1.0)
        self.assertEqual(json.loads((self.run.path / "03_reassembly_report.json").read_text(encoding="utf-8")), report)

    def test_writer_whitespace_is_dropped_and_the_source_whitespace_put_back(self):
        self.write_rewrites(lambda i, piece: "\n\n  " + piece.strip() + "   \n\n\n")
        chunk.reassemble(self.run.path)
        self.assertEqual(self.output(), self.source)
        self.write_rewrites(lambda i, piece: piece.strip().replace("문단", "단락"))
        chunk.reassemble(self.run.path)
        self.assertEqual(self.output(), self.source.replace("문단", "단락"))

    def test_ratio_below_half_rolls_the_chunk_back_and_does_not_fail_the_job(self):
        target = self.chunks[1]
        self.write_rewrites(lambda i, piece: "줄" * 20 if i == target["index"] else piece.replace("문단", "단락"))
        report = chunk.reassemble(self.run.path)
        self.assertEqual(report["rolled_back_chunks"], [target["index"]])
        self.assertEqual(report["warning_codes"], ["CHUNK_ROLLED_BACK"])
        out = self.output()
        self.assertIn(self.source[target["start"]:target["end"]], out)              # that chunk is the source
        self.assertIn("단락00", out)                                               # the others keep the rewrite
        entry = next(e for e in report["chunks"] if e["index"] == target["index"])
        self.assertEqual((entry["rolled_back"], entry["rollback_reason"]), (True, "ratio_low"))
        self.assertTrue(any("유실 의심" in w for w in report["warnings"]))
        self.assertEqual([e["rolled_back"] for e in report["chunks"] if e["index"] != target["index"]],
                         [False] * (len(self.chunks) - 1))

    def test_ratio_above_two_rolls_the_chunk_back(self):
        target = self.chunks[0]
        self.write_rewrites(lambda i, piece: piece.strip() * 3 if i == target["index"] else piece)
        report = chunk.reassemble(self.run.path)
        self.assertEqual(report["rolled_back_chunks"], [target["index"]])
        self.assertEqual(next(e for e in report["chunks"] if e["index"] == target["index"])["rollback_reason"], "ratio_high")
        self.assertEqual(self.output(), self.source)

    def test_exactly_half_and_exactly_double_are_kept(self):
        core1 = self.source[self.chunks[0]["start"]:self.chunks[0]["end"]].strip()
        core2 = self.source[self.chunks[1]["start"]:self.chunks[1]["end"]].strip()
        self.assertEqual(len(core1) % 2, 0)
        self.write_rewrites(lambda i, piece: "가" * (len(core1) // 2) if i == 1 else "나" * (len(core2) * 2) if i == 2 else piece)
        report = chunk.reassemble(self.run.path)
        self.assertEqual(report["rolled_back_chunks"], [])
        out = self.output()
        self.assertIn("가" * (len(core1) // 2), out)
        self.assertIn("나" * (len(core2) * 2), out)

    def test_empty_rewrite_rolls_back(self):
        self.write_rewrites(lambda i, piece: "  \n" if i == 2 else piece)
        report = chunk.reassemble(self.run.path)
        self.assertEqual(report["rolled_back_chunks"], [2])
        self.assertEqual(next(e for e in report["chunks"] if e["index"] == 2)["rollback_reason"], "empty")
        self.assertEqual(self.output(), self.source)

    def test_every_chunk_can_roll_back_and_the_output_is_the_source(self):
        self.write_rewrites(lambda i, piece: "줄")
        report = chunk.reassemble(self.run.path)
        self.assertEqual(len(report["rolled_back_chunks"]), len(self.chunks))
        self.assertEqual(self.output(), self.source)

    def test_report_keeps_the_vendor_keys(self):
        self.write_rewrites()
        report = chunk.reassemble(self.run.path, output="final.md", report="assembly.json")
        for key in ("source_chars", "output_chars", "total_ratio", "warnings", "chunks"):
            self.assertIn(key, report)
        for entry in report["chunks"]:
            for key in ("index", "passthrough", "orig_chars"):
                self.assertIn(key, entry)
            if not entry["passthrough"]:
                for key in ("rewritten_chars", "ratio"):
                    self.assertIn(key, entry)
        self.assertTrue((self.run.path / "final.md").exists() and (self.run.path / "assembly.json").exists())

    def test_passthrough_chunk_is_copied_verbatim(self):
        text = doc(*[para(300, f"문단{i:02d}") for i in range(8)]) + "\n1) 각주 설명입니다\n"
        run, manifest = self.prepared(text, **SMALL)
        source = run.source()
        for c in manifest["chunks"]:
            if not c["passthrough"]:
                (run.path / c["rewritten_file"]).write_text(source[c["start"]:c["end"]].replace("문단", "단락"), encoding="utf-8")
        report = chunk.reassemble(run.path)
        self.assertTrue((run.path / "03_reassembled.md").read_text(encoding="utf-8").endswith("1) 각주 설명입니다\n"))
        self.assertEqual(report["chunks"][-1], {"index": manifest["chunk_count"], "passthrough": True,
                                                "orig_chars": len("1) 각주 설명입니다\n")})

    def test_errors_that_still_fail_the_job(self):
        run, manifest = self.run, self.manifest
        with self.assertRaises(chunk.ReassemblyError):                       # no rewrite file yet
            chunk.reassemble(run.path)
        self.write_rewrites()
        (run.path / "01_input.txt").write_text(self.source + "x", encoding="utf-8")
        with self.assertRaisesRegex(chunk.ReassemblyError, "sha256"):
            chunk.reassemble(run.path)
        (run.path / "01_input.txt").write_text(self.source, encoding="utf-8")
        chunk.reassemble(run.path)                                           # restored: fine again
        for label, edit in (("gap", lambda m: m["chunks"][1].update(start=m["chunks"][1]["start"] + 1)),
                            ("unsafe name", lambda m: m["chunks"][0].update(rewritten_file="../x.txt")),
                            ("no chunks", lambda m: m.pop("chunks")),
                            ("bad type", lambda m: m["chunks"][0].update(end="x"))):
            with self.subTest(label):
                damaged = json.loads(json.dumps(manifest))
                edit(damaged)
                (run.path / "chunk_manifest.json").write_text(json.dumps(damaged), encoding="utf-8")
                with self.assertRaises(chunk.ReassemblyError):
                    chunk.reassemble(run.path)
        (run.path / "chunk_manifest.json").unlink()
        with self.assertRaises(chunk.ReassemblyError):
            chunk.reassemble(run.path)


# ==========================================================================
# the contract the current TypeScript parser enforces
# ==========================================================================
def ts_parse_manifest(value):
    """python-engine.ts parseManifest, check for check. The function is not exported, so this test
    mirrors its rules and test_parser_source_* pins that the TypeScript still reads exactly these."""
    def fail(message):
        raise AssertionError(message)

    def integer(v, label):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            fail(f"{label} must be a nonnegative integer")
        return v

    def string(v, label):
        if not isinstance(v, str):
            fail(f"{label} must be a string")
        return v

    def boolean(v, label):
        if not isinstance(v, bool):
            fail(f"{label} must be a boolean")
        return v

    def safe_leaf(v, label):
        leaf = string(v, label)
        if not leaf or leaf.startswith("/") or "/" in leaf or "\\" in leaf or leaf in (".", ".."):
            fail(f"{label} must be a safe filename")
        return leaf

    if not isinstance(value, dict):
        fail("manifest must be an object")
    if integer(value.get("version"), "version") != 1:
        fail("Unsupported manifest version")
    if not isinstance(value.get("chunks"), list):
        fail("chunks must be an array")
    chunks = []
    for raw in value["chunks"]:
        if not isinstance(raw, dict):
            fail("chunk must be an object")
        passthrough = boolean(raw.get("passthrough"), "passthrough")
        input_file = None if raw.get("input_file") is None else safe_leaf(raw["input_file"], "input_file")
        rewritten = None if raw.get("rewritten_file") is None else safe_leaf(raw["rewritten_file"], "rewritten_file")
        if passthrough and (input_file is not None or rewritten is not None):
            fail("Passthrough chunks cannot have rewrite filenames")
        if not passthrough and (input_file is None or rewritten is None):
            fail("Body chunks require input and rewritten filenames")
        if raw.get("heading") is not None and not isinstance(raw["heading"], str):
            fail("heading must be string or null")
        chunks.append({"index": integer(raw.get("index"), "index"), "start": integer(raw.get("start"), "start"),
                       "end": integer(raw.get("end"), "end"), "charCount": integer(raw.get("char_count"), "char_count"),
                       "startsWithHeading": boolean(raw.get("starts_with_heading"), "starts_with_heading")})
    if len(chunks) != integer(value.get("chunk_count"), "chunk_count"):
        fail("chunk_count mismatch")
    for index, c in enumerate(chunks):
        if c["index"] != index + 1 or c["end"] < c["start"]:
            fail("Invalid chunk ordering")
        if index and chunks[index - 1]["end"] != c["start"]:
            fail("Chunk spans are not contiguous")
    warnings = value.get("warnings")
    if not isinstance(warnings, list) or any(not isinstance(w, str) for w in warnings):
        fail("warnings must be a string array")
    string(value.get("source_sha256"), "source_sha256")
    safe_leaf(value.get("source_file"), "source_file")
    for key in ("source_chars", "body_chunk_count", "passthrough_chunk_count"):
        integer(value.get(key), key)
    if value.get("route_hint") not in (None, "light", "standard", "heavy"):
        fail("route_hint must be light, standard, heavy, or null")
    if value.get("route_reason") is not None:
        string(value["route_reason"], "route_reason")
    if value.get("processing_mode") not in ("single", "chunked"):
        fail("processing_mode must be single or chunked")
    return value


def ts_parse_sejong_block(manifest):
    """src/engine/sejong/python-adapter.ts parseSejongManifest, the optional block."""
    block = manifest.get("sejong")
    if block is None:
        return None
    assert block["version"] == 1
    assert block["genre"] in ("general", "blog", "essay", "report", "notice", "document")
    for seam in block["seams"]:
        assert 1 <= seam["chunk"] <= manifest["chunk_count"]
        for key in ("prev", "next"):
            start, end = seam[key]
            assert isinstance(start, int) and isinstance(end, int) and 0 <= start <= end
    return block


class ManifestContractTests(ChunkCase):
    def test_manifests_pass_the_parser_checks(self):
        footnoted = doc(*[para(300, f"가{i}") for i in range(10)]) + "\n1) 각주입니다\n"
        headed = doc(*sum(([f"## 절 {i}", para(300, f"나{i}")] for i in range(10)), []))
        for label, text, options in (("single", doc(para(400), para(400)), {}), ("single footnote", footnoted, {}),
                                     ("chunked", doc(*[para(300) for _ in range(12)]), SMALL),
                                     ("chunked footnote", footnoted, SMALL), ("chunked headings", headed, SMALL),
                                     ("blog genre", doc(*[para(300) for _ in range(12)]), dict(SMALL, genre="blog"))):
            with self.subTest(label):
                run, manifest = self.prepared(text, **options)
                on_disk = json.loads((run.path / "chunk_manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(on_disk, manifest)
                ts_parse_manifest(on_disk)
                ts_parse_sejong_block(on_disk)
                self.assertEqual(set(on_disk) - {"sejong"}, MANIFEST_KEYS)
                for entry in on_disk["chunks"]:
                    self.assertEqual(set(entry), ENTRY_KEYS)
                self.assertEqual(on_disk["body_chunk_count"] + on_disk["passthrough_chunk_count"], on_disk["chunk_count"])
                self.assertEqual(on_disk["lossless_check"], "ok")

    def test_the_mirror_rejects_what_the_parser_rejects(self):
        _, manifest = self.prepared(doc(*[para(300) for _ in range(12)]), **SMALL)
        for label, edit in (("version", lambda m: m.update(version=2)), ("count", lambda m: m.update(chunk_count=99)),
                            ("hint", lambda m: m.update(route_hint="auto")), ("mode", lambda m: m.update(processing_mode="x")),
                            ("gap", lambda m: m["chunks"][1].update(start=m["chunks"][1]["start"] + 1)),
                            ("leaf", lambda m: m.update(source_file="../x")),
                            ("body without files", lambda m: m["chunks"][0].update(rewritten_file=None))):
            damaged = json.loads(json.dumps(manifest))
            edit(damaged)
            with self.subTest(label), self.assertRaises(AssertionError):
                ts_parse_manifest(damaged)

    def test_parser_source_reads_named_fields_and_ignores_unknown_keys(self):
        source = PYTHON_ENGINE_TS.read_text(encoding="utf-8")
        body = source[source.index("function parseManifest("):source.index("export class PythonEngine")]
        for needle in ("Object.keys(", "Object.entries(", "Object.values(", "Reflect.ownKeys", "for (const key"):
            self.assertNotIn(needle, body, "the parser enumerates keys, so an unknown key could be rejected")
        for field in ("root.version", "root.chunks", "root.warnings", "root.source_file", "root.source_chars", "root.source_sha256",
                      "root.body_chunk_count", "root.passthrough_chunk_count", "root.route_hint", "root.route_reason",
                      "root.processing_mode", "root.chunk_count", "chunk.input_file", "chunk.rewritten_file", "chunk.heading",
                      "chunk.passthrough", "chunk.char_count", "chunk.starts_with_heading"):
            self.assertIn(field, body)
        self.assertNotIn("sejong", body)                         # the v2 block is invisible to the legacy parser
        self.assertIn("route_hint must be light, standard, heavy, or null", source)


# ==========================================================================
# synthetic long documents from the seed composites (T5 §5.3 generator idea) and performance
# ==========================================================================
PLAIN_HEADINGS = ["배송 안내", "준비물", "마무리하며", "오늘의 한 줄", "참가 방법", "이용 시간", "주의할 점", "후기 정리", "다음 계획",
                  "자주 묻는 질문", "가격 정보", "운영 시간 안내", "신청 방법", "행사 개요", "작업 순서", "재료 소개", "비용 정리",
                  "일정 안내", "주차 안내", "찾아오는 길", "사용 후기", "총평", "요약", "참고 사항", "공지 사항", "준비 과정",
                  "느낀 점", "결과 보고", "향후 일정", "문의 방법"]
PREFIXES = ["그리고 ", "하지만 ", "그래서 ", "또한 ", "한편 ", "특히 ", "따라서 ", "이러한 경우에도 ", "그런데 ", "다만 "]


def composites_posts(strip=False):
    rows = [json.loads(line) for line in (SEED / "seed_composites.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r["text"].rstrip("\n") if strip else r["text"] for r in rows if r["chars"] < 4000]


def body_paragraphs(text):
    out = []
    for p in re.split(r"\n\s*\n", text.strip()):
        if "\n" in p.strip() or p.lstrip().startswith(("#", "-")) or re.match(r"\s*\d+[.)]\s", p):
            continue
        out.append(p.strip())
    return out


def flat_augmented(rng, posts):
    """The body paragraphs of 6-9 composites; 9% get a connective opener and 8% a plain-text heading in front
    (the heading texts are returned as ground truth). Calibrated so the vendor chunker shows the order of
    magnitude T5 measured (8.8% connective starts, 8.1% orphaned headings)."""
    paragraphs = []
    for _ in range(rng.randint(6, 9)):
        paragraphs.extend(body_paragraphs(rng.choice(posts)))
    out, headings = [], set()
    for p in paragraphs:
        if rng.random() < 0.09:
            p = rng.choice(PREFIXES) + p
        if len(p) > 60 and rng.random() < 0.08:
            heading = rng.choice(PLAIN_HEADINGS)
            headings.add(heading)
            out.append(heading)
        out.append(p)
    return "\n\n".join(out) + "\n", headings


class SyntheticLongDocumentTests(ChunkCase):
    @classmethod
    def setUpClass(cls):
        cls.t5 = load("t5_flowlib_wp3", PROTOTYPES / "T5_flowlib.py")

    def dependent(self, line):
        t5 = self.t5
        return bool(t5.initial_connective(line) or t5._DEM_PRON_INIT.match(line) or t5._DEM_N_TOPIC.match(line))

    def measure(self, chunker, docs):
        seams = starts = orphans = 0
        rng = random.Random(20261004)
        posts = composites_posts()
        for _ in range(docs):
            text, headings = flat_augmented(rng, posts)
            spans = chunker(text)
            self.assertEqual("".join(text[s["start"]:s["end"]] for s in spans), text)
            body = [s for s in spans if not s["passthrough"]]
            for a, b in zip(body, body[1:]):
                seams += 1
                starts += self.dependent(self.first_line(text[b["start"]:b["end"]]))
                orphans += self.last_line(text[a["start"]:a["end"]]) in headings
        return seams, starts, orphans

    def test_no_orphaned_headings_and_at_most_two_percent_connective_start_seams(self):
        seams, starts, orphans = self.measure(lambda text: chunk.compute_spans(text)[0], 120)
        self.assertGreater(seams, 200)
        self.assertEqual(orphans, 0)
        self.assertLessEqual(starts / seams, 0.02, f"{starts}/{seams}")

    def test_the_vendor_chunker_fails_the_same_check(self):
        vendor = load("vendor_prepare_wp3b", VENDOR_PREPARE)
        seams, starts, orphans = self.measure(lambda text: vendor.compute_chunk_spans(text)[0], 60)
        self.assertGreater(starts / seams, 0.05)
        self.assertGreater(orphans, 0)

    def test_heading_rich_markdown_documents_chunk_near_the_target(self):
        rng = random.Random(7)
        posts = composites_posts(strip=True)
        sizes = []
        for _ in range(40):
            text = "\n\n".join(rng.choice(posts) for _ in range(rng.randint(6, 9))) + "\n"
            spans, _ = chunk.compute_spans(text)
            sizes += [s["end"] - s["start"] for s in spans[:-1]]
        sizes.sort()
        self.assertGreater(sizes[len(sizes) // 2], 3500)             # the vendor median on such documents is about 700


LINES = ["## 소제목 {}", "# 큰 제목", "제2장 개요", "Ⅲ. 결론", "1. 준비물", "2) 순서", "가. 항목", "(주)한빛 제공", "- 목록 {}",
         "> 인용 {}", "개요", "다음", "배송 안내", "▶ 무료 상담 신청하기", "* * *", "---", "", "   "]
SENTENCES = ["자료는 공유 폴더에 올려 두었습니다.", "다음 일정은 목요일입니다!", "참석하지 못한 분도 확인할 수 있어요.", "그러나 결과는 달랐다.",
             "이 방법은 간단하다.", "점심은 근처에서 먹었어요 ㅎㅎ", "“정말 그럴까요?” 그가 물었다.", "가격은 3.5만 원입니다.",
             "자세한 내용은 https://example.com/a.b 에서 보세요.", "그는 웃었다…"]


def random_document(rng):
    parts = []
    for _ in range(rng.randint(1, 60)):
        r = rng.random()
        if r < 0.45:
            parts.append(" ".join(rng.choice(SENTENCES) for _ in range(rng.randint(1, 12))))
        elif r < 0.55:
            parts.append("\n".join(" ".join(rng.choice(SENTENCES) for _ in range(rng.randint(1, 3))) for _ in range(rng.randint(2, 6))))
        elif r < 0.60:
            parts.append("```\n" + "\n\n".join(rng.choice(["# 주석", "x = 1", ""]) for _ in range(rng.randint(1, 8))) + "\n```")
        else:
            parts.append(rng.choice(LINES).format(rng.randint(1, 9)))
    text = rng.choice(["\n\n", "\n\n", "\n\n\n", "\n"]).join(parts)
    if rng.random() < 0.2:
        text += "\n\n1) 각주 하나\n2) 각주 둘\n"
    return text + rng.choice(["", "\n", "\n\n"])


class PropertyTests(ChunkCase):
    """Invariants on random documents of mixed line kinds, with random target, cap and single limit."""

    def test_invariants_on_random_documents(self):
        rng = random.Random(1234)
        checked = 0
        for _ in range(300):
            text = random_document(rng)
            if not text.strip():
                continue
            target = rng.choice([200, 300, 500, 800])
            cap = target + rng.choice([0, 100, 300])
            options = dict(max_single=rng.choice([0, 100, 400, 100000]), target=target, cap=cap)
            spans, _ = chunk.compute_spans(text, **options)                # raises when the spans do not join
            self.assertEqual(spans, chunk.compute_spans(text, **options)[0])
            footnote = chunk.find_footnote_block_start(text)
            body_end = len(text) if footnote is None else footnote
            scan = chunk._Scan(text[:body_end], cap)
            fences = list(zip(scan.fence_starts, scan.fence_ends))
            body = [s for s in spans if not s["passthrough"]]
            for a, b in zip(body, body[1:]):
                self.assertFalse(any(fs < b["start"] < fe for fs, fe in fences), "a cut inside a code fence")
                inside = [p for p in scan.paras if a["start"] <= p.start < a["end"]]
                if inside and inside[-1].last <= a["end"]:                  # the chunk ends at a paragraph end
                    self.assertFalse(inside[-1].glue, "a chunk ends on a heading or a title")
            for s in body:
                prev, nxt = chunk._seam(scan, s["start"], s["end"], body_end, 600, 300, 2)
                for (x, y), limit in ((prev, 600), (nxt, 300)):
                    self.assertTrue(0 <= x <= y <= body_end and y - x <= limit, (x, y))
                    if (x, y) != (0, 0):
                        self.assertEqual(text[x:y], text[x:y].strip())
                        self.assertTrue(text[x:y])
                self.assertTrue(prev == (0, 0) or prev[1] <= s["start"])
                self.assertTrue(nxt == (0, 0) or s["end"] <= nxt[0] <= nxt[1] <= body_end)
            checked += 1
        self.assertGreater(checked, 250)

    def test_prepare_then_identity_reassembly_on_random_documents(self):
        rng = random.Random(99)
        for _ in range(40):
            text = random_document(rng)
            if not text.strip():
                continue
            run, manifest = self.prepared(text, max_single=rng.choice([0, 400]), target=300, cap=500)
            source = run.source()
            for c in manifest["chunks"]:
                if not c["passthrough"]:
                    (run.path / c["rewritten_file"]).write_text(source[c["start"]:c["end"]], encoding="utf-8")
            report = chunk.reassemble(run.path)
            self.assertEqual((run.path / "03_reassembled.md").read_text(encoding="utf-8"), source)
            self.assertEqual(report["rolled_back_chunks"], [])


class PerformanceTests(ChunkCase):
    SHAPES = {
        "blog paragraphs": lambda n: "\n\n".join(composites_posts() * (n // 12000 + 1))[:n],
        "one paragraph": lambda n: " ".join(composites_posts() * (n // 12000 + 1)).replace("\n", " ")[:n],
        "unclosed quote": lambda n: "“" + "\n\n".join(composites_posts() * (n // 12000 + 1))[:n],
        "every paragraph a heading": lambda n: "\n\n".join(f"## 제목 {i}" for i in range(n // 12)),
        "numbered lines": lambda n: "\n".join(f"{i % 99 + 1}. 항목 {i} 입니다" for i in range(n // 15)),
        "one unsplittable run": lambda n: ("가나다 " * n)[:n],
        "tiny paragraphs": lambda n: "\n\n".join(["가"] * (n // 3)),
        "code fence": lambda n: "```\n" + "# 주석\n\n" * (n // 8) + "```\n",
    }

    def test_linear_time_and_lossless_on_adversarial_100k_shapes(self):
        for name, make in self.SHAPES.items():
            with self.subTest(name):
                timings = {}
                for size in (10_000, 100_000):
                    text = make(size)
                    started = time.perf_counter()
                    spans, _ = chunk.compute_spans(text)
                    timings[size] = time.perf_counter() - started
                    self.assertEqual("".join(text[s["start"]:s["end"]] for s in spans), text)
                self.assertLessEqual(timings[100_000], 2.0, f"{name}: {timings[100_000]:.3f}s")
                self.assertLessEqual(timings[100_000] / max(timings[10_000], 0.03), 15, f"{name}: {timings}")

    def test_prepare_and_reassemble_100k_end_to_end(self):
        run, manifest = self.prepared("\n\n".join(composites_posts() * 9)[:100_000])
        source = run.source()
        for c in manifest["chunks"]:
            if not c["passthrough"]:
                (run.path / c["rewritten_file"]).write_text(source[c["start"]:c["end"]], encoding="utf-8")
        started = time.perf_counter()
        report = chunk.reassemble(run.path)
        self.assertLessEqual(time.perf_counter() - started, 1.0)
        self.assertEqual((run.path / "03_reassembled.md").read_text(encoding="utf-8"), source)
        self.assertEqual(report["rolled_back_chunks"], [])


if __name__ == "__main__":
    unittest.main()
