import { candidateReviewForRetry, type CandidateReview } from './candidate-review.js';
import { parseRewriteOptions, type RewriteOptions } from './rewrite-policy.js';
import { checkDirectTextFidelity, checkStructuralFidelity, restoreProtectedSentences } from './direct-text-fidelity.js';
import { collectKoreanStyleFindings, documentRegister, type ChunkPromptContext } from './super-sejong.js';
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { performance } from "node:perf_hooks";
import type { EventSink } from "../contracts.js";
import { runChunkPool } from "./chunk-pool.js";
import type { CodexResult } from "./codex-runner.js";
import type {
  ChunkTiming,
  GateCode,
  TransformDiagnostics
} from "./diagnostics.js";
import { EngineError } from "./errors.js";
import {
  HUMANIZE_MODEL,
  HUMANIZE_REASONING_EFFORT
} from "./model-policy.js";
import type {
  ChunkEntry,
  ChunkManifest,
  GateResult,
  RestoreReport
} from "./python-engine.js";
import type { JobWorkspace } from "./workspace.js";
import type { ModelSettings } from './model-policy.js';
import { sejongFlags } from './sejong/config.js';
import type { AnalyseOptions, SejongPython } from './sejong/python-adapter.js';
import type { CheckReport } from './sejong/types.js';

export interface PythonAdapter {
  prepare(runDir: string, signal: AbortSignal): Promise<ChunkManifest>;
  restore(
    beforePath: string,
    afterPath: string,
    signal: AbortSignal
  ): Promise<RestoreReport>;
  verify(
    beforePath: string,
    afterPath: string,
    signal: AbortSignal,
    attempt?: 1 | 2
  ): Promise<GateResult>;
  reassemble(runDir: string, signal: AbortSignal): Promise<string>;
}

export interface CodexAdapter {
  transform(
    inputPath: string,
    outputPath: string,
    attempt: 1 | 2,
    signal: AbortSignal,
    settings?: ModelSettings,
    rewriteOptions?: RewriteOptions,
    candidateReview?: CandidateReview,
    chunkContext?: ChunkPromptContext
  ): Promise<CodexResult>;
}

export interface HumanizeRequest {
  rewriteOptions?: RewriteOptions;
  settings?: ModelSettings;
  jobId: string;
  workspace: JobWorkspace;
  signal: AbortSignal;
  onEvent: EventSink;
}

export interface HumanizeWarning {
  code: string;
  message: string;
}

export interface HumanizeResult {
  finalPath: string;
  sourceChars: number;
  outputChars: number;
  chunks: number;
  warnings: HumanizeWarning[];
  diagnostics: TransformDiagnostics;
}

export interface HumanizeEngineOptions {
  python: PythonAdapter;
  codex: CodexAdapter;
  chunkConcurrency: 1 | 2;
  model?: string;
  reasoningEffort?: string;
  now?: () => number;
  /** Super Sejong v2 CLI for the legacy shadow hook; only used when SUPER_SEJONG_V2_SHADOW=1. */
  v2Shadow?: V2ShadowAdapter;
  /** Environment the shadow flags are read from per job. Default process.env. */
  env?: NodeJS.ProcessEnv;
  /** Timeout of one shadow step in ms (default 10 s); the job waits at most 1.5 times this after the legacy decision. */
  v2ShadowTimeoutMs?: number;
}

interface ChunkTaskContext {
  rewriteOptions?: RewriteOptions;
  settings?: ModelSettings;
  sourcePoints: readonly string[];
  workspace: JobWorkspace;
  signal: AbortSignal;
  onWorkUnit(phase: "transform" | "verify"): void;
  onWarning(warning: HumanizeWarning): void;
  trackModelCall<T>(task: () => Promise<T>): Promise<T>;
  chunkContext?: ChunkPromptContext;
}

function countCodes(target: Record<string, number>, codes: readonly string[] | undefined): void {
  for (const code of codes ?? []) target[code] = (target[code] ?? 0) + 1;
}

function codeCounts(codes: readonly string[] | undefined): Record<string, number> {
  const counts: Record<string, number> = {};
  countCodes(counts, codes);
  return counts;
}

function mergeCounts(results: ReadonlyArray<Record<string, number>>): Record<string, number> {
  const merged: Record<string, number> = {};
  for (const counts of results) for (const [code, count] of Object.entries(counts)) merged[code] = (merged[code] ?? 0) + count;
  return merged;
}

export interface ChunkTaskResult {
  chunkIndex: number;
  warnings: HumanizeWarning[];
  codexCalls: number;
  retries: number;
  restoredSentences: number;
  removedCommas: number;
  repairedParticles: number;
  skippedSentences: number;
  fidelityGuardFailures: number;
  rolledBackChunks: number;
  protectedSentences: number;
  restoredProtectedSentences: number;
  candidateReviewRetries: number;
  /** Attempts whose reply was malformed or ambiguous (0–2). */
  unusableModelOutputs: number;
  hardFailures: Record<string, number>;
  shadowFailures: Record<string, number>;
  styleBefore: number;
  styleAfter: number;
  gateCodes: GateCode[];
  timings: ChunkTiming;
}

function cancelled(): EngineError {
  return new EngineError(
    "CLIENT_ABORTED",
    true,
    "Transformation was cancelled"
  );
}

function validation(message: string): EngineError {
  return new EngineError("VALIDATION_FAILED", false, message);
}

function codePointLength(value: string): number {
  return Array.from(value).length;
}

