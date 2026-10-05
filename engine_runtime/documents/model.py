from __future__ import annotations
import os
import re
import json
from bisect import bisect_right
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


# --------------------------------------------------------------------------
# Super Sejong Engine v2 (SUPER_SEJONG_ENGINE=v2): per-block plan and reject-only verification.
# The sejong package is imported only after the switch is on, so legacy jobs never load it.
# --------------------------------------------------------------------------
def sejong_v2():
    """Same reading of the switch as workflow.py: trimmed, lower-case; anything but v2 is legacy."""
    return os.environ.get('SUPER_SEJONG_ENGINE', '').strip().lower() == 'v2'


def _sejong():
    try:
        from .. import sejong
        from ..sejong import config, diagnose, plan, text, types, verify, voice
    except ImportError:  # Gateway imports documents as a top-level package.
        import sejong
        from sejong import config, diagnose, plan, text, types, verify, voice
    return sejong, config, diagnose, plan, text, types, verify, voice


# The SUPER_SEJONG_* settings a v2 job started with (job.json `sejongEnv`); every later call of the job reads them
# instead of its own environment, so a server restarted with other flags cannot strand a job between accept and
# finalize (code review 2026-10-05). None = read the process environment (prepare, legacy jobs).
_PINNED_ENV = None


def sejong_env():
    """The SUPER_SEJONG_* variables of this process, to pin in job.json at prepare."""
    return {k: v for k, v in os.environ.items() if k.startswith('SUPER_SEJONG_')}


def pin_sejong_env(env):
    global _PINNED_ENV
    _PINNED_ENV = dict(env) if env is not None else None


def sejong_flags():
    return _sejong()[1].Flags.from_env(_PINNED_ENV)


def sejong_engine():
    """{id, version} recorded in job.json when a job starts under v2 (a later change fails the job)."""
    return {'id': _sejong()[0].ENGINE_ID, 'version': _sejong()[0].VERSION}


class BlockRejected(DocumentError):
    """A v2 rejection that names its violations, so the retry prompt can quote them."""
    def __init__(self, message, violations=()):
        super().__init__(message)
        self.violations = list(violations)


# What a rejection tells the user and the retry prompt, by the family of the first violation. Codes only,
# never document text (DESIGN 4.4); the writer's retry prompt renders each code in Korean on the TS side.
FAMILY_MESSAGE = {
    'floor': '숫자·인용·이름 등 보호해야 할 표기가 바뀌었습니다',
    'meaning': '부정·가능·당위·행위 주체 등 문장의 의미가 바뀌었습니다',
    'voice': '말투(종결 어미·높임·문장 유형)가 바뀌었습니다',
    'cta': '행동 요청(CTA)의 내용이나 강도가 바뀌었습니다',
    'flow': '접속어·문장 순서 등 글의 흐름이 바뀌었습니다',
    'clarity': '문장이 더 읽기 어려워졌습니다',
    'norms': '맞춤법·띄어쓰기 오류가 새로 생겼습니다',
    'runaway': '문장 변경률이 너무 높습니다',
}
MAX_REPORTED = 8


def violation_json(violation):
    """The retry-prompt shape of one violation: code, detail label and the form to keep."""
    out = {'code': violation.code, 'detail': violation.detail or ''}
    if violation.family:
        out['family'] = violation.family
    if violation.keep:
        out['keep'] = violation.keep
    return out


