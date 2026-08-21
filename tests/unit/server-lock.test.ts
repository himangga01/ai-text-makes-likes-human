import { access, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { acquireServerLock } from "../../src/runtime/server-lock.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

describe("acquireServerLock", () => {
  it("rejects a second live server without touching active jobs", async () => {
    const root = await makeTestRoot();
    const runtimeRoot = path.join(root, "runtime");
    const activeJob = path.join(runtimeRoot, "jobs", "active-job", "01_input.txt");
    await mkdir(path.dirname(activeJob), { recursive: true });
    await writeFile(activeJob, "active", "utf8");
    const first = await acquireServerLock(runtimeRoot);
    try {
      await expect(acquireServerLock(runtimeRoot)).rejects.toThrow(
        "Portal server is already running"
      );
      await expect(access(activeJob)).resolves.toBeUndefined();
    } finally {
      await first.release();
      await removeTestRoot(root);
    }
  });

  it("reclaims a stale lock and releases idempotently", async () => {
    const root = await makeTestRoot();
    const runtimeRoot = path.join(root, "runtime");
    await mkdir(runtimeRoot, { recursive: true });
    await writeFile(path.join(runtimeRoot, "server.lock"), "99999999\n", "utf8");
    try {
      const lock = await acquireServerLock(runtimeRoot);
      await Promise.all([lock.release(), lock.release()]);
      await expect(access(path.join(runtimeRoot, "server.lock"))).rejects.toThrow();
    } finally {
      await removeTestRoot(root);
    }
  });
});
