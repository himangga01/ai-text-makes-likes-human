import { _electron as electron, test, expect, type ElectronApplication } from "@playwright/test";
import { mkdtemp, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const parent = path.resolve("runtime/test-tmp");
let fixture: string;
test.beforeAll(async () => {
  await mkdir(parent, { recursive: true }); fixture = await mkdtemp(path.join(parent, "desktop-cli-"));
  execFileSync("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path.resolve("scripts/build-test-cli.ps1"), "-OutputDirectory", fixture], { windowsHide: true });
});
async function launch(mode: "both" | "codex" | "claude" = "both", existingData?: string) {
  const data = existingData ?? await mkdtemp(path.join(parent, "desktop-profile-"));
  const packaged = process.env.DESKTOP_PACKAGED === "1";
  const environment = { ...process.env }; delete environment.ELECTRON_RUN_AS_NODE;
  const app = await electron.launch({ executablePath: packaged ? path.resolve("release/win-unpacked/HumanizeKR.exe") : require("electron"),
    args: packaged ? [] : [path.resolve("desktop-dist/main.cjs")],
    env: { ...environment, HUMANIZE_HEADLESS: "1", HUMANIZE_USER_DATA: data,
      CODEX_COMMAND: path.join(fixture, mode === "claude" ? "missing-codex.exe" : "codex.exe"),
      CLAUDE_COMMAND: path.join(fixture, mode === "codex" ? "missing-claude.exe" : "claude.exe"), HUMANIZE_FAKE_TRACE: path.join(data, "calls.txt") }
  });
  try {
    const page = await app.firstWindow();
    await expect(page.locator("#network-scope")).toHaveText("내 PC에서 실행");
    await expect(page.locator(`input[value="${mode === "claude" ? "claude" : "codex"}"]`)).toBeEnabled();
    return { app, page, data };
  } catch (error) { await app.close(); throw error; }
}
async function close(app: ElectronApplication) { await app.close(); }

test('model and effort preferences survive restart and reach the CLI with equal-height fields', async()=>{
  const first=await launch();const profile=first.data;
  try {
    await first.page.locator('#codex-model').selectOption('gpt-6-astra');
    await first.page.locator('#codex-effort').selectOption('low');
    await first.page.locator('#claude-model').selectOption('claude-sonnet-5');
    await first.page.locator('#claude-effort').selectOption('high');
    await first.page.locator('#rewrite-strength input[value="strong"]').check();
    await expect.poll(async()=>JSON.parse(await readFile(path.join(profile,'settings.json'),'utf8'))).toMatchObject({models:{claude:{model:'claude-sonnet-5',effort:'high'}},rewriteStrength:'strong'});
  } finally {await close(first.app);}
  const {app,page,data}=await launch('both',profile);
  try {
    await expect(page.locator('#codex-model')).toHaveValue('gpt-6-astra');await expect(page.locator('#codex-effort')).toHaveValue('low');
    await expect(page.locator('#claude-model')).toHaveValue('claude-sonnet-5');await expect(page.locator('#claude-effort')).toHaveValue('high');
    await expect(page.locator('#rewrite-strength input[value="strong"]')).toBeChecked();
    await expect(page.locator('#codex-connection')).toHaveAttribute('data-state','ready');
    const a=await page.locator('#source-text').boundingBox(),b=await page.locator('#result-text').boundingBox();
    expect(a!.height).toBe(b!.height);expect(a!.y).toBe(b!.y);
    await page.locator('#source-text').fill('원문을 그대로 둔다. 자연스러운 문장을 보존한다. 내용을 확인했다.');
    await page.locator('#transform-button').click();await expect(page.locator('#status-chip')).toContainText('완료');
    await expect(page.locator('#result-strength')).toHaveText('사용한 변환 강도 · 강하게');
    await expect(page.locator('#result-view-controls')).toBeVisible();
    await expect(page.locator('#result-diff-host')).toBeVisible();
    await expect(page.locator('#result-diff-host ins, #result-diff-host del')).toHaveCount(0);
    await expect(page.locator('#result-diff-host .result-diff__changes')).toHaveText('원문을 그대로 둔다. 자연스러운 문장을 보존한다. 내용을 확인했다.');
    const sourceBox=await page.locator('#source-text').boundingBox(),diffBox=await page.locator('#result-diff-host .result-diff__changes').boundingBox();
    expect(sourceBox!.y).toBeCloseTo(diffBox!.y, 3);
    expect(sourceBox!.height).toBeCloseTo(diffBox!.height, 3);
    expect(sourceBox!.y+sourceBox!.height).toBeCloseTo(diffBox!.y+diffBox!.height, 3);
    const settings=(await readFile(path.join(data,'calls.txt.settings'),'utf8')).trim().split('\n').map(x=>JSON.parse(x));
    expect(settings[0]).toEqual({engine:'codex',model:'gpt-6-astra',effort:'low',strength:'strong'});
    // Visual capture is a separate QA artifact; hidden Windows compositor capture
    // can stall despite all IPC, persistence and layout assertions succeeding.
    if(process.env.VISUAL_CAPTURE==='1')await page.screenshot({path:'test-results/desktop-model-settings.png',fullPage:true,animations:'disabled'});
  } finally {await close(app);}
});

for (const format of ['docx','pptx']) test(`Office ${format} keeps a document handle, supports native save and resets`, async()=>{
  const {app,page,data}=await launch();
  try {
    await app.evaluate(({dialog},file)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[file]});},path.resolve(`tests/fixtures/documents/mixed.${format}`));
    await page.locator('#text-file-button').click();
    await expect(page.locator('#source-file-name')).toContainText(format.toUpperCase());
    await expect(page.locator('#rewrite-controls')).toBeHidden();
    await expect(page.locator('#source-text')).toHaveJSProperty('readOnly',true);
    await page.evaluate(()=>{(window as any).__events=[];(window as any).humanizeDesktop.onEvent((e:any)=>(window as any).__events.push(e.type));});
    await page.locator('#transform-button').click();
    await page.waitForFunction(()=>['success','error'].includes((document.querySelector('#status') as HTMLElement).dataset.state??''));
    expect(await page.locator('#status-chip').innerText(),`${await page.locator('#status-message').innerText()} events=${await page.evaluate(()=>(window as any).__events.join(','))}`).toContain('완료');
    await expect(page.locator('#result-view-controls')).toBeHidden();
    await expect(page.locator('#download-button')).toBeEnabled();
    const output=path.join(data,`saved.${format}`);
    await app.evaluate(({dialog},file)=>{dialog.showSaveDialog=async()=>({canceled:false,filePath:file});},output);
    await page.locator('#download-button').click();
    await expect.poll(async()=>readFile(output).then(b=>b.subarray(0,2).toString()).catch(()=>'' )).toBe('PK');
    await page.locator('#reset-button').click();
    await expect(page.locator('#source-text')).toHaveValue('');
    await expect(page.locator('#source-text')).toHaveJSProperty('readOnly',false);
  } finally {await close(app);}
});

