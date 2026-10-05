"""Office path of Super Sejong Engine v2 (WP-12): per-block plan, reject-only verification, narrowed retry.

Every test pins its own SUPER_SEJONG_* environment, so the suite means the same thing whether it is started
with SUPER_SEJONG_ENGINE unset (legacy) or set to v2.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine_runtime'))
from documents.package import Package, DocumentError  # noqa: E402
from documents.model import (extract, apply_edits, resolve_edits, BlockRejected, sejong_block_plan, sejong_flags,  # noqa: E402
                             sejong_nominations)
from documents.workflow import prepare, dispatch  # noqa: E402

FIXTURE = ROOT / 'tests/fixtures/documents/mixed.docx'
VENDOR = ROOT / 'vendor/humanize-engine'
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
CLEAN = '팀은 풍부한 경험을 가지고 있다.'
MODAL_MESSAGE = '부정·당위·추측 표현 변화가 감지되었습니다.'
SHORT_NEGATION_MESSAGE = '짧은 부정 표현 변화가 감지되었습니다.'
DRIFT_MESSAGE = '문장이 사라지거나 부정·당위의 문장별 의미가 바뀌었습니다.'


class Env:
    """The SUPER_SEJONG_* variables of a test: every one is cleared, then `values` are set (None = unset)."""
    def __init__(self, engine, **values):
        self.values = {'SUPER_SEJONG_ENGINE': engine, **values}

    def __enter__(self):
        self.saved = dict(os.environ)
        for name in [n for n in os.environ if n.startswith('SUPER_SEJONG_')]:
            del os.environ[name]
        for name, value in self.values.items():
            if value is not None:
                os.environ[name] = value
        return self

    def __exit__(self, *exc):
        os.environ.clear()
        os.environ.update(self.saved)


def V2(**values):
    return Env('v2', **values)


def LEGACY(**values):
    return Env(None, **values)


class OfficeCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.jobs = self.work / 'jobs'

    def tearDown(self):
        self.temp.cleanup()

    def docx(self, paragraphs, name='case.docx'):
        parts = dict(Package(FIXTURE, 'docx').parts)
        body = ''.join(f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>' for text in paragraphs)
        parts['word/document.xml'] = f'<w:document {W}><w:body>{body}<w:sectPr/></w:body></w:document>'.encode()
        file = self.work / name
        with ZipFile(file, 'w', ZIP_DEFLATED) as archive:
            for part, data in parts.items():
                archive.writestr(part, data)
        return file

    def blocks(self, paragraphs):
        return extract(Package(self.docx(paragraphs), 'docx'))['blocks']

    def batch(self, state):
        return json.loads(Path(state['inputPath']).read_text(encoding='utf-8'))

    def answer(self, state, edits_by_block=None, reviewed=None):
        """Submit an Office response; returns the next state. `edits_by_block` maps block id to
        [{before, after}]."""
        batch = self.batch(state)
        hashes = {b['id']: b['sourceHash'] for b in batch['blocks']}
        edits_by_block = edits_by_block or {}
        value = {'schemaVersion': 2, 'batchId': batch['batchId'], 'sourceHash': batch['sourceHash'],
                 'reviewedIds': reviewed if reviewed is not None else [b['id'] for b in batch['blocks']],
                 'warnings': [],
                 'blocks': [{'id': i, 'sourceHash': hashes[i], 'edits': e} for i, e in edits_by_block.items()]}
        Path(state['responsePath']).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return self.dispatch('accept', state, chunk=state['chunk'], attempt=state['attempt'],
                             source_hash=state['sourceHash'], response=state['responsePath'])

    def dispatch(self, command, state, **kwargs):
        return dispatch(SimpleNamespace(command=command, job=state['job'], **kwargs), self.jobs, VENDOR)

    def finalize(self, state, name='out.docx'):
        out = self.work / name
        self.dispatch('finalize', state, output=str(out))
        return extract(Package(out, 'docx'))['blocks']


class PerBlockPlan(OfficeCase):
    def test_v2_batch_carries_the_plan_of_each_block_and_no_rulebook(self):
        # b2 has one sentence the block's own protection covers (a number) and one free sentence
        paragraphs = ['왜냐하면 일정이 변경됬습니다.', '참가비는 3만 원이 됬습니다. 일정을 변경됬어요~', CLEAN]
        with V2():
            state = prepare(self.docx(paragraphs), self.jobs, VENDOR)
            batch = self.batch(state)
        self.assertEqual(state['status'], 'rewrite')
        self.assertNotIn('rulesPath', state)
        self.assertEqual(batch['sejong']['version'], 1)
        self.assertEqual(batch['sejong']['genre'], 'document')
        self.assertEqual(batch['sejong']['engine']['id'], 'super-sejong')
        self.assertTrue(batch['sejong']['profile']['line'])
        self.assertTrue(batch['sejong']['review']['enabled'])
        self.assertGreaterEqual(batch['sejong']['review']['maxSentences'], 3)
        requests = {b['id']: b['plan']['requests'] for b in batch['blocks']}
        # a finding with a reason: the request, the rule that asks for it and the one-line guides
        first = requests['b1']
        self.assertEqual([r['sentence'] for r in first], ['S1'])
        self.assertEqual(first[0]['tier'], 'FIX')
        self.assertEqual(first[0]['rules'], ['SSJ-A01', 'SSJ-N04'])
        self.assertEqual(len(first[0]['guides']), 2)
        self.assertEqual(first[0]['fix'], [{'before': '됬', 'after': '됐'}])
        self.assertEqual(first[0]['text'], paragraphs[0])
        self.assertEqual((first[0]['voice']['level'], first[0]['voice']['mood']), ('HAPSYO', 'DECL'))
        self.assertFalse(first[0]['allowSplit'])
        # a sentence that the block's own protection covers (a number) can never be edited: no request for S1,
        # while a deterministic misspelling fix alone on S2 is still offered, as a FIX item with the expected form
        self.assertEqual([r['sentence'] for r in requests['b2']], ['S2'])
        self.assertEqual(requests['b2'][0]['rules'], ['SSJ-N04'])
        self.assertEqual(requests['b2'][0]['fix'], [{'before': '됬', 'after': '됐'}])
        self.assertEqual(requests['b2'][0]['voice']['level'], 'HAEYO')
        self.assertEqual(requests['b3'], [])

    def test_the_plan_never_leaves_the_batch_block_shape_of_the_response_protocol(self):
        with V2():
            state = prepare(self.docx(['왜냐하면 일정이 변경됬습니다.', CLEAN]), self.jobs, VENDOR)
            batch = self.batch(state)
        self.assertEqual(set(batch), {'schemaVersion', 'batchId', 'sourceHash', 'blocks', 'sejong'})
        for block in batch['blocks']:
            self.assertEqual(set(block), {'id', 'location', 'text', 'sourceHash', 'protected', 'maxChars', 'spans', 'plan'})
            self.assertTrue(all(set(span) == {'start', 'end'} for span in block['spans']))
        self.assertEqual(self.batch(state)['batchId'], str(state['chunk']))

    def test_legacy_batch_is_unchanged_and_still_names_the_rulebook(self):
        with LEGACY():
            state = prepare(self.docx(['왜냐하면 일정이 변경됬습니다.', CLEAN]), self.jobs, VENDOR)
            batch = self.batch(state)
        self.assertTrue(state['rulesPath'].endswith('skills/humanize-korean/references/quick-rules.md'))
        self.assertEqual(set(batch), {'schemaVersion', 'batchId', 'sourceHash', 'blocks'})
        for block in batch['blocks']:
            self.assertEqual(set(block), {'id', 'location', 'text', 'sourceHash', 'protected', 'maxChars', 'spans'})
        state_file = json.loads((self.jobs / state['job'] / 'job.json').read_text(encoding='utf-8'))
        for key in ('engine', 'active', 'carry', 'retry'):
            self.assertNotIn(key, state_file)

    def test_deterministic_fixes_are_offered_only_in_the_all_scope(self):
        for scope, offered in (('all', True), ('edited-only', False), ('off', False)):
            with self.subTest(scope=scope), V2(SUPER_SEJONG_DETERMINISTIC_FIX=scope):
                block = self.blocks(['일정을 변경됬어요~'])[0]
                requests = sejong_block_plan(block, sejong_flags())['requests']
                self.assertEqual(bool(requests), offered)

    def test_open_review_off_and_a_clean_block_ask_nothing(self):
        block = self.blocks([CLEAN])[0]
        with V2():
            plan = sejong_block_plan(block, sejong_flags())
        self.assertEqual((plan['requests'], plan['needsModel']), ([], True))   # medium: the open review may nominate
        self.assertEqual(plan['nominable'], 1)
        with V2(SUPER_SEJONG_OPEN_REVIEW='off'):
            plan = sejong_block_plan(block, sejong_flags())
        self.assertEqual(plan, {'requests': [], 'nominable': 0, 'needsModel': False})
        with V2(SUPER_SEJONG_MODE='off'):   # off also drops SUGGEST requests and the open review
            self.assertFalse(sejong_block_plan(block, sejong_flags())['needsModel'])

    def test_an_empty_plan_makes_no_model_call(self):
        with V2(SUPER_SEJONG_OPEN_REVIEW='off'):
            state = prepare(self.docx([CLEAN, '이 문서는 강한 경쟁력을 가지고 있다.']), self.jobs, VENDOR)
            self.assertEqual(state['status'], 'ready-to-finalize')
            self.assertNotIn('inputPath', state)
            out = self.finalize(state)
        self.assertEqual([b['text'] for b in out], [CLEAN, '이 문서는 강한 경쟁력을 가지고 있다.'])

    def test_batches_nobody_needs_are_skipped_and_only_asked_blocks_are_sent(self):
        paragraphs = [CLEAN] * 196 + ['왜냐하면 일정이 변경됬습니다.', CLEAN, CLEAN, CLEAN]
        with V2(SUPER_SEJONG_OPEN_REVIEW='off'):
            state = prepare(self.docx(paragraphs), self.jobs, VENDOR)
            self.assertEqual(state['totalChunks'], 3)
            self.assertEqual((state['status'], state['chunk']), ('rewrite', 3))   # batches 1 and 2 accepted unchanged
            batch = self.batch(state)
            self.assertEqual([b['id'] for b in batch['blocks']], ['b197'])
            self.assertFalse(batch['sejong']['review']['enabled'])
            state = self.answer(state, {'b197': [{'before': '왜냐하면 ', 'after': ''}]}, reviewed=['b197'])
            self.assertEqual(state['status'], 'ready-to-finalize')
        saved = json.loads((self.jobs / state['job'] / 'job.json').read_text(encoding='utf-8'))
        self.assertEqual((saved['current'], saved['attempt']), (3, 1))
        self.assertNotIn('active', saved)

    def test_review_ids_must_be_exactly_the_asked_blocks(self):
        with V2(SUPER_SEJONG_OPEN_REVIEW='off'):
            state = prepare(self.docx([CLEAN, '왜냐하면 일정이 변경됬습니다.']), self.jobs, VENDOR)
            self.assertEqual([b['id'] for b in self.batch(state)['blocks']], ['b2'])
            with self.assertRaises(DocumentError):
                self.answer(state, reviewed=['b1', 'b2'])
            self.assertEqual(self.answer(state, reviewed=['b2'])['status'], 'ready-to-finalize')

    def test_real_fixtures_get_a_plan_in_both_formats(self):
        for fmt in ('docx', 'pptx'):
            with self.subTest(fmt=fmt), V2():
                state = prepare(ROOT / f'tests/fixtures/documents/mixed.{fmt}', self.jobs / fmt, VENDOR)
                batch = self.batch(state)
                self.assertTrue(batch['blocks'])
                self.assertTrue(all('requests' in b['plan'] for b in batch['blocks']))
                self.assertNotIn('rulesPath', state)


class VerifyBlockRejects(OfficeCase):
    def edit(self, text, before, after):
        block = self.blocks([text])[0]
        return apply_edits(block, resolve_edits(block, [{'before': before, 'after': after}]))

    def assertRejected(self, text, before, after, code, family):
        with V2(), self.assertRaises(BlockRejected) as caught:
            self.edit(text, before, after)
        codes = [v['code'] for v in caught.exception.violations]
        self.assertIn(code, codes)
        self.assertIn(family, [v.get('family') for v in caught.exception.violations])
        self.assertEqual(len(codes), len(set(codes)), 'each code is reported once')
        self.assertIn(f'({", ".join(dict.fromkeys(codes))})', str(caught.exception))

    def test_voice_violations_are_rejected(self):
        self.assertRejected('신청서는 오늘 제출합니다.', '제출합니다', '제출해요', 'voice_level', 'voice')
        self.assertRejected('사장님이 오십니다.', '오십니다', '옵니다', 'voice_hon_si_dropped', 'voice')
        self.assertRejected('먼저 일정을 확인합니다. 그 뒤에 연락합니다.', '그 뒤에 연락합니다', '그 뒤에 연락하나요', 'voice_mood', 'voice')

    def test_cta_violations_are_rejected(self):
        self.assertRejected('궁금한 점이 있으시면 문의해 주세요.', '문의해 주세요', '문의가 가능합니다', 'cta_dropped', 'cta')

    def test_meaning_violations_are_rejected(self):
        self.assertRejected('직원은 교통비를 받지 않는다.', '받지 않는다', '받는다', 'polarity_changed', 'meaning')
        self.assertRejected('서울 사업은 시행이 가능하다.', '가능하다', '어렵다', 'modality_changed', 'meaning')
        self.assertRejected('위원회는 신청서를 승인했다.', '승인했다', '거절했다', 'lexical_polarity_changed', 'meaning')
        self.assertRejected('직원은 관리자를 돕는다.', '직원은 관리자를', '직원을 관리자는', 'participant_role_changed', 'meaning')

    def test_flow_violations_are_rejected(self):
        self.assertRejected('회의는 길었지만 결론은 분명하다.', '길었지만', '길었고', 'flow_contrast_changed', 'flow')

    def test_josa_violations_are_rejected(self):
        # the engine judges only stems whose reading is certain (acronyms, units): GPU = 지피유 takes 를, not 을
        with V2(), self.assertRaises(BlockRejected) as caught:
            self.edit('이 기능은 서버를 확인한다.', '서버를', 'GPU을')
        self.assertIn('josa_mismatch', [v['code'] for v in caught.exception.violations])

    def test_a_rejection_is_never_repaired(self):
        # a voice-neutral edit with one voice slip: the whole edit is refused, nothing of it is applied
        text = '신청서는 오늘 제출합니다. 담당자가 확인합니다.'
        block = self.blocks([text])[0]
        edits = resolve_edits(block, [{'before': '제출합니다', 'after': '제출해요'}, {'before': '확인합니다', 'after': '확인해요'}])
        with V2(), self.assertRaises(BlockRejected):
            apply_edits(block, edits)
        self.assertEqual(block['text'], text)

    def test_neutral_edits_pass(self):
        with V2():
            self.assertEqual(self.edit('민수는 책을 읽었다.', '민수는', '민수가'), '민수가 책을 읽었다.')
            self.assertEqual(self.edit(CLEAN, '가지고 있다', '갖고 있다'), '팀은 풍부한 경험을 갖고 있다.')
            self.assertEqual(self.edit('일정이 변경됬습니다.', '됬', '됐'), '일정이 변경됐습니다.')

    def test_a_crash_in_the_checks_fails_closed(self):
        from unittest.mock import patch
        block = self.blocks([CLEAN])[0]
        edits = resolve_edits(block, [{'before': '가지고 있다', 'after': '갖고 있다'}])
        with V2(), patch('sejong.verify.verify_block', side_effect=RuntimeError('boom')), self.assertRaises(DocumentError):
            apply_edits(block, edits)

    def test_every_rejection_is_a_document_error_with_a_korean_message(self):
        with V2(), self.assertRaises(DocumentError) as caught:
            self.edit('직원은 교통비를 받지 않는다.', '받지 않는다', '받는다')
        self.assertIn('의미가 바뀌었습니다', str(caught.exception))


class LegacyAndShadowKeepTheOrderedChecks(OfficeCase):
    SOURCE = '신청서는 오늘 제출해야 한다.'

    def reject(self, **env):
        block = self.blocks([self.SOURCE])[0]
        with self.assertRaises(DocumentError) as caught:
            apply_edits(block, resolve_edits(block, [{'before': '제출해야 한다', 'after': '제출할 수 있다'}]))
        return caught.exception

    def test_ordered_modal_check_runs_outside_enforce_in_both_engines(self):
        for engine in (LEGACY, V2):
            for mode in ('shadow', 'off'):
                with self.subTest(engine=engine.__name__, mode=mode), engine(SUPER_SEJONG_MODE=mode):
                    error = self.reject()
                    self.assertEqual(str(error), MODAL_MESSAGE)
                    self.assertNotIsInstance(error, BlockRejected)

    def test_enforce_replaces_the_ordered_lists(self):
        with LEGACY(SUPER_SEJONG_MODE='enforce'):
            error = self.reject()
        self.assertEqual(str(error), DRIFT_MESSAGE)
        self.assertNotIsInstance(error, BlockRejected)
        with V2(SUPER_SEJONG_MODE='enforce'):
            error = self.reject()
        self.assertIsInstance(error, BlockRejected)
        self.assertIn('modality_changed', [v['code'] for v in error.violations])

    def test_short_negation_check_runs_outside_enforce(self):
        block = self.blocks(['회사는 직원에게 교통비를 안 지급한다.'])[0]
        edits = resolve_edits(block, [{'before': '안 지급한다', 'after': '지급한다'}])
        for engine in (LEGACY, V2):
            for mode in ('shadow', 'off'):
                with self.subTest(engine=engine.__name__, mode=mode), engine(SUPER_SEJONG_MODE=mode):
                    with self.assertRaises(DocumentError) as caught:
                        apply_edits(block, edits)
                    self.assertEqual(str(caught.exception), SHORT_NEGATION_MESSAGE)

    def test_a_legacy_job_never_loads_the_v2_package(self):
        # a whole legacy Office job (prepare, answer, finalize) in a fresh interpreter, then the module table
        script = (
            "import sys, json\n"
            f"sys.path.insert(0, {str(ROOT / 'engine_runtime')!r})\n"
            "from pathlib import Path\nfrom types import SimpleNamespace\n"
            "from documents.workflow import prepare, dispatch\n"
            f"jobs, vendor = Path({str(self.jobs)!r}), Path({str(VENDOR)!r})\n"
            f"state = prepare(Path({str(self.docx([CLEAN]))!r}), jobs, vendor)\n"
            "batch = json.loads(Path(state['inputPath']).read_text(encoding='utf-8')); b = batch['blocks'][0]\n"
            "Path(state['responsePath']).write_text(json.dumps({'schemaVersion': 2, 'batchId': batch['batchId'], 'sourceHash': batch['sourceHash'],"
            " 'reviewedIds': [b['id']], 'warnings': [], 'blocks': [{'id': b['id'], 'sourceHash': b['sourceHash'],"
            " 'edits': [{'before': '가지고 있다', 'after': '갖고 있다'}]}]}, ensure_ascii=False), encoding='utf-8')\n"
            "state = dispatch(SimpleNamespace(command='accept', job=state['job'], chunk=1, attempt=1, source_hash=state['sourceHash'],"
            " response=state['responsePath']), jobs, vendor)\n"
            "assert state['decision'] == 'accept', state\n"
            "print(json.dumps(sorted(m for m in sys.modules if m == 'sejong' or m.startswith('sejong.'))))\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith('SUPER_SEJONG_')}
        env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
        done = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout.strip().splitlines()[-1]), [])

class RequestedSentencesOnly(OfficeCase):
    """DESIGN 3.9: a sentence changes only through a request; the open review adds at most its cap."""
    TWO = '왜냐하면 일정이 변경됬습니다. 팀은 풍부한 경험을 가지고 있다.'   # S1 has requests, S2 has none
    REQUESTED = {'before': '됬', 'after': '됐'}
    OTHER = {'before': '가지고 있다', 'after': '갖고 있다'}

    def test_without_an_open_review_an_edit_outside_the_requests_is_dropped_without_a_retry(self):
        with V2(SUPER_SEJONG_OPEN_REVIEW='off'):
            state = prepare(self.docx([self.TWO]), self.jobs, VENDOR)
            self.assertFalse(self.batch(state)['sejong']['review']['enabled'])
            state = self.answer(state, {'b1': [self.REQUESTED, self.OTHER]})
            self.assertEqual((state['decision'], state['status']), ('accept', 'ready-to-finalize'))
            self.assertTrue(any('문단 1' in w and '요청하지 않은 문장을 수정했습니다' in w for w in state['warnings']))
            # only the edit outside the requests is dropped; the requested fix in the same block is kept
            # (code review 2026-10-05: the whole block used to be dropped)
            self.assertEqual([b['text'] for b in self.finalize(state)], [self.TWO.replace('됬', '됐')])

    def test_a_job_keeps_the_flags_it_started_with(self):
        # code review 2026-10-05: accept under one SUPER_SEJONG_MODE and finalize under another stranded the job
        with V2(SUPER_SEJONG_MODE='off'):
            state = prepare(self.docx(['이 문서는 이해되어졌습니다.']), self.jobs, VENDOR)
        with V2(SUPER_SEJONG_MODE='off'):
            state = self.answer(state, {'b1': [{'before': '이해되어졌습니다', 'after': '이해됐어요'}]})
        with V2():
            out = self.finalize(state)
        self.assertEqual([b['text'] for b in out], ['이 문서는 이해됐어요.'])

    def test_an_edit_inside_the_requested_sentence_is_taken(self):
        with V2(SUPER_SEJONG_OPEN_REVIEW='off'):
            state = self.answer(prepare(self.docx([self.TWO]), self.jobs, VENDOR), {'b1': [self.REQUESTED]})
            self.assertEqual(state['decision'], 'accept')
            self.assertEqual([b['text'] for b in self.finalize(state)], [self.TWO.replace('됬', '됐')])

    def test_an_anchor_that_reaches_into_the_next_sentence_does_not_count_as_touching_it(self):
        edit = {'before': '변경됬습니다. 팀은', 'after': '변경됐습니다. 팀은'}
        with V2(SUPER_SEJONG_OPEN_REVIEW='off'):
            state = self.answer(prepare(self.docx([self.TWO]), self.jobs, VENDOR), {'b1': [edit]})
            self.assertEqual(state['decision'], 'accept')
            self.assertFalse(any('원문을 유지했습니다' in w for w in state['warnings']))

    def test_the_open_review_has_a_cap_and_the_excess_is_dropped_in_reply_order(self):
        with V2():
            state = prepare(self.docx([CLEAN] * 4), self.jobs, VENDOR)
            self.assertEqual(self.batch(state)['sejong']['review'], {'enabled': True, 'maxSentences': 3})
            state = self.answer(state, {f'b{i}': [self.OTHER] for i in range(1, 5)})
            self.assertEqual((state['decision'], state['status']), ('accept', 'ready-to-finalize'))
            self.assertTrue(any('문단 4' in w and '열린 검토 한도' in w for w in state['warnings']))
            self.assertFalse(any('문단 3' in w and '원문을 유지했습니다' in w for w in state['warnings']))
            texts = [b['text'] for b in self.finalize(state)]
        self.assertEqual(texts, ['팀은 풍부한 경험을 갖고 있다.'] * 3 + [CLEAN])

    def test_many_dropped_blocks_make_one_notice(self):
        with V2():
            state = prepare(self.docx([CLEAN] * 8), self.jobs, VENDOR)   # cap 3
            state = self.answer(state, {f'b{i}': [self.OTHER] for i in range(1, 9)})
        notices = [w for w in state['warnings'] if '열린 검토 한도' in w]
        self.assertEqual(len(notices), 1)
        self.assertIn('문단 4 등 5개 블록', notices[0])

    def test_the_cap_follows_the_nominable_sentences_of_the_batch(self):
        with V2():
            state = prepare(self.docx([CLEAN] * 40), self.jobs, VENDOR)
            self.assertEqual(self.batch(state)['sejong']['review']['maxSentences'], 4)   # max(3, ceil(0.1 * 40))

    def test_nominations_use_the_changed_range_not_the_anchor(self):
        block = self.blocks(['일정이 바뀌었습니다. 참가는 가능합니다.'])[0]

        def nominated(before, after, asked=()):
            edit = resolve_edits(block, [{'before': before, 'after': after}])
            return sejong_nominations(block, edit, asked)
        self.assertEqual(nominated('일정이', '새 일정이'), ['S1'])                              # insertion
        self.assertEqual(nominated('바뀌었습니다. 참가는', '바뀌었습니다. 참가는'), [])        # no change at all
        self.assertEqual(nominated('바뀌었습니다. 참가는', '바뀝니다. 참가는'), ['S1'])         # anchor reaches into S2
        self.assertEqual(nominated('가능합니다', '불가능합니다'), ['S2'])
        self.assertEqual(nominated('바뀌었습니다. 참가는', '바뀝니다. 참가는', asked=['S1']), [])    # S1 was requested

    def test_the_retry_reopens_the_open_review_only_for_blocks_that_had_no_request(self):
        with V2():
            state = prepare(self.docx(['직원은 교통비를 받지 않는다.']), self.jobs, VENDOR)   # no request: its edit was a nomination
            state = self.answer(state, {'b1': [{'before': '받지 않는다', 'after': '받는다'}]})
            self.assertEqual(state['decision'], 'retry')
            self.assertTrue(self.batch(state)['sejong']['review']['enabled'])
        with V2():
            state = prepare(self.docx(['왜냐하면 일정이 변경됬습니다.']), self.jobs, VENDOR)   # a request: no new nominations
            state = self.answer(state, {'b1': [{'before': '변경됬습니다', 'after': '변경됐어요'}]})
            self.assertEqual(state['decision'], 'retry')
            batch = self.batch(state)
            self.assertFalse(batch['sejong']['review']['enabled'])
            self.assertEqual(len(batch['blocks'][0]['plan']['requests']), 1)


class NarrowedRetry(OfficeCase):
    PARAGRAPHS = ['직원은 교통비를 받지 않는다.', CLEAN]
    BAD = {'b1': [{'before': '받지 않는다', 'after': '받는다'}]}
    GOOD = {'b2': [{'before': '가지고 있다', 'after': '갖고 있다'}]}

    def first_round(self):
        with V2():
            state = prepare(self.docx(self.PARAGRAPHS), self.jobs, VENDOR)
            state = self.answer(state, {**self.BAD, **self.GOOD})
        return state

    def test_only_the_failed_block_is_asked_again_with_its_named_violations(self):
        state = self.first_round()
        self.assertEqual((state['decision'], state['attempt'], state['status']), ('retry', 2, 'rewrite'))
        batch = self.batch(state)
        self.assertEqual([b['id'] for b in batch['blocks']], ['b1'])
        self.assertEqual(batch['sejong']['attempt'], 2)
        self.assertNotIn('profile', batch['sejong'])
        retry = batch['sejong']['retry']
        self.assertEqual([r['block'] for r in retry], ['b1'])
        self.assertEqual([v['code'] for v in retry[0]['violations']], ['polarity_changed'])
        self.assertIn('의미가 바뀌었습니다', retry[0]['message'])
        self.assertTrue(any('편집 검증 후 재시도합니다' in w for w in state['warnings']))
        saved = json.loads((self.jobs / state['job'] / 'job.json').read_text(encoding='utf-8'))
        self.assertEqual(set(saved['carry']), {'b2'})

    def test_a_second_failure_restores_only_that_block_and_keeps_the_passed_edit(self):
        state = self.first_round()
        with V2():
            state = self.answer(state, self.BAD)
            self.assertEqual((state['decision'], state['status']), ('rollback', 'ready-to-finalize'))
            self.assertTrue(any('원문을 유지했습니다' in w and '문단 1' in w for w in state['warnings']))
            out = self.finalize(state)
        self.assertEqual([b['text'] for b in out], [self.PARAGRAPHS[0], '팀은 풍부한 경험을 갖고 있다.'])

    def test_a_fixed_second_answer_is_accepted_next_to_the_carried_edit(self):
        state = self.first_round()
        with V2():
            state = self.answer(state, {'b1': [{'before': '직원은', 'after': '직원이'}]})
            self.assertEqual((state['decision'], state['status']), ('accept', 'ready-to-finalize'))
            out = self.finalize(state)
        self.assertEqual([b['text'] for b in out], ['직원이 교통비를 받지 않는다.', '팀은 풍부한 경험을 갖고 있다.'])
        saved = json.loads((self.jobs / state['job'] / 'job.json').read_text(encoding='utf-8'))
        for key in ('carry', 'retry', 'active'):
            self.assertNotIn(key, saved)

    def test_a_retry_response_must_review_exactly_the_failed_blocks(self):
        state = self.first_round()
        with V2(), self.assertRaises(DocumentError):
            self.answer(state, reviewed=['b1', 'b2'])

    def test_legacy_retry_still_resends_the_whole_batch(self):
        with LEGACY():
            state = prepare(self.docx(self.PARAGRAPHS), self.jobs, VENDOR)
            state = self.answer(state, {**self.BAD, **self.GOOD})
            self.assertEqual((state['decision'], state['attempt']), ('retry', 2))
            self.assertEqual([b['id'] for b in self.batch(state)['blocks']], ['b1', 'b2'])
            saved = json.loads((self.jobs / state['job'] / 'job.json').read_text(encoding='utf-8'))
            self.assertFalse({'carry', 'retry', 'active'} & set(saved))


class EngineGuard(OfficeCase):
    def test_a_job_cannot_change_engine_midway(self):
        with V2():
            state = prepare(self.docx([CLEAN]), self.jobs, VENDOR)
        with LEGACY(), self.assertRaises(DocumentError):
            self.dispatch('next', state)
        with LEGACY():
            legacy = prepare(self.docx([CLEAN], 'legacy.docx'), self.jobs, VENDOR)
        with V2(), self.assertRaises(DocumentError):
            self.dispatch('next', legacy)
        with V2():
            self.assertEqual(self.dispatch('next', state)['status'], 'rewrite')

    def test_the_engine_version_is_recorded_and_checked(self):
        with V2():
            state = prepare(self.docx([CLEAN]), self.jobs, VENDOR)
            file = self.jobs / state['job'] / 'job.json'
            saved = json.loads(file.read_text(encoding='utf-8'))
            self.assertEqual(saved['engine']['id'], 'super-sejong')
            self.assertRegex(saved['engine']['version'], r'^\d+\.\d+\.\d+')
            saved['engine']['version'] = '0.0.1'
            file.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
            with self.assertRaises(DocumentError):
                self.dispatch('next', state)

    def test_cleanup_works_whatever_the_engine(self):
        with V2():
            state = prepare(self.docx([CLEAN]), self.jobs, VENDOR)
        with LEGACY():
            self.assertEqual(self.dispatch('cleanup', state)['status'], 'cleaned')
        self.assertFalse((self.jobs / state['job']).exists())


if __name__ == '__main__':
    unittest.main()
