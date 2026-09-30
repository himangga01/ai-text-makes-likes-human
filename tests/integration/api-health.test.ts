import { describe, expect, it } from "vitest";
import { loadConfig } from "../../src/config.js";
import { createApp } from "../../src/app.js";
import { MODEL_OPTIONS } from '../../src/engine/model-policy.js';
import { TransformQueue } from "../../src/queue/transform-queue.js";
import { close, listen } from "../helpers/http-app.js";

const config = loadConfig({}, process.cwd());

describe("GET /api/health", () => {
  it('refreshes provider readiness instead of retaining the startup login status',async()=>{
    const preflight={ready:false,nodeVersion:'24.19.0',message:'로그인 필요'};
    let count=0;
    const app=createApp({config,queue:new TransformQueue({maxActive:1,maxAccepted:3}),
      engine:{transform:async()=>{throw new Error('not used');}},preflight,
      refreshHealth:async()=>{count++;Object.assign(preflight,{ready:true,message:undefined});return preflight;}});
    const running=await listen(app);
    try {const response=await fetch(`${running.baseUrl}/api/health`);expect(response.status).toBe(200);expect(count).toBe(1);}
    finally {await close(running.server);}
  });
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
        rewriteOptions: expect.arrayContaining([{id:'very-strong',label:'매우 강하게',description:expect.any(String)}]),
        modelOptions: MODEL_OPTIONS,
        modelDefaults: { codex: { model: 'gpt-5.6-sol', effort: 'medium' }, claude: { model: 'claude-fable-5-1', effort: 'high' } },
        checkedAt: expect.any(String),
        documentsAvailable: false,
        status: "ready",
        pid: process.pid,
        engine: "codex-cli",
        engineVersion: "0.149.0",
        humanizeVersion: "2.3.2",
        claudeAvailable: false,
        activeJobs: 0,
        queuedJobs: 0
      });
    } finally {
      await close(running.server);
    }
  });

  it("reports claudeAvailable when a Claude engine is configured", async () => {
    const app = createApp({
      config,
      queue: new TransformQueue({ maxActive: 1, maxAccepted: 3 }),
      engine: { transform: async () => { throw new Error("not used"); } },
      claudeEngine: { transform: async () => { throw new Error("not used"); } },
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
      const body = await response.json();
      expect(body.claudeAvailable).toBe(true);
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
        rewriteOptions: expect.arrayContaining([{id:'very-strong',label:'매우 강하게',description:expect.any(String)}]),
        modelOptions: MODEL_OPTIONS,
        modelDefaults: { codex: { model: 'gpt-5.6-sol', effort: 'medium' }, claude: { model: 'claude-fable-5-1', effort: 'high' } },
        checkedAt: expect.any(String),
        status: "degraded",
        pid: process.pid,
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
