from __future__ import annotations
import re
import json
from .package import W, A, P, R, E, XMLSPACE, Package, DocumentError, local, ns, digest
try:
    from ..quantities import signed_quantities
    from ..super_sejong import document_sentence_drift, mode as super_sejong_mode
    from .. import super_sejong_josa as josa
except ImportError:  # Gateway imports documents as a top-level package.
    from quantities import signed_quantities
    from super_sejong import document_sentence_drift, mode as super_sejong_mode
    import super_sejong_josa as josa

PROTECTED = {'hyperlink', 'fldSimple', 'fldChar', 'instrText', 'fld', 'bookmarkStart', 'bookmarkEnd',
             'commentRangeStart', 'commentRangeEnd', 'ins', 'del', 'moveFrom', 'moveTo', 'sdt',
             'footnoteReference', 'endnoteReference', 'AlternateContent', 'oMath', 'oMathPara',
             'noBreakHyphen', 'softHyphen', 'sym', 'ptab'}
QUOTE = re.compile(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|\x27[^\x27\n]*\x27|「[^」]*」|『[^』]*』')
# \b는 한글도 단어 문자로 보므로 "Apple과"의 A 앞뒤에 경계가 없다 — 라틴 문자 경계만 본다.
RISK = re.compile(r'\d|https?://|(?<![A-Za-z0-9])[A-Z][A-Za-z0-9_-]*|[가-힣]+(?:님|씨)(?=\s|[.,]|$)'
                  r'|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]'
                  r'|[가-힣]{2,4}\s?(?:대표|회장|사장|교수|장관|차관|의원|위원장|박사|기자|총리|대통령|시장|지사|원장|소장|감독|선수|작가|변호사|판사|검사)'
                  r'(?=$|[\s,.은는이가을를의께도와과])')
# 두 서식 run 사이에 이런 인라인 객체가 있으면 같은 서식이어도 편집 구간을 나눈다.
# 합치면 치환 텍스트가 첫 run에 몰려 그림·주석 위치가 글자에 대해 이동한다.
INLINE_OBJECTS = {'drawing', 'pict', 'object', 'commentReference', 'footnoteReference', 'endnoteReference',
                  'AlternateContent', 'fldChar', 'sym', 'ptab', 'noBreakHyphen', 'softHyphen', 'ruby'}
XML_ILLEGAL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')
MODAL = re.compile(r'않|없|못|아니|금지|불가|해야|필요|수\s*있|판단|추정|보인다|가능|듯')
SHORT_NEGATION = re.compile(r'(?<!\S)안(?=\s+[가-힣]+(?:다|요)(?=$|[\s.!?,]))')

def _nearest(node, names):
    return next((a for a in node.iterancestors() if local(a) in names), None)


def public_block(block):
    # Style identity and XML paths remain local for verification, never in the prompt.
    return {**{k: block[k] for k in ('id', 'location', 'text', 'sourceHash', 'protected', 'maxChars')},
            'spans': [{'start': s['start'], 'end': s['end']} for s in block['spans']]}


def has_editable_text(text, protected):
    cursor = 0
    for span in sorted(protected, key=lambda s: s['start']):
        if text[cursor:span['start']].strip():
            return True
        cursor = max(cursor, span['end'])
    return bool(text[cursor:].strip())

def extract(pkg: Package):
    parts = [(pkg.main, 0)]
    if pkg.format == 'pptx':
        rels = {r['id']: r for r in pkg.relationships(pkg.main)}
        parts = []
        for n in pkg.tree(pkg.main).iter():
            if local(n) == 'sldId':
                rid = next((n.get('{'+r+'}id') for r in R if n.get('{'+r+'}id')), None)
                rel = rels.get(rid)
                if not rel or rel['external'] or not rel['type'].endswith('/slide'):
                    raise DocumentError('슬라이드 관계가 잘못되었습니다.')
                parts.append((rel['target'], len(parts)+1))
        if len(parts) > 200 or len({p[0] for p in parts}) != len(parts):
            raise DocumentError('슬라이드는 200개 이하이며 중복 관계가 없어야 합니다.')
    blocks, warnings = [], []
    total = 0
    for part, slide in parts:
        tree = pkg.tree(part)
        paragraphs = [n for n in tree.iter() if local(n) == 'p' and ns(n) in W+A]
        field_depth = 0
        for index, para in enumerate(paragraphs, 1):
            inside_field = field_depth > 0
            for n in para.iter():
                if local(n) == 'fldChar' and _nearest(n, {'p'}) is para:
                    inside_field = True
                    kind=next((v for k,v in n.attrib.items() if k.endswith('}fldCharType')), '')
                    if kind=='begin':field_depth+=1
                    if kind=='end':field_depth=max(0,field_depth-1)
            # Tab-stop definitions (w:tabs/w:tab, a:tabLst/a:tab) are layout, not text.
            nodes = [n for n in para.iter() if local(n) in ('t','br','cr','tab') and ns(n) in W+A and _nearest(n, {'p'}) is para
                     and not (local(n) == 'tab' and local(n.getparent()) in ('tabs', 'tabLst'))]
            if not any(local(n)=='t' for n in nodes):
                continue
            wanted, barriers, pending = set(map(id, nodes)), set(), False
            for n in para.iter():
                if _nearest(n, {'p'}) is not para and n is not para:
                    continue
                if local(n) in INLINE_OBJECTS:
                    pending = True
                elif id(n) in wanted and local(n) == 't':
                    if pending:
                        barriers.add(id(n))
                    pending = False
            shape = _nearest(para, {'sp', 'graphicFrame'})
            shape_id = next((n.get('id') for n in shape.iter() if local(n) == 'cNvPr'), '') if shape is not None else ''
            location = f'슬라이드 {slide} · 도형 {shape_id or "표"} · 문단 {index}' if slide else f'문단 {index}'
            protected = any(local(n) in PROTECTED for n in para.iter() if _nearest(n, {'p'}) is para)
            protected = protected or any(local(n) in PROTECTED for n in para.iterancestors())
            # Complex fields may span multiple paragraphs; preserve only that range.
            protected = protected or inside_field
            runs, text, spans, controls, ruby = [], '', [], [], []
            for node in nodes:
                if local(node)!='t':
                    start=len(text);text+='\t' if local(node)=='tab' else '\n'
                    controls.append({'start':start,'end':len(text)})
                    spans.append({'start':start,'end':len(text),'style':'protected-control'})
                    continue
                run = _nearest(node, {'r'})
                props = next((n for n in run if local(n) == 'rPr'), None) if run is not None else None
                key = E.tostring(props, method='c14n') if props is not None else b''
                if props is not None and any(local(n) in ('hlinkClick', 'hlinkMouseOver') for n in props.iter()):
                    protected = True
                start = len(text)
                text += node.text or ''
                runs.append({'path': tree.getelementpath(node), 'start': start, 'end': len(text)})
                if _nearest(node, {'ruby', 'p'}) is not None and local(_nearest(node, {'ruby', 'p'})) == 'ruby':
                    ruby.append({'start': start, 'end': len(text)})  # reading and base stay paired
                parent = run.getparent() if run is not None else node.getparent()
                signature = digest(key) + tree.getpath(parent)
                if spans and spans[-1]['style'] == signature and id(node) not in barriers:
                    spans[-1]['end'] = len(text)
                else:
                    spans.append({'start': start, 'end': len(text), 'style': signature})
            total += len(text)
            title = any(local(n) == 'pStyle' and any('heading' in v.lower() or 'title' in v.lower() for v in n.attrib.values()) for n in para.iter())
            if shape is not None:
                title = title or any(local(n) == 'ph' and n.get('type') in ('title', 'ctrTitle') for n in shape.iter())
            # Numeric/entity-bearing sentences are immutable so value-to-subject association survives.
            protected_spans = controls[:] + ruby
            offset = 0
            for sentence in re.split(r'(?<=[.!?])(?=\s)', text):
                if RISK.search(sentence):
                    protected_spans.append({'start': offset, 'end': offset+len(sentence)})
                offset += len(sentence)
            protected_spans += [{'start': m.start(), 'end': m.end()} for m in QUOTE.finditer(text)]
            editable = bool(re.search('[가-힣]', text)) and not protected and len(text) <= 9000 and has_editable_text(text, protected_spans)
            if protected or len(text) > 9000:
                warnings.append(f'{location}: 필드·보호 구조 또는 긴 구간을 원문으로 유지합니다.')
            blocks.append({'id': f'b{len(blocks)+1}', 'part': part, 'location': location, 'text': text,
                           'sourceHash': digest(text.encode()), 'runs': runs, 'spans': spans,
                           'protected': protected_spans, 'editable': editable,
                           'maxChars': len(text) if title or slide else min(10000, max(len(text)+30, int(len(text)*1.2)))})
        for node in tree.iter():
            if local(node) in ('object', 'oleObj', 'AlternateContent', 'oMath') or local(node)=='graphicData' and not node.get('uri','').endswith('/table'):
                warnings.append(f'{"슬라이드 "+str(slide) if slide else "문서"}: 차트·수식·삽입 객체·호환 구조는 원본을 보존합니다.')
    if total > 100000:
        raise DocumentError('추출 텍스트는 100,000자 이하만 지원합니다.')
    if pkg.format == 'pptx':
        warnings.append('발표자 노트·마스터·테마·미디어는 원본을 유지합니다. 결과 슬라이드의 배치를 확인해 주세요.')
    else:
        warnings.append('머리글·바닥글·각주·미주·주석은 원본을 유지합니다. 결과 문서의 페이지 배치를 확인해 주세요.')
    batches, current, size, packet_size = [], [], 0, 0
    for block in blocks:
        if not block['editable'] or not block['text'].strip():
            continue
        # Bound both text and actual metadata. Many tiny Word paragraphs should not
        # each consume a separate 32-item invocation; dense spans still split early.
        cost = len(json.dumps(public_block(block), ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        if current and (size+len(block['text']) > 7000 or len(current) >= 96 or packet_size+cost > 48000):
            batches.append(current); current=[]; size=0; packet_size=0
        current.append(block['id']); size += len(block['text']); packet_size += cost
    if current:
        batches.append(current)
    return {'schemaVersion': 1, 'format': pkg.format, 'sourceHash': pkg.hash,
            'partHashes': {name: digest(data) for name,data in pkg.parts.items()},
            'blocks': blocks, 'batches': batches, 'warnings': list(dict.fromkeys(warnings)),
            'sourceChars': total, 'slides': len(parts) if pkg.format == 'pptx' else 0}

def resolve_edits(block, edits):
    """Resolve compact exact anchors locally; never guess among duplicate matches."""
    if not isinstance(edits,list) or len(edits)>200:
        raise DocumentError('편집 목록이 잘못되었습니다.')
    result=[]
    for edit in edits:
        if isinstance(edit,dict) and set(edit)=={'before','after'}:
            before=edit['before']
            if not isinstance(before,str) or not before:
                raise DocumentError('편집 원문이 비어 있습니다.')
            start=block['text'].find(before)
            if start<0 or block['text'].find(before,start+1)>=0:
                raise DocumentError('편집 원문이 없거나 여러 번 등장합니다. 문맥을 포함해 유일하게 지정해 주세요.')
            edit={**edit,'start':start,'end':start+len(before)}
        result.append(edit)
    return result


def apply_edits(block, edits):
    if not isinstance(edits, list) or len(edits)>200:
        raise DocumentError('편집 목록이 잘못되었습니다.')
    source = block['text']
    previous = -1
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'start','end','before','after'}:
            raise DocumentError('편집 응답 형식이 잘못되었습니다.')
        start,end = edit['start'], edit['end']
        if type(start) is not int or type(end) is not int or not 0<=start<end<=len(source) or start<previous:
            raise DocumentError('편집 범위가 겹치거나 잘못되었습니다. 삽입은 인접 원문을 포함한 치환으로 제출해 주세요.')
        if edit['before'] != source[start:end] or not isinstance(edit['after'],str) or len(edit['after'])>10000:
            raise DocumentError('편집 대상 원문이 일치하지 않습니다.')
        if any(c in edit['after'] for c in ('\n','\r','\t')) or any(ord(c)<32 for c in edit['after']):
            raise DocumentError('문단 구조를 바꾸는 편집은 허용하지 않습니다.')
        if XML_ILLEGAL.search(edit['after']):
            raise DocumentError('문서에 쓸 수 없는 문자가 포함된 편집입니다.')
        if not any(start>=s['start'] and end<=s['end'] for s in block['spans']):
            raise DocumentError('서식 경계를 넘는 편집입니다.')
        if any(start<p['end'] and end>p['start'] for p in block['protected']):
            raise DocumentError('숫자·인용·이름 보호 구간을 변경했습니다.')
        previous = end
    result = source
    for edit in reversed(edits):
        result=result[:edit['start']]+edit['after']+result[edit['end']:]
    if not result.strip() or len(result)>block['maxChars']:
        raise DocumentError('텍스트 길이 제한을 벗어났습니다.')
    from difflib import SequenceMatcher
    if 1-SequenceMatcher(None,source,result,autojunk=False).ratio()>=0.5:
        raise DocumentError('문장 변경률이 50% 이상입니다.')
    # In enforce mode Super Sejong's sentence-aligned comparison replaces these ordered list checks,
    # which also rejected harmless clause reordering. Shadow and off keep them, so shadow is never weaker.
    sejong = super_sejong_mode()
    if sejong != 'enforce' and MODAL.findall(source)!=MODAL.findall(result):
        raise DocumentError('부정·당위·추측 표현 변화가 감지되었습니다.')
    if sejong != 'enforce' and SHORT_NEGATION.findall(source)!=SHORT_NEGATION.findall(result):
        raise DocumentError('짧은 부정 표현 변화가 감지되었습니다.')
    if signed_quantities(source)!=signed_quantities(result):
        raise DocumentError('숫자·부호·단위가 추가되거나 변경되었습니다.')
    if sejong == 'enforce' and document_sentence_drift(source, result):
        raise DocumentError('문장이 사라지거나 부정·당위의 문장별 의미가 바뀌었습니다.')
    # Office runs map edits to formatting spans, so an introduced particle mismatch is rejected, not repaired.
    if sejong == 'enforce' and josa.gate(source, result, None, 'certain'):
        raise DocumentError('수정한 낱말 뒤의 조사 형태가 맞지 않습니다.')
    return result

def export(pkg, manifest, accepted, output):
    if pkg.hash != manifest['sourceHash']:
        raise DocumentError('원본 문서가 변경되었습니다.')
    changes, allowed = {}, {}
    for block in manifest['blocks']:
        edits = accepted.get(block['id'], [])
        if not edits:
            continue
        if not block['editable']:
            raise DocumentError('보호 블록에 편집이 있습니다.')
        apply_edits(block, edits)
        tree=pkg.tree(block['part'])
        for edit in reversed(edits):
            affected=[r for r in block['runs'] if r['start']<edit['end'] and r['end']>edit['start']]
            for index, run in enumerate(affected):
                node=tree.find(run['path'])
                if node is None: raise DocumentError('문서 텍스트 노드를 찾을 수 없습니다.')
                value=node.text or ''
                lo=max(0,edit['start']-run['start']); hi=min(run['end'],edit['end'])-run['start']
                node.text=value[:lo]+(edit['after'] if index==0 else '')+value[hi:]
                if (node.text or '').startswith(' ') or (node.text or '').endswith(' '):
                    node.set(XMLSPACE,'preserve')
                allowed.setdefault(block['part'],set()).add(run['path'])
        changes[block['part']]=E.tostring(tree,encoding='UTF-8',xml_declaration=True,standalone=tree.docinfo.standalone)
    pkg.write(output,changes)
    try:
        check=Package(output,manifest['format'])
        if set(check.parts)!=set(pkg.parts):
            raise DocumentError('결과의 문서 part 목록이 변경되었습니다.')
        from .package import xml
        for name,data in pkg.parts.items():
            if name not in changes:
                if check.parts[name]!=data:
                    raise DocumentError('원본 보존 part가 변경되었습니다.')
            else:
                before,after=xml(data),check.tree(name)
                for xpath in allowed[name]:
                    old=before.find(xpath); new=after.find(xpath)
                    if old is None or new is None:
                        raise DocumentError('결과 텍스트 노드 대응이 깨졌습니다.')
                    new.text=old.text
                    if XMLSPACE in old.attrib: new.set(XMLSPACE,old.get(XMLSPACE))
                    else: new.attrib.pop(XMLSPACE,None)
                if E.tostring(before,method='c14n')!=E.tostring(after,method='c14n'):
                    raise DocumentError('허용된 텍스트 외 XML 변경이 감지되었습니다.')
        fresh=extract(Package(output,manifest['format']))
        if len(fresh['blocks'])!=len(manifest['blocks']):
            raise DocumentError('문서 블록이 누락되었습니다.')
        for old,new in zip(manifest['blocks'],fresh['blocks']):
            expected=apply_edits(old,accepted[old['id']]) if accepted.get(old['id']) else old['text']
            if expected!=new['text']:
                raise DocumentError('결과 문서 텍스트 대응이 다릅니다.')
    except Exception:
        output.unlink(missing_ok=True)
        raise
