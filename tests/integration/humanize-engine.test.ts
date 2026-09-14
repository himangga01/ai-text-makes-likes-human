import { copyFile, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type { CodexAdapter } from "../../src/engine/humanize-engine.js";
import { HumanizeEngine } from "../../src/engine/humanize-engine.js";
import {
  CLAUDE_MODEL,
  CLAUDE_REASONING_EFFORT,
  HUMANIZE_MODEL,
  HUMANIZE_REASONING_EFFORT
} from "../../src/engine/model-policy.js";
import { PythonEngine } from "../../src/engine/python-engine.js";
import { JobWorkspace } from "../../src/engine/workspace.js";
import { SpawnCommandRunner } from "../../src/process/command-runner.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";
import { pythonCommand } from "../helpers/python-command.js";

class IdentityCodex implements CodexAdapter {
  async transform(inputPath: string) {
    return { rewrittenText: await readFile(inputPath, "utf8"), warnings: [] };
  }
}

describe("HumanizeEngine integration", () => {
  it.each([
    { model: HUMANIZE_MODEL, reasoningEffort: HUMANIZE_REASONING_EFFORT },
    { model: CLAUDE_MODEL, reasoningEffort: CLAUDE_REASONING_EFFORT }
  ])("restores lost hedges while retaining $model diagnostics", async options => {
    const outer = await makeTestRoot();
    const workspace = await JobWorkspace.create(outer, "model-restore");
    try {
      const source =
        "이 수치는 낮은 것으로 판단된다. 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.\n";
      await writeFile(workspace.path("01_input.txt"), source, "utf8");
      const engine = new HumanizeEngine({
        ...options,
        python: new PythonEngine({
          pythonCommand,
          vendorRoot: path.resolve("vendor/humanize-engine"),
          runner: new SpawnCommandRunner()
        }),
        codex: {
          async transform(inputPath) {
            const text = await readFile(inputPath, "utf8");
            return {
              rewrittenText: text.replace("낮은 것으로 판단된다", "낮은 수치다"),
              warnings: []
            };
          }
        },
        chunkConcurrency: 1
      });
      const result = await engine.transform({
        jobId: workspace.jobId,
        workspace,
        signal: new AbortController().signal,
        onEvent: () => undefined
      });

      expect(await readFile(result.finalPath, "utf8")).toBe(source);
      expect(result.diagnostics).toMatchObject({
        ...options,
        restoredSentences: 1,
        removedCommas: 0
      });
      expect(result.warnings).toContainEqual(
        expect.objectContaining({ code: "MODALITY_RESTORED" })
      );
    } finally {
      await workspace.cleanup();
      await removeTestRoot(outer);
    }
  });

  it("preserves protected anchors through real prepare, gate, and reassembly", async () => {
    const outer = await makeTestRoot();
    const workspace = await JobWorkspace.create(outer, "integration-job");
    try {
      await copyFile(
        path.resolve("tests/fixtures/short-korean.txt"),
        workspace.path("01_input.txt")
      );
      const engine = new HumanizeEngine({
        python: new PythonEngine({
          pythonCommand,
          vendorRoot: path.resolve("vendor/humanize-engine"),
          runner: new SpawnCommandRunner()
        }),
        codex: new IdentityCodex(),
        chunkConcurrency: 1
      });

      const result = await engine.transform({
        jobId: workspace.jobId,
        workspace,
        signal: new AbortController().signal,
        onEvent: () => undefined
      });
      const output = await readFile(result.finalPath, "utf8");

      expect(output).toContain("1,200명");
      expect(output).toContain("OpenAI");
      expect(output).toContain("# 테스트 문서");
      expect(output).toBe(await readFile(workspace.path("01_input.txt"), "utf8"));
    } finally {
      await workspace.cleanup();
      await removeTestRoot(outer);
    }
  });

  it("round-trips astral characters byte-for-byte through the real engine", async () => {
    const outer = await makeTestRoot();
    const workspace = await JobWorkspace.create(outer, "integration-astral");
    try {
      const source =
        "# 이모지 문서\n\n이 문서는 이모지 😀 를 포함한다. 수치 1,200은 유지한다.\n\n둘째 문단이다. 😀 마지막 문장이다.\n";
      await writeFile(workspace.path("01_input.txt"), source, "utf8");
      const engine = new HumanizeEngine({
        python: new PythonEngine({
          pythonCommand,
          vendorRoot: path.resolve("vendor/humanize-engine"),
          runner: new SpawnCommandRunner()
        }),
        codex: new IdentityCodex(),
        chunkConcurrency: 1
      });

      const result = await engine.transform({
        jobId: workspace.jobId,
        workspace,
        signal: new AbortController().signal,
        onEvent: () => undefined
      });

      expect(result.diagnostics.restoredSentences).toBe(0);
      expect(result.diagnostics.sourceChars).toBe(Array.from(source).length);
      expect(await readFile(result.finalPath, "utf8")).toBe(
        await readFile(workspace.path("01_input.txt"), "utf8")
      );
    } finally {
      await workspace.cleanup();
      await removeTestRoot(outer);
    }
  });
});
