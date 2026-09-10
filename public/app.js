import {
  getMarkdownDownloadName,
  readTextFile,
  TextFileError
} from "./text-file.js";
import { progressForEvent } from "./progress.js";
import { desktop, health, transform } from "./transport.js";
import { createResultDiff } from "./result-diff.js";
import { isOfficeFile, importDocument, closeDocument, transformDocument, saveDocument } from './document-file.js';
import { connectionState, formatElapsed, effortLabels } from './connection-settings.js';

const elements = {
  shell: document.querySelector("#editor-shell"),
  source: document.querySelector("#source-text"),
  result: document.querySelector("#result-text"),
  sourceCount: document.querySelector("#source-count"),
  fileInput: document.querySelector("#text-file-input"),
  fileButton: document.querySelector("#text-file-button"),
  fileName: document.querySelector("#source-file-name"),
  transform: document.querySelector("#transform-button"),
  cancel: document.querySelector("#cancel-button"),
  copy: document.querySelector("#copy-button"),
  download: document.querySelector("#download-button"),
  reset: document.querySelector("#reset-button"),
  rewriteControls: document.querySelector("#rewrite-controls"),
  rewriteOptionList: document.querySelector("#rewrite-option-list"),
  resultStrength: document.querySelector("#result-strength"),
  resultViewControls: document.querySelector("#result-view-controls"),
  resultModeButtons: [...document.querySelectorAll("[data-result-mode]")],
  changeLegend: document.querySelector("#change-legend"),
  resultDiffHost: document.querySelector("#result-diff-host"),
  engineInputs: [...document.querySelectorAll("#engine-select input[name=engine]")],
  claudeOption: document.querySelector("#engine-option-claude"),
  status: document.querySelector("#status"),
  statusChip: document.querySelector("#status-chip"),
  statusMessage: document.querySelector("#status-message"),
  progressPanel: document.querySelector("#progress-panel"),
  progress: document.querySelector("#progress"),
  progressValue: document.querySelector("#progress-value"),
  empty: document.querySelector("#result-empty"),
  steps: [...document.querySelectorAll("#workflow-steps li")]
};

let engineReady = false;
let claudeAvailable = false;
let codexAvailable = false;
const warnings = new Set();
const warningPanel = document.querySelector("#warnings-panel");
const warningList = document.querySelector("#warnings-list");

function clearWarnings() { warnings.clear(); warningList.replaceChildren(); warningPanel.hidden = true; }
function addWarning(message) {
  if (warnings.has(message)) return;
  warnings.add(message);
  const item = document.createElement("li"); item.textContent = message; warningList.append(item); warningPanel.hidden = false;
}
function selectedReady() { return selectedEngine() === "claude" ? claudeAvailable : codexAvailable; }
let running = false;
let controller;
let sourceFile;
let activeDownloadName;
let resultDownloadName;
let lastProgress = 0;
let runCompleted = false;
let officeDocument;
let documentResult;
let importing = false;
let documentFailed = false;
let checkingHealth = false;
let finalText = "";
let activeRun;
let resultMode = "diff";
let resultGeneration = 0;
let comparisonReady = false;
let elapsedStarted;
let elapsedInterval;
let modelOptions={codex:[{id:'gpt-5.6-sol',label:'GPT-5.6 Sol',efforts:['low','medium','high','xhigh']}],claude:[{id:'claude-opus-5',label:'Claude Opus 5',efforts:['low','medium','high','xhigh','max']}]};
let selections={codex:{model:'gpt-5.6-sol',effort:'medium'},claude:{model:'claude-opus-5',effort:'medium'}};
const bundledRewriteOptions = [
  { id: "normal", label: "보통", description: "원래 표현을 살려 어색한 부분을 다듬습니다." },
  { id: "medium", label: "중간", description: "어휘와 길어진 표현을 더 자연스럽게 정리합니다." },
  { id: "strong", label: "강하게", description: "문장 구조와 반복 표현까지 적극적으로 바꿉니다." },
  { id: "very-strong", label: "매우 강하게", description: "뜻은 유지하고 글 전반의 표현과 문장 구성을 크게 바꿉니다." }
];
let rewriteOptions = bundledRewriteOptions;
let rewriteStrength = "normal";
try {const saved=JSON.parse(localStorage.getItem('humanize-model-settings')??'null');if(saved&&typeof saved==='object')for(const kind of ['codex','claude'])if(saved[kind])selections[kind]=saved[kind];}catch{}
if (!desktop) {
  const savedStrength = localStorage.getItem("humanize-rewrite-strength");
  if (bundledRewriteOptions.some(option => option.id === savedStrength)) rewriteStrength = savedStrength;
}

