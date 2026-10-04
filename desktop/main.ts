import { defaultPreferences, loadPreferences, savePreferences, selectRewriteStrength } from './preferences.js';
import { parseRewriteOptions } from '../src/engine/rewrite-policy.js';
import { app, BrowserWindow, protocol, ipcMain, dialog, clipboard, utilityProcess, type UtilityProcess, type IpcMainInvokeEvent } from "electron";
import { readFile, writeFile, mkdir, readdir, rm, stat } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { spawn } from "node:child_process";
import { parseEngineChoice, type EngineChoice } from "../src/engine/model-policy.js";
import { parseModelSettings, type ModelSettings } from '../src/engine/model-policy.js';
import { sameFile, saveDocumentCopy } from './save-target.js';
import { MAX_TEXT_FILE_BYTES } from '../src/engine/input-limits.js';

app.setName("HumanizeKR");
if (process.env.HUMANIZE_USER_DATA) app.setPath("userData", path.resolve(process.env.HUMANIZE_USER_DATA));
protocol.registerSchemesAsPrivileged([{ scheme: "humanize", privileges: { standard: true, secure: true, supportFetchAPI: true } }]);
const resourceRoot = app.isPackaged ? path.join(process.resourcesPath, "engine") : path.resolve(__dirname, "..");
const publicRoot = path.join(app.isPackaged ? app.getAppPath() : resourceRoot, "public");
const jobsRoot = path.join(app.getPath("userData"), "jobs");
const settingsPath = path.join(app.getPath("userData"), "settings.json");
let preferences = defaultPreferences();
let window: BrowserWindow | undefined;
let worker: UtilityProcess | undefined;
let activeId: string | undefined;
let quitting = false;
let mayQuit = false;
let saving = Promise.resolve();
const children = new Set<number>();
// The TXT/MD file the current text came from; saving a result over it is refused.
let textSource: string | undefined;
let pendingSource: { token: string; path: string | undefined } | undefined;
const pending = new Map<string, { resolve(value: any): void; reject(reason: Error): void; timer?: NodeJS.Timeout }>();

