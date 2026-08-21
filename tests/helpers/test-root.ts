import { mkdir, mkdtemp, rm } from "node:fs/promises";
import path from "node:path";

const parent = path.resolve("runtime", "test-tmp");

export async function makeTestRoot(prefix = "case-"): Promise<string> {
  await mkdir(parent, { recursive: true });
  return mkdtemp(path.join(parent, prefix));
}

export async function removeTestRoot(root: string): Promise<void> {
  await rm(root, { recursive: true, force: true, maxRetries: 3 });
}
