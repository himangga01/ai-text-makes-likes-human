import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type { TransformEvent } from "../../src/contracts.js";
import { JobWorkspace } from "../../src/engine/workspace.js";
import {
  HumanizeEngine,
  type CodexAdapter,
  type PythonAdapter
} from "../../src/engine/humanize-engine.js";
import type {
  ChunkManifest,
  GateResult
} from "../../src/engine/python-engine.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

const ok = (): GateResult => ({
  status: "ok",
  exitCode: 0,
  gateCodes: ["GATE_OK"]
});
const warn = (): GateResult => ({
  status: "warn",
  exitCode: 1,
  gateCodes: ["GATE_WARN"]
});
const abort = (): GateResult => ({
  status: "abort",
  exitCode: 2,
  gateCodes: ["GATE_ABORT"]
});
const gateError = (): GateResult => ({
  status: "error",
  exitCode: 3,
  gateCodes: ["GATE_ERROR"]
});

function manifest(chunks: ChunkManifest["chunks"], sourceChars: number): ChunkManifest {
  return {
    version: 1,
    sourceFile: "01_input.txt",
    sourceChars,
    sourceSha256: "hash",
    chunkCount: chunks.length,
    bodyChunkCount: chunks.filter(chunk => !chunk.passthrough).length,
    passthroughChunkCount: chunks.filter(chunk => chunk.passthrough).length,
    routeHint: "standard",
    routeReason: "single document route",
    processingMode: "single",
    warnings: [],
    chunks
  };
}

function body(index: number, start: number, end: number) {
  return {
    index,
    start,
    end,
    charCount: end - start,
    startsWithHeading: false,
    heading: null,
    passthrough: false,
    inputFile: `01_chunk_${String(index).padStart(2, "0")}_input_with_metrics.txt`,
    rewrittenFile: `02_chunk_${String(index).padStart(2, "0")}_rewritten.txt`
  };
}

function passthrough(index: number, start: number, end: number) {
  return {
    index,
    start,
    end,
    charCount: end - start,
    startsWithHeading: false,
    heading: null,
    passthrough: true,
    inputFile: null,
    rewrittenFile: null
  };
}

class FakePython implements PythonAdapter {
  private verifyResults: GateResult[];
  constructor(
    private readonly chunkManifest: ChunkManifest,
    verifyResults: GateResult[]
  ) {
    this.verifyResults = [...verifyResults];
  }
  async prepare(): Promise<ChunkManifest> {
    return this.chunkManifest;
  }
  async verify(): Promise<GateResult> {
    const result = this.verifyResults.shift();
    if (!result) throw new Error("No gate result configured");
    return result;
  }
  async reassemble(runDir: string): Promise<string> {
    const source = await readFile(path.join(runDir, "01_input.txt"), "utf8");
    const pieces: string[] = [];
    for (const chunk of this.chunkManifest.chunks) {
      pieces.push(
        chunk.passthrough
          ? source.slice(chunk.start, chunk.end)
          : await readFile(path.join(runDir, chunk.rewrittenFile!), "utf8")
      );
    }
    const output = path.join(runDir, "03_reassembled.md");
    await writeFile(output, pieces.join(""), "utf8");
    return output;
  }
}

class FakeCodex implements CodexAdapter {
  readonly attempts: Array<{ source: string; attempt: 1 | 2 }> = [];
  constructor(
    private readonly outputs: string[],
    private readonly afterTransform?: (count: number) => void
  ) {}
  async transform(
    inputPath: string,
    _outputPath: string,
    attempt: 1 | 2
  ) {
    const source = await readFile(inputPath, "utf8");
    this.attempts.push({ source, attempt });
    const rewrittenText = this.outputs.shift();
    if (rewrittenText === undefined) throw new Error("No Codex output configured");
    this.afterTransform?.(this.attempts.length);
    return { rewrittenText, warnings: [] };
  }
}

async function setup(source: string): Promise<{
  outer: string;
  workspace: JobWorkspace;
}> {
  const outer = await makeTestRoot();
  const workspace = await JobWorkspace.create(outer, "job-1");
  await writeFile(workspace.path("01_input.txt"), source, "utf8");
  return { outer, workspace };
}

