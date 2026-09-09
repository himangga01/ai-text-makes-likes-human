import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'engine_runtime'))
from documents.package import Package, DocumentError, xml
from documents.model import extract,apply_edits,export
from documents.workflow import prepare,dispatch
FIXTURES=ROOT/'tests/fixtures/documents'

class Documents(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.work=Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def package(self,fmt='docx'):
        return Package(FIXTURES/f'mixed.{fmt}',fmt)
    def mutate(self,fmt,mutator):
        p=self.package(fmt);parts=dict(p.parts);mutator(parts)
        file=self.work/('mutated.'+fmt)
        with ZipFile(file,'w',ZIP_DEFLATED) as z:
            for n,data in parts.items():z.writestr(n,data)
        return file
    def edits(self,block):
        word='가지고 있다';start=block['text'].find(word)
        if start<0:return []
        edit={'start':start,'end':start+len(word),'before':word,'after':'갖고 있다'}
        try:apply_edits(block,[edit]);return [edit]
        except DocumentError:return []
    def test_real_office_packages_and_preview(self):
        for fmt in ('docx','pptx'):
            with self.subTest(fmt=fmt):
                m=extract(self.package(fmt))
                self.assertTrue(m['batches']);self.assertGreater(len(m['blocks']),5)
                self.assertTrue(any('가지고 있다' in b['text'] for b in m['blocks']))
                if fmt=='pptx':self.assertEqual(m['slides'],2)
    def test_noop_roundtrip_preserves_every_part(self):
        for fmt in ('docx','pptx'):
            with self.subTest(fmt=fmt):
                p=self.package(fmt);m=extract(p);out=self.work/('noop.'+fmt)
                export(p,m,{},out)
                self.assertEqual(p.parts,Package(out,fmt).parts)
    def test_edits_preserve_structure_and_nontext_parts(self):
        for fmt in ('docx','pptx'):
            with self.subTest(fmt=fmt):
                p=self.package(fmt);m=extract(p)
                edits={b['id']:self.edits(b) for b in m['blocks'] if b['editable']}
                self.assertTrue(any(edits.values()))
                out=self.work/('edited.'+fmt);export(p,m,edits,out)
                after=Package(out,fmt)
                touched={b['part'] for b in m['blocks'] if edits.get(b['id'])}
                self.assertEqual({k:v for k,v in p.parts.items() if k not in touched},{k:v for k,v in after.parts.items() if k not in touched})
                self.assertTrue(any('갖고 있다' in b['text'] for b in extract(after)['blocks']))
    def editable(self):
        return next(b for b in extract(self.package())['blocks'] if b['editable'] and self.edits(b))
    def test_bad_before_rejected(self):
        b=self.editable();e=self.edits(b);e[0]['before']='wrong'
        with self.assertRaises(DocumentError):apply_edits(b,e)
    def test_overlap_rejected(self):
        b=self.editable();e=self.edits(b)
        with self.assertRaises(DocumentError):apply_edits(b,e+e)
    def test_style_boundary_rejected(self):
        b=self.editable();b['spans']=[{'start':0,'end':2},{'start':2,'end':len(b['text'])}]
        with self.assertRaises(DocumentError):apply_edits(b,[{'start':0,'end':4,'before':b['text'][:4],'after':'변경'}])
    def test_number_association_protected(self):
        b=next(b for b in extract(self.package())['blocks'] if '10명' in b['text'])
        start=b['text'].index('10')
        with self.assertRaises(DocumentError):apply_edits(b,[{'start':start,'end':start+2,'before':'10','after':'20'}])
    def test_short_quote_protected(self):
        b=next(b for b in extract(self.package())['blocks'] if '승인한다' in b['text']);start=b['text'].index('승인한다')
        with self.assertRaises(DocumentError):apply_edits(b,[{'start':start,'end':start+4,'before':'승인한다','after':'거절한다'}])
    def test_negation_injection_rejected(self):
        b=self.editable();start=b['text'].index('있다')
        with self.assertRaises(DocumentError):apply_edits(b,[{'start':start,'end':start+2,'before':'있다','after':'없다'}])
    def test_ppt_growth_rejected(self):
        b=next(b for b in extract(self.package('pptx'))['blocks'] if b['editable'] and '가지고 있다' in b['text'])
        e=self.edits(b);e[0]['after']='매우 풍부하게 가지고 있다'
        with self.assertRaises(DocumentError):apply_edits(b,e)
    def test_wrong_extension_rejected(self):
        with self.assertRaises(DocumentError):Package(FIXTURES/'mixed.docx','pptx')
    def test_dtd_rejected(self):
        with self.assertRaises(DocumentError):xml(b'<!DOCTYPE r [<!ENTITY x "text">]><r>&x;</r>')
    def test_zip_traversal_rejected(self):
        file=self.mutate('docx',lambda parts:parts.update({'../escape':b'x'}))
        with self.assertRaises(DocumentError):Package(file,'docx')
    def test_missing_part_rejected(self):
        file=self.mutate('docx',lambda parts:parts.pop(self.package().main))
        with self.assertRaises(DocumentError):Package(file,'docx')
    def test_macro_rejected(self):
        file=self.mutate('docx',lambda parts:parts.update({'word/vbaProject.bin':b'content'}))
        with self.assertRaises(DocumentError):Package(file,'docx')
    def test_signed_rejected(self):
        file=self.mutate('docx',lambda parts:parts.update({'_xmlsignatures/sig1.xml':b'<signature/>'}))
        with self.assertRaises(DocumentError):Package(file,'docx')
    def test_strict_namespaces(self):
        def change(parts):
            for name,data in list(parts.items()):
                if name.endswith(('.xml','.rels')):
                    data=data.replace(b'http://schemas.openxmlformats.org/wordprocessingml/2006/main',b'http://purl.oclc.org/ooxml/wordprocessingml/main')
                    parts[name]=data.replace(b'http://schemas.openxmlformats.org/officeDocument/2006/relationships',b'http://purl.oclc.org/ooxml/officeDocument/relationships')
        p=Package(self.mutate('docx',change),'docx');m=extract(p)
        out=self.work/'strict.docx';export(p,m,{b['id']:self.edits(b) for b in m['blocks'] if b['editable']},out)
        self.assertEqual(Package(out,'docx').format,'docx')
    def test_fields_across_textless_paragraphs_protected(self):
        def change(parts):
            data=parts['word/document.xml'].decode()
            field='<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r></w:p><w:p><w:r><w:t>필드 결과를 가지고 있다.</w:t></w:r></w:p><w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
            parts['word/document.xml']=data.replace('<w:body>','<w:body>'+field).encode()
        m=extract(Package(self.mutate('docx',change),'docx'))
        self.assertFalse(next(b for b in m['blocks'] if '필드 결과' in b['text'])['editable'])
        self.assertTrue(next(b for b in m['blocks'] if '강한 경쟁력' in b['text'])['editable'])
    def test_duplicate_zip_entry_rejected(self):
        file=self.work/'duplicate.docx'
        with ZipFile(file,'w') as z:
            z.writestr('same.xml','<a/>');z.writestr('same.xml','<b/>')
        with self.assertRaises(DocumentError):Package(file,'docx')
    def test_unicode_offsets_and_xml_escaping(self):
        def change(parts):parts['word/document.xml']=parts['word/document.xml'].replace('내용을 자연스럽게 다듬는다.'.encode(),'😀 내용을 자연스럽게 다듬는다.'.encode())
        p=Package(self.mutate('docx',change),'docx');m=extract(p)
        b=next(b for b in m['blocks'] if '😀' in b['text']);start=b['text'].index('자연스럽게')
        edit={'start':start,'end':start+5,'before':'자연스럽게','after':'<정확히>'}
        out=self.work/'unicode.docx';export(p,m,{b['id']:[edit]},out)
        self.assertIn('&lt;정확히&gt;',Package(out).parts[b['part']].decode())
    def test_export_rejects_changed_source(self):
        p=self.package();m=extract(p);m['sourceHash']='0'*64
        with self.assertRaises(DocumentError):export(p,m,{},self.work/'wrong.docx')
    def test_explicit_break_and_tab_are_preserved_while_text_is_edited(self):
        def change(parts):parts['word/document.xml']=parts['word/document.xml'].replace('강한 경쟁력을 가지고 있다. 내용을 자연스럽게 다듬는다.'.encode(),'강한 경쟁력을 가지고 있다.</w:t><w:br/><w:tab/><w:t>내용을 자연스럽게 다듬는다.'.encode())
        p=Package(self.mutate('docx',change),'docx');m=extract(p);b=next(b for b in m['blocks'] if '\n\t' in b['text'])
        self.assertTrue(b['editable']);self.assertIn('\n\t',b['text'])
        out=self.work/'breaks.docx';export(p,m,{b['id']:self.edits(b)},out)
        after=next(x for x in extract(Package(out))['blocks'] if '\n\t' in x['text'])
        self.assertIn('갖고 있다.\n\t',after['text'])
    def test_many_short_paragraphs_use_bounded_larger_batches(self):
        def change(parts):
            para='<w:p><w:r><w:t>강한 경쟁력을 가지고 있다.</w:t></w:r></w:p>'
            parts['word/document.xml']=parts['word/document.xml'].replace(b'<w:body>', ('<w:body>'+para*200).encode())
        manifest=extract(Package(self.mutate('docx',change),'docx'))
        self.assertEqual(len(manifest['batches']),3)
        self.assertTrue(all(len(batch)<=96 for batch in manifest['batches']))
        ids=[id for batch in manifest['batches'] for id in batch]
        self.assertEqual(ids,[b['id'] for b in manifest['blocks'] if b['editable'] and b['text'].strip()])

    def test_sparse_response_requires_complete_review_and_rejects_foreign_edits(self):
        root=self.work/'jobs';vendor=ROOT/'vendor/humanize-engine'
        state=prepare(FIXTURES/'mixed.docx',root,vendor)
        batch=json.loads(Path(state['inputPath']).read_text(encoding='utf-8'))
        ids=[b['id'] for b in batch['blocks']]
        value={'schemaVersion':2,'batchId':batch['batchId'],'sourceHash':batch['sourceHash'],
               'reviewedIds':ids,'blocks':[],'warnings':[]}
        def submit(payload):
            Path(state['responsePath']).write_text(json.dumps(payload),encoding='utf-8')
            return dispatch(SimpleNamespace(command='accept',job=state['job'],chunk=state['chunk'],attempt=state['attempt'],source_hash=state['sourceHash'],response=state['responsePath']),root,vendor)
        for bad_ids in (ids[:-1],ids+[ids[0]],list(reversed(ids))):
            if bad_ids!=ids:
                with self.assertRaises(DocumentError):submit({**value,'reviewedIds':bad_ids})
        with self.assertRaises(DocumentError):submit({**value,'blocks':[{'id':'foreign','sourceHash':'x','edits':[]}]})
        with self.assertRaises(DocumentError):submit({**value,'blocks':[{'id':ids[0],'sourceHash':batch['blocks'][0]['sourceHash'],'edits':[]}]*2})
        done=submit(value)
        self.assertEqual(done['status'],'ready-to-finalize')
        out=self.work/'sparse.docx'
        dispatch(SimpleNamespace(command='finalize',job=state['job'],output=str(out)),root,vendor)
        self.assertEqual(Package(out).parts,self.package().parts)

    def test_gateway_complete_and_no_overwrite(self):
        root=self.work/'jobs';vendor=ROOT/'vendor/humanize-engine'
        state=prepare(FIXTURES/'mixed.docx',root,vendor)
        while state['status']=='rewrite':
            batch=json.loads(Path(state['inputPath']).read_text(encoding='utf-8'))
            value={'schemaVersion':2,'batchId':batch['batchId'],'sourceHash':batch['sourceHash'],'warnings':[],
                   'reviewedIds':[b['id'] for b in batch['blocks']],
                   'blocks':[{'id':b['id'],'sourceHash':b['sourceHash'],'edits':self.edits(b)} for b in batch['blocks'] if self.edits(b)]}
            Path(state['responsePath']).write_text(json.dumps(value),encoding='utf-8')
            state=dispatch(SimpleNamespace(command='accept',job=state['job'],chunk=state['chunk'],attempt=state['attempt'],source_hash=state['sourceHash'],response=state['responsePath']),root,vendor)
        out=self.work/'out.docx'
        done=dispatch(SimpleNamespace(command='finalize',job=state['job'],output=str(out)),root,vendor)
        self.assertEqual(done['status'],'done');self.assertIn('갖고 있다',done['preview'])
        with self.assertRaises(DocumentError):dispatch(SimpleNamespace(command='finalize',job=state['job'],output=str(out)),root,vendor)
        dispatch(SimpleNamespace(command='cleanup',job=state['job']),root,vendor)
        self.assertFalse((root/state['job']).exists())

class CompactBatchTests(unittest.TestCase):
    def test_exact_anchors_resolve_unicode_but_never_guess(self):
        from documents.model import resolve_edits
        block={'text':'😀 강한 경쟁력을 가지고 있다.'}
        edits=resolve_edits(block,[{'before':'가지고 있다','after':'갖고 있다'}])
        self.assertEqual(block['text'][edits[0]['start']:edits[0]['end']],'가지고 있다')
        for text,before in [('가 가','가'),('가','나'),('가','')]:
            with self.assertRaises(DocumentError):resolve_edits({'text':text},[{'before':before,'after':'다'}])
    def test_protected_union_and_partial_text(self):
        from documents.model import has_editable_text
        self.assertFalse(has_editable_text('가나다라', [{'start':0,'end':2},{'start':1,'end':4}]))
        self.assertTrue(has_editable_text('가나다라', [{'start':0,'end':2}]))

    def test_public_spans_hide_style_and_xml_paths(self):
        from documents.model import public_block
        manifest=extract(Package(FIXTURES/'mixed.docx'))
        block=next(b for b in manifest['blocks'] if b['editable'])
        public=public_block(block)
        self.assertTrue(all(set(span)=={'start','end'} for span in public['spans']))
        self.assertTrue(all('style' in span for span in block['spans']))
        self.assertEqual(public['sourceHash'],block['sourceHash'])

if __name__=='__main__':unittest.main()
