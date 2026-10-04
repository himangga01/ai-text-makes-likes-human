/** TypeScript side of the Super Sejong v2 Python CLI (engine_runtime/sejong_cli.py, DESIGN.md 5.1/5.2).
 * Spawns prepare/analyse/check/verify/finalize through the same CommandRunner the legacy
 * python-engine.ts uses, reads the plan, check report and manifest files with a size bound, and
 * validates them as engine_runtime/sejong/io.py does: the JSON Schema subset against
 * engine_runtime/sejong/schemas/*.schema.json (read at run time, so one schema serves both languages)
 * plus the cross-reference checks a schema cannot express. Exit codes map to the legacy gate contract:
 * check/verify 0-3 = gate.exit_code with the legacy decision table, 3 = execution error.
 * Error messages name steps, JSON paths and keywords only, never document text.
 * Nothing imports this module yet: the legacy engine stays the default.
 */
import { open, stat } from 'node:fs/promises';
import path from 'node:path';
import type { CommandResult, CommandRunner } from '../../process/command-runner.js';
import { EngineError } from '../errors.js';
import type { ChunkEntry, ChunkManifest, GateResult } from '../python-engine.js';
import type { RewriteOptions, RewriteStrength } from '../rewrite-policy.js';
import {
  CHECK_SCHEMA, isSejongCode, LEGACY_REASONS, PLAN_SCHEMA, SEJONG_GENRES,
  type CheckReport, type GatePolicy, type Plan, type SejongGenre
} from './types.js';

export const SEJONG_CLI = 'sejong_cli.py';
const GATE_CODES = ['GATE_OK', 'GATE_WARN', 'GATE_ABORT', 'GATE_ERROR'] as const;
const GATE_STATUS = ['ok', 'warn', 'abort', 'error'] as const;

export interface SejongPythonOptions {
  pythonCommand: string;
  /** The engine_runtime directory: holds sejong_cli.py and sejong/schemas/. */
  engineRoot: string;
  runner: CommandRunner;
  timeoutMs?: number;
  /** Cap on captured stdout+stderr of one CLI run (reports go to files). Default 1 MiB. */
  maxOutputBytes?: number;
  /** Cap on one plan, check report or manifest file. Default 16 MiB. */
  maxReportBytes?: number;
  /** Base environment of the child (default process.env); PYTHONDONTWRITEBYTECODE and PYTHONUTF8 are always set. */
  env?: NodeJS.ProcessEnv;
}

export interface AnalyseOptions {
  inputKind: RewriteOptions['inputKind'];
  strength: RewriteStrength;
  genre: SejongGenre;
}

export interface AnalyseArgs extends AnalyseOptions {
  /** Chunk text file. */
  source: string;
  /** Whole prepared document, for seams and footnotes. */
  context?: string;
  chunkIndex: number;
  chunkTotal: number;
  /** Where the CLI writes plan.json. */
  out: string;
}

export interface CheckArgs {
  plan: string;
  source: string;
  /** Exactly one of response (writer reply JSON) and candidate (text). */
  response?: string;
  candidate?: string;
  attempt: 1 | 2;
  /** Attempt 2: the decided text of attempt 1. */
  base?: string;
  /** Decided chunk text written by the CLI. */
  out: string;
  /** Check report written by the CLI. */
  report: string;
}

export interface SejongSeam { chunk: number; prev: [number, number]; next: [number, number] }
export interface SejongManifest extends ChunkManifest {
  /** Optional v2 block (DESIGN 3.12 Manifest). */
  sejong?: { version: 1; genre: SejongGenre; seams: SejongSeam[] };
}

/* ---------- JSON Schema subset: the keywords of engine_runtime/sejong/io.py, nothing else ---------- */

export type JsonSchema = { [key: string]: unknown };
export class SchemaError extends Error {}
const ANNOTATIONS = ['$schema', '$id', '$comment', '$defs', 'title', 'description', 'default', 'examples'];
const KEYWORDS = new Set([...ANNOTATIONS, 'type', 'enum', 'const', 'pattern', 'minLength', 'maxLength', 'minimum',
  'maximum', 'minItems', 'maxItems', 'uniqueItems', 'items', 'properties', 'required', 'additionalProperties',
  'propertyNames', 'anyOf', '$ref']);
