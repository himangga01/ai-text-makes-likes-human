"""Super Sejong Engine v2 flow and clarity guards (WP-7, DESIGN.md 3.8, 3.10; T5 section 4, T4 section 6).

Every text here is constructed (tests/skills/data/sejong_flow_cases.json) or comes from the seed
benchmark; no owner text. The mutation set is the T5 mutation test (T5 section 4) run on 24 constructed
passages instead of the owner's posts, plus twelve classes written after the guard (EXTRA_HARM) and the
seed benchmark's own gold fixes as real, minimal edits. The numbers are in-sample for the T5 classes
(the guard was written knowing them), exactly as T5 says of its own table.
"""
import collections
import json
import random
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine_runtime"))
from sejong import clarity, config, flow, text as T, types  # noqa: E402
from sejong.align import align_documents  # noqa: E402

CASES = json.loads((ROOT / "tests" / "skills" / "data" / "sejong_flow_cases.json").read_text(encoding="utf-8"))
SEED = ROOT / "docs" / "research" / "super-sejong" / "v2" / "benchmark"
DETAIL = re.compile(r"[a-z0-9_:>+\-]*\Z")      # details are labels and counts, never text


def prepare(src, out):
    a, b = T.segment(src), T.segment(out)
    return a, b, align_documents(a, b)


def flow_of(src, out, **kwargs):
    a, b, pairs = prepare(src, out)
    return flow.check(a, b, pairs, **kwargs)


def clarity_of(src, out, **kwargs):
    a, b, pairs = prepare(src, out)
    return clarity.check(a, b, pairs, **kwargs)


def codes(violations):
    return sorted({v.code for v in violations})


