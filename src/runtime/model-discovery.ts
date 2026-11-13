import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import type { EngineChoice } from '../engine/model-policy.js';
import { terminateProcessTree, trackLiveProcess } from '../process/command-runner.js';

/** Asks a writer CLI for its live model list over the CLI's own stdio protocol (Codex app-server JSON-RPC, Claude Code
 * stream-json control request). No prompt is sent, so discovery consumes no usage. The child is always gone when the
 * promise settles: stdin is closed after the answer and the process tree is killed after a short grace, at once on error. */
export interface DiscoveredModel { id: string; label: string; efforts: string[] }
export interface DiscoveredCatalog {
  engine: EngineChoice;
  /** Selectable models in CLI order, deduplicated by id, never empty on success. */
  models: DiscoveredModel[];
  cliDefault?: { model: string; effort?: string };
  excluded: { id: string; reason: 'hidden' | 'no-effort' }[];
  cliVersion?: string;
}
export interface DiscoveryOptions { cwd: string; timeoutMs?: number; env?: NodeJS.ProcessEnv }
type Mapped = Pick<DiscoveredCatalog, 'models' | 'cliDefault' | 'excluded'>;

/** spawn: the CLI could not be started. timeout: no answer in time. protocol: early exit, error reply or malformed
 * reply. empty: the CLI answered but listed no selectable model. */
export class ModelDiscoveryError extends Error {
  constructor(readonly code: 'spawn' | 'timeout' | 'protocol' | 'empty', message: string) {
    super(message);
    this.name = 'ModelDiscoveryError';
  }
}

const TIMEOUT_MS = 20_000, GRACE_MS = 2_000, KILL_WAIT_MS = 2_000, MAX_LINE_CHARS = 4 * 1024 * 1024, MAX_PAGES = 50;
export const CLAUDE_DISCOVERY_ARGS = ['-p', '--restricted', '--strict-mcp-config', '--tools', '', '--no-session-persistence',
  '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose'];

type Message = Record<string, unknown>;
const isRecord = (value: unknown): value is Message => typeof value === 'object' && value !== null && !Array.isArray(value);
const text = (value: unknown): string => typeof value === 'string' ? value.trim() : '';
// Ids and efforts end up as CLI arguments, so only plain tokens are kept.
const token = (value: unknown): string => { const item = text(value); return /^[A-Za-z0-9][\w.:/[\]-]{0,127}$/.test(item) ? item : ''; };
const tokens = (values: unknown[]): string[] => [...new Set(values.map(token).filter(Boolean))];
const brief = (value: unknown): string => text(value).replace(/\s+/g, ' ').slice(0, 200);

let clientVersion: string | undefined;
function portalVersion(): string {
  if (clientVersion) return clientVersion;
  try {
    const version: unknown = (JSON.parse(readFileSync(new URL('../../package.json', import.meta.url), 'utf8')) as Message).version;
    clientVersion = typeof version === 'string' && version ? version : undefined;
  } catch { /* bundled without package.json */ }
  return clientVersion ??= '0.0.0';
}

const codexLabel = (name: string): string => name.replace(/-(?=[A-Z][a-z])/g, ' ');
const claudeLabel = (name: string): string => !name || /^claude\b/i.test(name) ? name : `Claude ${name}`;

export function mapCodexModels(data: unknown[]): Mapped {
  const result: Mapped = { models: [], excluded: [] }, seen = new Set<string>();
  for (const item of data) {
    const id = isRecord(item) ? token(item.id) : '';
    if (!isRecord(item) || !id || seen.has(id)) continue;
    seen.add(id);
    if (item.isDefault === true && !result.cliDefault) {
      const effort = token(item.defaultReasoningEffort);
      result.cliDefault = effort ? { model: id, effort } : { model: id };
    }
    if (item.hidden === true) { result.excluded.push({ id, reason: 'hidden' }); continue; }
    const efforts = tokens(Array.isArray(item.supportedReasoningEfforts)
      ? item.supportedReasoningEfforts.map(entry => isRecord(entry) ? entry.reasoningEffort : entry) : []);
    if (efforts.length === 0) result.excluded.push({ id, reason: 'no-effort' });
    else result.models.push({ id, label: codexLabel(text(item.displayName)) || id, efforts });
  }
  return result;
}

