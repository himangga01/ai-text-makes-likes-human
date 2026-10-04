import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { PythonEngine } from "../../src/engine/python-engine.js";
import { exited, FakeCommandRunner } from "../helpers/fake-command-runner.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

const vendorRoot = path.resolve("vendor/humanize-engine");

function manifestFixture(overrides: Record<string, unknown> = {}) {
  return {
    version: 1,
    source_file: "01_input.txt",
    source_chars: 15,
    source_sha256: "abc123",
    chunk_count: 2,
    body_chunk_count: 1,
    passthrough_chunk_count: 1,
    route_hint: "standard",
    route_reason: "카운트형 티 3건 · risk_band medium — 단일 윤문 권장",
    processing_mode: "single",
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
    ],
    ...overrides
  };
}

function gateStdout(exitCode: number): string {
  return `[P3 golden] PASS\n${JSON.stringify({
    golden: [],
    gate: { verdict: "WARN", exit_code: exitCode }
  }, null, 2)}\n`;
}

describe("PythonEngine", () => {
  it("maps upstream manifest fields without inventing chunk filenames", async () => {
    const runDir = await makeTestRoot();
    try {
      await writeFile(
        path.join(runDir, "chunk_manifest.json"),
        JSON.stringify(manifestFixture()),
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
      expect(manifest.routeHint).toBe("standard");
      expect(manifest.routeReason).toContain("단일 윤문 권장");
      expect(manifest.processingMode).toBe("single");
      expect(runner.calls[0]?.args).toContain("--portal-auto-route");
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it.each([
    ["route_hint", "fast"],
    ["processing_mode", "parallel"]
  ])("rejects invalid manifest enum %s=%s", async (field, value) => {
    const runDir = await makeTestRoot();
    try {
      await writeFile(
        path.join(runDir, "chunk_manifest.json"),
        JSON.stringify(manifestFixture({ [field]: value })),
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

  it.each([
    [0, "ok"],
    [1, "warn"],
    [2, "abort"],
    [3, "error"]
  ] as const)("maps gate exit %i to %s", async (exitCode, status) => {
    const runner = new FakeCommandRunner([
      exited(gateStdout(exitCode), exitCode)
    ]);
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

    expect(result).toEqual({
      status,
      exitCode,
      gateCodes: [
        ["GATE_OK", "GATE_WARN", "GATE_ABORT", "GATE_ERROR"][exitCode]
      ]
    });
    expect(result).not.toHaveProperty("stdout");
  });

  it("restores modality, strips injected commas and repairs particles in place", async () => {
    const runner = new FakeCommandRunner([
      exited("", 0, '{\n "restored": 1,\n "skipped": 2,\n "details": {}\n}\n'),
      exited("", 0, '{"commas_removed": 3, "sentences_touched": 1}\n'),
      exited("", 0, '{"repaired": 4}\n')
    ]);
    const engine = new PythonEngine({
      pythonCommand: "python",
      vendorRoot,
      runner
    });

    const report = await engine.restore(
      "C:/job/before.txt",
      "C:/job/after.txt",
      new AbortController().signal
    );

    expect(report).toEqual({
      restoredSentences: 1,
      skippedSentences: 2,
      removedCommas: 3,
      repairedParticles: 4
    });
    const after = path.resolve("C:/job/after.txt");
    expect(runner.calls.map(call => call.args[0])).toEqual([
      path.join(vendorRoot, "scripts", "restore_modality.py"),
      path.resolve(vendorRoot, "../../engine_runtime/comma_guard.py"),
      path.resolve(vendorRoot, "../../engine_runtime/super_sejong_josa.py")
    ]);
    for (const call of runner.calls) {
      expect(call.args).toEqual(
        expect.arrayContaining(["--before", "--after", "--out", after, "--json"])
      );
      expect(call.args).not.toContain("--all");
    }
  });

  it("rejects a failed modality restore before stripping commas", async () => {
    const runner = new FakeCommandRunner([exited("", 1, "Traceback")]);
    const engine = new PythonEngine({
      pythonCommand: "python",
      vendorRoot,
      runner
    });

    await expect(
      engine.restore(
        "C:/job/before.txt",
        "C:/job/after.txt",
        new AbortController().signal
      )
    ).rejects.toMatchObject({ publicCode: "ENGINE_OUTPUT_INVALID" });
    expect(runner.calls).toHaveLength(1);
  });

  it("gives a chunk gate the whole prepared source as footnote context", async () => {
    const runDir = await makeTestRoot();
    try {
      await writeFile(path.join(runDir, "chunk_manifest.json"), JSON.stringify(manifestFixture()), "utf8");
      await writeFile(path.join(runDir, "01_input.txt"), "원문", "utf8");
      const runner = new FakeCommandRunner([exited(gateStdout(0), 0), exited(gateStdout(0), 0)]);
      const engine = new PythonEngine({ pythonCommand: "python", vendorRoot, runner });
      await engine.verify(path.join(runDir, "chunk-1-source.txt"), path.join(runDir, "02_chunk_01_rewritten.txt"), new AbortController().signal);
      const args = runner.calls[0]!.args;
      expect(args[args.indexOf("--context") + 1]).toBe(path.join(runDir, "01_input.txt"));
      // The full-document gate already compares the whole source.
      await engine.verify(path.join(runDir, "01_input.txt"), path.join(runDir, "final.md"), new AbortController().signal);
      expect(runner.calls[1]!.args).not.toContain("--context");
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it("rejects malformed gate stdout", async () => {
    const engine = new PythonEngine({
      pythonCommand: "python",
      vendorRoot,
      runner: new FakeCommandRunner([
        exited("[P3 golden] PASS\nnot-json\n", 1)
      ])
    });

    await expect(
      engine.verify(
        "C:/job/before.txt",
        "C:/job/after.txt",
        new AbortController().signal
      )
    ).rejects.toMatchObject({ publicCode: "ENGINE_OUTPUT_INVALID" });
  });

  it("rejects a gate report exit-code mismatch", async () => {
    const engine = new PythonEngine({
      pythonCommand: "python",
      vendorRoot,
      runner: new FakeCommandRunner([exited(gateStdout(0), 1)])
    });

    await expect(
      engine.verify(
        "C:/job/before.txt",
        "C:/job/after.txt",
        new AbortController().signal
      )
    ).rejects.toMatchObject({ publicCode: "ENGINE_OUTPUT_INVALID" });
  });

  it("omits portal auto-routing when explicitly disabled", async () => {
    const runDir = await makeTestRoot();
    try {
      await writeFile(
        path.join(runDir, "chunk_manifest.json"),
        JSON.stringify(manifestFixture()),
        "utf8"
      );
      const runner = new FakeCommandRunner([exited("")]);
      const engine = new PythonEngine({
        pythonCommand: "python",
        vendorRoot,
        runner,
        autoRoute: false
      });

      await engine.prepare(runDir, new AbortController().signal);

      expect(runner.calls[0]?.args).not.toContain("--portal-auto-route");
    } finally {
      await removeTestRoot(runDir);
    }
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
          route_hint: "standard",
          route_reason: "single document route",
          processing_mode: "single",
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
