// SejongEngine orchestration against a scripted Python adapter and a stub writer: no Python, no writer CLI.
// The plan, source and check reports are the WP-10 CLI contract fixture (constructed text only).
import { readFileSync } from 'node:fs';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { loadConfig } from '../../src/config.js';
import type { TransformEvent } from '../../src/contracts.js';
import { HumanizeEngine } from '../../src/engine/humanize-engine.js';
import type { ModelSettings } from '../../src/engine/model-policy.js';
import type { GateResult } from '../../src/engine/python-engine.js';
import { SejongEngine, type SejongPythonPort, type SejongWriter } from '../../src/engine/sejong/engine.js';
import {
  parseSejongManifest, type CheckArgs, type FinalizeReport, type PlanExpectation, type SejongManifest
} from '../../src/engine/sejong/python-adapter.js';
import type { CheckReport, Plan } from '../../src/engine/sejong/types.js';
import { JobWorkspace } from '../../src/engine/workspace.js';
import type { CommandRequest, CommandResult, CommandRunner } from '../../src/process/command-runner.js';
import { createProductionRuntime } from '../../src/runtime/create-runtime.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';

const root = path.resolve('.');
const contract = JSON.parse(readFileSync(path.join(root, 'tests/fixtures/sejong/cli-contract.json'), 'utf8')) as {
  source: string; manifest: unknown; plan: Plan; checks: Record<'accept' | 'retry' | 'attempt2' | 'rollback', CheckReport>;
};
const quickRules = readFileSync(path.join(root, 'vendor/humanize-engine/skills/humanize-korean/references/quick-rules.md'), 'utf8');
const VERSION = { id: 'super-sejong' as const, version: contract.plan.engine.version, schema: 1 };
const clone = <T>(value: T): T => structuredClone(value);
const okGate = (exitCode: 0 | 1 | 2 | 3 = 0, hardFailures: string[] = [], shadowFailures: string[] = []): GateResult => ({
  status: (['ok', 'warn', 'abort', 'error'] as const)[exitCode], exitCode,
  gateCodes: [(['GATE_OK', 'GATE_WARN', 'GATE_ABORT', 'GATE_ERROR'] as const)[exitCode]],
  hardFailures, shadowFailures, policy: exitCode === 0 ? 'accept' : exitCode === 3 ? 'error' : 'retry'
});

interface Script {
  plan?: Plan;
  checks: CheckReport[];
  /** Text the check step writes as the decided chunk, per call. */
  decided?: string[];
  gates?: GateResult[];
  finalize?: Partial<FinalizeReport>;
  versions?: Array<typeof VERSION>;
}

/** Scripted SejongPython: records every call and plays back the contract fixture. */
class FakePython implements SejongPythonPort {
  readonly packageRoot = path.join(root, 'engine_runtime', 'sejong');
  readonly checks: Array<CheckArgs & { reply: string }> = [];
  readonly gates: Array<[string, string]> = [];
  plan: Plan;
  constructor(private readonly script: Script) { this.plan = script.plan ?? clone(contract.plan); }
  async prepare(runDir: string): Promise<SejongManifest> {
    const manifest = parseSejongManifest(contract.manifest);
    manifest.sejong!.plans = [{ chunk: 1, file: 'plan-01.json', needsModel: this.plan.needsModel }];
    await writeFile(path.join(runDir, 'plan-01.json'), JSON.stringify(this.plan), 'utf8');
    return manifest;
  }
  async readPlan(_file: string, expect: PlanExpectation): Promise<Plan> {
    if (expect.chunkIndex !== 1 || expect.chunkTotal !== 1) throw new Error('unexpected chunk');
    return this.plan;
  }
  async check(args: CheckArgs): Promise<CheckReport> {
    const call = this.checks.length;
    this.checks.push({ ...args, reply: await readFile(args.response!, 'utf8') });
    await writeFile(args.out, this.script.decided?.[call] ?? `decided ${call + 1}\n`, 'utf8');
    const report = this.script.checks[call];
    if (!report) throw new Error('no scripted check report');
    return report;
  }
  async verifyDocument(before: string, after: string): Promise<GateResult> {
    this.gates.push([await readFile(before, 'utf8'), await readFile(after, 'utf8')]);
    return this.script.gates?.[this.gates.length - 1] ?? okGate();
  }
  async finalize(runDir: string): Promise<string> {
    const output = path.join(runDir, '03_reassembled.md');
    await writeFile(output, await readFile(path.join(runDir, '02_chunk_01_rewritten.txt'), 'utf8'), 'utf8');
    return output;
  }
  async readFinalizeReport(): Promise<FinalizeReport> {
    return { warningCodes: [], rolledBackChunks: [], seamReverts: 0, seamCodes: [], floorCodes: [], documentRolledBack: false,
      changeRate: 0, ...this.script.finalize };
  }
}