const resultDiff = createResultDiff({
  container: elements.resultDiffHost,
  onStatus(event) {
    if (event.type === "copy-warning") addWarning(event.message);
  }
});

function normalizeLineEndings(text) {
  return String(text).replace(/\r\n?/g, "\n");
}

function renderRewriteOptions(options = rewriteOptions) {
  if (!Array.isArray(options) || options.length !== 4 || !options.every(option =>
    bundledRewriteOptions.some(fallback => fallback.id === option?.id) &&
    typeof option.label === "string" && typeof option.description === "string"
  )) options = bundledRewriteOptions;
  rewriteOptions = options;
  if (!rewriteOptions.some(option => option.id === rewriteStrength)) rewriteStrength = "normal";
  elements.rewriteOptionList.replaceChildren(...rewriteOptions.map(option => {
    const label = document.createElement("label");
    label.className = "strength-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "rewrite-strength";
    input.value = option.id;
    input.checked = option.id === rewriteStrength;
    const body = document.createElement("span");
    body.className = "strength-option-body";
    const title = document.createElement("span");
    title.className = "strength-option-title";
    title.textContent = option.label;
    const description = document.createElement("span");
    description.className = "strength-option-description";
    description.textContent = option.description;
    body.append(title, description);
    label.append(input, body);
    return label;
  }));
  for (const input of elements.rewriteOptionList.querySelectorAll("input")) {
    input.addEventListener("change", handleRewriteStrengthChange);
  }
}

async function handleRewriteStrengthChange(event) {
  const previous = rewriteStrength;
  rewriteStrength = event.target.value;
  try {
    if (desktop) await window.humanizeDesktop.selectRewriteStrength(rewriteStrength);
    else localStorage.setItem("humanize-rewrite-strength", rewriteStrength);
  } catch (error) {
    rewriteStrength = previous;
    renderRewriteOptions();
    setStatus("error", "설정 저장 오류", error.message);
  }
  refreshControls();
}

function renderModelControls(kind) {
  const model=document.querySelector(`#${kind}-model`);const effort=document.querySelector(`#${kind}-effort`);
  const options=modelOptions[kind];
  const selected=options.find(x=>x.id===selections[kind]?.model)??options[0];
  const level=selected.efforts.includes(selections[kind]?.effort)?selections[kind].effort:'medium';
  model.replaceChildren(...options.map(x=>new Option(x.label,x.id,false,x.id===selected.id)));
  effort.replaceChildren(...selected.efforts.map(x=>new Option(effortLabels[x]??x,x,false,x===level)));
  selections[kind]={model:model.value,effort:effort.value};
}
function setConnection(kind, provider, failed=false) {
  const value=failed?{state:'error',icon:'×',label:'연결 확인 실패'}:connectionState(provider);
  const badge=document.querySelector(`#${kind}-connection`);badge.dataset.state=value.state;
  badge.querySelector('.connection-icon').textContent=value.icon;badge.querySelector('.connection-label').textContent=value.label;
  const compact=document.querySelector(`[data-engine-status="${kind}"]`);compact.textContent=value.icon;compact.dataset.state=value.state;compact.setAttribute('aria-label',value.label);
  document.querySelector(`[data-provider="${kind}"]`).dataset.connection=value.state;
  document.querySelector(`#${kind}-health`).textContent=failed?'연결을 다시 점검해 주세요.':provider?.message??(value.state==='ready'?'CLI 설치·로그인을 확인했습니다.':value.state==='auth'?'CLI에서 로그인한 뒤 다시 점검해 주세요.':value.state==='error'?'CLI 실행 파일과 로그인 상태를 확인해 주세요.':'설치와 로그인 상태를 확인합니다.');
}
function tickElapsed(){if(elapsedStarted!==undefined)document.querySelector('#elapsed-time').textContent=formatElapsed(performance.now()-elapsedStarted);}
function stopElapsed(){tickElapsed();clearInterval(elapsedInterval);elapsedInterval=undefined;elapsedStarted=undefined;}
function startElapsed(){stopElapsed();elapsedStarted=performance.now();tickElapsed();elapsedInterval=setInterval(tickElapsed,250);}

