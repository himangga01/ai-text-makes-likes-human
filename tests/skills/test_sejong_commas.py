"""Super Sejong Engine v2 comma rule (WP-9, DESIGN.md 3.7 step 5 and 4.2; T1 report 1.7 and 6 Improve 4).

Fixtures are constructed sentences and the project-authored seed benchmark
(docs/research/super-sejong/v2/benchmark/seed_benchmark.jsonl, original text); the owner's posts and the
KatFish corpora that the T1 probe ran on are not stored in the repository.
"""
import json
import random
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine_runtime"))
from sejong import commas  # noqa: E402
from sejong.align import similarity  # noqa: E402
from sejong.commas import count_connective_commas, strip_injected, strip_injected_report  # noqa: E402

try:
    from engine_runtime import comma_guard  # noqa: E402

    VENDOR = comma_guard.load_vendor()
except (ImportError, FileNotFoundError, OSError):          # vendor/ is removed in WP-18
    comma_guard = VENDOR = None

BENCHMARK = ROOT / "docs" / "research" / "super-sejong" / "v2" / "benchmark" / "seed_benchmark.jsonl"
PROTOTYPES = ROOT / "docs" / "research" / "super-sejong" / "v2" / "prototypes"
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_ENDING = re.compile(r"(고|며|지만|면서|는데|아서|어서|여서|해서|져서)(\s)")


def seed_texts():
    if not BENCHMARK.exists():
        return []
    return [json.loads(line)["text"] for line in BENCHMARK.read_text(encoding="utf-8").splitlines() if line.strip()]


def per_sentence(text, edit):
    """Apply edit(sentence) to every sentence of text, keeping the separators."""
    out, pos = [], 0
    for m in _SENTENCE_END.finditer(text):
        out.append(edit(text[pos:m.start()]))
        out.append(m.group())
        pos = m.end()
    out.append(edit(text[pos:]))
    return "".join(out)


def only_commas_removed(test, candidate, result):
    """result is candidate with some commas deleted and nothing else changed."""
    i = 0
    for ch in candidate:
        if i < len(result) and result[i] == ch:
            i += 1
        else:
            test.assertEqual(ch, ",", "a character other than a comma changed")
    test.assertEqual(i, len(result), "result has characters candidate lacks")


def commas_of(sentence):
    return sentence.count(",")


class WriterCommasKept(unittest.TestCase):
    """The T1 probe shape: a one-word edit at the start of a sentence removes none of the writer's commas."""

    def test_one_word_edit_at_sentence_start_removes_nothing(self):
        before = ("그는 밥을 먹고, 학교에 갔다. 날씨가 좋았지만, 바람이 불었다.\n"
                  "서류를 검토하고, 보완이 필요해서, 연락드립니다. 문의는 전화로 하시고, 결과를 기다려 주세요.\n")
        after = per_sentence(before, lambda s: "정말 " + s if s.strip() else s)
        self.assertEqual(strip_injected_report(before, after)[0], after)
        self.assertEqual(strip_injected(before, after), (after, 0))
        if VENDOR is not None:      # the legacy stripper deletes every one of them: the bug being fixed
            self.assertEqual(VENDOR.strip_injected(before, after)[1]["commas_removed"], 5)

    def test_the_probe_on_every_seed_sentence_with_a_connective_comma(self):
        probes = removed = 0
        for text in seed_texts():
            for sentence in _SENTENCE_END.split(text):
                if count_connective_commas(sentence) == 0:
                    continue
                probes += 1
                after = text.replace(sentence, "정말 " + sentence, 1)
                removed += strip_injected(text, after)[1]
        self.assertGreaterEqual(probes, 30)          # 54 in the current seed benchmark
        self.assertEqual(removed, 0)

    def test_every_sentence_edited_at_once_in_every_seed_text(self):
        for text in seed_texts():
            self.assertEqual(strip_injected(text, per_sentence(text, lambda s: "정말 " + s)), (
                per_sentence(text, lambda s: "정말 " + s), 0))

    def test_mid_sentence_word_edits_remove_nothing(self):
        random.seed(7)
        for text in seed_texts():
            def edit(sentence):
                words = sentence.split(" ")
                inside = [i for i, w in enumerate(words) if "," not in w and len(w) >= 2]
                if inside:
                    words[random.choice(inside)] += "조차"
                return " ".join(words)
            after = per_sentence(text, edit)
            self.assertEqual(strip_injected(text, after)[1], 0, text)

    def test_the_writers_comma_stays_when_the_word_before_it_changes(self):
        before = "서류를 검토하고, 보완이 필요하면 연락합니다."
        for after in ("서류를 확인하고, 보완이 필요하면 연락합니다.", "서류를 꼼꼼히 살펴보고, 필요하면 연락합니다."):
            self.assertEqual(strip_injected(before, after), (after, 0))


