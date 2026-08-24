import {
  getMarkdownDownloadName,
  readTextFile,
  TextFileError
} from "./text-file.js";
import { progressForEvent } from "./progress.js";

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
let running = false;
let controller;
let sourceFile;
let activeDownloadName;
let resultDownloadName;
let lastProgress = 0;
let runCompleted = false;

function countCharacters(text) {
  return Array.from(text).length;
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

function resetProgress() {
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
  const canDownload = Boolean(resultDownloadName && elements.result.value);
  elements.sourceCount.textContent = `${countCharacters(elements.source.value).toLocaleString("ko-KR")}자`;
  elements.transform.disabled = !engineReady || !hasSource || running;
  elements.fileButton.disabled = running;
  elements.reset.disabled = running || (!hasSource && !elements.result.value);
  elements.copy.disabled = elements.result.value.length === 0;
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
  elements.empty.hidden = elements.result.value.length > 0;
  elements.copy.disabled = elements.result.value.length === 0;
}

function handleEvent(event) {
  applyProgress(event);
  switch (event.type) {
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
      elements.result.value = "";
      elements.empty.hidden = true;
      setStep(2);
      break;
    case "result-delta":
      elements.result.value += event.text;
      showResultState();
      break;
    case "warning":
      setStatus("warning", "검토 권장", event.message);
      break;
    case "done":
      runCompleted = true;
      resultDownloadName = activeDownloadName;
      setStatus(
        "success",
        "완료",
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

async function consumeNdjson(response) {
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.message || "변환 요청을 시작하지 못했습니다.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim()) handleEvent(JSON.parse(line));
    }
    if (done) break;
  }
  if (buffer.trim()) handleEvent(JSON.parse(buffer));
}

async function startTransform() {
  if (running || elements.source.value.trim().length === 0) return;
  controller = new AbortController();
  activeDownloadName =
    sourceFile?.format === "markdown"
      ? getMarkdownDownloadName(sourceFile.fileName)
      : undefined;
  runCompleted = false;
  clearResultDownload();
  resetProgress();
  setRunning(true);
  setStatus("processing", "접수 중", "서버에 원문을 안전하게 전달하고 있습니다.");
  setStep(1);
  applyProgress({ type: "accepted" });
  try {
    const response = await fetch("/api/transform", {
      method: "POST",
      headers: { "content-type": "text/plain; charset=utf-8" },
      body: elements.source.value,
      signal: controller.signal
    });
    await consumeNdjson(response);
  } catch (error) {
    if (controller.signal.aborted) {
      setStatus("warning", "취소됨", "변환을 취소했습니다. 원문은 그대로 남아 있습니다.");
    } else {
      setStatus("error", "오류", error?.message || "처리 중 오류가 발생했습니다. 다시 시도해 주세요.");
    }
    elements.progressPanel.hidden = true;
  } finally {
    controller = undefined;
    activeDownloadName = undefined;
    if (!runCompleted) clearResultDownload();
    setRunning(false);
    showResultState();
  }
}

elements.source.addEventListener("input", () => {
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

elements.fileButton.addEventListener("click", () => elements.fileInput.click());
elements.fileInput.addEventListener("change", async () => {
  const file = elements.fileInput.files?.[0];
  if (!file) return;
  const previous = elements.source.value;
  try {
    const loaded = await readTextFile(file);
    elements.source.value = loaded.text;
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
        : "텍스트 파일을 읽지 못했습니다. 다른 인코딩으로 저장해 다시 시도해 주세요.";
    setStatus("error", "파일 오류", message);
    refreshControls();
  } finally {
    elements.fileInput.value = "";
  }
});

elements.transform.addEventListener("click", startTransform);
elements.cancel.addEventListener("click", () => controller?.abort());
elements.reset.addEventListener("click", () => {
  elements.source.value = "";
  elements.result.value = "";
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
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(elements.result.value);
    return;
  }

  elements.result.focus();
  elements.result.select();
  const copied = document.execCommand("copy");
  elements.result.setSelectionRange(
    elements.result.value.length,
    elements.result.value.length
  );
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

elements.download.addEventListener("click", () => {
  if (!resultDownloadName || !elements.result.value) return;
  const blob = new Blob([elements.result.value], {
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
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    const body = await response.json();
    engineReady = response.ok && body.status === "ready";
    if (!engineReady) {
      setStatus("error", "엔진 점검", body.message || "서버의 변환 엔진을 사용할 수 없습니다.");
    }
  } catch {
    setStatus("error", "연결 오류", "서버 상태를 확인하지 못했습니다.");
  }
  refreshControls();
}

showResultState();
refreshControls();
checkHealth();