function stopChildren() {
  for (const pid of children) {
    if (process.platform === "win32") spawn("taskkill.exe", ["/PID", String(pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
    else { try { process.kill(pid, "SIGKILL"); } catch { /* already gone */ } }
  }
  children.clear();
}
function startWorker() {
  if (worker) return worker;
  const env = { ...process.env, HUMANIZE_RESOURCE_ROOT: resourceRoot, HUMANIZE_JOBS_ROOT: jobsRoot,
    HUMANIZE_PYTHON: path.join(app.isPackaged ? resourceRoot : path.join(resourceRoot, "build-resources"), "python", "python.exe") };
  const created = utilityProcess.fork(path.join(__dirname, "worker.cjs"), [], { env, stdio: "pipe", serviceName: "Humanize engine" });
  worker = created;
  // Worker and CLI diagnostic streams can contain private text. Never persist them.
  created.stdout?.on("data", () => {}); created.stderr?.on("data", () => {});
  created.on("message", (message: any) => {
    if (message.kind === "child" && Number.isInteger(message.pid) && message.pid > 0) {
      if (message.alive) children.add(message.pid); else children.delete(message.pid);
    } else if (message.kind === "event" && message.id === activeId && !window?.isDestroyed()) {
      window?.webContents.send("humanize:event", message.event);
    } else if (message.kind === "response") {
      const call = pending.get(message.id); if (!call) return;
      clearTimeout(call.timer); pending.delete(message.id);
      if (message.error) call.reject(new Error(String(message.error))); else call.resolve(message.value);
    }
  });
  created.on("exit", () => {
    if (worker !== created) return;
    worker = undefined; stopChildren();
    for (const call of pending.values()) { clearTimeout(call.timer); call.reject(new Error("엔진 연결이 종료되었습니다. 다시 점검해 주세요.")); }
    pending.clear();
  });
  return created;
}
function request(kind: string, payload: Record<string, unknown> = {}, id = randomUUID()): Promise<any> {
  const current = startWorker();
  return new Promise((resolve, reject) => {
    const call: { resolve(value: any): void; reject(reason: Error): void; timer?: NodeJS.Timeout } = { resolve, reject };
    if (kind === "health") call.timer = setTimeout(() => { pending.delete(id); reject(new Error("CLI 상태 점검 시간이 초과되었습니다.")); }, 60_000);
    pending.set(id, call); current.postMessage({ kind, id, ...payload });
  });
}
function trusted(event: IpcMainInvokeEvent) {
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || !event.senderFrame.url.startsWith("humanize://app/")) throw new Error("허용되지 않은 요청입니다.");
}
function engine(value: unknown): EngineChoice {
  const choice = parseEngineChoice(value); if (!choice) throw new Error("지원하지 않는 엔진입니다."); return choice;
}
function text(value: unknown): string { if (typeof value !== "string") throw new Error("텍스트가 필요합니다."); return value; }
function persist() {
  const snapshot = structuredClone(preferences);
  saving = saving.catch(() => {}).then(() => savePreferences(settingsPath, snapshot));
  return saving;
}
function handle(name: string, task: (value: any) => unknown) {
  ipcMain.handle(`humanize:${name}`, async (event, value) => { trusted(event); if (quitting) throw new Error("앱 종료 중입니다."); return task(value); });
}
function registerIpc() {
  handle("preferences", () => preferences);
  handle("health", () => request("health", { commands: preferences.commands }));
  handle("select-engine", async value => { if (activeId) throw new Error("변환 중입니다."); preferences.selectedEngine = engine(value); await persist(); });
  handle('select-model', async value => {
    if(activeId) throw new Error('변환 중입니다.');
    const choice=engine(value?.engine);
    preferences.models[choice]=parseModelSettings(choice,value?.model,value?.effort);
    await persist();return preferences.models[choice];
  });
  handle('select-rewrite-strength', value => {
    if (activeId) throw new Error('변환 중입니다.');
    return selectRewriteStrength(preferences,value,persist);
  });
  handle("choose-cli", async value => {
    const choice = engine(value); if (activeId) throw new Error("변환 중입니다.");
    const selected = await dialog.showOpenDialog(window!, { title: `${choice} 실행 파일 선택`, properties: ["openFile"], filters: [{ name: "CLI 실행 파일", extensions: ["exe"] }] });
    if (!selected.canceled && selected.filePaths[0]) { preferences.commands[choice] = selected.filePaths[0]; await persist(); }
    return preferences;
  });
  handle("reset-cli", async value => { if (activeId) throw new Error("변환 중입니다."); delete preferences.commands[engine(value)]; await persist(); return preferences; });
  handle("transform", async value => {
    if (activeId) throw new Error("이미 변환 중입니다.");
    const choice=engine(value?.engine);
    const rewriteOptions = parseRewriteOptions(value?.inputKind,value?.strength);
    const input = { text: text(value?.text), engine: choice, commands: {...preferences.commands},
      ...(rewriteOptions ? {inputKind:rewriteOptions.inputKind,strength:rewriteOptions.strength} : {}),
      settings:parseModelSettings(choice,value?.settings?.model,value?.settings?.effort) };
    if (!input.text.trim()) throw new Error("원문을 입력해 주세요.");
    const id = randomUUID(); activeId = id;
    try { return await request("transform", { input }, id); } finally { if (activeId === id) activeId = undefined; }
  });
  handle('transform-document',async value=>{
    if(activeId) throw new Error('이미 변환 중입니다.');
    const id=randomUUID();activeId=id;
    try {const choice=engine(value?.engine);return await request('document-transform',{input:{id:text(value?.id),token:text(value?.token),engine:choice,commands:preferences.commands,settings:parseModelSettings(choice,value?.settings?.model,value?.settings?.effort)}},id);}
    finally {if(activeId===id)activeId=undefined;}
  });
  handle('close-document',value=>request('document-close',{documentId:text(value?.id),token:text(value?.token)}));
  handle('save-document',async value=>{
    const info=await request('document-result',{documentId:text(value?.id),token:text(value?.token)});
    try {
      const selected=await dialog.showSaveDialog(window!,{defaultPath:info.name,filters:[{name:'Office 문서',extensions:[info.format]}]});
      if(selected.canceled||!selected.filePath)return false;
      await saveDocumentCopy(info.output,selected.filePath,info.original,info.format);return true;
    } finally {await request('document-release',{leaseId:info.leaseId}).catch(()=>{});}
  });
  handle("cancel", () => { if (activeId) worker?.postMessage({ kind: "cancel", id: activeId }); });
  handle("open-text", async () => {
    if(activeId)throw new Error('변환 중입니다.');
    const selected = await dialog.showOpenDialog(window!, { properties: ["openFile"], filters: [{ name: "지원 문서", extensions: ["txt", "md", "docx", "pptx"] }] });
    const file = selected.filePaths[0]; if (selected.canceled || !file) return null;
    if(/\.(docx|pptx)$/i.test(file)){
      const document=await request('document-import',{file});
      const sourceToken=randomUUID();pendingSource={token:sourceToken,path:undefined};
      return {document,sourceToken};
    }
    if (!/\.(txt|md)$/i.test(file)) throw new Error("TXT, MD, DOCX 또는 PPTX 파일을 선택해 주세요.");
    // Refuse before reading: the renderer would otherwise receive the whole file.
    if ((await stat(file)).size > MAX_TEXT_FILE_BYTES) throw new Error("TXT·MD 파일은 1 MiB 이하만 불러올 수 있습니다.");
    const bytes = new Uint8Array(await readFile(file));
    const sourceToken=randomUUID();pendingSource={token:sourceToken,path:path.resolve(file)};
    return { name: path.basename(file), bytes, sourceToken };
  });
  handle("commit-source", value => {
    if (!pendingSource || value?.sourceToken !== pendingSource.token) throw new Error("파일 선택 상태가 만료되었습니다.");
    textSource=pendingSource.path;pendingSource=undefined;
  });
  handle("clear-source", () => { textSource=undefined;pendingSource=undefined; });
  handle("save-text", async value => {
    const content = text(value?.text);
    const name = path.basename(text(value?.name)).replace(/[<>:"/\\|?*]/g, "-");
    const selected = await dialog.showSaveDialog(window!, { defaultPath: /\.(txt|md)$/i.test(name) ? name : "humanized.md", filters: [{ name: "Markdown", extensions: ["md"] }, { name: "텍스트", extensions: ["txt"] }] });
    if (selected.canceled || !selected.filePath) return false;
    if (textSource && sameFile(selected.filePath, textSource)) throw new Error("원본과 다른 새 파일 이름을 지정해 주세요.");
    await writeFile(selected.filePath, content, "utf8"); return true;
  });
  handle("copy", value => clipboard.writeText(text(value)));
}

async function initialize() {
  await mkdir(jobsRoot, { recursive: true });
  // The Electron single-instance lock is held; only this app's old UUID jobs live here.
  for (const entry of await readdir(jobsRoot, { withFileTypes: true })) {
    if (/^[a-f0-9-]{36}$/.test(entry.name) && entry.isDirectory() && !entry.isSymbolicLink()) {
      const target = path.resolve(jobsRoot, entry.name);
      if (path.dirname(target) === path.resolve(jobsRoot)) await rm(target, { recursive: true, force: true });
    }
  }
  preferences = await loadPreferences(settingsPath);
  protocol.handle("humanize", async incoming => {
    const url = new URL(incoming.url);
    if (url.hostname !== "app") return new Response("Forbidden", { status: 403 });
    const file = path.resolve(publicRoot, "." + decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname));
    if (!file.startsWith(path.resolve(publicRoot) + path.sep)) return new Response("Forbidden", { status: 403 });
    try {
      const content = await readFile(file);
      const mime: Record<string, string> = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png" };
      return new Response(new Uint8Array(content), { headers: {
        "Content-Type": (mime[path.extname(file)] ?? "application/octet-stream") + "; charset=utf-8",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-src 'none'"
      } });
    } catch { return new Response("Not found", { status: 404 }); }
  });
  registerIpc();
  window = new BrowserWindow({ width: 1200, height: 880, minWidth: 760, minHeight: 640, show: false,
    icon: path.join(app.isPackaged ? process.resourcesPath : path.join(resourceRoot, "build-resources"), "icon.ico"),
    title: "Humanize KR · 한국어 문장 다듬기", autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), nodeIntegration: false, contextIsolation: true, sandbox: true, spellcheck: false } });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", event => event.preventDefault());
  window.once("ready-to-show", () => { if (process.env.HUMANIZE_HEADLESS !== "1") window?.show(); });
  window.on("close", event => { if (!mayQuit) { event.preventDefault(); app.quit(); } });
  await window.loadURL("humanize://app/index.html");
}

if (!app.requestSingleInstanceLock()) { mayQuit = true; app.quit(); }
else {
  app.on("second-instance", () => { if (window?.isMinimized()) window.restore(); window?.show(); window?.focus(); });
  app.on("before-quit", event => {
    if (mayQuit) return;
    event.preventDefault(); if (quitting) return; quitting = true;
    (async () => {
      if (worker) {
        let timer: NodeJS.Timeout | undefined;
        await Promise.race([request("shutdown"), new Promise<void>(resolve => { timer = setTimeout(resolve, 15_000); })]).catch(() => {});
        clearTimeout(timer); stopChildren(); worker?.kill();
      }
      await saving.catch(() => {}); mayQuit = true; app.quit();
    })();
  });
  app.whenReady().then(initialize).catch(() => { dialog.showErrorBox("Humanize KR", "앱을 시작하지 못했습니다. 파일을 다시 내려받아 실행해 주세요."); mayQuit = true; app.quit(); });
}