class InjectedCommas(unittest.TestCase):
    def test_a_comma_added_to_an_edited_sentence_is_removed(self):
        self.assertEqual(strip_injected("그는 밥을 먹고 학교에 갔다.\n", "그는 아침을 먹고, 학교에 갔다.\n"),
                         ("그는 아침을 먹고 학교에 갔다.\n", 1))

    def test_the_writers_comma_stays_and_the_injected_one_goes(self):
        text, report = strip_injected_report("서류를 검토하고, 보완이 필요해서 연락합니다.\n",
                                             "서류를 꼼꼼히 검토하고, 보완이 필요해서, 연락드립니다.\n")
        self.assertEqual(text, "서류를 꼼꼼히 검토하고, 보완이 필요해서 연락드립니다.\n")
        self.assertEqual((report["commas_removed"], report["sentences_touched"]), (1, 1))

    def test_removed_down_to_the_source_count(self):
        before = "그는 밥을 먹고, 책을 읽으며 쉬다가 잠들었다."
        after = "그는 밥을 먹고, 책을 읽으며, 쉬다가, 잠들었는데, 아무도 몰랐고, 조용했다."
        text, removed = strip_injected(before, after)
        self.assertEqual(count_connective_commas(before), 1)
        # 쉬다가, is not connective-ending (가 is not in the list) and stays
        self.assertEqual(text, "그는 밥을 먹고, 책을 읽으며 쉬다가, 잠들었는데 아무도 몰랐고 조용했다.")
        self.assertEqual(removed, 3)

    def test_the_count_never_drops_below_the_writers(self):
        # Three commas in the rewrite against two in the source: only one has to go, and the rewrite
        # no longer lines up with the source's commas character by character.
        before = "밥을 먹고, 책을 읽으며, 일찍 잤다."
        after = "밥을 먹은 뒤에 책을 읽고, 쉬면서, 일찍 잤는데, 일찍 잤다."
        self.assertGreater(similarity(before, after), commas.MIN_SCORE)
        text, removed = strip_injected(before, after)
        self.assertEqual(removed, 1)
        self.assertEqual(commas_of(text), 2)
        only_commas_removed(self, after, text)

    def test_a_sentence_the_source_has_verbatim_is_the_writers_wherever_it_moved(self):
        before = "서류를 검토하고, 연락합니다. 결과를 확인하며, 기다립니다."
        after = "결과를 확인하며, 기다립니다. 서류를 검토하고, 연락합니다."
        self.assertEqual(strip_injected(before, after), (after, 0))

    def test_a_moved_word_keeps_its_comma(self):
        # The alignment cannot pair a word that moved against the order; the word and its comma are the writer's
        before = "A서류를 확인하고, B사본을 정리해 C보고서를 보냈다."
        after = "C보고서를 보내려고 B사본을 정리해 A서류를 확인하고, 끝내면서, 쉬었다."
        self.assertEqual(strip_injected(before, after)[0], "C보고서를 보내려고 B사본을 정리해 A서류를 확인하고, 끝내면서 쉬었다.")
        # without any alignment (a sentence above MAX_PIECE) the word rule alone picks the writer's comma:
        # the rewrite's own comma is the one nearest to the source's in relative position
        pad = "가나다 " * 800
        before = pad + "확인하고, 연락합니다."
        after = "확인하고, " + pad + "보내고, 연락합니다."
        text, report = strip_injected_report(before, after)
        self.assertEqual(report["pairs_unaligned"], 1)
        self.assertEqual(text, "확인하고, " + pad + "보내고 연락합니다.")

    def test_a_repeated_word_matches_only_as_often_as_the_source_has_it(self):
        before = "남자는 뼈대가 크고 근육이 붙는 몸으로 크고, 여자는 작다."
        after = "남자는 뼈대가 크고, 근육이 붙는 몸으로 크고, 여자는 작다."
        self.assertEqual(strip_injected(before, after)[0], before)

    def test_equal_counts_are_kept_even_when_the_commas_moved(self):
        before = "서류를 확인하고, 사본을 보냈다."
        after = "서류를 확인하고 사본을 보내면서, 마무리했다."
        self.assertEqual(strip_injected(before, after), (after, 0))

    def test_a_new_sentence_is_new(self):
        before = "결과는 다음 주에 나옵니다.\n"
        after = "결과는 다음 주에 나옵니다. 확인하고, 연락하겠습니다.\n"
        self.assertEqual(strip_injected(before, after),
                         ("결과는 다음 주에 나옵니다. 확인하고 연락하겠습니다.\n", 1))

    def test_a_rewrite_that_shares_nothing_with_its_partner_is_new(self):
        before = "정책이 바뀌었으니 확인하세요. 내일 회의가 있습니다."
        after = "정책이 바뀌었으니 확인하세요. 비용을 정리하고, 일정을 잡고, 보고서를 쓴다."
        self.assertLess(similarity("내일 회의가 있습니다.", "비용을 정리하고, 일정을 잡고, 보고서를 쓴다."), commas.MIN_SCORE)
        self.assertEqual(strip_injected(before, after)[0],
                         "정책이 바뀌었으니 확인하세요. 비용을 정리하고 일정을 잡고 보고서를 쓴다.")

    def test_a_split_pair_shares_the_sources_count(self):
        before = "서류를 검토하고, 보완이 필요하면 연락합니다."
        after = "서류를 검토하고, 보완이 필요하면 연락합니다. 연락은 전화로 하시고, 결과를 기다려 주세요."
        # the added sentence is new: its comma goes; the source's own comma stays
        self.assertEqual(strip_injected(before, after)[0],
                         "서류를 검토하고, 보완이 필요하면 연락합니다. 연락은 전화로 하시고 결과를 기다려 주세요.")
        split = "서류를 검토합니다. 보완이 필요해서, 연락합니다."
        self.assertEqual(strip_injected("서류를 검토하고 보완이 필요해서 연락합니다.", split)[0],
                         "서류를 검토합니다. 보완이 필요해서 연락합니다.")

    def test_a_merged_pair_keeps_the_commas_of_both_source_sentences(self):
        before = "서류를 검토하고, 접수했다. 결과를 확인하며, 기다렸다."
        after = "서류를 검토하고, 접수한 뒤 결과를 확인하며, 기다렸다."
        self.assertEqual(strip_injected(before, after), (after, 0))
        injected = "서류를 검토하고, 접수한 뒤 결과를 확인하며, 기다리다가 쉬고, 있었다."
        self.assertEqual(strip_injected(before, injected)[0], "서류를 검토하고, 접수한 뒤 결과를 확인하며, 기다리다가 쉬고 있었다.")

    def test_a_long_sentence_falls_back_to_the_count(self):
        long_before = "가나다 " * 800 + "확인하고, 연락합니다."
        long_after = "가나다 " * 800 + "확인하고, 보내고, 연락합니다. "
        self.assertGreater(len(long_before), commas.MAX_PIECE)
        text, report = strip_injected_report(long_before, long_after)
        self.assertEqual(report["pairs_unaligned"], 1)
        self.assertEqual((report["commas_removed"], commas_of(text)), (1, 1))
        only_commas_removed(self, long_after, text)

    def test_only_commas_are_ever_touched_and_line_endings_survive(self):
        before = "첫째 줄에서 확인하고\r\n둘째 줄은 그대로 둔다.\r\n\r\n셋째 문단을 읽고, 알려 주세요.\r\n"
        after = "첫째 줄에서 확인하고,\r\n둘째 줄은 그대로 두고, 확인한다.\r\n\r\n셋째 문단을 읽고, 알려 주시고, 끝낸다.\r\n"
        text, removed = strip_injected(before, after)
        only_commas_removed(self, after, text)
        self.assertEqual(text, "첫째 줄에서 확인하고\r\n둘째 줄은 그대로 두고 확인한다.\r\n\r\n셋째 문단을 읽고, 알려 주시고 끝낸다.\r\n")
        self.assertEqual(removed, 3)

    def test_idempotent(self):
        for before, after in (("서류를 검토하고, 보완이 필요해서 연락합니다.", "서류를 꼼꼼히 검토하고, 보완이 필요해서, 연락드립니다."),
                              ("결과는 나왔다.", "결과는 나왔다. 그리고, 확인하고, 알려드립니다."),
                              ("그리고 비용은 늘었다.", "그리고, 비용은 늘었다.")):
            for restore in (False, True):
                once = strip_injected(before, after, restore_dropped=restore)[0]
                self.assertEqual(strip_injected(before, once, restore_dropped=restore), (once, 0))

    def test_every_seed_text_with_commas_injected(self):
        """Injecting a comma after every connective ending of every edited sentence: the writer's commas all
        survive, only commas change, and a second pass changes nothing."""
        checked = 0
        for text in seed_texts():
            edited = per_sentence(text, lambda s: "정말 " + s)
            injected = _ENDING.sub(lambda m: m.group(1) + "," + m.group(2), edited)
            result, removed = strip_injected(text, injected)
            only_commas_removed(self, injected, result)
            for before, after in zip(_SENTENCE_END.split(edited), _SENTENCE_END.split(result)):
                self.assertGreaterEqual(commas_of(after), commas_of(before))      # no writer comma lost
            self.assertEqual(strip_injected(text, result), (result, 0))
            checked += removed > 0
        self.assertGreaterEqual(checked, 20)


