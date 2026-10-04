/** WP-17: the legacy shadow hook (SUPER_SEJONG_V2_SHADOW=1) against a fake v2 adapter.
 * The real Python CLI is covered in sejong-shadow-real.test.ts. Here: when the hook runs, what it records,
 * and that nothing it does or fails at can reach the legacy result.
 */
import { readFileSync } from 'node:fs';
import { readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  HumanizeEngine, shadowCandidates, type CodexAdapter, type HumanizeResult, type PythonAdapter, type V2ShadowAdapter
} from '../../src/engine/humanize-engine.js';
import { EngineError } from '../../src/engine/errors.js';
import type { ChunkEntry, ChunkManifest, GateResult, RestoreReport } from '../../src/engine/python-engine.js';
import type { RewriteOptions } from '../../src/engine/rewrite-policy.js';
import type { AnalyseOptions, SejongManifest } from '../../src/engine/sejong/python-adapter.js';
import type { CheckReport } from '../../src/engine/sejong/types.js';
import { JobWorkspace } from '../../src/engine/workspace.js';
import { deferred } from '../helpers/deferred.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';

const fixtures = path.resolve('tests/fixtures/sejong');
const fixtureReport = (name: string): CheckReport => JSON.parse(readFileSync(path.join(fixtures, name), 'utf8')) as CheckReport;
const ACCEPT = fixtureReport('check-accept.json');
const RETRY = fixtureReport('check-retry.json');
const ROLLBACK = fixtureReport('check-rollback.json');
const ON = { SUPER_SEJONG_V2_SHADOW: '1' };
const signal = new AbortController().signal;

/* ---------- legacy side: the same stand-ins tests/unit/humanize-engine.test.ts uses ---------- */

const ok = (): GateResult => ({ status: 'ok', exitCode: 0, gateCodes: ['GATE_OK'] });
const noRestore = (): RestoreReport => ({ restoredSentences: 0, skippedSentences: 0, removedCommas: 0 });

function legacyBody(index: number, start: number, end: number): ChunkEntry {
  const label = String(index).padStart(2, '0');
  return { index, start, end, charCount: end - start, startsWithHeading: false, heading: null, passthrough: false,
    inputFile: `01_chunk_${label}_input_with_metrics.txt`, rewrittenFile: `02_chunk_${label}_rewritten.txt` };
}

function legacyManifest(source: string): ChunkManifest {
  const chars = Array.from(source).length;
  return { version: 1, sourceFile: '01_input.txt', sourceChars: chars, sourceSha256: 'hash', chunkCount: 1, bodyChunkCount: 1,
    passthroughChunkCount: 0, routeHint: 'standard', routeReason: 'single document route', processingMode: 'single',
    warnings: [], chunks: [legacyBody(1, 0, chars)] };
}

class LegacyPython implements PythonAdapter {
  verifyCalls = 0;
  constructor(private readonly manifest: ChunkManifest, private readonly onVerify?: (call: number) => Promise<void>) {}
  async prepare(): Promise<ChunkManifest> { return this.manifest; }
  async restore(): Promise<RestoreReport> { return noRestore(); }
  async verify(): Promise<GateResult> {
    this.verifyCalls += 1;
    await this.onVerify?.(this.verifyCalls);
    return ok();
  }
  async reassemble(runDir: string): Promise<string> {
    const output = path.join(runDir, '03_reassembled.md');
    await writeFile(output, await readFile(path.join(runDir, this.manifest.chunks[0]!.rewrittenFile!), 'utf8'), 'utf8');
    return output;
  }
}

const rewriting = (rewrite: (text: string) => string): CodexAdapter => ({
  async transform(inputPath) {
    return { rewrittenText: rewrite(await readFile(inputPath, 'utf8')), warnings: [] };
  }
});

/* ---------- v2 side: a fake adapter writing plan files like the CLI and returning canned reports ---------- */

function v2Chunk(index: number, start: number, end: number, passthrough = false): ChunkEntry {
  const label = String(index).padStart(2, '0');
  return { index, start, end, charCount: end - start, startsWithHeading: false, heading: null, passthrough,
    inputFile: passthrough ? null : `01_chunk_${label}_input.txt`, rewrittenFile: passthrough ? null : `02_chunk_${label}_rewritten.txt` };
}

