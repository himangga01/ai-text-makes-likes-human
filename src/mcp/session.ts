import { readFileSync } from 'node:fs';
import { open, readFile, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { MAX_INPUT_CHARS, MAX_TEXT_FILE_BYTES } from '../engine/input-limits.js';
import { LEGACY_REWRITE_OPTIONS } from '../engine/rewrite-policy.js';
import { decodeTextFile, PortalClient, PortalError, type Engine, type JobOptions } from './portal-client.js';

/** Model Context Protocol server of the portal (stdio, JSON-RPC 2.0, one message per line). Three tools:
 * humanize_text (chat text, every strength), humanize_file (TXT/MD with a strength, DOCX/PPTX at the default; the
 * result goes to a new file, never over an existing one) and humanize_status. Each call is one portal job, so the
 * portal's queue, engines, model policy and preservation checks apply unchanged. No dependency: the protocol subset
 * a tools-only server needs is implemented here (initialize, ping, tools/list, tools/call, progress, cancellation). */
export const PROTOCOL_VERSIONS = ['2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05'] as const;
const STRENGTHS = LEGACY_REWRITE_OPTIONS.map(option => option.id);
const OFFICE_BYTES = 50 * 1024 ** 2;
const VERSION = (JSON.parse(readFileSync(new URL('../../package.json', import.meta.url), 'utf8')) as { version: string }).version;

type Id = string | number;
type Message = Record<string, unknown>;
interface ToolResult { content: Array<{ type: 'text'; text: string }>; isError?: boolean }

const engineSchema = { type: 'string', enum: ['codex', 'claude'], default: 'codex', description: '변환 CLI. 생략하면 codex.' };
const modelSchema = { type: 'string', description: '모델 ID. 생략하면 포털 기본값. 쓸 수 있는 값은 humanize_status의 modelOptions.' };
const effortSchema = { type: 'string', description: '추론 수준(예: high, xhigh). 생략하면 그 모델의 포털 기본값.' };
const strengthSchema = { type: 'string', enum: STRENGTHS, default: 'normal',
  description: `변환 강도. ${LEGACY_REWRITE_OPTIONS.map(option => `${option.id}=${option.label}`).join(', ')}. 생략하면 normal.` };

export const TOOLS = [
  {
    name: 'humanize_text', title: '한국어 글 윤문',
    description: '한국어 글의 번역투와 기계적인 문체를 윤문 포털로 다듬고, 보존 검사를 통과한 결과 텍스트를 돌려준다. 사실·숫자·인용·이름·말투는 그대로 두며, 보존을 확인하지 못한 구간은 원문을 유지한다. 글 길이와 모델에 따라 몇 분 걸릴 수 있다.',
    inputSchema: { type: 'object', additionalProperties: false, required: ['text'], properties: {
      text: { type: 'string', description: `다듬을 원문(최대 ${MAX_INPUT_CHARS.toLocaleString('ko-KR')}자).` },
      strength: strengthSchema, engine: engineSchema, model: modelSchema, effort: effortSchema } },
    annotations: { readOnlyHint: true, openWorldHint: false }
  },
  {
    name: 'humanize_file', title: '한국어 파일 윤문',
    description: 'TXT·MD·DOCX·PPTX 파일을 윤문 포털로 다듬어 원본 옆의 새 파일(<이름>-humanized.<확장자>)로 저장한다. 원본과 기존 파일은 덮어쓰지 않는다. 강도는 TXT·MD에만 적용되고, DOCX·PPTX는 서식을 지키기 위해 보통으로 처리한다.',
    inputSchema: { type: 'object', additionalProperties: false, required: ['path'], properties: {
      path: { type: 'string', description: '원본 파일의 절대 경로(.txt, .md, .docx, .pptx).' },
      outputPath: { type: 'string', description: '결과를 저장할 새 파일의 절대 경로. 원본과 확장자가 같아야 하고 아직 없는 파일이어야 한다. 생략하면 원본 옆에 자동으로 만든다.' },
      strength: { ...strengthSchema, description: `${strengthSchema.description} TXT·MD만 해당.` },
      engine: engineSchema, model: modelSchema, effort: effortSchema } },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false }
  },
  {
    name: 'humanize_status', title: '윤문 포털 상태',
    description: '윤문 포털의 준비 상태, 쓸 수 있는 CLI, 변환 강도 설명, 모델 목록과 기본값, 입력 한도, 대기 작업 수를 돌려준다.',
    inputSchema: { type: 'object', additionalProperties: false, properties: {} },
    annotations: { readOnlyHint: true, openWorldHint: false }
  }
] as const;

