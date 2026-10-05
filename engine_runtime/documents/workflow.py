from __future__ import annotations
import json
import os
import re
import shutil
from pathlib import Path
import uuid
from .package import Package, DocumentError, digest
from .model import extract, apply_edits, export, public_block, resolve_edits
from .model import sejong_v2, sejong_flags, sejong_engine, sejong_block_plan, sejong_nominations, sejong_review_limit, sejong_profile
from .model import sejong_env, pin_sejong_env

def save(file, value):
    temp=file.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,separators=(',', ':')),encoding='utf-8')
    temp.replace(file)

def prepare(input_path, root, vendor, job_id=None):
    pin_sejong_env(None)   # a new job reads this process's SUPER_SEJONG_* settings and pins them below
    if job_id is not None and (not isinstance(job_id, str) or not re.fullmatch(r'job-[a-f0-9]{32}', job_id)):
        raise DocumentError('작업 ID가 잘못되었습니다.')
    suffix=input_path.suffix.lower()[1:]
    if suffix not in ('docx','pptx'):
        raise DocumentError('DOCX/PPTX 문서만 지원합니다.')
    pkg=Package(input_path,suffix)
    manifest=extract(pkg)
    if not manifest['batches']:
        raise DocumentError('윤문 가능한 텍스트가 없습니다. 보호 구조만 있는 문서는 원본을 유지해 주세요.')
    job=root/(job_id or 'job-'+uuid.uuid4().hex)
    job.mkdir(parents=True)
    try:
        (job/('original.'+suffix)).write_bytes(pkg.raw)
        save(job/'document.json',manifest)
        state={'schemaVersion':2,'kind':'document','job':job.name,'format':suffix,'inputPath':str(input_path.resolve()),
               'name':input_path.stem+'-humanized.'+suffix,'vendor':str(vendor.resolve()),'current':0,'attempt':1,
               'sourceHash':pkg.hash,'manifestHash':digest((job/'document.json').read_bytes()),
               'status':'active','accepted':{},'warnings':manifest['warnings'],'restored':0}
        if sejong_v2():
            state['engine']=sejong_engine()  # id+version; a later change of engine or version fails the job
            state['sejongEnv']=sejong_env()  # SUPER_SEJONG_* flags; every later call of the job uses these
        save(job/'job.json',state)
        return next_batch(job,state,manifest)
    except Exception:
        if job.resolve().parent==root.resolve() and re.fullmatch(r'job-[a-f0-9]{32}',job.name):
            shutil.rmtree(job)
        raise

def v2_batch(job,state,manifest):
    """Super Sejong v2 view of the current batch: one compact plan per block, only the blocks the writer is
    asked about, and the retry data on attempt 2.

    A block is asked about when its plan has a request or an open review can nominate one of its sentences
    (SUPER_SEJONG_OPEN_REVIEW). When no block of a batch is, the batch is accepted unchanged without a model
    call and the next one is looked at (DESIGN 3.4: an empty plan makes no call); `state['current']` moves
    and job.json is saved. Attempt 2 asks only the blocks the first answer failed, with their rejection
    (`state['retry']`); the edits of the blocks that passed wait in `state['carry']`.
    `state['active']` records which block ids this answer must review. Returns None when no batch is left,
    else (ids, blocks for the batch file, the batch's `sejong` object)."""
    flags=sejong_flags()
    by_id={b['id']:b for b in manifest['blocks']}
    changed=False
    result=None
    while state['current']<len(manifest['batches']):
        all_ids=manifest['batches'][state['current']]
        retry=state.get('retry') if state['attempt']==2 else None
        wanted=[i for i in all_ids if i in retry] if retry else all_ids
        plans={i:sejong_block_plan(by_id[i],flags) for i in wanted}
        ids=wanted if retry else [i for i in wanted if plans[i]['needsModel']]
        if ids:
            # The open review covers every asked block on attempt 1; on the retry only blocks without a request
            # (their failed edit was a nomination), because the retry adds no new requests.
            nominable=sum(plans[i]['nominable'] for i in ids if not retry or not plans[i]['requests'])
            cap=sejong_review_limit(nominable) if nominable else 0
            asked={i:[r['sentence'] for r in plans[i]['requests']] for i in ids}   # the sentences the writer is told to fix
            active={'chunk':state['current']+1,'attempt':state['attempt'],'ids':ids,'review':cap,'asked':asked}
            if state.get('active')!=active:
                state['active']=active;changed=True
            sejong={'version':1,'engine':state.get('engine') or sejong_engine(),'genre':'document','attempt':state['attempt'],
                    'review':{'enabled':cap>0,'maxSentences':cap}}
            if retry:
                sejong['retry']=[{'block':i,'message':retry[i]['message'],'violations':retry[i]['violations']} for i in ids]
            else:
                sejong['profile']=sejong_profile([by_id[i]['text'] for i in ids])
            result=(ids,[{**public_block(by_id[i]),'plan':{'requests':plans[i]['requests']}} for i in ids],sejong)
            break
        state['current']+=1;state['attempt']=1;state.pop('active',None);changed=True
        notice='SEJONG_NO_EDIT_NEEDED: 고칠 곳을 찾지 못한 구간은 모델을 호출하지 않고 원문을 유지했습니다.'
        if notice not in state['warnings']:
            state['warnings'].append(notice)
    if result is None and state.pop('active',None) is not None:
        changed=True
    if changed:
        save(job/'job.json',state)
    return result

