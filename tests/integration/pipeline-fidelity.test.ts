import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { CodexRunner } from "../../src/engine/codex-runner.js";
import { HumanizeEngine, type CodexAdapter } from "../../src/engine/humanize-engine.js";
import { PythonEngine } from "../../src/engine/python-engine.js";
import type { RewriteOptions } from "../../src/engine/rewrite-policy.js";
import { JobWorkspace } from "../../src/engine/workspace.js";
import type { CommandRequest } from "../../src/process/command-runner.js";
import { SpawnCommandRunner } from "../../src/process/command-runner.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";
import { pythonCommand } from "../helpers/python-command.js";

const python = () => new PythonEngine({
  pythonCommand,
  vendorRoot: path.resolve("vendor/humanize-engine"),
  runner: new SpawnCommandRunner()
});

async function run(source: string, codex: CodexAdapter, rewriteOptions?: RewriteOptions) {
  const outer = await makeTestRoot();
  const workspace = await JobWorkspace.create(outer, "pipeline-fidelity");
  try {
    await writeFile(workspace.path("01_input.txt"), source, "utf8");
    const engine = new HumanizeEngine({ python: python(), codex, chunkConcurrency: 1 });
    const result = await engine.transform({
      jobId: workspace.jobId,
      workspace,
      signal: new AbortController().signal,
      onEvent: () => undefined,
      rewriteOptions
    });
    return { output: await readFile(result.finalPath, "utf8"), result };
  } finally {
    await workspace.cleanup();
    await removeTestRoot(outer);
  }
}

const rewriting = (rewrite: (text: string, attempt: 1 | 2) => string): CodexAdapter => ({
  async transform(inputPath, _outputPath, attempt) {
    return { rewrittenText: rewrite(await readFile(inputPath, "utf8"), attempt), warnings: [] };
  }
});

const paragraph = [
  "우리 팀은 지난 분기에 새로운 협업 방식을 도입하였다.",
  "처음에는 낯선 도구 때문에 혼란이 있었지만 곧 익숙해졌다.",
  "회의 시간은 눈에 띄게 줄었고 결정은 더 빨라졌다.",
  "대표는 이 변화를 조직 전체로 확대하겠다고 발표하였다.",
  "다른 부서도 비슷한 방식을 시험해 보기로 하였다.",
  "우리는 이 경험을 문서로 정리해 공유하였다."
].join(" ");
const source = `${paragraph}\n\n두 번째 문단도 있다. 이 문단은 결론을 담는다.\n`;
const dropSentence = (text: string) => text.replace(" 대표는 이 변화를 조직 전체로 확대하겠다고 발표하였다.", "");
const duplicateSentence = (text: string) => text.replace("두 번째 문단도 있다.", "두 번째 문단도 있다. 두 번째 문단도 있다.");

describe("structural guard for every input kind", () => {
  it.each([
    ["text-file", { inputKind: "text-file", strength: "normal" } as RewriteOptions],
    ["legacy request without input kind", undefined]
  ])("rolls back a dropped sentence for %s", async (_label, options) => {
    // File inputs may split or merge sentences, so the Python sentence_dropped gate
    // (not a sentence count) catches the loss.
    const { output, result } = await run(source, rewriting(dropSentence), options);
    expect(output).toBe(source);
    expect(result.warnings.map(warning => warning.code)).toEqual(
      expect.arrayContaining(["CHUNK_RETRY", "CHUNK_ROLLED_BACK"])
    );
  });

  it.each([
    ["a rulebook split", (text: string) => text.replace("혼란이 있었지만 곧", "혼란이 있었다. 하지만 곧")],
    ["an ellipsis respelling", (text: string) => text.replace("결론을 담는다.", "결론을 담는다...")]
  ])("keeps %s in a text file", async (_label, edit) => {
    const { output, result } = await run(source, rewriting(edit), { inputKind: "text-file", strength: "normal" });
    expect(output).toBe(edit(source));
    expect(result.diagnostics.retries).toBe(0);
  });

  it("rolls back a duplicated sentence in a text file", async () => {
    const { output } = await run(source, rewriting(duplicateSentence), { inputKind: "text-file", strength: "normal" });
    expect(output).toBe(source);
  });

  it("keeps a structure-preserving text-file rewrite", async () => {
    const { output, result } = await run(source, rewriting(text => text.replace("공유하였다", "공유했다")), { inputKind: "text-file", strength: "normal" });
    expect(output).toBe(source.replace("공유하였다", "공유했다"));
    expect(result.diagnostics.retries).toBe(0);
  });

  it("rejects output that echoes the prompt source boundary", async () => {
    const leak = (text: string) => `BEGIN_SOURCE_${"a".repeat(32)}\n${text}`;
    const { output, result } = await run(source, rewriting(leak), { inputKind: "text-file", strength: "normal" });
    expect(output).toBe(source);
    expect(result.warnings.map(warning => warning.code)).toContain("CHUNK_ROLLED_BACK");
  });
});

describe("chunk whitespace normalization", () => {
  it("accepts a full-text rewrite whose trailing newline was trimmed", async () => {
    const text = "우리는 새로운 방식을 도입하였다. 이 방식은 팀의 협업을 강화하였다.\n";
    const edit = (value: string) => value.replace("도입하였다", "도입했다").replace("강화하였다", "강화했다");
    const { output, result } = await run(text, rewriting(value => edit(value).trimEnd()), { inputKind: "direct-text", strength: "medium" });
    expect(output).toBe(edit(text));
    expect(result.diagnostics.retries).toBe(0);
    expect(result.warnings.map(warning => warning.code)).not.toContain("DIRECT_TEXT_FIDELITY_RESTRICTED");
  });
});

