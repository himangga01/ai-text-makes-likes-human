"""Resource limits of an Office file: every limit refuses a hostile file before the work it bounds, with a
DocumentLimitError (code DOCUMENT_TOO_LARGE) and a fixed Korean message, and real documents still pass."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine_runtime'))
from documents import package as package_module  # noqa: E402
from documents import model as model_module  # noqa: E402
from documents.package import Package, DocumentError, DocumentLimitError  # noqa: E402
from documents.model import extract, export, apply_edits  # noqa: E402
from documents.workflow import prepare, dispatch  # noqa: E402

FIXTURES = ROOT / 'tests/fixtures/documents'
VENDOR = ROOT / 'vendor/humanize-engine'
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
PARAGRAPH = '<w:p><w:r><w:t>{}</w:t></w:r></w:p>'


class DocumentLimits(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def docx(self, body=None, extra=None, name='case.docx'):
        """The fixture DOCX with another body and extra parts."""
        parts = dict(Package(FIXTURES / 'mixed.docx', 'docx').parts)
        if body is not None:
            parts['word/document.xml'] = (f'<w:document {W}><w:body>' + body + '<w:sectPr/></w:body></w:document>').encode()
        parts.update(extra or {})
        file = self.work / name
        with ZipFile(file, 'w', ZIP_DEFLATED) as archive:
            for part, data in parts.items():
                archive.writestr(part, data)
        return file

    def refused(self, file, message, fmt='docx'):
        with self.assertRaises(DocumentLimitError) as caught:
            prepare(file, self.work / 'jobs', VENDOR)
        self.assertEqual(caught.exception.code, 'DOCUMENT_TOO_LARGE')
        self.assertIn(message, str(caught.exception))
        self.assertFalse((self.work / 'jobs').exists() and any((self.work / 'jobs').iterdir()))
        return caught.exception

    def test_real_documents_still_pass(self):
        for fmt in ('docx', 'pptx'):
            with self.subTest(fmt=fmt):
                state = prepare(FIXTURES / f'mixed.{fmt}', self.work / fmt, VENDOR)
                self.assertEqual(state['status'], 'rewrite')

    def test_a_highly_compressed_package_is_refused_before_it_is_expanded(self):
        file = self.docx(extra={'word/media/zero.bin': bytes(4 * 1024**2)})
        with patch.object(package_module, 'RATIO_GRACE', 1024**2), patch.object(package_module.ZipFile, 'open', side_effect=AssertionError('read')):
            self.refused(file, '압축률이 비정상적으로 높은 문서')

    def test_the_declared_expanded_size_is_refused_before_reading(self):
        file = self.docx(extra={'word/media/random.bin': os.urandom(256 * 1024)})
        with patch.object(package_module, 'MAX_TOTAL', 128 * 1024), patch.object(package_module.ZipFile, 'open', side_effect=AssertionError('read')):
            self.refused(file, '압축 해제 크기')

    def test_tiny_xml_nodes_are_counted_before_any_tree_is_built(self):
        # A part of empty elements holds far more nodes than its bytes suggest.
        file = self.docx(extra={'customXml/item1.xml': b'<r>' + b'<a/>' * 3000 + b'</r>'})
        with patch.object(package_module, 'MAX_NODES', 2000), patch.object(package_module, 'xml', side_effect=AssertionError('parsed')):
            self.refused(file, 'XML 노드')

    def test_attributes_and_text_count_as_nodes(self):
        self.assertEqual(package_module.census(b'<r a="1" b="2">x<s/>y<!--c--><?p d?></r>', 100), 100 - 8)

    def test_deep_nesting_is_refused(self):
        depth = package_module.MAX_DEPTH + 1
        file = self.docx(extra={'customXml/item1.xml': b'<a>' * depth + b'</a>' * depth})
        self.refused(file, 'XML 64단계')

    def test_a_huge_central_directory_is_refused_before_zipfile_reads_it(self):
        file = self.docx(extra={f'x/{index}': b'' for index in range(40)})
        with patch.object(package_module, 'MAX_ENTRIES', 30), patch.object(package_module, 'ZipFile', side_effect=AssertionError('opened')):
            self.refused(file, '내부 파일은 30개')
        with patch.object(package_module, 'MAX_DIRECTORY', 512), patch.object(package_module, 'ZipFile', side_effect=AssertionError('opened')):
            self.refused(file, '내부 파일은')

    def test_text_segments_blocks_characters_and_batches(self):
        cases = [('MAX_CHARS', 50, PARAGRAPH.format('가' * 60), '추출 텍스트는 50자'),
                 ('MAX_SEGMENTS', 10, PARAGRAPH.format('가') * 11, '텍스트 조각'),
                 ('MAX_BLOCKS', 5, PARAGRAPH.format('1') * 6, '문단·셀'),
                 ('MAX_BATCHES', 2, PARAGRAPH.format('강한 경쟁력을 가지고 있다.') * (96 * 2 + 1), '2구간')]
        for name, value, body, message in cases:
            with self.subTest(limit=name), patch.object(model_module, name, value):
                self.refused(self.docx(body), message)

    def test_many_tiny_paragraphs_fail_fast_instead_of_making_countless_batches(self):
        # Within the character limit, but far more paragraphs than any batch budget allows.
        file = self.docx(PARAGRAPH.format('가') * 99072)
        self.assertLess(file.stat().st_size, 64 * 1024)
        started = time.monotonic()
        self.refused(file, '텍스트 조각')
        self.assertLess(time.monotonic() - started, 30)

    def test_many_sibling_paragraphs_keep_their_text_positions_through_export(self):
        body = PARAGRAPH.format('1') * 3000 + PARAGRAPH.format('이 방안은 강한 경쟁력을 가지고 있다.')
        pkg = Package(self.docx(body), 'docx')
        manifest = extract(pkg)
        block = manifest['blocks'][-1]
        self.assertEqual([run['path'] for run in block['runs']], [3000])
        start = block['text'].index('가지고 있다')
        edit = {'start': start, 'end': start + 6, 'before': '가지고 있다', 'after': '갖고 있다'}
        out = self.work / 'out.docx'
        export(pkg, manifest, {block['id']: [edit]}, out)
        self.assertEqual(extract(Package(out, 'docx'))['blocks'][-1]['text'], '이 방안은 강한 경쟁력을 갖고 있다.')

    def test_a_job_prepared_with_element_paths_still_exports(self):
        pkg = Package(FIXTURES / 'mixed.docx', 'docx')
        manifest = extract(pkg)
        tree = pkg.tree(pkg.main)
        nodes = list(tree.iter(*model_module.TEXT_TAGS))
        for block in manifest['blocks']:
            for run in block['runs']:
                run['path'] = tree.getelementpath(nodes[run['path']])
        block = next(b for b in manifest['blocks'] if '가지고 있다' in b['text'] and b['editable'])
        start = block['text'].index('가지고 있다')
        edit = {'start': start, 'end': start + 6, 'before': '가지고 있다', 'after': '갖고 있다'}
        apply_edits(block, [edit])
        out = self.work / 'legacy.docx'
        export(pkg, manifest, {block['id']: [edit]}, out)
        self.assertTrue(any('갖고 있다' in b['text'] for b in extract(Package(out, 'docx'))['blocks']))

    def test_an_accepted_edit_may_grow_the_text_past_the_input_limit(self):
        # The limits apply to the source; export's check of its own result does not refuse the accepted growth.
        text = '이 방안은 강한 경쟁력을 가지고 있다.'
        file = self.docx(PARAGRAPH.format(text))
        with patch.object(model_module, 'MAX_CHARS', len(text)):
            state = prepare(file, self.work / 'jobs', VENDOR)
            batch = json.loads(Path(state['inputPath']).read_text(encoding='utf-8'))
            block = batch['blocks'][0]
            reply = {'schemaVersion': 2, 'batchId': batch['batchId'], 'sourceHash': batch['sourceHash'], 'warnings': [],
                     'reviewedIds': [block['id']], 'blocks': [{'id': block['id'], 'sourceHash': block['sourceHash'],
                                                                'edits': [{'before': '방안은', 'after': '새로운 방안은'}]}]}
            Path(state['responsePath']).write_text(json.dumps(reply, ensure_ascii=False), encoding='utf-8')
            state = dispatch(SimpleNamespace(command='accept', job=state['job'], chunk=1, attempt=1, source_hash=state['sourceHash'],
                                             response=state['responsePath']), self.work / 'jobs', VENDOR)
            self.assertEqual(state['status'], 'ready-to-finalize')
            out = self.work / 'grown.docx'
            done = dispatch(SimpleNamespace(command='finalize', job=state['job'], output=str(out)), self.work / 'jobs', VENDOR)
        self.assertEqual(done['status'], 'done')
        self.assertIn('새로운 방안은', extract(Package(out, 'docx'))['blocks'][0]['text'])

    def test_the_gateway_reports_a_limit_with_its_code(self):
        file = self.docx(extra={'word/media/zero.bin': bytes(64 * 1024**2)})
        result = subprocess.run([sys.executable, str(ROOT / 'engine_runtime/skill_gateway.py'), '--workspace-root', str(self.work / 'jobs'),
                                 'prepare', '--input', str(file)], capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 1)
        failure = json.loads(result.stdout)
        self.assertEqual(failure['code'], 'DOCUMENT_TOO_LARGE')
        self.assertIn('압축률이 비정상적으로 높은 문서', failure['message'])
        malformed = self.work / 'bad.docx'
        malformed.write_bytes(b'not a zip')
        result = subprocess.run([sys.executable, str(ROOT / 'engine_runtime/skill_gateway.py'), '--workspace-root', str(self.work / 'jobs'),
                                 'prepare', '--input', str(malformed)], capture_output=True, encoding='utf-8')
        self.assertNotIn('code', json.loads(result.stdout))


if __name__ == '__main__':
    unittest.main()