class Exceptions(unittest.TestCase):
    def test_quotes_and_noun_lists_are_untouched(self):
        quoted = '그는 "먹고, 자고, 일했다"라고 말했다.\n'
        self.assertEqual(strip_injected("그는 말했다.\n", quoted), (quoted, 0))
        listed = "주요 비용은 재고, 창고, 광고비로 구분된다.\n"
        self.assertEqual(strip_injected("주요 비용은 재고와 창고와 광고비로 구분된다.\n", listed), (listed, 0))

    def test_a_quotation_across_sentences_is_found_on_the_whole_text(self):
        quoted = "그는 “먹고, 자고. 일하고, 쉬었다”라고 말했다."
        self.assertEqual(strip_injected("그는 말했다.", quoted), (quoted, 0))
        for opening, closing in (("‘", "’"), ("「", "」"), ("『", "』")):
            marked = "그는 %s먹고, 자고. 일하고, 쉬었다%s라고 말했다." % (opening, closing)
            self.assertEqual(strip_injected("그는 말했다.", marked), (marked, 0))

    def test_an_inch_mark_or_an_unclosed_quote_is_not_a_quotation(self):
        self.assertEqual(strip_injected('배관을 점검한다.', '5" 배관을 확인하고, 교체했다.')[0], '5" 배관을 확인하고 교체했다.')
        self.assertEqual(strip_injected("회의를 연다.", "“회의를 확인하고, 연다.")[0], "“회의를 확인하고 연다.")

    def test_a_list_of_verbs_is_not_a_noun_list(self):
        self.assertEqual(strip_injected("그는 말했다.", "그는 먹고, 자고, 일했다.")[0], "그는 먹고 자고 일했다.")

    def test_the_go_nouns_are_never_connectives(self):
        for noun in ("재고", "창고", "광고", "최고", "경고", "원고", "잔고", "공고", "출고", "금고"):
            text = "%s, 사본을 확인했다." % noun
            self.assertEqual(strip_injected("사본을 확인했다.", text), (text, 0))

    def test_a_comma_without_white_space_after_it_is_not_a_connective_comma(self):
        text = "그는 1,000원을 먹고,갔다."
        self.assertEqual(strip_injected("그는 갔다.", text), (text, 0))

    def test_a_comma_ending_a_line_is_a_connective_comma(self):
        self.assertEqual(strip_injected("첫째\n둘째", "정말 첫째 확인하고,\n둘째")[0], "정말 첫째 확인하고\n둘째")


