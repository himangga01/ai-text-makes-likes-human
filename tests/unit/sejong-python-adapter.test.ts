import { readFileSync } from 'node:fs';
import { copyFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { CommandResult } from '../../src/process/command-runner.js';
import { EngineError } from '../../src/engine/errors.js';
import {
  checkProblems, gatePolicy, gateResultOf, parseSejongManifest, planProblems, SchemaError, SejongPython, validateSchema,
  type AnalyseArgs, type CheckArgs, type JsonSchema
} from '../../src/engine/sejong/python-adapter.js';
import type { CheckReport, Plan } from '../../src/engine/sejong/types.js';
import { exited, FakeCommandRunner } from '../helpers/fake-command-runner.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';

const root = path.resolve('.');
const engineRoot = path.join(root, 'engine_runtime');
const fixture = (name: string): string => path.join(root, 'tests/fixtures/sejong', name);
const json = <T>(file: string): T => JSON.parse(readFileSync(file, 'utf8')) as T;
const schemas = {
  plan: json<JsonSchema>(path.join(engineRoot, 'sejong/schemas/plan.schema.json')),
  check: json<JsonSchema>(path.join(engineRoot, 'sejong/schemas/check.schema.json'))
};
const signal = new AbortController().signal;
const ended = (termination: CommandResult['termination']): CommandResult => ({ exitCode: -1, stdout: '', stderr: '', termination });

async function rejection(promise: Promise<unknown>): Promise<EngineError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(EngineError);
    return error as EngineError;
  }
  throw new Error('expected a rejection');
}

let dir = '';
beforeEach(async () => { dir = await makeTestRoot('sejong-adapter-'); });
afterEach(async () => { await removeTestRoot(dir); });

function adapter(results: Array<CommandResult | Error>, options: Partial<ConstructorParameters<typeof SejongPython>[0]> = {}) {
  const runner = new FakeCommandRunner(results);
  return { runner, python: new SejongPython({ pythonCommand: 'python3', engineRoot, runner, env: { KEEP: '1' }, ...options }) };
}

const analyseArgs = (overrides: Partial<AnalyseArgs> = {}): AnalyseArgs => ({
  source: path.join(dir, 'chunk.txt'), context: path.join(dir, '01_input.txt'), chunkIndex: 1, chunkTotal: 1,
  inputKind: 'direct-text', strength: 'medium', genre: 'blog', out: path.join(dir, 'plan.json'), ...overrides
});
const checkArgs = (overrides: Partial<CheckArgs> = {}): CheckArgs => ({
  plan: path.join(dir, 'plan.json'), source: path.join(dir, 'chunk.txt'), response: path.join(dir, 'r.json'),
  attempt: 1, out: path.join(dir, 'decided.txt'), report: path.join(dir, 'check.json'), ...overrides
});

