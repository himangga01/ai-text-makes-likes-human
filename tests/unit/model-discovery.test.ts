import { readFile } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  CLAUDE_DISCOVERY_ARGS, discoverClaudeModels, discoverCodexModels, discoverModels, mapClaudeModels, mapCodexModels,
  ModelDiscoveryError, type DiscoveryOptions
} from '../../src/runtime/model-discovery.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';

const fixtures = path.resolve('tests/fixtures/model-discovery');
const lists = JSON.parse(readFileSync(path.join(fixtures, 'model-lists.json'), 'utf8')) as { codex: unknown[]; claude: unknown[] };
const fakeCodex = [path.join(fixtures, 'fake-codex-app-server.mjs')], fakeClaude = [path.join(fixtures, 'fake-claude-control.mjs')];
const full = ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'], five = full.slice(0, 5);
const claudeIds = ['claude-opus-5-5', 'claude-fable-5-2', 'claude-sonnet-5-5', 'claude-haiku-5-5', 'claude-fable-5-1', 'claude-sonnet-5',
  'claude-opus-5', 'claude-fable-5', 'claude-opus-4-8', 'claude-opus-4-7', 'claude-opus-4-6', 'claude-sonnet-4-6'];

function alive(pid: number): boolean {
  try { process.kill(pid, 0); return true; } catch { return false; }
}
async function rejection(promise: Promise<unknown>): Promise<ModelDiscoveryError> {
  const error = await promise.then(() => undefined, (reason: unknown) => reason);
  expect(error).toBeInstanceOf(ModelDiscoveryError);
  return error as ModelDiscoveryError;
}

describe('mapCodexModels', () => {
  it('maps the live catalog shape: labels, efforts, default and hidden models', () => {
    const mapped = mapCodexModels(lists.codex);
    expect(mapped.models.map(model => [model.id, model.label])).toEqual([
      ['gpt-6.1-sol', 'GPT-6.1 Sol'], ['gpt-6-astra', 'GPT-6 Astra'], ['gpt-6.1-terra', 'GPT-6.1 Terra'], ['gpt-6-sol', 'GPT-6 Sol'],
      ['gpt-6-luna', 'GPT-6 Luna'], ['gpt-5.6-sol', 'GPT-5.6 Sol'], ['gpt-5.6-terra', 'GPT-5.6 Terra'], ['gpt-5.6-luna', 'GPT-5.6 Luna']
    ]);
    expect(mapped.models[0]!.efforts).toEqual(full);
    expect(mapped.models.find(model => model.id === 'gpt-6-luna')!.efforts).toEqual(five);
    expect(mapped.cliDefault).toEqual({ model: 'gpt-6.1-sol', effort: 'low' });
    expect(mapped.excluded).toEqual([{ id: 'gpt-reserve', reason: 'hidden' }, { id: 'codex-auto-review', reason: 'hidden' }]);
  });
  it('excludes models without efforts, falls back to the id and skips duplicates and malformed entries', () => {
    const mapped = mapCodexModels([
      null, 'gpt-x', { displayName: 'No id' }, { id: '--model', supportedReasoningEfforts: ['low'] },
      { id: 'gpt-a', displayName: '', supportedReasoningEfforts: [{ reasoningEffort: 'high' }, { reasoningEffort: 'high' }, { reasoningEffort: 7 }] },
      { id: 'gpt-a', displayName: 'GPT-A-Duplicate', supportedReasoningEfforts: [{ reasoningEffort: 'low' }] },
      { id: 'gpt-oss', displayName: 'GPT-OSS-Mini', supportedReasoningEfforts: [{ reasoningEffort: 'low' }] },
      { id: 'gpt-b', displayName: 'GPT-B', isDefault: true, supportedReasoningEfforts: [] },
      { id: 'gpt-c', displayName: 'GPT-C', isDefault: true, defaultReasoningEffort: 'high', supportedReasoningEfforts: [{ reasoningEffort: 'high' }] }
    ]);
    expect(mapped.models).toEqual([
      { id: 'gpt-a', label: 'gpt-a', efforts: ['high'] }, { id: 'gpt-oss', label: 'GPT-OSS Mini', efforts: ['low'] },
      { id: 'gpt-c', label: 'GPT-C', efforts: ['high'] }
    ]);
    expect(mapped.excluded).toEqual([{ id: 'gpt-b', reason: 'no-effort' }]);
    expect(mapped.cliDefault).toEqual({ model: 'gpt-b' });
  });
});

