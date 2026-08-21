import path from "node:path";
import { describe, expect, it } from "vitest";
import { loadConfig } from "../../src/config.js";

describe("loadConfig", () => {
  it("uses the approved LAN, queue, timeout, and disk defaults", () => {
    const root = path.resolve("C:/project/2026/ai-text-makes-likes-human");
    const config = loadConfig({}, root);

    expect(config.host).toBe("0.0.0.0");
    expect(config.port).toBe(3210);
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
});