export function mapClaudeModels(models: unknown[]): Mapped {
  const entries = models.filter(isRecord).map(item => ({
    alias: text(item.value), id: token(item.resolvedModel) || token(item.value), name: text(item.displayName),
    efforts: item.supportsEffort === true && Array.isArray(item.supportedEffortLevels) ? tokens(item.supportedEffortLevels) : []
  }));
  const fallback = entries.find(entry => entry.alias === 'default');
  const result: Mapped = { models: [], excluded: [] }, seen = new Set<string>();
  if (fallback && fallback.id && fallback.id !== 'default') result.cliDefault = { model: fallback.id };
  for (const entry of entries) {
    if (entry === fallback || !entry.id || seen.has(entry.id)) continue;
    seen.add(entry.id);
    if (entry.efforts.length === 0) result.excluded.push({ id: entry.id, reason: 'no-effort' });
    else result.models.push({ id: entry.id, label: claudeLabel(entry.name) || entry.id, efforts: entry.efforts });
  }
  const model = result.cliDefault?.model;
  if (model && !result.models.some(item => item.id === model)) {
    const efforts = entries.find(entry => entry.id === model && entry.efforts.length > 0)?.efforts;
    if (efforts) {
      // The default entry's own name ("Default (recommended)") is not a model name.
      const named = entries.find(entry => entry.id === model && entry !== fallback && entry.name);
      result.models.unshift({ id: model, label: claudeLabel(named?.name ?? '') || model, efforts });
      result.excluded = result.excluded.filter(item => item.id !== model);
    }
  }
  return result;
}

interface Channel { send(message: Message): void; read(): Promise<Message> }

async function converse<T>(label: string, command: string, args: string[], options: DiscoveryOptions,
  talk: (channel: Channel) => Promise<T>): Promise<T> {
  const child = spawn(command, args, {
    cwd: options.cwd, shell: false, windowsHide: true, detached: process.platform !== 'win32',
    env: { ...process.env, ...options.env, NO_COLOR: '1' }, stdio: ['pipe', 'pipe', 'pipe']
  });
  const untrack = child.pid === undefined ? () => {} : trackLiveProcess(child.pid);
  const exited = new Promise<void>(resolve => child.once('exit', () => resolve()));
  const queue: Message[] = [];
  let waiter: { resolve(message: Message): void; reject(error: Error): void } | undefined;
  let failure: ModelDiscoveryError | undefined, partial = '', stderr = '';
  const fail = (error: ModelDiscoveryError): void => {
    failure ??= error;
    waiter?.reject(failure);
    waiter = undefined;
  };
  const kill = (): void => { if (child.pid !== undefined && child.exitCode === null && child.signalCode === null) terminateProcessTree(child.pid); };
  const timeoutMs = options.timeoutMs ?? TIMEOUT_MS;
  const timer = setTimeout(() => {
    fail(new ModelDiscoveryError('timeout', `${label} did not list its models within ${timeoutMs} ms`));
    kill();
  }, timeoutMs);

  child.on('error', error => fail(new ModelDiscoveryError('spawn', `${label} could not be started: ${brief(error.message)}`)));
  child.stdin.on('error', () => { /* the child closed stdin; its exit reports the failure */ });
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', chunk => { stderr = (stderr + String(chunk)).slice(-4096); });
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', chunk => {
    partial += String(chunk);
    for (let end = partial.indexOf('\n'); end >= 0; end = partial.indexOf('\n')) {
      const line = partial.slice(0, end).trim();
      partial = partial.slice(end + 1);
      let message: unknown;
      try { message = line ? JSON.parse(line) : undefined; } catch { continue; }
      if (!isRecord(message)) continue;
      if (waiter) { waiter.resolve(message); waiter = undefined; } else queue.push(message);
    }
    if (partial.length > MAX_LINE_CHARS) { partial = ''; fail(new ModelDiscoveryError('protocol', `${label} wrote an oversized line`)); kill(); }
  });
  // 'close' follows the last stdout chunk, so an answer written just before exiting is still read.
  child.once('close', (code, signal) => {
    const reason = brief(stderr.trim().split('\n').pop());
    fail(new ModelDiscoveryError('protocol', `${label} exited (${signal ?? `code ${code}`}) before answering${reason ? `: ${reason}` : ''}`));
  });

  const channel: Channel = {
    send: message => { if (!child.stdin.destroyed) child.stdin.write(`${JSON.stringify(message)}\n`); },
    read: () => {
      const next = queue.shift();
      if (next) return Promise.resolve(next);
      if (failure) return Promise.reject(failure);
      return new Promise((resolve, reject) => { waiter = { resolve, reject }; });
    }
  };
  const settle = async (graceful: boolean): Promise<void> => {
    clearTimeout(timer);
    if (child.pid === undefined) return;
    if (graceful) {
      child.stdin.end();
      if (await within(exited, GRACE_MS)) return;
    }
    kill();
    await within(exited, KILL_WAIT_MS);
  };
  try {
    const result = await talk(channel);
    await settle(true);
    return result;
  } catch (error) {
    await settle(false);
    throw error instanceof ModelDiscoveryError ? error : new ModelDiscoveryError('protocol', `${label}: ${brief(error instanceof Error ? error.message : error)}`);
  } finally {
    untrack();
  }
}