const patterns = new Map<string, RegExp>();

function kindOf(value: unknown): string {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number';
  return typeof value;
}

function same(a: unknown, b: unknown): boolean {
  const ka = kindOf(a), kb = kindOf(b);
  if (ka === 'array' && kb === 'array') {
    const x = a as unknown[], y = b as unknown[];
    return x.length === y.length && x.every((item, i) => same(item, y[i]));
  }
  if (ka === 'object' && kb === 'object') {
    const x = a as Record<string, unknown>, y = b as Record<string, unknown>;
    const keys = Object.keys(x);
    return keys.length === Object.keys(y).length && keys.every(key => Object.hasOwn(y, key) && same(x[key], y[key]));
  }
  return a === b;
}

function codePointLength(text: string): number {
  let count = 0;
  for (const _ of text) count += 1;
  return count;
}

/** Problems of value against schema ([] = valid). Messages name JSON paths and keywords only. */
export function validateSchema(value: unknown, schema: JsonSchema, root: JsonSchema = schema, at = '$'): string[] {
  const unknown = Object.keys(schema).filter(key => !KEYWORDS.has(key));
  if (unknown.length) throw new SchemaError(`unsupported keywords ${unknown.sort().join(',')} at ${at}`);
  const problems: string[] = [];
  if (typeof schema.$ref === 'string') {
    if (!schema.$ref.startsWith('#/')) throw new SchemaError(`only local $ref is supported at ${at}`);
    const target = schema.$ref.slice(2).split('/')
      .reduce<unknown>((node, part) => (node as JsonSchema)[part.replaceAll('~1', '/').replaceAll('~0', '~')], root);
    problems.push(...validateSchema(value, target as JsonSchema, root, at));
  }
  const kind = kindOf(value);
  if (schema.type !== undefined) {
    const allowed = (Array.isArray(schema.type) ? schema.type : [schema.type]) as string[];
    if (!allowed.includes(kind) && !(kind === 'integer' && allowed.includes('number'))) return [...problems, `${at}: type`];
  }
  if ('const' in schema && !same(value, schema.const)) problems.push(`${at}: const`);
  if (Array.isArray(schema.enum) && !schema.enum.some(option => same(value, option))) problems.push(`${at}: enum`);
  if (Array.isArray(schema.anyOf) && !schema.anyOf.some(option => validateSchema(value, option as JsonSchema, root, at).length === 0)) {
    problems.push(`${at}: anyOf`);
  }
  if (kind === 'string') {
    const text = value as string;
    if (typeof schema.minLength === 'number' || typeof schema.maxLength === 'number') {
      const length = codePointLength(text);
      if (typeof schema.minLength === 'number' && length < schema.minLength) problems.push(`${at}: minLength`);
      if (typeof schema.maxLength === 'number' && length > schema.maxLength) problems.push(`${at}: maxLength`);
    }
    if (typeof schema.pattern === 'string') {
      let regex = patterns.get(schema.pattern);
      if (!regex) patterns.set(schema.pattern, regex = new RegExp(schema.pattern, 'u'));
      if (!regex.test(text)) problems.push(`${at}: pattern`);
    }
  }
  if (kind === 'integer' || kind === 'number') {
    if (typeof schema.minimum === 'number' && (value as number) < schema.minimum) problems.push(`${at}: minimum`);
    if (typeof schema.maximum === 'number' && (value as number) > schema.maximum) problems.push(`${at}: maximum`);
  }
  if (kind === 'array') {
    const items = value as unknown[];
    if (typeof schema.minItems === 'number' && items.length < schema.minItems) problems.push(`${at}: minItems`);
    if (typeof schema.maxItems === 'number' && items.length > schema.maxItems) problems.push(`${at}: maxItems`);
    if (schema.uniqueItems === true && items.some((item, i) => items.slice(0, i).some(other => same(item, other)))) {
      problems.push(`${at}: uniqueItems`); // only short arrays (rules, ≤ 40) use uniqueItems
    }
    if (schema.items) items.forEach((item, i) => problems.push(...validateSchema(item, schema.items as JsonSchema, root, `${at}[${i}]`)));
  }
  if (kind === 'object') {
    const object = value as Record<string, unknown>;
    const properties = (schema.properties ?? {}) as Record<string, JsonSchema>;
    for (const key of (schema.required ?? []) as string[]) if (!Object.hasOwn(object, key)) problems.push(`${at}: missing ${key}`);
    for (const [key, item] of Object.entries(object)) {
      if (schema.propertyNames && validateSchema(key, schema.propertyNames as JsonSchema, root, at).length) {
        problems.push(`${at}: propertyNames`);
        continue;
      }
      if (Object.hasOwn(properties, key)) problems.push(...validateSchema(item, properties[key]!, root, `${at}.${key}`));
      else if (schema.additionalProperties === false) problems.push(`${at}: unknown property`);
      else if (typeof schema.additionalProperties === 'object' && schema.additionalProperties !== null) {
        problems.push(...validateSchema(item, schema.additionalProperties as JsonSchema, root, `${at}.${key}`));
      }
    }
  }
  return problems;
}