// Python str.strip() whitespace: reassemble_chunks.py re-attaches the source
// chunk's outer whitespace, so every pre-assembly check must see the same shape.
const pythonWhitespace = String.fromCodePoint(
  0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680,
  0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a,
  0x2028, 0x2029, 0x202f, 0x205f, 0x3000
);
const leadingWhitespace = new RegExp(`^[${pythonWhitespace}]*`, "u");
const trailingWhitespace = new RegExp(`[${pythonWhitespace}]*$`, "u");

function alignOuterWhitespace(source: string, output: string): string {
  const leading = source.match(leadingWhitespace)![0];
  if (leading.length === source.length) return output;
  const core = output.replace(leadingWhitespace, "").replace(trailingWhitespace, "");
  return core ? leading + core + source.match(trailingWhitespace)![0] : output;
}

// Only a malformed or ambiguous reply from a successful run is the model's fault
// for this chunk. Timeouts and CLI failures (login, usage limit, network) fail the job.
function unusableModelOutput(error: unknown): boolean {
  return error instanceof EngineError && error.publicCode === "ENGINE_OUTPUT_INVALID";
}

/* ---------- Super Sejong v2 shadow hook (DESIGN 5.4 SUPER_SEJONG_V2_SHADOW, rollout S3) ----------
 * With SUPER_SEJONG_V2_SHADOW=1 and the legacy engine selected, v2 looks at the same job on the side and
 * never calls a model: `prepare --analyse` on the prepared source, then `check --candidate` (attempt 1) per
 * v2 chunk with the text legacy delivered. The result is diagnostics.v2ShadowCounts: fixed keys and integer
 * counts, never text (every key part is checked against SHADOW_KEY_PART, so no document text can become a key).
 * It cannot change the legacy result: it only reads the delivered text, works in its own directory inside the
 * job workspace, and every failure, timeout or abort is swallowed into a count. The analyse step needs only the
 * source, so it overlaps with the legacy model call; the check steps start when the delivered text is final
 * (right after reassembly, while the legacy full-document gate runs) and the job waits for them at the end.
 *
 * Keys (a count of 0 is not recorded, so an absent key reads as 0; the three ms_ timings are always present when measured):
 *   shadow_ok | shadow_failed        every step ran / some step failed (see failed_*, timeout_*, aborted_*)
 *   failed_<step> timeout_<step> aborted_<step>     step = prepare | plan | check
 *   chunks chunks_need_model chunks_no_model chunks_open_review chunks_checked chunks_unaligned
 *   plan_sentences deterministic_fixes cta_units sanitize_differs
 *   requests_<fix|suggest|review>      requests v2 would have sent; request_rule_<rule> per rule
 *   findings_<fix|suggest|leave>       finding_rule_<rule> per rule
 *   gate_exit_<0|1|2>                  v2 gate result per checked chunk (0 accept, 1 retry, 2 fail)
 *   would_accept | would_retry | would_fail   whole job, only when every chunk was checked (fail > retry > accept)
 *   sentences_<unchanged|deterministic|accepted|retry|rejected|reverted>   v2 verdict on the legacy text
 *   hard_<code> soft_<code>            gate hard failures / shadow codes; sentence_code_<code>
 *   retry_code_<code> retry_family_<family> reverted_family_<family>
 *   request_status_<fixed|untouched|still_present|declined>   plan requests against the legacy text
 *   reverted_sentences collateral_reverts voice_grafts cmc_restored norm_fixes repaired_particles
 *   removed_commas restored_sentences  (the report's counts)
 *   ms_prepare ms_check ms_overhead    wall ms of the analyse step, of the check phase, and of what the job waited for the shadow
 */
export type V2ShadowAdapter = Pick<SejongPython, 'prepare' | 'check'>;

const SHADOW_DIR = 'v2-shadow';
const SHADOW_STEP_TIMEOUT_MS = 10_000;     // one Python step; the 300 ms budget is for the whole job, this only bounds a hang
const SHADOW_FINISH_FACTOR = 1.5;          // everything the job may wait for after the legacy decision, in steps
const SHADOW_CHECK_CONCURRENCY = 2;
const SHADOW_MAX_KEYS = 200;
const SHADOW_MAX_PLAN_BYTES = 16 * 1024 * 1024;
const SHADOW_KEY_PART = /^[A-Za-z0-9_.-]{1,64}$/;

type ShadowStep = 'prepare' | 'plan' | 'check';

class ShadowCounts {
  readonly values: Record<string, number> = {};
  private size = 0;

  /** A count; 0 is not recorded, so an absent key reads as 0. */
  add(key: string, by = 1): void {
    if (!Number.isFinite(by) || by <= 0) return;
    let name = key;
    if (!Object.hasOwn(this.values, name) && this.size >= SHADOW_MAX_KEYS) name = 'other_keys';
    if (!Object.hasOwn(this.values, name)) this.size += 1;
    this.values[name] = (this.values[name] ?? 0) + Math.floor(by);
  }

  /** Wall time in whole ms, kept at 0 (an absent timing would read as "not measured"); outside the key cap, there are three of them. */
  time(key: string, ms: number): void {
    this.values[key] = Math.max(0, Math.round(ms));
  }

  /** `<prefix>_<code>`; anything that is not a short identifier is counted as `<prefix>_other`. */
  code(prefix: string, raw: unknown, by = 1): void {
    const part = typeof raw === 'string' && SHADOW_KEY_PART.test(raw) ? raw.toLowerCase().replace(/[.-]/g, '_') : 'other';
    this.add(`${prefix}_${part}`, by);
  }
}

function shadowRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function shadowList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/** Sizes of one v2 plan: what v2 would have sent to the writer. Fields are read defensively; the check step validates the plan itself. */
function digestShadowPlan(counts: ShadowCounts, value: unknown): void {
  const plan = shadowRecord(value);
  if (!plan) throw new Error('plan is not an object');
  counts.add('plan_sentences', shadowList(plan.sentences).length);
  counts.add(plan.needsModel === true ? 'chunks_need_model' : 'chunks_no_model');
  if (shadowRecord(plan.openReview)?.enabled === true) counts.add('chunks_open_review');
  for (const raw of shadowList(plan.requests)) {
    const request = shadowRecord(raw);
    counts.code('requests', request?.tier);
    for (const rule of shadowList(request?.rules)) counts.code('request_rule', rule);
  }
  for (const raw of shadowList(plan.findings)) {
    const finding = shadowRecord(raw);
    counts.code('findings', finding?.tier);
    counts.code('finding_rule', finding?.rule);
  }
  counts.add('deterministic_fixes', shadowList(plan.deterministic).length);
  counts.add('cta_units', shadowList(plan.ctaLedger).length);
}

/** What v2 would have decided about the legacy text of one chunk (codes and counts of the check report only). */
function digestShadowCheck(counts: ShadowCounts, report: CheckReport): void {
  counts.add('chunks_checked');
  counts.add(`gate_exit_${report.gate.exit_code}`);
  for (const code of report.hardFailures) counts.code('hard', code);
  for (const code of report.shadowFailures) counts.code('soft', code);
  for (const sentence of report.sentences) {
    counts.code('sentences', sentence.status);
    for (const code of sentence.codes) counts.code('sentence_code', code);
  }
  for (const item of report.retry) {
    for (const violation of item.violations) {
      counts.code('retry_code', violation.code);
      if (violation.family) counts.code('retry_family', violation.family);
    }
  }
  for (const [family, count] of Object.entries(report.counts.revertedByFamily)) counts.code('reverted_family', family, count);
  for (const [status, count] of Object.entries(report.requestStatus)) counts.code('request_status', status, count);
  counts.add('reverted_sentences', report.counts.revertedSentences);
  counts.add('collateral_reverts', report.counts.collateralReverts);
  counts.add('voice_grafts', report.counts.voiceGrafts);
  counts.add('cmc_restored', report.counts.cmcRestored);
  counts.add('norm_fixes', report.counts.normFixes);
  counts.add('repaired_particles', report.counts.repairedParticles);
  counts.add('removed_commas', report.counts.removedCommas);
  counts.add('restored_sentences', report.counts.restoredSentences);
}

/** The legacy text that belongs to each v2 body chunk. One chunk covering the document takes the whole text.
 * Otherwise the chunks start and end on line boundaries (v2 cuts between paragraphs), and the legacy text
 * is cut by line numbers: that needs the same line count and the same blank-line positions as the source,
 * which legacy keeps when it keeps paragraphs. A chunk that cannot be assigned is left out (counted as unaligned). */
export function shadowCandidates(prepared: string, output: string, chunks: readonly ChunkEntry[]): Map<number, string> {
  const found = new Map<number, string>();
  const body = chunks.filter(chunk => !chunk.passthrough);
  if (chunks.length === 1 && body.length === 1) return found.set(body[0]!.index, output);
  const points = Array.from(prepared);
  if (chunks[0]?.start !== 0 || chunks.at(-1)?.end !== points.length) return found;
  const sourceLines = prepared.split('\n'), outputLines = output.split('\n');
  if (sourceLines.length !== outputLines.length) return found;
  if (sourceLines.some((line, index) => (line.trim() === '') !== (outputLines[index]!.trim() === ''))) return found;
  let before = 0;
  for (const chunk of chunks) {
    const text = points.slice(chunk.start, chunk.end);
    const lines = text.reduce((total, point) => total + (point === '\n' ? 1 : 0), 0);
    const endsWithNewline = text.at(-1) === '\n';
    const onLines = (chunk.start === 0 || points[chunk.start - 1] === '\n') && (chunk.end === points.length || endsWithNewline);
    if (!chunk.passthrough && onLines) {
      const piece = outputLines.slice(before, before + lines + (endsWithNewline ? 0 : 1)).join('\n');
      found.set(chunk.index, endsWithNewline ? `${piece}\n` : piece);
    }
    before += lines;
  }
  return found;
}

interface ShadowPrepared {
  chunks: ChunkEntry[];
  /** The document as v2 prepared it; chunk offsets are code points into it. */
  document: string;
}

class V2ShadowRun {
  private readonly stop = new AbortController();
  private readonly counts = new ShadowCounts();
  private readonly dir: string;
  /** Aborted when the job has waited as long as it may for the shadow after the legacy decision. */
  private readonly deadline = new AbortController();
  private prepared: Promise<ShadowPrepared | undefined> = Promise.resolve(undefined);
  private checked: Promise<void> = Promise.resolve();
  private failed = false;

  constructor(
    private readonly adapter: V2ShadowAdapter,
    workspace: JobWorkspace,
    private readonly signal: AbortSignal,
    private readonly now: () => number,
    private readonly stepTimeoutMs: number
  ) {
    this.dir = workspace.path(SHADOW_DIR);
  }

  /** Starts the analyse step; it overlaps with the legacy model call and never rejects. */
  begin(source: string, options: AnalyseOptions): void {
    this.prepared = this.prepare(source, options).catch(() => {
      this.failed = true;
      return undefined;
    });
  }

  /** Stops whatever is still running (the legacy job ended or failed). */
  dispose(): void {
    this.stop.abort();
  }

