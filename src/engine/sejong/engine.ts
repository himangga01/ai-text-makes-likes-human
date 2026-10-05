/** Super Sejong Engine v2 orchestration (DESIGN.md 3.0, 3.5, 3.9, 4.3, 5.2): the v2 counterpart of
 * HumanizeEngine, selected by SUPER_SEJONG_ENGINE=v2 (src/runtime/create-runtime.ts). Same contract:
 * transform(request): Promise<HumanizeResult>, the same progress and warning events, the same diagnostics
 * shape plus the optional v2 fields (codes and counts only, never text).
 *
 * Per job:
 *   prepare --analyse      manifest v1 + one plan per body chunk (python-adapter.ts)
 *   per body chunk         plan.needsModel false → no writer call: check with an empty reply, which yields
 *                          base(x) = the source plus the deterministic fixes (SEJONG_NO_EDIT_NEEDED);
 *                          otherwise prompt (prompt.ts) → writer.runPrompt with response-schema.json →
 *                          reply parsed (response.ts) → check attempt 1; on policy `retry` one targeted retry
 *                          with only the failed requests and their named violations → check attempt 2 with
 *                          --base. The decided text goes to 02_chunk_NN_rewritten.txt (on rollback it is base(x):
 *                          the source plus the deterministic fixes, which verify clean by construction).
 *   finalize               reassembly, document floor and seam reverts (a residual floor failure puts the
 *                          whole document back to the source: DIRECT_TEXT_DOCUMENT_ROLLED_BACK)
 *   final verify gate      legacy gate JSON on the whole document; exit 3 fails the job (VALIDATION_FAILED)
 *
 * Python decides every sentence; this class never edits text itself. A reply this side cannot use is still
 * handed to the check step (as an object that fails the response schema) so Python's decision table, not a
 * second one here, decides what an unusable reply costs. The engine version is read when the job starts and
 * must not change while it runs (every plan carries it, and it is read again before reassembly), the
 * "version file + preflight + mid-job check" pattern of DESIGN 4.1 (version.ts, WP-14).
 */
import { randomUUID } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { performance } from 'node:perf_hooks';
import { runChunkPool } from '../chunk-pool.js';
import type { ChunkTiming, GateCode, TransformDiagnostics } from '../diagnostics.js';
import { EngineError } from '../errors.js';
import type { HumanizeRequest, HumanizeResult, HumanizeWarning } from '../humanize-engine.js';
import { HUMANIZE_MODEL, HUMANIZE_REASONING_EFFORT, type ModelSettings } from '../model-policy.js';
import type { ChunkEntry, GateResult } from '../python-engine.js';
import { parseRewriteOptions, type RewriteOptions } from '../rewrite-policy.js';
import { sejongFlags } from './config.js';
import { buildSejongPrompt, seamContextFrom } from './prompt.js';
import { gateResultOf, type SejongManifest, type SejongPython } from './python-adapter.js';
import { readSejongReply } from './response.js';
import { REQUEST_OUTCOMES, type CheckReport, type Plan, type SejongFamily, type SejongGenre } from './types.js';
import { readEngineVersion, type EngineVersion } from './version.js';

/** The writer CLI (CodexRunner or ClaudeRunner): one prompt in, the raw final message out. */
export interface SejongWriter {
  runPrompt(prompt: string, schemaPath: string, outputPath: string, signal: AbortSignal, settings?: ModelSettings): Promise<string>;
}

/** The adapter calls SejongEngine makes (SejongPython, or a fake in tests). */
export type SejongPythonPort = Pick<SejongPython,
  'packageRoot' | 'prepare' | 'readPlan' | 'check' | 'verifyDocument' | 'finalize' | 'readFinalizeReport'>;

export interface SejongEngineOptions {
  python: SejongPythonPort;
  writer: SejongWriter;
  /** src/engine/sejong/response-schema.json (passed to the writer's structured-output option). */
  schemaPath: string;
  chunkConcurrency: 1 | 2;
  model?: string;
  reasoningEffort?: string;
  now?: () => number;
  /** Environment of the v2 flags (genre default); default process.env. */
  env?: NodeJS.ProcessEnv;
  /** Reads the engine version; default readEngineVersion(python.packageRoot). */
  readVersion?: () => Promise<EngineVersion>;
}