describe('SejongPython.analyse', () => {
  it('spawns the CLI with the documented arguments and returns the plan', async () => {
    await copyFile(fixture('plan-blog-medium.json'), path.join(dir, 'plan.json'));
    const { runner, python } = adapter([exited('')]);
    const plan = await python.analyse(analyseArgs(), signal);
    expect(plan).toEqual(json<Plan>(fixture('plan-blog-medium.json')));
    expect(runner.calls).toHaveLength(1);
    const call = runner.calls[0]!;
    expect(call.command).toBe('python3');
    expect(call.args).toEqual([path.join(engineRoot, 'sejong_cli.py'), 'analyse',
      '--source', path.join(dir, 'chunk.txt'), '--context', path.join(dir, '01_input.txt'),
      '--chunk-index', '1', '--chunk-total', '1', '--input-kind', 'direct-text', '--strength', 'medium', '--genre', 'blog',
      '--out', path.join(dir, 'plan.json')]);
    expect(call.cwd).toBe(dir);
    expect(call.env).toEqual({ KEEP: '1', PYTHONDONTWRITEBYTECODE: '1', PYTHONUTF8: '1' });
    expect(call.maxOutputBytes).toBe(1024 * 1024);
    expect(call.timeoutMs).toBe(120_000);
    expect(call.signal).toBe(signal);
  });

  it('parses the empty plan, which needs no model call', async () => {
    await copyFile(fixture('plan-no-edit.json'), path.join(dir, 'plan.json'));
    const { runner, python } = adapter([exited('')]);
    const plan = await python.analyse(analyseArgs({ context: undefined, inputKind: 'text-file', strength: 'normal', genre: 'general' }), signal);
    expect([plan.needsModel, plan.requests, plan.openReview]).toEqual([false, [], { enabled: false, maxSentences: 0 }]);
    expect(runner.calls[0]!.args).not.toContain('--context');
  });

  it('rejects a plan for another chunk or other options', async () => {
    await copyFile(fixture('plan-blog-medium.json'), path.join(dir, 'plan.json'));
    for (const overrides of [{ strength: 'strong' as const }, { genre: 'general' as const }, { inputKind: 'text-file' as const },
      { chunkIndex: 1, chunkTotal: 2 }]) {
      const { python } = adapter([exited('')]);
      expect((await rejection(python.analyse(analyseArgs(overrides), signal))).message).toContain('does not match');
    }
    const { python } = adapter([]);
    await expect(python.analyse(analyseArgs({ chunkIndex: 3, chunkTotal: 2 }), signal)).rejects.toThrow('within 1..total');
  });

  it('rejects an invalid plan with paths only, never document text', async () => {
    const plan = json<Plan>(fixture('plan-blog-medium.json'));
    plan.needsModel = false;
    plan.profile.line = '비밀 문장';
    plan.sentences[0]!.voice.final = 'x'.repeat(201);
    await writeFile(path.join(dir, 'plan.json'), JSON.stringify(plan));
    const { python } = adapter([exited('')]);
    const error = await rejection(python.analyse(analyseArgs(), signal));
    expect(error.publicCode).toBe('ENGINE_OUTPUT_INVALID');
    expect(error.message).toContain('$.sentences[0].voice.final: maxLength');
    expect(error.message).not.toMatch(/비밀|xxxx/u);
  });

  it('maps exit codes, terminations and unreadable output', async () => {
    const cases: Array<[CommandResult, string, string]> = [
      [exited('', 1), 'ENGINE_OUTPUT_INVALID', 'analyse step failed'],
      [exited('', 2), 'ENGINE_OUTPUT_INVALID', 'unexpected code'],
      [ended('timeout'), 'ENGINE_TIMEOUT', 'timed out'],
      [ended('aborted'), 'CLIENT_ABORTED', 'cancelled'],
      [ended('output-limit'), 'ENGINE_OUTPUT_INVALID', 'exceeded the limit']
    ];
    for (const [result, code, message] of cases) {
      const { python } = adapter([result]);
      const error = await rejection(python.analyse(analyseArgs(), signal));
      expect([error.publicCode, error.message.includes(message)]).toEqual([code, true]);
    }
    const { python: missing } = adapter([exited('')]);
    expect((await rejection(missing.analyse(analyseArgs(), signal))).message).toContain('Unable to read Sejong plan');
    await writeFile(path.join(dir, 'plan.json'), '{not json');
    const { python: broken } = adapter([exited('')]);
    expect((await rejection(broken.analyse(analyseArgs(), signal))).message).toContain('not JSON');
  });

  it('bounds the size of the plan file', async () => {
    await copyFile(fixture('plan-blog-medium.json'), path.join(dir, 'plan.json'));
    const size = readFileSync(path.join(dir, 'plan.json')).length;
    const { python } = adapter([exited('')], { maxReportBytes: size - 1 });
    expect((await rejection(python.analyse(analyseArgs(), signal))).message).toContain(`exceeds ${size - 1} bytes`);
    // The schema files are read under the same bound.
    const { python: exact } = adapter([exited('')], { maxReportBytes: 64 * 1024 });
    await expect(exact.analyse(analyseArgs(), signal)).resolves.toMatchObject({ schema: 'sejong-plan/1' });
  });
});

