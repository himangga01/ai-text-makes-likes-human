import path from "node:path";
import { describe, expect, it } from "vitest";
import { loadConfig } from "../../src/config.js";

describe("loadConfig", () => {
  it("uses the approved LAN, queue, timeout, and disk defaults", () => {
    const root = path.resolve("C:/project/2026/ai-text-makes-likes-human");
    const config = loadConfig({}, root);

    expect(config.host).toBe("0.0.0.0");
    expect(config.port).toBe(7882);
    expect(config.maxAcceptedJobs).toBe(3);
    expect(config.maxActiveJobs).toBe(1);
    expect(config.chunkTimeoutMs).toBe(10 * 60 * 1000);
    expect(config.minFreeBytes).toBe(1024 ** 3);
    expect(config.runtimeRoot).toBe(path.join(root, "runtime", "jobs"));
    expect(config.vendorRoot).toBe(path.join(root, "vendor", "humanize-engine"));
  });

  it("rejects a port outside the valid TCP range", () => {
    expect(() => loadConfig({ PORT: "70000" }, process.cwd())).toThrow(
      "PORT must be an integer from 1 to 65535"
    );
  });

  it("starts conservatively with auto-route enabled and serial chunk execution", () => {
    const config = loadConfig({}, process.cwd());

    expect(config.autoRoute).toBe(true);
    expect(config.chunkConcurrency).toBe(1);
  });

  it("disables auto-route only for the exact rollback value zero", () => {
    expect(
      loadConfig({ HUMANIZE_AUTO_ROUTE: "0" }, process.cwd()).autoRoute
    ).toBe(false);
    expect(
      loadConfig({ HUMANIZE_AUTO_ROUTE: "false" }, process.cwd()).autoRoute
    ).toBe(true);
  });

  it.each(["0", "3", "1.5", "fast"])(
    "rejects invalid CODEX_CHUNK_CONCURRENCY=%s",
    value => {
      expect(() =>
        loadConfig({ CODEX_CHUNK_CONCURRENCY: value }, process.cwd())
      ).toThrow("CODEX_CHUNK_CONCURRENCY must be 1 or 2");
    }
  );

  it("allows the benchmark to select concurrency two", () => {
    expect(
      loadConfig({ CODEX_CHUNK_CONCURRENCY: "2" }, process.cwd())
        .chunkConcurrency
    ).toBe(2);
  });
});