function v2Manifest(chunks: ChunkEntry[]): SejongManifest {
  const body = chunks.filter(chunk => !chunk.passthrough).length;
  return { version: 1, sourceFile: '01_input.txt', sourceChars: chunks.at(-1)!.end, sourceSha256: 'hash', chunkCount: chunks.length,
    bodyChunkCount: body, passthroughChunkCount: chunks.length - body, routeHint: null, routeReason: 'sejong:single',
    processingMode: chunks.length === 1 ? 'single' : 'chunked', warnings: [], chunks };
}

interface FakePlan {
  needsModel?: boolean;
  sentences?: number;
  requests?: Array<{ tier: unknown; rules: unknown[] }>;
  findings?: Array<{ tier: unknown; rule: unknown }>;
  deterministic?: number;
  cta?: number;
  openReview?: boolean;
}

const planJson = (plan: FakePlan): unknown => ({
  schema: 'sejong-plan/1',
  sentences: Array.from({ length: plan.sentences ?? 4 }, (_unused, index) => ({ id: `S${index + 1}` })),
  needsModel: plan.needsModel ?? true,
  requests: plan.requests ?? [],
  findings: plan.findings ?? [],
  deterministic: Array.from({ length: plan.deterministic ?? 0 }),
  ctaLedger: Array.from({ length: plan.cta ?? 0 }),
  openReview: { enabled: plan.openReview ?? false, maxSentences: 3 }
});

interface FakeOptions {
  chunks: ChunkEntry[];
  plans?: FakePlan[];
  reports?: Array<CheckReport | Error>;
  prepareError?: Error;
  /** Called with the signal; the returned promise ignores it unless it resolves on its own. */
  prepareGate?: (signal: AbortSignal) => Promise<void>;
  checkGate?: () => Promise<never>;
}

class FakeV2 implements V2ShadowAdapter {
  readonly prepareCalls: Array<{ runDir: string; analyse: AnalyseOptions | undefined; signal: AbortSignal }> = [];
  readonly checkCalls: Array<{ plan: string; source: string; candidate: string | undefined; attempt: number; candidateText: string }> = [];
  constructor(private readonly options: FakeOptions) {}

  async prepare(runDir: string, abort: AbortSignal, opts: { analyse?: AnalyseOptions } = {}): Promise<SejongManifest> {
    this.prepareCalls.push({ runDir, analyse: opts.analyse, signal: abort });
    await this.options.prepareGate?.(abort);
    if (this.options.prepareError) throw this.options.prepareError;
    const body = this.options.chunks.filter(chunk => !chunk.passthrough);
    for (const [offset, chunk] of body.entries()) {
      await writeFile(path.join(runDir, `plan-${String(chunk.index).padStart(2, '0')}.json`),
        JSON.stringify(planJson(this.options.plans?.[offset] ?? {})), 'utf8');
    }
    return v2Manifest(this.options.chunks);
  }

  async check(args: Parameters<V2ShadowAdapter['check']>[0]): Promise<CheckReport> {
    this.checkCalls.push({ plan: args.plan, source: args.source, candidate: args.candidate, attempt: args.attempt,
      candidateText: await readFile(args.candidate!, 'utf8') });
    await this.options.checkGate?.();
    const next = this.options.reports?.[this.checkCalls.length - 1] ?? ACCEPT;
    if (next instanceof Error) throw next;
    return next;
  }
}

/* ---------- harness ---------- */

let outer = '';
beforeEach(async () => { outer = await makeTestRoot('sejong-shadow-'); });
afterEach(async () => { await removeTestRoot(outer); });

const SOURCE = '회의는 다음 주에 열립니다. 자료는 메일로 보냅니다. 문의는 담당자에게 주세요. 감사합니다.\n';
const EDIT = (text: string): string => text.replace('보냅니다', '보내 드립니다');

interface RunOptions {
  source?: string;
  codex?: CodexAdapter;
  shadow?: FakeV2;
  env?: NodeJS.ProcessEnv;
  timeoutMs?: number;
  jobId?: string;
  controller?: AbortController;
  /** Request options; `null` sends none, like a legacy caller. Default text-file / normal. */
  rewriteOptions?: RewriteOptions | null;
  /** Runs inside the legacy gate; call 1 is the chunk gate, call 2 the full-document gate. */
  onVerify?: (call: number) => Promise<void>;
}

