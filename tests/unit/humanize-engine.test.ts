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
  GateResult,
  RestoreReport
} from "../../src/engine/python-engine.js";
import { EngineError } from "../../src/engine/errors.js";
import { deferred, type Deferred } from "../helpers/deferred.js";
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

function manifest(
  chunks: ChunkManifest["chunks"],
  sourceChars: number,
  processingMode: ChunkManifest["processingMode"] = "single"
): ChunkManifest {
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
    processingMode,
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

const noRestore = (): RestoreReport => ({
  restoredSentences: 0,
  skippedSentences: 0,
  removedCommas: 0
});

class FakePython implements PythonAdapter {
  reassembleCalls = 0;
  readonly calls: Array<"restore" | "verify"> = [];
  readonly restoreCalls: Array<{ before: string; after: string }> = [];
  private verifyResults: GateResult[];
  private restoreReports: RestoreReport[];
  constructor(
    private readonly chunkManifest: ChunkManifest,
    verifyResults: GateResult[],
    restoreReports: RestoreReport[] = []
  ) {
    this.verifyResults = [...verifyResults];
    this.restoreReports = [...restoreReports];
  }
  async prepare(): Promise<ChunkManifest> {
    return this.chunkManifest;
  }
  async restore(before: string, after: string): Promise<RestoreReport> {
    this.calls.push("restore");
    this.restoreCalls.push({ before, after });
    return this.restoreReports.shift() ?? noRestore();
  }
  async verify(): Promise<GateResult> {
    this.calls.push("verify");
    const result = this.verifyResults.shift();
    if (!result) throw new Error("No gate result configured");
    return result;
  }
  async reassemble(runDir: string): Promise<string> {
    this.reassembleCalls += 1;
    const source = Array.from(
      await readFile(path.join(runDir, "01_input.txt"), "utf8")
    );
    const pieces: string[] = [];
    for (const chunk of this.chunkManifest.chunks) {
      pieces.push(
        chunk.passthrough
          ? source.slice(chunk.start, chunk.end).join("")
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

interface DeferredCodexCall {
  started: Deferred<void>;
  result: Deferred<{ rewrittenText: string; warnings: string[] }>;
}

class DeferredCodex implements CodexAdapter {
  active = 0;
  maxActive = 0;
  readonly startedSources: string[] = [];
  private readonly calls = new Map<string, DeferredCodexCall>();

  constructor(sources: string[]) {
    for (const source of sources) {
      this.calls.set(source, {
        started: deferred<void>(),
        result: deferred<{ rewrittenText: string; warnings: string[] }>()
      });
    }
  }

  started(source: string): Promise<void> {
    return this.call(source).started.promise;
  }

  resolve(
    source: string,
    rewrittenText: string,
    warnings: string[] = []
  ): void {
    this.call(source).result.resolve({ rewrittenText, warnings });
  }

  async transform(inputPath: string) {
    const source = await readFile(inputPath, "utf8");
    const call = this.call(source);
    this.startedSources.push(source);
    this.active += 1;
    this.maxActive = Math.max(this.maxActive, this.active);
    call.started.resolve();
    try {
      return await call.result.promise;
    } finally {
      this.active -= 1;
    }
  }

  private call(source: string): DeferredCodexCall {
    const call = this.calls.get(source);
    if (!call) throw new Error(`No deferred Codex call for ${source}`);
    return call;
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
      const ticks = [0, 5, 15, 18, 18, 19, 20, 27, 30, 35, 40];
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
        model: "gpt-6.1-sol",
        reasoningEffort: "high",
        processingMode: "single",
        routeHint: "standard",
        sourceChars: 3,
        bodyChunks: 1,
        codexCalls: 1,
        retries: 0,
        restoredSentences: 0,
        removedCommas: 0,
        gateCodes: ["GATE_OK", "GATE_OK"],
        maxObservedCodexConcurrency: 1,
        prepareMs: 5,
        codexMs: 3,
        restoreMs: 1,
        gateMs: 12,
        assembleMs: 5,
        totalMs: 40
      });
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("slices chunks by code points so astral characters keep manifest offsets", async () => {
    const test = await setup("😀AB--😀");
    try {
      const codex = new FakeCodex(["😀AB"]);
      const engine = new HumanizeEngine({
        python: new FakePython(
          manifest([body(1, 0, 3), passthrough(2, 3, 6)], 6),
          [ok(), ok()]
        ),
        codex,
        chunkConcurrency: 1
      });

      const result = await engine.transform({
        jobId: "job-1",
        workspace: test.workspace,
        signal: new AbortController().signal,
        onEvent: () => undefined
      });

      expect(codex.attempts).toEqual([{ source: "😀AB", attempt: 1 }]);
      expect(await readFile(result.finalPath, "utf8")).toBe("😀AB--😀");
      expect(result.diagnostics.sourceChars).toBe(6);
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("rejects a manifest whose offsets do not cover the source text", async () => {
    const test = await setup("AAAA");
    try {
      const engine = new HumanizeEngine({
        python: new FakePython(manifest([body(1, 0, 3)], 3), [ok(), ok()]),
        codex: new FakeCodex(["BBB"]),
        chunkConcurrency: 1
      });

      await expect(
        engine.transform({
          jobId: "job-1",
          workspace: test.workspace,
          signal: new AbortController().signal,
          onEvent: () => undefined
        })
      ).rejects.toMatchObject({ publicCode: "ENGINE_OUTPUT_INVALID" });
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("restores modality in place before every chunk gate and reports it", async () => {
    const test = await setup("AAA");
    const events: TransformEvent[] = [];
    try {
      const python = new FakePython(
        manifest([body(1, 0, 3)], 3),
        [warn(), ok(), ok()],
        [
          { restoredSentences: 2, skippedSentences: 1, removedCommas: 1 },
          { restoredSentences: 0, skippedSentences: 0, removedCommas: 3 }
        ]
      );
      const engine = new HumanizeEngine({
        python,
        codex: new FakeCodex(["BBB", "CCC"]),
        chunkConcurrency: 1
      });

      const result = await engine.transform({
        jobId: "job-1",
        workspace: test.workspace,
        signal: new AbortController().signal,
        onEvent: event => events.push(event)
      });

      expect(python.calls).toEqual([
        "restore",
        "verify",
        "restore",
        "verify",
        "verify"
      ]);
      expect(python.restoreCalls).toEqual([
        {
          before: test.workspace.path("chunk-1-source.txt"),
          after: test.workspace.path("02_chunk_01_rewritten.txt")
        },
        {
          before: test.workspace.path("chunk-1-source.txt"),
          after: test.workspace.path("02_chunk_01_rewritten.txt")
        }
      ]);
      expect(events.filter(event => event.type === "warning")).toEqual([
        expect.objectContaining({
          code: "MODALITY_RESTORED",
          message: "1번 구간에서 서법 보존을 위해 2개 문장을 원문으로 되돌렸습니다."
        }),
        expect.objectContaining({ code: "CHUNK_RETRY" })
      ]);
      expect(result.diagnostics).toMatchObject({
        codexCalls: 2,
        retries: 1,
        restoredSentences: 2,
        removedCommas: 4
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

  it("processes chunked bodies two at a time and reassembles in manifest order", async () => {
    const test = await setup("AAABBBCCCDDD");
    try {
      const chunks = [
        body(1, 0, 3),
        body(2, 3, 6),
        body(3, 6, 9),
        body(4, 9, 12)
      ];
      const codex = new DeferredCodex(["AAA", "BBB", "CCC", "DDD"]);
      const engine = new HumanizeEngine({
        python: new FakePython(
          manifest(chunks, 12, "chunked"),
          [ok(), ok(), ok(), ok(), ok()]
        ),
        codex,
        chunkConcurrency: 2
      });

      const resultPromise = engine.transform({
        jobId: "job-1",
        workspace: test.workspace,
        signal: new AbortController().signal,
        onEvent: () => undefined
      });

      await Promise.all([codex.started("AAA"), codex.started("BBB")]);
      expect(codex.active).toBe(2);
      codex.resolve("BBB", "222");
      await codex.started("CCC");
      codex.resolve("CCC", "333");
      await codex.started("DDD");
      codex.resolve("DDD", "444");
      codex.resolve("AAA", "111");

      const result = await resultPromise;
      expect(codex.maxActive).toBe(2);
      expect(await readFile(result.finalPath, "utf8")).toBe("111222333444");
      expect(result.diagnostics.maxObservedCodexConcurrency).toBe(2);
      expect(result.diagnostics.codexCalls).toBe(4);
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("reports codex concurrency observed within each job", async () => {
    const first = await setup("AAABBB");
    const second = await setup("CCC");
    try {
      const pythons = [
        new FakePython(manifest([body(1, 0, 3), body(2, 3, 6)], 6, "chunked"), [ok(), ok(), ok()]),
        new FakePython(manifest([body(1, 0, 3)], 3, "chunked"), [ok(), ok()])
      ];
      let current = pythons[0]!;
      const python: PythonAdapter = {
        prepare: async () => { current = pythons.shift()!; return current.prepare(); },
        restore: (before, after) => current.restore(before, after),
        verify: () => current.verify(),
        reassemble: runDir => current.reassemble(runDir)
      };
      const codex = new DeferredCodex(["AAA", "BBB", "CCC"]);
      const engine = new HumanizeEngine({ python, codex, chunkConcurrency: 2 });

      const firstRun = engine.transform({ jobId: "job-1", workspace: first.workspace, signal: new AbortController().signal, onEvent: () => undefined });
      await Promise.all([codex.started("AAA"), codex.started("BBB")]);
      codex.resolve("AAA", "111");
      codex.resolve("BBB", "222");
      expect((await firstRun).diagnostics.maxObservedCodexConcurrency).toBe(2);

      const secondRun = engine.transform({ jobId: "job-1", workspace: second.workspace, signal: new AbortController().signal, onEvent: () => undefined });
      await codex.started("CCC");
      codex.resolve("CCC", "333");
      expect((await secondRun).diagnostics.maxObservedCodexConcurrency).toBe(1);
    } finally {
      await first.workspace.cleanup();
      await second.workspace.cleanup();
      await removeTestRoot(first.outer);
      await removeTestRoot(second.outer);
    }
  });

  it("emits monotonic aggregate work units for out-of-order completion without counting retries", async () => {
    const test = await setup("AAABBBCCCDDD");
    try {
      const chunks = [
        body(1, 0, 3),
        body(2, 3, 6),
        body(3, 6, 9),
        body(4, 9, 12)
      ];
      const codex = new DeferredCodex(["AAA", "BBB", "CCC", "DDD"]);
      const events: TransformEvent[] = [];
      const engine = new HumanizeEngine({
        python: new FakePython(
          manifest(chunks, 12, "chunked"),
          [warn(), ok(), ok(), ok(), ok(), ok()]
        ),
        codex,
        chunkConcurrency: 2
      });

      const resultPromise = engine.transform({
        jobId: "job-1",
        workspace: test.workspace,
        signal: new AbortController().signal,
        onEvent: event => events.push(event)
      });

      await Promise.all([codex.started("AAA"), codex.started("BBB")]);
      codex.resolve("BBB", "222");
      await codex.started("CCC");
      codex.resolve("CCC", "333");
      await codex.started("DDD");
      codex.resolve("DDD", "444");
      codex.resolve("AAA", "111");
      const result = await resultPromise;

      const aggregateEvents = events.filter(
        (event): event is Extract<TransformEvent, { type: "progress" }> =>
          event.type === "progress" &&
          (event.phase === "transform" || event.phase === "verify")
      );
      expect(aggregateEvents.map(event => event.totalUnits)).toEqual(
        Array(8).fill(8)
      );
      expect(aggregateEvents.map(event => event.completedUnits)).toEqual(
        [1, 2, 3, 4, 5, 6, 7, 8]
      );
      expect(events.filter(
        event => event.type === "warning" && event.code === "CHUNK_RETRY"
      )).toHaveLength(1);
      expect(result.diagnostics.codexCalls).toBe(5);
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("emits concurrent warnings immediately but returns them in manifest order", async () => {
    const test = await setup("AAABBB");
    const chunkTwoWarningObserved = deferred<void>();
    const warningEvents: Array<{ code: string; message: string }> = [];
    let resultSettled = false;
    try {
      const codex = new DeferredCodex(["AAA", "BBB"]);
      const engine = new HumanizeEngine({
        python: new FakePython(
          manifest(
            [body(1, 0, 3), body(2, 3, 6)],
            6,
            "chunked"
          ),
          [ok(), ok(), ok()]
        ),
        codex,
        chunkConcurrency: 2
      });

      const resultPromise = engine.transform({
        jobId: "job-1",
        workspace: test.workspace,
        signal: new AbortController().signal,
        onEvent: event => {
          if (event.type !== "warning") return;
          warningEvents.push({ code: event.code, message: event.message });
          if (event.message.startsWith("2번 구간에 모델 검토")) {
            chunkTwoWarningObserved.resolve();
          }
        }
      }).finally(() => {
        resultSettled = true;
      });

      await Promise.all([codex.started("AAA"), codex.started("BBB")]);
      codex.resolve("BBB", "222", ["chunk two warning"]);
      await chunkTwoWarningObserved.promise;
      expect(resultSettled).toBe(false);
      expect(codex.active).toBe(1);

      codex.resolve("AAA", "111", ["chunk one warning"]);
      const result = await resultPromise;
      expect(warningEvents).toEqual([
        { code: "MODEL_WARNING", message: "2번 구간에 모델 검토 주의가 있습니다. 원문과 결과를 확인해 주세요." },
        { code: "MODEL_WARNING", message: "1번 구간에 모델 검토 주의가 있습니다. 원문과 결과를 확인해 주세요." }
      ]);
      expect(result.warnings).toEqual([
        { code: "MODEL_WARNING", message: "1번 구간에 모델 검토 주의가 있습니다. 원문과 결과를 확인해 주세요." },
        { code: "MODEL_WARNING", message: "2번 구간에 모델 검토 주의가 있습니다. 원문과 결과를 확인해 주세요." }
      ]);
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("keeps single manifests sequential when chunk concurrency is two", async () => {
    const test = await setup("AAABBBCCCDDD");
    try {
      const chunks = [
        body(1, 0, 3),
        body(2, 3, 6),
        body(3, 6, 9),
        body(4, 9, 12)
      ];
      const codex = new DeferredCodex(["AAA", "BBB", "CCC", "DDD"]);
      const engine = new HumanizeEngine({
        python: new FakePython(
          manifest(chunks, 12, "single"),
          [ok(), ok(), ok(), ok(), ok()]
        ),
        codex,
        chunkConcurrency: 2
      });

      const resultPromise = engine.transform({
        jobId: "job-1",
        workspace: test.workspace,
        signal: new AbortController().signal,
        onEvent: () => undefined
      });

      await codex.started("AAA");
      codex.resolve("AAA", "111");
      await codex.started("BBB");
      codex.resolve("BBB", "222");
      await codex.started("CCC");
      codex.resolve("CCC", "333");
      await codex.started("DDD");
      codex.resolve("DDD", "444");

      const result = await resultPromise;
      expect(codex.maxActive).toBe(1);
      expect(await readFile(result.finalPath, "utf8")).toBe("111222333444");
      expect(result.diagnostics.maxObservedCodexConcurrency).toBe(1);
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("waits for an aborted sibling before rejecting a chunk failure", async () => {
    const test = await setup("AAABBBCCCDDD");
    const firstStarted = deferred<void>();
    const secondStarted = deferred<void>();
    const secondMayFail = deferred<void>();
    const firstObservedAbort = deferred<void>();
    const firstMaySettle = deferred<void>();
    const allActiveSettled = deferred<void>();
    // Unusable model output is recovered per chunk; an unavailable engine still fails the job.
    const failure = new EngineError(
      "ENGINE_UNAVAILABLE",
      false,
      "chunk two failed"
    );
    const startedSources: string[] = [];
    let active = 0;
    const codex: CodexAdapter = {
      async transform(inputPath, _outputPath, _attempt, signal) {
        const source = await readFile(inputPath, "utf8");
        startedSources.push(source);
        active += 1;
        try {
          if (source === "AAA") {
            firstStarted.resolve();
            await new Promise<void>(resolve => {
              const observeAbort = (): void => {
                firstObservedAbort.resolve();
                resolve();
              };
              if (signal.aborted) observeAbort();
              else signal.addEventListener("abort", observeAbort, { once: true });
            });
            await firstMaySettle.promise;
            throw new EngineError("CLIENT_ABORTED", true, "sibling cancelled");
          }
          if (source === "BBB") {
            secondStarted.resolve();
            await secondMayFail.promise;
            throw failure;
          }
          throw new Error(`Unexpected Codex start for ${source}`);
        } finally {
          active -= 1;
          if (active === 0) allActiveSettled.resolve();
        }
      }
    };
    const python = new FakePython(
      manifest(
        [
          body(1, 0, 3),
          body(2, 3, 6),
          body(3, 6, 9),
          body(4, 9, 12)
        ],
        12,
        "chunked"
      ),
      []
    );

    try {
      const engine = new HumanizeEngine({
        python,
        codex,
        chunkConcurrency: 2
      });
      let transformSettled = false;
      let activeWhenRejected = -1;
      const outcomePromise = engine.transform({
        jobId: "job-1",
        workspace: test.workspace,
        signal: new AbortController().signal,
        onEvent: () => undefined
      }).then(
        value => {
          transformSettled = true;
          return { status: "fulfilled" as const, value };
        },
        error => {
          transformSettled = true;
          activeWhenRejected = active;
          return { status: "rejected" as const, error };
        }
      );

      await Promise.all([firstStarted.promise, secondStarted.promise]);
      secondMayFail.resolve();
      await firstObservedAbort.promise;
      expect(transformSettled).toBe(false);
      expect(active).toBe(1);

      firstMaySettle.resolve();
      await allActiveSettled.promise;
      const outcome = await outcomePromise;
      expect(outcome.status).toBe("rejected");
      if (outcome.status === "rejected") {
        expect(outcome.error).toBe(failure);
      }
      expect(activeWhenRejected).toBe(0);
      expect([...startedSources].sort()).toEqual(["AAA", "BBB"]);
      expect(python.reassembleCalls).toBe(0);
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

  it("emits warnings at their original points when retry attempt two fails", async () => {
    const test = await setup("AAA");
    const attempts: Array<1 | 2> = [];
    const events: TransformEvent[] = [];
    const codex: CodexAdapter = {
      async transform(_inputPath, _outputPath, attempt) {
        attempts.push(attempt);
        if (attempt === 1) {
          return {
            rewrittenText: "BAD",
            warnings: ["first attempt warning"]
          };
        }
        throw new Error("retry attempt failed");
      }
    };

    try {
      const engine = new HumanizeEngine({
        python: new FakePython(
          manifest([body(1, 0, 3)], 3),
          [warn()]
        ),
        codex,
        chunkConcurrency: 1
      });

      await expect(
        engine.transform({
          jobId: "job-1",
          workspace: test.workspace,
          signal: new AbortController().signal,
          onEvent: event => events.push(event)
        })
      ).rejects.toThrow("retry attempt failed");

      expect(attempts).toEqual([1, 2]);
      expect(
        events.map(event => {
          if (event.type === "progress") return `progress:${event.phase}`;
          if (event.type === "warning") return `warning:${event.code}`;
          return event.type;
        })
      ).toEqual([
        "progress:sanitize",
        "progress:chunk",
        "progress:transform",
        "warning:MODEL_WARNING",
        "warning:CHUNK_RETRY"
      ]);
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("keeps warnings observable when retry attempt two is cancelled", async () => {
    const test = await setup("AAA");
    const controller = new AbortController();
    const attempts: Array<1 | 2> = [];
    const events: TransformEvent[] = [];
    const codex: CodexAdapter = {
      async transform(_inputPath, _outputPath, attempt) {
        attempts.push(attempt);
        if (attempt === 1) {
          return {
            rewrittenText: "BAD",
            warnings: ["first attempt warning"]
          };
        }
        controller.abort();
        return { rewrittenText: "CANCELLED", warnings: [] };
      }
    };

    try {
      const engine = new HumanizeEngine({
        python: new FakePython(
          manifest([body(1, 0, 3)], 3),
          [warn()]
        ),
        codex,
        chunkConcurrency: 1
      });

      await expect(
        engine.transform({
          jobId: "job-1",
          workspace: test.workspace,
          signal: controller.signal,
          onEvent: event => events.push(event)
        })
      ).rejects.toMatchObject({ publicCode: "CLIENT_ABORTED" });

      expect(attempts).toEqual([1, 2]);
      expect(
        events.map(event => {
          if (event.type === "progress") return `progress:${event.phase}`;
          if (event.type === "warning") return `warning:${event.code}`;
          return event.type;
        })
      ).toEqual([
        "progress:sanitize",
        "progress:chunk",
        "progress:transform",
        "warning:MODEL_WARNING",
        "warning:CHUNK_RETRY"
      ]);
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("does not complete the verify work unit when cancellation arrives with the retry gate result", async () => {
    const test = await setup("AAA");
    const controller = new AbortController();
    const events: TransformEvent[] = [];
    let verifyCalls = 0;
    const python: PythonAdapter = {
      async prepare() {
        return manifest([body(1, 0, 3)], 3);
      },
      async restore() {
        return noRestore();
      },
      async verify() {
        verifyCalls += 1;
        if (verifyCalls === 1) return warn();
        controller.abort();
        return ok();
      },
      async reassemble() {
        throw new Error("Cancelled work must not be reassembled");
      }
    };

    try {
      const engine = new HumanizeEngine({
        python,
        codex: new FakeCodex(["BAD", "GOOD"]),
        chunkConcurrency: 1
      });

      await expect(
        engine.transform({
          jobId: "job-1",
          workspace: test.workspace,
          signal: controller.signal,
          onEvent: event => events.push(event)
        })
      ).rejects.toMatchObject({ publicCode: "CLIENT_ABORTED" });

      expect(verifyCalls).toBe(2);
      expect(events).toContainEqual(
        expect.objectContaining({ type: "warning", code: "CHUNK_RETRY" })
      );
      expect(events.filter(
        (event): event is Extract<TransformEvent, { type: "progress" }> =>
          event.type === "progress" &&
          (event.phase === "transform" || event.phase === "verify")
      )).toEqual([
        expect.objectContaining({
          phase: "transform",
          completedUnits: 1,
          totalUnits: 2
        })
      ]);
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

describe("Super Sejong integration", () => {
  it("tells split chunks their position and the document speech level, but not a single chunk", async () => {
    const first = "안내합니다. 신청은 내일까지입니다. ";
    const second = "문의는 메일로 받습니다.";
    const test = await setup(first + second);
    try {
      const contexts: unknown[] = [];
      const codex: CodexAdapter = {
        async transform(inputPath, _outputPath, _attempt, _signal, _settings, _options, _review, chunkContext) {
          contexts.push(chunkContext);
          return { rewrittenText: await readFile(inputPath, "utf8"), warnings: [] };
        }
      };
      const a = Array.from(first).length, b = a + Array.from(second).length;
      const engine = new HumanizeEngine({
        python: new FakePython(manifest([body(1, 0, a), body(2, a, b)], b, "chunked"), [ok(), ok(), ok()]),
        codex,
        chunkConcurrency: 1
      });
      await engine.transform({ jobId: "job-1", workspace: test.workspace, signal: new AbortController().signal, onEvent: () => undefined });
      expect(contexts).toEqual([{ index: 1, total: 2, register: "합쇼체" }, { index: 2, total: 2, register: "합쇼체" }]);

      const single = await setup("AAA");
      try {
        contexts.length = 0;
        await new HumanizeEngine({ python: new FakePython(manifest([body(1, 0, 3)], 3), [ok(), ok()]), codex, chunkConcurrency: 1 })
          .transform({ jobId: "job-1", workspace: single.workspace, signal: new AbortController().signal, onEvent: () => undefined });
        expect(contexts).toEqual([undefined]);
      } finally {
        await single.workspace.cleanup();
        await removeTestRoot(single.outer);
      }
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });

  it("reports gate failure codes, shadow codes, particle repairs and style findings without text", async () => {
    const source = "결론적으로 이를 통해 다양한 효과를 얻는 것이 중요합니다.";
    const test = await setup(source);
    try {
      const engine = new HumanizeEngine({
        python: new FakePython(
          manifest([body(1, 0, Array.from(source).length)], Array.from(source).length),
          [{ ...abort(), hardFailures: ["polarity_changed"] }, { ...ok(), shadowFailures: ["modality_changed"] }, ok()],
          [{ ...noRestore(), repairedParticles: 1 }, { ...noRestore(), repairedParticles: 2 }]
        ),
        codex: new FakeCodex(["첫 시도 결과다.", "그래서 효과를 얻었다."]),
        chunkConcurrency: 1
      });
      const result = await engine.transform({ jobId: "job-1", workspace: test.workspace, signal: new AbortController().signal, onEvent: () => undefined });
      expect(result.diagnostics.hardFailureCounts).toEqual({ polarity_changed: 1 });
      expect(result.diagnostics.shadowFailureCounts).toEqual({ modality_changed: 1 });
      expect(result.diagnostics.repairedParticles).toBe(3);
      expect(result.diagnostics.styleFindingsBefore).toBeGreaterThanOrEqual(3);
      expect(result.diagnostics.styleFindingsAfter).toBe(0);
    } finally {
      await test.workspace.cleanup();
      await removeTestRoot(test.outer);
    }
  });
});