// Python never sends this reply; it only fails the response schema, so the check step counts the attempt as
// an unusable reply (DESIGN 3.6) exactly as it would have counted the writer's own malformed text.
const UNUSABLE_REPLY = '{"unusable":true}';
const EMPTY_REPLY = '{"replacements":[],"rewrittenText":"","warnings":[]}';
// Floor codes of DESIGN 3.8: after finalize they can only mean that the document floor still fails.
const FLOOR_CODES = new Set(['empty_output', 'quote_altered', 'heading_lost', 'heading_absorbed', 'footnote_count',
  'footnote_numbers', 'footnote_def', 'footnote_anchor', 'number_injected', 'number_dropped', 'quantity_changed',
  'name_changed', 'weekday_changed', 'sentence_dropped', 'protected_span_changed', 'josa_mismatch']);
const FAMILY_KO: Record<SejongFamily, string> = {
  floor: '보존', meaning: '의미', voice: '말투', cta: '행동 요청', flow: '흐름', clarity: '명료성', norms: '맞춤법',
  runaway: '변경량', nli: '함의'
};
const DOCUMENT_ROLLBACK = 'DIRECT_TEXT_DOCUMENT_ROLLED_BACK';
const CHUNK_ROLLBACK = 'CHUNK_ROLLED_BACK';

interface ChunkContext {
  plan: Plan;
  /** The plan file named by manifest.sejong.plans (relative to the workspace). */
  planFile: string;
  settings?: ModelSettings;
  workspace: HumanizeRequest['workspace'];
  documentText: string;
  signal: AbortSignal;
  onWorkUnit(phase: 'transform' | 'verify'): void;
  onWarning(warning: HumanizeWarning): void;
  trackModelCall<T>(task: () => Promise<T>): Promise<T>;
}

interface ChunkResult {
  chunkIndex: number;
  warnings: HumanizeWarning[];
  writerCalls: number;
  retries: number;
  unusableModelOutputs: number;
  rolledBack: boolean;
  modelCallNeeded: boolean;
  hardFailures: Record<string, number>;
  shadowFailures: Record<string, number>;
  gateCodes: GateCode[];
  /** Final check report: request outcomes, reverts and deterministic fixes. */
  final: CheckReport;
  /** Repairs summed over both attempts (an attempt reports only the sentences it edited). */
  repairs: { voiceGrafts: number; cmcRestored: number; repairedParticles: number; removedCommas: number };
  sentenceRetries: number;
  nominations: number;
  timings: ChunkTiming;
}

function cancelled(): EngineError {
  return new EngineError('CLIENT_ABORTED', true, 'Transformation was cancelled');
}

function countCodes(target: Record<string, number>, codes: readonly string[] | undefined): void {
  for (const code of codes ?? []) target[code] = (target[code] ?? 0) + 1;
}

function mergeCounts(results: ReadonlyArray<Record<string, number>>): Record<string, number> {
  const merged: Record<string, number> = {};
  for (const counts of results) for (const [code, count] of Object.entries(counts)) merged[code] = (merged[code] ?? 0) + count;
  return merged;
}

function sum<T>(items: readonly T[], value: (item: T) => number): number {
  return items.reduce((total, item) => total + value(item), 0);
}

function codePointLength(value: string): number {
  return Array.from(value).length;
}

/** Sentences of an attempt-1 report that are open-review nominations (request id = sentence id). */
function nominationsOf(report: CheckReport): number {
  return report.sentences.filter(sentence => sentence.request !== null && sentence.request === sentence.id).length;
}

/** Why a chunk was rolled back, from the gate's hard codes (the warning used to say 의미 보존 for every reason). */
export function rollbackReason(hardFailures: readonly string[]): string {
  if (hardFailures.includes('model_output_unusable')) return '모델 응답을 쓸 수 없어';
  if (hardFailures.includes('change_rate_runaway')) return '바뀐 양이 너무 많아';
  return '내용 보존을 확인하지 못해';
}