async function run(options: RunOptions = {}): Promise<{ result: HumanizeResult; output: string; workspace: JobWorkspace }> {
  const source = options.source ?? SOURCE;
  const workspace = await JobWorkspace.create(outer, options.jobId ?? 'job-1');
  await writeFile(workspace.path('01_input.txt'), source, 'utf8');
  const engine = new HumanizeEngine({
    python: new LegacyPython(legacyManifest(source), options.onVerify),
    codex: options.codex ?? rewriting(EDIT),
    chunkConcurrency: 1,
    ...(options.shadow ? { v2Shadow: options.shadow } : {}),
    ...(options.env ? { env: options.env } : {}),
    ...(options.timeoutMs ? { v2ShadowTimeoutMs: options.timeoutMs } : {})
  });
  const result = await engine.transform({
    jobId: workspace.jobId, workspace, signal: (options.controller ?? new AbortController()).signal,
    onEvent: () => undefined,
    ...(options.rewriteOptions === null ? {} : { rewriteOptions: options.rewriteOptions ?? { inputKind: 'text-file', strength: 'normal' } })
  });
  return { result, output: await readFile(result.finalPath, 'utf8'), workspace };
}

const TIMINGS = ['prepareMs', 'codexMs', 'restoreMs', 'gateMs', 'assembleMs', 'totalMs'];
function stable(result: HumanizeResult): unknown {
  const diagnostics: Record<string, unknown> = { ...result.diagnostics };
  for (const key of [...TIMINGS, 'v2ShadowCounts']) delete diagnostics[key];
  return { diagnostics, warnings: result.warnings, chunks: result.chunks, sourceChars: result.sourceChars, outputChars: result.outputChars };
}

const wholeChunk = (source: string): ChunkEntry[] => [v2Chunk(1, 0, Array.from(source).length)];

describe('SUPER_SEJONG_V2_SHADOW off', () => {
  it.each([
    ['unset', {}],
    ['0', { SUPER_SEJONG_V2_SHADOW: '0' }],
    ['an unknown value', { SUPER_SEJONG_V2_SHADOW: 'yes' }],
    ['v2 selected as the engine', { SUPER_SEJONG_V2_SHADOW: '1', SUPER_SEJONG_ENGINE: 'v2' }]
  ])('runs nothing and records nothing when the flag is %s', async (_label, env) => {
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE) });
    const { result, output, workspace } = await run({ shadow, env });
    expect(shadow.prepareCalls).toHaveLength(0);
    expect(shadow.checkCalls).toHaveLength(0);
    expect(result.diagnostics.v2ShadowCounts).toBeUndefined();
    expect('v2ShadowCounts' in result.diagnostics).toBe(false);
    expect(await readdir(workspace.root)).not.toContain('v2-shadow');
    expect(output).toBe(EDIT(SOURCE));
  });

  it('runs nothing when the flag is on but no v2 adapter was given', async () => {
    const { result } = await run({ env: ON });
    expect(result.diagnostics.v2ShadowCounts).toBeUndefined();
  });
});

