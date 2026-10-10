import { spawn } from 'node:child_process';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import type { Server } from 'node:http';
import path from 'node:path';
import { createInterface } from 'node:readline';
import { afterEach, describe, expect, it } from 'vitest';
import { createApp } from '../../src/app.js';
import { loadConfig } from '../../src/config.js';
import type { HumanizeRequest } from '../../src/engine/humanize-engine.js';
import { PortalClient } from '../../src/mcp/portal-client.js';
import { createSession, PROTOCOL_VERSIONS } from '../../src/mcp/session.js';
import { TransformQueue } from '../../src/queue/transform-queue.js';
import { close, listen } from '../helpers/http-app.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';

const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => { while (cleanups.length) await cleanups.pop()!(); });

const preflight = { ready: true as const, nodeVersion: '24.19.0', pythonVersion: '3.14.7', codexVersion: '0.161.0', humanizeVersion: '2.3.2' };

/** A real portal app with a fake text engine (records each request, answers `rewrite(source)`) and a fake Office
 * engine (answers the bytes `PK-result`). */
async function portal(rewrite: (source: string) => string = source => source.replace('수행한다', '한다'), options: { gate?: Promise<void> } = {}) {
  const root = await makeTestRoot();
  const requests: HumanizeRequest[] = [];
  const queue = new TransformQueue({ maxActive: 1, maxAccepted: 3 });
  const engine = { async transform(request: HumanizeRequest) {
    requests.push(request);
    const source = await readFile(request.workspace.path('01_input.txt'), 'utf8');
    request.onEvent({ type: 'progress', phase: 'transform', current: 1, total: 1, message: '1/1 구간을 다듬는 중입니다.' });
    request.onEvent({ type: 'warning', code: 'CHUNK_RETRY', message: '1번 구간을 더 보수적으로 다시 다듬습니다.' });
    if (options.gate) await Promise.race([options.gate, new Promise((_, reject) => request.signal.addEventListener('abort', () => reject(new Error('aborted'))))]);
    const finalPath = request.workspace.path('03_reassembled.md');
    await writeFile(finalPath, rewrite(source), 'utf8');
    return { finalPath, sourceChars: source.length, outputChars: rewrite(source).length, chunks: 1, warnings: [], diagnostics: {} as never };
  } };
  const state = { job: 'job-' + 'a'.repeat(32), kind: 'document', format: 'docx', name: 'report-humanized.docx', preview: '[문단 1]\n원문',
    sourceChars: 2, editableBlocks: 1, preservedBlocks: 0, totalChunks: 1, warnings: ['각주 보존'] };
  const documentEngine = { root: path.join(root, 'documents'), async prepare() { return { ...state }; }, async cleanup() {}, async health() { return true; },
    async transform(current: typeof state, _engine: string, dir: string) {
      const output = path.join(dir, 'out.docx');
      await writeFile(output, 'PK-result');
      return { state: { ...current, status: 'done' }, output, bytes: 9, sha256: '0'.repeat(64), elapsedMs: 1 };
    } } as never;
  const app = createApp({ config: { ...loadConfig({}, process.cwd()), runtimeRoot: path.join(root, 'jobs'), minFreeBytes: 1 }, queue,
    engine, claudeEngine: engine, documentEngine, preflight, logger: { info() {}, error() {} } });
  const running = await listen(app);
  cleanups.push(async () => { await app.locals.documentStore?.close(); await queue.shutdown(); await close(running.server as Server); await removeTestRoot(root); });
  return { ...running, root, requests, store: app.locals.documentStore };
}

function connect(baseUrl: string) {
  const sent: any[] = [];
  const session = createSession({ client: new PortalClient(baseUrl), send: message => { sent.push(message); } });
  const request = async (id: number, method: string, params?: unknown) => {
    await session.handle({ jsonrpc: '2.0', id, method, ...(params === undefined ? {} : { params }) });
    return sent.find(message => message.id === id);
  };
  const call = async (id: number, name: string, args: unknown, meta?: unknown) =>
    (await request(id, 'tools/call', { name, arguments: args, ...(meta ? { _meta: meta } : {}) }))?.result;
  return { session, sent, request, call };
}