/* ---------- contract checks beyond the schema (port of io.plan_problems / io.check_problems) ---------- */

/** Legacy decision table (engine_runtime/workflow.decision), kept by v2 (3.9). */
export function gatePolicy(exitCode: 0 | 1 | 2 | 3, attempt: 1 | 2): GatePolicy {
  if (exitCode === 3) return 'error';
  if (exitCode === 0) return 'accept';
  if (attempt === 1) return 'retry';
  return exitCode === 2 ? 'rollback' : 'accept-with-warning';
}

function duplicates(items: Array<{ id: string }>, what: string): string[] {
  const seen = new Set<string>(), problems: string[] = [];
  for (const item of items) {
    if (seen.has(item.id)) problems.push(`$.${what}: duplicate id ${item.id}`);
    seen.add(item.id);
  }
  return problems;
}

export function planProblems(data: unknown, schema: JsonSchema): string[] {
  const problems = validateSchema(data, schema);
  if (problems.length) return problems;
  const plan = data as Plan;
  for (const key of ['sentences', 'findings', 'requests', 'ctaLedger'] as const) problems.push(...duplicates(plan[key], key));
  const chars = plan.chunk.chars;
  if (plan.chunk.index > plan.chunk.total) problems.push('$.chunk: index above total');
  const sentences = new Map(plan.sentences.map(s => [s.id, s]));
  const findings = new Map(plan.findings.map(f => [f.id, f]));
  const ledger = new Map(plan.ctaLedger.map(c => [c.id, c]));
  let previousEnd = 0;
  plan.sentences.forEach((s, index) => {
    const where = `$.sentences[${index}]`;
    if (!(previousEnd <= s.start && s.start <= s.end && s.end <= chars) || s.startU16 > s.endU16 ||
        s.startU16 < s.start || s.endU16 < s.end) problems.push(`${where}: offsets out of order`);
    previousEnd = s.end;
    for (const id of s.findings) {
      if (findings.get(id)?.sentence !== s.id) problems.push(`${where}.findings: ${id} does not point back to ${s.id}`);
    }
    if (s.cta !== null && ledger.get(s.cta)?.sentence !== s.id) problems.push(`${where}.cta: ${s.cta} does not point back to ${s.id}`);
  });
  const inside = (item: { sentence: string; start: number; end: number }, where: string): void => {
    const sentence = sentences.get(item.sentence);
    if (!sentence) problems.push(`${where}: unknown sentence ${item.sentence}`);
    else if (!(sentence.start <= item.start && item.start <= item.end && item.end <= sentence.end)) {
      problems.push(`${where}: range outside sentence ${item.sentence}`);
    }
  };
  const requestRules = new Map<string, Set<string>>();
  plan.findings.forEach((f, index) => {
    inside(f, `$.findings[${index}]`);
    const listed = sentences.get(f.sentence)?.findings;
    if (listed && !listed.includes(f.id)) problems.push(`$.findings[${index}]: not listed by sentence ${f.sentence}`);
    if (f.action === 'request') {
      const rules = requestRules.get(f.sentence) ?? new Set<string>();
      rules.add(f.rule);
      requestRules.set(f.sentence, rules);
    }
  });
  plan.protected.forEach((span, index) => {
    if (!(span.start < span.end && span.end <= chars)) problems.push(`$.protected[${index}]: empty or out of range`);
  });
  plan.ctaLedger.forEach((c, index) => {
    if (!sentences.has(c.sentence)) problems.push(`$.ctaLedger[${index}]: unknown sentence ${c.sentence}`);
  });
  const requested = new Set<string>();
  plan.requests.forEach((r, index) => {
    const where = `$.requests[${index}]`;
    if (!sentences.has(r.sentence)) problems.push(`${where}: unknown sentence ${r.sentence}`);
    if (requested.has(r.sentence)) problems.push(`${where}: second request for ${r.sentence}`);
    requested.add(r.sentence);
    const rules = requestRules.get(r.sentence) ?? new Set<string>();
    if (r.tier !== 'REVIEW' && (!r.rules.length || r.rules.some(rule => !rules.has(rule)))) {
      problems.push(`${where}: rules are not request findings of ${r.sentence}`);
    }
  });
  plan.deterministic.forEach((d, index) => {
    const where = `$.deterministic[${index}]`;
    inside(d, where);
    const finding = findings.get(d.finding);
    if (!finding || finding.action !== 'deterministic' || finding.sentence !== d.sentence) {
      problems.push(`${where}: finding is not a deterministic finding of ${d.sentence}`);
    }
    if (d.end - d.start !== codePointLength(d.before)) problems.push(`${where}: range length differs from before`);
  });
  const review = plan.openReview;
  if (plan.options.openReview !== review.enabled) problems.push('$.openReview.enabled: differs from options.openReview');
  if (!review.enabled && review.maxSentences !== 0) problems.push('$.openReview.maxSentences: must be 0 when disabled');
  if (plan.needsModel !== (plan.requests.length > 0 || review.enabled)) {
    problems.push('$.needsModel: must equal (requests non-empty or openReview.enabled)');
  }
  return problems;
}

