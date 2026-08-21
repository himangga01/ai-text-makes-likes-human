import { access, writeFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { JobWorkspace } from "../../src/engine/workspace.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

describe("JobWorkspace", () => {
  it("creates only beneath its runtime root and cleanup is idempotent", async () => {
    const testRoot = await makeTestRoot();
    try {
      const workspace = await JobWorkspace.create(testRoot, "job-123");
      await expect(access(workspace.root)).resolves.toBeUndefined();
      expect(workspace.jobId).toBe("job-123");
      expect(workspace.path("01_input.txt").startsWith(testRoot)).toBe(true);
      expect(() => workspace.path("../escape.txt")).toThrow(
        "Unsafe workspace path"
      );
      await writeFile(workspace.path("01_input.txt"), "내용", "utf8");

      await Promise.all([workspace.cleanup(), workspace.cleanup()]);
      await expect(access(workspace.root)).rejects.toThrow();
    } finally {
      await removeTestRoot(testRoot);
    }
  });

  it("rejects a job id containing path separators", async () => {
    const testRoot = await makeTestRoot();
    try {
      await expect(JobWorkspace.create(testRoot, "../escape")).rejects.toThrow(
        "Unsafe job id"
      );
    } finally {
      await removeTestRoot(testRoot);
    }
  });
});
