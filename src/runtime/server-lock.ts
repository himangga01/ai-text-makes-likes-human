import { closeSync, rmSync } from "node:fs";
import { randomUUID } from 'node:crypto';
import { link, mkdir, open, readFile, rm, rmdir, type FileHandle } from "node:fs/promises";
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

export async function acquireServerLock(runtimeRoot: string): Promise<ServerLock> {
  const resolvedRoot = path.resolve(runtimeRoot);
  const lockPath = path.join(resolvedRoot, "server.lock");
  await mkdir(resolvedRoot, { recursive: true });

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const temporary=path.join(resolvedRoot,`.server-lock-${randomUUID()}.tmp`);
    const handle=await open(temporary,'wx',0o600);
    try {
      // Publish a complete PID atomically; another startup never observes a
      // partially-written owner. The temporary file is on the same filesystem.
      await handle.writeFile(`${process.pid}\n`, "utf8");
      await link(temporary,lockPath);
      return new FileServerLock(handle, lockPath);
    } catch (error) {
      await handle.close();
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      // Serialize stale-owner inspection + deletion. Never delete an unknown
      // recovery marker: an interrupted recovery fails closed for inspection.
      const recovery=path.join(resolvedRoot,'server.lock.reclaim');
      try {await mkdir(recovery);} catch(recoveryError) {
        if((recoveryError as NodeJS.ErrnoException).code==='EEXIST')throw new Error('Portal lock recovery is already in progress; inspect server.lock.reclaim after all portal processes stop');
        throw recoveryError;
      }
      try {
        let owner:number;
        try {owner=Number((await readFile(lockPath,'utf8')).trim());}
        catch(readError) {
          if((readError as NodeJS.ErrnoException).code==='ENOENT')continue;
          throw readError;
        }
        if(!Number.isInteger(owner)||owner<=0||processIsAlive(owner))throw new Error('Portal server is already running or lock ownership is unknown');
        await rm(lockPath,{force:true});
      } finally {await rmdir(recovery);}
    } finally {await rm(temporary,{force:true});}
  }

  throw new Error("Unable to acquire portal server lock");
}