describe('SejongPython.check', () => {
  const cases: Array<[string, 0 | 1 | 2, 1 | 2]> = [['check-accept.json', 0, 1], ['check-retry.json', 1, 1], ['check-rollback.json', 2, 2]];

  it('returns each fixture report when the exit code matches gate.exit_code', async () => {
    for (const [name, exitCode, attempt] of cases) {
      await copyFile(fixture(name), path.join(dir, 'check.json'));
      const { runner, python } = adapter([exited('', exitCode)]);
      const args = checkArgs({ attempt, ...(attempt === 2 ? { base: path.join(dir, 'decided-1.txt') } : {}) });
      expect(await python.check(args, signal)).toEqual(json<CheckReport>(fixture(name)));
      expect(runner.calls[0]!.args).toEqual([path.join(engineRoot, 'sejong_cli.py'), 'check',
        '--plan', path.join(dir, 'plan.json'), '--source', path.join(dir, 'chunk.txt'), '--response', path.join(dir, 'r.json'),
        '--attempt', String(attempt), ...(attempt === 2 ? ['--base', path.join(dir, 'decided-1.txt')] : []),
        '--out', path.join(dir, 'decided.txt'), '--report', path.join(dir, 'check.json')]);
    }
  });

  it('treats a check that exits 1 without writing its report as an execution error', async () => {
    const { python } = adapter([exited('', 1)]);
    expect(await rejection(python.check(checkArgs({ report: path.join(dir, 'missing-report.json') }), signal)))
      .toMatchObject({ publicCode: 'VALIDATION_FAILED' });
  });

  it('maps a check report to the legacy gate result', () => {
    const expected = [
      { status: 'ok', exitCode: 0, gateCodes: ['GATE_OK'], policy: 'accept', hardFailures: [], shadowFailures: ['clarity_longer_sentence'] },
      { status: 'warn', exitCode: 1, gateCodes: ['GATE_WARN'], policy: 'retry', hardFailures: [], shadowFailures: [] },
      { status: 'abort', exitCode: 2, gateCodes: ['GATE_ABORT'], policy: 'rollback', hardFailures: ['quote_altered'], shadowFailures: [] }
    ];
    cases.forEach(([name], index) => expect(gateResultOf(json<CheckReport>(fixture(name)))).toMatchObject(expected[index]!));
    expect(gateResultOf(json<CheckReport>(fixture('check-rollback.json'))).warningReasons).toEqual({ version: 1, codes: ['P0_CHANGE_RATE'] });
    for (const exit of [0, 1, 2, 3] as const) for (const attempt of [1, 2] as const) {
      expect(gatePolicy(exit, attempt)).toBe([['accept', 'accept'], ['retry', 'accept-with-warning'], ['retry', 'rollback'], ['error', 'error']][exit]![attempt - 1]);
    }
  });

  it('uses the candidate path instead of a response when given', async () => {
    await copyFile(fixture('check-accept.json'), path.join(dir, 'check.json'));
    const { runner, python } = adapter([exited('', 0)]);
    await python.check(checkArgs({ response: undefined, candidate: path.join(dir, 'c.txt') }), signal);
    expect(runner.calls[0]!.args).toContain('--candidate');
    expect(runner.calls[0]!.args).not.toContain('--response');
    const { python: none } = adapter([]);
    await expect(none.check(checkArgs({ candidate: path.join(dir, 'c.txt') }), signal)).rejects.toThrow('exactly one');
    await expect(none.check(checkArgs({ attempt: 2 }), signal)).rejects.toThrow('decided text of attempt 1');
  });

  it('fails closed on mismatched or inconsistent reports', async () => {
    await copyFile(fixture('check-retry.json'), path.join(dir, 'check.json'));
    const { python } = adapter([exited('', 0)]);
    expect((await rejection(python.check(checkArgs(), signal))).message).toBe('Gate report exit code mismatch');
    await copyFile(fixture('check-accept.json'), path.join(dir, 'check.json'));
    const { python: other } = adapter([exited('', 0)]);
    expect((await rejection(other.check(checkArgs({ attempt: 2, base: path.join(dir, 'b.txt') }), signal))).message).toContain('another attempt');
    const report = json<CheckReport>(fixture('check-retry.json'));
    report.policy = 'accept';
    await writeFile(path.join(dir, 'check.json'), JSON.stringify(report));
    const { python: policy } = adapter([exited('', 1)]);
    expect((await rejection(policy.check(checkArgs(), signal))).message).toContain('legacy decision table');
    const { python: odd } = adapter([exited('', 4)]);
    expect((await rejection(odd.check(checkArgs(), signal))).message).toBe('Unexpected Sejong check exit code');
  });

  it('turns exit 3 into the execution error the legacy engine raises', async () => {
    const { python } = adapter([exited('{"gate":{"exit_code":3},"hardFailures":[],"policy":"error"}', 3)]);
    const error = await rejection(python.check(checkArgs(), signal));
    expect([error.publicCode, error.retryable]).toEqual(['VALIDATION_FAILED', false]);
  });
});

