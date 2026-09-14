import { access, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { acquireServerLock } from "../../src/runtime/server-lock.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

describe("acquireServerLock", () => {
  it('does not compete with a stale-lock recovery already in progress', async () => {
    const root=await makeTestRoot();await writeFile(path.join(root,'server.lock'),'99999999\n');
    await mkdir(path.join(root,'server.lock.reclaim'));
    let unexpected:Awaited<ReturnType<typeof acquireServerLock>>|undefined;
    try {
      let error:unknown;try {unexpected=await acquireServerLock(root);}catch(e){error=e;}
      expect(error).toBeInstanceOf(Error);
    } finally {await unexpected?.release();await removeTestRoot(root);}
  });
  it('does not unlink a successor lock on a repeated exit release', async () => {
    const root=await makeTestRoot();
    const first=await acquireServerLock(root);await first.release();
    const second=await acquireServerLock(root);
    try {first.releaseSync();await expect(access(path.join(root,'server.lock'))).resolves.toBeUndefined();}
    finally {await second.release();await removeTestRoot(root);}
  });

  it('does not reclaim a lock whose owner is still being published', async () => {
    const root=await makeTestRoot();await writeFile(path.join(root,'server.lock'),'');
    let unexpected:Awaited<ReturnType<typeof acquireServerLock>>|undefined;
    try {
      let error:unknown;
      try {unexpected=await acquireServerLock(root);} catch(e){error=e;}
      expect(error).toBeInstanceOf(Error);
    } finally {await unexpected?.release();await removeTestRoot(root);}
  });
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

  it("supports synchronous cleanup during the process exit event", async () => {
    const root = await makeTestRoot();
    const runtimeRoot = path.join(root, "runtime");
    try {
      const lock = await acquireServerLock(runtimeRoot);
      lock.releaseSync();
      lock.releaseSync();
      await expect(access(path.join(runtimeRoot, "server.lock"))).rejects.toThrow();
    } finally {
      await removeTestRoot(root);
    }
  });
});
