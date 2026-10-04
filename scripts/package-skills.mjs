import { cp, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { preparePython } from "./prepare-python.mjs";
import { prepareNode } from "./prepare-node.mjs";
import { buildSkillBridge } from "./build-skill-bridge.mjs";
import { bytecodeFilter, readSejongEngineVersion, stageEngineRuntime } from "./engine-runtime.mjs";
const python = await preparePython();
const node = await prepareNode(python);
const bridge = await buildSkillBridge();
await mkdir("release", { recursive: true });
const pkg = JSON.parse(await readFile("package.json", "utf8"));
const filter = bytecodeFilter;
// Fail before staging anything when the Super Sejong version pin is missing or malformed.
const sejong = await readSejongEngineVersion();
for (const host of ["claude", "codex"]) {
  const stage = await mkdtemp(path.resolve("build-resources", `skill-${host}-`));
  const destination = path.join(stage, "humanize-kr");
  await mkdir(destination);
  await cp("skills/humanize-kr/SKILL.md", path.join(destination, "SKILL.md"));
  await cp("skills/humanize-kr/references", path.join(destination, "references"), { recursive: true });
  if (host === "codex") await cp("skills/humanize-kr/agents", path.join(destination, "agents"), { recursive: true });
  // engine_runtime/ is copied whole, so engine_runtime/sejong/** (v2 engine, ENGINE_VERSION, schemas, data) ships with both hosts.
  await stageEngineRuntime(path.join(destination, "engine_runtime"));
  await cp(bridge, path.join(destination, "engine_runtime/skill-bridge.cjs"));
  await cp("vendor/humanize-engine", path.join(destination, "vendor/humanize-engine"), { recursive: true, filter });
  await cp(python, path.join(destination, "python"), { recursive: true });
  await cp(node, path.join(destination, "node"), { recursive: true });
  await writeFile(path.join(destination, "distribution.json"), JSON.stringify({ product: "HumanizeKR", version: pkg.version, host,
    engine: (await readFile("vendor/humanize-engine/ENGINE_VERSION", "utf8")).trim(), sejongEngine: sejong }, null, 2));
  const output = path.resolve("release", `humanize-kr-${host}-${pkg.version}-win-x64.zip`);
  const result = spawnSync(path.join(python, "python.exe"), ["-c",
    "from pathlib import Path; import sys,zipfile; root=Path(sys.argv[1]); z=zipfile.ZipFile(sys.argv[2],'w',zipfile.ZIP_DEFLATED); [z.write(p,p.relative_to(root).as_posix()) for p in sorted(root.rglob('*')) if p.is_file()]; z.close()",
    stage, output], { encoding: "utf8", windowsHide: true });
  if (result.status !== 0) throw new Error(result.stderr || "Skill archive failed");
  const hash = createHash("sha256").update(await readFile(output)).digest("hex");
  await writeFile(output + ".sha256", `${hash}  ${path.basename(output)}\n`);
  console.log(`${host} skill: ${output}`);
}
await cp("scripts/install-humanize-skill.ps1", "release/install-humanize-skill.ps1");
