import { chromium } from "@playwright/test";
import { createServer } from "node:net";
import { spawn, execFileSync } from "node:child_process";
import { mkdtemp, mkdir, copyFile, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
const live = process.argv.includes("--live");
const engine = process.argv.includes("--claude") ? "claude" : "codex";
const parent = path.resolve("runtime/test-tmp"); await mkdir(parent, { recursive: true });
const root = await mkdtemp(path.join(parent, "portable-smoke-"));
const copied = path.join(root, "복사 앱"); await mkdir(copied);
const pkg = JSON.parse(await readFile("package.json", "utf8"));
const exe = path.join(copied, "HumanizeKR.exe");
await copyFile(path.resolve("release", `HumanizeKR-${pkg.version}-win-x64.exe`), exe);
const artifactSha256 = createHash("sha256").update(await readFile(exe)).digest("hex");
const data = path.join(root, "profile");
const environment = { ...process.env, HUMANIZE_USER_DATA: data, HUMANIZE_HEADLESS: "1" };
delete environment.ELECTRON_RUN_AS_NODE;
if (!live) {
  const fixture = path.join(root, "cli");
  execFileSync("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.resolve("scripts/build-test-cli.ps1"), "-OutputDirectory", fixture], { windowsHide: true });
  environment.CODEX_COMMAND = path.join(fixture, "codex.exe");
  environment.CLAUDE_COMMAND = path.join(fixture, "claude.exe");
  environment.PATH = path.join(process.env.SystemRoot ?? "C:/Windows", "System32");
}
const probe = createServer();
await new Promise(resolve => probe.listen(0, "127.0.0.1", resolve));
const port = probe.address().port; await new Promise(resolve => probe.close(resolve));
const child = spawn(exe, [`--remote-debugging-port=${port}`], { cwd: copied, env: environment, windowsHide: true, stdio: "ignore" });
const started = Date.now(); let browser;
try {
  for (let i = 0; i < 120; i++) {
    try { browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, { timeout: 1000 }); break; } catch { await new Promise(resolve => setTimeout(resolve, 500)); }
  }
  if (!browser) throw new Error("Portable EXE did not expose its test browser endpoint");
  let page;
  for (let i = 0; i < 60; i++) {
    page = browser.contexts().flatMap(context => context.pages()).find(candidate => candidate.url().startsWith("humanize://app"));
    if (page) break; await new Promise(resolve => setTimeout(resolve, 250));
  }
  if (!page) throw new Error("Portable window did not load");
  page.setDefaultTimeout(60_000);
  await page.waitForFunction(choice => { const input = document.querySelector(`input[value="${choice}"]`); return input && !input.disabled; }, engine);
  if (engine === "claude") await page.locator("#engine-option-claude").click();
  const source = "오늘 오전 회의에는 12명이 참석했다. 참석자들은 배포 계획을 검토했다. 담당자는 문서의 수치를 다시 확인했다. 회의에서 정한 내용은 오후에 공유했다.";
  await page.locator("#source-text").fill(source);
  await page.locator("#transform-button").click();
  await page.waitForFunction(() => ["success", "error"].includes(document.querySelector("#editor-shell").dataset.state), null, { timeout: 240000 });
  const state = await page.locator("#editor-shell").getAttribute("data-state");
  if (state !== "success") throw new Error(await page.locator("#status-message").textContent());
  const output = await page.locator("#result-text").inputValue();
  if (!output.includes("12명")) throw new Error("Protected number was not preserved");
  for (let i = 0; i < 40 && (await readdir(path.join(data, "jobs"))).length; i++) await new Promise(resolve => setTimeout(resolve, 100));
  const clean = (await readdir(path.join(data, "jobs"))).length === 0;
  if (!clean) throw new Error("Job cleanup did not finish");
  const report = { mode: live ? "live" : "fixture-no-node-python-path", engine, portableCopied: true, artifactSha256, sourceChars: source.length, outputChars: output.length, cleanup: clean, elapsedMs: Date.now() - started };
  await writeFile(path.resolve("release", `smoke-${live ? "live" : "fixture"}-${engine}.json`), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
  const session = await browser.newBrowserCDPSession();
  await Promise.race([session.send("Browser.close").catch(() => {}), new Promise(resolve => setTimeout(resolve, 3000))]);
} finally {
  await Promise.race([browser?.close().catch(() => {}), new Promise(resolve => setTimeout(resolve, 3000))]);
  for (let i = 0; i < 60 && child.exitCode === null; i++) await new Promise(resolve => setTimeout(resolve, 100));
  if (child.exitCode === null && child.pid) execFileSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
}
