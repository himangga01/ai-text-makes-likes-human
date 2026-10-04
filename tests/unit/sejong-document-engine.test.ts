import { afterEach, expect, it, vi } from 'vitest';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { DocumentEngine } from '../../src/documents/document-engine.js';
import { SpawnCommandRunner, type CommandRequest } from '../../src/process/command-runner.js';
import { loadConfig } from '../../src/config.js';
import type { TransformEvent } from '../../src/contracts.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';
import { documentPythonCommand } from '../helpers/python-command.js';

// Office extraction runs in Python with lxml; skip rather than fail on an interpreter without it.
const officeIt = documentPythonCommand ? it : it.skip;
const cleanup: Array<() => Promise<unknown>> = [];
afterEach(async () => {
  vi.unstubAllEnvs();
  for (const fn of cleanup.splice(0).reverse()) await fn();
});

type Batch = { batchId: string; sourceHash: string; blocks: Array<{ id: string; text: string; sourceHash: string }> };
type Answer = (batch: Batch, attempt: number, prompt: string) => { reviewedIds?: string[]; edits: Record<string, Array<{ before: string; after: string }>> };

/** A DocumentEngine whose model calls are scripted: `answer` sees the batch the prompt carries and replies. */
async function setup(env: Record<string, string | undefined>, answer: Answer) {
  for (const name of ['SUPER_SEJONG_ENGINE', 'SUPER_SEJONG_MODE', 'SUPER_SEJONG_OPEN_REVIEW', 'SUPER_SEJONG_DETERMINISTIC_FIX',
    'SUPER_SEJONG_GENRE_DEFAULT']) vi.stubEnv(name, env[name]);
  const root = await makeTestRoot();
  cleanup.push(() => removeTestRoot(root));
  const config = { ...loadConfig({}, process.cwd()), runtimeRoot: root, pythonCommand: documentPythonCommand! };
  const native = new SpawnCommandRunner();
  const prompts: string[] = [];
  const runner = {
    async run(request: CommandRequest) {
      if (!request.args.includes('--output-last-message')) return native.run(request);
      const prompt = request.stdin!;
      prompts.push(prompt);
      const match = prompt.match(/BEGIN_SOURCE_([a-f0-9]+)\r?\n(.*?)\r?\nEND_SOURCE_\1/s)!;
      const batch = JSON.parse(match[2]!) as Batch;
      const reply = answer(batch, prompts.length, prompt);
      const hashes = new Map(batch.blocks.map(block => [block.id, block.sourceHash]));
      const output = {
        schemaVersion: 2, batchId: batch.batchId, sourceHash: batch.sourceHash, warnings: [],
        reviewedIds: reply.reviewedIds ?? batch.blocks.map(block => block.id),
        blocks: Object.entries(reply.edits).map(([id, edits]) => ({ id, sourceHash: hashes.get(id)!, edits }))
      };
      await writeFile(request.args[request.args.indexOf('--output-last-message') + 1]!, JSON.stringify(output));
      return { exitCode: 0, stdout: '', stderr: '', termination: 'exit' as const };
    }
  };
  const engine = new DocumentEngine(config, runner);
  const events: TransformEvent[] = [];
  const run = async () => {
    const state = await engine.prepare(path.resolve('tests/fixtures/documents/mixed.docx'));
    return engine.transform(state, 'codex', path.join(root, 'out'), new AbortController().signal, event => events.push(event));
  };
  return { prompts, events, run, root };
}
const idOf = (batch: Batch, text: string) => batch.blocks.find(block => block.text.includes(text))!.id;
const sourceOf = (prompt: string) => JSON.parse(prompt.match(/BEGIN_SOURCE_([a-f0-9]+)\r?\n(.*?)\r?\nEND_SOURCE_\1/s)![2]!) as Batch;

