import { execFileSync } from "node:child_process";
import { closeSync, readFileSync, rmSync } from "node:fs";
import { randomUUID } from 'node:crypto';
import { link, mkdir, open, readFile, rm, rmdir, stat, type FileHandle } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

function processIsAlive(pid: number): boolean {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

// The kernel's per-boot identity decides whether a lock belongs to this boot:
// PIDs are reused after a reboot and clocks can step. Windows has none, so it
// keeps the age-based rule below.
function currentBootId(): string | undefined {
  try {
    if (process.platform === "darwin") return execFileSync("/usr/sbin/sysctl", ["-n", "kern.bootsessionuuid"], { encoding: "utf8", timeout: 2_000 }).trim() || undefined;
    if (process.platform === "linux") return readFileSync("/proc/sys/kernel/random/boot_id", "utf8").trim() || undefined;
  } catch { /* Unreadable: fall back to the age-based rule. */ }
  return undefined;
}

// A lock or recovery marker written before the last boot cannot belong to a
// running server, even if its PID now belongs to another process. The margin
// keeps a forward clock correction from making a live lock look that old.
const BOOT_MARGIN_MS = 10 * 60 * 1000;
async function predatesBoot(file: string): Promise<boolean> {
  try {
    return (await stat(file)).mtimeMs < Date.now() - os.uptime() * 1000 - BOOT_MARGIN_MS;
  } catch {
    return false;
  }
}

export interface ServerLock {
  release(): Promise<void>;
  releaseSync(): void;
}

class FileServerLock implements ServerLock {
  private releasePromise: Promise<void> | undefined;
  private released = false;

  constructor(
    private readonly handle: FileHandle,
    private readonly lockPath: string
  ) {}

  release(): Promise<void> {
    if (this.released) {
      return Promise.resolve();
    }
    this.released = true;
    this.releasePromise ??= (async () => {
      await this.handle.close();
      await rm(this.lockPath, { force: true });
    })();
    return this.releasePromise;
  }

  releaseSync(): void {
    if (this.released) return;
    if (!this.released) {
      this.released = true;
      try {
        closeSync(this.handle.fd);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EBADF") throw error;
      }
    }
    rmSync(this.lockPath, { force: true });
  }
}

export interface ServerLockOptions {
  bootId?: () => string | undefined;
}

export async function acquireServerLock(runtimeRoot: string, options: ServerLockOptions = {}): Promise<ServerLock> {
  const resolvedRoot = path.resolve(runtimeRoot);
  const lockPath = path.join(resolvedRoot, "server.lock");
  await mkdir(resolvedRoot, { recursive: true });
  const bootId = (options.bootId ?? currentBootId)();

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const temporary=path.join(resolvedRoot,`.server-lock-${randomUUID()}.tmp`);
    const handle=await open(temporary,'wx',0o600);
    try {
      // Publish a complete PID (and boot identity) atomically; another startup never
      // observes a partially-written owner. The temporary file is on the same filesystem.
      await handle.writeFile(`${process.pid}\n${bootId ? `${bootId}\n` : ""}`, "utf8");
      await link(temporary,lockPath);
      return new FileServerLock(handle, lockPath);
    } catch (error) {
      await handle.close();
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      // Serialize stale-owner inspection + deletion. Never delete an unknown
      // recovery marker: an interrupted recovery fails closed for inspection.
      const recovery=path.join(resolvedRoot,'server.lock.reclaim');
      try {await mkdir(recovery);} catch(recoveryError) {
        if((recoveryError as NodeJS.ErrnoException).code!=='EEXIST')throw recoveryError;
        if(await predatesBoot(recovery)){await rm(recovery,{recursive:true,force:true});continue;}
        throw new Error('Portal lock recovery is already in progress; inspect server.lock.reclaim after all portal processes stop');
      }
      try {
        let owner:number;let ownerBoot:string|undefined;
        try {
          // `pid\n` (older servers) or `pid\nbootId\n`.
          const [pidLine='',bootLine='']=(await readFile(lockPath,'utf8')).split('\n');
          owner=Number(pidLine.trim());ownerBoot=bootLine.trim()||undefined;
        }
        catch(readError) {
          if((readError as NodeJS.ErrnoException).code==='ENOENT')continue;
          throw readError;
        }
        const ownerGone=Number.isInteger(owner)&&owner>0&&!processIsAlive(owner);
        const stale=ownerBoot&&bootId?ownerBoot!==bootId||ownerGone:await predatesBoot(lockPath)||ownerGone;
        if(!stale)throw new Error('Portal server is already running or lock ownership is unknown');
        await rm(lockPath,{force:true});
      } finally {await rmdir(recovery);}
    } finally {await rm(temporary,{force:true});}
  }

  throw new Error("Unable to acquire portal server lock");
}
