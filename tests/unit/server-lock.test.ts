import { access, mkdir, readFile, utimes, writeFile } from "node:fs/promises";
import os from "node:os";
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

  it("treats a lock from before the last boot as stale even when its PID was reused", async () => {
    const root = await makeTestRoot();
    const beforeBoot = new Date(Date.now() - os.uptime() * 1000 - 3_600_000);
    try {
      // process.pid is alive: after a reboot an unrelated process can own the old PID.
      await writeFile(path.join(root, "server.lock"), `${process.pid}\n`, "utf8");
      await utimes(path.join(root, "server.lock"), beforeBoot, beforeBoot);
      await mkdir(path.join(root, "server.lock.reclaim"));
      await utimes(path.join(root, "server.lock.reclaim"), beforeBoot, beforeBoot);
      const lock = await acquireServerLock(root);
      await lock.release();
      // A lock written during this boot with a live PID still means a running server.
      await writeFile(path.join(root, "server.lock"), `${process.pid}\n`, "utf8");
      await expect(acquireServerLock(root)).rejects.toThrow("Portal server is already running");
    } finally {
      await removeTestRoot(root);
    }
  });

  it("records the boot identity and reclaims a lock from another boot at once", async () => {
    const root = await makeTestRoot();
    try {
      const first = await acquireServerLock(root, { bootId: () => "boot-a" });
      expect(await readFile(path.join(root, "server.lock"), "utf8")).toBe(`${process.pid}\nboot-a\n`);
      await first.release();
      // A reboot moments after the lock was written: the PID is live again, but the boot differs.
      await writeFile(path.join(root, "server.lock"), `${process.pid}\nboot-a\n`, "utf8");
      const second = await acquireServerLock(root, { bootId: () => "boot-b" });
      await second.release();
    } finally {
      await removeTestRoot(root);
    }
  });

  it("trusts a matching boot identity over the lock's age", async () => {
    const root = await makeTestRoot();
    const beforeBoot = new Date(Date.now() - os.uptime() * 1000 - 3_600_000);
    try {
      // A forward clock step can make a live lock look older than the boot.
      await writeFile(path.join(root, "server.lock"), `${process.pid}\nboot-a\n`, "utf8");
      await utimes(path.join(root, "server.lock"), beforeBoot, beforeBoot);
      await expect(acquireServerLock(root, { bootId: () => "boot-a" })).rejects.toThrow("Portal server is already running");
      // Without a readable current boot identity the old pid + age rules apply.
      await writeFile(path.join(root, "server.lock"), `${process.pid}\nboot-a\n`, "utf8");
      await expect(acquireServerLock(root, { bootId: () => undefined })).rejects.toThrow("Portal server is already running");
    } finally {
      await removeTestRoot(root);
    }
  });

  it("reads this machine's boot identity where the platform exposes one", async () => {
    const root = await makeTestRoot();
    try {
      const lock = await acquireServerLock(root);
      const lines = (await readFile(path.join(root, "server.lock"), "utf8")).split("\n");
      expect(lines[0]).toBe(String(process.pid));
      if (process.platform === "darwin" || process.platform === "linux") expect(lines[1]).toMatch(/^[0-9A-Fa-f-]{32,}$/);
      await lock.release();
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