describe('SejongPython.verifyDocument', () => {
  const gate = (exitCode: number, extra: Record<string, unknown> = {}): string =>
    `[floor] PASS\n${JSON.stringify({ gate: { exit_code: exitCode }, hardFailures: [], warningReasons: { version: 1, codes: [] },
      policy: gatePolicy(exitCode as 0, 1), shadowFailures: ['flow_sentence_added', 'NOT_A_CODE'], ...extra }, null, 2)}\n`;

  it('parses the legacy gate JSON from stdout like PythonEngine.verify()', async () => {
    const { runner, python } = adapter([exited(gate(1), 1)]);
    const result = await python.verifyDocument(path.join(dir, 'before.txt'), path.join(dir, 'after.txt'), signal, 1, path.join(dir, 'ctx.txt'));
    expect(result).toEqual({ status: 'warn', exitCode: 1, gateCodes: ['GATE_WARN'], warningReasons: { version: 1, codes: [] },
      hardFailures: [], policy: 'retry' });
    expect(runner.calls[0]!.args).toEqual([path.join(engineRoot, 'sejong_cli.py'), 'verify', '--before', path.join(dir, 'before.txt'),
      '--after', path.join(dir, 'after.txt'), '--context', path.join(dir, 'ctx.txt'), '--attempt', '1']);
    const { python: clean } = adapter([exited(gate(0, { shadowFailures: ['flow_sentence_added'] }), 0)]);
    expect(await clean.verifyDocument('a', 'b', signal)).toMatchObject({ status: 'ok', shadowFailures: ['flow_sentence_added'] });
    const { python: failed } = adapter([exited(gate(3), 3)]);
    expect(await failed.verifyDocument('a', 'b', signal)).toMatchObject({ status: 'error', exitCode: 3, gateCodes: ['GATE_ERROR'] });
  });

  it('rejects mismatched exit codes and policies', async () => {
    const { python } = adapter([exited(gate(0), 1)]);
    expect((await rejection(python.verifyDocument('a', 'b', signal))).message).toBe('Gate report exit code mismatch');
    const { python: policy } = adapter([exited(gate(1, { policy: 'accept' }), 1)]);
    expect((await rejection(policy.verifyDocument('a', 'b', signal))).message).toContain('legacy decision table');
    const { python: none } = adapter([exited('no json', 0)]);
    expect((await rejection(none.verifyDocument('a', 'b', signal))).message).toContain('Unable to parse gate JSON');
    // a crash before main() (exit 1, a traceback, no JSON) is an execution error, not invalid output
    const { python: crash } = adapter([exited('Traceback (most recent call last):', 1)]);
    expect(await rejection(crash.verifyDocument('a', 'b', signal))).toMatchObject({ publicCode: 'VALIDATION_FAILED' });
    const { python: odd } = adapter([exited(gate(0), 9)]);
    expect((await rejection(odd.verifyDocument('a', 'b', signal))).message).toBe('Unexpected gate exit code');
  });
});

