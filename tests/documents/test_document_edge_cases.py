import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine_runtime'))
from documents.package import Package, DocumentError  # noqa: E402
from documents.model import extract, apply_edits, export, resolve_edits  # noqa: E402
from documents.workflow import prepare, dispatch  # noqa: E402

FIXTURE = ROOT / 'tests/fixtures/documents/mixed.docx'
NAMESPACES = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
              'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
              'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"')


class DocumentEdgeCases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def docx(self, body, name='case.docx'):
        parts = dict(Package(FIXTURE, 'docx').parts)
        parts['word/document.xml'] = (f'<w:document {NAMESPACES}><w:body>' + body +
                                      '<w:sectPr/></w:body></w:document>').encode()
        file = self.work / name
        with ZipFile(file, 'w', ZIP_DEFLATED) as archive:
            for part, data in parts.items():
                archive.writestr(part, data)
        return file

    def block(self, body):
        return extract(Package(self.docx(body), 'docx'))['blocks'][0]

    def test_latin_names_next_to_hangul_particles_are_protected(self):
        block = self.block('<w:p><w:r><w:t>삼성전자는 Apple과 경쟁한다. 우리는 AI를 활용한다. 그는 李文學 교수를 만났다.</w:t></w:r></w:p>')
        for before, after in (('Apple과', 'Google과'), ('AI를', 'ML을'), ('李文學', '李文鶴')):
            with self.subTest(before=before):
                with self.assertRaises(DocumentError):
                    apply_edits(block, resolve_edits(block, [{'before': before, 'after': after}]))

    def test_shadow_mode_keeps_the_ordered_modal_check(self):
        block = self.block('<w:p><w:r><w:t>신청서는 오늘 제출해야 한다.</w:t></w:r></w:p>')
        edits = resolve_edits(block, [{'before': '제출해야 한다', 'after': '제출할 수 있다'}])
        previous = os.environ.get('SUPER_SEJONG_MODE')
        try:
            for value in ('enforce', 'shadow', 'off'):
                os.environ['SUPER_SEJONG_MODE'] = value
                with self.subTest(mode=value), self.assertRaises(DocumentError):
                    apply_edits(block, edits)
        finally:
            if previous is None:
                os.environ.pop('SUPER_SEJONG_MODE', None)
            else:
                os.environ['SUPER_SEJONG_MODE'] = previous

    def test_edits_cannot_move_text_across_an_inline_picture(self):
        bold = '<w:rPr><w:b/></w:rPr>'
        picture = ('<w:r><w:drawing><wp:inline><wp:extent cx="1" cy="1"/><wp:docPr id="1" name="p"/>'
                   '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"/>'
                   '</a:graphic></wp:inline></w:drawing></w:r>')
        block = self.block('<w:p><w:r>' + bold + '<w:t xml:space="preserve">그림 설명은 </w:t></w:r>' + picture +
                           '<w:r>' + bold + '<w:t>아래에 둔다고 볼 수 있다.</w:t></w:r></w:p>')
        with self.assertRaises(DocumentError):
            apply_edits(block, resolve_edits(block, [{'before': '설명은 아래에 둔다고', 'after': '설명은 아래에 놓는다고'}]))
        edited = apply_edits(block, resolve_edits(block, [{'before': '둔다고', 'after': '놓는다고'}]))
        self.assertEqual(edited, '그림 설명은 아래에 놓는다고 볼 수 있다.')

    def test_xml_illegal_characters_are_rejected_before_finalize(self):
        file = self.docx('<w:p><w:r><w:t>팀은 풍부한 경험을 가지고 있다.</w:t></w:r></w:p>')
        jobs, vendor = self.work / 'jobs', ROOT / 'vendor/humanize-engine'
        state = prepare(file, jobs, vendor)
        batch = json.loads(Path(state['inputPath']).read_text(encoding='utf-8'))
        block = batch['blocks'][0]
        response = {'schemaVersion': 2, 'batchId': batch['batchId'], 'sourceHash': batch['sourceHash'],
                    'reviewedIds': [block['id']], 'warnings': [],
                    'blocks': [{'id': block['id'], 'sourceHash': block['sourceHash'],
                                'edits': [{'before': '가지고', 'after': '갖\ufffe고'}]}]}
        Path(state['responsePath']).write_text(json.dumps(response), encoding='utf-8')
        state = dispatch(SimpleNamespace(command='accept', job=state['job'], chunk=state['chunk'],
                                         attempt=state['attempt'], source_hash=state['sourceHash'],
                                         response=state['responsePath']), jobs, vendor)
        self.assertNotEqual(state['decision'], 'accept')
        full = extract(Package(file, 'docx'))['blocks'][0]
        with self.assertRaises(DocumentError):
            apply_edits(full, resolve_edits(full, [{'before': '가지고', 'after': '갖\ud800고'}]))

    def test_tab_stop_definitions_are_not_text(self):
        block = self.block('<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="2000"/><w:tab w:val="right" w:pos="9000"/>'
                           '</w:tabs></w:pPr><w:r><w:t>이 문단은 탭 문자가 없다.</w:t></w:r></w:p>')
        self.assertEqual(block['text'], '이 문단은 탭 문자가 없다.')
        block = self.block('<w:p><w:r><w:t>앞</w:t><w:tab/><w:t>뒤에 있는 글이다.</w:t></w:r></w:p>')
        self.assertEqual(block['text'], '앞\t뒤에 있는 글이다.')

    def test_ruby_readings_are_protected(self):
        block = self.block('<w:p><w:r><w:t xml:space="preserve">이 제도는 </w:t></w:r><w:ruby><w:rubyPr/>'
                           '<w:rt><w:r><w:t>민본</w:t></w:r></w:rt><w:rubyBase><w:r><w:t>근본</w:t></w:r></w:rubyBase>'
                           '</w:ruby><w:r><w:t xml:space="preserve"> 사상에 뿌리를 두고 있다. 이 사상은 오래되었다.</w:t></w:r></w:p>')
        with self.assertRaises(DocumentError):
            apply_edits(block, resolve_edits(block, [{'before': '민본', 'after': '인본'}]))

    def test_changed_number_words_are_rejected(self):
        block = self.block('<w:p><w:r><w:t>매출은 두 배로 늘었고 참석자는 열 명이었다.</w:t></w:r></w:p>')
        with self.assertRaises(DocumentError):
            apply_edits(block, resolve_edits(block, [{'before': '두 배로', 'after': '세 배로'}]))

    def test_changed_duration_unit_is_rejected(self):
        block = self.block('<w:p><w:r><w:t>배송은 세 시간 걸렸다.</w:t></w:r></w:p>')
        with self.assertRaises(DocumentError):
            apply_edits(block, resolve_edits(block, [{'before': '세 시간', 'after': '세 분'}]))

    def test_many_small_xml_parts_cannot_exhaust_the_parser_budget(self):
        parts = dict(Package(FIXTURE, 'docx').parts)
        large_xml = b'<root>' + b'a' * (8 * 1024**2) + b'</root>'
        for index in range(3):
            parts[f'customXml/large-{index}.xml'] = large_xml
        file = self.work / 'many-xml-parts.docx'
        with ZipFile(file, 'w', ZIP_DEFLATED) as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
        with self.assertRaises(DocumentError):
            Package(file, 'docx')

    def test_edit_cannot_delete_an_entire_sentence(self):
        block = self.block('<w:p><w:r><w:t>서비스가 좋아졌다. 고객은 만족했다.</w:t></w:r></w:p>')
        with self.assertRaises(DocumentError):
            apply_edits(block, resolve_edits(block, [{'before': ' 고객은 만족했다.', 'after': ''}]))

    def test_edit_cannot_move_obligation_to_another_subject(self):
        block = self.block('<w:p><w:r><w:t>직원은 검토해야 한다. 관리자는 승인한다.</w:t></w:r></w:p>')
        edits = resolve_edits(block, [
            {'before': '검토해야', 'after': '검토'},
            {'before': '승인한다', 'after': '승인해야 한다'},
        ])
        with self.assertRaises(DocumentError):
            apply_edits(block, edits)

    def test_edit_cannot_swap_who_helps_whom(self):
        block = self.block('<w:p><w:r><w:t>직원은 관리자를 돕는다.</w:t></w:r></w:p>')
        edits = resolve_edits(block, [
            {'before': '직원은', 'after': '직원을'},
            {'before': '관리자를', 'after': '관리자는'},
        ])
        with self.assertRaises(DocumentError):
            apply_edits(block, edits)

    def test_reordered_names_cannot_exchange_roles(self):
        block = self.block('<w:p><w:r><w:t>민수는 지수를 도왔다.</w:t></w:r></w:p>')
        with self.assertRaises(DocumentError):
            apply_edits(block, resolve_edits(block, [{'before': '민수는 지수를', 'after': '지수는 민수를'}]))

    def test_short_negation_before_connective_cannot_disappear(self):
        block = self.block('<w:p><w:r><w:t>그는 안 먹고 집에 갔다.</w:t></w:r></w:p>')
        with self.assertRaises(DocumentError):
            apply_edits(block, resolve_edits(block, [{'before': '안 먹고', 'after': '먹고'}]))

    def test_short_negation_cannot_move_to_a_new_predicate(self):
        block = self.block('<w:p><w:r><w:t>그는 안 먹고 집에 갔다.</w:t></w:r></w:p>')
        edits = resolve_edits(block, [{'before': '안 먹고', 'after': '먹고'}, {'before': '집에 갔다', 'after': '집에 안 갔다'}])
        with self.assertRaises(DocumentError):
            apply_edits(block, edits)

    def test_one_hour_cannot_become_one_minute(self):
        block = self.block('<w:p><w:r><w:t>배송은 한 시간 걸렸다.</w:t></w:r></w:p>')
        with self.assertRaises(DocumentError):
            apply_edits(block, resolve_edits(block, [{'before': '한 시간', 'after': '한 분'}]))

    def test_possible_and_difficult_cannot_swap_between_projects(self):
        block = self.block('<w:p><w:r><w:t>서울 사업은 내년부터 시행이 가능하다. 부산 사업은 현재 시행이 어렵다.</w:t></w:r></w:p>')
        edits = resolve_edits(block, [{'before': '가능하다', 'after': '어렵다'}, {'before': '어렵다.', 'after': '가능하다.'}])
        with self.assertRaises(DocumentError):
            apply_edits(block, edits)

    def test_approval_cannot_become_rejection(self):
        block = self.block('<w:p><w:r><w:t>위원회는 신청서를 승인했다.</w:t></w:r></w:p>')
        with self.assertRaises(DocumentError):
            apply_edits(block, resolve_edits(block, [{'before': '승인했다', 'after': '거절했다'}]))

    def test_topic_to_subject_particle_is_not_a_hard_role_error(self):
        block = self.block('<w:p><w:r><w:t>민수는 책을 읽었다.</w:t></w:r></w:p>')
        edited = apply_edits(block, resolve_edits(block, [{'before': '민수는', 'after': '민수가'}]))
        self.assertEqual(edited, '민수가 책을 읽었다.')

    def accept_with_warnings(self, warnings):
        file = self.docx('<w:p><w:r><w:t>팀은 풍부한 경험을 가지고 있다.</w:t></w:r></w:p>')
        jobs, vendor = self.work / 'jobs', ROOT / 'vendor/humanize-engine'
        state = prepare(file, jobs, vendor)
        batch = json.loads(Path(state['inputPath']).read_text(encoding='utf-8'))
        block = batch['blocks'][0]
        response = {'schemaVersion': 2, 'batchId': batch['batchId'], 'sourceHash': batch['sourceHash'],
                    'reviewedIds': [block['id']], 'warnings': warnings,
                    'blocks': [{'id': block['id'], 'sourceHash': block['sourceHash'], 'edits': []}]}
        Path(state['responsePath']).write_text(json.dumps(response, ensure_ascii=False), encoding='utf-8')
        return dispatch(SimpleNamespace(command='accept', job=state['job'], chunk=state['chunk'],
                                        attempt=state['attempt'], source_hash=state['sourceHash'],
                                        response=state['responsePath']), jobs, vendor)

    def test_model_warnings_are_not_echoed_to_clients(self):
        # A warning may be a prompt-injection exfiltration channel; keep only a fixed notice.
        schema = json.loads((ROOT / 'engine_runtime/documents/response-schema.json').read_text(encoding='utf-8'))
        self.assertEqual(schema['properties']['warnings'].get('maxItems'), 20)
        self.assertEqual(schema['properties']['warnings']['items'].get('maxLength'), 300)
        state = self.accept_with_warnings([f'검토 사유 {i}' for i in range(21)] + ['/private/auth.json'])
        self.assertEqual(state['decision'], 'accept')
        self.assertIn('모델이 검토 주의 사항을 제시했습니다. 원문과 결과를 확인해 주세요.', state['warnings'])
        self.assertNotIn('/private/auth.json', str(state['warnings']))
        self.assertNotIn('검토 사유', str(state['warnings']))

    def test_job_status_fields_come_before_the_preview(self):
        # R2-5.6: hosts that truncate long output still see status and paths.
        file = self.docx('<w:p><w:r><w:t>팀은 풍부한 경험을 가지고 있다.</w:t></w:r></w:p>')
        state = prepare(file, self.work / 'jobs', ROOT / 'vendor/humanize-engine')
        keys = list(state)
        for key in ('status', 'inputPath', 'responsePath'):
            self.assertLess(keys.index(key), keys.index('preview'), keys)

    def test_completed_document_reports_actual_output_characters(self):
        file = self.docx('<w:p><w:r><w:t>팀은 풍부한 경험을 가지고 있다.</w:t></w:r></w:p>')
        jobs, vendor = self.work / 'jobs', ROOT / 'vendor/humanize-engine'
        state = prepare(file, jobs, vendor)
        batch = json.loads(Path(state['inputPath']).read_text(encoding='utf-8'))
        block = batch['blocks'][0]
        response = {'schemaVersion': 2, 'batchId': batch['batchId'], 'sourceHash': batch['sourceHash'],
                    'reviewedIds': [block['id']], 'warnings': [],
                    'blocks': [{'id': block['id'], 'sourceHash': block['sourceHash'],
                                'edits': [{'before': '가지고 있다', 'after': '갖고 있다'}]}]}
        Path(state['responsePath']).write_text(json.dumps(response, ensure_ascii=False), encoding='utf-8')
        state = dispatch(SimpleNamespace(command='accept', job=state['job'], chunk=state['chunk'],
                                         attempt=state['attempt'], source_hash=state['sourceHash'],
                                         response=state['responsePath']), jobs, vendor)
        self.assertEqual(state['decision'], 'accept')
        output = self.work / 'shorter.docx'
        done = dispatch(SimpleNamespace(command='finalize', job=state['job'], output=str(output)), jobs, vendor)
        self.assertEqual(done['outputChars'], done['sourceChars'] - 1)


if __name__ == '__main__':
    unittest.main()