class StubWriter implements SejongWriter {
  readonly prompts: string[] = [];
  readonly calls: Array<{ schemaPath: string; outputPath: string; settings?: ModelSettings }> = [];
  constructor(private readonly replies: string[]) {}
  async runPrompt(prompt: string, schemaPath: string, outputPath: string, _signal: AbortSignal, settings?: ModelSettings): Promise<string> {
    this.prompts.push(prompt);
    this.calls.push({ schemaPath, outputPath, ...(settings ? { settings } : {}) });
    const reply = this.replies.shift();
    if (reply === undefined) throw new Error('unexpected writer call');
    return reply;
  }
}

const reply = (replacements: Array<{ id: string; text: string }>, warnings: string[] = []): string =>
  JSON.stringify({ replacements: replacements.map(item => ({ ...item, reason: 'SSJ' })), rewrittenText: '', warnings });
const EMPTY = '{"replacements":[],"rewrittenText":"","warnings":[]}';

let outer = '';
beforeEach(async () => { outer = await makeTestRoot('sejong-engine-unit-'); });
afterEach(async () => { await removeTestRoot(outer); });

async function run(python: FakePython, writer: StubWriter, options: { versions?: Array<typeof VERSION>; settings?: ModelSettings } = {}) {
  const workspace = await JobWorkspace.create(outer, `job-${Math.random().toString(36).slice(2)}`);
  await writeFile(workspace.path('01_input.txt'), contract.source, 'utf8');
  await writeFile(workspace.path('01_chunk_01_input.txt'), contract.source, 'utf8');
  const versions = [...(options.versions ?? [])];
  const engine = new SejongEngine({
    python, writer, schemaPath: '/schema/response-schema.json', chunkConcurrency: 1, now: () => 0, env: {},
    readVersion: async () => versions.shift() ?? VERSION
  });
  const events: TransformEvent[] = [];
  const result = await engine.transform({
    jobId: workspace.jobId, workspace, signal: new AbortController().signal, onEvent: event => events.push(event),
    rewriteOptions: { inputKind: 'direct-text', strength: 'medium' }, ...(options.settings ? { settings: options.settings } : {})
  });
  return { result, events, workspace, output: await readFile(result.finalPath, 'utf8') };
}

const codes = (warnings: Array<{ code: string }>): string[] => warnings.map(warning => warning.code);

describe('SejongEngine without a model call', () => {
  it('checks an empty plan with an empty reply, never calls the writer, and delivers base(x)', async () => {
    const plan = clone(contract.plan);
    plan.requests = [];
    plan.findings = plan.findings.filter(finding => finding.action !== 'request');
    plan.openReview = { enabled: false, maxSentences: 0 };
    plan.options.openReview = false;
    plan.needsModel = false;
    const python = new FakePython({ plan, checks: [contract.checks.accept], decided: ['고친 결과\n'] });
    const writer = new StubWriter([]);
    const { result, output, events } = await run(python, writer);
    expect(writer.prompts).toHaveLength(0);
    expect(python.checks).toHaveLength(1);
    expect(python.checks[0]).toMatchObject({ attempt: 1, reply: EMPTY });
    expect(python.checks[0]!.base).toBeUndefined();
    expect(output).toBe('고친 결과\n');
    expect(result.warnings).toEqual([{ code: 'SEJONG_NO_EDIT_NEEDED',
      message: '1번 구간에서 고칠 문장을 찾지 못해 모델을 호출하지 않았습니다. 확실한 맞춤법 오류 1곳만 자동으로 고쳤습니다.' }]);
    expect(events.filter(event => event.type === 'warning')).toHaveLength(1);
    expect(result.diagnostics).toMatchObject({ engine: 'v2', codexCalls: 0, chunksWithoutModelCall: 1, normFixes: 1, retries: 0,
      planRequests: { FIX: 0, SUGGEST: 0, REVIEW: 0 } });
  });
});

