import { createInterface } from 'node:readline';
import { PortalClient } from './portal-client.js';
import { createSession } from './session.js';

// stdio entry of the MCP server (src/mcp/session.ts): `node dist/mcp/server.js`. stdout carries only protocol
// messages; the portal address comes from HUMANIZE_PORTAL_URL (default: this machine's portal).
const portalUrl = process.env.HUMANIZE_PORTAL_URL?.trim() || 'http://127.0.0.1:7882';
let parsed: URL | undefined;
try { parsed = new URL(portalUrl); } catch { /* reported below */ }
if (!parsed || (parsed.protocol !== 'http:' && parsed.protocol !== 'https:')) {
  process.stderr.write('HUMANIZE_PORTAL_URL must be an http(s) URL, e.g. http://192.168.0.10:7882\n');
  process.exit(2);
}

const session = createSession({
  client: new PortalClient(portalUrl),
  send: message => { process.stdout.write(JSON.stringify(message) + '\n'); }
});
const pending = new Set<Promise<void>>();
const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on('line', line => {
  if (!line.trim()) return;
  let message: unknown;
  try { message = JSON.parse(line); }
  catch { process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } }) + '\n'); return; }
  const task = session.handle(message).catch(() => undefined).finally(() => pending.delete(task));
  pending.add(task);
});
input.on('close', () => {
  // The client went away: cancel running portal jobs (the portal stops a job whose client disconnected), then exit.
  session.close();
  void Promise.allSettled([...pending]).then(() => process.exit(0));
});
process.stderr.write(`humanize-kr MCP server ready (portal ${portalUrl})\n`);
