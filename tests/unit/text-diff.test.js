import { describe, expect, it } from "vitest";
import { createTextDiffEngine, diffText } from "../../public/text-diff.js";

function sourceFrom(segments) {
  return segments
    .filter(segment => segment.type !== "insert")
    .map(segment => segment.text)
    .join("");
}

function targetFrom(segments) {
  return segments
    .filter(segment => segment.type !== "delete")
    .map(segment => segment.text)
    .join("");
}

describe("diffText", () => {
  it.each([
    ["identical", "같은 문장", "같은 문장"],
    ["append", "문장", "문장입니다"],
    ["delete", "아주 긴 문장", "문장"],
    ["replacement", "오늘은 맑습니다.", "오늘은 흐립니다."],
    ["Korean morphology", "문장을 자연스럽게 고칩니다.", "문장을 더 자연스럽게 다듬었습니다."],
    ["repeated anchors", "하나 둘 하나 셋 하나", "하나 둘 하나 넷 하나"],
    ["normalized line endings", "첫 줄\n둘째 줄\n", "첫 줄\n새 둘째 줄\n"],
    ["spaces and blank lines", "앞  공백\n\n끝 ", "앞 공백\n새 줄\n끝  "],
    ["markup-like text", '<img src=x onerror="alert(1)">', '<script>alert(2)</script>']
  ])("reconstructs both inputs exactly for %s", (_name, source, target) => {
    const result = diffText(source, target);

    expect(sourceFrom(result.segments)).toBe(source);
    expect(targetFrom(result.segments)).toBe(target);
    expect(result.segments.every(segment => segment.text.length > 0)).toBe(true);
  });

  it("keeps ZWJ emoji and combining sequences whole while refining a replacement", () => {
    const family = "👨‍👩‍👧‍👦";
    const technologist = "👩‍💻";
    const combining = "e\u0301";
    const result = diffText(`A${family}${combining}Z`, `A${technologist}${combining}Z`);

    expect(result.segments).toEqual([
      { type: "equal", text: "A" },
      { type: "delete", text: family },
      { type: "insert", text: technologist },
      { type: "equal", text: `${combining}Z` }
    ]);
  });

  it.each([
    ["10k", "가".repeat(5_000), "나".repeat(5_000)],
    ["50k", "가".repeat(25_000), "나".repeat(25_000)]
  ])("falls back truthfully within the compute budget for %s all-changed input", (_name, source, target) => {
    const startedAt = performance.now();
    const result = diffText(source, target, {
      maxOperations: 2_000,
      maxTimeMs: 500,
      maxDisplayNodes: 5_000
    });

    expect(performance.now() - startedAt).toBeLessThan(500);
    expect(result.coarse).toBe(true);
    expect(result.notice).toMatch(/간략|한도/);
    expect(result.displayNodes).toBeLessThanOrEqual(5_000);
    expect(sourceFrom(result.segments)).toBe(source);
    expect(targetFrom(result.segments)).toBe(target);
    expect(result.segments.some(segment => segment.type === "delete")).toBe(true);
    expect(result.segments.some(segment => segment.type === "insert")).toBe(true);
  });

  it("uses a truthful coarse replacement when the display-node limit is exceeded", () => {
    const source = "a1 b2 c3 d4";
    const target = "aX bY cZ dW";
    const result = diffText(source, target, { maxDisplayNodes: 3 });

    expect(result.coarse).toBe(true);
    expect(result.displayNodes).toBe(2);
    expect(sourceFrom(result.segments)).toBe(source);
    expect(targetFrom(result.segments)).toBe(target);
  });
});

class ControlledWorker {
  static instances = [];

  constructor() {
    this.listeners = new Map();
    ControlledWorker.instances.push(this);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  postMessage(message) {
    this.request = message;
  }

  terminate() {
    this.terminated = true;
  }

  emit(type, value) {
    for (const listener of this.listeners.get(type) ?? []) listener(value);
  }
}

describe("createTextDiffEngine", () => {
  it("computes small inputs directly and keeps the exact reconstruction contract", async () => {
    const engine = createTextDiffEngine({
      workerThreshold: 10_000,
      workerFactory: () => new ControlledWorker()
    });

    const result = await engine.compute("원문", "결과문");

    expect(sourceFrom(result.segments)).toBe("원문");
    expect(targetFrom(result.segments)).toBe("결과문");
  });

  it("rejects a superseded job and ignores its stale worker result", async () => {
    ControlledWorker.instances = [];
    const engine = createTextDiffEngine({
      workerThreshold: 1,
      workerFactory: () => new ControlledWorker()
    });
    const first = engine.compute("이전 원문", "이전 결과");
    const firstWorker = ControlledWorker.instances[0];
    const second = engine.compute("최신 원문", "최신 결과");
    const secondWorker = ControlledWorker.instances[1];

    await expect(first).rejects.toMatchObject({ name: "AbortError" });
    firstWorker.emit("message", {
      data: {
        type: "result",
        generation: firstWorker.request.generation,
        result: diffText("이전 원문", "이전 결과")
      }
    });
    secondWorker.emit("message", {
      data: {
        type: "result",
        generation: secondWorker.request.generation,
        result: diffText("최신 원문", "최신 결과")
      }
    });

    const result = await second;
    expect(sourceFrom(result.segments)).toBe("최신 원문");
    expect(targetFrom(result.segments)).toBe("최신 결과");
  });

  it("cancels an active worker job without accepting later output", async () => {
    ControlledWorker.instances = [];
    const engine = createTextDiffEngine({
      workerThreshold: 1,
      workerFactory: () => new ControlledWorker()
    });
    const pending = engine.compute("취소할 원문", "취소할 결과");
    const worker = ControlledWorker.instances[0];

    engine.cancel();
    worker.emit("message", {
      data: {
        type: "result",
        generation: worker.request.generation,
        result: diffText("취소할 원문", "취소할 결과")
      }
    });

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
