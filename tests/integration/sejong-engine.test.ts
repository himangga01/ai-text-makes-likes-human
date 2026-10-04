// SejongEngine end to end on the real v2 Python CLI (engine_runtime/sejong_cli.py) with stub writers: the
// writer CLIs (Codex, Claude) are never run. Constructed text only, plus the seed composites of
// docs/research/super-sejong/v2/benchmark (original text, CC0-1.0 proposed).
import { readFileSync } from 'node:fs';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { TransformEvent } from '../../src/contracts.js';
import type { HumanizeResult } from '../../src/engine/humanize-engine.js';
import type { ModelSettings } from '../../src/engine/model-policy.js';
import type { RewriteOptions } from '../../src/engine/rewrite-policy.js';
import { SejongEngine, type SejongWriter } from '../../src/engine/sejong/engine.js';
import { SejongPython } from '../../src/engine/sejong/python-adapter.js';
import { JobWorkspace } from '../../src/engine/workspace.js';
import { SpawnCommandRunner } from '../../src/process/command-runner.js';
import { pythonCommand } from '../helpers/python-command.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';

const root = path.resolve('.');
const schemaPath = path.join(root, 'src/engine/sejong/response-schema.json');
const quickRules = readFileSync(path.join(root, 'vendor/humanize-engine/skills/humanize-korean/references/quick-rules.md'), 'utf8');
// SUPER_SEJONG_* variables of the developer's shell must not change what these tests see.
const env: NodeJS.ProcessEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('SUPER_SEJONG_')));

interface Item { id: string; sentence: string; text: string }
type Reply = (prompt: string, attempt: 1 | 2) => string;

/** Items of one nonce block of a v2 prompt (REQUESTS or SENTENCES). */
export function promptBlock(prompt: string, name: 'REQUESTS' | 'SENTENCES'): Item[] {
  const match = new RegExp(`BEGIN_${name}_([0-9A-Za-z]+)\\n([\\s\\S]*?)\\nEND_${name}_\\1`, 'u').exec(prompt);
  return match ? (JSON.parse(match[2]!) as Array<Partial<Item>>).map(item => ({ id: item.id!, sentence: item.sentence ?? item.id!, text: item.text! })) : [];
}

class StubWriter implements SejongWriter {
  readonly prompts: string[] = [];
  readonly settings: Array<ModelSettings | undefined> = [];
  constructor(private readonly reply: Reply) {}
  async runPrompt(prompt: string, schema: string, outputPath: string, _signal: AbortSignal, settings?: ModelSettings): Promise<string> {
    expect(schema).toBe(schemaPath);
    this.prompts.push(prompt);
    this.settings.push(settings);
    const raw = this.reply(prompt, prompt.includes('[재시도]') ? 2 : 1);
    await writeFile(outputPath, raw, 'utf8');
    return raw;
  }
}

const json = (replacements: Array<{ id: string; text: string; reason?: string }>): string =>
  JSON.stringify({ replacements: replacements.map(item => ({ reason: 'SSJ', ...item })), rewrittenText: '', warnings: [] });

let outer = '';
beforeEach(async () => { outer = await makeTestRoot('sejong-engine-'); });
afterEach(async () => { await removeTestRoot(outer); });

async function run(source: string, writer: SejongWriter, rewriteOptions?: RewriteOptions, extraEnv: NodeJS.ProcessEnv = {}) {
  const workspace = await JobWorkspace.create(outer, `job-${Math.random().toString(36).slice(2)}`);
  await writeFile(workspace.path('01_input.txt'), source, 'utf8');
  const jobEnv = { ...env, ...extraEnv };
  const engine = new SejongEngine({
    python: new SejongPython({ pythonCommand, engineRoot: path.join(root, 'engine_runtime'), runner: new SpawnCommandRunner(), env: jobEnv }),
    writer, schemaPath, chunkConcurrency: 1, env: jobEnv
  });
  const events: TransformEvent[] = [];
  const result: HumanizeResult = await engine.transform({
    jobId: workspace.jobId, workspace, signal: new AbortController().signal, onEvent: event => events.push(event),
    ...(rewriteOptions ? { rewriteOptions } : {})
  });
  const output = await readFile(result.finalPath, 'utf8');
  return { result, output, events, workspace };
}

const codes = (result: HumanizeResult): string[] => result.warnings.map(warning => warning.code);

