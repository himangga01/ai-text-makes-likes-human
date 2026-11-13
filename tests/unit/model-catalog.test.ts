import { afterEach, describe, expect, it } from 'vitest';
import { FALLBACK_MODEL_OPTIONS, getModelDefaults, getModelOptions, resetModelCatalog, type EngineChoice } from '../../src/engine/model-policy.js';
import { ModelCatalogService, parseRequestModelSettings } from '../../src/runtime/model-catalog.js';
import { ModelDiscoveryError, type DiscoveredCatalog, type DiscoveredModel } from '../../src/runtime/model-discovery.js';
import type { ProviderHealth, ProviderHealthMap } from '../../src/runtime/provider-health.js';
import { deferred } from '../helpers/deferred.js';

const MINUTE = 60_000;
const efforts = ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'];
const model = (id: string, label = id): DiscoveredModel => ({ id, label, efforts });
const codexList = [model('gpt-6.1-sol', 'GPT-6.1 Sol'), model('gpt-7-nova', 'GPT-7 Nova')];

type Outcome = DiscoveredCatalog | Error | Promise<DiscoveredCatalog>;
function harness(outcomes: Partial<Record<EngineChoice, Outcome[]>> = {}) {
  let now = Date.parse('2026-11-13T09:00:00Z');
  const calls: EngineChoice[] = []; const logs: Record<string, unknown>[] = [];
  const service = new ModelCatalogService({
    now: () => now,
    logger: { info: value => logs.push(value), error: value => logs.push(value) },
    discover: async engine => {
      calls.push(engine);
      const next = outcomes[engine]?.shift() ?? { engine, models: engine === 'codex' ? codexList : [model('claude-opus-5-5')], excluded: [] };
      if (next instanceof Error) throw next;
      return next;
    }
  });
  return { service, calls, logs, advance: (ms: number) => { now += ms; }, get now() { return now; } };
}
const catalog = (models: DiscoveredModel[], extra: Partial<DiscoveredCatalog> = {}): DiscoveredCatalog => ({ engine: 'codex', models, excluded: [], ...extra });
const provider = (ready: boolean, version?: string): ProviderHealth => ({ ready, installed: true, authenticated: ready, version, message: '' });
const providers = (codex: ProviderHealth, claude: ProviderHealth = provider(false)): ProviderHealthMap => ({ codex, claude });
const settle = async () => { for (let n = 0; n < 5; n++) await new Promise(resolve => setImmediate(resolve)); };

afterEach(() => resetModelCatalog());