def next_batch(job,state,manifest):
    output_chars = manifest['sourceChars'] + sum(
        len(edit['after']) - len(edit['before'])
        for edits in state['accepted'].values() for edit in edits
    )
    base={'job':job.name,'kind':'document','format':state['format'],'name':state['name'],
          'sourceHash':state['sourceHash'],'warnings':state['warnings'], 'sourceChars':manifest['sourceChars'],
          'outputChars':output_chars,
          'totalChunks':len(manifest['batches']),'editableBlocks':sum(b['editable'] for b in manifest['blocks']),
          'preservedBlocks':sum(not b['editable'] for b in manifest['blocks']), 'slides':manifest['slides']}
    # The preview can be ~100k chars; it goes last so a host that truncates long
    # output still sees the status and paths first.
    preview={'preview':'\n\n'.join(f"[{b['location']}]\n" + (apply_edits(b,state['accepted'][b['id']]) if state['status']=='done' and state['accepted'].get(b['id']) else b['text']) for b in manifest['blocks'])}
    if state['status']=='done':
        return {'status':'done','outputPath':state['outputPath'],'restoredBlocks':state['restored'],**base,**preview}
    plan=v2_batch(job,state,manifest) if sejong_v2() else None
    if state['current']>=len(manifest['batches']):
        return {'status':'ready-to-finalize',**base,**preview}
    if plan:
        ids,blocks,sejong=plan
        batch={'schemaVersion':1,'batchId':str(state['current']+1),'sourceHash':state['sourceHash'],'blocks':blocks,'sejong':sejong}
        file=job/f"batch-{state['current']+1}.json"
        save(file,batch)
        # v2 sends no rulebook: there is no rulesPath, the plan travels in the batch itself.
        return {'status':'rewrite','chunk':state['current']+1,'attempt':state['attempt'],
                'inputPath':str(file),'responsePath':str(job/f"response-{state['current']+1}-{state['attempt']}.json"),
                'schemaPath':str(Path(__file__).parent/'response-schema.json'),**base,**preview}
    ids=manifest['batches'][state['current']]
    batch={'schemaVersion':1,'batchId':str(state['current']+1),'sourceHash':state['sourceHash'],
           'blocks':[public_block(b) for b in manifest['blocks'] if b['id'] in ids]}
    file=job/f"batch-{state['current']+1}.json"
    save(file,batch)
    return {'status':'rewrite','chunk':state['current']+1,'attempt':state['attempt'],
            'inputPath':str(file),'responsePath':str(job/f"response-{state['current']+1}-{state['attempt']}.json"),
            'schemaPath':str(Path(__file__).parent/'response-schema.json'),
            'rulesPath':str(Path(state['vendor'])/'skills/humanize-korean/references/quick-rules.md'),**base,**preview}