test("isolated renderer uses only the selected CLI and supports native save/copy", async () => {
  const { app, page, data } = await launch();
  try {
    expect(await page.evaluate(() => typeof (window as any).require)).toBe("undefined");
    await expect(page.locator('input[value="claude"]')).toBeEnabled();
    await page.locator("#engine-option-claude").click();
    const input = path.join(data, "원문 문서.md");
    const source = "회의에는 12명이 참석했다. 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.";
    await writeFile(input, Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(source, "utf16le")]));
    await app.evaluate(({ dialog }, file) => { dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [file] }); }, input);
    await page.locator("#text-file-button").click();
    await expect(page.locator("#source-text")).toHaveValue(source);
    await expect(page.locator("#source-file-name")).toContainText("UTF-16");
    await expect(page.locator("#rewrite-controls")).toBeHidden();
    await page.locator("#transform-button").click();
    await expect(page.locator("#status-chip")).toContainText("완료");
    await expect(page.locator("#result-text")).toHaveValue(/12명/);
    expect((await readFile(path.join(data, "calls.txt"), "utf8")).trim().split("\n").every(value => value === "claude")).toBe(true);
    expect((await readFile(path.join(data, "calls.txt.settings"), "utf8")).trim().split("\n").map(value => JSON.parse(value).strength).every(value => value === "")).toBe(true);
    await expect(page.locator("#result-view-controls")).toBeHidden();
    await page.locator("#copy-button").click();
    expect(await app.evaluate(({ clipboard }) => clipboard.readText())).toContain("12명");
    const output = path.join(data, "result.md");
    await app.evaluate(({ dialog }, file) => { dialog.showSaveDialog = async () => ({ canceled: false, filePath: file }); }, output);
    await page.locator("#download-button").click();
    await expect.poll(async () => readFile(output, "utf8").catch(() => "")).toContain("12명");
    await expect.poll(async () => readdir(path.join(data, "jobs"))).toEqual([]);
    await page.screenshot({ path: "test-results/desktop-preview.png", fullPage: true });
  } finally { await close(app); }
});