describe('MCP protocol', () => {
  it('negotiates the protocol version and lists the three tools', async () => {
    const { request, sent, session } = connect('http://127.0.0.1:9');
    const known = await request(1, 'initialize', { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 't', version: '1' } });
    expect(known.result).toMatchObject({ protocolVersion: '2025-03-26', capabilities: { tools: { listChanged: false } }, serverInfo: { name: 'humanize-kr' } });
    expect((await request(2, 'initialize', { protocolVersion: '2099-01-01' })).result.protocolVersion).toBe(PROTOCOL_VERSIONS[0]);
    await session.handle({ jsonrpc: '2.0', method: 'notifications/initialized' });
    expect(sent).toHaveLength(2);                                     // a notification gets no answer
    expect((await request(3, 'ping')).result).toEqual({});
    const tools = (await request(4, 'tools/list')).result.tools;
    expect(tools.map((tool: any) => tool.name)).toEqual(['humanize_text', 'humanize_file', 'humanize_status']);
    expect(tools[0].inputSchema.properties.strength.enum).toEqual(['normal', 'medium', 'strong', 'very-strong', 'rewrite']);
    expect(tools[1].annotations).toMatchObject({ readOnlyHint: false, destructiveHint: false });
  });

  it('answers unknown methods, unknown tools and batches with JSON-RPC errors', async () => {
    const { request, session, sent } = connect('http://127.0.0.1:9');
    expect((await request(1, 'resources/list')).error.code).toBe(-32601);
    expect((await request(2, 'tools/call', { name: 'nope', arguments: {} })).error.code).toBe(-32602);
    await session.handle([{ jsonrpc: '2.0', id: 3, method: 'ping' }]);
    expect(sent.at(-1)).toMatchObject({ id: null, error: { code: -32600 } });
  });

  it('reports bad arguments and an unreachable portal as tool errors', async () => {
    const { call } = connect('http://127.0.0.1:9');
    const cases = [[{ text: '' }, 'text에'], [{ text: '글', strength: 'maximum' }, 'strength는'],
      [{ text: '글', engine: 'gemini' }, 'engine은'], [{ text: '글', extra: 1 }, '알 수 없는 인자']] as const;
    for (const [index, [args, text]] of cases.entries()) {
      const result = await call(10 + index, 'humanize_text', args);
      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain(text);
    }
    const offline = await call(2, 'humanize_text', { text: '글입니다.' });
    expect(offline).toMatchObject({ isError: true });
    expect(offline.content[0].text).toContain('PORTAL_UNREACHABLE');
    expect((await call(3, 'humanize_file', { path: 'relative.txt' })).content[0].text).toContain('절대 경로');
    expect((await call(4, 'humanize_file', { path: '/tmp/a.pdf' })).content[0].text).toContain('TXT, MD, DOCX, PPTX');
    expect((await call(5, 'humanize_file', { path: '/tmp/a.docx', strength: 'strong' })).content[0].text).toContain('보통으로만');
  });
});