describe('SejongEngine with the writer', () => {
  it('sends the plan prompt with the v2 schema and settings, and delivers the accepted decision', async () => {
    const python = new FakePython({ checks: [contract.checks.accept], decided: ['결정 1\n'] });
    const writer = new StubWriter([reply([{ id: 'R1', text: '왜냐하면 일정이 바뀌었기 때문입니다.' }], ['주의'])]);
    const settings = { model: 'gpt-6-sol', effort: 'high' };
    const { result, output } = await run(python, writer, { settings });
    expect(writer.calls).toEqual([{ schemaPath: '/schema/response-schema.json', outputPath: expect.stringMatching(/writer-1-attempt-1\.json$/u), settings }]);
    expect(writer.prompts[0]).toContain('"id":"R1"');
    expect(writer.prompts[0]).toContain('[열린 검토]');
    expect(JSON.parse(python.checks[0]!.reply)).toEqual(JSON.parse(reply([{ id: 'R1', text: '왜냐하면 일정이 바뀌었기 때문입니다.' }], ['주의'])));
    expect(output).toBe('결정 1\n');
    expect(codes(result.warnings)).toEqual(['MODEL_WARNING']);
    expect(result.diagnostics).toMatchObject({
      engine: 'v2', model: 'gpt-6-sol', reasoningEffort: 'high', codexCalls: 1, retries: 0, sentenceRetries: 0,
      requestStatus: { FIXED: 1, UNTOUCHED: 0, STILL_PRESENT: 0, LOST: 0, DECLINED: 0 }, planRequests: { FIX: 1, SUGGEST: 0, REVIEW: 0 },
      gateCodes: ['GATE_OK', 'GATE_OK'], hardFailureCounts: {}, shadowFailureCounts: {}, normFixes: 1, restoreMs: 0
    });
    // The final gate compares the prepared source with the delivered text.
    expect(python.gates).toEqual([[contract.source, '결정 1\n']]);
  });

  it('retries once with only the failed requests and their named violations, on top of the attempt-1 decision', async () => {
    const python = new FakePython({ checks: [contract.checks.retry, contract.checks.attempt2], decided: ['결정 1\n', '결정 2\n'] });
    const writer = new StubWriter([
      reply([{ id: 'R1', text: '왜냐하면 일정이 바뀌었어요.' }, { id: 'S1', text: '오늘은 세미나 후기를 정리해요.' }]),
      reply([{ id: 'R1', text: '왜냐하면 일정이 바뀌었기 때문입니다.' }])
    ]);
    const { result, output } = await run(python, writer);
    expect(writer.prompts).toHaveLength(2);
    const retry = writer.prompts[1]!;
    expect(retry).toContain('[재시도]');
    expect(retry).toContain('S1 이전 답: 말투가 합쇼체에서 해요체로 바뀌었다(voice_level).');
    expect(retry).toContain('R1 이전 답: 말투가 합쇼체에서 해요체로 바뀌었다(voice_level).');
    expect([...retry.matchAll(/"id":"([RS][0-9]+)"/gu)].map(match => match[1])).toEqual(['S1', 'R1']);
    expect(retry).not.toContain('[열린 검토]');
    expect(retry).not.toContain('[문서 말투 참고]');
    expect(retry).not.toContain('guides');
    expect(retry).not.toContain('quick_rules');
    for (const line of quickRules.split('\n').filter(text => text.trim().length > 30)) expect(retry).not.toContain(line.trim());
    expect(python.checks.map(call => [call.attempt, path.basename(call.base ?? '')])).toEqual([[1, ''], [2, 'decided-1-attempt-1.txt']]);
    expect(output).toBe('결정 2\n');
    expect(codes(result.warnings)).toEqual(['CHUNK_RETRY']);
    expect(result.diagnostics).toMatchObject({ codexCalls: 2, retries: 1, sentenceRetries: 2, gateCodes: ['GATE_WARN', 'GATE_OK', 'GATE_OK'],
      requestStatus: { FIXED: 1 }, planRequests: { REVIEW: 1 } });
  });

  it('drops an attempt-2 replacement off the retry list before the check step sees it', async () => {
    const python = new FakePython({ checks: [contract.checks.retry, contract.checks.attempt2] });
    const writer = new StubWriter([EMPTY, reply([{ id: 'R1', text: '왜냐하면 일정이 바뀌었기 때문입니다.' }, { id: 'S3', text: '다른 문장.' }])]);
    await run(python, writer);
    expect(JSON.parse(python.checks[1]!.reply).replacements.map((item: { id: string }) => item.id)).toEqual(['R1']);
  });

  it('rolls the chunk back to base(x), the decided text of a rollback, when attempt 2 ends in rollback', async () => {
    const base = '원문에 확실한 맞춤법 수정만 더한 글\n';
    const python = new FakePython({ checks: [contract.checks.retry, contract.checks.rollback], decided: ['decided 1\n', base] });
    const writer = new StubWriter([EMPTY, EMPTY]);
    const { result, output, workspace } = await run(python, writer);
    expect(output).toBe(base);
    expect(await readFile(workspace.path('02_chunk_01_rewritten.txt'), 'utf8')).toBe(base);
    expect(codes(result.warnings)).toEqual(['CHUNK_RETRY', 'CHUNK_ROLLED_BACK']);
    expect(result.diagnostics).toMatchObject({ rolledBackChunks: 1, gateCodes: ['GATE_WARN', 'GATE_ABORT', 'GATE_OK'] });
  });

  it('accepts with a warning at attempt 2 and reports reverted sentences by family, codes and counts only', async () => {
    const warned = clone(contract.checks.attempt2);
    Object.assign(warned, { gate: { exit_code: 1 }, policy: 'accept-with-warning', shadowFailures: ['clarity_longer_sentence'] });
    warned.counts = { ...warned.counts, revertedSentences: 3, revertedByFamily: { voice: 1, meaning: 1 }, collateralReverts: 1,
      restoredSentences: 1, voiceGrafts: 2, cmcRestored: 1, removedCommas: 1, repairedParticles: 1 };
    const python = new FakePython({ checks: [contract.checks.retry, warned] });
    const { result } = await run(python, new StubWriter([EMPTY, EMPTY]));
    expect(result.warnings.filter(warning => warning.code !== 'CHUNK_RETRY')).toEqual([
      { code: 'CHUNK_WARNING_ACCEPTED', message: '1번 구간에 검토 권고가 있습니다.' },
      { code: 'SEJONG_SENTENCES_REVERTED', message: '1번 구간에서 검증을 통과하지 못한 문장 3개를 원래 문장으로 되돌렸습니다(말투 1, 의미 1, 요청 밖 수정 1).' }
    ]);
    expect(result.diagnostics).toMatchObject({
      revertedSentences: { voice: 1, meaning: 1 }, collateralReverts: 1, restoredSentences: 1, voiceGrafts: 2, cmcRestored: 1,
      removedCommas: 1, repairedParticles: 1, shadowFailureCounts: { clarity_longer_sentence: 1 }
    });
  });

  it('hands an unusable reply to the check step as an unusable marker and warns once', async () => {
    const python = new FakePython({ checks: [contract.checks.retry, contract.checks.attempt2] });
    const writer = new StubWriter(['not json', reply([{ id: 'R1', text: '왜냐하면 일정이 바뀌었기 때문입니다.' }])]);
    const { result } = await run(python, writer);
    expect(python.checks[0]!.reply).toBe('{"unusable":true}');
    expect(codes(result.warnings)).toEqual(['MODEL_OUTPUT_UNUSABLE', 'CHUNK_RETRY']);
    expect(result.diagnostics.unusableModelOutputs).toBe(1);
  });

  it('fails the job when every writer reply was unusable', async () => {
    const python = new FakePython({ checks: [contract.checks.retry, contract.checks.rollback] });
    await expect(run(python, new StubWriter(['x', 'y']))).rejects.toMatchObject({ publicCode: 'ENGINE_OUTPUT_INVALID' });
  });
});