def reject_with_sejong(source, result):
    """v2 verification of one block rewrite (DESIGN 4.3): every enforced violation of the sentence-aligned
    families (floor incl. josa, meaning, voice, CTA, flow, norms; clarity per its mode) rejects the edit.
    Nothing is repaired: an Office edit maps to formatting runs, so the writer's text is taken or refused.
    A crash in the checks refuses too (fail closed)."""
    try:
        found = _sejong()[6].verify_block(source, result, flags=sejong_flags())
    except Exception:
        raise DocumentError('수정 내용을 검증하지 못해 원문을 유지합니다.') from None
    if not found:
        return
    # verify_block reports a floor code once per pair and once for the whole text; say each violation once.
    found = list({(v.code, v.detail, v.keep): v for v in found}.values())
    codes = list(dict.fromkeys(v.code for v in found))[:MAX_REPORTED]
    if codes == ['josa_mismatch']:
        message = '수정한 낱말 뒤의 조사 형태가 맞지 않습니다.'
    else:
        message = f"{FAMILY_MESSAGE.get(found[0].family or 'floor', FAMILY_MESSAGE['floor'])} ({', '.join(codes)})"
    raise BlockRejected(message, [violation_json(v) for v in found[:MAX_REPORTED]])


# Office has no strength setting: every block is planned at the owner's route strength (DESIGN 3.4 medium =
# FIX + SUGGEST + open review) with the document genre (DESIGN 5.4: Office sends `document`).
OFFICE_STRENGTH = 'medium'
OFFICE_GENRE = 'document'


