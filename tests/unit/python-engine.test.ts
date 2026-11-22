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

// lexical_layer.py restore --json: indented, and it names the sentences it touched.
const LEXICAL_REPORT = `${JSON.stringify({
  restored: 1,
  skipped: 1,
  restored_items: [{ after: "이 결과를 여러 렌즈로 살펴본다.", before: "이 결과를 여러 관점에서 살펴본다.", headwords: ["렌즈"] }],
  skipped_items: [{ after: "두 렌즈를 쓴다.", before: "두 관점을 쓴다.", headwords: ["렌즈"], reason: "짝 유사도 낮음" }]
}, null, 1)}\n`;

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

  it("restores modality, strips injected commas, restores lexicon injections and repairs particles in place", async () => {
    const runner = new FakeCommandRunner([
      exited("", 0, '{\n "restored": 1,\n "skipped": 2,\n "details": {}\n}\n'),
      exited("", 0, '{"commas_removed": 3, "sentences_touched": 1}\n'),
      exited("", 0, LEXICAL_REPORT),
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
      repairedParticles: 4,
      restoredLexicalSentences: 1,
      skippedLexicalSentences: 1,
      lexicalRestoreFailures: 0
    });
    // Counts only: the sentences the lexical report names never leave the adapter.
    expect(JSON.stringify(report)).not.toContain("렌즈");
    const after = path.resolve("C:/job/after.txt");
    expect(runner.calls.map(call => call.args[0])).toEqual([
      path.join(vendorRoot, "scripts", "restore_modality.py"),
      path.resolve(vendorRoot, "../../engine_runtime/comma_guard.py"),
      path.join(vendorRoot, "scripts", "lexical_layer.py"),
      path.resolve(vendorRoot, "../../engine_runtime/super_sejong_josa.py")
    ]);
    expect(runner.calls[2]!.args[1]).toBe("restore");
    for (const call of runner.calls) {
      expect(call.args).toEqual(
        expect.arrayContaining(["--before", "--after", "--out", after, "--json"])
      );
      expect(call.args).not.toContain("--all");
    }
  });

  it("counts a lexical restore without a usable report and still repairs particles", async () => {
    for (const lexical of [
      exited("", 0, "[lexical-layer] 건너뜀: lexicon missing\n"),
      exited("", 0, '{"restored": -1, "skipped": 0}\n'),
      exited("", 0, '{"restored": 1}\n'),
      exited("", 1, "Traceback (most recent call last)\n")
    ]) {
      const runner = new FakeCommandRunner([
        exited("", 0, '{"restored": 0, "skipped": 0}\n'),
        exited("", 0, '{"commas_removed": 0}\n'),
        lexical,
        exited("", 0, '{"repaired": 2}\n')
      ]);
      const engine = new PythonEngine({ pythonCommand: "python", vendorRoot, runner });
      const report = await engine.restore("C:/job/before.txt", "C:/job/after.txt", new AbortController().signal);
      expect(report).toMatchObject({
        repairedParticles: 2,
        restoredLexicalSentences: 0,
        skippedLexicalSentences: 0,
        lexicalRestoreFailures: 1
      });
      expect(runner.calls).toHaveLength(4);
    }
  });

  it("asks the lexical layer for one source's hints with the prepare genre", async () => {
    const block = "[어휘 점검]\n안내\n- [우선] 렌즈 — 원문: \"렌즈\"\n[어휘 점검 끝]";
    const runner = new FakeCommandRunner([exited(`${block}\n`), exited("\n")]);
    const engine = new PythonEngine({ pythonCommand: "python", vendorRoot, runner });
    const signal = new AbortController().signal;

    expect(await engine.lexicalHints("C:/job/chunk-1-source.txt", signal)).toEqual({ hints: block, failed: false });
    expect(await engine.lexicalHints("C:/job/chunk-1-source.txt", signal)).toEqual({ hints: "", failed: false });
    expect(runner.calls[0]!.args).toEqual([
      path.join(vendorRoot, "scripts", "lexical_layer.py"),
      "hints", "--input", path.resolve("C:/job/chunk-1-source.txt"), "--genre", "essay"
    ]);
    expect(runner.calls[0]!.cwd).toBe(path.dirname(path.resolve("C:/job/chunk-1-source.txt")));
  });

  it("reports a failed hints run as no block instead of failing", async () => {
    const block = "[어휘 점검]\n- x\n[어휘 점검 끝]";
    for (const result of [
      exited("", 0, "[lexical-layer] 건너뜀: boom\n"),
      exited(`${block}\n`, 0, "[lexical-layer] 건너뜀: boom\n"),
      exited(`${block}\n`, 1),
      exited("[어휘 점검]\n- 잘린 블록\n"),
      { exitCode: 0, stdout: "", stderr: "", termination: "timeout" as const },
      new Error("spawn python ENOENT")
    ]) {
      const engine = new PythonEngine({ pythonCommand: "python", vendorRoot, runner: new FakeCommandRunner([result]) });
      expect(await engine.lexicalHints("C:/job/chunk-1-source.txt", new AbortController().signal)).toEqual({ hints: "", failed: true });
    }
  });

  it("lets a cancelled hints run cancel the job", async () => {
    const controller = new AbortController();
    controller.abort();
    const engine = new PythonEngine({
      pythonCommand: "python", vendorRoot,
      runner: new FakeCommandRunner([{ exitCode: 0, stdout: "", stderr: "", termination: "aborted" }])
    });
    await expect(engine.lexicalHints("C:/job/chunk-1-source.txt", controller.signal)).rejects.toMatchObject({ publicCode: "CLIENT_ABORTED" });
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