class InitialConnectives(unittest.TestCase):
    def test_the_writers_initial_comma_stays(self):
        before = "그리고, 비용은 늘었다."
        for after in ("그리고, 비용이 늘었다.", "그리고, 비용은 크게 늘었다."):
            self.assertEqual(strip_injected(before, after), (after, 0))

    def test_a_changed_connective_keeps_the_writers_comma(self):
        before = "하지만, 비용은 늘었다."
        self.assertEqual(strip_injected(before, "그러나, 비용은 늘었다."), ("그러나, 비용은 늘었다.", 0))

    def test_a_newly_inserted_initial_comma_is_removed(self):
        for word in ("그리고", "하지만", "그러나", "그런데"):
            text, removed = strip_injected("%s 비용은 늘었다." % word, "%s, 비용은 늘었다." % word)
            self.assertEqual((text, removed), ("%s 비용은 늘었다." % word, 1), word)

    def test_an_initial_comma_in_an_inserted_sentence_is_new(self):
        before = "결과는 나왔다."
        self.assertEqual(strip_injected(before, "결과는 나왔다. 하지만, 비용은 늘었다.")[0], "결과는 나왔다. 하지만 비용은 늘었다.")

    def test_the_initial_comma_is_outside_the_count(self):
        # k = 0: the writer has only the initial comma; the comma after 확인하고 is the rewrite's
        self.assertEqual(count_connective_commas("그리고, 확인하고 연락했다."), 0)
        self.assertEqual(strip_injected("그리고, 확인하고 연락했다.", "그리고, 확인하고, 연락했다.")[0], "그리고, 확인하고 연락했다.")

    def test_a_mid_sentence_connective_is_an_ordinary_connective_comma(self):
        # only a comma at the start of a sentence is the initial-connective case
        self.assertEqual(strip_injected("비용이 늘었다. 그는 말했다.", "비용이 늘었다. 그는 하지만, 말했다.")[0],
                         "비용이 늘었다. 그는 하지만 말했다.")
        self.assertEqual(strip_injected("비용이 늘었다. 그는 말했다.", "비용이 늘었다. 그는 그러나, 말했다.")[1], 0)

    def test_marks_in_front_of_the_connective(self):
        self.assertEqual(strip_injected("- 그리고 확인한다.", "- 그리고, 확인한다.")[0], "- 그리고 확인한다.")
        quoted = '“그리고, 이것이 끝이다”라고 그는 말했다.'
        self.assertEqual(strip_injected("그는 말했다.", quoted), (quoted, 0))


