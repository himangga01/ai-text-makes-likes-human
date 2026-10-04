"""The comma guard removes only connective-ending commas a rewrite added, never the writer's own."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine_runtime import comma_guard  # noqa: E402
from engine_runtime.workflow import restore  # noqa: E402

VENDOR = comma_guard.load_vendor()


def strip(before, after):
    return comma_guard.strip_injected(before, after, VENDOR)


class WriterCommas(unittest.TestCase):
    def test_a_one_word_edit_keeps_the_writers_commas(self):
        before = '그는 밥을 먹고, 학교에 갔다. 날씨가 좋았지만, 바람이 불었다.\n'
        after = '그는 아침을 먹고, 학교에 갔다. 날씨가 맑았지만, 바람이 불었다.\n'
        self.assertEqual(strip(before, after), (after, {'commas_removed': 0, 'sentences_touched': 0}))
        # The vendored stripper removed both; this is the regression being fixed.
        self.assertEqual(VENDOR.strip_injected(before, after)[1]['commas_removed'], 2)

    def test_an_injected_comma_is_removed_and_the_writers_comma_kept(self):
        output, report = strip('서류를 검토하고, 보완이 필요해서 연락합니다.\n',
                               '서류를 꼼꼼히 검토하고, 보완이 필요해서, 연락드립니다.\n')
        self.assertEqual(output, '서류를 꼼꼼히 검토하고, 보완이 필요해서 연락드립니다.\n')
        self.assertEqual(report, {'commas_removed': 1, 'sentences_touched': 1})

    def test_comma_added_to_an_edited_sentence_is_removed(self):
        self.assertEqual(strip('그는 밥을 먹고 학교에 갔다.\n', '그는 아침을 먹고, 학교에 갔다.\n')[0],
                         '그는 아침을 먹고 학교에 갔다.\n')

    def test_a_new_sentence_is_still_treated_as_new(self):
        output, report = strip('결과는 다음 주에 나옵니다.\n', '결과는 다음 주에 나옵니다. 확인하고, 연락하겠습니다.\n')
        self.assertEqual(output, '결과는 다음 주에 나옵니다. 확인하고 연락하겠습니다.\n')
        self.assertEqual(report['commas_removed'], 1)

    def test_quotes_and_noun_lists_are_untouched(self):
        quoted = '그는 "먹고, 자고, 일했다"라고 말했다.\n'
        self.assertEqual(strip('그는 말했다.\n', quoted)[0], quoted)
        listed = '주요 비용은 재고, 창고, 광고비로 구분된다.\n'
        self.assertEqual(strip('주요 비용은 재고와 창고와 광고비로 구분된다.\n', listed)[0], listed)

    def test_long_documents_stay_fast(self):
        import time
        before = '그는 밥을 먹고, 학교에 갔다. ' * 3000
        started = time.perf_counter()
        _, report = strip(before, before.replace('밥을', '아침을'))
        self.assertEqual(report['commas_removed'], 0)
        self.assertLess(time.perf_counter() - started, 5)


class Integration(unittest.TestCase):
    def test_restore_keeps_the_writers_comma(self):
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / 'before.txt', Path(folder) / 'after.txt'
            before.write_text('그는 밥을 먹고, 학교에 갔다.\n', encoding='utf-8')
            after.write_text('그는 아침을 먹고, 학교에 갔다.\n', encoding='utf-8')
            self.assertEqual(restore(before, after)['removedCommas'], 0)
            self.assertEqual(after.read_text(encoding='utf-8'), '그는 아침을 먹고, 학교에 갔다.\n')

    def test_cli_used_by_the_server(self):
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / 'before.txt', Path(folder) / 'after.txt'
            before.write_text('서류를 검토하고, 보완이 필요해서 연락합니다.\n', encoding='utf-8')
            after.write_text('서류를 꼼꼼히 검토하고, 보완이 필요해서, 연락드립니다.\n', encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'engine_runtime' / 'comma_guard.py'),
                                     '--before', str(before), '--after', str(after), '--out', str(after), '--json'],
                                    capture_output=True, text=True, check=True,
                                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            self.assertIn('"commas_removed": 1', result.stderr)
            self.assertEqual(after.read_text(encoding='utf-8'), '서류를 꼼꼼히 검토하고, 보완이 필요해서 연락드립니다.\n')


if __name__ == '__main__':
    unittest.main()