export function checkProblems(data: unknown, schema: JsonSchema): string[] {
  const problems = validateSchema(data, schema);
  if (problems.length) return problems;
  const report = data as CheckReport;
  const exitCode = report.gate.exit_code, attempt = report.attempt;
  if (report.policy !== gatePolicy(exitCode, attempt)) problems.push('$.policy: differs from the legacy decision table');
  if (report.hardFailures.length && exitCode !== 2 && exitCode !== 3) problems.push('$.hardFailures: present with exit code 0 or 1');
  if (report.warningReasons.codes.some(code => code !== 'P0_CHANGE_RATE')) {
    problems.push('$.warningReasons.codes: v2 emits at most P0_CHANGE_RATE');
  }
  problems.push(...duplicates(report.sentences, 'sentences'), ...duplicates(report.retry, 'retry'));
  if (report.retry.length && (attempt !== 1 || report.policy !== 'retry')) problems.push('$.retry: only at attempt 1 with policy retry');
  const retrying = new Map(report.sentences.filter(s => s.status === 'retry').map(s => [s.id, s.request]));
  const listed = new Map(report.retry.map(r => [r.sentence, r.id]));
  if (listed.size !== retrying.size || [...listed].some(([sentence, id]) => !retrying.has(sentence) || retrying.get(sentence) !== id)) {
    problems.push('$.retry: must list exactly the sentences with status retry and their requests');
  }
  return problems;
}

/** Legacy GateResult view of a check report, the shape humanize-engine.ts consumes from PythonEngine.verify(). */
export function gateResultOf(report: Pick<CheckReport, 'gate' | 'hardFailures' | 'warningReasons' | 'policy' | 'shadowFailures'>): GateResult {
  const exitCode = report.gate.exit_code;
  return {
    status: GATE_STATUS[exitCode],
    exitCode,
    gateCodes: [GATE_CODES[exitCode]],
    warningReasons: { version: 1, codes: [...report.warningReasons.codes] },
    hardFailures: [...report.hardFailures],
    shadowFailures: report.shadowFailures.filter(isSejongCode),
    policy: report.policy
  };
}

/* ---------- manifest v1 (+ optional sejong block) ---------- */

