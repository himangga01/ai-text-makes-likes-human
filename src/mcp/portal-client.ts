import http from 'node:http';
import https from 'node:https';
import { Readable } from 'node:stream';
import type { TransformEvent } from '../contracts.js';

/** HTTP client of the LAN portal for the MCP server: the portal's queue, engines and checks do the work, so an MCP
 * job is exactly a web job (same NDJSON events, same Office upload → transform → result → delete lifecycle). */
export type Engine = 'codex' | 'claude';
export interface JobOptions { engine: Engine; model?: string; effort?: string }
export type Progress = (message: string) => void;

export class PortalError extends Error {
  constructor(readonly code: string, message: string) { super(message); }
}

export interface TextResult { text: string; warnings: string[]; sourceChars: number; outputChars: number; chunks: number; elapsedMs: number }
export interface DocumentResult { bytes: Uint8Array; name: string; format: 'docx' | 'pptx'; warnings: string[]; chunks: number; elapsedMs: number }

export class PortalClient {
  constructor(readonly baseUrl: string, private readonly fetcher: typeof fetch = httpFetch) {}

  async health(signal?: AbortSignal): Promise<Record<string, unknown>> {
    const response = await this.request('/api/health', { signal });
    // A degraded portal answers 503 with the same body plus errorCode and message: that body is the answer.
    if (!response.ok && response.status !== 503) throw await failure(response);
    return await response.json() as Record<string, unknown>;
  }

  async transformText(text: string, options: JobOptions & { inputKind: 'direct-text' | 'text-file'; strength: string },
    progress: Progress, signal?: AbortSignal): Promise<TextResult> {
    const query = jobQuery(options, { inputKind: options.inputKind, strength: options.strength });
    const response = await this.request(`/api/transform?${query}`, {
      method: 'POST', headers: { 'content-type': 'text/plain; charset=utf-8' }, body: text, signal });
    if (!response.ok) throw await failure(response);
    let output = '';
    const warnings: string[] = [];
    const done = await readEvents(response, event => {
      if (event.type === 'result-delta') output += event.text;
      else if (event.type === 'warning') warnings.push(event.message);
      else report(event, progress);
    });
    return { text: output, warnings, sourceChars: done.sourceChars, outputChars: done.outputChars, chunks: done.chunks, elapsedMs: done.elapsedMs };
  }

  async transformDocument(bytes: Uint8Array, fileName: string, options: JobOptions, progress: Progress,
    signal?: AbortSignal): Promise<DocumentResult> {
    const uploaded = await this.request('/api/documents', { method: 'POST', signal, body: bytes as BodyInit,
      headers: { 'content-type': 'application/octet-stream', 'x-file-name': encodeURIComponent(fileName) } });
    if (!uploaded.ok) throw await failure(uploaded);
    const document = await uploaded.json() as { id: string; token: string; name: string; format: 'docx' | 'pptx'; warnings?: string[] };
    const authorization = { authorization: `Bearer ${document.token}` };
    try {
      progress(`문서를 읽었습니다(${document.format.toUpperCase()}).`);
      const response = await this.request(`/api/documents/${encodeURIComponent(document.id)}/transform?${jobQuery(options)}`,
        { method: 'POST', headers: authorization, signal });
      if (!response.ok) throw await failure(response);
      const warnings = [...(document.warnings ?? [])];
      let name = document.name;
      const done = await readEvents(response, event => {
        if (event.type === 'warning') { if (!warnings.includes(event.message)) warnings.push(event.message); }
        else if (event.type === 'document-result') name = event.name;
        else report(event, progress);
      });
      const result = await this.request(`/api/documents/${encodeURIComponent(document.id)}/result`, { headers: authorization, signal });
      if (!result.ok) throw await failure(result);
      return { bytes: new Uint8Array(await result.arrayBuffer()), name, format: document.format, warnings, chunks: done.chunks, elapsedMs: done.elapsedMs };
    } finally {
      // The portal keeps a finished document for 30 minutes; this client has its bytes, so it closes it now.
      await this.request(`/api/documents/${encodeURIComponent(document.id)}`, { method: 'DELETE', headers: authorization })
        .then(response => response.body?.cancel(), () => undefined);
    }
  }

  private async request(pathname: string, init: RequestInit): Promise<Response> {
    try {
      return await this.fetcher(new URL(pathname, this.baseUrl), init);
    } catch (error) {
      if (init.signal?.aborted) throw new PortalError('CLIENT_ABORTED', '요청이 취소되었습니다.');
      throw new PortalError('PORTAL_UNREACHABLE', `윤문 포털(${this.baseUrl})에 연결할 수 없습니다. 포털 서버가 실행 중인지, HUMANIZE_PORTAL_URL이 맞는지 확인해 주세요.`);
    }
  }
}

/** `fetch` over node:http(s). Node's built-in fetch (undici) drops a response whose headers or body stay silent for
 * 5 minutes, and a portal job can be silent longer (waiting in the queue, one chunk may take up to 10 minutes), so the
 * MCP server would fail a job the portal is still running. node:http has no idle limit; the caller's signal still
 * cancels, and the client's own tool timeout bounds the call. */