  /** Starts checking the delivered text; never rejects and never runs longer than the finish budget. */
  check(output: string): void {
    const budget = setTimeout(() => this.deadline.abort(), Math.round(this.stepTimeoutMs * SHADOW_FINISH_FACTOR));
    this.checked = (async () => {
      try {
        const prepared = await this.prepared;
        if (prepared) await this.checkAll(prepared, output);
      } catch {
        this.fail('check', undefined, undefined);
      } finally {
        clearTimeout(budget);
      }
    })();
  }

  /** Waits for the check and returns the counts; ms_overhead is the time this wait took. Never throws. */
  async collect(): Promise<Record<string, number>> {
    const waitedFrom = this.now();
    await this.checked;
    this.counts.add(this.failed ? 'shadow_failed' : 'shadow_ok');
    this.counts.time('ms_overhead', this.now() - waitedFrom);
    return { ...this.counts.values };
  }

  private fail(step: ShadowStep, error: unknown, timer: AbortSignal | undefined): void {
    this.failed = true;
    const code = error instanceof EngineError ? error.publicCode : undefined;
    const timedOut = timer?.aborted === true || this.deadline.signal.aborted || code === 'ENGINE_TIMEOUT';
    const aborted = this.signal.aborted || this.stop.signal.aborted || code === 'CLIENT_ABORTED';
    this.counts.add(`${timedOut ? 'timeout' : aborted ? 'aborted' : 'failed'}_${step}`);
  }

  /** Runs one step under the step timeout, the finish deadline and the job's own signals. The step is also
   * raced against them, so an adapter that ignores its signal cannot hold the job. */
  private async step<T>(step: ShadowStep, task: (signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
    const timer = AbortSignal.timeout(this.stepTimeoutMs);
    const signal = AbortSignal.any([this.signal, this.stop.signal, this.deadline.signal, timer]);
    let onAbort: (() => void) | undefined;
    const stopped = new Promise<never>((_resolve, reject) => {
      onAbort = () => reject(new EngineError(timer.aborted || this.deadline.signal.aborted ? 'ENGINE_TIMEOUT' : 'CLIENT_ABORTED', true, 'Shadow step stopped'));
      if (signal.aborted) onAbort();
      else signal.addEventListener('abort', onAbort, { once: true });
    });
    try {
      return await Promise.race([task(signal), stopped]);
    } catch (error) {
      this.fail(step, error, timer);
      return undefined;
    } finally {
      if (onAbort) signal.removeEventListener('abort', onAbort);
      stopped.catch(() => undefined);
    }
  }

  private async readPlan(file: string): Promise<unknown> {
    if ((await stat(file)).size > SHADOW_MAX_PLAN_BYTES) throw new Error('plan is too large');
    return JSON.parse(await readFile(file, 'utf8'));
  }

  private async prepare(source: string, options: AnalyseOptions): Promise<ShadowPrepared | undefined> {
    const startedAt = this.now();
    const prepared = await this.step('prepare', async signal => {
      await mkdir(this.dir, { recursive: true });
      await writeFile(path.join(this.dir, '01_input.txt'), source, 'utf8');
      const manifest = await this.adapter.prepare(this.dir, signal, { analyse: options });
      return { manifest, document: await readFile(path.join(this.dir, manifest.sourceFile), 'utf8') };
    });
    if (!prepared) return undefined;
    const chunks = prepared.manifest.chunks;
    const body = chunks.filter(chunk => !chunk.passthrough);
    this.counts.add('chunks', body.length);
    if (prepared.document !== source) this.counts.add('sanitize_differs');
    const planned = await this.step('plan', async () => {
      for (const chunk of body) digestShadowPlan(this.counts, await this.readPlan(this.planFile(chunk)));
      return true;
    });
    this.counts.time('ms_prepare', this.now() - startedAt);
    return planned ? { chunks, document: prepared.document } : undefined;
  }

  private planFile(chunk: ChunkEntry): string {
    return path.join(this.dir, `plan-${String(chunk.index).padStart(2, '0')}.json`);
  }

  private async checkAll(prepared: ShadowPrepared, output: string): Promise<void> {
    const startedAt = this.now();
    const body = prepared.chunks.filter(chunk => !chunk.passthrough);
    const candidates = shadowCandidates(prepared.document, output, prepared.chunks);
    const exits: number[] = [];
    let next = 0;
    const worker = async (): Promise<void> => {
      while (next < body.length) {
        const chunk = body[next++]!;
        const candidate = candidates.get(chunk.index);
        if (candidate === undefined) {
          this.counts.add('chunks_unaligned');
          continue;
        }
        const label = String(chunk.index).padStart(2, '0');
        const report = await this.step('check', async signal => {
          const candidateFile = path.join(this.dir, `v2-candidate-${label}.txt`);
          await writeFile(candidateFile, candidate, 'utf8');
          return this.adapter.check({
            plan: this.planFile(chunk),
            source: path.join(this.dir, chunk.inputFile!),
            candidate: candidateFile,
            attempt: 1,
            out: path.join(this.dir, `v2-decided-${label}.txt`),
            report: path.join(this.dir, `v2-check-${label}.json`)
          }, signal);
        });
        if (!report) continue;
        digestShadowCheck(this.counts, report);
        exits.push(report.gate.exit_code);
      }
    };
    await Promise.all(Array.from({ length: Math.min(SHADOW_CHECK_CONCURRENCY, body.length) }, worker));
    this.counts.time('ms_check', this.now() - startedAt);
    if (body.length > 0 && exits.length === body.length) {
      this.counts.add(exits.some(code => code >= 2) ? 'would_fail' : exits.includes(1) ? 'would_retry' : 'would_accept');
    }
  }
}

export class HumanizeEngine {
  private readonly python: PythonAdapter;
  private readonly codex: CodexAdapter;
  private readonly chunkConcurrency: 1 | 2;
  private readonly model: string;
  private readonly reasoningEffort: string;
  private readonly now: () => number;
  private readonly v2Shadow: V2ShadowAdapter | undefined;
  private readonly env: NodeJS.ProcessEnv | undefined;
  private readonly v2ShadowTimeoutMs: number;

