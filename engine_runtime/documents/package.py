from __future__ import annotations
import hashlib
import io
import posixpath
import struct
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile, BadZipFile
from lxml import etree as E

# Resource limits of one DOCX/PPTX. A small hostile file must not cost much memory, time or model calls, so
# every limit is checked before the work it bounds: the ZIP end records before zipfile reads the central
# directory, declared sizes before any entry is read, the bytes actually read while reading, a node census
# of every XML part before any tree is built, and the text and batch counts while the blocks are extracted
# (model.py). The same numbers are documented in docs/documents.md and docs/skills-guide.md.
MAX_FILE = 50 * 1024**2           # the file itself (also enforced by the portal upload, the app and the MCP server)
MAX_TOTAL = 250 * 1024**2         # expanded bytes of all entries, declared and actually read
MAX_XML = 10 * 1024**2            # one XML part
MAX_TOTAL_XML = 24 * 1024**2      # all XML parts
MAX_ENTRIES = 10_000              # ZIP entries
MAX_DIRECTORY = 4 * 1024**2       # central directory bytes, checked before zipfile parses it
MAX_RATIO = 100                   # expanded : compressed of the whole package ...
RATIO_GRACE = 8 * 1024**2         # ... once more than this is expanded
MAX_NODES = 1_500_000             # elements, attributes, text runs, comments and PIs of all XML parts
MAX_DEPTH = 64                    # element nesting of one XML part
LIMIT_CODE = 'DOCUMENT_TOO_LARGE'
W = ('http://schemas.openxmlformats.org/wordprocessingml/2006/main', 'http://purl.oclc.org/ooxml/wordprocessingml/main')
A = ('http://schemas.openxmlformats.org/drawingml/2006/main', 'http://purl.oclc.org/ooxml/drawingml/main')
P = ('http://schemas.openxmlformats.org/presentationml/2006/main', 'http://purl.oclc.org/ooxml/presentationml/main')
R = ('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'http://purl.oclc.org/ooxml/officeDocument/relationships')
XMLSPACE = '{http://www.w3.org/XML/1998/namespace}space'
UNREADABLE = 'DOCX/PPTX ZIP 문서를 읽지 못했습니다.'

class DocumentError(ValueError):
    pass

class DocumentLimitError(DocumentError):
    """A resource limit of the package or its text. The message is fixed Korean text (never document content),
    so the portal, the app, the MCP server and the skill Gateway show it as it is, under LIMIT_CODE."""
    code = LIMIT_CODE

def limit(message, split=True):
    return DocumentLimitError(message + (' 문서를 나눠서 다시 시도해 주세요.' if split else ''))

def _too_many_entries():
    return limit(f'문서 내부 파일은 {MAX_ENTRIES:,}개 이하만 지원합니다.')

def _xml_part_too_large():
    return limit(f'문서 XML part는 {MAX_XML // 1024**2} MiB 이하만 지원합니다.')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def local(node):
    return E.QName(node).localname if isinstance(node.tag, str) else ''

def ns(node):
    return E.QName(node).namespace if isinstance(node.tag, str) else ''

def _parser(target=None):
    return E.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False, huge_tree=False,
                       remove_blank_text=False, remove_comments=False, strip_cdata=False, target=target)

class _Census:
    """Parser target that builds nothing: it counts the nodes a tree of the part would hold (elements,
    attributes, text runs, comments, PIs) against the package budget and tracks the nesting depth. Raising
    from a callback stops libxml2 at once, so a hostile part costs only the bytes read before the limit."""
    def __init__(self, budget):
        self.left, self.depth, self.text = budget, 0, False
    def spend(self, nodes):
        self.left -= nodes
        if self.left < 0:
            raise limit(f'문서 구조가 너무 복잡합니다(XML 노드 {MAX_NODES:,}개 초과).')
    def start(self, tag, attrib):
        self.depth += 1; self.text = False
        if self.depth > MAX_DEPTH:
            raise limit(f'문서 구조가 너무 깊게 중첩되어 있습니다(XML {MAX_DEPTH}단계 초과).')
        self.spend(1 + len(attrib))
    def end(self, tag):
        self.depth -= 1; self.text = False
    def data(self, data):
        if not self.text:
            self.text = True; self.spend(1)
    def comment(self, text):
        self.text = False; self.spend(1)
    def pi(self, target, data=None):
        self.text = False; self.spend(1)
    def close(self):
        return self.left

def census(data, budget=MAX_NODES):
    """Node budget left after `data`; raises DocumentLimitError past MAX_NODES or MAX_DEPTH."""
    if len(data) > MAX_XML:
        raise _xml_part_too_large()
    try:
        return E.fromstring(data, _parser(_Census(budget)))
    except E.XMLSyntaxError as exc:
        raise DocumentError('손상된 XML 문서입니다.') from exc