describe('SUPER_SEJONG_V2_SHADOW=1', () => {
  it('analyses the source, checks the delivered text at attempt 1 and records codes and counts', async () => {
    const shadow = new FakeV2({
      chunks: wholeChunk(SOURCE),
      plans: [{ needsModel: true, sentences: 4, openReview: true, deterministic: 1, cta: 2,
        requests: [{ tier: 'FIX', rules: ['SSJ-A04'] }, { tier: 'SUGGEST', rules: ['SSJ-LV3', 'CLR-LONG'] }],
        findings: [{ tier: 'FIX', rule: 'SSJ-A04' }, { tier: 'LEAVE', rule: 'SSJ-N04C' }] }],
      reports: [RETRY]
    });
    const { result, output, workspace } = await run({ shadow, env: { ...ON, SUPER_SEJONG_GENRE_DEFAULT: 'blog' } });

    expect(shadow.prepareCalls).toHaveLength(1);
    expect(shadow.prepareCalls[0]!.runDir).toBe(workspace.path('v2-shadow'));
    expect(shadow.prepareCalls[0]!.analyse).toEqual({ inputKind: 'text-file', strength: 'normal', genre: 'blog' });
    expect(shadow.checkCalls).toHaveLength(1);
    const call = shadow.checkCalls[0]!;
    expect(call.attempt).toBe(1);
    expect(call.candidateText).toBe(output);          // the text legacy delivered, not the source
    expect(call.candidateText).toBe(EDIT(SOURCE));
    expect(call.plan).toBe(path.join(workspace.path('v2-shadow'), 'plan-01.json'));
    expect(call.source).toBe(path.join(workspace.path('v2-shadow'), '01_chunk_01_input.txt'));

    const counts = result.diagnostics.v2ShadowCounts!;
    expect(counts).toMatchObject({
      shadow_ok: 1, chunks: 1, chunks_need_model: 1, chunks_open_review: 1, plan_sentences: 4, deterministic_fixes: 1, cta_units: 2,
      requests_fix: 1, requests_suggest: 1, request_rule_ssj_a04: 1, request_rule_ssj_lv3: 1, request_rule_clr_long: 1,
      findings_fix: 1, findings_leave: 1, finding_rule_ssj_a04: 1, finding_rule_ssj_n04c: 1,
      chunks_checked: 1, gate_exit_1: 1, would_retry: 1,
      sentences_retry: 1, sentences_unchanged: 3, sentences_deterministic: 1,
      sentence_code_voice_level: 1, retry_code_voice_level: 1, retry_family_voice: 1,
      request_status_still_present: 1, norm_fixes: 1
    });
    expect(counts.would_accept).toBeUndefined();
    expect(counts.ms_overhead).toBeGreaterThanOrEqual(0);
    expect(counts.ms_prepare).toBeGreaterThanOrEqual(0);
    expect(counts.ms_check).toBeGreaterThanOrEqual(0);
  });

  it('starts the check when the delivered text is final, while the legacy full-document gate still runs', async () => {
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE) });
    let seenDuringFullGate = -1;
    const onVerify = async (call: number): Promise<void> => {
      if (call !== 2) return;
      // Hangs (and the test fails by timeout) unless the shadow check was started before this gate returns.
      await expect.poll(() => shadow.checkCalls.length, { timeout: 2000 }).toBe(1);
      seenDuringFullGate = shadow.checkCalls[0]!.candidateText === EDIT(SOURCE) ? 1 : 0;
    };
    const { result } = await run({ shadow, env: ON, onVerify });
    expect(seenDuringFullGate).toBe(1);
    expect(result.diagnostics.v2ShadowCounts?.would_accept).toBe(1);
  });

  it('leaves the verdict to the legacy full-document gate: an abort still fails the job, shadow or not', async () => {
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE) });
    class AbortingGate extends LegacyPython {
      override async verify(): Promise<GateResult> {
        this.verifyCalls += 1;
        return this.verifyCalls === 2 ? { status: 'abort', exitCode: 2, gateCodes: ['GATE_ABORT'] } : ok();
      }
    }
    const workspace = await JobWorkspace.create(outer, 'abort');
    await writeFile(workspace.path('01_input.txt'), SOURCE, 'utf8');
    const engine = new HumanizeEngine({ python: new AbortingGate(legacyManifest(SOURCE)), codex: rewriting(EDIT), chunkConcurrency: 1, v2Shadow: shadow, env: ON });
    await expect(engine.transform({ jobId: 'abort', workspace, signal, onEvent: () => undefined, rewriteOptions: { inputKind: 'text-file', strength: 'normal' } }))
      .rejects.toMatchObject({ publicCode: 'VALIDATION_FAILED' });
  });

  it.each([
    ['direct text, strong', { inputKind: 'direct-text', strength: 'strong' } as RewriteOptions, 'direct-text', 'strong'],
    ['a text file', { inputKind: 'text-file', strength: 'normal' } as RewriteOptions, 'text-file', 'normal'],
    ['a legacy request without options', null, 'text-file', 'normal']
  ])('asks v2 to analyse the same job: %s, default genre', async (_label, rewriteOptions, inputKind, strength) => {
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE) });
    await run({ shadow, env: ON, rewriteOptions, codex: rewriting(text => text) });
    expect(shadow.prepareCalls[0]!.analyse).toEqual({ inputKind, strength, genre: 'general' });
  });

  it('records a rollback verdict, hard failures and families of reverted sentences', async () => {
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE), reports: [ROLLBACK] });
    const { result } = await run({ shadow, env: ON });
    const counts = result.diagnostics.v2ShadowCounts!;
    expect(counts.gate_exit_2).toBe(1);
    expect(counts.would_fail).toBe(1);
    for (const code of ROLLBACK.hardFailures) expect(counts[`hard_${code}`]).toBe(1);
    for (const [family, count] of Object.entries(ROLLBACK.counts.revertedByFamily)) expect(counts[`reverted_family_${family}`]).toBe(count);
    expect(counts.reverted_sentences).toBe(ROLLBACK.counts.revertedSentences);
  });

  it('starts the analyse step while the legacy model call is still running', async () => {
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE) });
    const started = deferred<void>();
    const release = deferred<void>();
    const codex: CodexAdapter = {
      async transform(inputPath) {
        started.resolve();
        await release.promise;
        return { rewrittenText: EDIT(await readFile(inputPath, 'utf8')), warnings: [] };
      }
    };
    const pending = run({ shadow, env: ON, codex });
    await started.promise;
    await expect.poll(() => shadow.prepareCalls.length).toBe(1);
    expect(shadow.checkCalls).toHaveLength(0);          // the check needs the delivered text
    release.resolve();
    const { result } = await pending;
    expect(shadow.checkCalls).toHaveLength(1);
    expect(result.diagnostics.v2ShadowCounts?.shadow_ok).toBe(1);
  });

  it.each([
    ['an edited rewrite', rewriting(EDIT), SOURCE],
    ['an identity rewrite', rewriting(text => text), SOURCE],
    ['a rewrite that adds a sentence', rewriting(text => `${text}추가 문장입니다.\n`), SOURCE]
  ])('delivers byte-identical text, warnings and diagnostics with and without the shadow (%s)', async (_label, codex, source) => {
    const without = await run({ codex, source, jobId: 'without' });
    const shadow = new FakeV2({ chunks: wholeChunk(source), reports: [RETRY] });
    const withShadow = await run({ codex, source, shadow, env: ON, jobId: 'with' });
    expect(Buffer.from(withShadow.output, 'utf8').equals(Buffer.from(without.output, 'utf8'))).toBe(true);
    expect(stable(withShadow.result)).toEqual(stable(without.result));
    expect(without.result.diagnostics.v2ShadowCounts).toBeUndefined();
    expect(withShadow.result.diagnostics.v2ShadowCounts).toBeDefined();
  });

  it('keeps everything it writes inside its own directory of the job workspace', async () => {
    const without = await run({ jobId: 'plain' });
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE) });
    const withShadow = await run({ shadow, env: ON, jobId: 'shadowed' });
    const names = (await readdir(withShadow.workspace.root)).sort();
    expect(names).toEqual([...(await readdir(without.workspace.root)), 'v2-shadow'].sort());
    expect((await readdir(withShadow.workspace.path('v2-shadow'))).sort()).toEqual(
      ['01_input.txt', 'plan-01.json', 'v2-candidate-01.txt'].sort());
    expect(await readFile(withShadow.workspace.path('v2-shadow/01_input.txt'), 'utf8')).toBe(SOURCE);
  });

  it('counts a chunk that starts or ends inside a line as unaligned instead of guessing', async () => {
    // v2 cuts a very long paragraph between sentences: the legacy text cannot be cut by lines there.
    const source = '첫 문장입니다. 둘째 문장입니다.\n';
    const cut = Array.from('첫 문장입니다. ').length;
    const shadow = new FakeV2({ chunks: [v2Chunk(1, 0, cut), v2Chunk(2, cut, Array.from(source).length)] });
    const { result } = await run({ source, shadow, env: ON, codex: rewriting(text => text.replace('둘째', '두 번째')) });
    const counts = result.diagnostics.v2ShadowCounts!;
    expect(counts.chunks).toBe(2);
    expect(counts.chunks_unaligned).toBe(2);
    expect(counts.chunks_checked).toBeUndefined();
    expect(counts.would_accept ?? counts.would_retry ?? counts.would_fail).toBeUndefined();
    expect(shadow.checkCalls).toHaveLength(0);
    expect(counts.shadow_ok).toBe(1);                    // nothing failed; the check was just not possible
  });
});