function within(promise: Promise<unknown>, ms: number): Promise<boolean> {
  return new Promise(resolve => {
    const timer = setTimeout(() => resolve(false), ms);
    void promise.then(() => { clearTimeout(timer); resolve(true); });
  });
}

function catalog(engine: EngineChoice, mapped: Mapped, cliVersion: string | undefined, label: string): DiscoveredCatalog {
  if (mapped.models.length === 0) throw new ModelDiscoveryError('empty', `${label} listed no selectable model`);
  return { engine, ...mapped, ...(cliVersion ? { cliVersion } : {}) };
}

/** `leadingArgs` go before the CLI's own arguments (e.g. a script for an interpreter); production passes none. */
export async function discoverCodexModels(command: string, options: DiscoveryOptions, leadingArgs: string[] = []): Promise<DiscoveredCatalog> {
  const label = 'Codex app-server';
  const { userAgent, data } = await converse(label, command, [...leadingArgs, 'app-server'], options, async channel => {
    let id = 0;
    const call = async (method: string, params: Message): Promise<Message> => {
      const request = ++id;
      channel.send({ jsonrpc: '2.0', id: request, method, params });
      for (;;) {
        const message = await channel.read();
        if ('method' in message || message.id !== request) continue;
        if (isRecord(message.error)) throw new ModelDiscoveryError('protocol', `${label} ${method} failed: ${brief(message.error.message) || 'error'}`);
        if (!isRecord(message.result)) throw new ModelDiscoveryError('protocol', `${label} ${method} returned no result`);
        return message.result;
      }
    };
    const initialized = await call('initialize', { clientInfo: { name: 'humanize-portal', title: '윤문 포털', version: portalVersion() } });
    channel.send({ jsonrpc: '2.0', method: 'initialized' });
    const data: unknown[] = [], cursors = new Set<string>();
    let cursor: string | undefined;
    for (let page = 0; ; page++) {
      if (page >= MAX_PAGES) throw new ModelDiscoveryError('protocol', `${label} model/list did not finish paging`);
      const result = await call('model/list', { includeHidden: false, limit: 100, ...(cursor ? { cursor } : {}) });
      if (!Array.isArray(result.data)) throw new ModelDiscoveryError('protocol', `${label} model/list returned no data`);
      data.push(...result.data);
      cursor = text(result.nextCursor) || undefined;
      if (!cursor) break;
      if (cursors.has(cursor)) throw new ModelDiscoveryError('protocol', `${label} model/list repeated a cursor`);
      cursors.add(cursor);
    }
    return { userAgent: text(initialized.userAgent), data };
  });
  return catalog('codex', mapCodexModels(data), userAgent.match(/\/(\d+\.\d+\.\d+)/)?.[1], label);
}

export async function discoverClaudeModels(command: string, options: DiscoveryOptions, leadingArgs: string[] = []): Promise<DiscoveredCatalog> {
  const label = 'Claude Code';
  const { version, models } = await converse(label, command, [...leadingArgs, ...CLAUDE_DISCOVERY_ARGS], options, async channel => {
    const requestId = `models-${randomUUID()}`;
    channel.send({ type: 'control_request', request_id: requestId, request: { subtype: 'initialize' } });
    for (;;) {
      const message = await channel.read();
      const response = message.type === 'control_response' && isRecord(message.response) ? message.response : undefined;
      if (!response || response.request_id !== requestId) continue;
      if (response.subtype !== 'success') throw new ModelDiscoveryError('protocol', `${label} initialize failed: ${brief(response.error) || 'error'}`);
      const payload = response.response;
      if (!isRecord(payload) || !Array.isArray(payload.models)) throw new ModelDiscoveryError('protocol', `${label} initialize returned no models`);
      return { version: text(payload.claude_code_version) || undefined, models: payload.models as unknown[] };
    }
  });
  return catalog('claude', mapClaudeModels(models), version, label);
}

export function discoverModels(engine: EngineChoice, command: string, options: DiscoveryOptions): Promise<DiscoveredCatalog> {
  return engine === 'codex' ? discoverCodexModels(command, options) : discoverClaudeModels(command, options);
}