describe('SejongEngine with the real Python CLI', () => {
  it('makes no writer call on an empty plan and still applies the deterministic fixes', async () => {
    const writer = new StubWriter(() => { throw new Error('the writer must not be called'); });
    const source = '회의는 오전 10시에 시작합니다. 참가비는 3만 원이 됬습니다.\n';
    const { result, output, events } = await run(source, writer, { inputKind: 'direct-text', strength: 'normal' });
    expect(writer.prompts).toHaveLength(0);
    expect(output).toBe('회의는 오전 10시에 시작합니다. 참가비는 3만 원이 됐습니다.\n');
    expect(codes(result)).toEqual(['SEJONG_NO_EDIT_NEEDED']);
    expect(result.warnings[0]!.message).toContain('맞춤법 오류 1곳');
    expect(result.diagnostics).toMatchObject({
      engine: 'v2', requestedStrength: 'normal', codexCalls: 0, retries: 0, chunksWithoutModelCall: 1, normFixes: 1,
      planRequests: { FIX: 0, SUGGEST: 0, REVIEW: 0 }, bodyChunks: 1, processingMode: 'single', routeHint: null,
      gateCodes: ['GATE_OK', 'GATE_OK'], rolledBackChunks: 0, fullSourceRollbacks: 0
    });
    expect(events.filter(event => event.type === 'progress').map(event => (event as { phase: string }).phase))
      .toEqual(['sanitize', 'chunk', 'transform', 'verify', 'assemble']);
    expect(result.outputChars).toBe(Array.from(output).length);
  });

  it('treats a request without options as a text file: normal strength, no open review', async () => {
    const writer = new StubWriter(() => { throw new Error('the writer must not be called'); });
    const source = '회의는 오전 10시에 시작합니다. 자료는 미리 읽어 오세요.\n';
    const { result, output } = await run(source, writer);
    expect([writer.prompts.length, output, result.diagnostics.requestedStrength]).toEqual([0, source, undefined]);
  });

  it('sends one prompt for the open review at medium and delivers an accepted edit', async () => {
    const source = '오늘은 세미나 후기를 정리합니다. 발표 자료가 많이 도움이 되었습니다.\n';
    const writer = new StubWriter(prompt => {
      const sentences = promptBlock(prompt, 'SENTENCES');
      const target = sentences.find(item => item.text.includes('많이 도움이'));
      return json(target ? [{ id: target.id, text: target.text.replace('많이 도움이 되었습니다', '큰 도움이 되었습니다'), reason: '22 어휘상 잘못된 표현' }] : []);
    });
    const { result, output } = await run(source, writer, { inputKind: 'direct-text', strength: 'medium' });
    expect(writer.prompts).toHaveLength(1);
    expect(writer.prompts[0]).toContain('[열린 검토]');
    expect(writer.prompts[0]).not.toContain('quick_rules');
    expect(output).toBe('오늘은 세미나 후기를 정리합니다. 발표 자료가 큰 도움이 되었습니다.\n');
    expect(result.diagnostics).toMatchObject({ codexCalls: 1, retries: 0, chunksWithoutModelCall: 0, planRequests: { REVIEW: 1 } });
    expect(codes(result)).not.toContain('SEJONG_NO_EDIT_NEEDED');
  });

  it('retries only the failed sentence with its named violation, then reverts what still fails', async () => {
    const source = '오늘은 세미나 후기를 정리합니다. 발표 자료가 많이 도움이 되었습니다.\n';
    const writer = new StubWriter((prompt, attempt) => {
      const items = attempt === 1 ? promptBlock(prompt, 'SENTENCES') : promptBlock(prompt, 'REQUESTS');
      const target = items.find(item => item.text.includes('도움이'));
      // A negation the source does not have: polarity_changed (meaning, enforced) both times.
      return json(target ? [{ id: target.id, text: target.text.replace('도움이 되었습니다', '도움이 되지 않았습니다'), reason: '22 어휘상 잘못된 표현' }] : []);
    });
    const { result, output, workspace } = await run(source, writer, { inputKind: 'direct-text', strength: 'medium' });
    expect(writer.prompts).toHaveLength(2);
    const retry = writer.prompts[1]!;
    expect(retry).toContain('[재시도]');
    expect(retry).toMatch(/S2 이전 답: 긍정·부정이 바뀌었다[^\n]*\(polarity_changed\)\./u);
    expect(promptBlock(retry, 'REQUESTS').map(item => item.id)).toEqual(['S2']);
    expect(retry).not.toContain('[열린 검토]');
    expect(retry).not.toContain('[문서 말투 참고]');
    for (const line of quickRules.split('\n').filter(text => text.trim().length > 30)) expect(retry).not.toContain(line.trim());
    expect(output).toBe(source);
    expect(codes(result)).toEqual(expect.arrayContaining(['CHUNK_RETRY', 'SEJONG_SENTENCES_REVERTED']));
    expect(result.diagnostics).toMatchObject({ codexCalls: 2, retries: 1, sentenceRetries: 1, revertedSentences: { meaning: 1 }, restoredSentences: 1 });
    expect(result.diagnostics.hardFailureCounts).toEqual({});
    // The check reports of both attempts stay in the workspace; the reply files hold what Python received.
    expect(JSON.parse(await readFile(workspace.path('check-1-attempt-2.json'), 'utf8')).attempt).toBe(2);
  });

  it('fails the job like the legacy engine when every writer reply is unusable', async () => {
    const source = '오늘은 세미나 후기를 정리합니다. 발표 자료가 많이 도움이 되었습니다.\n';
    const writer = new StubWriter(() => '```json\n{}\n```');
    await expect(run(source, writer, { inputKind: 'direct-text', strength: 'medium' }))
      .rejects.toMatchObject({ publicCode: 'ENGINE_OUTPUT_INVALID', message: 'Every chunk returned unusable model output' });
    expect(writer.prompts).toHaveLength(1);
  });
});

