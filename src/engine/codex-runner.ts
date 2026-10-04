import type { CandidateReview } from './candidate-review.js';
import { parseRewriteOptions, type RewriteOptions } from './rewrite-policy.js';
import { randomUUID } from "node:crypto";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { CommandRunner } from "../process/command-runner.js";
import { EngineError, engineFailed, modelUnavailable } from "./errors.js";
import {
  HUMANIZE_MODEL,
  HUMANIZE_REASONING_EFFORT
} from "./model-policy.js";
import { buildHumanizePrompt } from "./prompt-builder.js";
import type { ChunkPromptContext } from "./super-sejong.js";
import { parseTextResult } from './text-edits.js';
import { parseModelSettings, type ModelSettings } from './model-policy.js';

export interface CodexResult {
  fidelityIssues?: number;
  rewrittenText: string;
  warnings: string[];
}

export interface CodexPermitPool {
  readonly maxObserved: number;
  run<T>(signal: AbortSignal, task: () => Promise<T>): Promise<T>;
}

export interface CodexRunnerOptions {
  promptBuilder?: typeof buildHumanizePrompt;
  resultParser?: typeof parseEngineResult;
  codexCommand: string;
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

type ErrorLine = { status?: unknown; error?: { message?: unknown } };

// Codex prints an API rejection as `ERROR: {"status":400,"error":{"message":...}}`
// on stderr. Earlier lines can echo the prompt, so only the final ERROR line of a
// failed run decides.
function lastErrorLine(stderr: string): ErrorLine | undefined {
  const lines = stderr.split(/\r?\n/).filter(line => /^\s*ERROR\b/.test(line) && line.includes("{"));
  const line = lines.at(-1);
  if (!line) return undefined;
  try {
    const value: unknown = JSON.parse(line.slice(line.indexOf("{")));
    return typeof value === "object" && value !== null ? value as ErrorLine : undefined;
  } catch { return undefined; }
}

// Only a model-specific 400/404 becomes MODEL_UNAVAILABLE.
function modelRejection(exitCode: number, stderr: string): string | undefined {
  if (exitCode === 0) return undefined;
  const record = lastErrorLine(stderr);
  const message = record?.error?.message;
  if ((record?.status === 400 || record?.status === 404) && typeof message === "string" &&
    /\bmodel\b/i.test(message) && /not supported|does not exist|not found|unknown|unsupported|not available/i.test(message)) {
    return `status ${record.status}`;
  }
  return undefined;
}

// Only the exit code and the API status are logged, never CLI text.
function failureReason(exitCode: number, stderr: string): string {
  const status = lastErrorLine(stderr)?.status;
  return typeof status === "number" ? `exit ${exitCode}, status ${status}` : `exit ${exitCode}`;
}

export function parseEngineResult(raw: string, label = "Codex"): CodexResult {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch (error) {
    throw invalid(`${label} final output is not JSON`, error);
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw invalid(`${label} final output must be an object`);
  }
  const result = value as Record<string, unknown>;
  if (
    typeof result.rewrittenText !== "string" ||
    result.rewrittenText.trim().length === 0
  ) {
    throw invalid(`${label} rewrittenText must be a nonempty string`);
  }
  if (
    !Array.isArray(result.warnings) ||
    result.warnings.length > 20 ||
    result.warnings.some(
      warning => typeof warning !== "string" || warning.length > 300
    )
  ) {
    throw invalid(`${label} warnings must be a bounded string array`);
  }
  return {
    rewrittenText: result.rewrittenText,
    warnings: result.warnings as string[]
  };
}

export class CodexRunner {
  private readonly options: CodexRunnerOptions;
  private quickRulesPromise: Promise<string> | undefined;