function countCharacters(text) {
  return Array.from(text).length;
}

function selectedEngine() {
  return elements.engineInputs.find(input => input.checked)?.value ?? "codex";
}

function applyClaudeAvailability() {
  for (const input of elements.engineInputs) {
    const ready = input.value === "claude" ? claudeAvailable : codexAvailable;
    input.disabled = running || !ready;
    input.closest("label").title = ready ? "" : "이 CLI의 설치·로그인 상태를 확인해 주세요.";
  }
}

function setStep(index) {
  elements.steps.forEach((step, position) => {
    step.classList.toggle("is-current", position === index);
  });
}

function setStatus(kind, label, message) {
  elements.shell.dataset.state = kind;
  elements.status.dataset.state = kind;
  elements.statusChip.className = `status-chip status-${kind}`;
  elements.statusChip.textContent = label;
  elements.statusMessage.textContent = message;
}

function clearResultDownload() {
  resultDownloadName = undefined;
  elements.download.hidden = true;
  elements.download.disabled = true;
}

function directTextInput() {
  return !sourceFile && !officeDocument;
}

function setResultMode(nextMode, focusFinal = false) {
  resultMode = nextMode;
  const showComparison = runCompleted && comparisonReady && directTextInput() && nextMode === "diff";
  elements.result.hidden = showComparison;
  elements.resultDiffHost.hidden = !showComparison;
  elements.changeLegend.hidden = !showComparison;
  for (const button of elements.resultModeButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.resultMode === nextMode));
  }
  if (nextMode === "final" && focusFinal) elements.result.focus();
}

function clearCompletedResult() {
  resultGeneration += 1;
  comparisonReady = false;
  finalText = "";
  activeRun = undefined;
  runCompleted = false;
  elements.result.value = "";
  elements.resultStrength.hidden = true;
  elements.resultStrength.textContent = "";
  elements.resultViewControls.hidden = true;
  resultDiff.reset();
  setResultMode("diff");
}

function renderCompletedResult(run) {
  elements.result.value = finalText;
  if (run.inputKind === "direct-text") {
    const option = rewriteOptions.find(candidate => candidate.id === run.strength)
      ?? bundledRewriteOptions.find(candidate => candidate.id === run.strength);
    elements.resultStrength.textContent = `사용한 변환 강도 · ${option?.label ?? run.strength}`;
    elements.resultStrength.hidden = false;
    elements.resultViewControls.hidden = false;
    resultMode = "diff";
    setResultMode("diff");
    const expectedGeneration = resultGeneration;
    const expectedFinalText = finalText;
    setTimeout(() => {
      if (expectedGeneration !== resultGeneration || !runCompleted) return;
      void resultDiff.setResult(run.sourceSnapshot, expectedFinalText).then(outcome => {
        if (outcome.status !== "rendered" || expectedGeneration !== resultGeneration || finalText !== expectedFinalText) return;
        comparisonReady = true;
        setResultMode(resultMode);
      }).catch(() => {
        if (expectedGeneration !== resultGeneration) return;
        addWarning("변경 비교를 만들지 못했습니다. 최종문에서 결과를 확인해 주세요.");
        setResultMode("final");
      });
    }, 0);
  } else {
    elements.resultStrength.hidden = true;
    elements.resultViewControls.hidden = true;
    resultDiff.reset();
    setResultMode("final");
  }
}

function resetProgress() {
  stopElapsed();document.querySelector('#elapsed-time').textContent='00:00';
  lastProgress = 0;
  elements.progress.value = 0;
  elements.progressValue.textContent = "0%";
  elements.progressPanel.hidden = true;
}

function applyProgress(event) {
  const next = progressForEvent(event);
  if (next === undefined) return;
  elements.progressPanel.hidden = false;
  if (next === null) {
    elements.progress.removeAttribute("value");
    elements.progressValue.textContent = "대기 중";
    return;
  }

  lastProgress = Math.max(lastProgress, next);
  elements.progress.value = lastProgress;
  elements.progressValue.textContent = `${Math.round(lastProgress)}%`;
}

