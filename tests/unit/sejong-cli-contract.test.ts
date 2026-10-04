// What the real v2 CLI (engine_runtime/sejong_cli.py, WP-10) writes, fed to the TypeScript side that consumes it:
// the adapter's plan/check validators and gate parser, the manifest parser and the prompt builder (WP-11a).
// tests/fixtures/sejong/cli-contract.json is produced by tests/skills/test_sejong_pipeline.py, which fails when
// the CLI output and this fixture drift apart (SEJONG_WRITE_FIXTURES=1 regenerates it). Constructed text only.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  checkProblems, gatePolicy, gateResultOf, parseSejongManifest, planProblems, SejongPython, type JsonSchema
} from '../../src/engine/sejong/python-adapter.js';
import { buildSejongPrompt, reviewTypeOf } from '../../src/engine/sejong/prompt.js';
import { parseSejongResponse } from '../../src/engine/sejong/response.js';
import type { CheckReport, Plan } from '../../src/engine/sejong/types.js';
import { exited, FakeCommandRunner } from '../helpers/fake-command-runner.js';

const root = path.resolve('.');
const engineRoot = path.join(root, 'engine_runtime');
const json = <T>(file: string): T => JSON.parse(readFileSync(file, 'utf8')) as T;
const contract = json<{
  source: string;
  manifest: unknown;
  plan: Plan;
  checks: Record<'accept' | 'retry' | 'attempt2' | 'rollback', CheckReport>;
  gates: Record<'same' | 'number' | 'emoticon', { exitCode: 0 | 1 | 2 | 3; stdout: string }>;
}>(path.join(root, 'tests/fixtures/sejong/cli-contract.json'));
const schemas = {
  plan: json<JsonSchema>(path.join(engineRoot, 'sejong/schemas/plan.schema.json')),
  check: json<JsonSchema>(path.join(engineRoot, 'sejong/schemas/check.schema.json'))
};
const signal = new AbortController().signal;
const NONCE = 'WP10CONTRACT';

describe('v2 CLI output against the TypeScript contract', () => {
  it('passes the plan and check validators of the adapter', () => {
    expect(planProblems(contract.plan, schemas.plan)).toEqual([]);
    for (const [name, report] of Object.entries(contract.checks)) {
      expect(checkProblems(report, schemas.check), name).toEqual([]);
      expect(gateResultOf(report).policy, name).toBe(gatePolicy(report.gate.exit_code, report.attempt));
    }
    expect(contract.checks.accept.gate.exit_code).toBe(0);
    expect(contract.checks.rollback.policy).toBe('rollback');
  });

  it('parses the manifest with its sejong block', () => {
    const manifest = parseSejongManifest(contract.manifest);
    expect(manifest.processingMode).toBe('single');
    expect(manifest.sejong).toEqual({ version: 1, genre: 'blog', seams: [] });
  });

  it('builds the attempt-1 prompt from the plan and accepts a reply for it', () => {
    const prompt = buildSejongPrompt({ plan: contract.plan, source: contract.source, nonce: NONCE, attempt: 1 });
    expect(prompt).toContain('"id":"R1"');
    expect(prompt).toContain('[열린 검토]');
    const reply = JSON.stringify({ replacements: [{ id: 'R1', text: '왜냐하면 일정이 바뀌었기 때문입니다.', reason: 'SSJ-A01' }],
      rewrittenText: '', warnings: [] });
    expect(parseSejongResponse(reply, contract.plan).replacements).toHaveLength(1);
  });

  it('builds the retry prompt from the check report, an open-review nomination included', () => {
    const retry = contract.checks.retry.retry;
    expect(retry.map(item => item.id).sort()).toEqual(['R1', 'S1']);
    const prompt = buildSejongPrompt({ plan: contract.plan, source: contract.source, nonce: NONCE, attempt: 2, retry });
    expect(prompt).toContain('R1 이전 답:');
    expect(prompt).toContain('S1 이전 답:');
    expect(prompt).toContain('(voice_level)');
    expect(reviewTypeOf('14 부적절한 종결어미 사용')).toBe(14);
  });

  it('parses the verify gate JSON exactly as PythonEngine.verify() does', async () => {
    for (const [name, gate] of Object.entries(contract.gates)) {
      const runner = new FakeCommandRunner([exited(gate.stdout, gate.exitCode)]);
      const python = new SejongPython({ pythonCommand: 'python3', engineRoot, runner });
      const result = await python.verifyDocument('before.txt', 'after.txt', signal);
      const raw = JSON.parse(gate.stdout) as { hardFailures: string[]; shadowFailures: string[] };
      expect(result.exitCode, name).toBe(gate.exitCode);
      expect(result.policy, name).toBe(gatePolicy(gate.exitCode, 1));
      expect(result.hardFailures, name).toEqual(raw.hardFailures);
      expect(result.shadowFailures, name).toEqual(raw.shadowFailures);
    }
    expect(contract.gates.number.exitCode).toBe(2);
    expect(contract.gates.emoticon.exitCode).toBe(1);
  });
});