function revertedMessage(report: CheckReport): string {
  const families = Object.entries(report.counts.revertedByFamily)
    .filter(([, count]) => (count ?? 0) > 0)
    .map(([family, count]) => `${FAMILY_KO[family as SejongFamily] ?? family} ${count}`);
  const counts = report.counts;
  const collateral = counts.collateralReverts > 0 ? [`요청 밖 수정 ${counts.collateralReverts}`] : [];
  // Rejected replacements (a line break, an open-review nomination over the limit, …) carry no family.
  const familyTotal = Object.values(counts.revertedByFamily).reduce((total, count) => total + (count ?? 0), 0);
  const other = counts.revertedSentences - familyTotal - counts.collateralReverts;
  const parts = [...families, ...collateral, ...(other > 0 ? [`형식 ${other}`] : [])];
  return parts.length ? `(${parts.join(', ')})` : '';
}

export class SejongEngine {
  private readonly python: SejongPythonPort;
  private readonly writer: SejongWriter;
  private readonly schemaPath: string;
  private readonly chunkConcurrency: 1 | 2;
  private readonly model: string;
  private readonly reasoningEffort: string;
  private readonly now: () => number;
  private readonly env: NodeJS.ProcessEnv;
  private readonly readVersion: () => Promise<EngineVersion>;

  constructor(options: SejongEngineOptions) {
    this.python = options.python;
    this.writer = options.writer;
    this.schemaPath = options.schemaPath;
    this.chunkConcurrency = options.chunkConcurrency;
    this.model = options.model ?? HUMANIZE_MODEL;
    this.reasoningEffort = options.reasoningEffort ?? HUMANIZE_REASONING_EFFORT;
    this.now = options.now ?? (() => performance.now());
    this.env = options.env ?? process.env;
    this.readVersion = options.readVersion ?? (() => readEngineVersion(this.python.packageRoot));
  }

  private ensureActive(signal: AbortSignal): void {
    if (signal.aborted) throw cancelled();
  }

  private emitWarning(request: HumanizeRequest, warnings: HumanizeWarning[], warning: HumanizeWarning): void {
    warnings.push(warning);
    request.onEvent({ type: 'warning', ...warning });
  }

  /** The version every step of this job must report; a packaging error is ENGINE_UNAVAILABLE, as in preflight. */
  private async engineVersion(): Promise<EngineVersion> {
    try {
      return await this.readVersion();
    } catch (error) {
      throw new EngineError('ENGINE_UNAVAILABLE', false, 'Super Sejong engine version file is unreadable', { cause: error });
    }
  }