function refreshControls() {
  const hasSource = elements.source.value.trim().length > 0;
  const canDownload = Boolean(resultDownloadName && finalText);
  const showRewriteControls = directTextInput();
  elements.sourceCount.textContent = `${countCharacters(elements.source.value).toLocaleString("ko-KR")}자`;
  elements.transform.disabled = !engineReady || !selectedReady() || !hasSource || running || importing || checkingHealth || documentFailed || Boolean(documentResult);
  elements.engineInputs.forEach(input => {
    input.disabled =
      running || (input.value === "claude" ? !claudeAvailable : !codexAvailable);
  });
  elements.source.readOnly = running || importing || Boolean(officeDocument);
  document.querySelectorAll("#desktop-settings button").forEach(button => { button.disabled = running; });
  document.querySelector('#refresh-health').disabled=running||checkingHealth;
  document.querySelectorAll('.model-controls select').forEach(select=>{select.disabled=running||importing||checkingHealth;});
  elements.rewriteControls.hidden = !showRewriteControls;
  elements.rewriteOptionList.querySelectorAll("input").forEach(input => { input.disabled = running || importing; });
  elements.fileButton.disabled = running || importing;
  elements.reset.disabled = running || importing || (!hasSource && !elements.result.value);
  elements.copy.disabled = !runCompleted || elements.result.value.length === 0;
  elements.download.hidden = !canDownload;
  elements.download.disabled = !canDownload || running;
}

function setRunning(value) {
  running = value;
  elements.transform.hidden = value;
  elements.cancel.hidden = !value;
  if (value) elements.progressPanel.hidden = false;
  refreshControls();
}

function showResultState() {
  elements.empty.hidden = finalText.length > 0;
  elements.copy.disabled = !runCompleted || finalText.length === 0;
}

function handleEvent(event) {
  applyProgress(event);
  switch (event.type) {
    case 'document-result':
      documentResult=event;
      activeDownloadName=event.name;
      if (activeRun) activeRun.streamedText = event.preview;
      break;
    case "accepted":
      setStatus("processing", "접수", "변환 작업을 준비하고 있습니다.");
      setStep(1);
      break;
    case "queued":
      setStatus("processing", `대기 ${event.position}`, `앞에 ${event.position}건의 작업이 있습니다.`);
      break;
    case "progress": {
      const message =
        Number.isInteger(event.completedUnits) && Number.isInteger(event.totalUnits)
          ? `전체 작업 ${event.completedUnits}/${event.totalUnits} 진행 중입니다.`
          : event.message;
      setStatus("processing", "변환 중", message);
      break;
    }
    case "result-start":
      if (activeRun) activeRun.streamedText = "";
      elements.empty.hidden = true;
      setStep(2);
      break;
    case "result-delta":
      if (activeRun) activeRun.streamedText += event.text;
      break;
    case "warning":
      addWarning(event.message);
      break;
    case "done":
      stopElapsed();
      finalText = activeRun?.streamedText ?? "";
      runCompleted = true;
      resultDownloadName = activeDownloadName;
      renderCompletedResult(activeRun);
      setStatus(
        "success",
        warnings.size ? "완료 · 검토 권장" : "완료",
        `${event.chunks}개 구간 · ${(event.elapsedMs / 1000).toFixed(1)}초 만에 완료했습니다.`
      );
      setStep(2);
      refreshControls();
      break;
    case "error":
      throw Object.assign(new Error(event.message), { code: event.code });
    default:
      throw new Error("알 수 없는 서버 응답입니다.");
  }
}


