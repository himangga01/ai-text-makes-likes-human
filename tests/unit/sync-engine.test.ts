import { execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

async function fixture(dirty: boolean) {
  const root = await makeTestRoot("sync-preflight-");
  const source = path.join(root, "source");
  const service = path.join(root, "portal");
  await mkdir(path.join(source, "skills/humanize-korean"), { recursive: true });
  await mkdir(path.join(source, "scripts"));
  await writeFile(path.join(source, "skills/humanize-korean/SKILL.md"), '---\nversion: "2.3.2"\n---\n');
  await writeFile(path.join(source, "scripts/prepare_monolith_input.py"), "upstream content\n");
  const git = (...args: string[]) => execFileSync("git", ["-C", source, ...args], { windowsHide: true, encoding: "utf8" }).trim();
  git("init", "-q"); git("add", ".");
  git("-c", "user.name=Sync Fixture", "-c", "user.email=sync-test@example.invalid", "commit", "-qm", "fixture");
  const sha = git("rev-parse", "HEAD");
  await mkdir(path.join(service, "scripts"), { recursive: true });
  await mkdir(path.join(service, "vendor/humanize-engine/scripts"), { recursive: true });
  const target = path.join(service, "vendor/humanize-engine/scripts/prepare_monolith_input.py");
  await writeFile(target, "original portal content\n");
  const script = (await readFile("scripts/sync-engine.ps1", "utf8")).replace(/\$expectedCommit = '[0-9a-f]+'/u, `$expectedCommit = '${sha}'`);
  const scriptPath = path.join(service, "scripts/sync-engine.ps1");
  await writeFile(scriptPath, script);
  if (dirty) await writeFile(path.join(source, "scripts/prepare_monolith_input.py"), "uncommitted change\n");
  return { root, source, target, scriptPath };
}

describe.skipIf(process.platform !== "win32")("engine sync input validation", () => {
  it.each([false, true])("preserves vendor when source is invalid (dirty=%s)", async dirty => {
    const test = await fixture(dirty);
    try {
      let error: any;
      try { execFileSync("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", test.scriptPath, "-Source", test.source], { windowsHide: true, encoding: "utf8", stdio: "pipe" }); }
      catch (caught) { error = caught; }
      expect(error).toBeDefined();
      expect(String(error.stderr)).toContain(dirty ? "Uncommitted upstream changes" : "Required upstream file is missing");
      expect(await readFile(test.target, "utf8")).toBe("original portal content\n");
    } finally { await removeTestRoot(test.root); }
  });
});