describe('multi-chunk assignment of the legacy text', () => {
  const source = 'A1 안내합니다. A2 보냅니다.\n\nB1 안내합니다. B2 보냅니다.\n\n[1] 각주입니다.\n';
  const points = Array.from(source);
  const firstEnd = Array.from('A1 안내합니다. A2 보냅니다.\n\n').length;
  const secondEnd = Array.from('A1 안내합니다. A2 보냅니다.\n\nB1 안내합니다. B2 보냅니다.\n\n').length;
  const chunks = [v2Chunk(1, 0, firstEnd), v2Chunk(2, firstEnd, secondEnd), v2Chunk(3, secondEnd, points.length, true)];

  it('hands each v2 body chunk its own lines of the delivered text and skips the passthrough chunk', async () => {
    const shadow = new FakeV2({ chunks, reports: [ACCEPT, RETRY] });
    const edit = (text: string): string => text.replace('B2 보냅니다', 'B2 보내 드립니다');
    const { result, output } = await run({ source, shadow, env: ON, codex: rewriting(edit) });
    expect(output).toBe(edit(source));
    expect(shadow.checkCalls.map(call => call.candidateText).sort()).toEqual(
      ['A1 안내합니다. A2 보냅니다.\n\n', 'B1 안내합니다. B2 보내 드립니다.\n\n'].sort());
    const counts = result.diagnostics.v2ShadowCounts!;
    expect(counts).toMatchObject({ chunks: 2, chunks_checked: 2, gate_exit_0: 1, gate_exit_1: 1, would_retry: 1 });
  });

  it('takes the worst verdict of the chunks for the whole job', async () => {
    const worst = new FakeV2({ chunks, reports: [RETRY, ROLLBACK] });
    expect((await run({ source, shadow: worst, env: ON, jobId: 'a' })).result.diagnostics.v2ShadowCounts)
      .toMatchObject({ would_fail: 1 });
    const best = new FakeV2({ chunks, reports: [ACCEPT, ACCEPT] });
    const counts = (await run({ source, shadow: best, env: ON, jobId: 'b' })).result.diagnostics.v2ShadowCounts!;
    expect(counts).toMatchObject({ would_accept: 1, gate_exit_0: 2 });
    expect(counts.would_retry).toBeUndefined();
  });
});

