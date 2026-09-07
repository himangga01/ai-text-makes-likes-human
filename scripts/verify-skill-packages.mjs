import { execFileSync, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, writeFile, readdir } from "node:fs/promises";
import path from "node:path";
const parent = path.resolve("runtime/test-tmp"); await mkdir(parent, { recursive: true });
const pkg = JSON.parse(await readFile("package.json", "utf8"));
for (const host of ["Claude", "Codex"]) {
  const root = await mkdtemp(path.join(parent, "skill-package-"));
  const installArgs = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.resolve("scripts/install-humanize-skill.ps1"), "-HostName", host, "-Scope", "Project", "-ProjectRoot", root,
    "-Archive", path.resolve("release", `humanize-kr-${host.toLowerCase()}-${pkg.version}-win-x64.zip`)];
  execFileSync("powershell.exe", installArgs, { windowsHide: true });
  const second = execFileSync("powershell.exe", installArgs, { windowsHide: true, encoding: "utf8" });
  if (!second.includes("Already installed")) throw new Error("Installer is not idempotent");
  const skill = path.join(root, host === "Claude" ? ".claude" : ".agents", "skills", "humanize-kr");
  const python = path.join(skill, "python/python.exe");
  const gateway = path.join(skill, "engine_runtime/skill_gateway.py");
  const jobs = path.join(root, "jobs");
  const source = path.join(root, "source.md"); const output = path.join(root, "result.md");
  const input = "# 문서\n\n회의 참석자는 12명이었다. 회의 내용을 문서로 남겼다. 다음 문장은 그대로 둔다. 😀\n";
  await writeFile(source, input, "utf8");
  function call(...args) {
    const result = spawnSync(python, [gateway, "--workspace-root", jobs, ...args], { cwd: root, windowsHide: true, encoding: "utf8", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PATH: path.join(process.env.SystemRoot ?? "C:/Windows", "System32") } });
    if (result.status !== 0) throw new Error(result.stdout + result.stderr);
    return JSON.parse(result.stdout);
  }
  let state = call("prepare", "--input", source);
  while (state.status === "rewrite") {
    await writeFile(state.responsePath, JSON.stringify({ rewrittenText: await readFile(state.inputPath, "utf8"), warnings: [] }));
    state = call("accept", "--job", state.job, "--chunk", String(state.chunk), "--attempt", String(state.attempt), "--source-hash", state.sourceHash, "--response", state.responsePath);
  }
  call("finalize", "--job", state.job, "--output", output);
  if ((await readFile(output, "utf8")) !== input) throw new Error("Packaged skill changed the source");
  call("cleanup", "--job", state.job);
  if ((await readdir(jobs)).length !== 0) throw new Error("Packaged skill leaked a job");
  console.log(`${host}: installed twice, embedded Python roundtrip, Unicode preservation and cleanup passed`);
}