function invalid(message: string, cause?: unknown): EngineError {
  return new EngineError('ENGINE_OUTPUT_INVALID', false, message, cause === undefined ? undefined : { cause });
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw invalid(`${label} must be an object`);
  return value as Record<string, unknown>;
}
function integer(value: unknown, label: string): number {
  if (!Number.isInteger(value) || Number(value) < 0) throw invalid(`${label} must be a nonnegative integer`);
  return Number(value);
}
function text(value: unknown, label: string): string {
  if (typeof value !== 'string') throw invalid(`${label} must be a string`);
  return value;
}
function flag(value: unknown, label: string): boolean {
  if (typeof value !== 'boolean') throw invalid(`${label} must be a boolean`);
  return value;
}
function safeLeaf(value: unknown, label: string): string {
  const leaf = text(value, label);
  if (!leaf || path.isAbsolute(leaf) || leaf.includes('/') || leaf.includes('\\') || leaf === '.' || leaf === '..') {
    throw invalid(`${label} must be a safe filename`);
  }
  return leaf;
}
function range(value: unknown, label: string): [number, number] {
  if (!Array.isArray(value) || value.length !== 2) throw invalid(`${label} must be a [start, end] pair`);
  const start = integer(value[0], label), end = integer(value[1], label);
  if (start > end) throw invalid(`${label} must not end before it starts`);
  return [start, end];
}

/** Manifest v1 as python-engine.ts parses it, plus the optional `sejong` block. Unknown root keys are ignored. */
export function parseSejongManifest(value: unknown): SejongManifest {
  const root = record(value, 'manifest');
  if (integer(root.version, 'version') !== 1) throw invalid('Unsupported manifest version');
  if (!Array.isArray(root.chunks)) throw invalid('chunks must be an array');
  const chunks = root.chunks.map((raw, offset): ChunkEntry => {
    const chunk = record(raw, `chunks[${offset}]`);
    const passthrough = flag(chunk.passthrough, `chunks[${offset}].passthrough`);
    const inputFile = chunk.input_file === null ? null : safeLeaf(chunk.input_file, `chunks[${offset}].input_file`);
    const rewrittenFile = chunk.rewritten_file === null ? null : safeLeaf(chunk.rewritten_file, `chunks[${offset}].rewritten_file`);
    if (passthrough && (inputFile !== null || rewrittenFile !== null)) throw invalid('Passthrough chunks cannot have rewrite filenames');
    if (!passthrough && (inputFile === null || rewrittenFile === null)) throw invalid('Body chunks require input and rewritten filenames');
    if (chunk.heading !== null && typeof chunk.heading !== 'string') throw invalid(`chunks[${offset}].heading must be string or null`);
    return {
      index: integer(chunk.index, `chunks[${offset}].index`),
      start: integer(chunk.start, `chunks[${offset}].start`),
      end: integer(chunk.end, `chunks[${offset}].end`),
      charCount: integer(chunk.char_count, `chunks[${offset}].char_count`),
      startsWithHeading: flag(chunk.starts_with_heading, `chunks[${offset}].starts_with_heading`),
      heading: chunk.heading as string | null,
      passthrough, inputFile, rewrittenFile
    };
  });
  const chunkCount = integer(root.chunk_count, 'chunk_count');
  if (chunks.length !== chunkCount) throw invalid('chunk_count mismatch');
  chunks.forEach((chunk, index) => {
    if (chunk.index !== index + 1 || chunk.end < chunk.start) throw invalid('Invalid chunk ordering');
    if (index > 0 && chunks[index - 1]!.end !== chunk.start) throw invalid('Chunk spans are not contiguous');
  });
  if (!Array.isArray(root.warnings) || root.warnings.some(item => typeof item !== 'string')) throw invalid('warnings must be a string array');
  const routeHint = root.route_hint;
  if (routeHint !== null && routeHint !== 'light' && routeHint !== 'standard' && routeHint !== 'heavy') {
    throw invalid('route_hint must be light, standard, heavy, or null');
  }
  if (root.processing_mode !== 'single' && root.processing_mode !== 'chunked') throw invalid('processing_mode must be single or chunked');
  const manifest: SejongManifest = {
    version: 1,
    sourceFile: safeLeaf(root.source_file, 'source_file'),
    sourceChars: integer(root.source_chars, 'source_chars'),
    sourceSha256: text(root.source_sha256, 'source_sha256'),
    chunkCount,
    bodyChunkCount: integer(root.body_chunk_count, 'body_chunk_count'),
    passthroughChunkCount: integer(root.passthrough_chunk_count, 'passthrough_chunk_count'),
    routeHint,
    routeReason: root.route_reason === null ? null : text(root.route_reason, 'route_reason'),
    processingMode: root.processing_mode,
    chunks,
    warnings: root.warnings as string[]
  };
  if (root.sejong !== undefined) {
    const block = record(root.sejong, 'sejong');
    if (integer(block.version, 'sejong.version') !== 1) throw invalid('Unsupported sejong manifest block');
    if (!SEJONG_GENRES.includes(block.genre as SejongGenre)) throw invalid('sejong.genre is not a known genre');
    if (!Array.isArray(block.seams)) throw invalid('sejong.seams must be an array');
    const seams = block.seams.map((raw, offset): SejongSeam => {
      const seam = record(raw, `sejong.seams[${offset}]`);
      const chunk = integer(seam.chunk, `sejong.seams[${offset}].chunk`);
      if (chunk < 1 || chunk > chunkCount) throw invalid(`sejong.seams[${offset}].chunk is not a chunk`);
      return { chunk, prev: range(seam.prev, `sejong.seams[${offset}].prev`), next: range(seam.next, `sejong.seams[${offset}].next`) };
    });
    manifest.sejong = { version: 1, genre: block.genre as SejongGenre, seams };
  }
  return manifest;
}

