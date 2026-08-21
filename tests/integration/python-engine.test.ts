import { copyFile, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { PythonEngine } from "../../src/engine/python-engine.js";
import { SpawnCommandRunner } from "../../src/process/command-runner.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

const engine = new PythonEngine({
  pythonCommand: "python",
  vendorRoot: path.resolve("vendor/humanize-engine"),
  runner: new SpawnCommandRunner()
});

describe("PythonEngine integration", () => {
  it("prepares, verifies, and losslessly reassembles a short document", async () => {
    const runDir = await makeTestRoot();
    try {
      await copyFile(
        path.resolve("tests/fixtures/short-korean.txt"),
        path.join(runDir, "01_input.txt")
      );
      const signal = new AbortController().signal;
      const manifest = await engine.prepare(runDir, signal);
      const source = await readFile(path.join(runDir, manifest.sourceFile), "utf8");

      for (const chunk of manifest.chunks.filter(item => !item.passthrough)) {
        await writeFile(
          path.join(runDir, chunk.rewrittenFile!),
          source.slice(chunk.start, chunk.end),
          "utf8"
        );
      }

      const outputPath = await engine.reassemble(runDir, signal);
      expect(await readFile(outputPath, "utf8")).toBe(source);
      const gate = await engine.verify(
        path.join(runDir, manifest.sourceFile),
        outputPath,
        signal
      );
      expect(gate.status).toBe("ok");
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it("creates multiple body chunks for a document over 15,000 characters", async () => {
    const runDir = await makeTestRoot();
    try {
      const paragraph =
        "이 문단은 장문 자동 분할을 검증한다. 수치 1,200과 OpenAI는 그대로 유지한다. 문장 경계에서 안전하게 나뉘어야 한다.\n\n";
      const source = `# 장문 테스트\n\n${paragraph.repeat(230)}`;
      expect(source.length).toBeGreaterThan(15_000);
      await writeFile(path.join(runDir, "01_input.txt"), source, "utf8");

      const manifest = await engine.prepare(
        runDir,
        new AbortController().signal
      );

      expect(manifest.bodyChunkCount).toBeGreaterThanOrEqual(2);
      expect(manifest.chunks.map(chunk => [chunk.start, chunk.end])).toEqual(
        expect.arrayContaining([[0, manifest.chunks[0]!.end]])
      );
      const sanitized = await readFile(path.join(runDir, "01_input.txt"), "utf8");
      expect(
        manifest.chunks.map(chunk => sanitized.slice(chunk.start, chunk.end)).join("")
      ).toBe(sanitized);
    } finally {
      await removeTestRoot(runDir);
    }
  });
});