  constructor(options: CodexRunnerOptions) {
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
    const selection = parseModelSettings('codex', settings?.model, settings?.effort);
    const resultPath = path.resolve(outputPath);
    const [source, quickRules] = await Promise.all([
      readFile(sourcePath, "utf8"),
      this.quickRules()
    ]);

    let nonce = randomUUID().replaceAll("-", "");
    while (
      source.includes(nonce) || candidateReview?.candidate.includes(nonce)
    ) {
      nonce = randomUUID().replaceAll("-", "");
    }
    const prompt = (this.options.promptBuilder ?? buildHumanizePrompt)({ source, quickRules, attempt, nonce, rewriteOptions: options, candidateReview, chunkContext });

    await this.exec(prompt, this.options.schemaPath, resultPath, signal, selection);

    try {
      const raw = await readFile(resultPath, "utf8");
      return this.options.resultParser ? this.options.resultParser(raw) : parseTextResult(raw, source, 'Codex', options);
    } catch (error) {
      if (error instanceof EngineError) throw error;
      throw invalid("Codex result file is missing", error);
    }
  }

  /** Super Sejong v2 (DESIGN 4.3, 5.2 SejongWriter): sends a ready prompt with the given output schema and
   * returns the final message unparsed; the caller validates it (sejong/response.ts). No rulebook is read. */
  async runPrompt(
    prompt: string,
    schemaPath: string,
    outputPath: string,
    signal: AbortSignal,
    settings?: ModelSettings
  ): Promise<string> {
    const selection = parseModelSettings('codex', settings?.model, settings?.effort);
    const resultPath = path.resolve(outputPath);
    await this.exec(prompt, path.resolve(schemaPath), resultPath, signal, selection);
    try {
      return await readFile(resultPath, "utf8");
    } catch (error) {
      throw invalid("Codex result file is missing", error);
    }
  }

  private async exec(
    prompt: string,
    schemaPath: string,
    resultPath: string,
    signal: AbortSignal,
    selection: ModelSettings
  ): Promise<void> {
    await rm(resultPath, { force: true });
    const isolatedCwd = await mkdtemp(path.join(os.tmpdir(), "humanize-codex-"));
    let command;
    try {
      command = await this.options.permitPool.run(signal, () =>
        this.options.runner.run({
        command: this.options.codexCommand,
        args: [
          "exec",
          "--ephemeral",
          "--skip-git-repo-check",
          "--ignore-user-config",
          "--ignore-rules",
          // The model receives untrusted document text and needs no host tools. Codex 0.160
          // accepts but ignores --disable unified_exec, so the read-only sandbox and the empty
          // working directory remain the actual containment.
          "--disable", "shell_tool",
          "--disable", "unified_exec",
          "--disable", "code_mode_host",
          "--disable", "view_image",
          "--disable", "browser_use",
          "--disable", "apps",
          "--disable", "computer_use",
          "--model",
          selection.model,
          "--config",
          `model_reasoning_effort="${selection.effort}"`,
          "--sandbox",
          "read-only",
          "--output-schema",
          schemaPath,
          "--output-last-message",
          resultPath,
          "-"
        ],
        cwd: isolatedCwd,
        stdin: prompt,
        timeoutMs: this.options.timeoutMs,
        signal,
        env: { ...process.env, NO_COLOR: "1" }
        })
      );
    } finally {
      await rm(isolatedCwd, { recursive: true, force: true });
    }

    if (command.termination === "timeout") {
      throw new EngineError("ENGINE_TIMEOUT", true, "Codex timed out");
    }
    if (command.termination === "aborted") {
      throw new EngineError("CLIENT_ABORTED", true, "Codex was cancelled");
    }
    if (command.termination === "output-limit") {
      throw engineFailed("Codex", "CLI output limit exceeded");
    }
    const rejection = modelRejection(command.exitCode, command.stderr);
    if (rejection) throw modelUnavailable("Codex", rejection);
    if (command.exitCode !== 0) {
      throw engineFailed("Codex", failureReason(command.exitCode, command.stderr));
    }
  }
}