export interface SessionOptions { client: PortalClient; send(message: Message): void }

export function createSession({ client, send }: SessionOptions) {
  const running = new Map<Id, AbortController>();
  let protocolVersion: string = PROTOCOL_VERSIONS[0];
  const reply = (id: Id, result: unknown): void => send({ jsonrpc: '2.0', id, result });
  const fail = (id: Id | null, code: number, message: string): void => send({ jsonrpc: '2.0', id, error: { code, message } });

  async function call(id: Id, params: Message): Promise<void> {
    const controller = new AbortController();
    running.set(id, controller);
    const token = (params._meta as Message | undefined)?.progressToken;
    let step = 0;
    const progress = (message: string): void => {
      if (typeof token === 'string' || typeof token === 'number')
        send({ jsonrpc: '2.0', method: 'notifications/progress', params: { progressToken: token, progress: ++step, message } });
    };
    try {
      const result = await runTool(client, String(params.name), (params.arguments ?? {}) as Message, progress, controller.signal);
      // A cancelled request gets no response (MCP cancellation).
      if (!controller.signal.aborted) reply(id, result);
    } catch (error) {
      if (error instanceof UnknownTool) fail(id, -32602, error.message);
      else if (!controller.signal.aborted) reply(id, toolError(error));
    } finally {
      running.delete(id);
    }
  }

  return {
    get protocolVersion() { return protocolVersion; },
    /** Handles one parsed message; resolves when its response (if any) was sent. */
    async handle(message: unknown): Promise<void> {
      if (Array.isArray(message)) return fail(null, -32600, 'Batch requests are not supported');
      if (!message || typeof message !== 'object' || (message as Message).jsonrpc !== '2.0') return fail(null, -32600, 'Invalid request');
      const { id, method, params = {} } = message as { id?: Id; method?: unknown; params?: Message };
      if (typeof method !== 'string') return;                       // a response: this server sends no requests
      if (id === undefined || id === null) {
        if (method === 'notifications/cancelled') running.get((params as Message).requestId as Id)?.abort();
        return;
      }
      switch (method) {
        case 'initialize': {
          const requested = (params as Message).protocolVersion;
          protocolVersion = PROTOCOL_VERSIONS.includes(requested as typeof PROTOCOL_VERSIONS[number]) ? requested as string : PROTOCOL_VERSIONS[0];
          return reply(id, { protocolVersion, capabilities: { tools: { listChanged: false } },
            serverInfo: { name: 'humanize-kr', title: '한국어 윤문 포털', version: VERSION },
            instructions: '한국어 글과 TXT·MD·DOCX·PPTX 파일의 번역투·기계적인 문체를 윤문 포털로 다듬는 도구다. 한 번의 호출이 포털 작업 하나이며 몇 분 걸릴 수 있다. 결과는 보존 검사를 통과한 것만 돌아오고, 파일은 항상 새 파일로 저장된다.' });
        }
        case 'ping': return reply(id, {});
        case 'tools/list': return reply(id, { tools: TOOLS });
        case 'tools/call': return call(id, params as Message);
        default: return fail(id, -32601, `Method not found: ${method}`);
      }
    },
    /** Aborts every running call (stdin closed). */
    close(): void { for (const controller of running.values()) controller.abort(); }
  };
}

class UnknownTool extends Error {}
class InvalidArguments extends Error {}