describe('MCP tools on the portal', () => {
  it('humanize_text runs a direct-text job at the requested strength and reports progress and warnings', async () => {
    const t = await portal();
    const { call, sent } = connect(t.baseUrl);
    const result = await call(1, 'humanize_text', { text: '담당자는 정리 작업을 수행한다.', strength: 'strong', engine: 'claude',
      model: 'claude-sonnet-5-5', effort: 'high' }, { progressToken: 'p1' });
    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toBe('담당자는 정리 작업을 한다.');
    expect(result.content[1].text).toContain('변환 강도: 강하게 (strong)');
    expect(result.content[1].text).toContain('1번 구간을 더 보수적으로 다시 다듬습니다.');
    expect(t.requests[0]!.rewriteOptions).toEqual({ inputKind: 'direct-text', strength: 'strong' });
    expect(t.requests[0]!.settings).toEqual({ model: 'claude-sonnet-5-5', effort: 'high' });
    const progress = sent.filter(message => message.method === 'notifications/progress');
    expect(progress.map(message => message.params.progressToken)).toEqual(progress.map(() => 'p1'));
    expect(progress.map(message => message.params.progress)).toEqual(progress.map((_, index) => index + 1));
    expect(progress.map(message => message.params.message)).toContain('1/1 구간을 다듬는 중입니다.');
  });

  it('surfaces a portal refusal with its code', async () => {
    const t = await portal();
    const result = await connect(t.baseUrl).call(1, 'humanize_text', { text: '글입니다.', model: 'no-such-model' });
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toContain('INVALID_MODEL_SETTINGS');
  });

  it('humanize_file decodes a CP949 text file, sends it as a text file with its strength and never overwrites', async () => {
    const t = await portal();
    const dir = path.join(t.root, 'files');
    await mkdir(dir);
    const source = path.join(dir, '보고서.txt');
    await writeFile(source, Buffer.from('b0a1b3aa20bcf6c7e0c7d1b4d92e0d0a', 'hex'));   // CP949 "가나 수행한다.\r\n"
    const { call } = connect(t.baseUrl);
    const first = await call(1, 'humanize_file', { path: source, strength: 'medium' });
    expect(first.isError).toBeUndefined();
    expect(first.content[0].text).toContain(path.join(dir, '보고서-humanized.txt'));
    expect(first.content[0].text).toContain('변환 강도: 중간 (medium)');
    expect(await readFile(path.join(dir, '보고서-humanized.txt'), 'utf8')).toBe('가나 한다.\n');
    expect(t.requests[0]!.rewriteOptions).toEqual({ inputKind: 'text-file', strength: 'medium' });
    await call(2, 'humanize_file', { path: source });
    expect(t.requests[1]!.rewriteOptions).toEqual({ inputKind: 'text-file', strength: 'normal' });
    expect((await readdir(dir)).sort()).toEqual(['보고서-humanized-2.txt', '보고서-humanized.txt', '보고서.txt']);
    expect(await readFile(source)).toEqual(Buffer.from('b0a1b3aa20bcf6c7e0c7d1b4d92e0d0a', 'hex'));
    const taken = await call(3, 'humanize_file', { path: source, outputPath: path.join(dir, '보고서-humanized.txt') });
    expect(taken.isError).toBe(true);
    expect(taken.content[0].text).toContain('이미 있습니다');
    expect((await call(4, 'humanize_file', { path: source, outputPath: source })).content[0].text).toContain('원본 파일에는');
  });

  it('humanize_file runs an Office document through upload, transform and result, then closes it on the portal', async () => {
    const t = await portal();
    const source = path.join(t.root, 'report.docx');
    await writeFile(source, 'PK-source');
    const result = await connect(t.baseUrl).call(1, 'humanize_file', { path: source });
    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toContain('각주 보존');
    expect(await readFile(path.join(t.root, 'report-humanized.docx'), 'utf8')).toBe('PK-result');
    await expect.poll(() => t.store.records.size).toBe(0);
  });

  it('a cancelled call sends no response and stops the portal job', async () => {
    let release!: () => void;
    const t = await portal(undefined, { gate: new Promise<void>(resolve => { release = resolve; }) });
    cleanups.push(async () => release());
    const { session, sent } = connect(t.baseUrl);
    const running = session.handle({ jsonrpc: '2.0', id: 7, method: 'tools/call', params: { name: 'humanize_text', arguments: { text: '글입니다.' } } });
    await expect.poll(() => t.requests.length).toBe(1);
    await session.handle({ jsonrpc: '2.0', method: 'notifications/cancelled', params: { requestId: 7, reason: 'user' } });
    await running;
    expect(sent.find(message => message.id === 7)).toBeUndefined();
    await expect.poll(() => t.requests[0]!.signal.aborted).toBe(true);
  });

  it('serves the protocol over stdio', async () => {
    const t = await portal();
    const child = spawn(process.execPath, ['--import', 'tsx', 'src/mcp/server.ts'], { env: { ...process.env, HUMANIZE_PORTAL_URL: t.baseUrl }, stdio: ['pipe', 'pipe', 'pipe'] });
    cleanups.push(async () => { child.kill(); });
    const lines = createInterface({ input: child.stdout! })[Symbol.asyncIterator]();
    const next = async () => JSON.parse((await lines.next()).value as string);
    child.stdin!.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 't', version: '1' } } }) + '\n');
    expect((await next()).result.serverInfo.name).toBe('humanize-kr');
    child.stdin!.write('{broken\n');
    expect((await next()).error.code).toBe(-32700);
    child.stdin!.write(JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'humanize_text', arguments: { text: '정리 작업을 수행한다.' } } }) + '\n');
    expect((await next()).result.content[0].text).toBe('정리 작업을 한다.');
    const exited = new Promise<number | null>(resolve => child.once('exit', resolve));
    child.stdin!.end();
    expect(await exited).toBe(0);
  }, 30000);
});
