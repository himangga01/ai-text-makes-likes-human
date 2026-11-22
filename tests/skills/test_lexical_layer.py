"""Vendor lexical layer (im-not-ai 2.4.x) with the portal patch: hints, restore safety and file I/O."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'vendor/humanize-engine/scripts'
sys.path.insert(0, str(SCRIPTS))
import lexical_layer  # noqa: E402


def cli(*args):
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
    return subprocess.run([sys.executable, str(SCRIPTS / 'lexical_layer.py'), *args], capture_output=True, text=True,
                          encoding='utf-8', env=env, check=True)


class LexicalRestoreTest(unittest.TestCase):
    def test_an_injected_headword_sentence_goes_back_to_the_source(self):
        source = '올해 매출은 크게 늘었다. 이 결과를 여러 관점에서 살펴본다. 비용은 조금 줄었다.\n'
        candidate = '올해 매출은 크게 늘었다. 이 결과를 여러 렌즈로 살펴본다. 비용은 조금 줄었다.\n'
        output, restored, skipped = lexical_layer.restore(source, candidate)
        self.assertEqual(output, source)
        self.assertEqual([item['headwords'] for item in restored], [['렌즈']])
        self.assertEqual(skipped, [])

    def test_a_headword_the_source_already_used_is_not_restored(self):
        source = '이 문제를 렌즈로 본다. 결과를 여러 관점에서 살펴본다.\n'
        candidate = '이 문제를 다르게 본다. 결과를 여러 렌즈로 살펴본다.\n'
        self.assertEqual(lexical_layer.restore(source, candidate)[0], candidate)

    def test_a_reordered_pair_is_never_restored(self):
        # Pristine 2.4.7 paired the swapped sentences and restored one over the other:
        # '상반기에는 … 줄였다. 상반기에는 … 줄였다.' (the second half-year disappeared).
        source = '상반기에는 신규 채용 규모를 줄였다. 하반기에는 신규 채용 규모를 늘렸다.\n'
        for candidate in ('하반기에는 이 렌즈로 신규 채용 규모를 늘렸다. 상반기에는 신규 채용 규모를 줄였다.\n',
                          '하반기에는 신규 채용 규모를 늘렸다. 상반기에는 렌즈를 바꿔 신규 채용 규모를 줄였다.\n'):
            with self.subTest(candidate=candidate):
                output, restored, skipped = lexical_layer.restore(source, candidate)
                self.assertEqual(output, candidate)
                self.assertEqual(restored, [])
                self.assertEqual([item['reason'] for item in skipped], ['순서 변경 의심 — 다른 원문 문장과 더 가깝다'])

    def test_restoring_never_duplicates_a_sentence(self):
        source = '이 결과를 여러 관점에서 살펴본다. 비용은 조금 줄었다.\n'
        candidate = '이 결과를 여러 렌즈로 살펴본다. 이 결과를 여러 관점에서 살펴본다.\n'
        output, restored, skipped = lexical_layer.restore(source, candidate)
        self.assertEqual(output, candidate)
        self.assertEqual(restored, [])
        self.assertEqual([item['reason'] for item in skipped], ['복원하면 같은 문장이 중복된다'])

    def test_the_cli_keeps_crlf_and_reports_counts_as_json(self):
        source = '올해 매출은 크게 늘었다.\r\n이 결과를 여러 관점에서 살펴본다.\r\n'
        candidate = '올해 매출은 크게 늘었다.\r\n이 결과를 여러 렌즈로 살펴본다.\r\n'
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / 'before.txt', Path(folder) / 'after.txt'
            before.write_bytes(source.encode('utf-8'))
            after.write_bytes(candidate.encode('utf-8'))
            result = cli('restore', '--before', str(before), '--after', str(after), '--out', str(after), '--json')
            self.assertEqual(after.read_bytes(), source.encode('utf-8'))
        report = json.loads(result.stderr)
        self.assertEqual((report['restored'], report['skipped']), (1, 0))


class LexicalHintTest(unittest.TestCase):
    def test_hints_name_the_source_headword_but_not_a_quoted_one(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.txt'
            source.write_bytes('이 문제를 세 가지 렌즈로 본다.\r\n'.encode('utf-8'))
            block = cli('hints', '--input', str(source), '--genre', 'essay').stdout.strip()
            self.assertTrue(block.startswith('[어휘 점검]') and block.endswith('[어휘 점검 끝]'))
            self.assertIn('[우선] 렌즈', block)
            source.write_bytes('"세 가지 렌즈로 본다"는 예문이다.\n'.encode('utf-8'))
            self.assertEqual(cli('hints', '--input', str(source), '--genre', 'essay').stdout.strip(), '')

    def test_a_text_without_headwords_has_no_block(self):
        self.assertEqual(lexical_layer.render_hint_block(lexical_layer.find_hits('오늘은 비가 왔다.\n', 'essay')), '')


if __name__ == '__main__':
    unittest.main()