describe("HumanizeEngine", () => {
  it("transforms one body chunk and returns the verified result", async () => {
    const test = await setup("AAA");
    try {
      const ticks = [0, 5, 15, 18, 20, 27, 30, 35, 40];
      const now = () => ticks.shift() ?? 40;
      const codex = new FakeCodex(["BBB"]);
      const engine = new HumanizeEngine({
        python: new FakePython(manifest([body(1, 0, 3)], 3), [ok(), ok()]),
        codex,
        chunkConcurrency: 1,
        now
      });

      const result = await engine.transform({
        jobId: "job-1",
        workspace: test.workspace,
        signal: new AbortController().signal,
        onEvent: () => undefined
      });

      expect(await readFile(result.finalPath, "utf8")).toBe("BBB");
      expect(result.chunks).toBe(1);
      expect(codex.attempts).toEqual([{ source: "AAA", attempt: 1 }]);
      expect(result.diagnostics).toMatchObject({
        model: "gpt-5.6-sol",
        reasoningEffort: "high",
        processingMode: "single",
        routeHint: "standard",
        sourceChars: 3,
        bodyChunks: 1,
        codexCalls: 1,
        retries: 0,
        gateCodes: ["GATE_OK", "GATE_OK"],
        maxObservedCodexConcurrency: 1,
        prepareMs: 5,
        codexMs: 3,
        gateMs: 12,
        assembleMs: 5,
        totalMs: 40
      });
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("preserves passthrough content and body order", async () => {
    const test = await setup("AAA---BBB");
    try {
      const chunks = [body(1, 0, 3), passthrough(2, 3, 6), body(3, 6, 9)];
      const engine = new HumanizeEngine({
        python: new FakePython(manifest(chunks, 9), [ok(), ok(), ok()]),
        codex: new FakeCodex(["111", "222"]),
        chunkConcurrency: 1
      });

      const result = await engine.transform({
        jobId: "job-1",
        workspace: test.workspace,
        signal: new AbortController().signal,
        onEvent: () => undefined
      });

      expect(await readFile(result.finalPath, "utf8")).toBe("111---222");
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("retries a warned chunk once with the conservative attempt", async () => {
    const test = await setup("AAA");
    try {
      const codex = new FakeCodex(["BAD", "GOOD"]);
      const events: TransformEvent[] = [];
      const engine = new HumanizeEngine({
        python: new FakePython(
          manifest([body(1, 0, 3)], 3),
          [warn(), ok(), ok()]
        ),
        codex,
        chunkConcurrency: 1
      });

      const result = await engine.transform({
        jobId: "job-1",
        workspace: test.workspace,
        signal: new AbortController().signal,
        onEvent: event => events.push(event)
      });

      expect(await readFile(result.finalPath, "utf8")).toBe("GOOD");
      expect(codex.attempts.map(item => item.attempt)).toEqual([1, 2]);
      expect(result.diagnostics).toMatchObject({
        codexCalls: 2,
        retries: 1,
        gateCodes: ["GATE_WARN", "GATE_OK", "GATE_OK"]
      });
      expect(events).toContainEqual(
        expect.objectContaining({ type: "warning", code: "CHUNK_RETRY" })
      );
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("rolls a chunk back to source after two abort verdicts", async () => {
    const test = await setup("AAA");
    try {
      const engine = new HumanizeEngine({
        python: new FakePython(
          manifest([body(1, 0, 3)], 3),
          [abort(), abort(), ok()]
        ),
        codex: new FakeCodex(["TOTALLY NEW", "STILL NEW"]),
        chunkConcurrency: 1
      });

      const result = await engine.transform({
        jobId: "job-1",
        workspace: test.workspace,
        signal: new AbortController().signal,
        onEvent: () => undefined
      });

      expect(await readFile(result.finalPath, "utf8")).toBe("AAA");
      expect(result.warnings).toContainEqual(
        expect.objectContaining({ code: "CHUNK_ROLLED_BACK" })
      );
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("rejects a gate execution error and a full-document abort", async () => {
    const first = await setup("AAA");
    try {
      const brokenChunk = new HumanizeEngine({
        python: new FakePython(manifest([body(1, 0, 3)], 3), [gateError()]),
        codex: new FakeCodex(["BBB"]),
        chunkConcurrency: 1
      });
      await expect(
        brokenChunk.transform({
          jobId: "job-1",
          workspace: first.workspace,
          signal: new AbortController().signal,
          onEvent: () => undefined
        })
      ).rejects.toMatchObject({ publicCode: "VALIDATION_FAILED" });
    } finally {
      await first.workspace.cleanup();
      await removeTestRoot(first.outer);
    }

    const second = await setup("AAA");
    try {
      const brokenDocument = new HumanizeEngine({
        python: new FakePython(manifest([body(1, 0, 3)], 3), [ok(), abort()]),
        codex: new FakeCodex(["BBB"]),
        chunkConcurrency: 1
      });
      await expect(
        brokenDocument.transform({
          jobId: "job-1",
          workspace: second.workspace,
          signal: new AbortController().signal,
          onEvent: () => undefined
        })
      ).rejects.toMatchObject({ publicCode: "VALIDATION_FAILED" });
    } finally {
      await second.workspace.cleanup();
      await removeTestRoot(second.outer);
    }
  });

  it("does not start another chunk after cancellation", async () => {
    const test = await setup("AAABBB");
    const controller = new AbortController();
    try {
      const codex = new FakeCodex(["111", "222"], count => {
        if (count === 1) controller.abort();
      });
      const engine = new HumanizeEngine({
        python: new FakePython(
          manifest([body(1, 0, 3), body(2, 3, 6)], 6),
          [ok(), ok(), ok()]
        ),
        codex,
        chunkConcurrency: 1
      });

      await expect(
        engine.transform({
          jobId: "job-1",
          workspace: test.workspace,
          signal: controller.signal,
          onEvent: () => undefined
        })
      ).rejects.toMatchObject({ publicCode: "CLIENT_ABORTED" });
      expect(codex.attempts).toHaveLength(1);
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });
});
