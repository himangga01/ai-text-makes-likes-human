import { getModelOptions, isKnownModel, parseModelSettings, setLiveModels, type EngineChoice, type ModelSettings } from '../engine/model-policy.js';
import { ModelDiscoveryError, type DiscoveredCatalog } from './model-discovery.js';
import type { ProviderHealthMap } from './provider-health.js';

export type DiscoveryFailure = ModelDiscoveryError['code'];
/** checkedAt is when the served live list was discovered; lastError is the code of a later failed attempt. */
export interface ModelCatalogStatus { source: 'live' | 'fallback'; checkedAt?: string; cliVersion?: string; lastError?: DiscoveryFailure }
export interface ModelCatalogLogger { info(value: Record<string, unknown>): void; error(value: Record<string, unknown>): void }
export interface ModelCatalogOptions {
  discover: (engine: EngineChoice) => Promise<DiscoveredCatalog>;
  now?: () => number;
  logger?: ModelCatalogLogger;
}

export const MODEL_LIST_FRESH_MS = 10 * 60_000;
export const MODEL_LIST_RETRY_MS = 60_000;
export const MODEL_ENSURE_INTERVAL_MS = 30_000;

interface EngineState {
  inflight?: Promise<void>;
  first?: Promise<void>;
  live: boolean;
  succeededAt?: number;
  failedAt?: number;
  ensuredAt?: number;
  cliVersion?: string;
  /** Provider version last reported by a preflight, and the one the live list was discovered under. */
  seenVersion?: string;
  basisVersion?: string;
  lastError?: DiscoveryFailure;
}

const ENGINES = ['codex', 'claude'] as const;
const consoleLogger: ModelCatalogLogger = {
  info: value => console.log(JSON.stringify(value)),
  error: value => console.error(JSON.stringify(value))
};

/** Keeps each writer CLI's model list current: discovered at start-up and again when stale, the CLI version changes,
 * or a request names a model the list does not have yet. A failure keeps the last good list (live or fallback). */
export class ModelCatalogService {
  private readonly states: Record<EngineChoice, EngineState> = { codex: { live: false }, claude: { live: false } };
  private readonly now: () => number;
  private readonly logger: ModelCatalogLogger;

  constructor(private readonly options: ModelCatalogOptions) {
    this.now = options.now ?? Date.now;
    this.logger = options.logger ?? consoleLogger;
  }

  /** Single-flight per engine; without force it runs only when the list is stale and no failure is too recent. */
  refresh(engine: EngineChoice, { force = false }: { force?: boolean } = {}): Promise<void> {
    const state = this.states[engine];
    if (state.inflight) return state.inflight;
    if (!force && !this.due(state)) return Promise.resolve();
    const run = this.discover(engine, state).finally(() => { state.inflight = undefined; });
    state.inflight = run;
    state.first ??= run;
    return run;
  }

  /** Fire-and-forget; an engine whose provider is not ready is skipped. Omitted providers count as ready. */
  refreshIfStale(providers?: ProviderHealthMap): void {
    for (const engine of ENGINES) {
      const provider = providers?.[engine];
      if (providers && !provider?.ready) continue;
      const state = this.states[engine];
      if (provider?.version) state.seenVersion = provider.version;
      if (state.live && state.basisVersion === undefined) state.basisVersion = state.seenVersion;
      void this.refresh(engine);
    }
  }

  /** A request named a model the list lacks: one forced discovery (at most every 30 s per engine) may add it. */
  async ensureModel(engine: EngineChoice, model: unknown): Promise<boolean> {
    if (typeof model !== 'string' || !model) return false;
    if (isKnownModel(engine, model)) return true;
    const state = this.states[engine];
    if (state.inflight) await state.inflight;
    else {
      const now = this.now();
      if (state.ensuredAt !== undefined && now - state.ensuredAt < MODEL_ENSURE_INTERVAL_MS) return false;
      state.ensuredAt = now;
      await this.refresh(engine, { force: true });
    }
    return isKnownModel(engine, model);
  }

  /** Waits, at most maxWaitMs, for each engine's first discovery that has started. A health response right after
   * start-up then serves the live list instead of making clients replace a saved live-only model with a default. */
  async whenInitialized(maxWaitMs = 3000): Promise<void> {
    const pending = ENGINES.map(engine => this.states[engine].first).filter(run => run !== undefined);
    if (!pending.length) return;
    let timer: NodeJS.Timeout | undefined;
    await Promise.race([Promise.all(pending), new Promise<void>(resolve => { timer = setTimeout(resolve, maxWaitMs); timer.unref?.(); })]);
    clearTimeout(timer);
  }

  status(): Record<EngineChoice, ModelCatalogStatus> {
    const entry = (state: EngineState): ModelCatalogStatus => ({
      source: state.live ? 'live' : 'fallback',
      ...(state.live && state.succeededAt !== undefined ? { checkedAt: new Date(state.succeededAt).toISOString() } : {}),
      ...(state.live && state.cliVersion ? { cliVersion: state.cliVersion } : {}),
      ...(state.lastError ? { lastError: state.lastError } : {})
    });
    return { codex: entry(this.states.codex), claude: entry(this.states.claude) };
  }

  private due(state: EngineState): boolean {
    const now = this.now();
    if (state.failedAt !== undefined && state.failedAt >= (state.succeededAt ?? -Infinity) && now - state.failedAt < MODEL_LIST_RETRY_MS) return false;
    if (state.succeededAt === undefined) return true;
    if (state.seenVersion !== undefined && state.basisVersion !== undefined && state.seenVersion !== state.basisVersion) return true;
    return now - state.succeededAt >= MODEL_LIST_FRESH_MS;
  }

  private async discover(engine: EngineChoice, state: EngineState): Promise<void> {
    const before = getModelOptions()[engine];
    try {
      const catalog = await this.options.discover(engine);
      if (!setLiveModels(engine, catalog.models, catalog.cliDefault)) throw new ModelDiscoveryError('empty', 'No usable model in the discovered list');
      Object.assign(state, { live: true, succeededAt: this.now(), lastError: undefined, cliVersion: catalog.cliVersion ?? state.seenVersion,
        basisVersion: state.seenVersion ?? catalog.cliVersion?.match(/\d+\.\d+\.\d+/)?.[0] });
      const after = getModelOptions()[engine];
      if (JSON.stringify(after) === JSON.stringify(before)) return;
      const ids = after.map(item => item.id); const old = before.map(item => item.id);
      this.logger.info({ event: 'model_catalog_updated', engine, count: ids.length, added: ids.filter(id => !old.includes(id)),
        removed: old.filter(id => !ids.includes(id)), cliVersion: catalog.cliVersion });
    } catch (error) {
      // Only the code: a CLI's output or stack can carry account or path details.
      state.failedAt = this.now();
      state.lastError = error instanceof ModelDiscoveryError ? error.code : 'protocol';
      this.logger.error({ event: 'model_catalog_failed', engine, code: state.lastError });
    }
  }
}

/** Request-time parse: a model id the current list lacks gets one discovery before the request is refused. */
export async function parseRequestModelSettings(catalog: Pick<ModelCatalogService, 'ensureModel'> | undefined,
  engine: EngineChoice, model: unknown, effort: unknown): Promise<ModelSettings> {
  try { return parseModelSettings(engine, model, effort); }
  catch (error) {
    if (!catalog || typeof model !== 'string' || !model || isKnownModel(engine, model) || !await catalog.ensureModel(engine, model)) throw error;
    return parseModelSettings(engine, model, effort);
  }
}
