import { mkdir, open, readFile, rm, type FileHandle } from "node:fs/promises";
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
}

class FileServerLock implements ServerLock {
  private releasePromise: Promise<void> | undefined;

  constructor(
    private readonly handle: FileHandle,
    private readonly lockPath: string
  ) {}

  release(): Promise<void> {
    this.releasePromise ??= (async () => {
      await this.handle.close();
      await rm(this.lockPath, { force: true });
    })();
    return this.releasePromise;
  }
}

export async function acquireServerLock(runtimeRoot: string): Promise<ServerLock> {
  const resolvedRoot = path.resolve(runtimeRoot);
  const lockPath = path.join(resolvedRoot, "server.lock");
  await mkdir(resolvedRoot, { recursive: true });

  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const handle = await open(lockPath, "wx", 0o600);
      await handle.writeFile(`${process.pid}\n`, "utf8");
      return new FileServerLock(handle, lockPath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;

      let owner = 0;
      try {
        owner = Number.parseInt(await readFile(lockPath, "utf8"), 10);
      } catch (readError) {
        if ((readError as NodeJS.ErrnoException).code !== "ENOENT") {
          throw readError;
        }
        continue;
      }
      if (processIsAlive(owner)) {
        throw new Error("Portal server is already running");
      }
      await rm(lockPath, { force: true });
    }
  }

  throw new Error("Unable to acquire portal server lock");
}