class RestoreDropped(unittest.TestCase):
    def test_default_off(self):
        before = "그는 밥을 먹고, 학교에 갔다."
        after = "그는 밥을 먹고 학교에 갔다."
        self.assertEqual(strip_injected(before, after), (after, 0))
        self.assertEqual(strip_injected_report(before, after)[1]["commas_restored"], 0)

    def test_restores_a_comma_deleted_between_the_same_two_words(self):
        for before, after, expected in (
                ("그는 밥을 먹고, 학교에 갔다.", "그는 밥을 먹고 학교에 갔다.", "그는 밥을 먹고, 학교에 갔다."),
                ("물론, 비용은 늘었다.", "물론 비용은 늘었다.", "물론, 비용은 늘었다."),
                ("그는 밥을 먹고, 학교에 갔다.", "그는 아침을 먹고 학교에 갔다.", "그는 아침을 먹고, 학교에 갔다."),
        ):
            text, report = strip_injected_report(before, after, restore_dropped=True)
            self.assertEqual(text, expected)
            self.assertEqual((report["commas_removed"], report["commas_restored"]), (0, 1))
        self.assertEqual(strip_injected("그는 밥을 먹고, 학교에 갔다.", "그는 밥을 먹고 학교에 갔다.", restore_dropped=True)[1], 0)

    def test_not_restored_when_the_following_word_or_a_plain_left_word_changed(self):
        for after in ("그는 밥을 먹고 집에 갔다.", "그는 밥을 먹고 학교에서 갔다."):
            self.assertEqual(strip_injected("그는 밥을 먹고, 학교에 갔다.", after, restore_dropped=True)[0], after)
        # A left word without a connective ending must match exactly.
        self.assertEqual(strip_injected("사과, 배를 샀다.", "사과 배를 샀다.", restore_dropped=True)[0], "사과, 배를 샀다.")
        self.assertEqual(strip_injected("사과, 배를 샀다.", "포도 배를 샀다.", restore_dropped=True)[0], "포도 배를 샀다.")

    def test_restored_when_only_the_connective_clause_was_reworded(self):
        # The left word keeps its connective ending (-고), so the writer's comma comes back.
        self.assertEqual(strip_injected("그는 밥을 먹고, 학교에 갔다.", "그는 밥을 먹었고 학교에 갔다.", restore_dropped=True)[0],
                         "그는 밥을 먹었고, 학교에 갔다.")

    def test_numbers_and_commas_the_source_never_had(self):
        before = "금액은 1,000원이고, 기한은 내일입니다."
        after = "금액은 1,000원이고 기한은 내일입니다."
        self.assertEqual(strip_injected(before, after, restore_dropped=True)[0], before)
        self.assertEqual(strip_injected("비용이 늘었다.", "비용이 늘었다.", restore_dropped=True)[0], "비용이 늘었다.")

    def test_as_many_as_were_dropped(self):
        before = "가고, 나고 다. 가고, 나고 다."
        self.assertEqual(strip_injected_report(before, "가고 나고 다. 가고 나고 다.", restore_dropped=True)[0], before)
        once = "가고, 나고 다. 가고 나고 다."
        text, report = strip_injected_report(before, once, restore_dropped=True)
        self.assertEqual((text, report["commas_restored"]), (before, 1))

    def test_a_restored_comma_counts_toward_the_writers(self):
        # The rewrite deleted the comma after 먹고 and added one after 자고: with the restore, the writer's
        # comma is back and the added one exceeds the count, so it goes. Without it, the counts are equal.
        before = "먹고 자고, 갔다."
        after = "먹고, 자고 갔다."
        self.assertEqual(strip_injected(before, after)[0], after)
        self.assertEqual(strip_injected(before, after, restore_dropped=True)[0], before)

    def test_restore_and_strip_in_one_document(self):
        before = "서류를 검토하고, 보완이 필요해서 연락합니다.\n그리고, 결과를 알립니다.\n"
        after = "서류를 검토하고 보완이 필요해서, 연락드립니다.\n그리고 결과를 알립니다.\n"
        text, report = strip_injected_report(before, after, restore_dropped=True)
        self.assertEqual(text, "서류를 검토하고, 보완이 필요해서 연락드립니다.\n그리고, 결과를 알립니다.\n")
        self.assertEqual((report["commas_removed"], report["commas_restored"]), (1, 2))


