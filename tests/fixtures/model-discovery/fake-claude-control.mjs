// Stand-in for `claude -p --input-format stream-json --output-format stream-json`: answers the initialize control request.
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';
import { createInterface } from 'node:readline';

const mode = process.env.FAKE_MODE ?? 'ok';
const lists = JSON.parse(readFileSync(new URL('./model-lists.json', import.meta.url), 'utf8'));
const expected = ['-p', '--restricted', '--strict-mcp-config', '--tools', '', '--no-session-persistence',
  '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose'];
if (process.env.FAKE_PID_FILE) writeFileSync(process.env.FAKE_PID_FILE, String(process.pid));
if (JSON.stringify(process.argv.slice(2)) !== JSON.stringify(expected)) { process.stderr.write(`error: unexpected arguments ${JSON.stringify(process.argv.slice(2))}\n`); process.exit(2); }

const send = message => process.stdout.write(`${JSON.stringify(message)}\n`);
const lines = createInterface({ input: process.stdin });
lines.on('line', line => {
  if (process.env.FAKE_LOG_FILE) appendFileSync(process.env.FAKE_LOG_FILE, `${line}\n`);
  const message = JSON.parse(line);
  if (mode === 'silent') return;
  if (mode === 'exit') { process.stderr.write('Error: Invalid API key\n'); process.exit(1); }
  if (message.type !== 'control_request' || message.request?.subtype !== 'initialize') return;
  send({ type: 'system', subtype: 'hook_started', hook_name: 'SessionStart', session_id: 'fake' });
  send({ type: 'control_response', response: { subtype: 'success', request_id: 'someone-else', response: { models: [] } } });
  if (mode === 'error') { send({ type: 'control_response', response: { subtype: 'error', request_id: message.request_id, error: 'Already initialized' } }); return; }
  const models = mode === 'empty' ? lists.claude.filter(model => !model.supportsEffort) : lists.claude;
  send({ type: 'control_response', response: { subtype: 'success', request_id: message.request_id,
    response: { commands: [], agents: [], output_style: 'default', models, account: {}, claude_code_version: '2.1.323' } } });
});
lines.on('close', () => process.exit(0));