describe('SejongPython.prepare and finalize', () => {
  const manifest = (extra: Record<string, unknown> = {}) => ({
    version: 1, source_file: '01_input.txt', source_chars: 15, source_sha256: 'abc', chunk_count: 2, body_chunk_count: 2,
    passthrough_chunk_count: 0, route_hint: null, route_reason: 'sejong:chunked', processing_mode: 'chunked', warnings: [],
    chunks: [
      { index: 1, start: 0, end: 10, char_count: 10, starts_with_heading: false, heading: null, passthrough: false,
        input_file: '01_chunk_01_input.txt', rewritten_file: '02_chunk_01_rewritten.txt' },
      { index: 2, start: 10, end: 15, char_count: 5, starts_with_heading: true, heading: '# 둘', passthrough: false,
        input_file: '01_chunk_02_input.txt', rewritten_file: '02_chunk_02_rewritten.txt' }
    ],
    ...extra
  });

  it('parses manifest v1 with the sejong block and passes the analyse options', async () => {
    const seams = [{ chunk: 2, prev: [0, 10], next: [0, 0] }];
    await writeFile(path.join(dir, 'chunk_manifest.json'), JSON.stringify(manifest({ sejong: { version: 1, genre: 'blog', seams }, future: 1 })));
    const { runner, python } = adapter([exited('')]);
    const parsed = await python.prepare(dir, signal, { analyse: { inputKind: 'direct-text', strength: 'medium', genre: 'blog' } });
    expect(parsed).toMatchObject({ version: 1, chunkCount: 2, routeHint: null, routeReason: 'sejong:chunked', processingMode: 'chunked',
      sejong: { version: 1, genre: 'blog', seams } });
    expect(parsed.chunks[1]).toMatchObject({ index: 2, heading: '# 둘', inputFile: '01_chunk_02_input.txt' });
    expect(runner.calls[0]!.args).toEqual([path.join(engineRoot, 'sejong_cli.py'), 'prepare', '--run-dir', dir,
      '--analyse', '--input-kind', 'direct-text', '--strength', 'medium', '--genre', 'blog']);
    expect(runner.calls[0]!.cwd).toBe(dir);
  });

  it('rejects broken manifests and failed steps', async () => {
    const broken = [
      manifest({ version: 2 }), manifest({ chunk_count: 3 }), manifest({ route_hint: 'auto' }),
      manifest({ source_file: '../x' }), manifest({ sejong: { version: 2, genre: 'blog', seams: [] } }),
      manifest({ sejong: { version: 1, genre: 'news', seams: [] } }),
      manifest({ sejong: { version: 1, genre: 'blog', seams: [{ chunk: 3, prev: [0, 0], next: [0, 0] }] } }),
      manifest({ sejong: { version: 1, genre: 'blog', seams: [{ chunk: 1, prev: [5, 2], next: [0, 0] }] } })
    ];
    for (const value of broken) expect(() => parseSejongManifest(value)).toThrow(EngineError);
    expect(parseSejongManifest(manifest()).sejong).toBeUndefined();
    const { python } = adapter([exited('', 1)]);
    expect((await rejection(python.prepare(dir, signal))).message).toContain('prepare step failed');
  });

  it('returns the reassembled output path', async () => {
    await writeFile(path.join(dir, '03_reassembled.md'), '결과');
    const { runner, python } = adapter([exited('')]);
    expect(await python.finalize(dir, signal)).toBe(path.join(dir, '03_reassembled.md'));
    expect(runner.calls[0]!.args).toEqual([path.join(engineRoot, 'sejong_cli.py'), 'finalize', '--run-dir', dir,
      '--output', '03_reassembled.md', '--report', '03_reassembly_report.json']);
    const { python: failed } = adapter([exited('', 1)]);
    expect((await rejection(failed.finalize(dir, signal))).message).toContain('finalize step failed');
    const empty = await makeTestRoot('sejong-empty-');
    try {
      const { python: missing } = adapter([exited('')]);
      expect((await rejection(missing.finalize(empty, signal))).message).toBe('Reassembled output is missing');
    } finally {
      await removeTestRoot(empty);
    }
  });
});