class Splitting(unittest.TestCase):
    def test_sentences_and_paragraphs(self):
        text = '  첫째다. 둘째다.\n셋째는 "이다." 넷째다…\n\n다섯째다  '
        sents = commas._split(text)
        self.assertEqual([s.text for s in sents], ["첫째다.", "둘째다.", "셋째는 \"이다.\"", "넷째다…", "다섯째다"])
        self.assertEqual([s.para for s in sents], [0, 0, 0, 0, 1])
        for s in sents:
            self.assertEqual(text[s.start:s.end], s.text)
        self.assertEqual(commas._split(""), [])
        self.assertEqual(commas._split(" \n "), [])

    def test_the_pair_alignment_is_by_sentence_not_position(self):
        before = "첫째다. 서류를 검토하고, 연락한다. 끝이다."
        after = "서류를 검토하고, 보완이 필요해서, 연락한다. 끝이다."
        self.assertEqual(strip_injected(before, after)[0], "서류를 검토하고, 보완이 필요해서 연락한다. 끝이다.")

    def test_empty_inputs(self):
        self.assertEqual(strip_injected("", ""), ("", 0))
        self.assertEqual(strip_injected("", "그는 먹고, 갔다."), ("그는 먹고 갔다.", 1))
        self.assertEqual(strip_injected("그는 먹고, 갔다.", ""), ("", 0))
        self.assertEqual(strip_injected("   \n", "그는 먹고, 갔다.\n"), ("그는 먹고 갔다.\n", 1))


class QuoteSpans(unittest.TestCase):
    # Copied from vendor/humanize-engine/scripts/strip_injected_commas.py (MIT, (c) 2026 epoko77-ai).
    VENDOR_RE = re.compile(r"“[^”\n]*”|‘[^’\n]*’|(?<!\d)\"[^\"\n]*\"|「[^」\n]*」|『[^』\n]*』")

    def test_same_spans_as_the_vendored_regex_on_random_text(self):
        rng = random.Random(11)
        alphabet = "“”‘’\"\"「」『』 \n고,1가.5"
        for _ in range(3000):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
            self.assertEqual(commas._quote_spans(text), [m.span() for m in self.VENDOR_RE.finditer(text)], repr(text))

    def test_unclosed_openers_stay_linear(self):
        for text in ("“" * 100000, ("“a ‘b \"c " * 12000), "“" * 50000 + "\n" + "”" * 50000):
            started = time.perf_counter()
            commas._quote_spans(text)
            self.assertLess(time.perf_counter() - started, 0.5)


