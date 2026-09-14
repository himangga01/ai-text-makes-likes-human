from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engine_runtime.workflow import verify


class ContentFidelityTest(unittest.TestCase):
    def gate(self, source, candidate, attempt):
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / 'before.txt', Path(folder) / 'after.txt'
            suffix = ' 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.\n'
            before.write_text(source + suffix, encoding='utf-8')
            after.write_text(candidate + suffix, encoding='utf-8')
            return verify(before, after, attempt=attempt)

    def test_signed_quantities_and_units_cannot_change(self):
        for source, candidate in [('올해 수익률은 -5%다.', '올해 수익률은 5%다.'),
                                  ('최종 권장량은 5mg이다.', '최종 권장량은 5g이다.')]:
            for attempt, policy in [(1, 'retry'), (2, 'rollback')]:
                with self.subTest(source=source, attempt=attempt):
                    result = self.gate(source, candidate, attempt)
                    self.assertEqual(result['policy'], policy)
                    self.assertIn('quantity_changed', result['hardFailures'])

    def test_short_attributed_speech_is_immutable(self):
        result = self.gate('담당자는 "승인한다"라고 말했다.', '담당자는 "거부한다"라고 말했다.', 2)
        self.assertEqual(result['policy'], 'rollback')
        self.assertIn('quote_altered', result['hardFailures'])

    def test_number_formatting_and_unchanged_quotes_stay_valid(self):
        result = self.gate('가격은 1,000원이다. 담당자는 "승인한다"라고 말했다.',
                           '가격은 1000원이다. 담당자는 "승인한다"라고 말했다.', 1)
        self.assertEqual(result['hardFailures'], [])

    def test_rhetorical_quotes_do_not_become_immutable(self):
        result = self.gate('이것이 "정답"일까?', '이것이 "해답"일까?', 2)
        self.assertNotIn('quote_altered', result['hardFailures'])