describe('ModelCatalogService', () => {
  it('serves the fallback list until a discovery succeeds, then the live list', async () => {
    const test = harness({ codex: [catalog(codexList, { cliVersion: '0.167.0' })] });
    expect(getModelOptions()).toEqual(FALLBACK_MODEL_OPTIONS);
    expect(test.service.status()).toEqual({ codex: { source: 'fallback' }, claude: { source: 'fallback' } });
    await test.service.refresh('codex');
    expect(getModelOptions().codex.map(item => item.id)).toEqual(['gpt-6.1-sol', 'gpt-7-nova']);
    expect(getModelOptions().claude).toBe(FALLBACK_MODEL_OPTIONS.claude);
    expect(test.service.status()).toEqual({ codex: { source: 'live', checkedAt: '2026-11-13T09:00:00.000Z', cliVersion: '0.167.0' }, claude: { source: 'fallback' } });
  });

  it('logs a changed list once with the added and removed ids, and nothing for an unchanged one', async () => {
    const test = harness({ codex: [catalog(codexList, { cliVersion: '0.167.0' }), catalog(codexList), catalog([model('gpt-7-nova', 'GPT-7 Nova'), model('gpt-7-luna')])] });
    await test.service.refresh('codex');
    expect(test.logs).toEqual([{ event: 'model_catalog_updated', engine: 'codex', count: 2, added: ['gpt-7-nova'],
      removed: FALLBACK_MODEL_OPTIONS.codex.map(item => item.id).filter(id => id !== 'gpt-6.1-sol'), cliVersion: '0.167.0' }]);
    await test.service.refresh('codex', { force: true });
    expect(test.logs).toHaveLength(1);
    await test.service.refresh('codex', { force: true });
    expect(test.logs[1]).toEqual({ event: 'model_catalog_updated', engine: 'codex', count: 2, added: ['gpt-7-luna'], removed: ['gpt-6.1-sol'], cliVersion: undefined });
  });

  it('keeps the last good list on failure and logs only the error code', async () => {
    const failure = Object.assign(new ModelDiscoveryError('timeout', 'stdout: account someone@example.com'), { stack: 'at /private/path' });
    const test = harness({ codex: [new ModelDiscoveryError('spawn', 'ENOENT /usr/local/bin/codex'), catalog(codexList), failure, new Error('unexpected')] });
    await test.service.refresh('codex');
    expect(getModelOptions().codex).toBe(FALLBACK_MODEL_OPTIONS.codex);
    expect(test.service.status().codex).toEqual({ source: 'fallback', lastError: 'spawn' });
    await test.service.refresh('codex', { force: true });
    await test.service.refresh('codex', { force: true });
    expect(getModelOptions().codex.map(item => item.id)).toEqual(['gpt-6.1-sol', 'gpt-7-nova']);
    expect(test.service.status().codex).toMatchObject({ source: 'live', lastError: 'timeout' });
    await test.service.refresh('codex', { force: true });
    expect(test.service.status().codex.lastError).toBe('protocol');
    const failures = test.logs.filter(entry => entry.event === 'model_catalog_failed');
    expect(failures).toEqual([{ event: 'model_catalog_failed', engine: 'codex', code: 'spawn' },
      { event: 'model_catalog_failed', engine: 'codex', code: 'timeout' }, { event: 'model_catalog_failed', engine: 'codex', code: 'protocol' }]);
    expect(JSON.stringify(test.logs)).not.toMatch(/example\.com|private|ENOENT/);
  });

  it('treats a list with no usable entry as an empty discovery', async () => {
    const test = harness({ codex: [catalog([{ id: 'gpt 7', label: 'x', efforts: ['low'] }])] });
    await test.service.refresh('codex');
    expect(getModelOptions().codex).toBe(FALLBACK_MODEL_OPTIONS.codex);
    expect(test.service.status().codex).toEqual({ source: 'fallback', lastError: 'empty' });
  });

  it('runs one discovery per engine at a time', async () => {
    const pending = deferred<DiscoveredCatalog>();
    const test = harness({ codex: [pending.promise] });
    const first = test.service.refresh('codex'); const second = test.service.refresh('codex', { force: true });
    test.service.refreshIfStale();
    await settle();
    expect(test.calls).toEqual(['codex', 'claude']);
    pending.resolve(catalog(codexList));
    await Promise.all([first, second]);
    expect(test.calls).toEqual(['codex', 'claude']);
  });

  it('keeps a successful list fresh for 10 minutes', async () => {
    const test = harness();
    await test.service.refresh('codex');
    test.advance(10 * MINUTE - 1); test.service.refreshIfStale(providers(provider(true, '0.167.0'))); await settle();
    expect(test.calls).toEqual(['codex']);
    test.advance(1); test.service.refreshIfStale(providers(provider(true, '0.167.0'))); await settle();
    expect(test.calls).toEqual(['codex', 'codex']);
  });

  it('retries a failed discovery no sooner than one minute later', async () => {
    const slow = () => new ModelDiscoveryError('timeout', 'slow');
    const test = harness({ codex: [slow(), slow(), catalog(codexList), slow()] });
    const poll = async (ms: number) => { test.advance(ms); test.service.refreshIfStale(providers(provider(true))); await settle(); };
    await poll(0);
    await poll(MINUTE - 1);
    expect(test.calls).toHaveLength(1);
    await poll(1);
    expect(test.calls).toHaveLength(2);
    await poll(MINUTE);
    expect(test.service.status().codex.source).toBe('live');
    // A failure after a success also holds the retry for a minute, though the list itself is stale by then.
    await poll(10 * MINUTE);
    expect(test.calls).toHaveLength(4);
    await poll(MINUTE - 1);
    expect(test.calls).toHaveLength(4);
    await poll(1);
    expect(test.calls).toHaveLength(5);
  });

  it('refreshes at once when the provider reports a new CLI version', async () => {
    const test = harness();
    test.service.refreshIfStale(providers(provider(true, '0.167.0'))); await settle();
    test.advance(MINUTE); test.service.refreshIfStale(providers(provider(true, '0.167.0'))); await settle();
    expect(test.calls).toEqual(['codex']);
    test.service.refreshIfStale(providers(provider(true, '0.168.0'))); await settle();
    expect(test.calls).toEqual(['codex', 'codex']);
    test.service.refreshIfStale(providers(provider(true, '0.168.0'))); await settle();
    expect(test.calls).toEqual(['codex', 'codex']);
    expect(test.service.status().codex.cliVersion).toBe('0.168.0');
  });

  it('compares the provider version with the one the list was discovered under, not the discovery label', async () => {
    const test = harness({ codex: [catalog(codexList, { cliVersion: 'codex-cli 0.167.0 (app-server 3)' })] });
    test.service.refreshIfStale(providers(provider(true, '0.167.0'))); await settle();
    test.advance(MINUTE); test.service.refreshIfStale(providers(provider(true, '0.167.0'))); await settle();
    expect(test.calls).toEqual(['codex']);
    expect(test.service.status().codex.cliVersion).toBe('codex-cli 0.167.0 (app-server 3)');
  });

  it('skips an engine whose provider is not ready', async () => {
    const test = harness();
    test.service.refreshIfStale(providers(provider(false, '0.167.0'), provider(true, '2.1.323'))); await settle();
    expect(test.calls).toEqual(['claude']);
    test.service.refreshIfStale(); await settle();
    expect(test.calls).toEqual(['claude', 'codex']);
  });

  it('forces one discovery for an unknown model, at most every 30 seconds per engine', async () => {
    const test = harness({ codex: [catalog(codexList), catalog(codexList), catalog([...codexList, model('gpt-7-luna')])] });
    expect(await test.service.ensureModel('codex', 'gpt-6-astra')).toBe(true);
    expect(test.calls).toEqual([]);
    expect(await test.service.ensureModel('codex', 'gpt-7-nova')).toBe(true);
    expect(test.calls).toEqual(['codex']);
    test.advance(29_999);
    expect(await test.service.ensureModel('codex', 'gpt-7-luna')).toBe(false);
    expect(test.calls).toEqual(['codex']);
    expect(await test.service.ensureModel('claude', 'claude-fable-6')).toBe(false);
    expect(test.calls).toEqual(['codex', 'claude']);
    test.advance(1);
    expect(await test.service.ensureModel('codex', 'gpt-7-luna')).toBe(false);
    test.advance(30_000);
    expect(await test.service.ensureModel('codex', 'gpt-7-luna')).toBe(true);
    expect(test.calls).toEqual(['codex', 'claude', 'codex', 'codex']);
    for (const value of [undefined, '', ['gpt-7-nova'], 7]) expect(await test.service.ensureModel('codex', value)).toBe(false);
    expect(test.calls).toHaveLength(4);
  });

  it('lets ensureModel join a discovery already running instead of starting another', async () => {
    const pending = deferred<DiscoveredCatalog>();
    const test = harness({ codex: [pending.promise] });
    void test.service.refresh('codex');
    const known = test.service.ensureModel('codex', 'gpt-7-nova');
    pending.resolve(catalog(codexList));
    expect(await known).toBe(true);
    expect(test.calls).toEqual(['codex']);
  });

  it('moves the default to the CLI default when the configured one leaves the list', async () => {
    const test = harness({ codex: [catalog([model('gpt-7-luna'), { id: 'gpt-7-nova', label: 'GPT-7 Nova', efforts: ['low', 'medium'] }],
      { cliDefault: { model: 'gpt-7-nova', effort: 'medium' } })] });
    expect(getModelDefaults().codex).toEqual({ model: 'gpt-6.1-sol', effort: 'high' });
    await test.service.refresh('codex');
    expect(getModelDefaults()).toEqual({ codex: { model: 'gpt-7-nova', effort: 'medium' }, claude: { model: 'claude-opus-5-5', effort: 'xhigh' } });
  });

  it('lets a health response wait, briefly, for the first discovery only', async () => {
    const first = deferred<DiscoveredCatalog>(); const later = deferred<DiscoveredCatalog>();
    const test = harness({ codex: [first.promise, later.promise] });
    await test.service.whenInitialized();
    test.service.refreshIfStale(providers(provider(true)));
    let done = false; const waiting = test.service.whenInitialized().then(() => { done = true; });
    await settle(); expect(done).toBe(false);
    first.resolve(catalog(codexList)); await waiting;
    expect(getModelOptions().codex.map(item => item.id)).toContain('gpt-7-nova');
    void test.service.refresh('codex', { force: true });
    await test.service.whenInitialized();
    const stuck = harness({ codex: [new Promise<DiscoveredCatalog>(() => {})] });
    stuck.service.refreshIfStale(providers(provider(true)));
    const started = Date.now(); await stuck.service.whenInitialized(50);
    expect(Date.now() - started).toBeLessThan(1000);
    later.resolve(catalog(codexList));
  });
});

describe('parseRequestModelSettings', () => {
  it('accepts a model the next discovery knows and keeps the old error for one it does not', async () => {
    const test = harness();
    await expect(parseRequestModelSettings(test.service, 'codex', 'gpt-7-nova', 'ultra')).resolves.toEqual({ model: 'gpt-7-nova', effort: 'ultra' });
    test.advance(MINUTE);
    await expect(parseRequestModelSettings(test.service, 'codex', 'gpt-9', 'low')).rejects.toThrow('선택한 CLI에서 지원하는 모델과 추론 레벨을 선택해 주세요.');
    test.advance(MINUTE);
    // A known model with a level it lacks, or a malformed id, does not cost a discovery.
    await expect(parseRequestModelSettings(test.service, 'codex', 'gpt-7-nova', 'turbo')).rejects.toThrow();
    await expect(parseRequestModelSettings(test.service, 'codex', ['gpt-9'], 'low')).rejects.toThrow();
    await expect(parseRequestModelSettings(undefined, 'codex', 'gpt-9', 'low')).rejects.toThrow();
    expect(test.calls).toEqual(['codex', 'codex']);
  });
});