interface Injection { span: [number, number]; before: string; gold_fix: string; primary: boolean }
interface Composite { id: string; text: string; gold_text: string; injections: Injection[] }
const composites = readFileSync(path.join(root, 'docs/research/super-sejong/v2/benchmark/seed_composites.jsonl'), 'utf8')
  .trim().split('\n').map(line => JSON.parse(line) as Composite);

/** The gold version of one source sentence: every injection inside an occurrence of it, fixed; null when none. */
function goldSentence(record: Composite, text: string): string | null {
  for (let at = record.text.indexOf(text); at >= 0; at = record.text.indexOf(text, at + 1)) {
    const end = at + text.length;
    const inside = record.injections.filter(item => item.span[0] >= at && item.span[1] <= end).sort((a, b) => a.span[0] - b.span[0]);
    if (!inside.length) continue;
    let out = '', last = at;
    for (const item of inside) {
      out += record.text.slice(last, item.span[0]) + item.gold_fix;
      last = item.span[1];
    }
    return out + record.text.slice(last, end);
  }
  return null;
}

/** Tier-B stub writer (DESIGN 7, WP-15 protocol): every request or listed sentence whose gold version differs gets
 * that version as its replacement, the way the WP-10 Python stub derives replacements from gold_text. */
function goldWriter(record: Composite): StubWriter {
  return new StubWriter(prompt => {
    const seen = new Set<string>();
    const replacements: Array<{ id: string; text: string; reason: string }> = [];
    for (const item of [...promptBlock(prompt, 'REQUESTS'), ...promptBlock(prompt, 'SENTENCES')]) {
      const gold = seen.has(item.sentence) ? null : goldSentence(record, item.text);
      if (gold === null || gold === item.text) continue;
      seen.add(item.sentence);
      replacements.push({ id: item.id, text: gold, reason: '22 어휘상 잘못된 표현' });
    }
    return json(replacements.slice(0, 200));
  });
}

const A06_LICENSED = ['polarity_changed', 'modality_changed', 'lexical_polarity_changed'];

describe('Tier-B stub run on the six seed composites (real Python CLI, gold-derived replacements)', () => {
  // Measured on 2026-10-04 at medium/general: primary injections fixed 10/16, 11/13, 13/16, 11/13, 9/11, 73/92
  // (127/161); the rest sit outside the plan's requests and beyond the open-review limit. The document gate
  // still reports the codes an SSJ-A06 request licenses for its own repair (polarity, modality, lexical polarity;
  // check.LICENSED_BY_POLARITY_RULES), because it runs without plans; WP-10b added 별로/도저히/일절 to A06.
  it.each(composites.map(record => [record.id, record] as const))('%s', async (_id, record) => {
    const writer = goldWriter(record);
    const { result, output } = await run(record.text, writer, { inputKind: 'direct-text', strength: 'medium' });
    const d = result.diagnostics;
    expect(d.engine).toBe('v2');
    expect(d.unusableModelOutputs).toBe(0);
    expect([d.rolledBackChunks, d.fullSourceRollbacks]).toEqual([0, 0]);
    expect(codes(result)).not.toContain('DIRECT_TEXT_DOCUMENT_ROLLED_BACK');
    expect(Object.keys(d.hardFailureCounts ?? {}).filter(code => !A06_LICENSED.includes(code))).toEqual([]);
    // At most one call plus one targeted retry per chunk (G6).
    expect(d.codexCalls).toBeLessThanOrEqual(2 * d.bodyChunks);
    expect(writer.prompts.every(prompt => !prompt.includes('quick_rules') && !prompt.includes('<rewrite_policy>'))).toBe(true);
    // Paragraphs stay; a paragraph with no injection is delivered untouched.
    const sourceParagraphs = record.text.split('\n'), goldParagraphs = record.gold_text.split('\n'), outputParagraphs = output.split('\n');
    expect(outputParagraphs).toHaveLength(sourceParagraphs.length);
    const touched = sourceParagraphs.filter((paragraph, k) => paragraph === goldParagraphs[k] && outputParagraphs[k] !== paragraph);
    expect(touched).toEqual([]);
    // Every injection ends either fixed as gold or as the source wrote it; most primary ones are fixed.
    let fixed = 0, primaryFixed = 0, primary = 0;
    for (const item of record.injections) {
      const [start, end] = item.span;
      const left = record.text.slice(Math.max(0, start - 6), start), right = record.text.slice(end, end + 6);
      const isFixed = output.includes(left + item.gold_fix + right);
      if (isFixed) fixed += 1;
      if (item.primary) {
        primary += 1;
        if (isFixed) primaryFixed += 1;
      }
    }
    expect(fixed).toBeGreaterThan(0);
    expect(primaryFixed / primary).toBeGreaterThanOrEqual(0.5);
    expect(d.requestStatus?.FIXED).toBeGreaterThan(0);
  }, 60_000);
});