  private async processChunk(chunk: ChunkEntry, context: ChunkContext): Promise<ChunkResult> {
    this.ensureActive(context.signal);
    const { plan, workspace } = context;
    const index = chunk.index;
    const warnings: HumanizeWarning[] = [];
    const record = (warning: HumanizeWarning): void => {
      warnings.push(warning);
      context.onWarning(warning);
    };
    const sourcePath = workspace.path(chunk.inputFile!);
    const rewrittenPath = workspace.path(chunk.rewrittenFile!);
    const planPath = workspace.path(context.planFile);
    const source = await readFile(sourcePath, 'utf8');
    const gateCodes: GateCode[] = [];
    const hardFailures: Record<string, number> = {}, shadowFailures: Record<string, number> = {};
    const repairs = { voiceGrafts: 0, cmcRestored: 0, repairedParticles: 0, removedCommas: 0 };
    let writerCalls = 0, retries = 0, unusableModelOutputs = 0, writerMs = 0, checkMs = 0;

    const check = async (attempt: 1 | 2, reply: string, base?: string): Promise<CheckReport> => {
      const replyPath = workspace.path(`reply-${index}-attempt-${attempt}.json`);
      await writeFile(replyPath, reply, 'utf8');
      const startedAt = this.now();
      try {
        const report = await this.python.check({
          plan: planPath, source: sourcePath, response: replyPath, attempt,
          ...(base !== undefined ? { base } : {}),
          out: workspace.path(`decided-${index}-attempt-${attempt}.txt`),
          report: workspace.path(`check-${index}-attempt-${attempt}.json`)
        }, context.signal);
        const gate = gateResultOf(report);
        gateCodes.push(...gate.gateCodes);
        countCodes(hardFailures, gate.hardFailures);
        countCodes(shadowFailures, gate.shadowFailures);
        repairs.voiceGrafts += report.counts.voiceGrafts;
        repairs.cmcRestored += report.counts.cmcRestored;
        repairs.repairedParticles += report.counts.repairedParticles;
        repairs.removedCommas += report.counts.removedCommas;
        return report;
      } finally {
        checkMs += this.now() - startedAt;
      }
    };

    // One writer call; returns the reply the check step receives (the validated reply, or an unusable marker).
    const write = async (attempt: 1 | 2, retry?: CheckReport['retry']): Promise<string> => {
      let nonce = randomUUID().replaceAll('-', '');
      while (source.includes(nonce) || context.documentText.includes(nonce)) nonce = randomUUID().replaceAll('-', '');
      const seamContext = plan.chunk.total > 1 ? seamContextFrom(plan, context.documentText) : undefined;
      const prompt = buildSejongPrompt({ plan, source, nonce, attempt, ...(retry ? { retry } : {}), ...(seamContext ? { seamContext } : {}) });
      const startedAt = this.now();
      let raw: string;
      try {
        raw = await context.trackModelCall(() => this.writer.runPrompt(
          prompt, this.schemaPath, workspace.path(`writer-${index}-attempt-${attempt}.json`), context.signal, context.settings));
      } finally {
        writerMs += this.now() - startedAt;
        writerCalls += 1;
      }
      this.ensureActive(context.signal);
      const parsed = readSejongReply(raw, plan, retry ? { retry } : {});
      if (!parsed.ok) {
        unusableModelOutputs += 1;
        record({ code: 'MODEL_OUTPUT_UNUSABLE', message: `${index}번 구간의 모델 응답 형식을 사용할 수 없습니다.` });
        return UNUSABLE_REPLY;
      }
      if (parsed.value.response.warnings.length) {
        record({ code: 'MODEL_WARNING', message: `${index}번 구간에 모델 검토 주의가 있습니다. 원문과 결과를 확인해 주세요.` });
      }
      return JSON.stringify(parsed.value.forward);
    };

    let report: CheckReport;
    let sentenceRetries = 0, nominations = 0;
    let decided = workspace.path(`decided-${index}-attempt-1.txt`);
    if (!plan.needsModel) {
      // No request and no open review: nothing for a writer to do (DESIGN 3.4 step 4, G6).
      report = await check(1, EMPTY_REPLY);
      context.onWorkUnit('transform');
      const fixes = report.counts.normFixes;
      record({
        code: 'SEJONG_NO_EDIT_NEEDED',
        message: `${index}번 구간에서 고칠 문장을 찾지 못해 모델을 호출하지 않았습니다.` +
          (fixes > 0 ? ` 확실한 맞춤법 오류 ${fixes}곳만 자동으로 고쳤습니다.` : '')
      });
    } else {
      report = await check(1, await write(1));
      context.onWorkUnit('transform');
      nominations = nominationsOf(report);
      if (report.policy === 'retry') {
        retries += 1;
        sentenceRetries = report.retry.length;
        record({ code: 'CHUNK_RETRY', message: `${index}번 구간에서 검증에 걸린 문장만 한 번 더 다듬습니다.` });
        this.ensureActive(context.signal);
        const base = decided;
        // An unusable reply on a plan without requests leaves nothing to retry; attempt 2 then only settles
        // the gate on the attempt-1 decision, without a writer call.
        const reply = report.retry.length ? await write(2, report.retry) : EMPTY_REPLY;
        report = await check(2, reply, base);
        decided = workspace.path(`decided-${index}-attempt-2.txt`);
      }
    }
    this.ensureActive(context.signal);

    let rolledBack = false;
    if (report.policy === 'rollback') {
      rolledBack = true;
      await writeFile(rewrittenPath, await readFile(decided, 'utf8'), 'utf8');
      const fixes = report.counts.normFixes;
      record({
        code: CHUNK_ROLLBACK,
        message: `${index}번 구간은 ${rollbackReason(report.hardFailures)} 원문을 유지했습니다.` +
          (fixes > 0 ? ` 확실한 맞춤법 오류 ${fixes}곳만 고쳤습니다.` : '')
      });
    } else {
      await writeFile(rewrittenPath, await readFile(decided, 'utf8'), 'utf8');
      if (report.policy === 'accept-with-warning') {
        record({ code: 'CHUNK_WARNING_ACCEPTED', message: `${index}번 구간에 검토 권고가 있습니다.` });
      }
      if (report.counts.revertedSentences > 0) {
        record({
          code: 'SEJONG_SENTENCES_REVERTED',
          message: `${index}번 구간에서 검증을 통과하지 못한 문장 ${report.counts.revertedSentences}개를 원래 문장으로 되돌렸습니다${revertedMessage(report)}.`
        });
      }
    }
    context.onWorkUnit('verify');
    return {
      chunkIndex: index, warnings, writerCalls, retries, unusableModelOutputs, rolledBack,
      modelCallNeeded: plan.needsModel, hardFailures, shadowFailures, gateCodes, final: report, repairs,
      sentenceRetries, nominations,
      timings: { codexMs: writerMs, restoreMs: 0, gateMs: checkMs }
    };
  }