async function startTransform() {
  if (running || elements.source.value.trim().length === 0) return;
  controller = new AbortController();
  activeDownloadName =
    sourceFile?.format === "markdown"
      ? getMarkdownDownloadName(sourceFile.fileName)
      : desktop ? (sourceFile?.fileName?.replace(/\.txt$/i, "") || "humanized") + ".txt" : undefined;
  const inputKind = officeDocument ? undefined : sourceFile ? "text-file" : "direct-text";
  const sourceSnapshot = normalizeLineEndings(elements.source.value);
  const strength = inputKind === "direct-text" ? rewriteStrength : inputKind === "text-file" ? "normal" : undefined;
  clearCompletedResult();
  activeRun = { sourceSnapshot, inputKind, strength, streamedText: "" };
  clearWarnings();
  showResultState();
  clearResultDownload();
  resetProgress();
  setRunning(true);
  startElapsed();
  setStatus("processing", "접수 중", desktop ? "선택한 CLI로 변환을 준비합니다." : "서버에 원문을 안전하게 전달하고 있습니다.");
  setStep(1);
  applyProgress({ type: "accepted" });
  try {
    const settings={...selections[selectedEngine()]};
    if(officeDocument)await transformDocument(officeDocument,selectedEngine(),controller.signal,handleEvent,settings);
    else await transform(sourceSnapshot, selectedEngine(), controller.signal, handleEvent,settings,{inputKind,strength});
    if (!runCompleted) throw new Error("완료 응답을 받지 못했습니다. 다시 시도해 주세요.");
  } catch (error) {
    if(officeDocument){documentFailed=true;documentResult=undefined;void closeDocument(officeDocument);}
    clearCompletedResult();
    if (controller.signal.aborted) {
      setStatus("warning", "취소됨", "변환을 취소했습니다. 원문은 그대로 남아 있습니다.");
    } else {
      setStatus("error", "오류", error?.message || "처리 중 오류가 발생했습니다. 다시 시도해 주세요.");
    }
    elements.progressPanel.hidden = false;
  } finally {
    stopElapsed();
    controller = undefined;
    activeRun = undefined;
    activeDownloadName = undefined;
    if (!runCompleted) clearResultDownload();
    setRunning(false);
    showResultState();
  }
}

elements.source.addEventListener("input", () => {
  if (!running) { clearCompletedResult(); clearWarnings(); showResultState(); }
  sourceFile = undefined;
  elements.fileName.hidden = true;
  elements.fileName.textContent = "";
  clearResultDownload();
  if (!running) resetProgress();
  refreshControls();
  if (!running) {
    setStatus(
      elements.source.value.trim() ? "ready" : "idle",
      elements.source.value.trim() ? "입력 완료" : "준비",
      elements.source.value.trim()
        ? "변환 버튼을 눌러 문체를 다듬어 보세요."
        : "원문을 입력하면 변환 버튼이 활성화됩니다."
    );
  }
});

elements.fileButton.addEventListener("click", async () => {
  if (!desktop) { elements.fileInput.click(); return; }
  try {
    const selected = await window.humanizeDesktop.openText();
    if(selected?.document) await loadOffice(selected.document);
    else if (selected) await loadFile(new File([selected.bytes], selected.name));
  } catch (error) { setStatus("error", "파일 오류", error.message); }
});
elements.fileInput.addEventListener("change", () => loadFile(elements.fileInput.files?.[0]));
async function loadFile(file) {
  if (!file) return;
  const previous = elements.source.value;
  importing=true;
  clearCompletedResult();
  clearResultDownload();
  refreshControls();
  try {
    if(isOfficeFile(file.name)) {
      setStatus('processing','문서 읽기','문서 구조와 윤문할 텍스트를 확인합니다.');
      await loadOffice(await importDocument(file));return;
    }
    const loaded = await readTextFile(file);
    await closeDocument(officeDocument);officeDocument=undefined;documentResult=undefined;documentFailed=false;
    elements.source.value = loaded.text;
    clearCompletedResult(); clearWarnings(); showResultState();
    sourceFile = {
      fileName: loaded.fileName,
      format: loaded.format
    };
    clearResultDownload();
    resetProgress();
    elements.fileName.textContent = `${loaded.fileName} · ${loaded.encoding}`;
    elements.fileName.hidden = false;
    setStatus("ready", "파일 준비", "파일 내용을 확인한 뒤 변환 버튼을 눌러주세요.");
    refreshControls();
  } catch (error) {
    elements.source.value = previous;
    const message =
      error instanceof TextFileError
        ? error.message
        : error.message || "파일을 읽지 못했습니다.";
    setStatus("error", "파일 오류", message);
    refreshControls();
  } finally {
    importing=false;refreshControls();
    elements.fileInput.value = "";
  }
}
async function loadOffice(info) {
  await closeDocument(officeDocument);officeDocument=info;documentResult=undefined;documentFailed=false;
  sourceFile={fileName:info.name,format:info.format};elements.source.value=info.preview;clearCompletedResult();
  clearWarnings();for(const warning of info.warnings??[])addWarning(warning);
  clearResultDownload();resetProgress();showResultState();
  elements.fileName.hidden=false;elements.fileName.textContent=`${info.name.replace('-humanized','')} · ${info.format.toUpperCase()} · 윤문 ${info.editableBlocks}개 / 보존 ${info.preservedBlocks}개${info.slides?' · '+info.slides+'슬라이드':''}`;
  setStatus('ready','문서 준비','위치별 텍스트 미리보기입니다. 서식을 유지한 새 문서로 저장합니다.');refreshControls();
}