describe('shadowCandidates', () => {
  const doc = 'A1. A2.\n\nB1. B2.\n\n[1] 각주\n';
  const total = Array.from(doc).length;
  const a = Array.from('A1. A2.\n\n').length, b = Array.from('A1. A2.\n\nB1. B2.\n\n').length;
  const chunks = [v2Chunk(1, 0, a), v2Chunk(2, a, b), v2Chunk(3, b, total, true)];

  it('cuts the output by lines and leaves the passthrough chunk out', () => {
    const output = doc.replace('B2', 'B2 수정');
    expect([...shadowCandidates(doc, output, chunks)]).toEqual([[1, 'A1. A2.\n\n'], [2, 'B1. B2 수정.\n\n']]);
  });

  it('gives a single chunk the whole text, whatever its shape', () => {
    expect([...shadowCandidates(doc, 'any text', [v2Chunk(1, 0, total)])]).toEqual([[1, 'any text']]);
  });

  it.each([
    ['one line more', `${doc}extra\n`],
    ['one line less', 'A1. A2.\n\nB1. B2.\n[1] 각주\n'],
    ['a blank line moved', 'A1. A2.\nB1. B2.\n\n\n[1] 각주\n'],
    ['a blank line filled', doc.replace('A2.\n\nB1', 'A2.\n.\nB1')]
  ])('refuses the mapping for %s', (_label, output) => {
    expect(shadowCandidates(doc, output, chunks).size).toBe(0);
  });

  it('skips only the chunk that does not start and end on lines', () => {
    const mid = Array.from('A1. ').length;
    const odd = [v2Chunk(1, 0, mid), v2Chunk(2, mid, b), v2Chunk(3, b, total, true)];
    expect(shadowCandidates(doc, doc, odd).size).toBe(0);                 // chunk 1 ends mid-line, so does chunk 2 start
    const clean = [v2Chunk(1, 0, a), v2Chunk(2, a, total)];
    expect([...shadowCandidates(doc, doc, clean).keys()]).toEqual([1, 2]);
  });

  it('keeps an unterminated last line and does not mind CRLF', () => {
    const text = '가.\r\n\r\n나.';
    const cut = Array.from('가.\r\n\r\n').length;
    const split = [v2Chunk(1, 0, cut), v2Chunk(2, cut, Array.from(text).length)];
    expect([...shadowCandidates(text, text.replace('나.', '다.'), split)]).toEqual([[1, '가.\r\n\r\n'], [2, '다.']]);
  });

  it('refuses chunks that do not cover the document', () => {
    expect(shadowCandidates(doc, doc, [v2Chunk(1, 0, a), v2Chunk(2, a, b)]).size).toBe(0);
    expect(shadowCandidates(doc, doc, [v2Chunk(1, 2, a), v2Chunk(2, a, total)]).size).toBe(0);
  });
});

