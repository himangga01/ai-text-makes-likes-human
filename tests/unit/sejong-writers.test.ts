// runPrompt of the two writer CLIs (DESIGN 4.3, 5.2 SejongWriter) on fake command runners: the Codex and Claude
// CLIs are never run. The legacy transform() keeps needing the rulebook; runPrompt never reads one.
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ClaudeRunner } from '../../src/engine/claude-runner.js';
import { CodexRunner, type CodexPermitPool } from '../../src/engine/codex-runner.js';
import type { SejongWriter } from '../../src/engine/sejong/engine.js';
import type { CommandRequest, CommandResult, CommandRunner } from '../../src/process/command-runner.js';
import { exited, FakeCommandRunner } from '../helpers/fake-command-runner.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';

const SCHEMA = path.resolve('src/engine/sejong/response-schema.json');
const REPLY = '{"replacements":[{"id":"R1","text":"고친 문장입니다.","reason":"SSJ-A01"}],"rewrittenText":"","warnings":[]}';
const pool: CodexPermitPool & { runs: number } = { maxObserved: 1, runs: 0, run(_signal, task) { this.runs += 1; return task(); } };
const signal = new AbortController().signal;

/** Writes `output` where Codex is told to put its last message. */
class CodexOutput implements CommandRunner {
  readonly calls: CommandRequest[] = [];
  constructor(private readonly output: string | undefined, private readonly result: CommandResult = exited('')) {}
  async run(request: CommandRequest): Promise<CommandResult> {
    this.calls.push(request);
    const flag = request.args.indexOf('--output-last-message');
    if (this.output !== undefined && flag >= 0) await writeFile(request.args[flag + 1]!, this.output, 'utf8');
    return this.result;
  }
}

let dir = '';
beforeEach(async () => { dir = await makeTestRoot('sejong-writers-'); pool.runs = 0; });
afterEach(async () => { await removeTestRoot(dir); });

describe('CodexRunner.runPrompt', () => {
  it('sends the prompt on stdin with the given schema and returns the raw last message', async () => {
    const runner = new CodexOutput(REPLY);
    const codex: SejongWriter = new CodexRunner({ codexCommand: 'codex', schemaPath: '/legacy/output-schema.json', timeoutMs: 1000, runner, permitPool: pool });
    const out = path.join(dir, 'writer-1-attempt-1.json');
    expect(await codex.runPrompt('프롬프트 본문', SCHEMA, out, signal, { model: 'gpt-6-sol', effort: 'high' })).toBe(REPLY);
    const call = runner.calls[0]!;
    expect(call.stdin).toBe('프롬프트 본문');
    expect(call.args.slice(call.args.indexOf('--output-schema'), call.args.indexOf('--output-schema') + 4))
      .toEqual(['--output-schema', SCHEMA, '--output-last-message', out]);
    expect(call.args).toEqual(expect.arrayContaining(['--model', 'gpt-6-sol', 'model_reasoning_effort="high"', '--sandbox', 'read-only', '--ephemeral']));
    expect(call.cwd).not.toBe(dir);
    expect(pool.runs).toBe(1);
  });

  it('maps CLI failures exactly as transform() does and rejects an unsupported model before spawning', async () => {
    const failing = new CodexOutput(undefined, exited('', 1, 'ERROR: {"status":400,"error":{"message":"The model is not supported"}}'));
    const codex = new CodexRunner({ codexCommand: 'codex', schemaPath: SCHEMA, timeoutMs: 1000, runner: failing, permitPool: pool });
    await expect(codex.runPrompt('p', SCHEMA, path.join(dir, 'o.json'), signal)).rejects.toMatchObject({ publicCode: 'MODEL_UNAVAILABLE' });
    const missing = new CodexRunner({ codexCommand: 'codex', schemaPath: SCHEMA, timeoutMs: 1000, runner: new CodexOutput(undefined), permitPool: pool });
    await expect(missing.runPrompt('p', SCHEMA, path.join(dir, 'o.json'), signal)).rejects.toMatchObject({ publicCode: 'ENGINE_OUTPUT_INVALID' });
    const timeout = new CodexRunner({ codexCommand: 'codex', schemaPath: SCHEMA, timeoutMs: 1000, permitPool: pool,
      runner: new CodexOutput(undefined, { exitCode: -1, stdout: '', stderr: '', termination: 'timeout' }) });
    await expect(timeout.runPrompt('p', SCHEMA, path.join(dir, 'o.json'), signal)).rejects.toMatchObject({ publicCode: 'ENGINE_TIMEOUT' });
    const none = new CodexOutput(REPLY);
    await expect(new CodexRunner({ codexCommand: 'codex', schemaPath: SCHEMA, timeoutMs: 1000, runner: none, permitPool: pool })
      .runPrompt('p', SCHEMA, path.join(dir, 'o.json'), signal, { model: 'unknown-model', effort: 'high' })).rejects.toThrow();
    expect(none.calls).toHaveLength(0);
  });

  it('still needs quickRulesPath for the legacy transform()', async () => {
    const input = path.join(dir, 'in.txt');
    await writeFile(input, '원문이다.', 'utf8');
    const runner = new CodexOutput('{}');
    const codex = new CodexRunner({ codexCommand: 'codex', schemaPath: SCHEMA, timeoutMs: 1000, runner, permitPool: pool });
    await expect(codex.transform(input, path.join(dir, 'o.json'), 1, signal)).rejects.toThrow('quickRulesPath');
    expect(runner.calls).toHaveLength(0);
  });
});