describe('contract validation in TypeScript (port of engine_runtime/sejong/io.py)', () => {
  const clone = <T>(value: T): T => structuredClone(value);

  it('accepts every fixture', () => {
    for (const name of ['plan-blog-medium.json', 'plan-no-edit.json']) expect(planProblems(json(fixture(name)), schemas.plan)).toEqual([]);
    for (const name of ['check-accept.json', 'check-retry.json', 'check-rollback.json']) {
      expect(checkProblems(json(fixture(name)), schemas.check)).toEqual([]);
    }
  });

  it('rejects the plan mutations the Python contract tests reject', () => {
    const plan = json<Plan>(fixture('plan-blog-medium.json'));
    const mutations: Array<(p: Plan) => void> = [
      p => { (p as unknown as Record<string, unknown>).extra = 1; },
      p => { p.sentences[0]!.id = 's1'; },
      p => { p.chunk.sourceSha256 = 'ABC'; },
      p => { p.sentences[0]!.end = 18.5; },
      p => { p.requests[0]!.rules = ['SSJ-A01', 'SSJ-A01']; },
      p => { p.needsModel = false; },
      p => { p.sentences[1]!.id = 'S1'; },
      p => { p.sentences[1]!.start = 10; },
      p => { p.requests[0]!.sentence = 'S9'; },
      p => { p.requests[0]!.rules = ['SSJ-N04']; },
      p => { p.findings[0]!.sentence = 'S1'; },
      p => { p.deterministic[0]!.before = '됬됬'; },
      p => { p.openReview.enabled = false; },
      p => { p.protected[0]!.end = 999; },
      p => { p.sentences[4]!.cta = null; p.ctaLedger[0]!.sentence = 'S9'; },
      p => { p.chunk.index = 2; }
    ];
    for (const [index, mutate] of mutations.entries()) {
      const broken = clone(plan);
      mutate(broken);
      expect([index, planProblems(broken, schemas.plan).length > 0]).toEqual([index, true]);
    }
  });

  it('rejects the check mutations the Python contract tests reject', () => {
    const report = json<CheckReport>(fixture('check-retry.json'));
    const mutations: Array<(r: CheckReport) => void> = [
      r => { r.shadowFailures.push('VOICE_LEVEL'); },
      r => { r.retry[0]!.violations[0]!.code = 'voice level'; },
      r => { (r as { attempt: number }).attempt = 3; },
      r => { (r.warningReasons.codes as string[]).push('P1_STYLE_TARGET'); },
      r => { r.hardFailures.push('quote_altered'); },
      r => { r.retry = []; },
      r => { r.sentences[1]!.status = 'accepted'; },
      r => { r.attempt = 2; r.policy = 'accept-with-warning'; },
      r => { r.sentences.push(clone(r.sentences[0]!)); }
    ];
    for (const [index, mutate] of mutations.entries()) {
      const broken = clone(report);
      mutate(broken);
      expect([index, checkProblems(broken, schemas.check).length > 0]).toEqual([index, true]);
    }
  });

  it('refuses schema keywords it does not implement, like io.py', () => {
    expect(() => validateSchema('x', { type: 'string', format: 'email' })).toThrow(SchemaError);
    expect(() => validateSchema('x', { $ref: 'http://example.com/s.json' })).toThrow(SchemaError);
    expect(validateSchema('😀', { maxLength: 1 })).toEqual([]);
    expect(validateSchema('abc\n', { pattern: '^[a-z]+$' }).length).toBeGreaterThan(0);
    expect(validateSchema(true, { enum: [1] }).length).toBeGreaterThan(0);
    expect(validateSchema(1.0, { type: 'integer' })).toEqual([]);
  });
});
