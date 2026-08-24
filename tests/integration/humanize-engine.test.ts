import { copyFile, readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type { CodexAdapter } from "../../src/engine/humanize-engine.js";
import { HumanizeEngine } from "../../src/engine/humanize-engine.js";
import { PythonEngine } from "../../src/engine/python-engine.js";
import { JobWorkspace } from "../../src/engine/workspace.js";
import { SpawnCommandRunner } from "../../src/process/command-runner.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

class IdentityCodex implements CodexAdapter {
  async transform(inputPath: string) {
    return { rewrittenText: await readFile(inputPath, "utf8"), warnings: [] };
  }
}

describe("HumanizeEngine integration", () => {
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
          pythonCommand: "python",
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
});
