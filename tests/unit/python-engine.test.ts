import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { PythonEngine } from "../../src/engine/python-engine.js";
import { exited, FakeCommandRunner } from "../helpers/fake-command-runner.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

const vendorRoot = path.resolve("vendor/humanize-engine");

describe("PythonEngine", () => {
  it("maps upstream manifest fields without inventing chunk filenames", async () => {
    const runDir = await makeTestRoot();
    try {
      await writeFile(
        path.join(runDir, "chunk_manifest.json"),
        JSON.stringify({
          version: 1,
          source_file: "01_input.txt",
          source_chars: 15,
          source_sha256: "abc123",
          chunk_count: 2,
          body_chunk_count: 1,
          passthrough_chunk_count: 1,
          warnings: [],
          chunks: [
            {
              index: 1,
              start: 0,
              end: 10,
              char_count: 10,
              starts_with_heading: false,
              heading: null,
              passthrough: false,
              input_file: "01_chunk_01_input_with_metrics.txt",
              rewritten_file: "02_chunk_01_rewritten.txt"
            },
            {
              index: 2,
              start: 10,
              end: 15,
              char_count: 5,
              starts_with_heading: false,
              heading: null,
              passthrough: true,
              input_file: null,
              rewritten_file: null
            }
          ]
        }),
        "utf8"
      );
      const runner = new FakeCommandRunner([exited("")]);
      const engine = new PythonEngine({
        pythonCommand: "python",
        vendorRoot,
        runner
      });

      const manifest = await engine.prepare(
        runDir,
        new AbortController().signal
      );

      expect(manifest).toMatchObject({
        version: 1,
        sourceFile: "01_input.txt",
        bodyChunkCount: 1,
        passthroughChunkCount: 1
      });
      expect(manifest.chunks[0]).toEqual({
        index: 1,
        start: 0,
        end: 10,
        charCount: 10,
        startsWithHeading: false,
        heading: null,
        passthrough: false,
        inputFile: "01_chunk_01_input_with_metrics.txt",
        rewrittenFile: "02_chunk_01_rewritten.txt"
      });
      expect(manifest.chunks[1]?.passthrough).toBe(true);
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it.each([
    [0, "ok"],
    [1, "warn"],
    [2, "abort"],
    [3, "error"]
  ] as const)("maps gate exit %i to %s", async (exitCode, status) => {
    const runner = new FakeCommandRunner([exited("gate output", exitCode)]);
    const engine = new PythonEngine({
      pythonCommand: "python",
      vendorRoot,
      runner
    });

    const result = await engine.verify(
      "C:/job/before.txt",
      "C:/job/after.txt",
      new AbortController().signal
    );

    expect(result).toEqual({ status, exitCode, stdout: "gate output" });
  });

  it("rejects manifest traversal filenames", async () => {
    const runDir = await makeTestRoot();
    try {
      await mkdir(path.join(runDir, "nested"), { recursive: true });
      await writeFile(
        path.join(runDir, "chunk_manifest.json"),
        JSON.stringify({
          version: 1,
          source_file: "01_input.txt",
          source_chars: 1,
          source_sha256: "hash",
          chunk_count: 1,
          body_chunk_count: 1,
          passthrough_chunk_count: 0,
          warnings: [],
          chunks: [{
            index: 1, start: 0, end: 1, char_count: 1,
            starts_with_heading: false, heading: null, passthrough: false,
            input_file: "../secret.txt", rewritten_file: "02_chunk_01_rewritten.txt"
          }]
        }),
        "utf8"
      );
      const engine = new PythonEngine({
        pythonCommand: "python",
        vendorRoot,
        runner: new FakeCommandRunner([exited("")])
      });

      await expect(
        engine.prepare(runDir, new AbortController().signal)
      ).rejects.toMatchObject({ publicCode: "ENGINE_OUTPUT_INVALID" });
    } finally {
      await removeTestRoot(runDir);
    }
  });
});