function toolError(error: unknown): ToolResult {
  const message = error instanceof PortalError ? `${error.message} (${error.code})`
    : error instanceof InvalidArguments ? error.message : '윤문 도구가 실패했습니다.';
  return { content: [{ type: 'text', text: message }], isError: true };
}

function optionalString(args: Message, key: string): string | undefined {
  const value = args[key];
  if (value === undefined) return undefined;
  if (typeof value !== 'string' || !value.trim()) throw new InvalidArguments(`${key}는 비어 있지 않은 문자열이어야 합니다.`);
  return value;
}

function jobOptions(args: Message, allowed: string[]): JobOptions & { strength: string } {
  const unknown = Object.keys(args).filter(key => !allowed.includes(key));
  if (unknown.length) throw new InvalidArguments(`알 수 없는 인자입니다: ${unknown.join(', ')}`);
  const engine = optionalString(args, 'engine') ?? 'codex';
  if (engine !== 'codex' && engine !== 'claude') throw new InvalidArguments('engine은 codex 또는 claude입니다.');
  const strength = optionalString(args, 'strength') ?? 'normal';
  if (!STRENGTHS.includes(strength as typeof STRENGTHS[number])) throw new InvalidArguments(`strength는 ${STRENGTHS.join(', ')} 중 하나입니다.`);
  return { engine: engine as Engine, model: optionalString(args, 'model'), effort: optionalString(args, 'effort'), strength };
}

function lines(...items: Array<string | false | undefined>): string {
  return items.filter(Boolean).join('\n');
}

function summary(strength: string | undefined, result: { warnings: string[]; chunks: number; elapsedMs: number }): string {
  const label = LEGACY_REWRITE_OPTIONS.find(option => option.id === strength)?.label;
  return lines(label && `변환 강도: ${label} (${strength})`, `구간 ${result.chunks}개 · ${(result.elapsedMs / 1000).toFixed(1)}초`,
    result.warnings.length > 0 && `안내 ${result.warnings.length}건:\n${result.warnings.map(warning => `- ${warning}`).join('\n')}`);
}

async function runTool(client: PortalClient, name: string, args: Message, progress: (message: string) => void,
  signal: AbortSignal): Promise<ToolResult> {
  if (name === 'humanize_status') {
    jobOptions(args, []);
    const health = await client.health(signal);
    return { content: [{ type: 'text', text: JSON.stringify(health, null, 2) }] };
  }
  if (name === 'humanize_text') {
    const options = jobOptions(args, ['text', 'strength', 'engine', 'model', 'effort']);
    if (typeof args.text !== 'string' || !args.text.trim()) throw new InvalidArguments('text에 다듬을 원문을 넣어 주세요.');
    const text = args.text.replace(/\r\n?/g, '\n');
    if (Array.from(text).length > MAX_INPUT_CHARS) throw new InvalidArguments(`원문은 ${MAX_INPUT_CHARS.toLocaleString('ko-KR')}자 이하만 변환할 수 있습니다. 나눠서 요청해 주세요.`);
    const result = await client.transformText(text, { ...options, inputKind: 'direct-text' }, progress, signal);
    return { content: [{ type: 'text', text: result.text }, { type: 'text', text: `[윤문 정보]\n${summary(options.strength, result)}` }] };
  }
  if (name === 'humanize_file') return humanizeFile(client, args, progress, signal);
  throw new UnknownTool(`Unknown tool: ${name}`);
}

