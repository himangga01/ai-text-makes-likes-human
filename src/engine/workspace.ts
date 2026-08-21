import { mkdir, rm } from "node:fs/promises";
import path from "node:path";

const SAFE_JOB_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/u;

export class JobWorkspace {
  readonly root: string;
  private cleanupPromise: Promise<void> | undefined;

  private constructor(
    runtimeRoot: string,
    public readonly jobId: string
  ) {
    this.root = path.resolve(runtimeRoot, jobId);
  }

  static async create(
    runtimeRoot: string,
    jobId: string
  ): Promise<JobWorkspace> {
    if (!SAFE_JOB_ID.test(jobId)) {
      throw new Error("Unsafe job id");
    }

    const workspace = new JobWorkspace(runtimeRoot, jobId);
    const resolvedRuntime = path.resolve(runtimeRoot);
    if (!workspace.root.startsWith(`${resolvedRuntime}${path.sep}`)) {
      throw new Error("Unsafe job id");
    }

    await mkdir(resolvedRuntime, { recursive: true });
    await mkdir(workspace.root, { mode: 0o700 });
    return workspace;
  }

  path(relativePath: string): string {
    if (path.isAbsolute(relativePath)) {
      throw new Error("Unsafe workspace path");
    }
    const resolved = path.resolve(this.root, relativePath);
    if (!resolved.startsWith(`${this.root}${path.sep}`)) {
      throw new Error("Unsafe workspace path");
    }
    return resolved;
  }

  cleanup(): Promise<void> {
    this.cleanupPromise ??= rm(this.root, {
      recursive: true,
      force: true,
      maxRetries: 3,
      retryDelay: 100
    });
    return this.cleanupPromise;
  }
}
