import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { loadConfig } from "../../src/config.js";
import { createApp } from "../../src/app.js";
import { FALLBACK_MODEL_OPTIONS, resetModelCatalog, type EngineChoice } from '../../src/engine/model-policy.js';
import type { HumanizeRequest } from "../../src/engine/humanize-engine.js";
import { ModelCatalogService } from "../../src/runtime/model-catalog.js";
import { ModelDiscoveryError, type DiscoveredCatalog } from "../../src/runtime/model-discovery.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";
import { TransformQueue } from "../../src/queue/transform-queue.js";
import { close, listen } from "../helpers/http-app.js";

const config = loadConfig({}, process.cwd());
afterEach(() => resetModelCatalog());

describe("GET /api/health", () => {
  it('returns a fixed error when a readiness probe throws an internal path', async () => {
    const queue = new TransformQueue({ maxActive: 1, maxAccepted: 3 });
    const app = createApp({ config, queue,
      engine: { transform: async () => { throw new Error('not used'); } },
      preflight: { ready: false, nodeVersion: '24.19.0' },
      refreshHealth: async () => { throw new Error('비밀 경로 /private/auth.json'); }
    });
    const running = await listen(app);
    try {
      const response = await fetch(`${running.baseUrl}/api/health`);
      const body = await response.text();
      expect(response.status).toBe(500);
      expect(body).toContain('INTERNAL_ERROR');
      expect(body).not.toContain('/private/auth.json');
    } finally { await close(running.server); }
  });
  it('serves supervisor status without waiting for provider or Office probes', async () => {
    const queue = new TransformQueue({ maxActive: 1, maxAccepted: 3 });
    let probes = 0;
    const app = createApp({ config, queue,
      engine: { transform: async () => { throw new Error('not used'); } },
      preflight: { ready: false, nodeVersion: '24.19.0' },
      refreshHealth: async () => { probes++; throw new Error('slow or unavailable CLI'); }
    });
    const running = await listen(app);
    try {
      const response = await fetch(`${running.baseUrl}/api/status`);
      expect(response.status).toBe(200);
      expect(await response.json()).toMatchObject({ status: 'degraded', pid: process.pid, activeJobs: 0, queuedJobs: 0 });
      expect(probes).toBe(0);
    } finally { await close(running.server); }
  });
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
        modelOptions: FALLBACK_MODEL_OPTIONS,
        modelDefaults: { codex: { model: 'gpt-6.1-sol', effort: 'high' }, claude: { model: 'claude-opus-5-5', effort: 'xhigh' } },
        inputLimits: { maxInputChars: 100000, maxTextFileBytes: 1048576 },
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
        modelOptions: FALLBACK_MODEL_OPTIONS,
        modelDefaults: { codex: { model: 'gpt-6.1-sol', effort: 'high' }, claude: { model: 'claude-opus-5-5', effort: 'xhigh' } },
        inputLimits: { maxInputChars: 100000, maxTextFileBytes: 1048576 },
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

describe("live model catalog", () => {
  const nova = { id: "gpt-7-nova", label: "GPT-7 Nova", efforts: ["low", "medium", "high"] };
  const ready = { ready: true, nodeVersion: "24.19.0", pythonVersion: "3.14.7", codexVersion: "0.167.0", humanizeVersion: "2.3.2" };
  // A fake discovery answering with whatever the CLI offers at the time; no list means the CLI is missing.
  function catalogOf(offered: Partial<Record<EngineChoice, DiscoveredCatalog["models"]>>) {
    const calls: EngineChoice[] = [];
    const service = new ModelCatalogService({ logger: { info() {}, error() {} }, discover: async engine => {
      calls.push(engine);
      const models = offered[engine];
      if (!models) throw new ModelDiscoveryError("spawn", "no CLI");
      return { engine, models, excluded: [], cliVersion: "0.167.0" };
    } });
    return { service, calls, offered };
  }

  it("serves the live list, its defaults and the catalog status from both health branches", async () => {
    const { service } = catalogOf({ codex: [nova] });
    await service.refresh("codex");
    await service.refresh("claude");
    for (const preflight of [ready, { ready: false, nodeVersion: "24.19.0", message: "로그인 필요" }]) {
      const app = createApp({ config, queue: new TransformQueue({ maxActive: 1, maxAccepted: 3 }), modelCatalog: service,
        engine: { transform: async () => { throw new Error("not used"); } }, preflight });
      const running = await listen(app);
      try {
        const response = await fetch(`${running.baseUrl}/api/health`);
        expect(response.status).toBe(preflight.ready ? 200 : 503);
        expect(await response.json()).toMatchObject({
          modelOptions: { codex: [nova], claude: FALLBACK_MODEL_OPTIONS.claude },
          modelDefaults: { codex: { model: "gpt-7-nova", effort: "high" }, claude: { model: "claude-opus-5-5", effort: "xhigh" } },
          modelCatalog: { codex: { source: "live", checkedAt: expect.any(String), cliVersion: "0.167.0" }, claude: { source: "fallback", lastError: "spawn" } }
        });
      } finally { await close(running.server); }
    }
  });

  it("waits for the first discovery so a client right after start-up sees the live list", async () => {
    const { service } = catalogOf({ codex: [nova] });
    service.refreshIfStale({ codex: { ready: true, installed: true, authenticated: true, version: "0.167.0", message: "" },
      claude: { ready: false, installed: false, authenticated: false, message: "" } });
    const app = createApp({ config, queue: new TransformQueue({ maxActive: 1, maxAccepted: 3 }), modelCatalog: service,
      engine: { transform: async () => { throw new Error("not used"); } }, preflight: ready });
    const running = await listen(app);
    try {
      const body = await (await fetch(`${running.baseUrl}/api/health`)).json();
      expect(body.modelOptions.codex).toEqual([nova]);
    } finally { await close(running.server); }
  });

  it("accepts a transform naming a model only the next discovery knows, and still refuses an unknown one", async () => {
    const outer = await makeTestRoot();
    const { service, calls, offered } = catalogOf({ codex: FALLBACK_MODEL_OPTIONS.codex });
    const seen: HumanizeRequest["settings"][] = [];
    const app = createApp({ config: { ...config, runtimeRoot: path.join(outer, "jobs") }, queue: new TransformQueue({ maxActive: 1, maxAccepted: 3 }),
      modelCatalog: service, preflight: ready, logger: { info() {}, error() {} },
      engine: { transform: async request => { seen.push(request.settings); throw new Error("stop after the settings check"); } } });
    const running = await listen(app);
    const post = (query: string) => fetch(`${running.baseUrl}/api/transform?${query}`, { method: "POST", headers: { "content-type": "text/plain" }, body: "원문입니다." });
    try {
      // The CLI started offering gpt-7-nova after the list was served; the request itself triggers the discovery.
      await service.refresh("codex");
      expect(calls).toEqual(["codex"]);
      offered.codex = [...FALLBACK_MODEL_OPTIONS.codex, nova];
      const accepted = await post("engine=codex&model=gpt-7-nova&effort=medium");
      expect(accepted.status).toBe(200);
      await accepted.text();
      expect(seen).toEqual([{ model: "gpt-7-nova", effort: "medium" }]);
      expect(calls).toEqual(["codex", "codex"]);
      const refused = await post("engine=codex&model=gpt-9-unknown&effort=low");
      expect(refused.status).toBe(400);
      expect(await refused.json()).toEqual({ code: "INVALID_MODEL_SETTINGS", message: "선택한 CLI에서 지원하는 모델과 추론 레벨을 선택해 주세요." });
      // Within 30 seconds of the last forced discovery, another unknown id costs no further discovery.
      expect(calls).toEqual(["codex", "codex"]);
      expect(seen).toHaveLength(1);
    } finally { await close(running.server); await removeTestRoot(outer); }
  });
});