  constructor(options: HumanizeEngineOptions) {
    this.python = options.python;
    this.codex = options.codex;
    this.chunkConcurrency = options.chunkConcurrency;
    this.model = options.model ?? HUMANIZE_MODEL;
    this.reasoningEffort = options.reasoningEffort ?? HUMANIZE_REASONING_EFFORT;
    this.now = options.now ?? (() => performance.now());
    this.v2Shadow = options.v2Shadow;
    this.env = options.env;
    this.v2ShadowTimeoutMs = options.v2ShadowTimeoutMs ?? SHADOW_STEP_TIMEOUT_MS;
  }

  /** Starts the v2 shadow run of this job, or returns undefined when it is off (the default) or cannot start. */
  private startShadow(request: HumanizeRequest, source: string, options: RewriteOptions | undefined): V2ShadowRun | undefined {
    if (!this.v2Shadow) return undefined;
    try {
      const flags = sejongFlags(this.env ?? process.env);
      if (!flags.v2Shadow || flags.engine !== 'legacy') return undefined;
      // Its own clock: an injected `now` must see exactly the calls the legacy engine makes.
      const run = new V2ShadowRun(this.v2Shadow, request.workspace, request.signal, () => performance.now(), this.v2ShadowTimeoutMs);
      run.begin(source, { inputKind: options?.inputKind ?? 'text-file', strength: options?.strength ?? 'normal', genre: flags.genreDefault });
      return run;
    } catch {
      return undefined;
    }
  }

  private ensureActive(signal: AbortSignal): void {
    if (signal.aborted) throw cancelled();
  }

  private emitWarning(
    request: HumanizeRequest,
    warnings: HumanizeWarning[],
    warning: HumanizeWarning
  ): void {
    warnings.push(warning);
    request.onEvent({ type: "warning", ...warning });
  }

  private recordChunkWarning(
    context: ChunkTaskContext,
    warnings: HumanizeWarning[],
    warning: HumanizeWarning
  ): void {
    warnings.push(warning);
    context.onWarning(warning);
  }

  private collectModelWarnings(
    context: ChunkTaskContext,
    warnings: HumanizeWarning[],
    messages: string[],
    chunkIndex: number
  ): void {
    if (messages.length) {
      this.recordChunkWarning(context, warnings, {
        code: "MODEL_WARNING",
        message: `${chunkIndex}번 구간에 모델 검토 주의가 있습니다. 원문과 결과를 확인해 주세요.`
      });
    }
  }

