"""Super Sejong particle (josa) agreement: only mismatches a rewrite introduces are acted on."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine_runtime import super_sejong_josa as josa
from engine_runtime.workflow import restore, verify


class SyllableArithmetic(unittest.TestCase):
    def test_final_consonant_classes(self):
        self.assertEqual(josa.syl_class('나'), 'V')
        self.assertEqual(josa.syl_class('책'), 'C')
        self.assertEqual(josa.syl_class('물'), 'L')


class Gate(unittest.TestCase):
    def test_introduced_mismatches_after_non_hangul_stems(self):
        cases = [('URL을 확인했다.', 'URL를 확인했다.', 'URL을 확인했다.'),
                 ('목표는 10%로 정했다.', '목표는 10%으로 정했다.', '목표는 10%로 정했다.'),
                 ('AI가 답했다.', 'AI이 답했다.', 'AI가 답했다.')]
        for source, output, repaired in cases:
            with self.subTest(output=output):
                findings = josa.gate(source, output, None, 'likely')
                self.assertTrue(findings)
                self.assertEqual(josa.repair(output, findings), repaired)

    def test_errors_already_in_the_source_are_left_alone(self):
        self.assertEqual(josa.gate('참석를 요청했다.', '참석를 다시 요청했다.', None, 'likely'), [])

    def test_correct_text_has_no_findings(self):
        text = 'AI가 데이터를 읽고 10%로 줄였다. 회의를 열었다. 사과와 배를 샀다.'
        self.assertEqual(josa.gate(text, text, None, 'likely'), [])


class Pipeline(unittest.TestCase):
    def files(self, folder, source, output):
        before, after = Path(folder) / 'before.txt', Path(folder) / 'after.txt'
        before.write_text(source, encoding='utf-8')
        after.write_text(output, encoding='utf-8')
        return before, after

    def test_restore_repairs_and_verify_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            before, after = self.files(folder, '회의를 열고 URL을 공유했다.\n', '회의를 열고 URL를 공유했다.\n')
            report = restore(before, after)
            self.assertEqual(report['repairedParticles'], 1)
            self.assertEqual(after.read_text(encoding='utf-8'), '회의를 열고 URL을 공유했다.\n')
            self.assertNotIn('josa_mismatch', verify(before, after)['hardFailures'])

    def test_verify_blocks_a_remaining_certain_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            before, after = self.files(folder, '목표는 10%로 정했다.\n', '목표는 10%으로 정했다.\n')
            self.assertIn('josa_mismatch', verify(before, after)['hardFailures'])

    def test_cli_used_by_the_server_reports_repairs(self):
        with tempfile.TemporaryDirectory() as folder:
            before, after = self.files(folder, 'URL을 확인했다.\n', 'URL를 확인했다.\n')
            env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
            result = subprocess.run([sys.executable, str(ROOT / 'engine_runtime' / 'super_sejong_josa.py'),
                                     '--before', str(before), '--after', str(after), '--out', str(after), '--json'],
                                    capture_output=True, text=True, env=env, check=True)
            self.assertEqual(json.loads(result.stderr), {'repaired': 1})
            self.assertEqual(after.read_text(encoding='utf-8'), 'URL을 확인했다.\n')
            off = subprocess.run([sys.executable, str(ROOT / 'engine_runtime' / 'super_sejong_josa.py'),
                                  '--before', str(before), '--after', str(after), '--out', str(after), '--json'],
                                 capture_output=True, text=True, env={**env, 'SUPER_SEJONG_MODE': 'off'}, check=True)
            self.assertEqual(json.loads(off.stderr), {'repaired': 0})


if __name__ == '__main__':
    unittest.main()
