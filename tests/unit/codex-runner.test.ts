import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type {
  CommandRequest,
  CommandResult,
  CommandRunner
} from "../../src/process/command-runner.js";
import { CodexRunner } from "../../src/engine/codex-runner.js";
import {
  HUMANIZE_MODEL,
  HUMANIZE_REASONING_EFFORT
} from "../../src/engine/model-policy.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

class OutputRunner implements CommandRunner {
  request: CommandRequest | undefined;
  constructor(
    private readonly output: string,
    private readonly result: CommandResult = {
      exitCode: 0,
      stdout: "",
      stderr: "",
      termination: "exit"
    },
    private readonly onRun?: () => void
  ) {}

  async run(request: CommandRequest): Promise<CommandResult> {
    this.request = request;
    this.onRun?.();
    const outputFlag = request.args.indexOf("--output-last-message");
    if (outputFlag >= 0 && this.result.termination === "exit") {
      await writeFile(request.args[outputFlag + 1]!, this.output, "utf8");
    }
    return this.result;
  }
}

class TrackingPermitPool {
  readonly maxObserved = 1;
  active = 0;
  runs = 0;
  readonly events: string[] = [];

  async run<T>(_signal: AbortSignal, task: () => Promise<T>): Promise<T> {
    this.runs += 1;
    this.active += 1;
    this.events.push("permit-enter");
    try {
      return await task();
    } finally {
      this.active -= 1;
      this.events.push("permit-leave");
    }
  }
}

async function fixture(
  runner: CommandRunner,
  permitPool = new TrackingPermitPool()
): Promise<{
  root: string;
  inputPath: string;
  outputPath: string;
  schemaPath: string;
  quickRulesPath: string;
  permitPool: TrackingPermitPool;
  codex: CodexRunner;
}> {
  const root = await makeTestRoot();
  const inputPath = path.join(root, "input.txt");
  const outputPath = path.join(root, "output.json");
  const schemaPath = path.join(root, "schema.json");
  const quickRulesPath = path.join(root, "rules.md");
  await writeFile(inputPath, "원문은 1,200명을 언급한다.", "utf8");
  await writeFile(schemaPath, "{}", "utf8");
  await writeFile(quickRulesPath, "RULE-A", "utf8");
  const options = {
    codexCommand: "codex",
    schemaPath,
    quickRulesPath,
    timeoutMs: 600_000,
    runner,
    permitPool
  };
  return {
    root,
    inputPath,
    outputPath,
    schemaPath,
    quickRulesPath,
    permitPool,
    codex: new CodexRunner(options)
  };
}

