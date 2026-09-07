import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ClaudeRunner } from "../../src/engine/claude-runner.js";
import type { CodexPermitPool } from "../../src/engine/codex-runner.js";
import { EngineError } from "../../src/engine/errors.js";
import {
  CLAUDE_MODEL,
  CLAUDE_REASONING_EFFORT
} from "../../src/engine/model-policy.js";
import type { CommandResult } from "../../src/process/command-runner.js";
import {
  exited,
  FakeCommandRunner
} from "../helpers/fake-command-runner.js";

const SCHEMA_PATH = path.join(
  process.cwd(),
  "src",
  "engine",
  "output-schema.json"
);

let root: string;
let inputPath: string;
let outputPath: string;
let quickRulesPath: string;

beforeEach(async () => {
  root = await mkdtemp(path.join(tmpdir(), "claude-runner-"));
  inputPath = path.join(root, "chunk-source.txt");
  outputPath = path.join(root, "claude-result.json");
  quickRulesPath = path.join(root, "quick-rules.md");
  await writeFile(inputPath, "이 문장은 매우 자연스럽습니다.", "utf8");
  await writeFile(quickRulesPath, "- 번역투를 피한다", "utf8");
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

const directPool: CodexPermitPool = {
  maxObserved: 1,
  run: (_signal, task) => task()
};

function makeRunner(
  results: Array<CommandResult | Error>
): { runner: ClaudeRunner; fake: FakeCommandRunner } {
  const fake = new FakeCommandRunner(results);
  return {
    fake,
    runner: new ClaudeRunner({
      claudeCommand: "claude",
      schemaPath: SCHEMA_PATH,
      quickRulesPath,
      timeoutMs: 5000,
      runner: fake,
      permitPool: directPool
    })
  };
}

function envelope(result: unknown): string {
  return JSON.stringify({
    is_error: false,
    subtype: "success",
    result: typeof result === "string" ? result : JSON.stringify(result)
  });
}

describe("ClaudeRunner", () => {
  it("reads the native CLI structured_output response", async () => {
    const { runner } = makeRunner([exited(JSON.stringify({ is_error: false, subtype: "success", structured_output: { rewrittenText: "수치는 12명이다.", warnings: [] } }))]);
    expect(await runner.transform(inputPath, outputPath, 1, new AbortController().signal)).toEqual({ rewrittenText: "수치는 12명이다.", warnings: [] });
  });
  it("invokes the restricted Claude CLI and persists the parsed result", async () => {
    const { runner, fake } = makeRunner([
      exited(envelope({ rewrittenText: "다듬어진 문장", warnings: ["주의"] }))
    ]);

    const result = await runner.transform(
      inputPath,
      outputPath,
      1,
      new AbortController().signal
    );

    expect(result).toEqual({
      rewrittenText: "다듬어진 문장",
      warnings: ["주의"]
    });
    const call = fake.calls[0];
    expect(call.command).toBe("claude");
    expect(call.args).toEqual([
      "-p",
      "--restricted",
      "--strict-mcp-config",
      "--tools",
      "",
      "--no-session-persistence",
      "--model",
      CLAUDE_MODEL,
      "--effort",
      CLAUDE_REASONING_EFFORT,
      "--output-format",
      "json",
      "--json-schema",
      JSON.stringify(
        (({ $schema, ...rest }) => rest)(
          JSON.parse(await readFile(SCHEMA_PATH, "utf8"))
        )
      )
    ]);
    expect(call.args.at(-1)).not.toContain("$schema");
    expect(call.stdin).toContain("이 문장은 매우 자연스럽습니다.");
    expect(call.stdin).toContain("번역투를 피한다");
    expect(call.cwd).toBe(root);
    expect(JSON.parse(await readFile(outputPath, "utf8"))).toEqual(result);
  });

  it("adds the conservative retry instruction on attempt 2", async () => {
    const { runner, fake } = makeRunner([
      exited(envelope({ rewrittenText: "결과", warnings: [] }))
    ]);
    await runner.transform(
      inputPath,
      outputPath,
      2,
      new AbortController().signal
    );
    expect(fake.calls[0].stdin).toContain("재시도 1회");
  });

  it("maps a nonzero exit to ENGINE_OUTPUT_INVALID", async () => {
    const { runner } = makeRunner([exited("", 1, "boom")]);
    await expect(
      runner.transform(inputPath, outputPath, 1, new AbortController().signal)
    ).rejects.toMatchObject({
      publicCode: "ENGINE_OUTPUT_INVALID",
      retryable: false
    });
  });

  it("maps a CLI error envelope to ENGINE_OUTPUT_INVALID", async () => {
    const { runner } = makeRunner([
      exited(
        JSON.stringify({
          is_error: true,
          subtype: "error_during_execution",
          result: "실패"
        })
      )
    ]);
    await expect(
      runner.transform(inputPath, outputPath, 1, new AbortController().signal)
    ).rejects.toMatchObject({ publicCode: "ENGINE_OUTPUT_INVALID" });
  });

  it("rejects a result that violates the output contract", async () => {
    const { runner } = makeRunner([
      exited(envelope({ rewrittenText: "   ", warnings: [] }))
    ]);
    const failure = await runner
      .transform(inputPath, outputPath, 1, new AbortController().signal)
      .catch(error => error);
    expect(failure).toBeInstanceOf(EngineError);
    expect(failure.publicCode).toBe("ENGINE_OUTPUT_INVALID");
  });

  it("maps a timeout termination to ENGINE_TIMEOUT", async () => {
    const { runner } = makeRunner([
      { exitCode: -1, stdout: "", stderr: "", termination: "timeout" }
    ]);
    await expect(
      runner.transform(inputPath, outputPath, 1, new AbortController().signal)
    ).rejects.toMatchObject({ publicCode: "ENGINE_TIMEOUT", retryable: true });
  });

  it("maps an aborted termination to CLIENT_ABORTED", async () => {
    const { runner } = makeRunner([
      { exitCode: -1, stdout: "", stderr: "", termination: "aborted" }
    ]);
    await expect(
      runner.transform(inputPath, outputPath, 1, new AbortController().signal)
    ).rejects.toMatchObject({ publicCode: "CLIENT_ABORTED", retryable: true });
  });
});