describe('ClaudeRunner.runPrompt', () => {
  it('passes the schema inline without $schema, returns the structured reply and keeps it in outputPath', async () => {
    const fake = new FakeCommandRunner([exited(JSON.stringify({ is_error: false, subtype: 'success', structured_output: JSON.parse(REPLY) }))]);
    const claude: SejongWriter = new ClaudeRunner({ claudeCommand: 'claude', schemaPath: '/legacy/output-schema.json', timeoutMs: 1000, runner: fake, permitPool: pool });
    const out = path.join(dir, 'writer-1-attempt-2.json');
    const raw = await claude.runPrompt('프롬프트', SCHEMA, out, signal);
    expect(JSON.parse(raw)).toEqual(JSON.parse(REPLY));
    expect(await readFile(out, 'utf8')).toBe(raw);
    const call = fake.calls[0]!;
    expect(call.stdin).toBe('프롬프트');
    expect(call.cwd).toBe(dir);
    const inline = JSON.parse(call.args[call.args.indexOf('--json-schema') + 1]!) as Record<string, unknown>;
    const { $schema, ...expected } = JSON.parse(await readFile(SCHEMA, 'utf8')) as Record<string, unknown>;
    expect($schema).toBeDefined();
    expect(inline).toEqual(expected);
    expect(call.args).toEqual(expect.arrayContaining(['-p', '--restricted', '--tools', '', '--no-session-persistence']));
  });

  it('returns a text result unparsed and maps a failed envelope to ENGINE_FAILED', async () => {
    const text = new FakeCommandRunner([exited(JSON.stringify({ is_error: false, subtype: 'success', result: 'not json at all' }))]);
    const claude = new ClaudeRunner({ claudeCommand: 'claude', schemaPath: SCHEMA, timeoutMs: 1000, runner: text, permitPool: pool });
    expect(await claude.runPrompt('p', SCHEMA, path.join(dir, 'o.json'), signal)).toBe('not json at all');
    const failed = new FakeCommandRunner([exited(JSON.stringify({ is_error: true, subtype: 'error_max_turns' }), 1)]);
    await expect(new ClaudeRunner({ claudeCommand: 'claude', schemaPath: SCHEMA, timeoutMs: 1000, runner: failed, permitPool: pool })
      .runPrompt('p', SCHEMA, path.join(dir, 'o.json'), signal)).rejects.toMatchObject({ publicCode: 'ENGINE_FAILED' });
  });

  it('still needs quickRulesPath for the legacy transform()', async () => {
    const input = path.join(dir, 'in.txt');
    await writeFile(input, '원문이다.', 'utf8');
    const fake = new FakeCommandRunner([]);
    const claude = new ClaudeRunner({ claudeCommand: 'claude', schemaPath: SCHEMA, timeoutMs: 1000, runner: fake, permitPool: pool });
    await expect(claude.transform(input, path.join(dir, 'o.json'), 1, signal)).rejects.toThrow('quickRulesPath');
    expect(fake.calls).toHaveLength(0);
  });
});