  async transform(request: HumanizeRequest): Promise<HumanizeResult> {
    // Requests without options (legacy API callers) take the most conservative route, like a text file.
    const requested = parseRewriteOptions(request.rewriteOptions?.inputKind, request.rewriteOptions?.strength);
    const rewriteOptions: RewriteOptions = requested ?? { inputKind: 'text-file', strength: 'normal' };
    const genre: SejongGenre = sejongFlags(this.env).genreDefault;
    const totalStartedAt = this.now();
    this.ensureActive(request.signal);
    const warnings: HumanizeWarning[] = [];
    const version = await this.engineVersion();
    request.onEvent({ type: 'progress', phase: 'sanitize', current: 0, total: 1, message: '원문을 안전하게 준비하는 중입니다.' });

    const manifest: SejongManifest = await this.python.prepare(request.workspace.root, request.signal, {
      analyse: { inputKind: rewriteOptions.inputKind, strength: rewriteOptions.strength, genre }
    });
    this.ensureActive(request.signal);
    const sourcePath = request.workspace.path(manifest.sourceFile);
    const source = await readFile(sourcePath, 'utf8');
    const sourcePoints = Array.from(source);
    const lastChunk = manifest.chunks.at(-1);
    if (manifest.sourceChars !== sourcePoints.length || (lastChunk ? lastChunk.end : 0) !== sourcePoints.length) {
      throw new EngineError('ENGINE_OUTPUT_INVALID', false, 'Chunk manifest does not cover the prepared source text');
    }
    const bodyChunks = manifest.chunks.filter(chunk => !chunk.passthrough);
    const entries = new Map((manifest.sejong?.plans ?? []).map(entry => [entry.chunk, entry]));
    if (bodyChunks.some(chunk => !entries.has(chunk.index))) {
      throw new EngineError('ENGINE_OUTPUT_INVALID', false, 'Sejong prepare wrote no plan for a body chunk');
    }
    const plans = new Map<number, Plan>();
    for (const chunk of bodyChunks) {
      const entry = entries.get(chunk.index)!;
      const plan = await this.python.readPlan(request.workspace.path(entry.file), {
        chunkIndex: chunk.index, chunkTotal: manifest.chunkCount, ...rewriteOptions, genre
      });
      if (plan.engine.id !== version.id || plan.engine.version !== version.version) {
        throw new EngineError('ENGINE_UNAVAILABLE', false, 'Super Sejong engine version changed during the job');
      }
      if (plan.needsModel !== entry.needsModel) throw new EngineError('ENGINE_OUTPUT_INVALID', false, 'Sejong manifest and plan disagree');
      plans.set(chunk.index, plan);
    }
    const prepareMs = this.now() - totalStartedAt;
    request.onEvent({ type: 'progress', phase: 'chunk', current: 1, total: 1, message: `${manifest.bodyChunkCount}개 구간으로 준비했습니다.` });
    for (const message of manifest.warnings) this.emitWarning(request, warnings, { code: 'CHUNK_PREPARE_WARNING', message });

    const concurrency = manifest.processingMode === 'single' ? 1 : this.chunkConcurrency;
    let completedUnits = 0;
    const totalUnits = bodyChunks.length * 2;
    let activeModelCalls = 0;
    let maxObservedCodexConcurrency = 0;
    const trackModelCall = async <T>(task: () => Promise<T>): Promise<T> => {
      activeModelCalls += 1;
      maxObservedCodexConcurrency = Math.max(maxObservedCodexConcurrency, activeModelCalls);
      try {
        return await task();
      } finally {
        activeModelCalls -= 1;
      }
    };
    const results = await runChunkPool(
      bodyChunks.map((chunk, bodyIndex) => ({ chunk, bodyIndex })),
      concurrency,
      request.signal,
      async ({ chunk, bodyIndex }, signal) => {
        this.ensureActive(signal);
        return this.processChunk(chunk, {
          plan: plans.get(chunk.index)!,
          planFile: entries.get(chunk.index)!.file,
          settings: request.settings,
          workspace: request.workspace,
          documentText: source,
          signal,
          trackModelCall,
          onWarning: warning => request.onEvent({ type: 'warning', ...warning }),
          onWorkUnit: phase => {
            completedUnits += 1;
            request.onEvent({
              type: 'progress', phase, current: bodyIndex + 1, total: bodyChunks.length, completedUnits, totalUnits,
              message: phase === 'transform'
                ? `${bodyIndex + 1}/${bodyChunks.length} 구간을 다듬는 중입니다.`
                : `${bodyIndex + 1}/${bodyChunks.length} 구간을 검증하는 중입니다.`
            });
          }
        });
      }
    );
    warnings.push(...results.flatMap(result => result.warnings));
    // Every chunk asked the writer and never got a usable reply: a model failure, not a completed rewrite.
    if (results.length > 0 && results.every(result => result.writerCalls > 0 && result.unusableModelOutputs >= result.writerCalls)) {
      throw new EngineError('ENGINE_OUTPUT_INVALID', false, 'Every chunk returned unusable model output');
    }

    this.ensureActive(request.signal);
    const current = await this.engineVersion();
    if (current.id !== version.id || current.version !== version.version || current.schema !== version.schema) {
      throw new EngineError('ENGINE_UNAVAILABLE', false, 'Super Sejong engine version changed during the job');
    }
    request.onEvent({ type: 'progress', phase: 'assemble', current: 1, total: 1, message: '문단과 순서를 복원하는 중입니다.' });
    const assembleStartedAt = this.now();
    const finalPath = await this.python.finalize(request.workspace.root, request.signal);
    const finalized = await this.python.readFinalizeReport(request.workspace.root);
    const assembleFinishedAt = this.now();
    const assembleMs = assembleFinishedAt - assembleStartedAt;
    for (const chunk of finalized.rolledBackChunks) {
      this.emitWarning(request, warnings, { code: CHUNK_ROLLBACK, message: `${chunk}번 구간은 결과 길이가 원문과 너무 달라 원문을 유지했습니다.` });
    }
    let fullSourceRollbacks = 0;
    const documentRollback = (): void => {
      fullSourceRollbacks = 1;
      this.emitWarning(request, warnings, { code: DOCUMENT_ROLLBACK, message: '전체 글의 내용 보존을 확인하지 못해 원문을 유지했습니다.' });
    };
    if (finalized.documentRolledBack || finalized.warningCodes.includes(DOCUMENT_ROLLBACK)) documentRollback();

    // The document gate runs without the plans, so it cannot see a request's licence (an SSJ-A06 polarity
    // repair) and every sentence was already verified against its source with that context. Only the floor
    // decides here: a floor code that survived finalize puts the source back; anything else is a review hint.
    const gateStartedAt = this.now();
    let fullGate: GateResult = await this.python.verifyDocument(sourcePath, finalPath, request.signal);
    if (fullGate.status === 'error') throw new EngineError('VALIDATION_FAILED', false, 'Full-document validation failed');
    const gates = [fullGate];
    if (fullGate.status === 'abort' && (fullGate.hardFailures ?? []).some(code => FLOOR_CODES.has(code))) {
      await writeFile(finalPath, source, 'utf8');
      if (!fullSourceRollbacks) documentRollback();
      fullGate = await this.python.verifyDocument(sourcePath, finalPath, request.signal);
      if (fullGate.status === 'error' || fullGate.status === 'abort') {
        throw new EngineError('VALIDATION_FAILED', false, 'Full-document validation failed');
      }
      gates.push(fullGate);
    }
    if (fullGate.status === 'warn' || fullGate.status === 'abort') {
      this.emitWarning(request, warnings, { code: 'DOCUMENT_REVIEW_RECOMMENDED', message: '전체 문서에 사람 검토가 권장되는 항목이 있습니다.' });
    }
    const fullGateMs = this.now() - gateStartedAt;

    const output = await readFile(finalPath, 'utf8');
    const finals = results.map(result => result.final);
    const reverted: Record<string, number> = {};
    for (const report of finals) {
      for (const [family, count] of Object.entries(report.counts.revertedByFamily)) reverted[family] = (reverted[family] ?? 0) + (count ?? 0);
    }
    if (finalized.seamReverts > 0) reverted.flow = (reverted.flow ?? 0) + finalized.seamReverts;
    const requestStatus: Record<string, number> = Object.fromEntries(REQUEST_OUTCOMES.map(outcome => [outcome, 0]));
    for (const report of finals) {
      for (const outcome of REQUEST_OUTCOMES) requestStatus[outcome] = (requestStatus[outcome] ?? 0) + report.requestStatus[outcome];
    }
    const planRequests = { FIX: 0, SUGGEST: 0, REVIEW: sum(results, result => result.nominations) };
    for (const plan of plans.values()) for (const item of plan.requests) planRequests[item.tier] += 1;
    const gateHard: Record<string, number> = {}, gateShadow: Record<string, number> = {};
    for (const gate of gates) {
      countCodes(gateHard, gate.hardFailures);
      countCodes(gateShadow, gate.shadowFailures);
    }
    const sourceChars = sourcePoints.length;
    const diagnostics: TransformDiagnostics = {
      ...(requested ? { requestedStrength: requested.strength } : {}),
      engine: 'v2',
      rolledBackChunks: sum(results, result => (result.rolledBack ? 1 : 0)) + finalized.rolledBackChunks.length,
      unusableModelOutputs: sum(results, result => result.unusableModelOutputs),
      hardFailureCounts: mergeCounts([...results.map(result => result.hardFailures), gateHard]),
      shadowFailureCounts: mergeCounts([...results.map(result => result.shadowFailures), gateShadow]),
      repairedParticles: sum(results, result => result.repairs.repairedParticles),
      fullSourceRollbacks,
      chunksWithoutModelCall: sum(results, result => (result.modelCallNeeded ? 0 : 1)),
      planRequests,
      requestStatus,
      revertedSentences: reverted,
      collateralReverts: sum(finals, report => report.counts.collateralReverts),
      voiceGrafts: sum(results, result => result.repairs.voiceGrafts),
      cmcRestored: sum(results, result => result.repairs.cmcRestored),
      normFixes: sum(finals, report => report.counts.normFixes),
      sentenceRetries: sum(results, result => result.sentenceRetries),
      model: request.settings?.model ?? this.model,
      reasoningEffort: request.settings?.effort ?? this.reasoningEffort,
      processingMode: manifest.processingMode,
      routeHint: manifest.routeHint,
      sourceChars,
      bodyChunks: bodyChunks.length,
      codexCalls: sum(results, result => result.writerCalls),
      retries: sum(results, result => result.retries),
      restoredSentences: sum(finals, report => report.counts.restoredSentences),
      removedCommas: sum(results, result => result.repairs.removedCommas),
      gateCodes: [...results.flatMap(result => result.gateCodes), ...gates.flatMap(gate => gate.gateCodes)],
      maxObservedCodexConcurrency,
      prepareMs,
      codexMs: sum(results, result => result.timings.codexMs),
      restoreMs: 0,
      gateMs: sum(results, result => result.timings.gateMs) + fullGateMs,
      assembleMs,
      totalMs: this.now() - totalStartedAt
    };
    return {
      finalPath,
      sourceChars,
      outputChars: codePointLength(output),
      chunks: bodyChunks.length,
      warnings,
      diagnostics
    };
  }
}
