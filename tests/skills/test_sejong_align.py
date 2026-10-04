"""Super Sejong Engine v2 sentence alignment (WP-2, DESIGN.md 3.8 and 6).

The reference is the T2 prototype aligner (docs/research/super-sejong/v2/prototypes/T2_gate.py),
loaded here with its own sentence splitter so both aligners see the same sentence lists.
"""
import importlib.util
import json
import random
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine_runtime"))
from sejong import align as aligner  # noqa: E402
from sejong.align import Pair, align, align_documents, band_width  # noqa: E402
from sejong.types import Document, Unit  # noqa: E402

PROTOTYPES = ROOT / "docs" / "research" / "super-sejong" / "v2" / "prototypes"
_SPLIT = re.compile(r"(?<=[.!?])\s+")


def load_t2():
    """T2_voice (imported by T2_gate as `voice`) and T2_gate, without leaving `voice` behind."""
    saved = sys.modules.get("voice")
    try:
        modules = {}
        for name, file in (("voice", "T2_voice.py"), ("t2_gate", "T2_gate.py")):
            spec = importlib.util.spec_from_file_location(name, PROTOTYPES / file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            modules[name] = module
        return modules["voice"], modules["t2_gate"]
    finally:
        sys.modules.pop("t2_gate", None)
        if saved is None:
            sys.modules.pop("voice", None)
        else:
            sys.modules["voice"] = saved


VOICE, T2 = load_t2()


def t2_pairs():
    data = json.loads((PROTOTYPES / "T2_pairs.json").read_text(encoding="utf-8"))
    return [(r["id"], r["src"], r["out"]) for label in ("preserve", "drift") for r in data[label]]


def t2_cmc_pairs():
    data = json.loads((PROTOTYPES / "T2_pairs_cmc.json").read_text(encoding="utf-8"))
    # preserve rows: [id, group, src, out]; drift rows: [id, type, severity, src, out]
    return [(row[0], row[-2], row[-1]) for label in ("preserve", "drift") for row in data[label]]


def sentences(text):
    return [s for s in _SPLIT.split(text.strip()) if s]


def units(paragraphs):
    """types.Unit list from paragraphs of sentences (offsets are not used by the aligner)."""
    out, pos = [], 0
    for para, sents in enumerate(paragraphs):
        for text in sents:
            out.append(Unit(f"S{len(out) + 1}", pos, pos + len(text), pos, pos + len(text), para, "body", text))
            pos += len(text) + 1
    return out


def by_paragraph(segments):
    """T2 Seg list -> paragraphs of sentence texts (Seg.par is the T2 paragraph index)."""
    groups = {}
    for seg in segments:
        groups.setdefault(seg.par, []).append(seg.text)
    return [groups[key] for key in sorted(groups)]


def links(pairs):
    return [(tuple(p.src), tuple(p.out)) for p in pairs]


def t2_links(src_segments, out_segments):
    return [(tuple(s), tuple(o)) for s, o in T2.align(src_segments, out_segments)]


def assert_complete(test, pairs, n, m):
    """Every index exactly once, in order, and only the five shapes."""
    test.assertEqual([i for p in pairs for i in p.src], list(range(n)))
    test.assertEqual([j for p in pairs for j in p.out], list(range(m)))
    test.assertTrue(all(p.shape in ("1:1", "1:2", "2:1", "1:0", "0:1") for p in pairs))
    for p in pairs:
        for side in (p.src, p.out):
            test.assertEqual(list(side), list(range(side[0], side[0] + len(side))) if side else [])


def composite(records, *, per=4, seed=0, edits=0):
    """A multi-paragraph document from the T2 records (per records to a paragraph) and its
    rewrite, with `edits` random deletions or insertions of whole sentences in the rewrite."""
    rng = random.Random(seed)
    src_pars, out_pars = [], []
    for k in range(0, len(records), per):
        group = records[k:k + per]
        src_pars.append(" ".join(r[1] for r in group))
        out_pars.append([r[2] for r in group])
    pool = [r[1] for r in records]
    for _ in range(edits):
        par = out_pars[rng.randrange(len(out_pars))]
        if rng.choice(("delete", "insert")) == "delete" and len(par) > 1:
            par.pop(rng.randrange(len(par)))
        else:
            par.insert(rng.randrange(len(par) + 1), rng.choice(pool))
    return "\n\n".join(src_pars), "\n\n".join(" ".join(p) for p in out_pars)


class Basics(unittest.TestCase):
    def test_identity_is_all_one_to_one(self):
        text = [s for _, src, _ in t2_pairs() for s in sentences(src)]
        for inputs in (text, units([text[:40], text[40:90], text[90:]])):
            pairs = align(inputs, inputs)
            self.assertEqual(links(pairs), [((i,), (i,)) for i in range(len(text))])
            self.assertTrue(all(p.score == 1.0 for p in pairs))

    def test_similarity_ignores_spacing_and_punctuation(self):
        self.assertEqual(aligner.similarity("확인해 주세요.", "확인해주세요!"), 1.0)
        self.assertEqual(aligner.similarity("", "확인"), 0.0)
        # Lines without content characters keep their own characters instead of all matching.
        self.assertEqual(aligner.similarity("😀", "😢"), 0.0)
        self.assertEqual(aligner.similarity("ㅋㅋ", "ㅋㅋ"), 1.0)

    def test_empty_sides(self):
        self.assertEqual(align([], []), [])
        self.assertEqual(links(align(["가나다."], [])), [((0,), ())])
        self.assertEqual(links(align([], ["가나다.", "라마바."])), [((), (0,)), ((), (1,))])

    def test_band_formula_and_cell_budget(self):
        self.assertEqual(band_width(10, 10), 8)
        self.assertEqual(band_width(10, 13), 14)
        self.assertEqual(band_width(3442, 3442 - 50), 108)
        # 3,442 sentences fit 2*|n-m| + 8 up to |n-m| = 68; past that the band stops growing.
        self.assertEqual(band_width(3442, 3442 - 1500), band_width(3442, 3442 - 68))
        self.assertLessEqual((3442 + 1) * (2 * band_width(3442, 1942) + 1), aligner.MAX_CELLS)

    def test_narrow_band_override_still_covers_everything(self):
        src = [s for _, s0, _ in t2_pairs()[:30] for s in sentences(s0)]
        out = src[:5] + src[12:]
        for band in (0, 1, 2):
            assert_complete(self, align(src, out, band=band), len(src), len(out))


class T2Agreement(unittest.TestCase):
    """Acceptance: pair agreement with the T2 aligner >= 99% on the 128 T2 pairs."""

    def agreement(self, records):
        same = 0
        for _, src, out in records:
            s, o = VOICE.split_sentences(src), VOICE.split_sentences(out)
            same += links(align_documents(by_paragraph(s), by_paragraph(o))) == t2_links(s, o)
        return same

    def test_t2_pair_set(self):
        records = t2_pairs()
        self.assertEqual(len(records), 128)
        self.assertEqual(self.agreement(records), 128)        # measured 128/128

    def test_t2_cmc_pair_set(self):
        records = t2_cmc_pairs()
        self.assertEqual(len(records), 20)
        self.assertEqual(self.agreement(records), 20)

    def test_multi_paragraph_composites(self):
        # T2 aligns the whole text as one block; v2 keeps paragraphs apart, so the only allowed
        # differences are T2 pairings that cross a paragraph boundary.
        records = t2_pairs()
        total = same = 0
        for seed, edits in ((0, 0), (1, 5), (2, 15), (5, 5), (13, 15), (19, 5)):
            src, out = composite(records, seed=seed, edits=edits)
            s, o = VOICE.split_sentences(src), VOICE.split_sentences(out)
            ours, ref = links(align_documents(by_paragraph(s), by_paragraph(o))), t2_links(s, o)
            assert_complete(self, align_documents(by_paragraph(s), by_paragraph(o)), len(s), len(o))
            total += len(ref)
            same += len(set(ours) & set(ref))
            for si, oi in set(ref) - set(ours):
                pars = {s[i].par for i in si} | {o[j].par for j in oi}
                self.assertGreater(len(pars), 1, f"seed {seed}: in-paragraph disagreement {si} {oi}")
        self.assertGreaterEqual(same / total, 0.99)


class Shapes(unittest.TestCase):
    def shape_of(self, record_id):
        _, src, out = next(r for r in t2_pairs() if r[0] == record_id)
        return [p.shape for p in align(sentences(src), sentences(out))]

    def test_split_and_merge_on_the_t2_pairs(self):
        for record_id in ("p53", "p55", "d55", "d56"):
            self.assertEqual(self.shape_of(record_id), ["2:1"], record_id)
        for record_id in ("p54", "p56", "d62"):
            self.assertEqual(self.shape_of(record_id), ["1:2"], record_id)
        for record_id in ("p61", "p62", "p63", "d57", "d58"):
            self.assertEqual(set(self.shape_of(record_id)), {"1:1"}, record_id)

    def test_insert_and_delete_inside_a_paragraph(self):
        src = sentences(next(r[1] for r in t2_pairs() if r[0] == "p62")) + \
            sentences(next(r[1] for r in t2_pairs() if r[0] == "p61"))
        deleted = src[:2] + src[3:]
        self.assertEqual(links(align(src, deleted)),
                         [((0,), (0,)), ((1,), (1,)), ((2,), ()), ((3,), (2,)), ((4,), (3,))])
        inserted = src[:2] + ["그리고 오늘 날씨는 맑고 바람이 조금 붑니다."] + src[2:]
        self.assertEqual(links(align(src, inserted)),
                         [((0,), (0,)), ((1,), (1,)), ((), (2,)), ((2,), (3,)), ((3,), (4,)), ((4,), (5,))])

    def test_split_and_merge_inside_a_longer_rewrite(self):
        records = {r[0]: r for r in t2_pairs()}
        ids = ("p01", "p53", "p02", "p54", "p03", "p55", "p04")
        src = [s for k in ids for s in sentences(records[k][1])]
        out = [s for k in ids for s in sentences(records[k][2])]
        shapes = [p.shape for p in align(src, out)]
        self.assertEqual(shapes, ["1:1", "2:1", "1:1", "1:2", "1:1", "2:1", "1:1"])

    def test_random_edits_always_give_a_complete_monotone_alignment(self):
        pool = [s for _, src, out in t2_pairs() for s in sentences(src) + sentences(out)]
        rng = random.Random(7)
        for _ in range(200):
            src = rng.sample(pool, rng.randrange(0, 12))
            out = [s for s in src if rng.random() > 0.2]
            for _ in range(rng.randrange(0, 3)):
                out.insert(rng.randrange(len(out) + 1), rng.choice(pool))
            assert_complete(self, align(src, out), len(src), len(out))


class Paragraphs(unittest.TestCase):
    def setUp(self):
        records = t2_pairs()
        self.src = [[s for r in records[k:k + 4] for s in sentences(r[1])] for k in range(0, 40, 4)]
        self.out = [[s for r in records[k:k + 4] for s in sentences(r[2])] for k in range(0, 40, 4)]

    def test_input_shapes_agree(self):
        src_units, out_units = units(self.src), units(self.out)
        expected = links(align_documents(self.src, self.out))
        self.assertEqual(links(align(src_units, out_units)), expected)
        self.assertEqual(links(align_documents(src_units, out_units)), expected)
        doc = lambda us: Document(" ".join(u.text for u in us), [], us)  # noqa: E731
        self.assertEqual(links(align_documents(doc(src_units), doc(out_units))), expected)
        # Without paragraph keys the lists are aligned as one block.
        flat_src, flat_out = [s for p in self.src for s in p], [s for p in self.out for s in p]
        self.assertEqual(links(align(flat_src, flat_out)), links(align_documents([flat_src], [flat_out])))

    def test_paragraphs_stop_cross_boundary_pairings(self):
        # The first sentence of paragraph 1 is deleted and paragraph 0 gains an unrelated last
        # sentence. Paragraph-first keeps them apart; one block pairs them 1:1 (T2's behaviour).
        src = [["신청은 온라인으로 진행합니다."], ["처리 기간은 20일입니다.", "결과는 문자로 알려 드립니다."]]
        out = [["신청은 온라인으로 진행합니다.", "최근 3개년 재무제표를 준비합니다."], ["결과는 문자로 알려 드립니다."]]
        self.assertEqual(links(align_documents(src, out)),
                         [((0,), (0,)), ((), (1,)), ((1,), ()), ((2,), (2,))])
        flat = links(align([s for p in src for s in p], [s for p in out for s in p]))
        self.assertIn(((1,), (1,)), flat)

    def test_paragraph_count_mismatch_falls_back_to_one_block(self):
        merged = [self.out[0] + self.out[1]] + self.out[2:]
        flat_src = [s for p in self.src for s in p]
        flat_out = [s for p in merged for s in p]
        pairs = align_documents(self.src, merged)
        self.assertEqual(links(pairs), links(align(flat_src, flat_out)))
        self.assertEqual(links(pairs), links(align_documents(self.src, self.out)))
        split = self.out[:3] + [self.out[3][:2], self.out[3][2:]] + self.out[4:]
        self.assertEqual(links(align_documents(self.src, split)), links(align_documents(self.src, self.out)))

    def test_displaced_paragraphs_fall_back_to_one_block(self):
        # Equal paragraph counts, but the writer merged paragraphs 1 and 2 and split paragraph 3:
        # pairing by order would set paragraph 2 against half of paragraph 3.
        p = self.out
        out = [p[0], p[1] + p[2], p[3][:2], p[3][2:]] + p[4:]
        src = self.src[:len(out)]
        out_units = units(out)
        src_units = units(src)
        sr = aligner._ranges([u.para for u in src_units])
        orr = aligner._ranges([u.para for u in out_units])
        side = aligner._Side([u.text for u in src_units]), aligner._Side([u.text for u in out_units])
        self.assertTrue(aligner._displaced(side[0], side[1], sr, orr))
        flat = links(align([u.text for u in src_units], [u.text for u in out_units]))
        self.assertEqual(links(align(src_units, out_units)), flat)
        # The one-block result follows the content: source paragraph 2 lands in the merged
        # output paragraph 1, and source paragraph 3 in output paragraphs 2 and 3.
        landing = {}
        for si, oi in flat:
            for i in si:
                landing.setdefault(src_units[i].para, set()).update(out_units[j].para for j in oi)
        self.assertEqual(landing, {0: {0}, 1: {1}, 2: {1}, 3: {2, 3}, **{k: {k} for k in range(4, len(src))}})

    def test_rewritten_paragraph_without_better_neighbour_stays_in_order(self):
        src = [["신청은 온라인으로 진행합니다."], ["오늘은 날씨가 맑습니다."], ["결과는 문자로 알려 드립니다."]]
        out = [["신청은 온라인으로 진행합니다."], ["하늘이 개었어요."], ["결과는 문자로 알려 드립니다."]]
        self.assertEqual(links(align_documents(src, out)), [((0,), (0,)), ((1,), (1,)), ((2,), (2,))])


class Performance(unittest.TestCase):
    """DESIGN.md 6: alignment of a 100k-char document <= 0.5 s; adversarial shapes <= 2 s."""

    @classmethod
    def setUpClass(cls):
        records = [r for r in t2_pairs() if r[0].startswith("p")]
        cls.src, cls.out, chars, k = [], [], 0, 0
        while chars < 100_000:
            group = [records[(k * 4 + i) % len(records)] for i in range(4)]
            k += 1
            cls.src.append([s for r in group for s in sentences(r[1])])
            cls.out.append([s for r in group for s in sentences(r[2])])
            chars += sum(len(s) for s in cls.src[-1])
        cls.chars = chars

    def timed(self, src, out, *, documents=True):
        best = float("inf")
        for _ in range(3):
            started = time.perf_counter()
            pairs = align_documents(src, out) if documents else align(src, out)
            best = min(best, time.perf_counter() - started)
        return best, pairs

    def test_100k_chars_within_half_a_second(self):
        self.assertGreaterEqual(self.chars, 100_000)
        n = sum(len(p) for p in self.src)
        for label, out in (("identity", self.src), ("rewrite", self.out),
                           ("paragraph merged", [self.out[0] + self.out[1]] + self.out[2:])):
            with self.subTest(case=label):
                seconds, pairs = self.timed(self.src, out)
                assert_complete(self, pairs, n, sum(len(p) for p in out))
                self.assertLessEqual(seconds, 0.5, f"{label}: {seconds:.3f}s")

    def test_adversarial_shapes_within_two_seconds(self):
        flat_src = [s for p in self.src for s in p]
        flat_out = [s for p in self.out for s in p]
        rng = random.Random(3)
        dropped = list(flat_out)
        for _ in range(300):
            dropped.pop(rng.randrange(len(dropped)))
        one = " ".join(flat_src)
        tiny = [chr(0xAC00 + i % 11172) for i in range(50_000)]
        for label, src, out in (("300 sentences dropped", flat_src, dropped),
                                ("one 100k sentence", [one], [one.replace("합니다", "해요")]),
                                ("50,000 one-char sentences", tiny, tiny[::-1])):
            with self.subTest(case=label):
                started = time.perf_counter()
                pairs = align(src, out)
                seconds = time.perf_counter() - started
                assert_complete(self, pairs, len(src), len(out))
                self.assertLessEqual(seconds, 2.0, f"{label}: {seconds:.3f}s")


if __name__ == "__main__":
    unittest.main()