describe("CodexRunner", () => {
  it("uses the approved fixed model policy", () => {
    expect(HUMANIZE_MODEL).toBe("gpt-6.1-sol");
    expect(HUMANIZE_REASONING_EFFORT).toBe("xhigh");
  });

  it("invokes isolated ephemeral Codex and returns schema-checked JSON", async () => {
    const runner = new OutputRunner(
      JSON.stringify({ rewrittenText: "원문은 1,200명을 말한다.", warnings: [] })
    );
    const test = await fixture(runner);
    try {
      const result = await test.codex.transform(
        test.inputPath,
        test.outputPath,
        1,
        new AbortController().signal
      );

      expect(result).toEqual({
        rewrittenText: "원문은 1,200명을 말한다.",
        warnings: []
      });
      expect(runner.request?.args).toEqual([
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable", "shell_tool",
        "--disable", "unified_exec",
        "--disable", "code_mode_host",
        "--disable", "view_image",
        "--disable", "browser_use",
        "--disable", "apps",
        "--disable", "computer_use",
        "--model",
        "gpt-6.1-sol",
        "--config",
        'model_reasoning_effort="xhigh"',
        "--sandbox",
        "read-only",
        "--output-schema",
        test.schemaPath,
        "--output-last-message",
        test.outputPath,
        "-"
      ]);
      expect(runner.request?.stdin).toContain("BEGIN_SOURCE_");
      expect(runner.request?.cwd).toContain('humanize-codex-');
      expect(await readFile(test.outputPath, "utf8")).toContain("rewrittenText");
    } finally {
      await removeTestRoot(test.root);
    }
  });

  it("runs first and retry subprocess attempts inside one permit each", async () => {
    const permitPool = new TrackingPermitPool();
    const runner = new OutputRunner(
      JSON.stringify({ rewrittenText: "rewritten", warnings: [] }),
      undefined,
      () => {
        expect(permitPool.active).toBe(1);
        permitPool.events.push("command-run");
      }
    );
    const test = await fixture(runner, permitPool);
    try {
      await test.codex.transform(
        test.inputPath,
        test.outputPath,
        1,
        new AbortController().signal
      );
      await test.codex.transform(
        test.inputPath,
        test.outputPath,
        2,
        new AbortController().signal
      );

      expect(permitPool.runs).toBe(2);
      expect(permitPool.active).toBe(0);
      expect(permitPool.events).toEqual([
        "permit-enter",
        "command-run",
        "permit-leave",
        "permit-enter",
        "command-run",
        "permit-leave"
      ]);
    } finally {
      await removeTestRoot(test.root);
    }
  });

  it("releases the permit when the command runner rejects", async () => {
    const permitPool = new TrackingPermitPool();
    const failure = new Error("command failed");
    const runner: CommandRunner = {
      async run() {
        expect(permitPool.active).toBe(1);
        permitPool.events.push("command-run");
        throw failure;
      }
    };
    const test = await fixture(runner, permitPool);
    try {
      await expect(
        test.codex.transform(
          test.inputPath,
          test.outputPath,
          1,
          new AbortController().signal
        )
      ).rejects.toBe(failure);
      expect(permitPool.runs).toBe(1);
      expect(permitPool.active).toBe(0);
      expect(permitPool.events).toEqual([
        "permit-enter",
        "command-run",
        "permit-leave"
      ]);
    } finally {
      await removeTestRoot(test.root);
    }
  });

  it("maps a rejected model to MODEL_UNAVAILABLE without echoing CLI text", async () => {
    // Real Codex 0.159.0 stderr for a model the ChatGPT login cannot use.
    const stderr = 'ERROR: {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The \'gpt-5.2\' model is not supported when using Codex with a ChatGPT account."}}\n';
    const test = await fixture({ run: async () => ({ exitCode: 1, stdout: "", stderr, termination: "exit" as const }) });
    try {
      const failure = await test.codex.transform(test.inputPath, test.outputPath, 1, new AbortController().signal).catch(error => error);
      expect(failure).toMatchObject({ publicCode: "MODEL_UNAVAILABLE", retryable: false });
      expect(failure.message).not.toContain("gpt-5.2");
    } finally {
      await removeTestRoot(test.root);
    }
  });

  it("maps other CLI failures to ENGINE_FAILED without echoing CLI text", async () => {
    for (const stderr of [
      'ERROR: {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"Input is too long."}}\n',
      'ERROR: {"type":"error","status":429,"error":{"message":"Rate limit reached"}}\n',
      // An earlier echoed model error does not decide the outcome; the last ERROR line does.
      'ERROR: {"status":400,"error":{"message":"The model does not exist"}}\nERROR: {"status":401,"error":{"message":"Unauthorized"}}\n'
    ]) {
      const test = await fixture({ run: async () => ({ exitCode: 1, stdout: "", stderr, termination: "exit" as const }) });
      try {
        const failure = await test.codex.transform(test.inputPath, test.outputPath, 1, new AbortController().signal).catch(error => error);
        expect(failure).toMatchObject({ publicCode: "ENGINE_FAILED", retryable: true });
        expect(failure.message).not.toMatch(/Rate limit|Unauthorized|too long/);
      } finally {
        await removeTestRoot(test.root);
      }
    }
  });

  it("ignores an echoed model error on a successful run", async () => {
    const stderr = 'user\n회사 "ERROR: {\\"status\\":400,\\"error\\":{\\"message\\":\\"The model is not supported\\"}}"\nERROR: {"status":400,"error":{"message":"The model is not supported"}}\n';
    const test = await fixture(new OutputRunner(JSON.stringify({ rewrittenText: "다듬은 문장입니다.", warnings: [] }),
      { exitCode: 0, stdout: "", stderr, termination: "exit" }));
    try {
      await expect(test.codex.transform(test.inputPath, test.outputPath, 1, new AbortController().signal))
        .resolves.toMatchObject({ rewrittenText: "다듬은 문장입니다." });
    } finally {
      await removeTestRoot(test.root);
    }
  });

  it("rejects malformed final JSON", async () => {
    const test = await fixture(new OutputRunner("not-json"));
    try {
      await expect(
        test.codex.transform(
          test.inputPath,
          test.outputPath,
          1,
          new AbortController().signal
        )
      ).rejects.toMatchObject({ publicCode: "ENGINE_OUTPUT_INVALID" });
    } finally {
      await removeTestRoot(test.root);
    }
  });

  it.each([
    ["timeout", "ENGINE_TIMEOUT"],
    ["aborted", "CLIENT_ABORTED"],
    ["output-limit", "ENGINE_FAILED"]
  ] as const)("maps %s termination to %s", async (termination, code) => {
    const test = await fixture(
      new OutputRunner("", {
        exitCode: -1,
        stdout: "",
        stderr: "",
        termination
      })
    );
    try {
      await expect(
        test.codex.transform(
          test.inputPath,
          test.outputPath,
          1,
          new AbortController().signal
        )
      ).rejects.toMatchObject({ publicCode: code });
    } finally {
      await removeTestRoot(test.root);
    }
  });

  it("rejects a blank rewrittenText even when JSON is valid", async () => {
    const test = await fixture(
      new OutputRunner(JSON.stringify({ rewrittenText: "   ", warnings: [] }))
    );
    try {
      await expect(
        test.codex.transform(
          test.inputPath,
          test.outputPath,
          1,
          new AbortController().signal
        )
      ).rejects.toMatchObject({ publicCode: "ENGINE_OUTPUT_INVALID" });
    } finally {
      await removeTestRoot(test.root);
    }
  });
});