/** The last line-starting JSON object in CLI output, as python-engine.ts reads the legacy gate report. */
function lastJsonObject(output: string, label: string): Record<string, unknown> {
  const starts = [...output.matchAll(/^\{/gmu)].map(match => match.index!);
  for (const start of starts.reverse()) {
    try {
      return record(JSON.parse(output.slice(start).trim()), `${label} report`);
    } catch {
      // Continue with an earlier line-starting object.
    }
  }
  throw invalid(`Unable to parse ${label} JSON report`);
}

/* ---------- the adapter ---------- */

export class SejongPython {
  private readonly engineRoot: string;
  private readonly timeoutMs: number;
  private readonly maxOutputBytes: number;
  private readonly maxReportBytes: number;
  private readonly schemas = new Map<string, Promise<JsonSchema>>();

  constructor(private readonly options: SejongPythonOptions) {
    this.engineRoot = path.resolve(options.engineRoot);
    this.timeoutMs = options.timeoutMs ?? 120_000;
    this.maxOutputBytes = options.maxOutputBytes ?? 1024 * 1024;
    this.maxReportBytes = options.maxReportBytes ?? 16 * 1024 * 1024;
  }

  get cliPath(): string {
    return path.join(this.engineRoot, SEJONG_CLI);
  }

  private schema(name: 'plan' | 'check'): Promise<JsonSchema> {
    let loaded = this.schemas.get(name);
    if (!loaded) {
      loaded = this.readBounded(path.join(this.engineRoot, 'sejong', 'schemas', `${name}.schema.json`), `${name} schema`)
        .then(raw => record(JSON.parse(raw), `${name} schema`) as JsonSchema);
      loaded.catch(() => this.schemas.delete(name));
      this.schemas.set(name, loaded);
    }
    return loaded;
  }

  private async readBounded(file: string, label: string): Promise<string> {
    let handle;
    try {
      const info = await stat(file);
      if (!info.isFile()) throw invalid(`Sejong ${label} is not a file`);
      if (info.size > this.maxReportBytes) throw invalid(`Sejong ${label} exceeds ${this.maxReportBytes} bytes`);
      handle = await open(file, 'r');
      // Read at most the bound plus one byte, so a file that grew after stat() is still caught.
      const buffer = Buffer.alloc(Math.min(info.size, this.maxReportBytes) + 1);
      const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
      if (bytesRead > this.maxReportBytes) throw invalid(`Sejong ${label} exceeds ${this.maxReportBytes} bytes`);
      return buffer.subarray(0, bytesRead).toString('utf8');
    } catch (error) {
      if (error instanceof EngineError) throw error;
      throw invalid(`Unable to read Sejong ${label}`, error);
    } finally {
      await handle?.close();
    }
  }

  private async readJson(file: string, label: string): Promise<unknown> {
    const raw = await this.readBounded(file, label);
    try {
      return JSON.parse(raw);
    } catch (error) {
      throw invalid(`Sejong ${label} is not JSON`, error);
    }
  }

  private async run(step: string, args: string[], cwd: string, signal: AbortSignal): Promise<CommandResult> {
    const result = await this.options.runner.run({
      command: this.options.pythonCommand,
      args: [this.cliPath, step, ...args],
      cwd,
      timeoutMs: this.timeoutMs,
      maxOutputBytes: this.maxOutputBytes,
      signal,
      env: { ...(this.options.env ?? process.env), PYTHONDONTWRITEBYTECODE: '1', PYTHONUTF8: '1' }
    });
    if (result.termination === 'timeout') throw new EngineError('ENGINE_TIMEOUT', true, `Sejong ${step} timed out`);
    if (result.termination === 'aborted') throw new EngineError('CLIENT_ABORTED', true, `Sejong ${step} was cancelled`);
    if (result.termination === 'output-limit') throw invalid(`Sejong ${step} output exceeded the limit`);
    return result;
  }

  /** prepare/analyse/finalize exit 0 or 1 (DESIGN 5.1); anything but 0 fails the step like the legacy prepare. */
  private requireSuccess(step: string, result: CommandResult): void {
    if (result.exitCode === 1) throw invalid(`Sejong ${step} step failed`);
    if (result.exitCode !== 0) throw invalid(`Sejong ${step} exited with an unexpected code`);
  }

  async prepare(runDir: string, signal: AbortSignal, opts: { analyse?: AnalyseOptions } = {}): Promise<SejongManifest> {
    const dir = path.resolve(runDir);
    const analyse = opts.analyse
      ? ['--analyse', '--input-kind', opts.analyse.inputKind, '--strength', opts.analyse.strength, '--genre', opts.analyse.genre]
      : [];
    this.requireSuccess('prepare', await this.run('prepare', ['--run-dir', dir, ...analyse], dir, signal));
    return parseSejongManifest(await this.readJson(path.join(dir, 'chunk_manifest.json'), 'chunk manifest'));
  }

  async analyse(args: AnalyseArgs, signal: AbortSignal): Promise<Plan> {
    if (!Number.isInteger(args.chunkIndex) || !Number.isInteger(args.chunkTotal) || args.chunkIndex < 1 || args.chunkIndex > args.chunkTotal) {
      throw new Error('Chunk index must be within 1..total');
    }
    const source = path.resolve(args.source), out = path.resolve(args.out);
    const result = await this.run('analyse', [
      '--source', source,
      ...(args.context ? ['--context', path.resolve(args.context)] : []),
      '--chunk-index', String(args.chunkIndex), '--chunk-total', String(args.chunkTotal),
      '--input-kind', args.inputKind, '--strength', args.strength, '--genre', args.genre,
      '--out', out
    ], path.dirname(source), signal);
    this.requireSuccess('analyse', result);
    const data = await this.readJson(out, 'plan');
    const problems = planProblems(data, await this.schema('plan'));
    if (problems.length) throw invalid(`Sejong plan is invalid: ${problems.slice(0, 3).join('; ')}`);
    const plan = data as Plan;
    if (plan.schema !== PLAN_SCHEMA || plan.chunk.index !== args.chunkIndex || plan.chunk.total !== args.chunkTotal ||
        plan.options.inputKind !== args.inputKind || plan.options.strength !== args.strength || plan.options.genre !== args.genre) {
      throw invalid('Sejong plan does not match the requested chunk and options');
    }
    return plan;
  }

  /** Apply/repair/verify/decide one attempt. Exit 0-2 return the report; exit 3 is an execution error. */
  async check(args: CheckArgs, signal: AbortSignal): Promise<CheckReport> {
    if ((args.response === undefined) === (args.candidate === undefined)) throw new Error('Pass exactly one of response and candidate');
    if (args.attempt === 2 && args.base === undefined) throw new Error('Attempt 2 needs the decided text of attempt 1');
    const source = path.resolve(args.source), report = path.resolve(args.report);
    const result = await this.run('check', [
      '--plan', path.resolve(args.plan), '--source', source,
      ...(args.response !== undefined ? ['--response', path.resolve(args.response)] : ['--candidate', path.resolve(args.candidate!)]),
      '--attempt', String(args.attempt),
      ...(args.base !== undefined ? ['--base', path.resolve(args.base)] : []),
      '--out', path.resolve(args.out), '--report', report
    ], path.dirname(source), signal);
    if (![0, 1, 2, 3].includes(result.exitCode)) throw invalid('Unexpected Sejong check exit code');
    // Exit 3 is the legacy "gate execution failed" status, which the legacy engine turns into VALIDATION_FAILED.
    if (result.exitCode === 3) throw new EngineError('VALIDATION_FAILED', false, 'Sejong check execution failed');
    const data = await this.readJson(report, 'check report');
    const problems = checkProblems(data, await this.schema('check'));
    if (problems.length) throw invalid(`Sejong check report is invalid: ${problems.slice(0, 3).join('; ')}`);
    const parsed = data as CheckReport;
    if (parsed.schema !== CHECK_SCHEMA || parsed.gate.exit_code !== result.exitCode) throw invalid('Gate report exit code mismatch');
    if (parsed.attempt !== args.attempt) throw invalid('Sejong check report is for another attempt');
    return parsed;
  }

  /** Legacy gate JSON on stdout (DESIGN 5.1 `verify`), mapped exactly as PythonEngine.verify() maps it. */
  async verifyDocument(before: string, after: string, signal: AbortSignal, attempt: 1 | 2 = 1, context?: string): Promise<GateResult> {
    const beforePath = path.resolve(before);
    const result = await this.run('verify', [
      '--before', beforePath, '--after', path.resolve(after),
      ...(context ? ['--context', path.resolve(context)] : []),
      '--attempt', String(attempt)
    ], path.dirname(beforePath), signal);
    if (![0, 1, 2, 3].includes(result.exitCode)) throw invalid('Unexpected gate exit code');
    const exitCode = result.exitCode as 0 | 1 | 2 | 3;
    const report = lastJsonObject(result.stdout, 'gate');
    if (integer(record(report.gate, 'gate report.gate').exit_code, 'gate report.gate.exit_code') !== exitCode) {
      throw invalid('Gate report exit code mismatch');
    }
    const reasons = report.warningReasons as Record<string, unknown> | undefined;
    const reasonCodes = reasons && typeof reasons === 'object' && !Array.isArray(reasons) && reasons.version === 1 &&
      Object.keys(reasons).sort().join(',') === 'codes,version' && Array.isArray(reasons.codes) &&
      new Set(reasons.codes).size === reasons.codes.length &&
      reasons.codes.every(code => (LEGACY_REASONS as readonly unknown[]).includes(code))
      ? reasons.codes as Array<typeof LEGACY_REASONS[number]>
      : undefined;
    if (report.policy !== undefined && report.policy !== gatePolicy(exitCode, attempt)) {
      throw invalid('Gate report policy differs from the legacy decision table');
    }
    const hard = report.hardFailures, shadow = report.shadowFailures;
    return {
      status: GATE_STATUS[exitCode],
      exitCode,
      gateCodes: [GATE_CODES[exitCode]],
      ...(reasonCodes ? { warningReasons: { version: 1 as const, codes: [...reasonCodes] } } : {}),
      ...(Array.isArray(hard) && hard.length <= 100 && hard.every(code => typeof code === 'string' && code.length <= 100)
        ? { hardFailures: hard as string[] } : {}),
      ...(Array.isArray(shadow) && shadow.length <= 100 && shadow.every(isSejongCode) ? { shadowFailures: shadow as string[] } : {}),
      ...(report.policy !== undefined ? { policy: report.policy as GatePolicy } : {})
    };
  }

  /** Reassemble + document verify + seam reverts; returns the path of 03_reassembled.md. */
  async finalize(runDir: string, signal: AbortSignal): Promise<string> {
    const dir = path.resolve(runDir);
    this.requireSuccess('finalize', await this.run('finalize', [
      '--run-dir', dir, '--output', '03_reassembled.md', '--report', '03_reassembly_report.json'
    ], dir, signal));
    const output = path.join(dir, '03_reassembled.md');
    try {
      if (!(await stat(output)).isFile()) throw new Error('not a file');
    } catch (error) {
      throw invalid('Reassembled output is missing', error);
    }
    return output;
  }
}
