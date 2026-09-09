from __future__ import annotations
import hashlib
import io
import posixpath
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile, BadZipFile
from lxml import etree as E

MAX_FILE = 50 * 1024**2
MAX_TOTAL = 250 * 1024**2
MAX_XML = 10 * 1024**2
W = ('http://schemas.openxmlformats.org/wordprocessingml/2006/main', 'http://purl.oclc.org/ooxml/wordprocessingml/main')
A = ('http://schemas.openxmlformats.org/drawingml/2006/main', 'http://purl.oclc.org/ooxml/drawingml/main')
P = ('http://schemas.openxmlformats.org/presentationml/2006/main', 'http://purl.oclc.org/ooxml/presentationml/main')
R = ('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'http://purl.oclc.org/ooxml/officeDocument/relationships')
XMLSPACE = '{http://www.w3.org/XML/1998/namespace}space'

class DocumentError(ValueError):
    pass

def digest(data):
    return hashlib.sha256(data).hexdigest()

def local(node):
    return E.QName(node).localname if isinstance(node.tag, str) else ''

def ns(node):
    return E.QName(node).namespace if isinstance(node.tag, str) else ''

def xml(data):
    if len(data) > MAX_XML:
        raise DocumentError('XML 크기 제한을 초과했습니다.')
    parser = E.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False,
                         huge_tree=False, remove_blank_text=False, remove_comments=False, strip_cdata=False)
    try:
        tree = E.parse(io.BytesIO(data), parser)
        if tree.docinfo.doctype or any(isinstance(n, E._Entity) for n in tree.iter()):
            raise DocumentError('DTD/엔티티가 포함된 문서는 지원하지 않습니다.')
        return tree
    except E.XMLSyntaxError as exc:
        raise DocumentError('손상된 XML 문서입니다.') from exc

def rel_name(part):
    return posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels') if part else '_rels/.rels'

class Package:
    def __init__(self, file: Path, expected: str | None = None):
        if file.stat().st_size > MAX_FILE:
            raise DocumentError('파일은 50 MiB 이하만 지원합니다.')
        self.raw = file.read_bytes()
        self.hash = digest(self.raw)
        self.parts = {}
        self.trees = {}
        try:
            with ZipFile(io.BytesIO(self.raw)) as z:
                self.infos = z.infolist()
                if len(self.infos) > 10000:
                    raise DocumentError('문서 내부 파일 수가 너무 많습니다.')
                total = 0
                for info in self.infos:
                    name = info.filename
                    if name in self.parts or '\\' in name or name.startswith('/') or ':' in name or '..' in name.split('/'):
                        raise DocumentError('잘못된 문서 내부 경로입니다.')
                    if info.flag_bits & 1 or info.file_size > MAX_TOTAL:
                        raise DocumentError('암호화되었거나 너무 큰 문서입니다.')
                    chunks = []
                    with z.open(info) as f:
                        while chunk := f.read(1024*1024):
                            total += len(chunk)
                            if total > MAX_TOTAL:
                                raise DocumentError('압축 해제 크기 제한을 초과했습니다.')
                            chunks.append(chunk)
                    data = b''.join(chunks)
                    self.parts[name] = data
                    if name.lower().endswith(('.xml', '.rels')):
                        self.trees[name] = xml(data)
                self.comment = z.comment
        except (BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise DocumentError('DOCX/PPTX ZIP 문서를 읽지 못했습니다. 암호화 파일은 지원하지 않습니다.') from exc
        if '[Content_Types].xml' not in self.parts or '_rels/.rels' not in self.parts:
            raise DocumentError('Office 문서 패키지가 아닙니다.')
        ctypes = self.parts['[Content_Types].xml'].lower()
        if any(x in ctypes for x in (b'macroenabled', b'vbaproject', b'digital-signature')) or any(
            x.lower().startswith('_xmlsignatures/') or 'vbaproject' in x.lower() for x in self.parts):
            raise DocumentError('매크로 또는 디지털 서명 문서는 지원하지 않습니다.')
        for name in self.trees:
            if name.endswith('.rels'):
                source = '' if name == '_rels/.rels' else posixpath.join(posixpath.dirname(posixpath.dirname(name)), posixpath.basename(name)[:-5])
                self.relationships(source)
        roots = [r for r in self.relationships('') if r['type'].endswith('/officeDocument') and not r['external']]
        if len(roots) != 1:
            raise DocumentError('문서 본문 관계를 확인하지 못했습니다.')
        self.main = roots[0]['target']
        root = self.tree(self.main).getroot()
        self.format = 'docx' if ns(root) in W and local(root) == 'document' else 'pptx' if ns(root) in P and local(root) == 'presentation' else None
        if not self.format or expected and expected != self.format:
            raise DocumentError('확장자와 실제 문서 형식이 다릅니다.')
        expected_mime = b'wordprocessingml.document.main+xml' if self.format == 'docx' else b'presentationml.presentation.main+xml'
        if expected_mime not in ctypes:
            raise DocumentError('지원하지 않는 Office 문서 형식입니다.')
        for tree in self.trees.values():
            if any(local(n) in ('documentProtection', 'writeProtection', 'modifyVerifier') for n in tree.iter()):
                raise DocumentError('편집 보호가 설정된 문서는 지원하지 않습니다.')

    def tree(self, part):
        if part not in self.trees:
            raise DocumentError('문서 XML part가 없습니다.')
        return self.trees[part]

    def relationships(self, part):
        tree = self.trees.get(rel_name(part))
        out = []
        if tree is None:
            return out
        ids = set()
        for r in tree.getroot():
            rid, target = r.get('Id'), r.get('Target', '')
            if not rid or rid in ids:
                raise DocumentError('문서 관계 ID가 잘못되었습니다.')
            ids.add(rid)
            external = r.get('TargetMode') == 'External'
            if not external:
                target = unquote(target).split('#')[0]
                if '\\' in target or ':' in target:
                    raise DocumentError('문서 관계 경로가 잘못되었습니다.')
                target = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(part), target))
                if target.startswith('../') or target not in self.parts:
                    raise DocumentError('문서 관계 대상이 없거나 패키지 밖입니다.')
            out.append({'id': rid, 'type': r.get('Type', ''), 'target': target, 'external': external})
        return out

    def write(self, output: Path, changes: dict):
        with output.open('xb') as f:
            with ZipFile(f, 'w') as z:
                z.comment = self.comment
                for info in self.infos:
                    z.writestr(info, changes.get(info.filename, self.parts[info.filename]))