describe('mapClaudeModels', () => {
  it('maps the live list: aliases supply labels, the default entry only sets the default', () => {
    const mapped = mapClaudeModels(lists.claude);
    expect(mapped.models.map(model => model.id)).toEqual(claudeIds);
    expect(mapped.models.slice(0, 5).map(model => model.label)).toEqual(['Claude Opus 5.5', 'Claude Fable 5.2', 'Claude Sonnet 5.5', 'Claude Haiku 5.5', 'Claude Fable 5.1']);
    expect(mapped.models.find(model => model.id === 'claude-opus-4-7')!.efforts).toEqual(five);
    expect(mapped.models.find(model => model.id === 'claude-sonnet-4-6')!.efforts).toEqual(['low', 'medium', 'high', 'max']);
    expect(mapped.cliDefault).toEqual({ model: 'claude-opus-5-5' });
    expect(mapped.excluded).toEqual([{ id: 'claude-haiku-4-5-20251001', reason: 'no-effort' }]);
  });
  it('keeps the first non-default occurrence and does not invent a default without effort levels', () => {
    const mapped = mapClaudeModels([
      { value: 'default', resolvedModel: 'claude-new-1', displayName: 'Default (recommended)' },
      { value: 'opus', resolvedModel: 'claude-opus-9', displayName: 'Opus 9', supportsEffort: true, supportedEffortLevels: ['high'] },
      { value: 'claude-opus-9', displayName: 'Opus 9 (pinned)', supportsEffort: true, supportedEffortLevels: ['low'] },
      { value: 'claude-sonnet-9', displayName: 'Claude Sonnet 9', supportsEffort: true, supportedEffortLevels: ['low', 'high'] },
      { value: 'claude-bare', displayName: '', supportsEffort: true, supportedEffortLevels: ['low'] },
      { value: 'claude-flagless', displayName: 'Flagless', supportedEffortLevels: ['low'] },
      { value: 'claude-levelless', displayName: 'Levelless', supportsEffort: true, supportedEffortLevels: [] }
    ]);
    expect(mapped.models).toEqual([
      { id: 'claude-opus-9', label: 'Claude Opus 9', efforts: ['high'] }, { id: 'claude-sonnet-9', label: 'Claude Sonnet 9', efforts: ['low', 'high'] },
      { id: 'claude-bare', label: 'claude-bare', efforts: ['low'] }
    ]);
    expect(mapped.excluded).toEqual([{ id: 'claude-flagless', reason: 'no-effort' }, { id: 'claude-levelless', reason: 'no-effort' }]);
    expect(mapped.cliDefault).toEqual({ model: 'claude-new-1' });
  });
  it('adds the default model when only the default entry carries its effort levels', () => {
    const levels = { supportsEffort: true, supportedEffortLevels: ['low', 'max'] };
    expect(mapClaudeModels([
      { value: 'default', resolvedModel: 'claude-new-1', displayName: 'Default (recommended)', ...levels },
      { value: 'claude-old', displayName: 'Old', ...levels }
    ]).models).toEqual([{ id: 'claude-new-1', label: 'claude-new-1', efforts: ['low', 'max'] }, { id: 'claude-old', label: 'Claude Old', efforts: ['low', 'max'] }]);
    const listedWithoutLevels = mapClaudeModels([
      { value: 'default', resolvedModel: 'claude-new-1', displayName: 'Default (recommended)', ...levels },
      { value: 'claude-new-1', displayName: 'New 1' }
    ]);
    expect(listedWithoutLevels.models).toEqual([{ id: 'claude-new-1', label: 'Claude New 1', efforts: ['low', 'max'] }]);
    expect(listedWithoutLevels.excluded).toEqual([]);
    expect(mapClaudeModels([{ value: 'default', displayName: 'Default' }]).cliDefault).toBeUndefined();
  });
});