describe('SejongEngine engine version and document gate', () => {
  it('fails the job when the engine version changes mid-job', async () => {
    const python = new FakePython({ checks: [contract.checks.accept] });
    await expect(run(python, new StubWriter([EMPTY]), { versions: [VERSION, { ...VERSION, version: '2.0.1' }] }))
      .rejects.toMatchObject({ publicCode: 'ENGINE_UNAVAILABLE', message: 'Super Sejong engine version changed during the job' });
    const stale = new FakePython({ checks: [] });
    stale.plan = { ...clone(contract.plan), engine: { id: 'super-sejong', version: '1.9.9' } };
    await expect(run(stale, new StubWriter([]))).rejects.toMatchObject({ publicCode: 'ENGINE_UNAVAILABLE' });
  });

  it('puts the source back when the document gate still finds a floor failure', async () => {
    const python = new FakePython({ checks: [contract.checks.accept], decided: ['바뀐 결과 4명\n'],
      gates: [okGate(2, ['number_injected']), okGate()] });
    const { result, output } = await run(python, new StubWriter([EMPTY]));
    expect(output).toBe(contract.source);
    expect(codes(result.warnings)).toEqual(['DIRECT_TEXT_DOCUMENT_ROLLED_BACK']);
    expect(result.diagnostics).toMatchObject({ fullSourceRollbacks: 1, hardFailureCounts: { number_injected: 1 },
      gateCodes: ['GATE_OK', 'GATE_ABORT', 'GATE_OK'] });
  });

  it('keeps the delivered text and recommends review when the document gate finds a non-floor code', async () => {
    const python = new FakePython({ checks: [contract.checks.accept], decided: ['결정\n'], gates: [okGate(2, ['polarity_changed'])] });
    const { result, output } = await run(python, new StubWriter([EMPTY]));
    expect(output).toBe('결정\n');
    expect(codes(result.warnings)).toEqual(['DOCUMENT_REVIEW_RECOMMENDED']);
    expect(result.diagnostics.hardFailureCounts).toEqual({ polarity_changed: 1 });
  });

  it('reports finalize rollbacks and fails on a gate execution error', async () => {
    const rolled = new FakePython({ checks: [contract.checks.accept],
      finalize: { warningCodes: ['CHUNK_ROLLED_BACK', 'DIRECT_TEXT_DOCUMENT_ROLLED_BACK'], rolledBackChunks: [1], documentRolledBack: true, seamReverts: 2 } });
    const { result } = await run(rolled, new StubWriter([EMPTY]));
    expect(codes(result.warnings)).toEqual(['CHUNK_ROLLED_BACK', 'DIRECT_TEXT_DOCUMENT_ROLLED_BACK']);
    expect(result.diagnostics).toMatchObject({ rolledBackChunks: 1, fullSourceRollbacks: 1, revertedSentences: { flow: 2 } });
    const broken = new FakePython({ checks: [contract.checks.accept], gates: [okGate(3)] });
    await expect(run(broken, new StubWriter([EMPTY]))).rejects.toMatchObject({ publicCode: 'VALIDATION_FAILED' });
  });
});