class ScoreFloor(unittest.TestCase):
    """MIN_SCORE separates sentences the writer rewrote from sentences the aligner paired by position."""

    def pairs(self):
        found = []
        data = json.loads((PROTOTYPES / "T2_pairs.json").read_text(encoding="utf-8"))
        found += [(r["src"], r["out"]) for label in ("preserve", "drift") for r in data[label]]
        for name in "ABC":
            data = json.loads((PROTOTYPES / ("T6_pairs_%s.json" % name)).read_text(encoding="utf-8"))
            found += [(r["source"], r["rewrite"]) for r in data]
        return found

    def test_rewrites_score_above_the_floor_and_unrelated_sentences_below(self):
        rewrites = [(a, b) for a, b in self.pairs() if len(a) >= 20 and len(b) >= 20]
        self.assertGreaterEqual(len(rewrites), 150)
        self.assertGreater(min(similarity(a, b) for a, b in rewrites), commas.MIN_SCORE + 0.05)
        sentences = [s for text in seed_texts() for s in _SENTENCE_END.split(text) if len(s) >= 20]
        rng = random.Random(5)
        scores = sorted(similarity(rng.choice(sentences), rng.choice(sentences)) for _ in range(5000))
        self.assertLess(scores[int(0.98 * len(scores))], commas.MIN_SCORE)


class Parity(unittest.TestCase):
    """Same output and count as engine_runtime/comma_guard.py on its test cases, where the DESIGN rule does
    not differ on purpose (it differs for 그러나/그런데 comma inserted at a sentence start, for commas that
    moved but keep the count, and in counting repeated words)."""

    CASES = (
        ("그는 밥을 먹고, 학교에 갔다. 날씨가 좋았지만, 바람이 불었다.\n", "그는 아침을 먹고, 학교에 갔다. 날씨가 맑았지만, 바람이 불었다.\n"),
        ("서류를 검토하고, 보완이 필요해서 연락합니다.\n", "서류를 꼼꼼히 검토하고, 보완이 필요해서, 연락드립니다.\n"),
        ("그는 밥을 먹고 학교에 갔다.\n", "그는 아침을 먹고, 학교에 갔다.\n"),
        ("결과는 다음 주에 나옵니다.\n", "결과는 다음 주에 나옵니다. 확인하고, 연락하겠습니다.\n"),
        ("그는 말했다.\n", '그는 "먹고, 자고, 일했다"라고 말했다.\n'),
        ("주요 비용은 재고와 창고와 광고비로 구분된다.\n", "주요 비용은 재고, 창고, 광고비로 구분된다.\n"),
        ("그는 밥을 먹고, 학교에 갔다. " * 30, ("그는 아침을 먹고, 학교에 갔다. " * 30).replace("갔다. 그는", "갔다. 그리고, 그는", 3)),
    )

    @unittest.skipIf(comma_guard is None, "engine_runtime/comma_guard.py or the vendored module is gone")
    def test_same_results_as_comma_guard(self):
        for before, after in self.CASES:
            expected_text, expected = comma_guard.strip_injected(before, after, VENDOR)
            text, report = strip_injected_report(before, after)
            self.assertEqual(text, expected_text, before)
            self.assertEqual(report["commas_removed"], expected["commas_removed"], before)
            self.assertEqual(report["sentences_touched"], expected["sentences_touched"], before)

    @unittest.skipIf(comma_guard is None, "engine_runtime/comma_guard.py or the vendored module is gone")
    def test_same_results_as_comma_guard_on_the_seed_texts(self):
        for text in seed_texts():
            after = per_sentence(text, lambda s: "정말 " + s)
            self.assertEqual(strip_injected_report(text, after)[0], comma_guard.strip_injected(text, after, VENDOR)[0])