def _union(spans):
    """Sorted, non-overlapping [start, end) intervals covering every span."""
    merged = []
    for start, end in sorted((s['start'], s['end']) for s in spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _free_text(text, merged, ends, start, end):
    """Whether [start, end) of `text` has a non-blank character outside the Office-protected intervals
    (`merged` from _union, `ends` their end offsets): the interval-wise form of has_editable_text."""
    cursor = start
    for lo, hi in merged[bisect_right(ends, start):]:
        if lo >= end:
            break
        if lo > cursor and text[cursor:lo].strip():
            return True
        cursor = max(cursor, hi)
    return cursor < end and bool(text[cursor:end].strip())


def sejong_block_plan(block, flags):
    """Compact v2 plan of one Office block (DESIGN 3.4, 4.3): sejong.plan.build_plan on the block text, cut
    down to what the writer prompt needs. A request or deterministic fix on a sentence that the block's own
    protection covers completely (numbers, entities, quotes, fields) is dropped, because no edit can reach it.

      requests   [{sentence, text, tier, rules, guides, allowSplit, frozen, keepTokens, voice, fix?}] in
                 sentence order; `fix` lists the deterministic misspelling fixes of that sentence
                 (before/after), offered as FIX items because Office never repairs (OD 3)
      nominable  the sentences an open review may nominate (editable, Hangul, not wholly frozen)
      needsModel a request exists, or the plan allows an open review and a sentence can be nominated

    Deterministic fixes are offered only with SUPER_SEJONG_DETERMINISTIC_FIX=all; edited-only and off
    mean "never on a sentence the writer did not choose to rewrite" and "never"."""
    _, _, diagnose, plan_mod, text_mod, types, _, _ = _sejong()
    text = block['text']
    options = types.Options(input_kind='direct-text', strength=OFFICE_STRENGTH, genre=OFFICE_GENRE,
                            fix_colloquial=flags.fix_colloquial, deterministic_fix=flags.deterministic_fix)
    try:
        plan = plan_mod.build_plan(text, options=options, flags=flags)
    except Exception:  # an unplannable block is left as it is
        return {'requests': [], 'nominable': 0, 'needsModel': False}
    merged = _union(block['protected'])
    ends = [m[1] for m in merged]
    free = {s.id: _free_text(text, merged, ends, s.start, s.end) for s in plan.sentences}
    sentences = {s.id: s for s in plan.sentences}
    order = {s.id: i for i, s in enumerate(plan.sentences)}
    spans_of = {s.id: [] for s in plan.sentences}
    starts = [s.start for s in plan.sentences]
    for span in plan.protected:  # freeze/keep-token spans bucketed per sentence by bisection
        at = max(0, bisect_right(starts, span.start) - 1)
        while at < len(plan.sentences) and plan.sentences[at].start < span.end:
            s = plan.sentences[at]
            lo, hi = max(span.start, s.start), min(span.end, s.end)
            if lo < hi:
                spans_of[s.id].append((span.policy, text[lo:hi]))
            at += 1
    entries = {}

    def entry(sentence_id, tier):
        s = sentences[sentence_id]
        if sentence_id not in entries:
            voice = s.voice.to_json()
            entries[sentence_id] = {
                'sentence': sentence_id, 'text': text[s.start:s.end], 'tier': tier, 'rules': [], 'guides': [],
                'allowSplit': False,
                'frozen': list(dict.fromkeys(t for p, t in spans_of[sentence_id] if p == 'freeze' and t.strip())),
                'keepTokens': list(dict.fromkeys(t for p, t in spans_of[sentence_id] if p != 'freeze' and t.strip())),
                'voice': voice}
        elif tier == 'FIX':
            entries[sentence_id]['tier'] = 'FIX'
        return entries[sentence_id]

    for request in plan.requests:
        if free.get(request.sentence):
            item = entry(request.sentence, request.tier)
            item['rules'] = list(request.rules)
            item['guides'] = list(request.guides)
            item['allowSplit'] = bool(request.allow_split)
    if plan.options.deterministic_fix == 'all':
        rule_of = {f.id: f.rule for f in plan.findings}
        guides = diagnose.guides()
        for fix in plan.deterministic:
            if not free.get(fix.sentence):
                continue
            item = entry(fix.sentence, 'FIX')
            rule = rule_of.get(fix.finding)
            if rule and rule not in item['rules']:
                item['rules'].append(rule)
                if guides.get(rule) and guides[rule] not in item['guides']:
                    item['guides'].append(guides[rule])
            item.setdefault('fix', []).append({'before': fix.before, 'after': fix.after})
    requests = [entries[k] for k in sorted(entries, key=order.get)]
    nominable = 0
    if plan.open_review.enabled:
        document = plan_mod.source_document(plan, text)
        nominable = sum(1 for u in document.units if free[u.id] and plan_mod.nominable(u, plan.protected))
    return {'requests': requests, 'nominable': nominable, 'needsModel': bool(requests) or nominable > 0}


def sejong_nominations(block, edits, asked):
    """Sentences of the block that resolved `edits` really change although the plan made no request for them
    (`asked`: the ids of the requested sentences the writer was shown): the writer's open-review nominations
    (DESIGN 3.4, 3.9: unrequested edits are reverted unless the open review allows them). The changed range
    of an edit is its before/after without their common prefix and suffix, so a unique anchor that reaches
    into a neighbouring sentence does not count as touching it."""
    text_mod = _sejong()[4]
    changed = []
    for edit in edits:
        before, after = edit['before'], edit['after']
        if before == after:
            continue
        head = 0
        while head < min(len(before), len(after)) and before[head] == after[head]:
            head += 1
        tail = 0
        while tail < min(len(before), len(after)) - head and before[-1 - tail] == after[-1 - tail]:
            tail += 1
        lo = edit['start'] + head
        changed.append((lo, max(edit['end'] - tail, lo + 1)))
    units = text_mod.segment(block['text']).units
    touched = {u.id for u in units for lo, hi in changed if u.start < hi and u.end > lo}
    return sorted(touched - set(asked))


def sejong_review_limit(nominable):
    """Open-review cap of a batch: max(3, ceil(0.1 n)) over its nominable sentences (DESIGN 3.4)."""
    return _sejong()[3].review_limit(nominable)


def sejong_profile(texts):
    """{line, mixed} voice profile of a batch (prompt context only, never a decision; OD 1)."""
    _, _, _, _, text_mod, _, _, voice = _sejong()
    found = voice.profile(text_mod.segment('\n\n'.join(texts)))
    return {'line': found['line'], 'mixed': bool(found['mixed'])}


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
    if sejong_v2():
        # v2: the sentence-aligned verification (floor incl. particles, meaning, voice, CTA, flow, norms)
        # replaces the two v1 enforce-mode checks below; it rejects and never repairs.
        reject_with_sejong(source, result)
        return result
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
