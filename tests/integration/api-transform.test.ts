import { readdir, writeFile } from "node:fs/promises";
import type { Server } from "node:http";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import type { HumanizeRequest, HumanizeResult } from "../../src/engine/humanize-engine.js";
import { loadConfig } from "../../src/config.js";
import { createApp, type AppLogger } from "../../src/app.js";
import { TransformQueue } from "../../src/queue/transform-queue.js";
import { EngineError } from "../../src/engine/errors.js";
import { close, listen } from "../helpers/http-app.js";
import { deferred } from "../helpers/deferred.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

const servers: Server[] = [];
afterEach(async () => {
  await Promise.all(servers.splice(0).map(close));
});

function ready() {
  return {
    ready: true as const,
    nodeVersion: "24.19.0",
    pythonVersion: "3.14.7",
    codexVersion: "0.149.0",
    humanizeVersion: "2.3.2"
  };
}

async function createTestApp(engine: { transform(request: HumanizeRequest): Promise<HumanizeResult> }, logger?: AppLogger) {
  const outer = await makeTestRoot();
  const config = {
    ...loadConfig({}, process.cwd()),
    runtimeRoot: path.join(outer, "jobs")
  };
  const queue = new TransformQueue({ maxActive: 1, maxAccepted: 3 });
  const app = createApp({ config, queue, engine, preflight: ready(), logger });
  const running = await listen(app);
  servers.push(running.server);
  return { ...running, outer, config, queue };
}

function parseNdjson(text: string): Array<Record<string, unknown>> {
  return text.trim().split("\n").filter(Boolean).map(line => JSON.parse(line));
}

describe("POST /api/transform", () => {
  it("streams a verified result and removes its workspace without logging content", async () => {
    const logs: unknown[] = [];
    const source = "비밀 원문은 1,200명을 언급한다.";
    const test = await createTestApp(
      {
        async transform(request) {
          request.onEvent({
            type: "progress",
            phase: "transform",
            current: 1,
            total: 1,
            message: "1/1 구간을 다듬는 중입니다."
          });
          const finalPath = request.workspace.path("03_reassembled.md");
          await writeFile(finalPath, "자연스러운 결과는 1,200명을 언급한다.", "utf8");
          return {
            finalPath,
            sourceChars: Array.from(source).length,
            outputChars: 25,
            chunks: 1,
            warnings: []
          };
        }
      },
      { info: value => logs.push(value), error: value => logs.push(value) }
    );
    try {
      const response = await fetch(`${test.baseUrl}/api/transform`, {
        method: "POST",
        headers: { "content-type": "text/plain; charset=utf-8" },
        body: source
      });
      expect(response.status).toBe(200);
      expect(response.headers.get("content-type")).toContain("application/x-ndjson");
      expect(response.headers.get("cache-control")).toBe("no-store");
      expect(response.headers.get("x-content-type-options")).toBe("nosniff");
      const events = parseNdjson(await response.text());

      expect(events.map(event => event.type)).toEqual([
        "accepted",
        "progress",
        "result-start",
        "result-delta",
        "done"
      ]);
      expect(events.find(event => event.type === "result-delta")?.text).toBe(
        "자연스러운 결과는 1,200명을 언급한다."
      );
      expect(await readdir(test.config.runtimeRoot)).toEqual([]);
      expect(JSON.stringify(logs)).not.toContain(source);
      expect(JSON.stringify(logs)).not.toContain("자연스러운 결과");
    } finally {
      await removeTestRoot(test.outer);
    }
  });

  it("returns an NDJSON EMPTY_INPUT error and releases capacity", async () => {
    const test = await createTestApp({
      transform: async () => {
        throw new Error("engine must not run");
      }
    });
    try {
      const response = await fetch(`${test.baseUrl}/api/transform`, {
        method: "POST",
        headers: { "content-type": "text/plain" },
        body: " \n\t"
      });
      const events = parseNdjson(await response.text());
      expect(events.at(-1)).toMatchObject({
        type: "error",
        code: "EMPTY_INPUT"
      });
      expect(test.queue.stats()).toEqual({ active: 0, queued: 0, reserved: 0 });
    } finally {
      await removeTestRoot(test.outer);
    }
  });

  it("rejects a fourth request before reading its body", async () => {
    const test = await createTestApp({
      transform: async () => {
        throw new Error("not used");
      }
    });
    try {
      test.queue.reserve("one");
      test.queue.reserve("two");
      test.queue.reserve("three");
      const response = await fetch(`${test.baseUrl}/api/transform`, {
        method: "POST",
        headers: { "content-type": "text/plain" },
        body: "이 본문은 읽히면 안 된다."
      });
      expect(response.status).toBe(429);
      expect(await response.json()).toEqual({
        code: "QUEUE_FULL",
        message: "현재 3건이 처리 중입니다. 잠시 후 다시 시도해 주세요."
      });
    } finally {
      await removeTestRoot(test.outer);
    }
  });

  it("aborts active work and deletes its workspace when the browser disconnects", async () => {
    const started = deferred<void>();
    const cancelled = deferred<void>();
    const test = await createTestApp({
      transform: async request => {
        started.resolve();
        return new Promise((_resolve, reject) => {
          const stop = () => {
            cancelled.resolve();
            reject(new EngineError("CLIENT_ABORTED", true, "client left"));
          };
          if (request.signal.aborted) stop();
          else request.signal.addEventListener("abort", stop, { once: true });
        });
      }
    });
    const controller = new AbortController();
    try {
      const response = await fetch(`${test.baseUrl}/api/transform`, {
        method: "POST",
        headers: { "content-type": "text/plain" },
        body: "연결 종료 테스트 원문",
        signal: controller.signal
      });
      await started.promise;
      controller.abort();
      await response.text().catch(() => undefined);

      await Promise.race([
        cancelled.promise,
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error("engine was not cancelled")), 1_000)
        )
      ]);
      for (let attempt = 0; attempt < 20; attempt += 1) {
        if ((await readdir(test.config.runtimeRoot)).length === 0) break;
        await new Promise(resolve => setTimeout(resolve, 25));
      }
      expect(await readdir(test.config.runtimeRoot)).toEqual([]);
      expect(test.queue.stats()).toEqual({ active: 0, queued: 0, reserved: 0 });
    } finally {
      controller.abort();
      await removeTestRoot(test.outer);
    }
  });
});