for (const choice of ["claude", "codex"] as const) test(`${choice} works when the other CLI is absent`, async () => {
  const { app, page } = await launch(choice);
  try {
    await expect(page.locator(`input[value="${choice === "codex" ? "claude" : "codex"}"]`)).toBeDisabled();
    if (choice === "claude") await page.locator("#engine-option-claude").click();
    await page.locator("#source-text").fill("문장을 그대로 보존한다. 회의는 오전에 끝났다. 모두 자료를 읽었다.");
    await page.locator("#transform-button").click();
    await expect(page.locator("#status-chip")).toContainText("완료");
  } finally { await close(app); }
});

test("numeric corruption rolls back and its warning survives completion", async () => {
  const { app, page } = await launch();
  try {
    await page.locator("#source-text").fill("NUMBER_FIXTURE 참석자는 12명이었다. 모두 자료를 읽었다. 회의는 오전에 시작했다. 기록을 문서로 남겼다.");
    await page.locator("#transform-button").click();
    await expect(page.locator("#status-chip")).toContainText("완료");
    await expect(page.locator("#result-text")).toHaveValue(/12명/);
    await expect(page.locator("#warnings-panel")).toContainText("원문을 유지");
    await page.locator("#source-text").fill("다른 원문");
    await expect(page.locator("#result-text")).toHaveValue("");
    await expect(page.locator("#copy-button")).toBeDisabled();
  } finally { await close(app); }
});

test("cancelling kills the CLI and removes the job", async () => {
  const { app, page, data } = await launch();
  try {
    await page.locator("#source-text").fill("CANCEL_FIXTURE 회의 내용을 기록했다. 자료는 그대로 둔다.");
    await page.locator("#transform-button").click();
    await expect.poll(async () => readFile(path.join(data, "calls.txt"), "utf8").catch(() => "")).toContain("codex");
    await page.locator("#cancel-button").click();
    await expect(page.locator("#status-chip")).toContainText("취소됨");
    await expect.poll(async () => readdir(path.join(data, "jobs"))).toEqual([]);
    await expect(page.locator("#copy-button")).toBeDisabled();
  } finally { await close(app); }
});

test("closing the app during a transformation cleans its job", async () => {
  const { app, page, data } = await launch();
  await page.locator("#source-text").fill("CANCEL_FIXTURE 회의 내용을 기록했다. 자료는 그대로 둔다.");
  await page.locator("#transform-button").click();
  await expect.poll(async () => readFile(path.join(data, "calls.txt"), "utf8").catch(() => "")).toContain("codex");
  await close(app);
  expect(await readdir(path.join(data, "jobs"))).toEqual([]);
});

test("the selected engine survives app restart", async () => {
  const first = await launch();
  try {
    await expect(first.page.locator('input[value="claude"]')).toBeEnabled();
    await first.page.locator("#engine-option-claude").click();
    await expect.poll(async () => JSON.parse(await readFile(path.join(first.data, "settings.json"), "utf8")).selectedEngine).toBe("claude");
  } finally { await close(first.app); }
  const second = await launch("both", first.data);
  try { await expect(second.page.locator('input[value="claude"]')).toBeChecked(); }
  finally { await close(second.app); }
});