describe("invalid model output for one chunk", () => {
  const text = "회의는 3시에 열렸다. 우리는 결과를 정리하였다. 우리는 결과를 공유하였다.\n";
  const codexWith = (payloads: object[]) => {
    const calls: CommandRequest[] = [];
    const runner = {
      async run(request: CommandRequest) {
        calls.push(request);
        const payload = payloads[calls.length - 1] ?? payloads.at(-1)!;
        await writeFile(request.args[request.args.indexOf("--output-last-message") + 1]!, JSON.stringify(payload));
        return { exitCode: 0, termination: "exit" as const, stdout: "", stderr: "" };
      }
    };
    const codex = new CodexRunner({
      codexCommand: "codex",
      schemaPath: path.resolve("src/engine/output-schema.json"),
      quickRulesPath: path.resolve("vendor/humanize-engine/skills/humanize-korean/references/quick-rules.md"),
      timeoutMs: 1000,
      runner,
      permitPool: { maxObserved: 1, run: (_signal, task) => task() }
    });
    return { codex, calls };
  };

  it("rolls the chunk back when the retry returns an ambiguous edit", async () => {
    const { codex, calls } = codexWith([
      { rewrittenText: "", edits: [{ before: "3시에", after: "4시에" }], warnings: [] },
      { rewrittenText: "", edits: [{ before: "우리는 결과를", after: "우리는 그 결과를" }], warnings: [] }
    ]);
    const { output, result } = await run(text, codex, { inputKind: "text-file", strength: "normal" });
    expect(calls).toHaveLength(2);
    expect(output).toBe(text);
    expect(result.warnings.map(warning => warning.code)).toEqual(
      expect.arrayContaining(["MODEL_OUTPUT_UNUSABLE", "CHUNK_ROLLED_BACK"])
    );
  });

  it("retries when the first attempt returns an ambiguous edit", async () => {
    const { codex, calls } = codexWith([
      { rewrittenText: "", edits: [{ before: "우리는 결과를", after: "우리는 그 결과를" }], warnings: [] },
      { rewrittenText: "", edits: [{ before: "정리하였다", after: "정리했다" }], warnings: [] }
    ]);
    const { output, result } = await run(text, codex, { inputKind: "text-file", strength: "normal" });
    expect(calls).toHaveLength(2);
    expect(output).toBe(text.replace("정리하였다", "정리했다"));
    expect(result.diagnostics.retries).toBe(1);
  });

  const failingCodex = (result: { exitCode: number; termination: "exit" | "timeout"; stderr?: string }) => {
    const calls: number[] = [];
    const runner = { async run() { calls.push(1); return { stdout: "", stderr: "", ...result }; } };
    const codex = new CodexRunner({
      codexCommand: "codex",
      schemaPath: path.resolve("src/engine/output-schema.json"),
      quickRulesPath: path.resolve("vendor/humanize-engine/skills/humanize-korean/references/quick-rules.md"),
      timeoutMs: 1000,
      runner,
      permitPool: { maxObserved: 1, run: (_signal, task) => task() }
    });
    return { codex, calls };
  };

  it("fails the job on a timeout after one call", async () => {
    const { codex, calls } = failingCodex({ exitCode: -1, termination: "timeout" });
    await expect(run(text, codex, { inputKind: "text-file", strength: "normal" })).rejects.toMatchObject({ publicCode: "ENGINE_TIMEOUT" });
    expect(calls).toHaveLength(1);
  });

  it.each([
    ["usage limit", 'ERROR: {"type":"error","status":429,"error":{"message":"Rate limit reached"}}\n'],
    ["expired login", 'ERROR: {"type":"error","status":401,"error":{"message":"Unauthorized"}}\n']
  ])("fails the job instead of returning the source on a CLI %s", async (_label, stderr) => {
    const { codex, calls } = failingCodex({ exitCode: 1, termination: "exit", stderr });
    await expect(run(text, codex, { inputKind: "text-file", strength: "normal" })).rejects.toMatchObject({ publicCode: "ENGINE_FAILED" });
    expect(calls).toHaveLength(1);
  });

  it("fails the job when every chunk's replies were unusable", async () => {
    const ambiguous = { rewrittenText: "", edits: [{ before: "우리는 결과를", after: "우리는 그 결과를" }], warnings: [] };
    const { codex, calls } = codexWith([ambiguous, ambiguous]);
    await expect(run(text, codex, { inputKind: "text-file", strength: "normal" })).rejects.toMatchObject({ publicCode: "ENGINE_OUTPUT_INVALID" });
    expect(calls).toHaveLength(2);
  });

  it("reports unusable replies and rollbacks in diagnostics for every input kind", async () => {
    const { codex } = codexWith([
      { rewrittenText: "", edits: [{ before: "3시에", after: "4시에" }], warnings: [] },
      { rewrittenText: "", edits: [{ before: "우리는 결과를", after: "우리는 그 결과를" }], warnings: [] }
    ]);
    const { result } = await run(text, codex, { inputKind: "text-file", strength: "normal" });
    expect(result.diagnostics).toMatchObject({ unusableModelOutputs: 1, rolledBackChunks: 1 });
  });
});