def directory(raw):
    """(entries, central directory bytes) from the end records, found the way zipfile finds them, so that a
    huge central directory is refused before zipfile turns every entry into an object."""
    at = len(raw) - 22
    if at < 0 or raw[at:at + 4] != b'PK\x05\x06' or raw[-2:] != b'\0\0':
        at = raw.rfind(b'PK\x05\x06', max(0, len(raw) - 22 - 65535))
    if at < 0 or len(raw) - at < 22:
        raise DocumentError(UNREADABLE)
    _, _, _, _, entries, size, _, _ = struct.unpack('<4s4H2LH', raw[at:at + 22])
    locator = at - 20
    if locator >= 56 and raw[locator:locator + 4] == b'PK\x06\x07' and raw[locator - 56:locator - 52] == b'PK\x06\x06':
        _, _, _, _, _, _, _, entries, size, _ = struct.unpack('<4sQ2H2L4Q', raw[locator - 56:locator])
    return entries, size

def xml(data):
    if len(data) > MAX_XML:
        raise _xml_part_too_large()
    parser = _parser()
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
    def __init__(self, file: Path, expected: str | None = None, limits: bool = True):
        """`limits=False` is for a package this module wrote from an accepted one (export's verification): the
        byte limits still apply, the ratio and node census do not, since accepted edits change them a little."""
        if file.stat().st_size > MAX_FILE:
            raise limit(f'파일은 {MAX_FILE // 1024**2} MiB 이하만 지원합니다.', split=False)
        self.raw = file.read_bytes()
        self.hash = digest(self.raw)
        self.parts = {}
        self.trees = {}
        entries, size = directory(self.raw)
        if entries > MAX_ENTRIES or size > MAX_DIRECTORY:
            raise _too_many_entries()
        try:
            with ZipFile(io.BytesIO(self.raw)) as z:
                self.infos = z.infolist()
                if len(self.infos) > MAX_ENTRIES:
                    raise _too_many_entries()
                # Declared sizes first: nothing is decompressed for a package that announces too much. Entries
                # never share bytes in a real package, so their compressed sizes fit in the file, and that keeps
                # the ratio check honest.
                declared = sum(info.file_size for info in self.infos)
                if sum(info.compress_size for info in self.infos) > len(self.raw):
                    raise DocumentError(UNREADABLE)
                expanded = max(RATIO_GRACE, MAX_RATIO * len(self.raw)) if limits else MAX_TOTAL
                self._check_total(declared, expanded)
                total = 0
                xml_total = 0
                for info in self.infos:
                    name = info.filename
                    is_xml = name.lower().endswith(('.xml', '.rels'))
                    if name in self.parts or '\\' in name or name.startswith('/') or ':' in name or '..' in name.split('/'):
                        raise DocumentError('잘못된 문서 내부 경로입니다.')
                    if info.flag_bits & 1:
                        raise DocumentError('암호화된 문서는 지원하지 않습니다.')
                    if is_xml and info.file_size > MAX_XML:
                        raise _xml_part_too_large()
                    chunks = []
                    member_size = 0
                    with z.open(info) as f:
                        while chunk := f.read(1024*1024):
                            member_size += len(chunk)
                            total += len(chunk)
                            self._check_total(total, expanded)
                            if is_xml:
                                xml_total += len(chunk)
                                if member_size > MAX_XML:
                                    raise _xml_part_too_large()
                                if xml_total > MAX_TOTAL_XML:
                                    raise limit(f'문서 XML 전체는 {MAX_TOTAL_XML // 1024**2} MiB 이하만 지원합니다.')
                            chunks.append(chunk)
                    self.parts[name] = b''.join(chunks)
                self.comment = z.comment
        except (BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise DocumentError(UNREADABLE) from exc
        # Every XML part is counted before any is parsed: a part of tiny elements costs a tree far larger than
        # its bytes, so trees are built only once the whole package is known to fit the node budget.
        budget = MAX_NODES
        names = [name for name in self.parts if name.lower().endswith(('.xml', '.rels'))]
        for name in names if limits else ():
            budget = census(self.parts[name], budget)
        for name in names:
            self.trees[name] = xml(self.parts[name])
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

    @staticmethod
    def _check_total(size, expanded):
        if size > MAX_TOTAL:
            raise limit(f'문서 압축 해제 크기는 {MAX_TOTAL // 1024**2} MiB 이하만 지원합니다.')
        if size > expanded:
            raise limit(f'압축률이 비정상적으로 높은 문서는 지원하지 않습니다(압축 해제 {MAX_RATIO}배 초과).', split=False)

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