/** Every command fails: preflight reports unavailable, and nothing is spawned for real. */
class NothingRuns implements CommandRunner {
  readonly calls: CommandRequest[] = [];
  async run(request: CommandRequest): Promise<CommandResult> {
    this.calls.push(request);
    return { exitCode: 1, stdout: '', stderr: '', termination: 'exit' };
  }
}

describe('engine switch (SUPER_SEJONG_ENGINE)', () => {
  const runtime = async (env: NodeJS.ProcessEnv) => {
    const config = { ...loadConfig(env, root), codexCommand: '/nonexistent/codex', claudeCommand: '/nonexistent/claude', runtimeRoot: outer };
    return createProductionRuntime(config, new NothingRuns());
  };

  it.each([[{}], [{ SUPER_SEJONG_ENGINE: 'legacy' }], [{ SUPER_SEJONG_ENGINE: 'v3' }], [{ SUPER_SEJONG_ENGINE: '' }]])(
    'keeps the legacy engine for %j', async env => {
      const created = await runtime(env);
      expect(created.engine).toBeInstanceOf(HumanizeEngine);
      expect(created.claudeEngine).toBeInstanceOf(HumanizeEngine);
      expect(created.preflight.engineId).toBeUndefined();
    });

  it.each([['v2'], [' V2 ']])('selects SejongEngine for both writers with %j', async value => {
    const config = loadConfig({ SUPER_SEJONG_ENGINE: value }, root);
    expect([config.engine, config.engineRoot]).toEqual(['v2', path.join(root, 'engine_runtime', 'sejong')]);
    const created = await runtime({ SUPER_SEJONG_ENGINE: value });
    expect(created.engine).toBeInstanceOf(SejongEngine);
    expect(created.claudeEngine).toBeInstanceOf(SejongEngine);
  });
});
