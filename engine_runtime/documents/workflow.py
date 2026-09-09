from __future__ import annotations
import json
import os
from pathlib import Path
import uuid
from .package import Package, DocumentError, digest
from .model import extract, apply_edits, export

def save(file, value):
    temp=file.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    temp.replace(file)

def prepare(input_path, root, vendor):
    suffix=input_path.suffix.lower()[1:]
    if suffix not in ('docx','pptx'):
        raise DocumentError('DOCX/PPTX 문서만 지원합니다.')
    pkg=Package(input_path,suffix)
    manifest=extract(pkg)
    if not manifest['batches']:
        raise DocumentError('윤문 가능한 텍스트가 없습니다. 보호 구조만 있는 문서는 원본을 유지해 주세요.')
    job=root/('job-'+uuid.uuid4().hex)
    job.mkdir(parents=True)
    (job/('original.'+suffix)).write_bytes(pkg.raw)
    save(job/'document.json',manifest)
    state={'schemaVersion':2,'kind':'document','job':job.name,'format':suffix,'inputPath':str(input_path.resolve()),
           'name':input_path.stem+'-humanized.'+suffix,'vendor':str(vendor.resolve()),'current':0,'attempt':1,
           'sourceHash':pkg.hash,'manifestHash':digest((job/'document.json').read_bytes()),
           'status':'active','accepted':{},'warnings':manifest['warnings'],'restored':0}
    save(job/'job.json',state)
    return next_batch(job,state,manifest)

def public_block(block):
    return {k:block[k] for k in ('id','location','text','sourceHash','spans','protected','maxChars')}

def next_batch(job,state,manifest):
    base={'job':job.name,'kind':'document','format':state['format'],'name':state['name'],
          'sourceHash':state['sourceHash'],'warnings':state['warnings'], 'sourceChars':manifest['sourceChars'],
          'totalChunks':len(manifest['batches']),'editableBlocks':sum(b['editable'] for b in manifest['blocks']),
          'preservedBlocks':sum(not b['editable'] for b in manifest['blocks']), 'slides':manifest['slides'],
          'preview':'\n\n'.join(f"[{b['location']}]\n" + (apply_edits(b,state['accepted'][b['id']]) if state['status']=='done' and state['accepted'].get(b['id']) else b['text']) for b in manifest['blocks'])}
    if state['status']=='done':
        return {**base,'status':'done','outputPath':state['outputPath'],'restoredBlocks':state['restored']}
    if state['current']>=len(manifest['batches']):
        return {**base,'status':'ready-to-finalize'}
    ids=manifest['batches'][state['current']]
    batch={'schemaVersion':1,'batchId':str(state['current']+1),'sourceHash':state['sourceHash'],
           'blocks':[public_block(b) for b in manifest['blocks'] if b['id'] in ids]}
    file=job/f"batch-{state['current']+1}.json"
    save(file,batch)
    return {**base,'status':'rewrite','chunk':state['current']+1,'attempt':state['attempt'],
            'inputPath':str(file),'responsePath':str(job/f"response-{state['current']+1}-{state['attempt']}.json"),
            'schemaPath':str(Path(__file__).parent/'response-schema.json'),
            'rulesPath':str(Path(state['vendor'])/'skills/humanize-korean/references/quick-rules.md')}

