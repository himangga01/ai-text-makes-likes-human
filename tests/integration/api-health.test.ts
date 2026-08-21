import { describe, expect, it } from "vitest";
import { loadConfig } from "../../src/config.js";
import { createApp } from "../../src/app.js";
import { TransformQueue } from "../../src/queue/transform-queue.js";
import { close, listen } from "../helpers/http-app.js";

const config = loadConfig({}, process.cwd());

describe("GET /api/health", () => {
  it("returns public readiness and live queue counts", async () => {
    const queue = new TransformQueue({ maxActive: 1, maxAccepted: 3 });
    const app = createApp({
      config,
      queue,
      engine: { transform: async () => { throw new Error("not used"); } },
      preflight: {
        ready: true,
        nodeVersion: "24.19.0",
        pythonVersion: "3.14.7",
        codexVersion: "0.149.0",
        humanizeVersion: "2.3.2"
      }
    });
    const running = await listen(app);
    try {
      const response = await fetch(`${running.baseUrl}/api/health`);
      expect(response.status).toBe(200);
      expect(await response.json()).toEqual({
        status: "ready",
        engine: "codex-cli",
        engineVersion: "0.149.0",
        humanizeVersion: "2.3.2",
        activeJobs: 0,
        queuedJobs: 0
      });
    } finally {
      await close(running.server);
    }
  });

  it("returns 503 without exposing private diagnostics when degraded", async () => {
    const app = createApp({
      config,
      queue: new TransformQueue({ maxActive: 1, maxAccepted: 3 }),
      engine: { transform: async () => { throw new Error("not used"); } },
      preflight: {
        ready: false,
        nodeVersion: "24.19.0",
        errorCode: "ENGINE_UNAVAILABLE",
        message: "서버의 Codex 로그인이 필요합니다."
      }
    });
    const running = await listen(app);
    try {
      const response = await fetch(`${running.baseUrl}/api/health`);
      expect(response.status).toBe(503);
      const body = await response.json();
      expect(body).toEqual({
        status: "degraded",
        errorCode: "ENGINE_UNAVAILABLE",
        message: "서버의 Codex 로그인이 필요합니다.",
        activeJobs: 0,
        queuedJobs: 0
      });
      expect(JSON.stringify(body)).not.toContain("C:\\Users");
    } finally {
      await close(running.server);
    }
  });
});