  private async processChunk(
    chunk: ChunkManifest["chunks"][number],
    context: ChunkTaskContext
  ): Promise<ChunkTaskResult> {
    this.ensureActive(context.signal);
    const warnings: HumanizeWarning[] = [];
    const gateCodes: GateCode[] = [];
    // Manifest offsets are Python code-point indices, not UTF-16 units.
    const sourceText = context.sourcePoints
      .slice(chunk.start, chunk.end)
      .join("");
    const chunkSourcePath = context.workspace.path(
      `chunk-${chunk.index}-source.txt`
    );
    const rewrittenPath = context.workspace.path(chunk.rewrittenFile!);
    let codexCalls = 0;
    let retries = 0;
    let codexMs = 0;
    let restoreMs = 0;
    let gateMs = 0;
    let restoredSentences = 0;
    let removedCommas = 0;
    let repairedParticles = 0;
    let skippedSentences = 0;
    let fidelityGuardFailures = 0;
    let rolledBackChunks = 0;
    let restoredProtectedSentences = 0;
    let candidateReviewRetries = 0;
    const direct = context.rewriteOptions?.inputKind === 'direct-text';
    const protectedSentences = direct ? checkDirectTextFidelity(sourceText, sourceText).protectedSentences : 0;
    let fidelityFailed = false;
    let candidateFidelityIssues = 0;
    if (protectedSentences > 0 && context.rewriteOptions?.strength !== 'normal') {
      this.recordChunkWarning(context, warnings, {
        code: 'DIRECT_TEXT_PROTECTED_SENTENCES',
        message: `${chunk.index}번 구간의 ${protectedSentences}개 문장은 숫자·인용·서법·조건 표현을 원문 그대로 두고 그 밖의 표현만 다듬으므로 변경 범위가 작을 수 있습니다.`
      });
    }

    await writeFile(chunkSourcePath, sourceText, "utf8");

    // Deterministic post-processing right before the gate: sentences whose
    // deontic/hedge modality vanished go back to the source wording, and
    // commas the rewrite injected after connective endings are removed.
    const restore = async (): Promise<void> => {
      const startedAt = this.now();
      if (direct && context.rewriteOptions?.strength === 'very-strong') {
        const candidate = await readFile(rewrittenPath, 'utf8');
        const protectedRestoration = restoreProtectedSentences(sourceText, candidate);
        if (protectedRestoration.restoredProtectedSentences > 0) {
          await writeFile(rewrittenPath, protectedRestoration.rewrittenText, 'utf8');
          restoredProtectedSentences += protectedRestoration.restoredProtectedSentences;
          this.recordChunkWarning(context, warnings, {
            code: 'DIRECT_TEXT_PROTECTED_SENTENCES_RESTORED',
            message: `${chunk.index}번 구간에서 확실히 대응하는 보호 문장 ${protectedRestoration.restoredProtectedSentences}개를 원문으로 되돌렸습니다.`
          });
        }
      }
      const report = await this.python.restore(
        chunkSourcePath,
        rewrittenPath,
        context.signal
      );
      restoreMs += this.now() - startedAt;
      restoredSentences += report.restoredSentences;
      removedCommas += report.removedCommas;
      repairedParticles += report.repairedParticles ?? 0;
      if (direct) {
        skippedSentences += report.skippedSentences;
        fidelityFailed = candidateFidelityIssues > 0 || report.skippedSentences > 0 || checkDirectTextFidelity(sourceText, await readFile(rewrittenPath, 'utf8')).violations > 0;
        if (fidelityFailed) {
          fidelityGuardFailures++;
          this.recordChunkWarning(context, warnings, {
            code: 'DIRECT_TEXT_FIDELITY_RESTRICTED',
            message: `${chunk.index}번 구간에서 문장 경계·사실 관계·핵심 개념 또는 서법 보존을 확인하지 못해 넓은 수정을 제한했습니다.`
          });
        }
      } else {
        // Files and legacy requests keep their editing policy but never lose,
        // duplicate or move sentences, paragraphs or Markdown structure.
        fidelityFailed = checkStructuralFidelity(sourceText, await readFile(rewrittenPath, 'utf8')) > 0;
        if (fidelityFailed) {
          this.recordChunkWarning(context, warnings, {
            code: 'STRUCTURE_FIDELITY_RESTRICTED',
            message: `${chunk.index}번 구간에서 문장·문단 구조 보존을 확인하지 못해 수정을 제한했습니다.`
          });
        }
      }
      if (report.restoredSentences > 0) {
        this.recordChunkWarning(context, warnings, {
          code: "MODALITY_RESTORED",
          message: `${chunk.index}번 구간에서 서법 보존을 위해 ${report.restoredSentences}개 문장을 원문으로 되돌렸습니다.`
        });
      }
    };

    // A malformed or ambiguous reply costs this chunk an attempt, not the job:
    // attempt 1 falls through to the retry, attempt 2 rolls back.
    let unusableModelOutputs = 0;
    const hardFailures: Record<string, number> = {}, shadowFailures: Record<string, number> = {};
    const attemptTransform = async (attempt: 1 | 2, candidateReview?: CandidateReview): Promise<CodexResult | undefined> => {
      const startedAt = this.now();
      try {
        return await context.trackModelCall(() => this.codex.transform(
          chunkSourcePath,
          context.workspace.path(`codex-${chunk.index}-attempt-${attempt}.json`),
          attempt,
          context.signal,
          context.settings,
          context.rewriteOptions,
          candidateReview,
          context.chunkContext
        ));
      } catch (error) {
        if (context.signal.aborted || !unusableModelOutput(error)) throw error;
        unusableModelOutputs += 1;
        this.recordChunkWarning(context, warnings, {
          code: "MODEL_OUTPUT_UNUSABLE",
          message: `${chunk.index}번 구간의 모델 응답 형식을 사용할 수 없습니다.`
        });
        return undefined;
      } finally {
        codexMs += this.now() - startedAt;
        codexCalls += 1;
      }
    };
    const acceptCandidate = async (result: CodexResult): Promise<void> => {
      this.collectModelWarnings(context, warnings, result.warnings, chunk.index);
      candidateFidelityIssues = result.fidelityIssues ?? 0;
      await writeFile(rewrittenPath, alignOuterWhitespace(sourceText, result.rewrittenText), "utf8");
      await restore();
    };

    const first = await attemptTransform(1);
    this.ensureActive(context.signal);
    context.onWorkUnit("transform");
    let gate: GateResult | undefined;
    if (first) {
      await acceptCandidate(first);
      const firstGateStartedAt = this.now();
      gate = await this.python.verify(
        chunkSourcePath,
        rewrittenPath,
        context.signal
      );
      gateMs += this.now() - firstGateStartedAt;
      gateCodes.push(...gate.gateCodes);
      countCodes(hardFailures, gate.hardFailures);
      countCodes(shadowFailures, gate.shadowFailures);
      if (gate.status === "error") {
        throw validation(`Chunk ${chunk.index} gate execution failed`);
      }
    }

    if (!gate || fidelityFailed || gate.policy === "retry" || (!gate.policy && (gate.status === "warn" || gate.status === "abort"))) {
      retries += 1;
      this.recordChunkWarning(context, warnings, {
        code: "CHUNK_RETRY",
        message: `${chunk.index}번 구간을 더 보수적으로 다시 다듬습니다.`
      });

      const candidateReview = gate && !fidelityFailed ? candidateReviewForRetry({
        source: sourceText, candidate: await readFile(rewrittenPath, 'utf8'),
        options: context.rewriteOptions, gate, parserIssues: candidateFidelityIssues, skippedSentences
      }) : undefined;
      if (candidateReview) {
        candidateReviewRetries++;
        this.recordChunkWarning(context, warnings, {
          code: 'DIRECT_TEXT_CANDIDATE_REVIEW_RETRY',
          message: `${chunk.index}번 구간은 문체 목표 경고만 남아 이전 후보를 원문과 보수적으로 대조하는 재시도를 수행합니다. 불확실한 수정은 되돌립니다.`
        });
      }
      this.ensureActive(context.signal);
      const second = await attemptTransform(2, candidateReview);
      this.ensureActive(context.signal);
      gate = undefined;
      if (second) {
        await acceptCandidate(second);
        const secondGateStartedAt = this.now();
        gate = await this.python.verify(
          chunkSourcePath,
          rewrittenPath,
          context.signal,
          2
        );
        gateMs += this.now() - secondGateStartedAt;
        gateCodes.push(...gate.gateCodes);
        countCodes(hardFailures, gate.hardFailures);
        countCodes(shadowFailures, gate.shadowFailures);
        if (gate.status === "error") {
          throw validation(`Chunk ${chunk.index} retry gate execution failed`);
        }
      }
      if (!gate || fidelityFailed || gate.status === "abort") {
        rolledBackChunks++;
        await writeFile(rewrittenPath, sourceText, "utf8");
        this.recordChunkWarning(context, warnings, {
          code: "CHUNK_ROLLED_BACK",
          message: `${chunk.index}번 구간은 의미 보존을 위해 원문을 유지했습니다.`
        });
      } else if (gate.status === "warn") {
        this.recordChunkWarning(context, warnings, {
          code: "CHUNK_WARNING_ACCEPTED",
          message: `${chunk.index}번 구간에 검토 권고가 있습니다.`
        });
      }
    }

    this.ensureActive(context.signal);
    context.onWorkUnit("verify");
    // Whether the style hints helped is measured, never assumed: findings in the source vs the delivered chunk.
    const styleBefore = collectKoreanStyleFindings(sourceText).length;
    const styleAfter = collectKoreanStyleFindings(await readFile(rewrittenPath, "utf8")).length;
    return {
      chunkIndex: chunk.index,
      warnings,
      codexCalls,
      retries,
      restoredSentences,
      removedCommas,
      repairedParticles,
      skippedSentences, fidelityGuardFailures, rolledBackChunks, protectedSentences, restoredProtectedSentences, candidateReviewRetries,
      unusableModelOutputs,
      hardFailures,
      shadowFailures,
      styleBefore,
      styleAfter,
      gateCodes,
      timings: { codexMs, restoreMs, gateMs }
    };
  }