def accept(job,state,manifest,chunk,attempt,source_hash,response):
    if state['status']!='active' or chunk!=state['current']+1 or attempt!=state['attempt'] or source_hash!=state['sourceHash']:
        raise DocumentError('다른 작업 또는 이전 시도의 응답입니다.')
    if response.stat().st_size>2*1024**2:
        raise DocumentError('모델 응답이 너무 큽니다.')
    value=json.loads(response.read_text(encoding='utf-8-sig'))
    ids=manifest['batches'][state['current']]
    if not isinstance(value,dict) or set(value)!={'schemaVersion','batchId','sourceHash','blocks','warnings'} or type(value.get('schemaVersion')) is not int or value.get('schemaVersion')!=1 or value.get('sourceHash')!=source_hash or value.get('batchId')!=str(chunk):
        raise DocumentError('문서 응답 식별 정보가 다릅니다.')
    items=value.get('blocks')
    if not isinstance(items,list) or any(not isinstance(b,dict) or set(b)!={'id','sourceHash','edits'} for b in items) or [b.get('id') for b in items]!=ids:
        raise DocumentError('응답 블록이 누락·중복되었거나 순서가 다릅니다.')
    warnings=value.get('warnings')
    if not isinstance(warnings,list) or len(warnings)>20 or any(not isinstance(w,str) or len(w)>300 for w in warnings):
        raise DocumentError('경고 응답 형식이 잘못되었습니다.')
    by_id={b['id']:b for b in manifest['blocks']}
    pending={}; failures=[]
    for item in items:
        block=by_id[item['id']]
        if item.get('sourceHash')!=block['sourceHash']:
            raise DocumentError('블록 원문 해시가 다릅니다.')
        try:
            apply_edits(block,item.get('edits'))
            pending[block['id']]=item['edits']
        except DocumentError as exc:
            failures.append((block,str(exc)))
    if failures and attempt==1:
        state['attempt']=2
        state['warnings'] += [f"{b['location']}: 편집 검증 후 재시도합니다 ({reason})" for b,reason in failures]
        decision='retry'
    else:
        state['accepted'].update(pending)
        for b,reason in failures:
            state['accepted'][b['id']]=[]
            state['restored']+=1
            state['warnings'].append(f"{b['location']}: 원문을 유지했습니다 ({reason})")
        state['current']+=1; state['attempt']=1
        decision='rollback' if failures else 'accept'
    state['warnings']=list(dict.fromkeys(state['warnings']+warnings))
    save(job/'job.json',state)
    return {**next_batch(job,state,manifest),'decision':decision}

def dispatch(args,root,vendor):
    if args.command=='prepare':
        return prepare(Path(args.input),root,vendor)
    if not isinstance(args.job,str) or len(args.job)!=36 or not args.job.startswith('job-') or any(c not in '0123456789abcdef' for c in args.job[4:]):
        raise DocumentError('작업 ID가 잘못되었습니다.')
    job=(root/args.job).resolve()
    if job.parent!=root.resolve():
        raise DocumentError('작업 경로가 잘못되었습니다.')
    lock=job/'operation.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(fd)
    try:
        state=json.loads((job/'job.json').read_text(encoding='utf-8'))
        if state['kind']!='document' or state['job']!=args.job:
            raise DocumentError('작업 상태가 잘못되었습니다.')
        if args.command=='cleanup':
            # Deletion performed after the lock is released.
            return {'status':'cleaned','job':args.job}
        raw=job/('original.'+state['format'])
        if digest(raw.read_bytes())!=state['sourceHash'] or digest((job/'document.json').read_bytes())!=state['manifestHash']:
            raise DocumentError('원본 또는 문서 manifest가 변경되었습니다.')
        manifest=json.loads((job/'document.json').read_text(encoding='utf-8'))
        if args.command=='next':
            return next_batch(job,state,manifest)
        if args.command=='accept':
            return accept(job,state,manifest,args.chunk,args.attempt,args.source_hash,Path(args.response))
        if args.command=='finalize':
            output=Path(args.output).resolve()
            if state['status']!='active' or state['current']!=len(manifest['batches']):
                raise DocumentError('모든 블록 검증 후 저장할 수 있습니다.')
            if output.suffix.lower()!='.'+state['format'] or output.exists() or output==Path(state['inputPath']) or output.is_relative_to(job):
                raise DocumentError('원본과 다른 새 출력 경로를 지정해 주세요.')
            temp=output.with_name('.humanize-'+uuid.uuid4().hex+'.'+state['format'])
            try:
                export(Package(raw,state['format']),manifest,state['accepted'],temp)
                # Publish the complete, verified file atomically without overwriting.
                if os.name == 'nt':
                    os.rename(temp, output)  # Windows rename fails if the target exists.
                else:
                    os.link(temp, output)  # Same directory/filesystem, exclusive destination.
            finally:
                temp.unlink(missing_ok=True)
            state.update(status='done',outputPath=str(output))
            save(job/'job.json',state)
            return next_batch(job,state,manifest)
        raise DocumentError('지원하지 않는 문서 명령입니다.')
    finally:
        lock.unlink(missing_ok=True)
        if args.command=='cleanup':
            import shutil
            shutil.rmtree(job)
