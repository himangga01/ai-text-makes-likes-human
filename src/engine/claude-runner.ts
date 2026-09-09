import { randomUUID } from "node:crypto";
import { readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import type { CommandRunner } from "../process/command-runner.js";
import {
  parseEngineResult,
  type CodexPermitPool,
  type CodexResult
} from "./codex-runner.js";
import { EngineError } from "./errors.js";
import { CLAUDE_MODEL, CLAUDE_REASONING_EFFORT } from "./model-policy.js";
import { buildHumanizePrompt } from "./prompt-builder.js";
import { parseTextResult } from './text-edits.js';
import { parseModelSettings, type ModelSettings } from './model-policy.js';

export interface ClaudeRunnerOptions {
  promptBuilder?: typeof buildHumanizePrompt;
  resultParser?: typeof parseEngineResult;
  claudeCommand: string;
  schemaPath: string;
  quickRulesPath: string;
  timeoutMs: number;
  runner: CommandRunner;
  permitPool: CodexPermitPool;
}

function invalid(message: string, cause?: unknown): EngineError {
  return new EngineError("ENGINE_OUTPUT_INVALID", false, message, { cause });
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
  if (record.is_error !== false || record.subtype !== "success") {
    throw invalid(
      `Claude CLI reported failure (subtype: ${String(record.subtype)})`
    );
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
  private schemaPromise: Promise<string> | undefined;

  constructor(options: ClaudeRunnerOptions) {
    this.options = {
      ...options,
      schemaPath: path.resolve(options.schemaPath),
      quickRulesPath: path.resolve(options.quickRulesPath)
    };
  }

  private quickRules(): Promise<string> {
    this.quickRulesPromise ??= readFile(this.options.quickRulesPath, "utf8");
    return this.quickRulesPromise;
  }

  private schema(): Promise<string> {
    this.schemaPromise ??= readFile(this.options.schemaPath, "utf8").then(
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
    return this.schemaPromise;
  }

  async transform(
    inputPath: string,
    outputPath: string,
    attempt: 1 | 2,
    signal: AbortSignal,
    settings?: ModelSettings
  ): Promise<CodexResult> {
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
      source.includes(`BEGIN_SOURCE_${nonce}`) ||
      source.includes(`END_SOURCE_${nonce}`)
    ) {
      nonce = randomUUID().replaceAll("-", "");
    }
    const prompt = (this.options.promptBuilder ?? buildHumanizePrompt)({ source, quickRules, attempt, nonce });

    await rm(resultPath, { force: true });
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
        cwd: path.dirname(sourcePath),
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
    if (command.exitCode !== 0) {
      throw invalid("Claude exited without a valid result");
    }

    const raw = extractResultText(command.stdout);
    const result = this.options.resultParser ? this.options.resultParser(raw, 'Claude') : parseTextResult(raw, source, 'Claude');
    await writeFile(resultPath, JSON.stringify(result), "utf8");
    return result;
  }
}