  async transform(request: HumanizeRequest): Promise<HumanizeResult> {
    const shadow: { run?: V2ShadowRun } = {};
    try {
      return await this.decideAndDeliver(request, shadow);
    } finally {
      shadow.run?.dispose();
    }
  }

  private async decideAndDeliver(request: HumanizeRequest, shadow: { run?: V2ShadowRun }): Promise<HumanizeResult> {
    const rewriteOptions = parseRewriteOptions(request.rewriteOptions?.inputKind, request.rewriteOptions?.strength);
    const totalStartedAt = this.now();
    this.ensureActive(request.signal);
    const warnings: HumanizeWarning[] = [];
    request.onEvent({
      type: "progress",
      phase: "sanitize",
      current: 0,
      total: 1,
      message: "원문을 안전하게 준비하는 중입니다."
    });

    const prepareStartedAt = totalStartedAt;
    const manifest = await this.python.prepare(
      request.workspace.root,
      request.signal
    );
    const prepareMs = this.now() - prepareStartedAt;
    this.ensureActive(request.signal);
    request.onEvent({
      type: "progress",
      phase: "chunk",
      current: 1,
      total: 1,
      message: `${manifest.bodyChunkCount}개 구간으로 준비했습니다.`
    });

    for (const message of manifest.warnings) {
      this.emitWarning(request, warnings, {
        code: "CHUNK_PREPARE_WARNING",
        message
      });
    }

    const sourcePath = request.workspace.path(manifest.sourceFile);
    const source = await readFile(sourcePath, "utf8");
    const sourcePoints = Array.from(source);
    const lastChunk = manifest.chunks.at(-1);
    if (
      manifest.sourceChars !== sourcePoints.length ||
      (lastChunk ? lastChunk.end : 0) !== sourcePoints.length
    ) {
      throw new EngineError(
        "ENGINE_OUTPUT_INVALID",
        false,
        "Chunk manifest does not cover the prepared source text"
      );
    }
    shadow.run = this.startShadow(request, source, rewriteOptions);
    const bodyChunks = manifest.chunks.filter(chunk => !chunk.passthrough);
    // Chunks are rewritten independently; the document's speech level keeps them consistent.
    const documentRegisterOfSource = bodyChunks.length > 1 ? documentRegister(source) : undefined;
    const concurrency =
      manifest.processingMode === "single" ? 1 : this.chunkConcurrency;
    let completedUnits = 0;
    const totalUnits = bodyChunks.length * 2;
    // Per job: a shared permit pool's lifetime maximum would leak earlier jobs.
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
    const chunkResults = await runChunkPool(
      bodyChunks.map((chunk, bodyIndex) => ({ chunk, bodyIndex })),
      concurrency,
      request.signal,
      async ({ chunk, bodyIndex }, signal) => {
        this.ensureActive(signal);
        return this.processChunk(chunk, {
          chunkContext: bodyChunks.length > 1 ? { index: bodyIndex + 1, total: bodyChunks.length, register: documentRegisterOfSource } : undefined,
          settings: request.settings,
          rewriteOptions,
          sourcePoints,
          workspace: request.workspace,
          signal,
          trackModelCall,
          onWarning: warning =>
            request.onEvent({ type: "warning", ...warning }),
          onWorkUnit: phase => {
            completedUnits += 1;
            request.onEvent({
              type: "progress",
              phase,
              current: bodyIndex + 1,
              total: bodyChunks.length,
              completedUnits,
              totalUnits,
              message: phase === "transform"
                ? `${bodyIndex + 1}/${bodyChunks.length} 구간을 다듬는 중입니다.`
                : `${bodyIndex + 1}/${bodyChunks.length} 구간을 검증하는 중입니다.`
            });
          }
        });
      }
    );
    warnings.push(...chunkResults.flatMap(result => result.warnings));
    // Every chunk kept its source because no attempt produced a usable reply:
    // that is a model failure, not a completed rewrite.
    if (chunkResults.length > 0 && chunkResults.every(result => result.unusableModelOutputs >= 2)) {
      throw new EngineError("ENGINE_OUTPUT_INVALID", false, "Every chunk returned unusable model output");
    }

    this.ensureActive(request.signal);
    request.onEvent({
      type: "progress",
      phase: "assemble",
      current: 1,
      total: 1,
      message: "문단과 순서를 복원하는 중입니다."
    });
    const assembleStartedAt = this.now();
    const finalPath = await this.python.reassemble(
      request.workspace.root,
      request.signal
    );
    const assembleFinishedAt = this.now();
    const assembleMs = assembleFinishedAt - assembleStartedAt;
    const fullGateStartedAt = assembleFinishedAt;
    let fullFidelityFailures = 0;
    if (rewriteOptions?.inputKind === 'direct-text' && checkDirectTextFidelity(source, await readFile(finalPath, 'utf8')).violations > 0) {
      fullFidelityFailures = 1;
      await writeFile(finalPath, source, 'utf8');
      this.emitWarning(request, warnings, {code:'DIRECT_TEXT_DOCUMENT_ROLLED_BACK',message:'전체 글의 문장 경계·내용 보존을 확인하지 못해 원문을 유지했습니다.'});
    }
    // The delivered text is final here (the full gate only accepts or fails the job); the shadow reads it while that gate runs.
    shadow.run?.check(await readFile(finalPath, "utf8"));
    const fullGate = await this.python.verify(
      sourcePath,
      finalPath,
      request.signal
    );
    const fullGateMs = this.now() - fullGateStartedAt;
    if (fullGate.status === "abort" || fullGate.status === "error") {
      throw validation("Full-document validation failed");
    }
    if (fullGate.status === "warn") {
      this.emitWarning(request, warnings, {
        code: "DOCUMENT_REVIEW_RECOMMENDED",
        message: "전체 문서에 사람 검토가 권장되는 항목이 있습니다."
      });
    }

    const output = await readFile(finalPath, "utf8");
    const v2ShadowCounts = await shadow.run?.collect();
    const sourceChars = sourcePoints.length;
    const diagnostics: TransformDiagnostics = {
      ...(rewriteOptions ? {requestedStrength: rewriteOptions.strength} : {}),
      ...(rewriteOptions?.inputKind === 'direct-text' ? {
        candidateReviewRetries: chunkResults.reduce((sum, result) => sum + result.candidateReviewRetries, 0),
        conservativeRetries: chunkResults.reduce((sum, result) => sum + result.retries, 0),
        skippedSentences: chunkResults.reduce((sum, result) => sum + result.skippedSentences, 0),
        fidelityGuardFailures: chunkResults.reduce((sum, result) => sum + result.fidelityGuardFailures, 0) + fullFidelityFailures,
        protectedSentences: chunkResults.reduce((sum, result) => sum + result.protectedSentences, 0),
        restoredProtectedSentences: chunkResults.reduce((sum, result) => sum + result.restoredProtectedSentences, 0),
        fullSourceRollbacks: fullFidelityFailures
      } : {}),
      ...(v2ShadowCounts ? { v2ShadowCounts } : {}),
      rolledBackChunks: chunkResults.reduce((sum, result) => sum + result.rolledBackChunks, 0),
      unusableModelOutputs: chunkResults.reduce((sum, result) => sum + result.unusableModelOutputs, 0),
      hardFailureCounts: mergeCounts([...chunkResults.map(result => result.hardFailures), codeCounts(fullGate.hardFailures)]),
      shadowFailureCounts: mergeCounts([...chunkResults.map(result => result.shadowFailures), codeCounts(fullGate.shadowFailures)]),
      styleFindingsBefore: chunkResults.reduce((sum, result) => sum + result.styleBefore, 0),
      styleFindingsAfter: chunkResults.reduce((sum, result) => sum + result.styleAfter, 0),
      repairedParticles: chunkResults.reduce((sum, result) => sum + result.repairedParticles, 0),
      model: request.settings?.model ?? this.model,
      reasoningEffort: request.settings?.effort ?? this.reasoningEffort,
      processingMode: manifest.processingMode,
      routeHint: manifest.routeHint,
      sourceChars,
      bodyChunks: bodyChunks.length,
      codexCalls: chunkResults.reduce(
        (total, result) => total + result.codexCalls,
        0
      ),
      retries: chunkResults.reduce(
        (total, result) => total + result.retries,
        0
      ),
      restoredSentences: chunkResults.reduce(
        (total, result) => total + result.restoredSentences,
        0
      ),
      removedCommas: chunkResults.reduce(
        (total, result) => total + result.removedCommas,
        0
      ),
      gateCodes: [
        ...chunkResults.flatMap(result => result.gateCodes),
        ...fullGate.gateCodes
      ],
      maxObservedCodexConcurrency,
      prepareMs,
      codexMs: chunkResults.reduce(
        (total, result) => total + result.timings.codexMs,
        0
      ),
      restoreMs: chunkResults.reduce(
        (total, result) => total + result.timings.restoreMs,
        0
      ),
      gateMs:
        chunkResults.reduce(
          (total, result) => total + result.timings.gateMs,
          0
        ) + fullGateMs,
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
