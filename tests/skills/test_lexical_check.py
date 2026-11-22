"""engine_runtime/lexical_check.py: the `[어휘 점검]` block plus the nouns the direct-text concept guard may let the rewrite replace."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / 'engine_runtime/lexical_check.py'
VENDOR = ROOT / 'vendor/humanize-engine'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(VENDOR / 'scripts'))
from engine_runtime import lexical_check as lexical_module, workflow  # noqa: E402
import lexical_layer  # noqa: E402

lexical_check = lexical_module.lexical_check

# A 'change' (바꿈 우선) noun, another one inside a phrase entry ("성공을 달성"), and a particle-bearing noun.
ESSAY = ('이번 분기 실적을 세 가지 렌즈로 살펴보면 흐름이 달라 보인다. 참석자는 12명이었다. '
         '마침내 성공을 달성했다. 이 결과는 다음 계획에 새로운 결을 더한다.')
# 기둥 and 여정 (twice) count, 역학 (conditional, once) does not, the quoted 렌즈 is a direct quotation,
# and "미묘한 접근" is a phrase entry that names no noun.
MIXED = '세 기둥 위에 계획을 세웠다. 이번 여정은 짧았다. 긴 여정 끝에 돌아왔다. 역학 실험을 했다. "렌즈로 보면"은 인용이다. 미묘한 접근이 필요하다.'


def headwords(block):
    return re.findall(r'^- \[(?:우선|조건부)\] (.+?) — ', block, re.M)


def cli(*args, check=True):
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
    return subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True, encoding='utf-8',
                          env=env, check=check)


class ReplaceableNounsTest(unittest.TestCase):
    def test_a_metaphor_noun_and_a_particle_noun_are_replaceable(self):
        report = lexical_check(ESSAY, VENDOR)
        # "결을" is the whole matched word (noun plus particle); the phrase entry "성공을 달성" names no noun.
        self.assertEqual(report['replaceableNouns'], ['결을', '렌즈'])
        self.assertEqual(headwords(report['block']), ['성공을 달성하다', '결(결을 더하다·N의 결)', '렌즈'])
        self.assertTrue(report['block'].startswith('[어휘 점검]\n') and report['block'].endswith('[어휘 점검 끝]'))

    def test_the_block_is_the_vendor_block_unchanged(self):
        for text in (ESSAY, MIXED):
            with self.subTest(text=text[:12]):
                self.assertEqual(lexical_check(text, VENDOR)['block'],
                                 lexical_layer.render_hint_block(lexical_layer.find_hits(text, 'essay')))

    def test_conditional_nouns_count_only_when_repeated_quotes_and_phrases_never(self):
        report = lexical_check(MIXED, VENDOR)
        self.assertEqual(report['replaceableNouns'], ['기둥', '여정'])
        # 역학 (conditional, used once) and the quoted 렌즈 are not in the block's nouns; 역학 is still a hint.
        self.assertNotIn('역학', report['replaceableNouns'])
        self.assertNotIn('렌즈', report['replaceableNouns'])
        self.assertIn('역학', headwords(report['block']))
        self.assertNotIn('렌즈', headwords(report['block']))
        # The phrase entry is a hint, but the noun inside it (접근) stays protected.
        self.assertIn('미묘한 접근', headwords(report['block']))
        self.assertNotIn('접근', report['replaceableNouns'])

    def test_a_conditional_noun_used_twice_is_replaceable_and_once_is_not(self):
        twice = lexical_check('이번 여정은 짧았다. 긴 여정 끝에 돌아왔다.', VENDOR)
        once = lexical_check('이번 여정은 짧았다.', VENDOR)
        self.assertEqual(twice['replaceableNouns'], ['여정'])
        self.assertEqual(once['replaceableNouns'], [])
        # One use is still in the block: the model may judge it, the guard just keeps protecting the noun.
        self.assertEqual(headwords(once['block']), ['여정'])
        self.assertEqual(lexical_module.CONDITIONAL_MIN_USES, 2)

    def test_the_quoted_occurrence_is_ignored_and_the_unquoted_one_counts(self):
        quoted = lexical_check('"렌즈로 보면"은 인용이다.', VENDOR)
        self.assertEqual(quoted, {'block': '', 'replaceableNouns': []})
        for text in ('"렌즈로 보면"은 인용이다. 이 문제를 렌즈로 본다.', '이 문제를 렌즈로 본다. “렌즈로 보면”은 인용이다.'):
            with self.subTest(text=text):
                self.assertEqual(lexical_check(text, VENDOR)['replaceableNouns'], ['렌즈'])
        # A surface that occurs only inside the quotation never enters the list ("결을" quoted, "결도" plain).
        self.assertEqual(lexical_check('그는 "결을 더하다"라고 썼다. 두 글은 결도 다르다.', VENDOR)['replaceableNouns'], ['결도'])
        # A conditional entry counts only unquoted uses: one quoted and one plain 여정 is a single use.
        self.assertEqual(lexical_check('"긴 여정"이라 썼다. 이번 여정은 짧았다.', VENDOR)['replaceableNouns'], [])

    def test_a_phrase_entry_alone_names_no_noun(self):
        report = lexical_check('미묘한 접근이 필요하다.', VENDOR)
        self.assertEqual(headwords(report['block']), ['미묘한 접근'])
        self.assertEqual(report['replaceableNouns'], [])

    def test_only_the_hints_the_block_shows_exempt_a_noun(self):
        # 15 entries of count 2 and 렌즈 (count 3) fill the block; 기둥 (count 1) is the 17th hit and is not shown.
        entries = [entry for entry in lexical_layer.load_lexicon()['entries']
                   if entry['tier'] == 'change' and '일반' not in entry['skip_genres'] and entry['id'] not in ('L-17', 'X-14')
                   and entry.get('test_detect_pos')]
        self.assertGreaterEqual(len(entries), lexical_layer.MAX_HINTS)
        text = ' '.join(' '.join([entry['test_detect_pos'][0]] * 2) for entry in entries[:lexical_layer.MAX_HINTS])
        text += ' 세 기둥 위에 계획을 세웠다. 이 렌즈로 본다. 저 렌즈로 본다. 그 렌즈로 본다.'
        hits = lexical_layer.find_hits(text, 'essay')
        self.assertGreater(len(hits), lexical_layer.MAX_HINTS)
        report = lexical_check(text, VENDOR)
        self.assertEqual(len(headwords(report['block'])), lexical_layer.MAX_HINTS)
        self.assertIn(f'(그 밖에 {len(hits) - lexical_layer.MAX_HINTS}개 항목은 생략', report['block'])
        self.assertIn('렌즈', headwords(report['block']))
        self.assertNotIn('기둥(세 기둥·핵심 기둥)', headwords(report['block']))
        self.assertIn('렌즈', report['replaceableNouns'])
        self.assertNotIn('기둥', report['replaceableNouns'])

    def test_a_genre_that_skips_an_entry_gives_no_noun(self):
        text = '이 논문은 성장 서사를 다룬다. 이 서사는 낡았다.'
        self.assertEqual(lexical_check(text, VENDOR)['replaceableNouns'], ['서사'])
        for genre in ('paper', 'abstract'):
            with self.subTest(genre=genre):
                self.assertEqual(lexical_check(text, VENDOR, genre), {'block': '', 'replaceableNouns': []})

    def test_text_without_lexicon_words_gives_nothing(self):
        for text in ('', '오늘은 비가 왔다. 참석자는 12명이었다.\n'):
            self.assertEqual(lexical_check(text, VENDOR), {'block': '', 'replaceableNouns': []})

    def test_a_vendor_without_the_layer_raises_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'scripts').mkdir()
            with self.assertRaises(ValueError):
                lexical_check(ESSAY, Path(folder))


class LexicalCheckCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def write(self, text, name='chunk.txt'):
        path = self.folder / name
        path.write_bytes(text.encode('utf-8'))
        return path

    def test_it_prints_the_json_and_exits_zero(self):
        result = cli('--input', self.write(ESSAY), '--vendor-root', VENDOR, '--genre', 'essay')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, '')
        report = json.loads(result.stdout)
        self.assertEqual(set(report), {'block', 'replaceableNouns'})
        self.assertEqual(report['replaceableNouns'], ['결을', '렌즈'])
        self.assertEqual(report, lexical_check(ESSAY, VENDOR))
        # Hangul stays Hangul on the wire: the server and the Gateway read the block as UTF-8 text.
        self.assertIn('[어휘 점검]', result.stdout)

    def test_the_defaults_are_the_repo_vendor_and_the_essay_genre(self):
        result = cli('--input', self.write(MIXED))
        self.assertEqual(json.loads(result.stdout)['replaceableNouns'], ['기둥', '여정'])
        paper = cli('--input', self.write('이 논문은 성장 서사를 다룬다. 이 서사는 낡았다.', 'paper.txt'), '--genre', 'paper')
        self.assertEqual(json.loads(paper.stdout), {'block': '', 'replaceableNouns': []})

    def test_a_text_without_hits_is_still_a_success(self):
        result = cli('--input', self.write('오늘은 비가 왔다.\n'), '--vendor-root', VENDOR)
        self.assertEqual((result.returncode, json.loads(result.stdout)), (0, {'block': '', 'replaceableNouns': []}))

    def test_a_vendor_without_the_layer_exits_one_with_empty_stdout(self):
        vendor = self.folder / 'no-layer'
        (vendor / 'scripts').mkdir(parents=True)
        result = cli('--input', self.write(ESSAY), '--vendor-root', vendor, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertIn('[lexical-check] failed', result.stderr)
        # The failure line never carries source text.
        self.assertNotIn('렌즈', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_a_missing_vendor_folder_or_input_exits_one_with_empty_stdout(self):
        for args in (('--input', self.write(ESSAY), '--vendor-root', self.folder / 'absent'),
                     ('--input', self.folder / 'absent.txt', '--vendor-root', VENDOR)):
            with self.subTest(args=[str(arg) for arg in args]):
                result = cli(*args, check=False)
                self.assertEqual((result.returncode, result.stdout), (1, ''))

    def test_crlf_input_is_read_without_errors_and_matches_the_lf_result(self):
        crlf = ESSAY.replace('. ', '.\r\n') + '\r\n'
        self.assertIn('\r\n', crlf)
        result = cli('--input', self.write(crlf), '--vendor-root', VENDOR)
        report = json.loads(result.stdout)
        self.assertEqual(report['replaceableNouns'], ['결을', '렌즈'])
        self.assertEqual(report, lexical_check(ESSAY, VENDOR))
        # A direct quotation never spans a CRLF line break.
        quoted = '"렌즈로 보면"은 인용이다.\r\n이 문제를 렌즈로 본다.\r\n'
        self.assertEqual(json.loads(cli('--input', self.write(quoted, 'quoted.txt'), '--vendor-root', VENDOR).stdout)['replaceableNouns'], ['렌즈'])


class WorkflowLexicalReportTest(unittest.TestCase):
    def test_the_report_carries_the_block_and_the_nouns_the_gateway_passes_on(self):
        report = workflow.lexical_report(ESSAY)
        self.assertEqual(report, lexical_check(ESSAY, workflow.DEFAULT_VENDOR))
        self.assertEqual(workflow.lexical_hints(ESSAY), report['block'])
        self.assertEqual(workflow.lexical_nouns(ESSAY), ['결을', '렌즈'])

    def test_an_empty_block_returns_no_nouns_even_when_the_check_names_some(self):
        # Defense in depth: as on the server, the exemption exists only alongside a block the rewrite was given.
        with mock.patch.object(workflow, 'lexical_check', return_value={'block': '', 'replaceableNouns': ['렌즈']}):
            self.assertEqual(workflow.lexical_report(ESSAY), {'block': '', 'replaceableNouns': []})
            self.assertEqual((workflow.lexical_hints(ESSAY), workflow.lexical_nouns(ESSAY)), ('', []))

    def test_a_source_without_lexicon_words_returns_nothing(self):
        report = workflow.lexical_report('오늘은 비가 왔다. 참석자는 12명이었다.\n')
        self.assertEqual(report, {'block': '', 'replaceableNouns': []})
        self.assertEqual(workflow.lexical_nouns(''), [])

    def test_a_failing_layer_returns_no_block_and_no_nouns(self):
        with mock.patch.object(workflow, 'lexical_check', side_effect=RuntimeError('lexicon unreadable')):
            self.assertEqual(workflow.lexical_report(ESSAY), {'block': '', 'replaceableNouns': []})
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'scripts').mkdir()
            self.assertEqual(workflow.lexical_report(ESSAY, Path(folder)), {'block': '', 'replaceableNouns': []})
            self.assertEqual(workflow.lexical_nouns(ESSAY, Path(folder)), [])

    def test_the_report_is_a_fresh_value_the_caller_may_change(self):
        first = workflow.lexical_report(ESSAY)
        first['replaceableNouns'].append('변경')
        self.assertEqual(workflow.lexical_report(ESSAY)['replaceableNouns'], ['결을', '렌즈'])


if __name__ == '__main__':
    unittest.main()