describe('model discovery over the CLI protocols', () => {
  let root: string, pidFile: string, logFile: string;
  beforeEach(async () => { root = await makeTestRoot('models-'); pidFile = path.join(root, 'pid'); logFile = path.join(root, 'log.jsonl'); });
  afterEach(async () => {
    const pid = Number(await readFile(pidFile, 'utf8').catch(() => '0'));
    if (pid > 0 && alive(pid)) process.kill(pid, 'SIGKILL');
    await removeTestRoot(root);
  });
  const options = (mode: string, extra: Partial<DiscoveryOptions> = {}): DiscoveryOptions =>
    ({ cwd: root, timeoutMs: 10_000, env: { FAKE_MODE: mode, FAKE_PID_FILE: pidFile, FAKE_LOG_FILE: logFile, FAKE_PAGE_SIZE: '3' }, ...extra });
  const childPid = async (): Promise<number> => Number(await readFile(pidFile, 'utf8'));
  const sent = async (): Promise<Record<string, any>[]> => (await readFile(logFile, 'utf8')).trim().split('\n').map(line => JSON.parse(line));

  it('lists Codex models through initialize and paged model/list, ignoring notifications, then stops the child', async () => {
    const catalog = await discoverCodexModels(process.execPath, options('ok'), fakeCodex);
    expect(catalog).toEqual({ engine: 'codex', ...mapCodexModels(lists.codex), excluded: [], cliVersion: '0.167.0' });
    expect(catalog.models).toHaveLength(8);
    const messages = await sent();
    expect(messages.map(message => message.method)).toEqual(['initialize', 'initialized', 'model/list', 'model/list', 'model/list']);
    expect(messages[0]).toMatchObject({ jsonrpc: '2.0', id: 1, params: { clientInfo: { name: 'humanize-portal', title: '윤문 포털', version: '0.5.0' } } });
    expect(messages[1]).not.toHaveProperty('id');
    expect(messages.slice(2).map(message => message.params)).toEqual([
      { includeHidden: false, limit: 100 }, { includeHidden: false, limit: 100, cursor: 'page-3' }, { includeHidden: false, limit: 100, cursor: 'page-6' }
    ]);
    expect(alive(await childPid())).toBe(false);
  });
  it('filters hidden Codex models even when the server returns them', async () => {
    const catalog = await discoverCodexModels(process.execPath, options('leak-hidden'), fakeCodex);
    expect(catalog.models.map(model => model.id)).not.toContain('gpt-reserve');
    expect(catalog.excluded).toEqual([{ id: 'gpt-reserve', reason: 'hidden' }, { id: 'codex-auto-review', reason: 'hidden' }]);
  });
  it('reports a JSON-RPC error as a protocol failure', async () => {
    const error = await rejection(discoverCodexModels(process.execPath, options('rpc-error'), fakeCodex));
    expect(error.code).toBe('protocol');
    expect(error.message).toContain('model catalog unavailable');
    expect(alive(await childPid())).toBe(false);
  });
  it('kills a CLI that never answers once the timeout expires', async () => {
    const started = Date.now();
    const error = await rejection(discoverCodexModels(process.execPath, options('silent', { timeoutMs: 1_000 }), fakeCodex));
    expect(error.code).toBe('timeout');
    expect(Date.now() - started).toBeLessThan(5_000);
    expect(alive(await childPid())).toBe(false);
  });
  it('reports a CLI that exits before answering with its exit code and last stderr line', async () => {
    const error = await rejection(discoverCodexModels(process.execPath, options('exit'), fakeCodex));
    expect(error.code).toBe('protocol');
    expect(error.message).toMatch(/code 3.*config could not be loaded/);
  });
  it('rejects a catalog without selectable models as empty', async () => {
    const error = await rejection(discoverCodexModels(process.execPath, options('empty'), fakeCodex));
    expect(error.code).toBe('empty');
    expect(alive(await childPid())).toBe(false);
  });
  it('kills a child that keeps running after stdin closes', async () => {
    const started = Date.now();
    const catalog = await discoverCodexModels(process.execPath, options('linger'), fakeCodex);
    expect(catalog.models).toHaveLength(8);
    expect(Date.now() - started).toBeGreaterThanOrEqual(1_900);
    expect(alive(await childPid())).toBe(false);
  }, 10_000);
  it('reports a missing executable as a spawn failure', async () => {
    const missing = path.join(root, 'no-such-cli');
    expect((await rejection(discoverModels('codex', missing, { cwd: root }))).code).toBe('spawn');
    expect((await rejection(discoverModels('claude', missing, { cwd: root }))).code).toBe('spawn');
  });

  it('lists Claude models from the initialize control response, skipping other events', async () => {
    const catalog = await discoverClaudeModels(process.execPath, options('ok'), fakeClaude);
    expect(catalog).toEqual({ engine: 'claude', ...mapClaudeModels(lists.claude), cliVersion: '2.1.323' });
    expect(catalog.models.map(model => model.id)).toEqual(claudeIds);
    const messages = await sent();
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({ type: 'control_request', request: { subtype: 'initialize' } });
    expect(messages[0]!.request_id).toMatch(/^models-/);
    expect(CLAUDE_DISCOVERY_ARGS).toContain('');
    expect(alive(await childPid())).toBe(false);
  });
  it('reports a Claude control error, an early exit and an empty list', async () => {
    const failed = await rejection(discoverClaudeModels(process.execPath, options('error'), fakeClaude));
    expect([failed.code, failed.message]).toEqual(['protocol', expect.stringContaining('Already initialized')]);
    const exited = await rejection(discoverClaudeModels(process.execPath, options('exit'), fakeClaude));
    expect([exited.code, exited.message]).toEqual(['protocol', expect.stringMatching(/code 1.*Invalid API key/)]);
    expect((await rejection(discoverClaudeModels(process.execPath, options('empty'), fakeClaude))).code).toBe('empty');
  });
  it('kills a Claude CLI that never answers', async () => {
    const error = await rejection(discoverClaudeModels(process.execPath, options('silent', { timeoutMs: 1_000 }), fakeClaude));
    expect(error.code).toBe('timeout');
    expect(alive(await childPid())).toBe(false);
  });
});