elements.transform.addEventListener("click", startTransform);
elements.cancel.addEventListener("click", () => controller?.abort());
elements.reset.addEventListener("click", () => {
  void closeDocument(officeDocument);officeDocument=undefined;documentResult=undefined;documentFailed=false;
  clearCompletedResult(); clearWarnings();
  elements.source.value = "";
  sourceFile = undefined;
  activeDownloadName = undefined;
  clearResultDownload();
  elements.fileName.hidden = true;
  elements.fileName.textContent = "";
  resetProgress();
  setStep(0);
  setStatus("idle", "준비", "원문을 입력하면 변환 버튼이 활성화됩니다.");
  showResultState();
  refreshControls();
  elements.source.focus();
});

async function copyResultText() {
  if (desktop) { await window.humanizeDesktop.copyText(finalText); return; }
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(finalText);
    return;
  }

  const active = document.activeElement;
  const inputSelection = active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement
    ? { start: active.selectionStart, end: active.selectionEnd, direction: active.selectionDirection }
    : undefined;
  const selection = document.getSelection();
  const ranges = selection ? Array.from({ length: selection.rangeCount }, (_, index) => selection.getRangeAt(index).cloneRange()) : [];
  selection?.removeAllRanges();
  const temporary = document.createElement("textarea");
  temporary.className = "clipboard-fallback";
  temporary.setAttribute("aria-hidden", "true");
  temporary.value = finalText;
  document.body.append(temporary);
  temporary.focus();
  temporary.select();
  const copied = document.execCommand("copy");
  temporary.remove();
  if (active instanceof HTMLElement) active.focus();
  if (inputSelection && (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement)) {
    active.setSelectionRange(inputSelection.start, inputSelection.end, inputSelection.direction);
  }
  if (selection) {
    selection.removeAllRanges();
    for (const range of ranges) selection.addRange(range);
  }
  if (!copied) throw new Error("copy command failed");
}

elements.copy.addEventListener("click", async () => {
  try {
    await copyResultText();
    const old = elements.copy.textContent;
    elements.copy.textContent = "복사됨";
    setTimeout(() => {
      elements.copy.textContent = old;
    }, 1200);
  } catch {
    setStatus("error", "복사 오류", "결과를 선택해 직접 복사해 주세요.");
  }
});