class Performance(unittest.TestCase):
    UNIT = "그는 밥을 먹고, 학교에 갔다. 날씨가 좋았지만, 바람이 불었다. 서류를 검토하고 보완이 필요해서 연락합니다.\n"

    def document(self, chars):
        return self.UNIT * (chars // len(self.UNIT) + 1)

    def timed(self, before, after, **kw):
        started = time.perf_counter()
        result = strip_injected_report(before, after, **kw)
        return result, time.perf_counter() - started

    def test_a_100k_document_runs_well_under_a_second(self):
        before = self.document(100000)
        self.assertGreaterEqual(len(before), 100000)
        edited = before.replace("밥을", "아침을")
        (text, report), seconds = self.timed(before, edited)
        self.assertEqual((text, report["commas_removed"]), (edited, 0))
        self.assertLess(seconds, 1.0)
        injected = edited.replace("검토하고 보완", "검토하고, 보완").replace("필요해서 ", "필요해서, ")
        (text, report), seconds = self.timed(before, injected)
        self.assertEqual(text, edited)
        self.assertEqual(report["commas_removed"], 2 * (len(before) // len(self.UNIT)))
        self.assertLess(seconds, 1.0)
        _, seconds = self.timed(before, injected.replace("먹고, ", "먹고 "), restore_dropped=True)
        self.assertLess(seconds, 1.0)

    def test_the_100k_to_10k_time_ratio(self):
        def run(chars):
            before = self.document(chars)
            after = before.replace("밥을", "아침을").replace("필요해서 ", "필요해서, ")
            return min(self.timed(before, after)[1] for _ in range(5))
        small, large = run(10000), run(100000)
        self.assertLess(large / max(small, 1e-4), 15)

    def test_adversarial_shapes_stay_under_two_seconds(self):
        shapes = {
            "one 100k word": ("가" * 100000, "가" * 100000 + "."),
            "one 100k sentence with 12k commas": (" ".join(["가나다고,"] * 12000), " ".join(["가나다고,"] * 12000) + " 라마"),
            "unclosed quotes": ("“" * 100000, "“" * 100000 + "x"),
            "noun-list shape": (" 재고, 창고, 광고비," * 5000, " 재고, 창고, 광고비," * 5000 + "x"),
            "8,000 short lines": ("".join("항목%d 확인하고, 연락\n" % i for i in range(8000)),
                                  "".join("정말 항목%d 확인하고, 연락하고, 끝\n" % i for i in range(8000))),
            "repeating 1,000-char sentences with added commas": (("가고, 나고 " * 100 + "다. ") * 100,
                                                                 (("가고, 나고, " * 100) + "다. ") * 100),
        }
        for name, (before, after) in shapes.items():
            (_, report), seconds = self.timed(before, after)
            self.assertLess(seconds, 2.0, name)

    def test_the_character_alignment_has_a_budget(self):
        before = ("가고, 나고 " * 100 + "다. ") * 100
        after = (("가고, 나고, " * 100) + "다. ") * 100
        text, report = strip_injected_report(before, after)
        self.assertEqual(report["pairs_unaligned"], 100)             # each pair above MAX_PAIR_WORK
        self.assertEqual(report["commas_removed"], 100 * 100)         # the count rule alone: 200 - 100 per sentence


class Contract(unittest.TestCase):
    def test_return_types_and_inputs_are_not_mutated(self):
        before, after = "그는 먹고, 갔다.", "그는 아침을 먹고, 가서, 갔다."
        text, removed = strip_injected(before, after)
        self.assertIsInstance(text, str)
        self.assertIsInstance(removed, int)
        report = strip_injected_report(before, after)[1]
        self.assertEqual(set(report), {"commas_removed", "commas_restored", "sentences_touched", "pairs_unaligned"})
        self.assertEqual(report["commas_removed"], removed)
        self.assertEqual((before, after), ("그는 먹고, 갔다.", "그는 아침을 먹고, 가서, 갔다."))

    def test_no_change_returns_the_same_object(self):
        text = "그는 먹고, 갔다."
        self.assertIs(strip_injected_report(text, text)[0], text)

    def test_count_connective_commas(self):
        self.assertEqual(count_connective_commas("그는 먹고, 자고 갔다."), 1)
        self.assertEqual(count_connective_commas("그는 먹고, 자고, 갔다."), 2)
        self.assertEqual(count_connective_commas('그는 "먹고, 자고" 갔다.'), 0)
        self.assertEqual(count_connective_commas("재고, 창고, 광고비를 센다."), 2)      # counted, but never removed
        self.assertEqual(count_connective_commas("그리고, 센다."), 0)
        self.assertEqual(count_connective_commas(""), 0)

    def test_standard_library_only_and_no_vendor_import(self):
        source = (ROOT / "engine_runtime" / "sejong" / "commas.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^\s*(import|from)\s+(vendor|engine_runtime|importlib)")
        self.assertIn("vendor/humanize-engine/scripts/strip_injected_commas.py (MIT", source)


if __name__ == "__main__":
    unittest.main()


class RestoreAfterRewrittenClause(unittest.TestCase):
    def test_comma_after_a_rewritten_connective_clause_is_restored(self):
        # Live check 2026-10-04: the writer turned "가능하며," into "진행할 수 있으며" and dropped the comma.
        source = "신청은 온라인으로 진행이 가능하며, 서류가 누락되면 연락합니다."
        candidate = "신청은 온라인으로 진행할 수 있으며 서류가 누락되면 연락합니다."
        text, report = commas.strip_injected_report(source, candidate, restore_dropped=True)
        self.assertEqual(text, "신청은 온라인으로 진행할 수 있으며, 서류가 누락되면 연락합니다.")
        self.assertEqual(report["commas_restored"], 1)
        self.assertEqual(commas.strip_injected_report(source, candidate)[0], candidate)  # default off
