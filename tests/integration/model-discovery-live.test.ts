import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { discoverModels } from '../../src/runtime/model-discovery.js';
import { resolveCli } from '../../src/runtime/cli-path.js';

// Opt-in: talks to the real `codex` and `claude` from PATH. Only the model list is requested, never a prompt.
const live = process.env.RUN_LIVE_MODELS === '1' ? describe : describe.skip;

live('live model discovery', () => {
  for (const engine of ['codex', 'claude'] as const) {
    it(`lists ${engine} models from the installed CLI`, async () => {
      const cwd = await mkdtemp(path.join(os.tmpdir(), 'live-models-'));
      try {
        const started = Date.now();
        const catalog = await discoverModels(engine, resolveCli(engine), { cwd });
        const elapsed = Date.now() - started;
        console.log(`${engine} ${catalog.cliVersion ?? '?'} ${elapsed} ms default=${JSON.stringify(catalog.cliDefault)}`
          + `\n  models: ${catalog.models.map(model => `${model.id} (${model.label}: ${model.efforts.join('/')})`).join(', ')}`
          + `\n  excluded: ${JSON.stringify(catalog.excluded)}`);
        expect(catalog.engine).toBe(engine);
        expect(catalog.models.length).toBeGreaterThan(0);
        for (const model of catalog.models) expect(model.efforts.length).toBeGreaterThan(0);
        expect(catalog.cliVersion).toMatch(/^\d+\.\d+\.\d+/);
      } finally {
        await rm(cwd, { recursive: true, force: true });
      }
    }, 60_000);
  }
});
