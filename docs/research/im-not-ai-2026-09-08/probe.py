"""Read-only source audit and deterministic counterexamples; no LLM calls.

Usage: python probe.py --source C:/project/2026/im-not-ai --work <scratch-dir>
Writes inventory.json and probes.json beside this file, scratch runs under --work.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import random
import re
import subprocess
import sys
from unittest.mock import patch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--work', type=Path, required=True)
    args = ap.parse_args()
    source = args.source.resolve()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    dest = Path(__file__).resolve().parent
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source / 'scripts'))
    sys.path.insert(0, str(source / 'skills/humanize-korean/references'))
    sys.path.insert(0, str(source / 'tests'))
    import build_quick_rules as builder
    import metrics_v2 as metrics
    import prepare_monolith_input as shim
    import checks
    import verify_gates as gates
    import restore_modality as modality
    import strip_injected_commas as commas
    import sanitize_text
    import corruption_engine
    import eval_baseline
    import humanize_asserts
    import reassemble_chunks

    def git(*a):
        return subprocess.check_output(['git', '-C', str(source), *a], encoding='utf-8').strip()

    files = git('ls-files').splitlines()
    records = []
    for name in files:
        p = source / name
        data = p.read_bytes()
        record = {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if p.suffix == '.png':
            record.update(kind='image', width=int.from_bytes(data[16:20], 'big'), height=int.from_bytes(data[20:24], 'big'))
        else:
            text = data.decode('utf-8')
            record.update(kind='text', lines=len(text.splitlines()))
            if p.suffix == '.py':
                tree = ast.parse(text)
                record['module_doc'] = ast.get_docstring(tree)
                record['symbols'] = [{'name': n.name, 'line': n.lineno,
                                      'end': n.end_lineno, 'doc': ast.get_docstring(n)}
                                     for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))]
                record['imports'] = sorted({n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} |
                                           {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names})
            elif p.suffix == '.json':
                obj = json.loads(text)
                record['json_keys'] = list(obj) if isinstance(obj, dict) else ['array']
                if isinstance(obj, dict) and 'records' in obj:
                    record['snapshot_records'] = len(obj['records'])
                    record['null_signal_values'] = sum(v is None for r in obj['records'] for k, v in r.get('metrics', {}).items() if k.startswith('sig_'))
            else:
                record['headings'] = [{'line': i, 'text': line} for i, line in enumerate(text.splitlines(), 1) if re.match(r'^#{1,6} ', line)]
        records.append(record)
    taxonomy = (source / 'skills/humanize-korean/references/ai-tell-taxonomy.md').read_text(encoding='utf-8')
    parsed = builder.parse_taxonomy(taxonomy)
    all_ids = re.findall(r'^#{2,3} ([A-J]-\d+)\.', taxonomy, re.M)
    inventory = {'source': str(source), 'commit': git('rev-parse', 'HEAD'),
                 'tracked_files': len(files), 'python_files': sum(x.endswith('.py') for x in files),
                 'text_files': sum(r['kind'] == 'text' for r in records),
                 'text_lines': sum(r.get('lines', 0) for r in records),
                 'written_pattern_ids': all_ids, 'generated_pattern_count': len(parsed),
                 'generated_by_category': dict(Counter(p['category'] for p in parsed)),
                 'quick_count': sum(p['quick'] is True for p in parsed),
                 'patterns': parsed, 'files': records}
    (dest / 'inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    def quiet(fn, *a, **kw):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            value = fn(*a, **kw)
        return value, output.getvalue()

    def gate_case(name, before, after):
        folder = work / name
        folder.mkdir(exist_ok=True)
        (folder / 'before.txt').write_text(before, encoding='utf-8')
        (folder / 'after.txt').write_text(after, encoding='utf-8')
        code, log = quiet(gates.main, ['--before', str(folder/'before.txt'), '--after', str(folder/'after.txt'), '--json'])
        return {'before': before, 'after': after, 'exit_code': code,
                'change_rate': metrics.change_rate(before, after),
                'failures': [f.code for f in checks.run_checks(before, after)],
                'dropped_numbers': checks.dropped_numbers(before, after), 'log': log}

    probes = {}
    probes['missing_rule'] = {'written': len(all_ids), 'parsed': len(parsed),
                             'missing': sorted(set(all_ids)-{p['id'] for p in parsed})}
    probes['overlapping_lexicon'] = {s: metrics.double_passive_count(s) for s in ['판단되어진다.', '보여진다.', '잊혀진다.']}
    probes['number_association_swap'] = gate_case('number-swap', '서울은 10명이고 부산은 20명이다.', '서울은 20명이고 부산은 10명이다.')
    probes['number_deletion'] = gate_case('number-deletion', '참여 인원은 20명이었다. 조사 결과는 보고서에 기록했다.', '참여 인원은 여러 명이었다. 조사 결과는 보고서에 기록했다.')
    probes['polarity_flip'] = gate_case('polarity-flip', '이 제품은 안전하다.', '이 제품은 안전하지 않다.')
    probes['short_quote'] = gate_case('short-quote', '그는 "승인한다"고 말했다.', '그는 "거절한다"고 말했다.')
    probes['restore_example'] = {'before': '성장률은 낮은 것으로 판단된다.', 'candidate': '성장률은 낮은 수치다.'}
    fixed, restored, skipped = modality.restore(probes['restore_example']['before'], probes['restore_example']['candidate'])
    probes['restore_example'].update(result=fixed, restored=len(restored), skipped=len(skipped))
    fixed, report = commas.strip_injected('문서를 읽었다. 결과를 정리했다.', '문서를 읽고, 결과를 정리했다.')
    probes['comma_example'] = {'result': fixed, **report}
    fixed, report = sanitize_text.sanitize('\u1112\u1161\u11ab\u200b글\u00a0문장\r\n')
    probes['sanitize_example'] = {'result': fixed, 'report': report.to_dict()}

    route_text = '핵심은 실행에 있다. 중요한 것은 검증이다. 필요한 것은 자료이다. 과제도 남아 있다.'
    route_dir = work / 'route'
    route_dir.mkdir(exist_ok=True)
    (route_dir/'01_input.txt').write_text(route_text, encoding='utf-8')
    quiet(shim.main, ['--run-dir', str(route_dir)])
    normal = json.loads((route_dir/'00_metrics.json').read_text(encoding='utf-8'))
    quiet(shim.main, ['--run-dir', str(route_dir), '--chunk'])
    manifest = json.loads((route_dir/'chunk_manifest.json').read_text(encoding='utf-8'))
    probes['route_mode_difference'] = {'text': route_text, 'normal': normal['route_hint'],
                                      'normal_signals': normal['route_signals'], 'chunk': manifest['route_hint']}
    with patch.object(shim._metrics_mod, 'compute_all', side_effect=ValueError('intentional research failure')):
        _, log = quiet(shim.main, ['--run-dir', str(route_dir)])
    probes['stale_metrics_on_failure'] = {'log': log, 'old_json_survives': (route_dir/'00_metrics.json').exists(),
                                        'error_exists': (route_dir/'00_metrics.error').exists(),
                                        'combined_contains_metrics': '[정량 사전 점수' in (route_dir/'01_input_with_metrics.txt').read_text(encoding='utf-8')}

    probes['baseline_signals'] = {name: eval_baseline._safe_signal('판단되어진다. AI에 의해 생성되었다.', name) for name in eval_baseline.SIGNAL_NAMES}
    v2 = metrics.compute_all('오늘은 산책했다. 집에 돌아와 밥을 먹었다.')
    probes['placeholder_scores'] = {'warning_count': len(v2['v2_baseline_warnings']),
                                    'nonnull_scores': sum(v is not None for v in v2['v2_z_scores'].values())}
    b, a = '가나다라마바사. '*100, '수정. '+'가나다라마바사. '*100
    probes['change_rate_implementations'] = {'case': 'repetitive 900-char source with short prefix insertion',
                                           'runtime': metrics.change_rate(b, a), 'test_helper': humanize_asserts.change_rate(b, a)}
    corrupt_src = '문제가 심해졌다.'
    corrupt_out = corruption_engine._inj_progressive_passive(corrupt_src, random.Random(7))
    probes['corruption_tense'] = {'clean': corrupt_src, 'corrupted': corrupt_out,
                                 'checks': [f.code for f in checks.run_checks(corrupt_src, corrupt_out)]}

    chunk_dir = work/'summary-reassembly'
    chunk_dir.mkdir(exist_ok=True)
    body = '# 첫 절\n첫 문단을 기록했다.\n\n# 다음 절\n다음 문단을 기록했다.\n'
    (chunk_dir/'01_input.txt').write_text(body, encoding='utf-8')
    quiet(shim.main, ['--run-dir', str(chunk_dir), '--chunk'])
    mf = json.loads((chunk_dir/'chunk_manifest.json').read_text(encoding='utf-8'))
    for c in mf['chunks']:
        if not c['passthrough']:
            text = body[c['start']:c['end']].strip()+'\n<!-- HUMANIZE-SUMMARY grade: A -->'
            (chunk_dir/c['rewritten_file']).write_text(text, encoding='utf-8')
    quiet(reassemble_chunks.main, ['--run-dir', str(chunk_dir)])
    joined = (chunk_dir/'03_reassembled.md').read_text(encoding='utf-8')
    probes['per_chunk_summary_contract'] = {'scenario': 'simulated chunk responses each contain monolith summary',
                                          'chunks': mf['body_chunk_count'], 'reassembled': joined,
                                          'gate_visible_body': gates.strip_summary_block(joined)}
    spans, warnings = shim.compute_chunk_spans('가'*10000)
    probes['chunk_limit_is_soft'] = {'sizes': [s['end']-s['start'] for s in spans], 'warnings': warnings}
    probes['source_status_after'] = git('status', '--porcelain')
    (dest/'probes.json').write_text(json.dumps(probes, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in inventory.items() if k in ['tracked_files','text_files','python_files','text_lines','generated_by_category','generated_pattern_count','quick_count']}, ensure_ascii=False))
    for k, v in probes.items():
        if isinstance(v, dict):
            v = {key: value for key, value in v.items() if key not in ['log','reassembled','before','after','text']}
        print(k, json.dumps(v, ensure_ascii=False))


if __name__ == '__main__':
    main()
