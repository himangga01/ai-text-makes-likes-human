import { randomUUID } from "node:crypto";
import { readFile, rm } from "node:fs/promises";
import path from "node:path";
import type { CommandRunner } from "../process/command-runner.js";
import { EngineError } from "./errors.js";
import {
  HUMANIZE_MODEL,
  HUMANIZE_REASONING_EFFORT
} from "./model-policy.js";
import { buildHumanizePrompt } from "./prompt-builder.js";

export interface CodexResult {
  rewrittenText: string;
  warnings: string[];
}

export interface CodexRunnerOptions {
  codexCommand: string;
  schemaPath: string;
  quickRulesPath: string;
  timeoutMs: number;
  runner: CommandRunner;
}

function invalid(message: string, cause?: unknown): EngineError {
  return new EngineError("ENGINE_OUTPUT_INVALID", false, message, { cause });
}

function parseResult(raw: string): CodexResult {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch (error) {
    throw invalid("Codex final output is not JSON", error);
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw invalid("Codex final output must be an object");
  }
  const result = value as Record<string, unknown>;
  if (
    typeof result.rewrittenText !== "string" ||
    result.rewrittenText.trim().length === 0
  ) {
    throw invalid("Codex rewrittenText must be a nonempty string");
  }
  if (
    !Array.isArray(result.warnings) ||
    result.warnings.length > 20 ||
    result.warnings.some(
      warning => typeof warning !== "string" || warning.length > 300
    )
  ) {
    throw invalid("Codex warnings must be a bounded string array");
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
      quickRulesPath: path.resolve(options.quickRulesPath)
    };
  }

  private quickRules(): Promise<string> {
    this.quickRulesPromise ??= readFile(this.options.quickRulesPath, "utf8");
    return this.quickRulesPromise;
  }

  async transform(
    inputPath: string,
    outputPath: string,
    attempt: 1 | 2,
    signal: AbortSignal
  ): Promise<CodexResult> {
    const sourcePath = path.resolve(inputPath);
    const resultPath = path.resolve(outputPath);
    const [source, quickRules] = await Promise.all([
      readFile(sourcePath, "utf8"),
      this.quickRules()
    ]);

    let nonce = randomUUID().replaceAll("-", "");
    while (
      source.includes(`BEGIN_SOURCE_${nonce}`) ||
      source.includes(`END_SOURCE_${nonce}`)
    ) {
      nonce = randomUUID().replaceAll("-", "");
    }
    const prompt = buildHumanizePrompt({ source, quickRules, attempt, nonce });

    await rm(resultPath, { force: true });
    const command = await this.options.runner.run({
      command: this.options.codexCommand,
      args: [
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--model",
        HUMANIZE_MODEL,
        "--config",
        `model_reasoning_effort="${HUMANIZE_REASONING_EFFORT}"`,
        "--sandbox",
        "read-only",
        "--output-schema",
        this.options.schemaPath,
        "--output-last-message",
        resultPath,
        "-"
      ],
      cwd: path.dirname(sourcePath),
      stdin: prompt,
      timeoutMs: this.options.timeoutMs,
      signal,
      env: { ...process.env, NO_COLOR: "1" }
    });

    if (command.termination === "timeout") {
      throw new EngineError("ENGINE_TIMEOUT", true, "Codex timed out");
    }
    if (command.termination === "aborted") {
      throw new EngineError("CLIENT_ABORTED", true, "Codex was cancelled");
    }
    if (command.exitCode !== 0) {
      throw invalid("Codex exited without a valid result");
    }

    try {
      return parseResult(await readFile(resultPath, "utf8"));
    } catch (error) {
      if (error instanceof EngineError) throw error;
      throw invalid("Codex result file is missing", error);
    }
  }
}
