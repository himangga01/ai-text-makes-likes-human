import type { CandidateReview } from './candidate-review.js';
import { parseRewriteOptions, type RewriteOptions } from './rewrite-policy.js';
import { randomUUID } from "node:crypto";
import { readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import type { CommandRunner } from "../process/command-runner.js";
import {
  parseEngineResult,
  type CodexPermitPool,
  type CodexResult
} from "./codex-runner.js";
import { EngineError, engineFailed, modelUnavailable } from "./errors.js";
import { CLAUDE_MODEL, CLAUDE_REASONING_EFFORT } from "./model-policy.js";
import { buildHumanizePrompt } from "./prompt-builder.js";
import type { ChunkPromptContext } from "./super-sejong.js";
import { parseTextResult } from './text-edits.js';
import { parseModelSettings, type ModelSettings } from './model-policy.js';

export interface ClaudeRunnerOptions {
  promptBuilder?: typeof buildHumanizePrompt;
  resultParser?: typeof parseEngineResult;
  claudeCommand: string;
  schemaPath: string;
  /** Legacy rulebook sent by transform(); runPrompt (Super Sejong v2) sends none and does not need it. */
  quickRulesPath?: string;
  timeoutMs: number;
  runner: CommandRunner;
  permitPool: CodexPermitPool;
}

function invalid(message: string, cause?: unknown): EngineError {
  return new EngineError("ENGINE_OUTPUT_INVALID", false, message, { cause });
}

function envelopeOf(stdout: string): Record<string, unknown> | undefined {
  try {
    const value: unknown = JSON.parse(stdout);
    return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
  } catch { return undefined; }
}

// Claude Code rejects an unknown or unauthorized model with exit 1, an
// `unrecognized_model` stderr tag and/or an error envelope carrying the API status.
// A successful run can print the same tag as a warning (its local catalog lacks
// the model but the API accepts it), so only a failed run is inspected.
function modelRejection(exitCode: number, stdout: string, stderr: string): string | undefined {
  const record = envelopeOf(stdout);
  if (exitCode === 0 && record?.is_error !== true) return undefined;
  if (stderr.includes("[claude-code:unrecognized_model]")) return "unrecognized_model";
  if (!record) return undefined;
  const status = record.api_error_status;
  if (record.is_error !== true || typeof record.result !== "string" || !/\bmodel\b/i.test(record.result)) return undefined;
  if (status === 400 || status === 404) return `api_error_status ${status}`;
  return record.terminal_reason === "api_error" && status === undefined ? "api_error" : undefined;
}

// Only fields the CLI fills itself are logged, never its result text.
function failureReason(exitCode: number, stdout: string): string {
  const record = envelopeOf(stdout), parts = [`exit ${exitCode}`];
  for (const key of ["subtype", "terminal_reason"]) {
    const value = record?.[key];
    if (typeof value === "string" && /^[a-z_]{1,40}$/.test(value) && value !== "success") parts.push(`${key} ${value}`);
  }
  if (typeof record?.api_error_status === "number") parts.push(`api_error_status ${record.api_error_status}`);
  return parts.join(", ");
}

function extractResultText(stdout: string): string {
  let envelope: unknown;
  try {
    envelope = JSON.parse(stdout);
  } catch (error) {
    throw invalid("Claude CLI output is not JSON", error);
  }
  if (
    typeof envelope !== "object" ||
    envelope === null ||
    Array.isArray(envelope)
  ) {
    throw invalid("Claude CLI output must be an object");
  }
  const record = envelope as Record<string, unknown>;
  if (record.is_error === true || (typeof record.subtype === "string" && record.subtype !== "success")) {
    throw engineFailed("Claude", failureReason(0, stdout));
  }
  if (record.is_error !== false || record.subtype !== "success") {
    throw invalid("Claude CLI envelope is malformed");
  }
  if (record.structured_output && typeof record.structured_output === "object") return JSON.stringify(record.structured_output);
  if (typeof record.result !== "string" || record.result.length === 0) {
    throw invalid("Claude CLI result is missing");
  }
  return record.result;
}

export class ClaudeRunner {
  private readonly options: ClaudeRunnerOptions;
  private quickRulesPromise: Promise<string> | undefined;
  /** Inline schema text per schema file: the legacy output schema and the v2 response schema. */
  private readonly schemaPromises = new Map<string, Promise<string>>();

  constructor(options: ClaudeRunnerOptions) {
    this.options = {
      ...options,
      schemaPath: path.resolve(options.schemaPath),
      ...(options.quickRulesPath === undefined ? {} : { quickRulesPath: path.resolve(options.quickRulesPath) })
    };
  }

  private quickRules(): Promise<string> {
    const rulesPath = this.options.quickRulesPath;
    if (rulesPath === undefined) return Promise.reject(new Error("The legacy prompt needs quickRulesPath"));
    this.quickRulesPromise ??= readFile(rulesPath, "utf8");
    return this.quickRulesPromise;
  }

  private schema(schemaPath: string = this.options.schemaPath): Promise<string> {
    let loaded = this.schemaPromises.get(schemaPath);
    if (!loaded) {
      loaded = readFile(schemaPath, "utf8").then(
        raw => {
          // Claude CLI의 스키마 검증기는 $schema 선언(draft 2020-12)을 거부한다.
          const { $schema, ...schema } = JSON.parse(raw) as Record<
            string,
            unknown
          >;
          void $schema;
          return JSON.stringify(schema);
        }
      );
      this.schemaPromises.set(schemaPath, loaded);
    }
    return loaded;
  }

  async transform(
    inputPath: string,
    outputPath: string,
    attempt: 1 | 2,
    signal: AbortSignal,
    settings?: ModelSettings,
    rewriteOptions?: RewriteOptions,
    candidateReview?: CandidateReview,
    chunkContext?: ChunkPromptContext
  ): Promise<CodexResult> {
    const options = parseRewriteOptions(rewriteOptions?.inputKind, rewriteOptions?.strength);
    const sourcePath = path.resolve(inputPath);
    const selection = parseModelSettings('claude', settings?.model, settings?.effort);
    const resultPath = path.resolve(outputPath);
    const [source, quickRules, schema] = await Promise.all([
      readFile(sourcePath, "utf8"),
      this.quickRules(),
      this.schema()
    ]);

    let nonce = randomUUID().replaceAll("-", "");
    while (
      source.includes(nonce) || candidateReview?.candidate.includes(nonce)
    ) {
      nonce = randomUUID().replaceAll("-", "");
    }
    const prompt = (this.options.promptBuilder ?? buildHumanizePrompt)({ source, quickRules, attempt, nonce, rewriteOptions: options, candidateReview, chunkContext });

    await rm(resultPath, { force: true });
    const raw = await this.exec(prompt, schema, path.dirname(sourcePath), signal, selection);
    const result = this.options.resultParser ? this.options.resultParser(raw, 'Claude') : parseTextResult(raw, source, 'Claude', options);
    await writeFile(resultPath, JSON.stringify(result), "utf8");
    return result;
  }

  /** Super Sejong v2 (DESIGN 4.3, 5.2 SejongWriter): sends a ready prompt with the given output schema and
   * returns the structured reply unparsed (also written to outputPath); the caller validates it
   * (sejong/response.ts). No rulebook is read. */
  async runPrompt(
    prompt: string,
    schemaPath: string,
    outputPath: string,
    signal: AbortSignal,
    settings?: ModelSettings
  ): Promise<string> {
    const selection = parseModelSettings('claude', settings?.model, settings?.effort);
    const resultPath = path.resolve(outputPath);
    const schema = await this.schema(path.resolve(schemaPath));
    await rm(resultPath, { force: true });
    const raw = await this.exec(prompt, schema, path.dirname(resultPath), signal, selection);
    await writeFile(resultPath, raw, "utf8");
    return raw;
  }

  private async exec(
    prompt: string,
    schema: string,
    cwd: string,
    signal: AbortSignal,
    selection: ModelSettings
  ): Promise<string> {
    const command = await this.options.permitPool.run(signal, () =>
      this.options.runner.run({
        command: this.options.claudeCommand,
        args: [
          "-p",
          "--restricted",
          "--strict-mcp-config",
          "--tools",
          "",
          "--no-session-persistence",
          "--model",
          selection.model,
          "--effort",
          selection.effort,
          "--output-format",
          "json",
          "--json-schema",
          schema
        ],
        cwd,
        stdin: prompt,
        timeoutMs: this.options.timeoutMs,
        signal,
        env: { ...process.env, NO_COLOR: "1" }
      })
    );

    if (command.termination === "timeout") {
      throw new EngineError("ENGINE_TIMEOUT", true, "Claude timed out");
    }
    if (command.termination === "aborted") {
      throw new EngineError("CLIENT_ABORTED", true, "Claude was cancelled");
    }
    if (command.termination === "output-limit") {
      throw engineFailed("Claude", "CLI output limit exceeded");
    }
    const rejection = modelRejection(command.exitCode, command.stdout, command.stderr);
    if (rejection) throw modelUnavailable("Claude", rejection);
    if (command.exitCode !== 0) {
      throw engineFailed("Claude", failureReason(command.exitCode, command.stdout));
    }

    return extractResultText(command.stdout);
  }
}