async function humanizeFile(client: PortalClient, args: Message, progress: (message: string) => void,
  signal: AbortSignal): Promise<ToolResult> {
  const options = jobOptions(args, ['path', 'outputPath', 'strength', 'engine', 'model', 'effort']);
  const source = optionalString(args, 'path');
  if (!source || !path.isAbsolute(source)) throw new InvalidArguments('path에 원본 파일의 절대 경로를 넣어 주세요.');
  const extension = path.extname(source).toLowerCase();
  if (!['.txt', '.md', '.docx', '.pptx'].includes(extension)) throw new InvalidArguments('TXT, MD, DOCX, PPTX 파일만 다듬을 수 있습니다.');
  const office = extension === '.docx' || extension === '.pptx';
  if (office && args.strength !== undefined && options.strength !== 'normal')
    throw new InvalidArguments('DOCX·PPTX는 서식을 지키기 위해 강도를 고를 수 없고 보통으로만 다듬습니다. strength를 빼고 다시 요청해 주세요.');
  const info = await stat(source).catch(() => undefined);
  if (!info?.isFile()) throw new InvalidArguments('원본 파일을 찾을 수 없습니다.');
  if (info.size > (office ? OFFICE_BYTES : MAX_TEXT_FILE_BYTES))
    throw new InvalidArguments(office ? '문서는 50 MiB 이하만 지원합니다.' : 'TXT·MD 파일은 1 MiB 이하만 다듬을 수 있습니다.');
  const requested = optionalString(args, 'outputPath');
  if (requested !== undefined) {
    if (!path.isAbsolute(requested)) throw new InvalidArguments('outputPath는 절대 경로여야 합니다.');
    if (path.extname(requested).toLowerCase() !== extension) throw new InvalidArguments('outputPath의 확장자는 원본과 같아야 합니다.');
    if (path.resolve(requested) === path.resolve(source)) throw new InvalidArguments('원본 파일에는 저장할 수 없습니다. 새 파일 경로를 지정해 주세요.');
  }
  const bytes = new Uint8Array(await readFile(source));
  let output: Uint8Array, warnings: string[], chunks: number, elapsedMs: number, strength: string | undefined;
  if (office) {
    const result = await client.transformDocument(bytes, path.basename(source), options, progress, signal);
    ({ warnings, chunks, elapsedMs } = result);
    output = result.bytes;
  } else {
    const text = decodeTextFile(bytes);
    if (!text.trim()) throw new InvalidArguments('파일에 다듬을 글이 없습니다.');
    if (Array.from(text).length > MAX_INPUT_CHARS) throw new InvalidArguments(`원문은 ${MAX_INPUT_CHARS.toLocaleString('ko-KR')}자 이하만 변환할 수 있습니다. 나눠서 요청해 주세요.`);
    const result = await client.transformText(text, { ...options, inputKind: 'text-file' }, progress, signal);
    ({ warnings, chunks, elapsedMs } = result);
    strength = options.strength;
    output = new TextEncoder().encode(result.text);
  }
  if (signal.aborted) throw new PortalError('CLIENT_ABORTED', '요청이 취소되었습니다.');
  const saved = await writeNew(requested ?? source, output, requested === undefined);
  return { content: [{ type: 'text', text: lines(`저장한 파일: ${saved}`, summary(strength, { warnings, chunks, elapsedMs }),
    '원본 파일은 바꾸지 않았습니다.') }] };
}

/** Writes `bytes` to a file that does not exist yet: `target` itself, or with `numbered` the first free
 * `<stem>-humanized[-N]<ext>` next to it. Never replaces a file. */
async function writeNew(target: string, bytes: Uint8Array, numbered: boolean): Promise<string> {
  const directory = path.dirname(target), extension = path.extname(target), stem = path.basename(target, extension);
  for (let index = 1; index <= (numbered ? 100 : 1); index++) {
    const file = numbered ? path.join(directory, `${stem}-humanized${index > 1 ? `-${index}` : ''}${extension}`) : target;
    let handle;
    try { handle = await open(file, 'wx'); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'EEXIST') continue;
      throw new InvalidArguments(`결과 파일을 만들지 못했습니다: ${file}`);
    }
    try {
      await handle.writeFile(bytes);
      await handle.close();
      return file;
    } catch {
      await handle.close().catch(() => undefined);
      await rm(file, { force: true });                // no half-written result is left behind
      throw new InvalidArguments(`결과 파일을 저장하지 못했습니다: ${file}`);
    }
  }
  throw new InvalidArguments(numbered ? '원본 옆에 저장할 새 파일 이름을 찾지 못했습니다. outputPath를 지정해 주세요.'
    : '같은 이름의 파일이 이미 있습니다. 다른 outputPath를 지정해 주세요.');
}