def seed_texts():
    rows = []
    for name in ("seed_benchmark.jsonl", "seed_composites.jsonl"):
        for line in (SEED / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


# --------------------------------------------------------------------------
# T5 mutation test on constructed passages
# --------------------------------------------------------------------------
def build(paragraphs):
    """[('h', text) | ('p', [sentences])] of a passage, through the engine's own segmenter."""
    text = "\n\n".join(paragraphs)
    blocks = []
    for index in sorted({u.para for u in T.segment(text).units}):
        units = [u for u in T.segment(text).units if u.para == index]
        blocks.append(["h", units[0].text] if units[0].kind == "heading" else ["p", [u.text for u in units]])
    return blocks


def render(blocks):
    return "\n\n".join(v if k == "h" else " ".join(v) for k, v in blocks) + "\n"


def clone(blocks):
    return [[k, (list(v) if isinstance(v, list) else v)] for k, v in blocks]


CONTRAST = ("하지만", "다만", "그러나", "그런데", "반면에", "반면")
ADD = ("또한", "그리고", "게다가", "더불어", "아울러", "나아가")


def lead(word):
    return re.compile("^(" + re.escape(word) + r")[,\s]+")


def plain(blocks, min_len=0):
    return [i for i, (k, v) in enumerate(blocks) if k == "p" and len(" ".join(v)) >= min_len]


def first_has_connective(sentence):
    return flow.initial_connective(sentence) is not None


def m_add(word, count):
    def mutate(blocks, rng):
        blocks = clone(blocks)
        idx = [i for i in plain(blocks, 40)[1:] if not first_has_connective(blocks[i][1][0])]
        if len(idx) < count:
            return None
        for i in rng.sample(idx, count):
            blocks[i][1][0] = word + ", " + blocks[i][1][0]
        return blocks
    return mutate


def m_drop(words, count=1):
    def mutate(blocks, rng):
        blocks = clone(blocks)
        found = [(i, j, w) for i, (k, v) in enumerate(blocks) if k == "p" for j, s in enumerate(v)
                 for w in words if lead(w).match(s)]
        if not found:
            return None
        for i, j, w in rng.sample(found, min(count, len(found))):
            blocks[i][1][j] = lead(w).sub("", blocks[i][1][j])
        return blocks
    return mutate


def m_swap_lead(words, new):
    def mutate(blocks, rng):
        blocks = clone(blocks)
        found = [(i, j, w) for i, (k, v) in enumerate(blocks) if k == "p" for j, s in enumerate(v)
                 for w in words if lead(w).match(s)]
        if not found:
            return None
        i, j, w = rng.choice(found)
        blocks[i][1][j] = lead(w).sub(new + " ", blocks[i][1][j])
        return blocks
    return mutate


def m_swap_sentences(blocks, rng):
    blocks = clone(blocks)
    idx = [i for i in plain(blocks) if len(blocks[i][1]) >= 2 and not first_has_connective(blocks[i][1][1])]
    if not idx:
        return None
    i = rng.choice(idx)
    blocks[i][1][0], blocks[i][1][1] = blocks[i][1][1], blocks[i][1][0]
    return blocks


def m_swap_paragraphs(blocks, rng):
    blocks = clone(blocks)
    idx = [i for i in range(1, len(blocks) - 2) if blocks[i][0] == "p" and blocks[i + 1][0] == "p"
           and len(" ".join(blocks[i][1])) > 40 and len(" ".join(blocks[i + 1][1])) > 40]
    if not idx:
        return None
    i = rng.choice(idx)
    blocks[i], blocks[i + 1] = blocks[i + 1], blocks[i]
    return blocks


def m_merge_paragraphs(blocks, rng):
    blocks = clone(blocks)
    idx = [i for i in range(1, len(blocks) - 1) if blocks[i][0] == "p" and blocks[i + 1][0] == "p"]
    if not idx:
        return None
    i = rng.choice(idx)
    blocks[i][1] = blocks[i][1] + blocks[i + 1][1]
    del blocks[i + 1]
    return blocks


def m_split_paragraph(blocks, rng):
    blocks = clone(blocks)
    idx = [i for i in plain(blocks) if len(blocks[i][1]) >= 2]
    if not idx:
        return None
    i = rng.choice(idx)
    a = blocks[i][1]
    blocks[i:i + 1] = [["p", a[:1]], ["p", a[1:]]]
    return blocks


def m_duplicate(blocks, rng):
    blocks = clone(blocks)
    idx = plain(blocks, 40)
    if not idx:
        return None
    i = rng.choice(idx)
    j = rng.randrange(len(blocks[i][1]))
    blocks[i][1].insert(j + 1, blocks[i][1][j])
    return blocks


def m_closing(blocks, rng):
    blocks = clone(blocks)
    idx = plain(blocks)
    if len(idx) < 2:
        return None
    blocks[idx[-1]][1] = blocks[idx[-1]][1] + ["결론적으로, 위 내용을 꼭 확인하시기 바랍니다."]
    return blocks


def m_drop_sentence(blocks, rng):
    blocks = clone(blocks)
    idx = [i for i in plain(blocks, 60) if len(blocks[i][1]) >= 2]
    if not idx:
        return None
    i = rng.choice(idx)
    del blocks[i][1][rng.randrange(len(blocks[i][1]))]
    return blocks


MERGES = (("합니다.", "하며,"), ("입니다.", "이며,"), ("됩니다.", "되며,"))


def m_merge_myeo(blocks, rng):
    blocks = clone(blocks)
    found = [(i, j) for i, (k, v) in enumerate(blocks) if k == "p" for j in range(len(v) - 1)
             if any(v[j].endswith(a) for a, _ in MERGES) and not first_has_connective(v[j + 1])]
    if not found:
        return None
    i, j = rng.choice(found)
    s = blocks[i][1][j]
    for a, b in MERGES:
        if s.endswith(a):
            blocks[i][1][j] = s[:-len(a)] + b
            break
    blocks[i][1][j:j + 2] = [blocks[i][1][j] + " " + blocks[i][1][j + 1]]
    return blocks


def m_split_myeo(blocks, rng):
    blocks = clone(blocks)
    found = [(i, j) for i, (k, v) in enumerate(blocks) if k == "p" for j, s in enumerate(v)
             if re.search(r"(하|이|되)며, [가-힣]", s)]
    if not found:
        return None
    i, j = rng.choice(found)
    s = blocks[i][1][j]
    m = re.search(r"(하|이|되)며, ", s)
    end = {"하": "합니다.", "이": "입니다.", "되": "됩니다."}[m.group(1)]
    blocks[i][1][j:j + 1] = [s[:m.start()] + end, s[m.end():]]
    return blocks


def m_swap_word(old, new):
    def mutate(blocks, rng):
        blocks = clone(blocks)
        found = [(i, j) for i, (k, v) in enumerate(blocks) if k == "p" for j, s in enumerate(v) if lead(old).match(s)]
        if not found:
            return None
        i, j = rng.choice(found)
        blocks[i][1][j] = lead(old).sub(new + " ", blocks[i][1][j])
        return blocks
    return mutate


EDITS = (("좋습니다", "바람직합니다"), ("중요합니다", "핵심입니다"), ("확인해 보시기 바랍니다", "확인해 보세요"),
         ("충분합니다", "넉넉합니다"), ("도움이 됩니다", "도움을 줍니다"), ("매우", "아주"), ("조금", "다소"))


def m_word_edits(blocks, rng):
    blocks = clone(blocks)
    found = [(i, j, old, new) for i, (k, v) in enumerate(blocks) if k == "p" for j, s in enumerate(v)
             for old, new in EDITS if old in s]
    if not found:
        return None
    for i, j, old, new in rng.sample(found, min(3, len(found))):
        blocks[i][1][j] = blocks[i][1][j].replace(old, new, 1)
    return blocks


def m_identity(blocks, rng):
    return clone(blocks)


NEUTRAL_CONTRAST = ("하지만", "다만", "그러나", "반면에", "반면")


def m_swap_contrast(blocks, rng):
    blocks = clone(blocks)
    found = [(i, j, w) for i, (k, v) in enumerate(blocks) if k == "p" for j, s in enumerate(v)
             for w in NEUTRAL_CONTRAST if lead(w).match(s)]
    if not found:
        return None
    i, j, w = rng.choice(found)
    new = "그러나" if w != "그러나" else "하지만"
    blocks[i][1][j] = lead(w).sub(new + " ", blocks[i][1][j])
    return blocks


def m_duplicate_far(blocks, rng):
    """A first sentence copied into a paragraph two or more paragraphs further on."""
    blocks = clone(blocks)
    idx = plain(blocks, 40)
    if len(idx) < 4:
        return None
    i = rng.choice(idx[:-2])
    k = rng.choice([x for x in idx if x >= i + 2])
    blocks[k][1].insert(rng.randrange(len(blocks[k][1]) + 1), blocks[i][1][0])
    return blocks


def m_move_sentence(blocks, rng):
    """The last sentence of a paragraph moved to the start of the next one."""
    blocks = clone(blocks)
    idx = [i for i in plain(blocks) if len(blocks[i][1]) >= 2 and i + 1 < len(blocks) and blocks[i + 1][0] == "p"]
    if not idx:
        return None
    i = rng.choice(idx)
    blocks[i + 1][1].insert(0, blocks[i][1].pop())
    return blocks


def m_merge_causal(blocks, rng):
    """Two sentences joined with an explicit reason: ... 합니다. X -> ... 하기 때문에 X."""
    blocks = clone(blocks)
    found = [(i, j) for i, (k, v) in enumerate(blocks) if k == "p" for j in range(len(v) - 1)
             if v[j].endswith("합니다.") and not first_has_connective(v[j + 1])]
    if not found:
        return None
    i, j = rng.choice(found)
    blocks[i][1][j:j + 2] = [blocks[i][1][j][:-4] + "하기 때문에 " + blocks[i][1][j + 1]]
    return blocks


def m_inline_contrast(blocks, rng):
    """The end of a sentence rewritten with a concession: ... 지만 모두에게 해당하는 것은 아닙니다."""
    blocks = clone(blocks)
    found = [(i, j) for i, (k, v) in enumerate(blocks) if k == "p" for j, s in enumerate(v) if s.endswith("습니다.") and " " in s]
    if not found:
        return None
    i, j = rng.choice(found)
    blocks[i][1][j] = blocks[i][1][j][:-4] + "지만 모두에게 해당하는 것은 아닙니다."
    return blocks


# (name, mutator, expected code or None, draws). A hard class is "detected" when the expected code is raised.
HARM = [
    ("F1a add 또한 (3)", m_add("또한", 3), "flow_transition_added", 2),
    ("F1b add 따라서 (3)", m_add("따라서", 3), "flow_transition_added", 2),
    ("F1c add 결론적으로 (1)", m_add("결론적으로", 1), "flow_transition_added", 2),
    ("F2a drop contrast connective", m_drop(CONTRAST), "flow_contrast_changed", 2),
    ("F3a contrast -> 따라서", m_swap_lead(CONTRAST, "따라서"), "flow_contrast_changed", 2),
    ("F3b 따라서 -> 하지만", m_swap_lead(("따라서",), "하지만"), "flow_contrast_changed", 2),
    ("F4 swap two sentences", m_swap_sentences, "flow_order_changed", 2),
    ("F5 swap two paragraphs", m_swap_paragraphs, "flow_order_changed", 2),
    ("F8 merge two paragraphs", m_merge_paragraphs, "flow_paragraph_count_changed", 2),
    ("F9 split a paragraph", m_split_paragraph, "flow_paragraph_count_changed", 2),
    ("F12 duplicate a sentence", m_duplicate, "flow_duplicate", 2),
]
# Not in T5's mutation list: classes written after the guard, to see that it is not only fitted to its own list.
EXTRA_HARM = [
    ("E1 add 게다가 (3)", m_add("게다가", 3), "flow_transition_added", 2),
    ("E2 add 그리고 (1)", m_add("그리고", 1), "flow_transition_added", 2),
    ("E3 add 먼저 (1)", m_add("먼저", 1), "flow_transition_added", 2),
    ("E4 add 그러나 (1)", m_add("그러나", 1), "flow_contrast_changed", 2),
    ("E5 add 특히 (2)", m_add("특히", 2), "flow_transition_added", 2),
    ("E6 add 이처럼 (1)", m_add("이처럼", 1), "flow_transition_added", 2),
    ("E7 contrast -> 또한", m_swap_lead(CONTRAST, "또한"), "flow_contrast_changed", 2),
    ("E8 또한 -> 따라서", m_swap_word("또한", "따라서"), "flow_transition_added", 2),
    ("E9 merge two sentences with 하기 때문에", m_merge_causal, "flow_transition_added", 2),
    ("E10 concession appended to a sentence", m_inline_contrast, "flow_contrast_changed", 2),
    ("E11 copy a sentence two paragraphs away", m_duplicate_far, "flow_duplicate", 2),
    ("E12 move a sentence to the next paragraph", m_move_sentence, "flow_order_changed", 2),
]
BENIGN = [
    ("B0 identity", m_identity, 1),
    ("B1 merge via 하며/이며/되며", m_merge_myeo, 1),
    ("B2 split at 하며/이며/되며", m_split_myeo, 1),
    ("B3 또한 -> 그리고", m_swap_word("또한", "그리고"), 1),
]
BENIGN_EXTRA = [
    ("B4 contrast -> 그러나/하지만", m_swap_contrast, 1),
    ("B5 또한 -> 아울러", m_swap_word("또한", "아울러"), 1),
    ("B6 word-level edits", m_word_edits, 1),
]


def run_mutation(mutator, draws):
    """[(passage id, flow violations)] for every passage the mutation applies to."""
    results = []
    for passage in CASES["passages"]:
        blocks = build(passage["paragraphs"])
        src = render(blocks)
        for rep in range(draws):
            rng = random.Random(f"{passage['id']}-{mutator.__name__}-{rep}")
            changed = mutator(blocks, rng)
            if changed is None:
                continue
            out = render(changed)
            if out == src and mutator is not m_identity:
                continue
            results.append((passage["id"], flow_of(src, out)))
    return results


class PassageTests(unittest.TestCase):
    def test_passages_round_trip_and_are_constructed_sized(self):
        self.assertEqual(len(CASES["passages"]), 24)
        for passage in CASES["passages"]:
            with self.subTest(passage=passage["id"]):
                blocks = build(passage["paragraphs"])
                self.assertEqual(render(blocks), "\n\n".join(passage["paragraphs"]) + "\n")
                for k, v in blocks:
                    for sentence in ([] if k == "h" else v):
                        self.assertGreaterEqual(len(re.sub(r"[^가-힣]", "", sentence)), 12)


class MutationTests(unittest.TestCase):
    """T5 section 4: each hard class is detected with its own code; benign edits stay clean."""

    def test_every_hard_mutation_class_is_detected(self):
        for name, mutator, expected, draws in HARM:
            with self.subTest(mutation=name):
                results = run_mutation(mutator, draws)
                self.assertGreaterEqual(len(results), 20, name)
                missed = [pid for pid, found in results if expected not in codes(found)]
                self.assertEqual(missed, [], f"{name}: {len(missed)}/{len(results)} missed")

    def test_classes_outside_the_t5_list_are_detected_too(self):
        for name, mutator, expected, draws in EXTRA_HARM:
            with self.subTest(mutation=name):
                results = run_mutation(mutator, draws)
                self.assertGreaterEqual(len(results), 20, name)
                missed = [pid for pid, found in results if expected not in codes(found)]
                self.assertEqual(missed, [], f"{name}: {len(missed)}/{len(results)} missed")

    def test_closing_sentence_and_dropped_additive_connective(self):
        results = run_mutation(m_closing, 2)
        self.assertGreaterEqual(len(results), 40)
        # F1d: the closing sentence opens with 결론적으로, so it is a hard transition; sentence_added shadows it too
        self.assertTrue(all("flow_transition_added" in codes(found) for _, found in results))
        shadowed = sum(1 for _, found in results if "flow_sentence_added" in codes(found))
        self.assertGreaterEqual(shadowed * 10, len(results) * 8, (shadowed, len(results)))   # T5: 36/56 on real posts
        # F2b: dropping an additive connective is soft by design (T5 section 4): nothing is flagged
        results = run_mutation(m_drop(ADD), 2)
        self.assertGreaterEqual(len(results), 20)
        self.assertEqual([pid for pid, found in results if found], [])

    def test_dropped_sentence_is_not_a_flow_matter(self):
        results = run_mutation(m_drop_sentence, 2)
        self.assertGreaterEqual(len(results), 20)
        flagged = [pid for pid, found in results if set(codes(found)) - {"flow_contrast_changed"}]
        self.assertEqual(flagged, [])

    def test_benign_false_alarms_at_most_one_per_77(self):
        total = flagged = 0
        per_class = {}
        for name, mutator, draws in BENIGN + BENIGN_EXTRA:
            results = run_mutation(mutator, draws)
            hits = [(pid, codes(found)) for pid, found in results if found]
            per_class[name] = (len(results), hits)
            if (name, mutator, draws) in BENIGN:
                total += len(results)
                flagged += len(hits)
            self.assertGreaterEqual(len(results), 20, name)
        # the T5-comparable classes B0-B3 and every benign class together
        self.assertGreaterEqual(total, 77)
        self.assertLessEqual(flagged * 77, total, per_class)
        everything = sum(n for n, _ in per_class.values())
        self.assertLessEqual(sum(len(h) for _, h in per_class.values()) * 77, everything, per_class)

    def test_b1_merge_is_clean_for_flow_and_flagged_by_the_clarity_guard(self):
        merged = 0
        for passage in CASES["passages"]:
            blocks = build(passage["paragraphs"])
            changed = m_merge_myeo(blocks, random.Random(passage["id"]))
            if changed is None:
                continue
            a, b, pairs = prepare(render(blocks), render(changed))
            self.assertEqual(flow.check(a, b, pairs), [], passage["id"])
            merged += 1
            self.assertIn("clarity_longer_sentence", codes(clarity.check(a, b, pairs)), passage["id"])
        self.assertGreaterEqual(merged, 20)


# --------------------------------------------------------------------------
# lexicon and markers
# --------------------------------------------------------------------------
class LexiconTests(unittest.TestCase):
    def test_lexicon_shape(self):
        lexicon = flow.LEXICON
        self.assertEqual(set(lexicon["classes"]), {"additive", "contrast", "causal", "example", "summary", "sequence"})
        words = [w for ws in lexicon["classes"].values() for w in ws]
        self.assertEqual(len(words), len(set(words)))
        self.assertTrue(set(lexicon["added_classes"]) <= set(lexicon["classes"]))
        self.assertFalse(set(lexicon["spoken"]) & set(lexicon["written"]))

    def test_initial_connective(self):
        cases = {
            "또한 문의는 전화로 받습니다.": ("또한", "additive"),
            "또한, 문의는 전화로 받습니다.": ("또한", "additive"),
            "그러나 신청은 끝났습니다.": ("그러나", "contrast"),
            "“하지만 늦었어요.” 그가 말했습니다.": None,           # the connective is inside a quotation
            "- 따라서 서류가 필요합니다.": ("따라서", "causal"),     # list marker is not part of the sentence
            "> 결론적으로 정리합니다.": ("결론적으로", "summary"),
            "단, 현금은 받지 않습니다.": ("단,", "contrast"),
            "단 한 번도 없었습니다.": None,                         # 단 + space is "only", not the connective
            "또 다른 방법도 있습니다.": None,
            "또는 전화로 문의하세요.": None,
            "그런데도 신청자는 늘었습니다.": None,                   # an ending, not a sentence-initial connective
            "마지막으로, 정리해 보겠습니다.": ("마지막으로", "sequence"),
            "이유는 간단합니다.": None,
            "둘째 문장입니다.": None,                                 # an ordinal counts as a connective only with its comma
            "둘째, 서류를 준비합니다.": ("둘째,", "sequence"),
            "첫 번째 방법은 간단합니다.": None,
        }
        for sentence, expected in cases.items():
            with self.subTest(sentence=sentence):
                self.assertEqual(flow.initial_connective(sentence), expected)

    def test_marker_counts_ignore_quotes_and_cover_endings(self):
        def contrast(sentence):
            return len(flow._Feat(T.split_sentences(sentence)[0]).contrast)

        self.assertEqual(contrast("가격은 비싸지만 품질은 좋습니다."), 1)
        self.assertEqual(contrast("하지만 가격은 비싸지만 품질은 좋습니다."), 2)
        self.assertEqual(contrast("비용이 들었는데도 효과는 없었습니다."), 1)
        self.assertEqual(contrast("한데도 결과는 같았습니다."), 1)
        self.assertEqual(contrast("그는 “하지만 늦었어요”라고 말했습니다."), 0)
        self.assertEqual(contrast("원단, 가죽, 실을 샀습니다."), 0)
        self.assertEqual(contrast("신청은 오늘까지입니다."), 0)

    def test_starter_and_causal_patterns_are_anchored_per_word(self):
        def feat(sentence):
            return flow._Feat(T.split_sentences(sentence)[0])

        # the (?![가-힣]) guard belongs to every alternative, not only the last word of the list
        self.assertFalse(feat("이로운 점이 많습니다.").starter)
        self.assertFalse(feat("이유는 간단합니다.").starter)
        self.assertFalse(feat("이런저런 이유가 있습니다.").starter)
        self.assertTrue(feat("이는 중요합니다.").starter)
        self.assertTrue(feat("이 연구는 중요합니다.").starter)
        self.assertTrue(feat("이와 같은 경우입니다.").starter)
        self.assertEqual(feat("결국은 왔습니다.").causal, 0)
        self.assertEqual(feat("결국 왔습니다.").causal, 1)
        self.assertEqual(feat("비 때문에 취소되었고 정전 때문에 늦었습니다.").causal, 2)
        self.assertEqual(feat("왜냐하면 일정이 바뀌었습니다.").causal, 1)
        self.assertEqual(feat("왜냐하면 일정이 바뀌었기 때문입니다.").causal, 1)
        self.assertEqual(len(feat("비록 늦었지만 도착했습니다.").contrast), 1)
        self.assertEqual(len(feat("비록 늦었습니다.").contrast), 1)

    def test_body_text_strips_marks(self):
        self.assertEqual(flow.body_text("- 항목"), "항목")
        self.assertEqual(flow.body_text("1. 항목"), "항목")
        self.assertEqual(flow.body_text("> - 항목"), "항목")
        self.assertEqual(flow.body_text("항목 - 값"), "항목 - 값")


# --------------------------------------------------------------------------
# explicit cases
# --------------------------------------------------------------------------
class ExplicitFlowCases(unittest.TestCase):
    def test_flow_cases(self):
        self.assertGreaterEqual(len(CASES["flow"]), 40)
        for case in CASES["flow"]:
            with self.subTest(case=case["id"]):
                found = flow_of(case["src"], case["out"])
                self.assertEqual(codes(found), sorted(case["expect"]), [(v.code, v.detail) for v in found])
                self.check_shape(case["src"], found)

    def check_shape(self, src, found):
        ids = {u.id for u in T.segment(src).units}
        for v in found:
            self.assertEqual(v.family, "flow")
            self.assertTrue(types.is_code(v.code), v.code)
            self.assertIn(v.severity, ("hard", "soft"))
            self.assertEqual(v.severity == "soft", v.code in flow.SOFT_CODES)
            self.assertTrue(v.sentence is None or v.sentence in ids, v.sentence)
            self.assertRegex(v.detail, DETAIL)
            types.Violation.from_json(v.to_json())

    def test_codes_are_the_design_codes(self):
        self.assertEqual(set(flow.CODES), {
            "flow_transition_added", "flow_contrast_changed", "flow_paragraph_count_changed", "flow_order_changed",
            "flow_duplicate", "flow_context_leak", "flow_seam_connective_changed"})
        self.assertEqual(flow.SOFT_CODES, ("flow_sentence_added",))
        self.assertEqual(set(clarity.CODES), {
            "clarity_longer_sentence", "clarity_bare_demonstrative_added", "clarity_agentless_oblig_added",
            "clarity_acronym_gloss_dropped", "clarity_number_marker_changed", "clarity_list_structure_changed"})
        for code in flow.CODES + flow.SOFT_CODES + clarity.CODES:
            self.assertTrue(types.is_code(code), code)

    def test_every_hard_code_is_covered_by_the_explicit_cases(self):
        seen = set()
        for group in ("flow", "seam", "docSeam"):
            for case in CASES[group]:
                seen.update(case["expect"])
        self.assertEqual(seen, set(flow.CODES) | set(flow.SOFT_CODES))

    def test_contrast_violation_names_the_marker_to_keep(self):
        found = flow_of(CASES["flow"][0]["src"], CASES["flow"][0]["src"].replace("하지만 주차", "주차"))
        lost = [v for v in found if v.code == "flow_contrast_changed"]
        self.assertEqual([(v.detail, v.keep) for v in lost], [("lost", "하지만")])

    def test_allow_licenses_codes_per_source_sentence(self):
        case = next(c for c in CASES["flow"] if c["id"] == "relation_repair_is_blocked_without_a_licence")
        a, b, pairs = prepare(case["src"], case["out"])
        self.assertEqual(codes(flow.check(a, b, pairs)), ["flow_contrast_changed", "flow_transition_added"])
        found = flow.check(a, b, pairs, allow={"S1": ["flow_contrast_changed", "flow_transition_added"]})
        self.assertEqual(found, [])
        only = flow.check(a, b, pairs, allow={"S1": {"flow_contrast_changed"}})
        self.assertEqual(codes(only), ["flow_transition_added"])
        wrong_sentence = flow.check(a, b, pairs, allow={"S2": ["flow_contrast_changed", "flow_transition_added"]})
        self.assertEqual(codes(wrong_sentence), ["flow_contrast_changed", "flow_transition_added"])
        self.assertEqual(codes(flow.check(a, b, pairs, allow={})), ["flow_contrast_changed", "flow_transition_added"])

    def test_inserted_sentence_is_attached_to_the_sentence_before_it(self):
        src = "접수는 평일에만 가능합니다. 문의는 전화로 받습니다."
        out = "접수는 평일에만 가능합니다. 이상으로 오늘 안내를 모두 마치며 편하게 말씀해 주세요. 문의는 전화로 받습니다."
        found = flow_of(src, out)
        self.assertEqual([(v.code, v.sentence) for v in found], [("flow_sentence_added", "S1")])
        first = flow_of(src, "안녕하세요 오늘도 좋은 하루 보내고 계신가요. " + src)
        self.assertEqual([(v.code, v.sentence) for v in first], [("flow_sentence_added", "S1")])


class SeamTests(unittest.TestCase):
    def test_seam_cases(self):
        for case in CASES["seam"]:
            with self.subTest(case=case["id"]):
                found = flow_of(case["src"], case["out"], seam={"prev": case["prev"], "next": case["next"]})
                self.assertEqual(codes(found), sorted(case["expect"]), [(v.code, v.detail) for v in found])

    def test_doc_seam_cases(self):
        for case in CASES["docSeam"]:
            with self.subTest(case=case["id"]):
                a, b, pairs = prepare(case["src"], case["out"])
                offset = case["src"].index(case["seam_before"])
                found = flow.seam_check(a, b, [offset])
                self.assertEqual(codes(found), sorted(case["expect"]), [(v.code, v.detail) for v in found])
                for v in found:
                    self.assertEqual(v.family, "flow")
                    self.assertRegex(v.detail, DETAIL)

    def test_seam_invariants_hold_on_identity_with_and_without_seam(self):
        for case in CASES["seam"] + CASES["flow"]:
            a = T.segment(case["src"])
            pairs = align_documents(a, a)
            self.assertEqual(flow.check(a, a, pairs), [], case["id"])
            self.assertEqual(flow.check(a, a, pairs, seam={"prev": "앞 문단입니다.", "next": "뒤 문단입니다."}), [], case["id"])
            for u in a.units[1:]:
                self.assertEqual(flow.seam_check(a, a, [u.start]), [], case["id"])

    def test_manifest_forms(self):
        src = CASES["docSeam"][1]["src"]
        out = CASES["docSeam"][1]["out"]
        a, b, pairs = prepare(src, out)
        offset = src.index("다만 신청")
        chunks = [{"index": 1, "start": 0, "end": offset - 2, "passthrough": False},
                  {"index": 2, "start": offset, "end": len(src), "passthrough": False}]
        forms = {
            "list": [offset],
            "chunks": {"version": 1, "chunks": chunks},
            "sejong block": {"version": 1, "chunks": chunks, "sejong": {"version": 1, "genre": "blog", "seams": [
                {"chunk": 2, "prev": [0, offset - 2], "next": [offset, offset + 5]}]}},
        }
        for label, manifest in forms.items():
            with self.subTest(form=label):
                self.assertEqual(flow._seam_offsets(manifest), [offset] if label == "list" else flow._seam_offsets(manifest))
                self.assertEqual(codes(flow.seam_check(a, b, manifest)), ["flow_seam_connective_changed"])
        # a passthrough heading chunk is not a seam, and an offset outside the document is ignored
        self.assertEqual(flow._seam_offsets({"chunks": [{"start": 0, "passthrough": True}, {"start": 5}, {"start": 90}]}), [90])
        self.assertEqual(flow.seam_check(a, b, [0, len(src) + 50]), [])
        self.assertEqual(flow.seam_check(a, b, {"chunks": []}), [])

    def test_degenerate_inputs(self):
        some = "첫 문장은 접수 방법을 안내합니다. 둘째 문장은 서류 준비를 안내합니다."
        for src, out in (("", ""), ("", some), (some, ""), (some, some)):
            with self.subTest(src=bool(src), out=bool(out)):
                a, b, pairs = prepare(src, out)
                for seam in (None, {"prev": "앞", "next": "뒤"}):
                    flow.check(a, b, pairs, seam=seam)
                    clarity.check(a, b, pairs)
                flow.seam_check(a, b, [0, 5, 10_000])
        a = T.segment(some)
        self.assertEqual(flow.check(a, a, align_documents(a, a), seam={"prev": "앞", "next": "뒤"}), [])
        found = flow_of("", some)
        self.assertEqual(codes(found), ["flow_paragraph_count_changed", "flow_sentence_added"])
        # a list of units works like a Document
        pairs = align_documents(a, a)
        self.assertEqual(flow.check(a.units, a.units, pairs), [])
        self.assertEqual(clarity.check(a.units, a.units, pairs), [])

    def test_check_with_seam_accepts_missing_or_empty_context(self):
        case = CASES["seam"][0]
        for seam in (None, {}, {"prev": "", "next": ""}, {"prev": None}):
            found = flow_of(case["src"], case["out"], seam=seam)
            self.assertEqual(codes(found), ["flow_contrast_changed"])


# --------------------------------------------------------------------------
# clarity
# --------------------------------------------------------------------------
class ClarityTests(unittest.TestCase):
    def test_clarity_cases(self):
        self.assertGreaterEqual(len(CASES["clarity"]), 30)
        for case in CASES["clarity"]:
            with self.subTest(case=case["id"]):
                found = clarity_of(case["src"], case["out"], genre=case.get("genre", "general"))
                self.assertEqual(codes(found), sorted(case["expect"]), [(v.code, v.detail) for v in found])
                ids = {u.id for u in T.segment(case["src"]).units}
                for v in found:
                    self.assertEqual((v.family, v.severity), ("clarity", "hard"))
                    self.assertIn(v.sentence, ids)
                    self.assertRegex(v.detail, DETAIL)

    def test_every_clarity_code_has_positives_and_counterexamples(self):
        for code in clarity.CODES:
            positives = [c for c in CASES["clarity"] if code in c["expect"]]
            negatives = [c for c in CASES["clarity"] if c["target"] == code and code not in c["expect"]]
            self.assertGreaterEqual(len(positives), 2, code)
            self.assertGreaterEqual(len(negatives), 2, code)

    def test_long_review(self):
        long_sentence = ("신청서를 작성하시고 필요한 서류를 모두 챙기신 다음 창구에 방문하셔서 번호표를 받으시고 순서를 기다리시다가 "
                         "담당자의 안내에 따라 접수를 마치시고 영수증을 받아 가시면 되며 문의가 있으시면 언제든 전화로 말씀해 주시기 바랍니다.")
        self.assertEqual(len(long_sentence.split()), 29)
        self.assertTrue(clarity.long_review(long_sentence, "blog"))
        self.assertTrue(clarity.long_review(long_sentence, "essay"))
        self.assertFalse(clarity.long_review(long_sentence, "report"))        # 40 eojeol for report, document, general
        self.assertFalse(clarity.long_review(long_sentence))
        self.assertFalse(clarity.long_review("“" + long_sentence + "”라고 말했습니다.", "blog"))      # direct quotation
        self.assertFalse(clarity.long_review(" ".join(["단어"] * 35) + " 입니다.", "blog"))             # long, no clause endings
        self.assertFalse(clarity.long_review("접수는 평일에만 가능하며 문의는 전화로 받고 있습니다.", "blog"))
        heading = T.segment("## " + long_sentence + "\n\n본문입니다.").units[0]
        self.assertEqual(heading.kind, "heading")
        self.assertFalse(clarity.long_review(heading, "blog"))
        unit = T.segment(long_sentence).units[0]
        self.assertTrue(clarity.long_review(unit, "blog"))
        self.assertEqual(clarity.long_threshold("blog"), 28)
        self.assertEqual(clarity.long_threshold("anything"), 40)

    def test_clause_endings_do_not_match_nouns(self):
        words = "광고 문서 화면 지면 서 고 나 데".split() + ["끝입니다."]
        self.assertEqual(clarity.clause_endings(words), 0)
        self.assertEqual(clarity.clause_endings("작성하시고 챙기시며 가서 합니다.".split()), 2)

    def test_approx2(self):
        found = clarity.approx2("회의는 약 30분 정도 걸리고 대략 5명 안팎입니다. 거의 100명 가량이 왔습니다.")
        self.assertEqual([(f.rule, f.tier, f.action, f.fix) for f in found], [("CLR-APPROX2", "SUGGEST", "request", "")] * 3)
        text = "회의는 약 30분 정도 걸리고 대략 5명 안팎입니다. 거의 100명 가량이 왔습니다."
        self.assertEqual([text[f.start:f.end] for f in found], ["정도", "안팎", "가량"])
        for clean in ("만약 늦으면 연락하세요.", "계약 기간은 30일 정도입니다.", "노약자 30명 정도가 왔습니다.",
                      "약 30분 걸립니다.", "30분 정도 걸립니다.", "그는 “약 30분 정도”라고 말했습니다."):
            with self.subTest(text=clean):
                self.assertEqual(clarity.approx2(clean), [])
        finding = found[0]
        types.Finding.from_json(finding.to_json())

    def test_eojeol_count_ignores_list_marker(self):
        self.assertEqual(clarity.eojeol_count("- 신분증을 가져오세요."), 2)
        self.assertEqual(clarity.eojeol_count("1. 신분증을 가져오세요."), 2)
        self.assertEqual(clarity.eojeol_count("신분증을 가져오세요."), 2)


# --------------------------------------------------------------------------
# identity and real-sized inputs
# --------------------------------------------------------------------------
class IdentityTests(unittest.TestCase):
    def test_identity_is_clean_on_every_seed_text(self):
        rows = seed_texts()
        self.assertGreaterEqual(len(rows), 212)
        for row in rows:
            doc = T.segment(row["text"])
            pairs = align_documents(doc, doc)
            self.assertEqual(flow.check(doc, doc, pairs), [], row["id"])
            self.assertEqual(clarity.check(doc, doc, pairs), [], row["id"])
            self.assertEqual(flow.check(doc, doc, pairs, seam={"prev": "앞 문단.", "next": "뒤 문단."}), [], row["id"])
            seams = [u.start for u in doc.units if u.start > 0][::7]
            self.assertEqual(flow.seam_check(doc, doc, seams), [], row["id"])

    def test_identity_is_clean_on_constructed_passages_and_cases(self):
        texts = ["\n\n".join(p["paragraphs"]) for p in CASES["passages"]]
        for group, keys in (("flow", ("src", "out")), ("clarity", ("src", "out")), ("seam", ("src", "out"))):
            for case in CASES[group]:
                texts.extend(case[k] for k in keys)
        for text in texts:
            doc = T.segment(text)
            pairs = align_documents(doc, doc)
            self.assertEqual(flow.check(doc, doc, pairs), [])
            self.assertEqual(clarity.check(doc, doc, pairs), [])

    def test_gold_rewrites_of_the_seed_set(self):
        """The seed gold texts are the authors' minimal fixes: the only real edits available. A hard flow
        code may fire only where the gold fix itself changes a connective (injection category CONNECT:
        그러나 -> 그래서, 반면 -> 그 결과, 좋았지만 -> 좋아서); on every other gold fix flow and clarity stay
        clean except for clarity codes, which are counted but never gated (shadow family)."""
        flagged = collections.Counter()
        total = 0
        outside = []
        for row in seed_texts():
            if not row.get("gold_text") or row["gold_text"] == row["text"]:
                continue
            total += 1
            a, b, pairs = prepare(row["text"], row["gold_text"])
            hard = flow.check(a, b, pairs)
            for v in hard + clarity.check(a, b, pairs):
                flagged[v.code] += 1
            categories = {i.get("category") for i in row.get("injections", [])}
            if any(v.code in flow.CODES for v in hard) and "CONNECT" not in categories:
                outside.append((row["id"], codes(hard)))
        self.assertGreaterEqual(total, 100)
        self.assertEqual(outside, [], dict(flagged))
        self.assertGreaterEqual(sum(n for code, n in flagged.items() if code in flow.CODES), 3)   # the CONNECT fixes are caught


class ModeTests(unittest.TestCase):
    def violation(self, code):
        family = "clarity" if code in clarity.CODES else "flow"
        return types.Violation(code=code, family=family, severity="hard")

    def test_defaults(self):
        flags = config.Flags.from_env({})
        for code in flow.CODES:
            self.assertEqual(flow.violation_mode(flags, self.violation(code)), "enforce", code)
        self.assertEqual(flow.violation_mode(flags, self.violation("flow_sentence_added")), "shadow")
        for code in clarity.CODES:
            self.assertEqual(flow.violation_mode(flags, self.violation(code)), "shadow", code)
        self.assertEqual(config.family_mode(flags, "clarity"), "shadow")

    def test_overrides(self):
        shadow = config.Flags.from_env({"SUPER_SEJONG_MODE": "shadow"})
        self.assertEqual({flow.violation_mode(shadow, self.violation(c)) for c in flow.CODES + clarity.CODES + flow.SOFT_CODES}, {"shadow"})
        off = config.Flags.from_env({"SUPER_SEJONG_MODE": "off"})
        self.assertEqual({flow.violation_mode(off, self.violation(c)) for c in flow.CODES + clarity.CODES + flow.SOFT_CODES}, {"off"})
        enforced = config.Flags.from_env({"SUPER_SEJONG_GATE_CLARITY": "enforce", "SUPER_SEJONG_GATE_FLOW": "enforce"})
        self.assertEqual(flow.violation_mode(enforced, self.violation("clarity_longer_sentence")), "enforce")
        # promoting the whole flow family does not promote flow_sentence_added (SHADOW_CODES)
        self.assertEqual(flow.violation_mode(enforced, self.violation("flow_sentence_added")), "shadow")
        flow_off = config.Flags.from_env({"SUPER_SEJONG_GATE_FLOW": "off"})
        self.assertEqual(flow.violation_mode(flow_off, self.violation("flow_contrast_changed")), "off")
        self.assertEqual(flow.violation_mode(flow_off, self.violation("flow_sentence_added")), "off")
        with self.assertRaises(ValueError):
            flow.violation_mode(shadow, types.Violation(code="flow_x"))

    def test_emitted_violations_carry_their_family(self):
        src = CASES["flow"][0]["src"]
        found = flow_of(src, src.replace("하지만 주차", "따라서 주차") + " 결론적으로 위 내용을 반드시 확인하시기 바랍니다.")
        self.assertTrue({"flow_contrast_changed", "flow_transition_added", "flow_sentence_added"} <= set(codes(found)))
        flags = config.Flags.from_env({})
        modes = {v.code: flow.violation_mode(flags, v) for v in found}
        self.assertEqual(modes["flow_sentence_added"], "shadow")
        self.assertEqual(modes["flow_contrast_changed"], "enforce")
        for family in {v.family for v in found}:
            self.assertIn(family, types.FAMILIES)


class PerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paragraphs = [p for passage in CASES["passages"] for p in passage["paragraphs"]]
        cls.paragraphs = paragraphs

    def document(self, chars):
        out, size = [], 0
        while size < chars:
            for paragraph in self.paragraphs:
                out.append(paragraph)
                size += len(paragraph) + 2
                if size >= chars:
                    break
        return out

    def timed(self, src_paragraphs, out_paragraphs):
        src, out = "\n\n".join(src_paragraphs), "\n\n".join(out_paragraphs)
        a, b = T.segment(src), T.segment(out)
        pairs = align_documents(a, b)
        best = float("inf")
        for _ in range(3):
            started = time.perf_counter()
            flow.check(a, b, pairs)
            clarity.check(a, b, pairs)
            flow.seam_check(a, b, [u.start for u in a.units][::50], pairs)
            best = min(best, time.perf_counter() - started)
        return best, len(a.text)

    def rewrite(self, paragraphs):
        rng = random.Random(7)
        out = list(paragraphs)
        for i in range(0, len(out), 9):
            out[i] = "또한, " + out[i]
        for _ in range(len(out) // 40):
            i = rng.randrange(1, len(out) - 1)
            out[i:i + 2] = [out[i] + " " + out[i + 1]]
        for _ in range(len(out) // 40):
            i = rng.randrange(len(out))
            out.insert(i, out[i])
        return out

    def test_100k_characters_and_linear_growth(self):
        small, big = self.document(10_000), self.document(100_000)
        times = {}
        for label, paragraphs in (("10k", small), ("100k", big)):
            for case, out in (("identity", paragraphs), ("rewrite", self.rewrite(paragraphs))):
                seconds, chars = self.timed(paragraphs, out)
                times[(label, case)] = seconds
                if label == "100k":
                    self.assertGreaterEqual(chars, 100_000)
                    self.assertLessEqual(seconds, 1.0, f"{label} {case}: {seconds:.3f}s")
        for case in ("identity", "rewrite"):
            ratio = times[("100k", case)] / max(times[("10k", case)], 1e-3)
            self.assertLessEqual(ratio, 15, f"{case}: 100k/10k = {ratio:.1f}")

    def test_adversarial_shapes(self):
        big = self.document(100_000)
        for label, out in (("all paragraphs reversed", big[::-1]),
                           ("all sentences repeated", [p + " " + p for p in big]),
                           ("one paragraph", ["\n".join(big)]),
                           ("paragraphs dropped", big[::2])):
            with self.subTest(case=label):
                seconds, _ = self.timed(big, out)
                self.assertLessEqual(seconds, 3.0, f"{label}: {seconds:.3f}s")

    def test_one_huge_sentence_and_one_char_sentences(self):
        one = " ".join(self.document(100_000)).replace(".", ",")
        tiny = [chr(0xAC00 + i % 11172) + "." for i in range(20_000)]
        for label, src, out in (("one 100k sentence", [one], [one.replace("합니다", "해요")]),
                                ("20,000 one-char sentences reversed", tiny, tiny[::-1])):
            with self.subTest(case=label):
                seconds, _ = self.timed(src, out)
                self.assertLessEqual(seconds, 3.0, f"{label}: {seconds:.3f}s")


if __name__ == "__main__":
    unittest.main()
