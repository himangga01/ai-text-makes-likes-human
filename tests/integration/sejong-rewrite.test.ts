// Strength rewrite, 매우 강하게(다시쓰기) (WP-19), end to end: SejongEngine on the real v2 Python CLI with stub writers
// (no writer CLI runs). Text comes from the constructed pairs of tests/skills/data/sejong_rewrite_pairs.json.
import { readFileSync } from 'node:fs';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { HumanizeResult } from '../../src/engine/humanize-engine.js';
import { SejongEngine, type SejongWriter } from '../../src/engine/sejong/engine.js';
import { SejongPython } from '../../src/engine/sejong/python-adapter.js';
import { JobWorkspace } from '../../src/engine/workspace.js';
import { SpawnCommandRunner } from '../../src/process/command-runner.js';
import { pythonCommand } from '../helpers/python-command.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';

const root = path.resolve('.');
const schemaPath = path.join(root, 'src/engine/sejong/response-schema.json');
const env: NodeJS.ProcessEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('SUPER_SEJONG_')));
type Pair = { id: string; source: string; rewrite: string };
const pairs = new Map((JSON.parse(readFileSync(path.join(root, 'tests/skills/data/sejong_rewrite_pairs.json'), 'utf8')) as { pairs: Pair[] })
  .pairs.map(pair => [pair.id, pair]));
const pair = (id: string): Pair => pairs.get(id)!;
const paragraphs = (text: string): string[] => text.trim().split(/\n\s*\n/u);

class StubWriter implements SejongWriter {
  readonly prompts: string[] = [];
  constructor(private readonly reply: (prompt: string, attempt: 1 | 2) => string) {}
  async runPrompt(prompt: string, schema: string, outputPath: string): Promise<string> {
    expect(schema).toBe(schemaPath);
    this.prompts.push(prompt);
    const raw = this.reply(prompt, prompt.includes('[재시도]') ? 2 : 1);
    await writeFile(outputPath, raw, 'utf8');
    return raw;
  }
}

const full = (text: string): string => JSON.stringify({ replacements: [], rewrittenText: text, warnings: [] });
const byParagraph = (items: Array<[string, string]>): string =>
  JSON.stringify({ replacements: items.map(([id, text]) => ({ id, text, reason: 'retry' })), rewrittenText: '', warnings: [] });
/** Paragraph ids named by the [재시도] section of a retry prompt. */
const retried = (prompt: string): string[] => [...prompt.matchAll(/^(P\d+) 이전 답:/gmu)].map(match => match[1]!);

let outer = '';
beforeEach(async () => { outer = await makeTestRoot('sejong-rewrite-'); });
afterEach(async () => { await removeTestRoot(outer); });

async function run(source: string, writer: SejongWriter) {
  const workspace = await JobWorkspace.create(outer, `job-${Math.random().toString(36).slice(2)}`);
  await writeFile(workspace.path('01_input.txt'), source, 'utf8');
  const engine = new SejongEngine({
    python: new SejongPython({ pythonCommand, engineRoot: path.join(root, 'engine_runtime'), runner: new SpawnCommandRunner(), env }),
    writer, schemaPath, chunkConcurrency: 1, env
  });
  const result: HumanizeResult = await engine.transform({
    jobId: workspace.jobId, workspace, signal: new AbortController().signal, onEvent: () => undefined,
    rewriteOptions: { inputKind: 'direct-text', strength: 'rewrite' }
  });
  return { result, output: await readFile(result.finalPath, 'utf8') };
}

const codes = (result: HumanizeResult): string[] => result.warnings.map(warning => warning.code);

describe('SejongEngine at strength rewrite', () => {
  it('delivers a whole rewrite whose paragraphs keep their voice, gated by paragraph', async () => {
    // G12 normalises a 해요 request to 하십시오 inside a 합쇼 paragraph: the edit gate would report voice_level.
    const writer = new StubWriter(() => full(pair('G12').rewrite));
    const { result, output } = await run(pair('G12').source, writer);
    expect(writer.prompts).toHaveLength(1);
    expect(writer.prompts[0]).toContain('문단별로 다시 쓴다');
    expect(writer.prompts[0]).toContain('[문단 말투]');
    expect(output).toBe(pair('G12').rewrite);
    expect(codes(result)).toEqual([]);
    expect(result.diagnostics).toMatchObject({ engine: 'v2', requestedStrength: 'rewrite', codexCalls: 1, retries: 0,
      rolledBackChunks: 0, fullSourceRollbacks: 0 });
  });

  it('retries a drifting paragraph by its id and reverts it alone', async () => {
    const damaged = pair('D21');
    const writer = new StubWriter((prompt, attempt) => attempt === 1
      ? full(damaged.rewrite)
      : byParagraph(retried(prompt).map(id => [id, paragraphs(damaged.rewrite)[Number(id.slice(1)) - 1]!])));
    const { result, output } = await run(damaged.source, writer);
    expect(writer.prompts).toHaveLength(2);
    expect(retried(writer.prompts[1]!)).toEqual(['P2']);
    expect(writer.prompts[1]).toContain('이 문단은 모든 문장을 해요체로 끝내야 하는데 합쇼체 문장이 있었다(voice_level).');
    const [p1, p2, p3] = paragraphs(output);
    expect([p1, p3]).toEqual([paragraphs(damaged.rewrite)[0], paragraphs(damaged.rewrite)[2]]);
    expect(p2).toBe(paragraphs(damaged.source)[1]);
    expect(codes(result)).toEqual(expect.arrayContaining(['CHUNK_RETRY', 'SEJONG_SENTENCES_REVERTED']));
    expect(result.warnings.find(w => w.code === 'CHUNK_RETRY')!.message).toContain('문단만 한 번 더 다시 씁니다');
    expect(result.warnings.find(w => w.code === 'SEJONG_SENTENCES_REVERTED')!.message).toContain('문단 1개를 원래 문단으로');
    expect(result.diagnostics).toMatchObject({ codexCalls: 2, retries: 1, sentenceRetries: 1, revertedSentences: { voice: 2 } });
  });

  it('counts a reply with another paragraph count as unusable and asks again by paragraph', async () => {
    const merged = pair('D24');
    const good = paragraphs(pair('G01').rewrite);
    const writer = new StubWriter((prompt, attempt) => attempt === 1
      ? full(merged.rewrite)
      : byParagraph(retried(prompt).map(id => [id, good[Number(id.slice(1)) - 1]!])));
    const { result, output } = await run(merged.source, writer);
    expect(retried(writer.prompts[1]!)).toEqual(['P1', 'P2', 'P3']);
    expect(output).toBe(pair('G01').rewrite);
    expect(codes(result)).toEqual(expect.arrayContaining(['MODEL_OUTPUT_UNUSABLE', 'CHUNK_RETRY']));
    expect(result.diagnostics).toMatchObject({ codexCalls: 2, unusableModelOutputs: 1 });
  });
});
