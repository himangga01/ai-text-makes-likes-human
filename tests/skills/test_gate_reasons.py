import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine_runtime import workflow

def p1_report():
    return {'genre':'essay','change_rate':{'rate':0.17,'scope':'전문','verdict':'OK'},
            's1_targets':[{'metric':'comma_segment_length','z_before':6.21,'z_after':6.17,'verdict':'미달'}],
            'antithesis':{'before':0,'after':0,'verdict':'스킵 (원문 대구 < 5)'},'golden':[],
            'sentence_touch':{'rate':0.75,'touched':9,'total':12},'numbers_dropped':[],
            'modality':{'lost_pairs':[],'uncertain_pairs':[],
                        'counts':{'deontic':{'before':0,'after':0},'hedge':{'before':0,'after':0}},'verdict':'OK'},
            'gate':{'exit_code':1,'verdict':'WARN — 경고. 사용자 고지 + finalize 승급'}}

class GateReasonTest(unittest.TestCase):
    def test_rejects_every_missing_unknown_or_malformed_nested_axis(self):
        report = p1_report()
        self.assertEqual(workflow.warning_reasons(report, 1)['codes'], ['P1_STYLE_TARGET'])
        paths = [('change_rate',), ('antithesis',), ('sentence_touch',), ('gate',),
                 ('modality',), ('modality','counts'), ('modality','counts','deontic'),
                 ('modality','counts','hedge')]
        for path in paths:
            original = report
            for key in path:
                original = original[key]
            for missing in [None, *original]:
                probe = copy.deepcopy(report)
                axis = probe
                for key in path:
                    axis = axis[key]
                if missing is None:
                    axis['future_warning'] = {'kind':'fidelity','failed':True}
                else:
                    del axis[missing]
                with self.subTest(path=path, missing=missing):
                    self.assertEqual(workflow.warning_reasons(probe, 1)['codes'], ['UNKNOWN'])
        mutations = [lambda p:p.update(sentence_touch=None),
                     lambda p:p['sentence_touch'].update(rate=float('nan')),
                     lambda p:p['sentence_touch'].update(touched=True),
                     lambda p:p['sentence_touch'].update(total=-1),
                     lambda p:p['gate'].update(verdict=None),
                     lambda p:p['gate'].update(exit_code=True),
                     lambda p:p['change_rate'].update(scope=[]),
                     lambda p:p['modality']['counts']['hedge'].update(before='0')]
        for index, mutate in enumerate(mutations):
            probe = copy.deepcopy(report)
            mutate(probe)
            with self.subTest(malformed=index):
                self.assertEqual(workflow.warning_reasons(probe, 1)['codes'], ['UNKNOWN'])

    def test_real_30_50_boundaries_keep_existing_gate_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            before, after = Path(directory)/'before.txt', Path(directory)/'after.txt'
            # Hangul placeholders: changed Latin words are a separate name_changed hard failure.
            before.write_text('가' * 100, encoding='utf-8')
            for changed in (29, 30, 49, 50):
                after.write_text('가' * (100-changed) + '나' * changed, encoding='utf-8')
                first = workflow.verify(before, after)
                second = workflow.verify(before, after, attempt=2)
                with self.subTest(changed=changed):
                    self.assertEqual('P0_CHANGE_RATE' in first['warningReasons']['codes'], changed >= 30)
                    if changed >= 50:
                        self.assertEqual(first['gate']['exit_code'], 2)
                        self.assertEqual(second['policy'], 'rollback')
                    else:
                        self.assertLess(first['gate']['exit_code'], 2)
                    if changed >= 30:
                        self.assertEqual(first['policy'], 'retry')

    def test_real_recorded_p1_warning_has_bounded_reasons(self):
        fixture = json.loads((ROOT / 'tests/fixtures/direct-live-quality.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            before, after = Path(directory)/'before.txt', Path(directory)/'after.txt'
            before.write_text(fixture['source'], encoding='utf-8')
            after.write_text(fixture['candidate'], encoding='utf-8')
            first = workflow.verify(before, after)
            second = workflow.verify(before, after, attempt=2)
        self.assertEqual(first['gate']['exit_code'], 1)
        self.assertEqual(first['policy'], 'retry')
        self.assertEqual(second['policy'], 'accept-with-warning')
        self.assertEqual(first.get('warningReasons'), {'version': 1, 'codes': ['P1_STYLE_TARGET']})
        self.assertEqual(first['hardFailures'], [])

    def test_classifies_mixed_missing_and_unknown_reports_closed(self):
        report = p1_report()
        self.assertEqual(workflow.warning_reasons(report,1)['codes'], ['P1_STYLE_TARGET'])
        mutations = [
            lambda p:p.pop('golden'), lambda p:p.update(future_warning=True),
            lambda p:p['change_rate'].update(rate=0.3),
            lambda p:p['antithesis'].update(verdict='unknown'),
            lambda p:p['modality'].update(verdict='unknown'),
            lambda p:p['s1_targets'][0].update(extra='unknown'),
            lambda p:p['golden'].append({'code':'new','message':'advisory'}),
            lambda p:p['modality']['uncertain_pairs'].append({}),
            lambda p:p['modality']['lost_pairs'].append({}),
            lambda p:p['antithesis'].update(before=5,after=0),
            lambda p:p['numbers_dropped'].append('12'),
            lambda p:p['s1_targets'][0].update(z_after=None),
            lambda p:p['s1_targets'][0].update(metric='unknown'),
            lambda p:p['s1_targets'][0].update(verdict='unknown'),
        ]
        for mutation in mutations:
            probe=copy.deepcopy(report); mutation(probe)
            with self.subTest(probe=probe):
                self.assertNotEqual(workflow.warning_reasons(probe,1)['codes'],['P1_STYLE_TARGET'])
        self.assertNotEqual(workflow.warning_reasons(report,1,'metrics unavailable')['codes'],['P1_STYLE_TARGET'])

if __name__ == '__main__': unittest.main()
