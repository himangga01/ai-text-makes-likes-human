/** WP-17: the legacy shadow hook with the real Python engines on both sides (legacy vendor engine and the v2 CLI).
 * Each scenario runs twice, without and with SUPER_SEJONG_V2_SHADOW=1; the delivered bytes, the warnings and the
 * legacy diagnostics must not differ. The scenarios reuse the inputs and rewrites of the existing integration
 * suites (humanize-engine.test.ts, pipeline-fidelity.test.ts), plus edits that v2 judges differently from legacy.
 */
import { readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { HumanizeEngine, type CodexAdapter, type HumanizeResult } from '../../src/engine/humanize-engine.js';
import { PythonEngine } from '../../src/engine/python-engine.js';
import type { RewriteOptions } from '../../src/engine/rewrite-policy.js';
import { SejongPython } from '../../src/engine/sejong/python-adapter.js';
import { JobWorkspace } from '../../src/engine/workspace.js';
import { SpawnCommandRunner } from '../../src/process/command-runner.js';
import { pythonCommand } from '../helpers/python-command.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';

const runner = new SpawnCommandRunner();
const legacyPython = () => new PythonEngine({ pythonCommand, vendorRoot: path.resolve('vendor/humanize-engine'), runner });
const v2 = new SejongPython({ pythonCommand, engineRoot: path.resolve('engine_runtime'), runner });
const SHADOW_ENV = { ...process.env, SUPER_SEJONG_V2_SHADOW: '1' };
const PLAIN_ENV = (() => {
  const env = { ...process.env };
  delete env.SUPER_SEJONG_V2_SHADOW;
  return env;
})();
const TEXT_FILE: RewriteOptions = { inputKind: 'text-file', strength: 'normal' };
const DIRECT: RewriteOptions = { inputKind: 'direct-text', strength: 'medium' };

const rewriting = (rewrite: (text: string, attempt: 1 | 2) => string): CodexAdapter => ({
  async transform(inputPath, _outputPath, attempt) {
    return { rewrittenText: rewrite(await readFile(inputPath, 'utf8'), attempt), warnings: [] };
  }
});
const identity = rewriting(text => text);

let counter = 0;
async function engineRun(source: string, codex: CodexAdapter, options: RewriteOptions | undefined, shadow: boolean) {
  const outer = await makeTestRoot('sejong-shadow-real-');
  counter += 1;
  const workspace = await JobWorkspace.create(outer, `job-${counter}`);
  try {
    await writeFile(workspace.path('01_input.txt'), source, 'utf8');
    const engine = new HumanizeEngine({
      python: legacyPython(), codex, chunkConcurrency: 1,
      ...(shadow ? { v2Shadow: v2, env: SHADOW_ENV } : { v2Shadow: v2, env: PLAIN_ENV })
    });
    const result = await engine.transform({
      jobId: workspace.jobId, workspace, signal: new AbortController().signal, onEvent: () => undefined,
      ...(options ? { rewriteOptions: options } : {})
    });
    const output = await readFile(result.finalPath, 'utf8');
    const files = await readdir(workspace.root);
    return { result, output, files };
  } finally {
    await workspace.cleanup();
    await removeTestRoot(outer);
  }
}

const TIMINGS = ['prepareMs', 'codexMs', 'restoreMs', 'gateMs', 'assembleMs', 'totalMs'];
function stable(result: HumanizeResult): unknown {
  const diagnostics: Record<string, unknown> = { ...result.diagnostics };
  for (const key of [...TIMINGS, 'v2ShadowCounts']) delete diagnostics[key];
  return { diagnostics, warnings: result.warnings, chunks: result.chunks, sourceChars: result.sourceChars, outputChars: result.outputChars };
}

async function both(source: string, codex: CodexAdapter, options?: RewriteOptions) {
  const off = await engineRun(source, codex, options, false);
  const on = await engineRun(source, codex, options, true);
  expect(Buffer.from(on.output, 'utf8').equals(Buffer.from(off.output, 'utf8'))).toBe(true);
  expect(stable(on.result)).toEqual(stable(off.result));
  expect('v2ShadowCounts' in off.result.diagnostics).toBe(false);
  expect(off.files).not.toContain('v2-shadow');
  expect(on.files).toContain('v2-shadow');
  const counts = on.result.diagnostics.v2ShadowCounts;
  expect(counts).toBeDefined();
  return { off, on, counts: counts! };
}

/* ---------- inputs of the existing integration suites ---------- */

const paragraph = [
  '우리 팀은 지난 분기에 새로운 협업 방식을 도입하였다.',
  '처음에는 낯선 도구 때문에 혼란이 있었지만 곧 익숙해졌다.',
  '회의 시간은 눈에 띄게 줄었고 결정은 더 빨라졌다.',
  '대표는 이 변화를 조직 전체로 확대하겠다고 발표하였다.',
  '다른 부서도 비슷한 방식을 시험해 보기로 하였다.',
  '우리는 이 경험을 문서로 정리해 공유하였다.'
].join(' ');
const pipeline = `${paragraph}\n\n두 번째 문단도 있다. 이 문단은 결론을 담는다.\n`;
const hedge = '이 수치는 낮은 것으로 판단된다. 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.\n';
const astral = '# 이모지 문서\n\n이 문서는 이모지 😀 를 포함한다. 수치 1,200은 유지한다.\n\n둘째 문단이다. 😀 마지막 문장이다.\n';
const brief = '우리는 새로운 방식을 도입하였다. 이 방식은 팀의 협업을 강화하였다.\n';
const dropSentence = (text: string) => text.replace(' 대표는 이 변화를 조직 전체로 확대하겠다고 발표하였다.', '');
const duplicateSentence = (text: string) => text.replace('두 번째 문단도 있다.', '두 번째 문단도 있다. 두 번째 문단도 있다.');

describe('delivered text is byte-identical with the shadow on (existing integration scenarios)', () => {
  it('identity rewrite of the integration fixture', async () => {
    const source = await readFile(path.resolve('tests/fixtures/short-korean.txt'), 'utf8');
    const { on, counts } = await both(source, identity);
    expect(on.output).toBe(source);
    expect(counts).toMatchObject({ shadow_ok: 1, chunks: 1, chunks_checked: 1, gate_exit_0: 1, would_accept: 1 });
  }, 60_000);

  it('astral characters round-trip', async () => {
    const { on, counts } = await both(astral, identity);
    expect(on.output).toBe(astral);
    expect(counts).toMatchObject({ shadow_ok: 1, would_accept: 1 });
  }, 60_000);

  it('a lost hedge restored by the legacy engine (no request options)', async () => {
    const { on, counts } = await both(hedge, rewriting(text => text.replace('낮은 것으로 판단된다', '낮은 수치다')));
    expect(on.output).toBe(hedge);
    expect(on.result.warnings).toContainEqual(expect.objectContaining({ code: 'MODALITY_RESTORED' }));
    expect(counts.shadow_ok).toBe(1);
  }, 60_000);

  it.each([
    ['a dropped sentence is rolled back', dropSentence, TEXT_FILE],
    ['a dropped sentence without request options', dropSentence, undefined],
    ['a duplicated sentence is rolled back', duplicateSentence, TEXT_FILE],
    ['a rulebook split is kept', (text: string) => text.replace('혼란이 있었지만 곧', '혼란이 있었다. 하지만 곧'), TEXT_FILE],
    ['an ellipsis respelling is kept', (text: string) => text.replace('결론을 담는다.', '결론을 담는다...'), TEXT_FILE],
    ['a structure-preserving edit is kept', (text: string) => text.replace('공유하였다', '공유했다'), TEXT_FILE],
    ['a prompt boundary echo is rolled back', (text: string) => `BEGIN_SOURCE_${'a'.repeat(32)}\n${text}`, TEXT_FILE]
  ])('pipeline fidelity: %s', async (_label, edit, options) => {
    const { counts } = await both(pipeline, rewriting(edit), options);
    expect(counts.shadow_ok).toBe(1);
  }, 60_000);

  it('direct text: a trimmed trailing newline is accepted', async () => {
    const edit = (value: string) => value.replace('도입하였다', '도입했다').replace('강화하였다', '강화했다');
    const { on, counts } = await both(brief, rewriting(value => edit(value).trimEnd()), DIRECT);
    expect(on.output).toBe(edit(brief));
    expect(counts.shadow_ok).toBe(1);
  }, 60_000);

  it('direct text: protected sentences, retry and rollback', async () => {
    const source = '회의는 3시에 열렸다. 우리는 결과를 정리하였다. 우리는 결과를 공유하였다.\n';
    const { counts } = await both(source, rewriting(text => text.replace('3시', '4시')), DIRECT);
    expect(counts.shadow_ok).toBe(1);
  }, 60_000);
});

describe('what v2 would have said about the legacy output', () => {
  const doubled = '회의 자료는 팀원들에 의해 작성되어졌습니다. 일정은 메일로 안내해 드립니다. 참석하실 분은 신청해 주세요.\n\n둘째 문단입니다. 문의는 담당자에게 연락해 주시기 바랍니다. 감사합니다.\n';
  const fixed = (text: string) => text.replace('작성되어졌습니다', '작성되었습니다');
  const drift = (text: string) => text.replace('작성되어졌습니다', '작성됐어요');
  const collateral = (text: string) => text.replace('안내해 드립니다', '안내드려요');

  it('an unedited text: v2 would send its request and accept the unchanged chunk', async () => {
    const { counts } = await both(doubled, identity, TEXT_FILE);
    expect(counts).toMatchObject({ shadow_ok: 1, chunks: 1, chunks_need_model: 1, requests_fix: 1, request_rule_ssj_a04: 1,
      gate_exit_0: 1, would_accept: 1, request_status_declined: 1, sentences_unchanged: 6 });
  }, 60_000);

  it('the double passive fixed by the writer: the request counts as fixed', async () => {
    const { on, counts } = await both(doubled, rewriting(fixed), TEXT_FILE);
    expect(on.output).toBe(fixed(doubled));
    expect(counts).toMatchObject({ would_accept: 1, request_status_fixed: 1, sentences_accepted: 1 });
  }, 60_000);

  it('a speech-level drift that legacy delivers: v2 would ask for a retry on the voice family', async () => {
    const { on, counts } = await both(doubled, rewriting(drift), TEXT_FILE);
    expect(on.output).toBe(drift(doubled));     // legacy delivered it; the shadow only reports
    expect(counts).toMatchObject({ gate_exit_1: 1, would_retry: 1, sentences_retry: 1, retry_family_voice: 1,
      retry_code_voice_level: 1, request_status_still_present: 1 });
    expect(counts.would_accept).toBeUndefined();
  }, 60_000);

  it('an edit nobody asked for: v2 would revert it as a collateral edit', async () => {
    const { on, counts } = await both(doubled, rewriting(collateral), TEXT_FILE);
    expect(on.output).toBe(collateral(doubled));
    expect(counts).toMatchObject({ would_accept: 1, sentences_reverted: 1, collateral_reverts: 1, reverted_sentences: 1, sentence_code_collateral_edit: 1 });
  }, 60_000);

  it('a flag value other than 1, or no flag, runs nothing even with the adapter present', async () => {
    const off = await engineRun(doubled, rewriting(fixed), TEXT_FILE, false);
    expect('v2ShadowCounts' in off.result.diagnostics).toBe(false);
    expect(off.files).not.toContain('v2-shadow');
  }, 60_000);
});

describe('a document that v2 cuts into several chunks', () => {
  // Distinct sentences, numbered paragraphs; two double passives far apart so that they land in different v2 chunks.
  const sentences = (paragraphIndex: number) => Array.from({ length: 6 }, (_unused, k) =>
    `${paragraphIndex + 1}번째 묶음의 ${k + 1}번 항목은 점검을 마치고 기록을 남겼습니다.`).join(' ');
  const paragraphs = Array.from({ length: 160 }, (_unused, index) => sentences(index));
  paragraphs[20] = '이 항목은 담당 팀에 의해 작성되어졌습니다. ' + paragraphs[20];
  paragraphs[140] = '다른 항목은 위원회에 의해 검토되어졌습니다. ' + paragraphs[140];
  const source = `${paragraphs.join('\n\n')}\n`;
  const fix = (text: string) => text.replace('작성되어졌습니다', '작성되었습니다').replace('검토되어졌습니다', '검토되었습니다');

  it('assigns the delivered text to every v2 chunk and records one verdict per chunk', async () => {
    expect(Array.from(source).length).toBeGreaterThan(15_000);
    const { on, counts } = await both(source, rewriting(fix), TEXT_FILE);
    expect(on.output).toBe(fix(source));
    expect(counts.chunks).toBeGreaterThanOrEqual(2);
    expect(counts.chunks_unaligned).toBeUndefined();
    expect(counts).toMatchObject({ shadow_ok: 1, chunks_checked: counts.chunks, gate_exit_0: counts.chunks, would_accept: 1,
      requests_fix: 2, request_status_fixed: 2 });
  }, 180_000);
});