elements.download.addEventListener("click", async () => {
  if(officeDocument&&documentResult){try{await saveDocument(officeDocument,documentResult.name);}catch(e){setStatus('error','저장 오류',e.message);}return;}
  if (!resultDownloadName || !finalText) return;
  if (desktop) {
    try { await window.humanizeDesktop.saveText({ text: finalText, name: resultDownloadName }); }
    catch (error) { setStatus("error", "저장 오류", error.message); }
    return;
  }
  const blob = new Blob([finalText], {
    type: "text/markdown;charset=utf-8"
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = resultDownloadName;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
});

async function checkHealth() {
  if(checkingHealth||running)return;
  checkingHealth=true;
  for(const kind of ['codex','claude'])setConnection(kind);
  refreshControls();
  try {
    const body = await health();
    if(body.modelOptions)modelOptions=body.modelOptions;
    renderRewriteOptions(body.rewriteOptions);
    for(const kind of ['codex','claude']) {
      renderModelControls(kind);
      const provider=body.providers?.[kind]??{ready:body.status==='ready'&&(kind==='codex'||body.claudeAvailable===true),installed:body.status==='ready',authenticated:body.status==='ready'&&(kind==='codex'||body.claudeAvailable===true),message:body.message};
      setConnection(kind,provider);
    }
    document.querySelector('#connection-checked').textContent=`확인 ${new Date(body.checkedAt??Date.now()).toLocaleTimeString('ko-KR')}`;
    engineReady = body.status === "ready";
    codexAvailable = engineReady && (body.providers ? body.providers.codex.ready : true);
    claudeAvailable = engineReady && (body.providers ? body.providers.claude.ready : body.claudeAvailable === true);
    if (desktop) {
      for (const kind of ["codex", "claude"]) document.querySelector(`#${kind}-health`).textContent = body.providers?.[kind]?.message || body.message || "사용할 수 없습니다.";
    }
    applyClaudeAvailability();
    if (!engineReady) {
      setStatus("error", "엔진 점검", body.message || "서버의 변환 엔진을 사용할 수 없습니다.");
    }
  } catch {
    for(const kind of ['codex','claude'])setConnection(kind,undefined,true);
    document.querySelector('#connection-checked').textContent='연결 점검 실패';
    engineReady = false; codexAvailable = false; claudeAvailable = false;
    setStatus("error", "연결 오류", "엔진 상태를 확인하지 못했습니다.");
  }
  checkingHealth=false;
  refreshControls();
}

showResultState();
applyClaudeAvailability();
renderRewriteOptions();
refreshControls();
for (const button of elements.resultModeButtons) button.addEventListener("click", event => {
  setResultMode(button.dataset.resultMode, event.detail === 0 && button.dataset.resultMode === "final");
});
for (const input of elements.engineInputs) input.addEventListener("change", () => {
  refreshControls();
  if (desktop) window.humanizeDesktop.selectEngine(selectedEngine()).catch(error => setStatus("error", "설정 오류", error.message));
});
async function initialize() {
  document.querySelector('#refresh-health').addEventListener('click',checkHealth);
  for(const kind of ['codex','claude'])for(const type of ['model','effort'])document.querySelector(`#${kind}-${type}`).addEventListener('change',async()=>{
    selections[kind]={model:document.querySelector(`#${kind}-model`).value,effort:document.querySelector(`#${kind}-effort`).value};
    renderModelControls(kind);
    try {if(desktop)await window.humanizeDesktop.selectModel({engine:kind,...selections[kind]});else localStorage.setItem('humanize-model-settings',JSON.stringify(selections));}
    catch(error){setStatus('error','설정 저장 오류',error.message);}
  });
  if (desktop) {
    document.body.classList.add("desktop-app");
    document.querySelector("#hero-title").textContent = "한국어 문장을 자연스럽게 다듬으세요";
    document.querySelector("#network-scope").textContent = "내 PC에서 실행";
    document.querySelector("#desktop-settings").hidden = false;
    document.querySelector('#connection-scope').textContent='이 PC에 설치·로그인된 CLI를 사용합니다.';
    document.querySelectorAll('.cli-path-controls').forEach(x=>{x.hidden=false;});
    document.querySelector(".privacy-note").textContent = "원문은 선택한 CLI로 처리하며 변환 이력은 앱에 저장하지 않습니다.";
    elements.download.textContent = "결과 저장";
    try {
      const preferences = await window.humanizeDesktop.preferences();
      if(preferences.models)for(const kind of ['codex','claude'])if(preferences.models[kind])selections[kind]=preferences.models[kind];
      if (rewriteOptions.some(option => option.id === preferences.rewriteStrength)) {
        rewriteStrength = preferences.rewriteStrength;
        renderRewriteOptions();
      }
      const selected = elements.engineInputs.find(input => input.value === preferences.selectedEngine);
      if (selected) selected.checked = true;
    } catch { /* keep default choice */ }
    for (const button of document.querySelectorAll("[data-choose-cli]")) button.addEventListener("click", async () => {
      try { await window.humanizeDesktop.chooseCli(button.dataset.chooseCli); await checkHealth(); }
      catch (error) { setStatus("error", "설정 오류", error.message); }
    });
    for (const button of document.querySelectorAll("[data-reset-cli]")) button.addEventListener("click", async () => {
      try { await window.humanizeDesktop.resetCli(button.dataset.resetCli); await checkHealth(); }
      catch (error) { setStatus("error", "설정 오류", error.message); }
    });
  }
  await checkHealth();
  setInterval(()=>{if(!document.hidden&&!running)void checkHealth();},60000);
}
initialize();