describe('v2 failures never reach the legacy result', () => {
  let jobs = 0;
  async function same(shadow: FakeV2, extra: Partial<RunOptions> = {}): Promise<Record<string, number>> {
    jobs += 1;
    const without = await run({ jobId: `without-${jobs}` });
    const withShadow = await run({ shadow, env: ON, jobId: `with-${jobs}`, ...extra });
    expect(withShadow.output).toBe(without.output);
    expect(stable(withShadow.result)).toEqual(stable(without.result));
    return withShadow.result.diagnostics.v2ShadowCounts!;
  }

  it('swallows a failing prepare step and counts it', async () => {
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE), prepareError: new EngineError('ENGINE_OUTPUT_INVALID', false, 'Sejong prepare step failed') });
    const counts = await same(shadow);
    expect(counts).toMatchObject({ shadow_failed: 1, failed_prepare: 1 });
    expect(counts.shadow_ok).toBeUndefined();
    expect(shadow.checkCalls).toHaveLength(0);
  });

  it('swallows a check execution error and still reports the plan sizes', async () => {
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE), plans: [{ requests: [{ tier: 'FIX', rules: ['SSJ-A04'] }] }],
      reports: [new EngineError('VALIDATION_FAILED', false, 'Sejong check execution failed')] });
    const counts = await same(shadow);
    expect(counts).toMatchObject({ shadow_failed: 1, failed_check: 1, chunks: 1, requests_fix: 1 });
    expect(counts.chunks_checked).toBeUndefined();
    expect(counts.would_accept ?? counts.would_retry ?? counts.would_fail).toBeUndefined();
  });

  it('swallows a plan that cannot be read', async () => {
    class BrokenPlan extends FakeV2 {
      override async prepare(runDir: string, abort: AbortSignal, opts: { analyse?: AnalyseOptions } = {}): Promise<SejongManifest> {
        const manifest = await super.prepare(runDir, abort, opts);
        await writeFile(path.join(runDir, 'plan-01.json'), '{not json', 'utf8');
        return manifest;
      }
    }
    const counts = await same(new BrokenPlan({ chunks: wholeChunk(SOURCE) }));
    expect(counts).toMatchObject({ shadow_failed: 1, failed_plan: 1 });
  });

  it('counts a step that hangs and ignores its signal as a timeout without holding the job', async () => {
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE), checkGate: () => new Promise<never>(() => undefined) });
    const startedAt = Date.now();
    const counts = await same(shadow, { timeoutMs: 80 });
    expect(Date.now() - startedAt).toBeLessThan(3000);
    expect(counts).toMatchObject({ shadow_failed: 1, timeout_check: 1 });
  });

  it('counts a hanging prepare as a timeout too', async () => {
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE), prepareGate: () => new Promise<void>(() => undefined) });
    const counts = await same(shadow, { timeoutMs: 80 });
    expect(counts).toMatchObject({ shadow_failed: 1, timeout_prepare: 1 });
  });

  it('maps the adapter timeout and cancellation errors to their own counts', async () => {
    const timeout = new FakeV2({ chunks: wholeChunk(SOURCE), reports: [new EngineError('ENGINE_TIMEOUT', true, 'Sejong check timed out')] });
    expect(await same(timeout)).toMatchObject({ timeout_check: 1 });
    const cancelled = new FakeV2({ chunks: wholeChunk(SOURCE), reports: [new EngineError('CLIENT_ABORTED', true, 'Sejong check was cancelled')] });
    expect(await same(cancelled)).toMatchObject({ aborted_check: 1 });
  });

  it('stops the analyse step when the legacy job fails, and the legacy error stays the legacy error', async () => {
    const entered = deferred<AbortSignal>();
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE), prepareGate: abort => { entered.resolve(abort); return new Promise<void>(() => undefined); } });
    const failing: CodexAdapter = {
      async transform() {
        await entered.promise;
        throw new EngineError('ENGINE_FAILED', true, 'Codex CLI failed (exit 1)');
      }
    };
    await expect(run({ shadow, env: ON, codex: failing })).rejects.toMatchObject({ publicCode: 'ENGINE_FAILED' });
    const abort = await entered.promise;
    await expect.poll(() => abort.aborted).toBe(true);
    expect(shadow.checkCalls).toHaveLength(0);
  });

  it('ends the shadow when the client cancels, without turning the legacy result into an error', async () => {
    const controller = new AbortController();
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE), checkGate: async () => { controller.abort(); return new Promise<never>(() => undefined); } });
    // The legacy decision was already made; a cancellation that only the shadow observes cannot undo it.
    const { result, output } = await run({ shadow, env: ON, controller });
    expect(output).toBe(EDIT(SOURCE));
    expect(result.diagnostics.v2ShadowCounts).toMatchObject({ shadow_failed: 1, aborted_check: 1 });
  });
});

