// Stand-in for `codex app-server`: newline-delimited JSON-RPC 2.0 on stdio. FAKE_MODE picks the behaviour.
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';
import { createInterface } from 'node:readline';

const mode = process.env.FAKE_MODE ?? 'ok';
const lists = JSON.parse(readFileSync(new URL('./model-lists.json', import.meta.url), 'utf8'));
const models = mode === 'empty' ? lists.codex.filter(model => model.hidden).concat([{ id: 'gpt-bare', displayName: 'GPT-Bare', supportedReasoningEfforts: [] }]) : lists.codex;
const pageSize = Number(process.env.FAKE_PAGE_SIZE ?? 4);
if (process.env.FAKE_PID_FILE) writeFileSync(process.env.FAKE_PID_FILE, String(process.pid));
if (process.argv[2] !== 'app-server') { process.stderr.write('error: unexpected arguments\n'); process.exit(2); }
process.stderr.write('codex app-server (fake) listening on stdio\n');

const send = message => process.stdout.write(`${JSON.stringify(message)}\n`);
const notify = () => send({ jsonrpc: '2.0', method: 'account/rateLimits/updated', params: { primary: null } });
const lines = createInterface({ input: process.stdin });
lines.on('line', line => {
  if (process.env.FAKE_LOG_FILE) appendFileSync(process.env.FAKE_LOG_FILE, `${line}\n`);
  const message = JSON.parse(line);
  if (mode === 'silent') return;
  if (mode === 'exit') { process.stderr.write('fatal: config could not be loaded\n'); process.exit(3); }
  if (message.method === 'initialize') {
    notify();
    process.stdout.write('not json, ignored\n');
    send({ jsonrpc: '2.0', id: message.id, result: { userAgent: 'humanize-portal/0.167.0 (Mac OS 26.1.0; arm64) fake (humanize-portal; 0.5.0)', codexHome: '/nowhere' } });
  } else if (message.method === 'model/list') {
    if (mode === 'rpc-error') { send({ jsonrpc: '2.0', id: message.id, error: { code: -32603, message: 'model catalog unavailable' } }); return; }
    const start = message.params.cursor ? Number(message.params.cursor.replace('page-', '')) : 0;
    const visible = models.filter(model => message.params.includeHidden || !model.hidden || mode === 'leak-hidden' || mode === 'empty');
    const data = visible.slice(start, start + pageSize), next = start + pageSize < visible.length ? `page-${start + pageSize}` : null;
    notify();
    send({ jsonrpc: '2.0', id: message.id, result: { data, nextCursor: next } });
  }
});
// The real app-server exits once stdin closes; `linger` ignores that to exercise the kill after the grace period.
lines.on('close', () => { if (mode !== 'linger') process.exit(0); else setInterval(() => {}, 1000); });