export const httpFetch: typeof fetch = async (input, init = {}) => {
  const url = new URL(input instanceof Request ? input.url : input);
  const raw = init.body;
  if (raw != null && typeof raw !== 'string' && !ArrayBuffer.isView(raw)) throw new TypeError('httpFetch sends string or byte bodies only');
  const body = raw == null ? undefined : typeof raw === 'string' ? Buffer.from(raw) : Buffer.from(raw.buffer, raw.byteOffset, raw.byteLength);
  const headers = Object.fromEntries(new Headers(init.headers));
  if (body) headers['content-length'] = String(body.length);
  return await new Promise<Response>((resolve, reject) => {
    const request = (url.protocol === 'https:' ? https : http).request(url,
      { method: init.method ?? 'GET', headers, signal: init.signal ?? undefined }, response => {
        const responseHeaders = new Headers();
        for (const [name, value] of Object.entries(response.headers))
          for (const item of [value ?? []].flat()) responseHeaders.append(name, item);
        const status = response.statusCode ?? 502;
        const empty = status === 204 || status === 205 || status === 304 || init.method === 'HEAD';
        if (empty) response.on('error', () => undefined).resume();
        resolve(new Response(empty ? null : Readable.toWeb(response) as ReadableStream<Uint8Array>, { status, headers: responseHeaders }));
      });
    request.on('error', reject);
    request.end(body);
  });
};

function jobQuery(options: JobOptions, extra: Record<string, string> = {}): string {
  return new URLSearchParams({ engine: options.engine, ...(options.model ? { model: options.model } : {}),
    ...(options.effort ? { effort: options.effort } : {}), ...extra }).toString();
}

async function failure(response: Response): Promise<PortalError> {
  const body = await response.json().catch(() => undefined) as { code?: unknown; message?: unknown } | undefined;
  return new PortalError(typeof body?.code === 'string' ? body.code : `HTTP_${response.status}`,
    typeof body?.message === 'string' ? body.message : `윤문 포털이 요청을 거절했습니다(HTTP ${response.status}).`);
}

function report(event: TransformEvent, progress: Progress): void {
  if (event.type === 'queued') progress(`대기 중입니다(앞에 ${event.position}건).`);
  else if (event.type === 'progress') progress(event.message);
}

type Done = Extract<TransformEvent, { type: 'done' }>;

/** Reads the NDJSON stream to its `done` event; an `error` event, or a stream that ends without `done`, fails. */
async function readEvents(response: Response, onEvent: (event: TransformEvent) => void): Promise<Done> {
  if (!response.body) throw new PortalError('ENGINE_FAILED', '윤문 포털의 응답이 비어 있습니다.');
  const decoder = new TextDecoder();
  let buffer = '';
  let done: Done | undefined;
  const handle = (line: string): void => {
    if (!line.trim()) return;
    const event = JSON.parse(line) as TransformEvent;
    if (event.type === 'error') throw new PortalError(event.code, event.message);
    if (event.type === 'done') done = event;
    else onEvent(event);
  };
  for await (const chunk of response.body as unknown as AsyncIterable<Uint8Array>) {
    buffer += decoder.decode(chunk, { stream: true });
    let newline: number;
    while ((newline = buffer.indexOf('\n')) >= 0) {
      handle(buffer.slice(0, newline));
      buffer = buffer.slice(newline + 1);
    }
  }
  handle(buffer + decoder.decode());
  if (!done) throw new PortalError('ENGINE_FAILED', '윤문 포털이 완료 응답 없이 연결을 닫았습니다.');
  return done;
}

/** TXT/MD bytes as the portal page reads them (public/text-file.js): a BOM picks UTF-8/UTF-16, then strict UTF-8,
 * then CP949; NULs without a BOM (UTF-16 without BOM) are refused instead of guessed. Line endings become LF. */
export function decodeTextFile(bytes: Uint8Array): string {
  const decode = (label: string, offset = 0): string => new TextDecoder(label, { fatal: true }).decode(bytes.subarray(offset));
  let text: string;
  try {
    if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) text = decode('utf-8', 3);
    else if (bytes[0] === 0xff && bytes[1] === 0xfe) text = decode('utf-16le', 2);
    else if (bytes[0] === 0xfe && bytes[1] === 0xff) text = decode('utf-16be', 2);
    else if (bytes.includes(0)) throw new PortalError('TEXT_FILE_UNSUPPORTED_ENCODING', 'BOM이 없는 UTF-16 등 지원하지 않는 인코딩입니다. UTF-8로 저장해 다시 시도해 주세요.');
    else { try { text = decode('utf-8'); } catch { text = decode('euc-kr'); } }
  } catch (error) {
    if (error instanceof PortalError) throw error;
    throw new PortalError('TEXT_FILE_DECODE_FAILED', '텍스트 파일을 읽지 못했습니다. 다른 인코딩으로 저장해 다시 시도해 주세요.');
  }
  return text.replace(/\r\n?/g, '\n');
}