describe('what ends up in v2ShadowCounts', () => {
  const KEY = /^[a-z0-9_]+$/;

  it('has only identifier keys and integer values even when the plan carries text', async () => {
    const shadow = new FakeV2({
      chunks: wholeChunk(SOURCE),
      plans: [{ requests: [{ tier: '원문 문장', rules: ['한글 규칙', 'SSJ-A04', 7, null] }],
        findings: [{ tier: undefined, rule: 'x'.repeat(200) }, { tier: 'FIX', rule: '../etc/passwd' }] }]
    });
    const { result } = await run({ shadow, env: ON });
    const counts = result.diagnostics.v2ShadowCounts!;
    for (const [key, value] of Object.entries(counts)) {
      expect(key, key).toMatch(KEY);
      expect(Number.isInteger(value), key).toBe(true);
      expect(value, key).toBeGreaterThanOrEqual(0);
    }
    expect(counts).toMatchObject({ requests_other: 1, request_rule_other: 3, request_rule_ssj_a04: 1, finding_rule_other: 2, findings_fix: 1, findings_other: 1 });
    expect(JSON.stringify(counts)).not.toContain('원문');
    expect(JSON.stringify(counts)).not.toContain('passwd');
  });

  it('bounds the number of distinct keys', async () => {
    const shadow = new FakeV2({
      chunks: wholeChunk(SOURCE),
      plans: [{ findings: Array.from({ length: 400 }, (_unused, index) => ({ tier: 'FIX', rule: `RULE-${index}` })) }]
    });
    const { result } = await run({ shadow, env: ON });
    const counts = result.diagnostics.v2ShadowCounts!;
    expect(Object.keys(counts).length).toBeLessThanOrEqual(204);   // 200 counted keys, other_keys, three timings
    expect(counts.other_keys).toBeGreaterThan(0);
  });

  it('is serialisable as a flat JSON log field', async () => {
    const shadow = new FakeV2({ chunks: wholeChunk(SOURCE), reports: [RETRY] });
    const { result } = await run({ shadow, env: ON });
    const copy = JSON.parse(JSON.stringify(result.diagnostics.v2ShadowCounts)) as Record<string, number>;
    expect(copy).toEqual(result.diagnostics.v2ShadowCounts);
  });
});