def accept(job,state,manifest,chunk,attempt,source_hash,response):
    if state['status']!='active' or chunk!=state['current']+1 or attempt!=state['attempt'] or source_hash!=state['sourceHash']:
        raise DocumentError('다른 작업 또는 이전 시도의 응답입니다.')
    if response.stat().st_size>2*1024**2:
        raise DocumentError('모델 응답이 너무 큽니다.')
    value=json.loads(response.read_text(encoding='utf-8-sig'))
    v2=sejong_v2()
    if v2:
        # v2 asks only the blocks that need the writer (and, on attempt 2, only the failed ones): v2_batch recorded which.
        active=state.get('active')
        if not isinstance(active,dict) or active.get('chunk')!=chunk or active.get('attempt')!=attempt:
            raise DocumentError('다른 작업 또는 이전 시도의 응답입니다.')
        ids=active['ids']
    else:
        ids=manifest['batches'][state['current']]
    if not isinstance(value,dict):
        raise DocumentError('문서 응답 형식이 잘못되었습니다.')
    version=value.get('schemaVersion')
    expected={'schemaVersion','batchId','sourceHash','blocks','warnings'}
    if version==2: expected.add('reviewedIds')
    if set(value)!=expected or type(version) is not int or version not in (1,2) or value.get('sourceHash')!=source_hash or value.get('batchId')!=str(chunk):
        raise DocumentError('문서 응답 식별 정보가 다릅니다.')
    items=value.get('blocks')
    if not isinstance(items,list) or any(not isinstance(b,dict) or set(b)!={'id','sourceHash','edits'} or not isinstance(b.get('id'),str) for b in items):
        raise DocumentError('응답 블록이 누락·중복되었거나 순서가 다릅니다.')
    item_ids=[b['id'] for b in items]
    if version==1:
        valid_ids=item_ids==ids
    else:
        # An omitted block is unchanged ONLY after explicit review of the whole batch.
        valid_ids=value.get('reviewedIds')==ids and len(set(item_ids))==len(item_ids) and item_ids==[id for id in ids if id in item_ids]
    if not valid_ids:
        raise DocumentError('검토 ID가 누락·중복되었거나 순서가 다릅니다.')
    warnings=value.get('warnings')
    if not isinstance(warnings,list) or any(not isinstance(w,str) for w in warnings):
        raise DocumentError('경고 응답 형식이 잘못되었습니다.')
    # Model text is untrusted document content and must not become a public warning.
    warnings=['모델이 검토 주의 사항을 제시했습니다. 원문과 결과를 확인해 주세요.'] if warnings else []
    by_id={b['id']:b for b in manifest['blocks']}
    pending={id:[] for id in ids if id not in item_ids}; failures=[]; named={}; dropped=[]
    budget=active['review'] if v2 else 0
    for item in items:
        block=by_id[item['id']]
        if item.get('sourceHash')!=block['sourceHash']:
            raise DocumentError('블록 원문 해시가 다릅니다.')
        try:
            edits=resolve_edits(block,item.get('edits')) if version==2 else item.get('edits')
            if v2 and edits:
                # v2: only the requested sentences may change, plus at most `review` others when the plan allows
                # an open review. Edit by edit, in reply order, an edit that would nominate more sentences than
                # the budget left is dropped without a retry; the block's other edits (the requested fixes among
                # them) are kept (code review 2026-10-05: the whole block used to be dropped).
                asked=active['asked'].get(block['id'],()); kept=[]; seen=set(); over=False
                for edit in edits:
                    new=set(sejong_nominations(block,[edit],asked))-seen
                    if len(new)>budget:
                        over=True
                        continue
                    budget-=len(new); seen|=new; kept.append(edit)
                if over:
                    dropped.append((block,'열린 검토 한도를 넘어 요청하지 않은 문장을 수정했습니다' if active['review'] else '요청하지 않은 문장을 수정했습니다'))
                edits=kept
            apply_edits(block,edits)
            pending[block['id']]=edits
        except DocumentError as exc:
            failures.append((block,str(exc)))
            named[block['id']]=exc
    for reason in dict.fromkeys(r for _,r in dropped):
        same=[b for b,r in dropped if r==reason]
        state['restored']+=len(same)
        # one notice per reason, so a long document does not flood the review list
        state['warnings'].append(f"{same[0]['location']}{' 등 %d개 블록' % len(same) if len(same)>1 else ''}: 일부 문장은 원문을 유지했습니다 ({reason})")
    if failures and attempt==1:
        state['attempt']=2
        state['warnings'] += [f"{b['location']}: 편집 검증 후 재시도합니다 ({reason})" for b,reason in failures]
        if v2:
            # Only the failed blocks go back to the writer, each with its named violations; the blocks that
            # passed keep their verified edits.
            state['carry']={i:e for i,e in pending.items() if e}
            state['retry']={b['id']:{'message':reason,'violations':list(getattr(named[b['id']],'violations',[]))} for b,reason in failures}
        decision='retry'
    else:
        if v2:
            state['accepted'].update(state.pop('carry',{}))
            state.pop('retry',None); state.pop('active',None)
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
        return prepare(Path(args.input),root,vendor,getattr(args,'job_id',None))
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
        if bool(state.get('engine'))!=sejong_v2() or (state.get('engine') and state['engine']!=sejong_engine()):
            raise DocumentError('작업을 시작한 윤문 엔진과 현재 설정이 다릅니다. 문서를 다시 선택해 주세요.')
        pin_sejong_env(state.get('sejongEnv', {}) if state.get('engine') else None)
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
        pin_sejong_env(None)   # the pin belongs to this call's job only
        lock.unlink(missing_ok=True)
        if args.command=='cleanup':
            import shutil
            shutil.rmtree(job)