officeIt('v2: the plan-driven prompt, a retry of only the failed block, and the passed edit kept', async () => {
  const t = await setup({ SUPER_SEJONG_ENGINE: 'v2' }, (batch, attempt) => {
    if (attempt === 1) {
      return { edits: {
        [idOf(batch, '안정적인 운영')]: [{ before: '가지고 있다', after: '갖고 있다' }],     // fine
        [idOf(batch, '팀은 풍부한')]: [{ before: '가지고 있다', after: '가지고 있어요' }]      // 해라체 -> 해요체
      } };
    }
    return { edits: {} };   // the retry gives up on the failed block
  });
  const result = await t.run();
  expect(t.prompts).toHaveLength(2);
  const [first, second] = t.prompts as [string, string];
  // attempt 1: v2 sections, the Office edit protocol, no rulebook text
  for (const marker of ['[편집 형식]', '[열린 검토]\n', '[출력 형식]', 'BEGIN_SOURCE_']) expect(first).toContain(marker);
  expect(first).not.toContain('한국어 규칙:');
  expect(first).not.toContain('Quick Rules');
  expect(first).not.toContain('[재시도]');
  expect(sourceOf(first).blocks.length).toBeGreaterThan(2);
  // attempt 2: only the failed block, its violation in Korean, still no rulebook
  expect(second).toContain('[재시도]');
  const retried = sourceOf(second).blocks;
  expect(retried.map(block => block.text)).toEqual(['팀은 풍부한 경험을 가지고 있다.']);
  expect(second).toContain(`${retried[0]!.id} 이전 답: 말투가 해라체에서 해요체로 바뀌었다(voice_level).`);
  expect(second).not.toContain('한국어 규칙:');
  expect(second).not.toContain('Quick Rules');
  // result: the passed edit is in, the failed block is the writer-free original
  expect(result.state.preview).toContain('안정적인 운영 역량을 갖고 있다.');
  expect(result.state.preview).toContain('팀은 풍부한 경험을 가지고 있다.');
  expect(result.state.preview).not.toContain('가지고 있어요');
  const warnings = t.events.filter(event => event.type === 'warning').map(event => (event as { message: string }).message);
  expect(warnings.some(message => message.includes('편집 검증 후 재시도합니다') && message.includes('voice_level'))).toBe(true);
  // giving up on the retry is a valid answer (no edit), not a rollback
  expect(warnings.some(message => message.includes('원문을 유지했습니다'))).toBe(false);
}, 30000);

officeIt('v2: a block that fails twice is restored while the rest of its batch keeps its edits', async () => {
  const bad = { before: '가지고 있다', after: '가지고 있어요' };
  const t = await setup({ SUPER_SEJONG_ENGINE: 'v2' }, (batch, attempt) => attempt === 1
    ? { edits: { [idOf(batch, '안정적인 운영')]: [{ before: '가지고 있다', after: '갖고 있다' }], [idOf(batch, '팀은 풍부한')]: [bad] } }
    : { edits: { [idOf(batch, '팀은 풍부한')]: [bad] } });
  const result = await t.run();
  expect(t.prompts).toHaveLength(2);
  expect(result.state.preview).toContain('안정적인 운영 역량을 갖고 있다.');
  expect(result.state.preview).toContain('팀은 풍부한 경험을 가지고 있다.');
  const warnings = t.events.filter(event => event.type === 'warning').map(event => (event as { message: string }).message);
  expect(warnings.some(message => message.includes('원문을 유지했습니다'))).toBe(true);
}, 30000);

officeIt('v2: an empty plan makes no model call and returns the document unchanged', async () => {
  const t = await setup({ SUPER_SEJONG_ENGINE: 'v2', SUPER_SEJONG_OPEN_REVIEW: 'off' }, () => {
    throw new Error('the model must not be called');
  });
  const result = await t.run();
  expect(t.prompts).toEqual([]);
  expect(result.state.status).toBe('done');
  expect(result.state.outputChars).toBe(result.state.sourceChars);
  expect(result.state.preview).toContain('가지고 있다');
  expect(result.bytes).toBeGreaterThan(0);
}, 30000);

officeIt('v2: one call per batch with the open review, and every asked block is reviewed', async () => {
  const t = await setup({ SUPER_SEJONG_ENGINE: 'v2' }, () => ({ edits: {} }));
  const result = await t.run();
  expect(t.prompts).toHaveLength(1);
  expect(result.state.status).toBe('done');
  expect(sourceOf(t.prompts[0]!).blocks.length).toBeGreaterThan(0);
}, 30000);

officeIt('legacy: the prompt still embeds the vendor rulebook and is the one it was', async () => {
  const t = await setup({}, () => ({ edits: {} }));
  const rules = await readFile(path.resolve('vendor/humanize-engine/skills/humanize-korean/references/quick-rules.md'), 'utf8');
  await t.run();
  expect(t.prompts).toHaveLength(1);
  const prompt = t.prompts[0]!;
  expect(prompt).toContain(`한국어 규칙:\n${rules}\n`);
  expect(prompt).toContain('모든 블록에 룰북을 적용해 검토한 뒤');
  expect(prompt).not.toContain('[편집 형식]');
  expect(prompt).not.toContain('[말투 시트]');
}, 30000);
