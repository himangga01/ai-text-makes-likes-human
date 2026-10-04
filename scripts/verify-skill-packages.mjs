import { execFileSync, spawnSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, writeFile, readdir } from "node:fs/promises";
import path from "node:path";
import { assertSejongBundle, loadBundledSejong, readSejongEngineVersion } from "./engine-runtime.mjs";
const parent = path.resolve("runtime/test-tmp"); await mkdir(parent, { recursive: true });
const pkg = JSON.parse(await readFile("package.json", "utf8"));
const sejong = await readSejongEngineVersion();
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
  // v2 engine: every engine_runtime/sejong file arrived unchanged and the embedded Python can import it
  // (the package reads its ENGINE_VERSION at import), at the version the receipt in distribution.json names.
  await assertSejongBundle(path.join(skill, "engine_runtime"));
  const loaded = loadBundledSejong(python, path.join(skill, "engine_runtime"), { cwd: root });
  const distribution = JSON.parse(await readFile(path.join(skill, "distribution.json"), "utf8"));
  for (const packed of [loaded, distribution.sejongEngine]) {
    if (packed?.id !== sejong.id || packed.version !== sejong.version || packed.schema !== sejong.schema) throw new Error("Packaged Super Sejong engine version differs from the source");
  }
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
  const nodeLock = JSON.parse(await readFile(path.join(skill, 'node/runtime-lock.json'), 'utf8'));
  if (nodeLock.version !== '24.19.0' || !(await readFile(path.join(skill, 'node/LICENSE'), 'utf8')).includes('Node.js')) throw new Error('Pinned licensed Node missing');
  if ((await readdir(path.join(skill,'node'))).sort().join(',') !== 'LICENSE,node.exe,runtime-lock.json') throw new Error('Unexpected Node runtime contents');
  const fixture = JSON.parse(await readFile('tests/fixtures/direct-live-quality.json','utf8'));
  for (const strength of ['normal','medium','strong','very-strong']) {
    const directSource = path.join(root, `direct-${strength}.txt`);
    const expected = strength === 'very-strong' ? fixture.candidate : fixture.source;
    await writeFile(directSource, fixture.source, 'utf8');
    state = call('prepare','--input',directSource,'--input-kind','direct-text','--strength',strength);
    let attempts = 0;
    while (state.status === 'rewrite') {
      if (++attempts > 2) throw new Error('Direct retry bound exceeded');
      if (state.rewriteOptions.strength !== strength) throw new Error('Requested strength lost');
      const instructions = await readFile(state.instructionsPath,'utf8');
      const sentences = JSON.parse(await readFile(state.sentencesPath,'utf8'));
      if (!instructions.includes(`요청 강도: ${strength}`) || !sentences.length) throw new Error('Host context missing');
      if (strength === 'very-strong' && state.attempt === 2 && !instructions.includes('BEGIN_CANDIDATE_')) throw new Error('Conservative review context missing');
      await writeFile(state.responsePath,JSON.stringify({rewrittenText:expected,edits:[],warnings:[]}));
      state=call('accept','--job',state.job,'--chunk',String(state.chunk),'--attempt',String(state.attempt),'--source-hash',state.sourceHash,'--response',state.responsePath);
    }
    const finalPath=path.join(root,`direct-${strength}-final.md`), comparisonPath=path.join(root,`direct-${strength}.html`);
    const done=call('finalize','--job',state.job,'--output',finalPath,'--comparison-output',comparisonPath);
    if(done.comparisonPath!==comparisonPath || await readFile(finalPath,'utf8')!==expected) throw new Error('Packaged direct final result differs');
    if(!(await readFile(comparisonPath,'utf8')).includes('최종문 복사')) throw new Error('Standalone comparison missing');
    call('cleanup','--job',state.job);
  }
  for (const format of ['docx','pptx']) {
    state=call('prepare','--input',path.resolve(`tests/fixtures/documents/mixed.${format}`));
    while(state.status==='rewrite') {
      const batch=JSON.parse(await readFile(state.inputPath,'utf8'));
      await writeFile(state.responsePath,JSON.stringify({schemaVersion:2,batchId:batch.batchId,sourceHash:batch.sourceHash,
        reviewedIds:batch.blocks.map(b=>b.id),blocks:[],warnings:[]}));
      state=call('accept','--job',state.job,'--chunk',String(state.chunk),'--attempt',String(state.attempt),'--source-hash',state.sourceHash,'--response',state.responsePath);
    }
    const officeOutput=path.join(root,`result.${format}`);
    call('finalize','--job',state.job,'--output',officeOutput);
    if((await readFile(officeOutput)).subarray(0,2).toString()!=='PK')throw new Error('Office package output missing');
    call('cleanup','--job',state.job);
  }
  if ((await readdir(jobs)).length !== 0) throw new Error("Packaged skill leaked a job");
  console.log(`${host}: installed twice, embedded Python/Node, TXT/DOCX/PPTX and four direct strengths, P1 review, HTML export, Unicode preservation and cleanup passed (${root})`);
}
