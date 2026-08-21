import { readTextFile, TextFileError } from "./text-file.js";

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
  reset: document.querySelector("#reset-button"),
  status: document.querySelector("#status"),
  statusChip: document.querySelector("#status-chip"),
  statusMessage: document.querySelector("#status-message"),
  progress: document.querySelector("#progress"),
  empty: document.querySelector("#result-empty"),
  steps: [...document.querySelectorAll("#workflow-steps li")]
};

let engineReady = false;
let running = false;
let controller;

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

function refreshControls() {
  const hasSource = elements.source.value.trim().length > 0;
  elements.sourceCount.textContent = `${countCharacters(elements.source.value).toLocaleString("ko-KR")}자`;
  elements.transform.disabled = !engineReady || !hasSource || running;
  elements.fileButton.disabled = running;
  elements.reset.disabled = running || (!hasSource && !elements.result.value);
  elements.copy.disabled = elements.result.value.length === 0;
}

function setRunning(value) {
  running = value;
  elements.transform.hidden = value;
  elements.cancel.hidden = !value;
  elements.progress.hidden = !value;
  refreshControls();
}

function showResultState() {
  elements.empty.hidden = elements.result.value.length > 0;
  elements.copy.disabled = elements.result.value.length === 0;
}

function handleEvent(event) {
  switch (event.type) {
    case "accepted":
      setStatus("processing", "접수", "변환 작업을 준비하고 있습니다.");
      setStep(1);
      break;
    case "queued":
      setStatus("processing", `대기 ${event.position}`, `앞에 ${event.position}건의 작업이 있습니다.`);
      elements.progress.removeAttribute("value");
      break;
    case "progress": {
      setStatus("processing", "변환 중", event.message);
      const total = Math.max(1, Number(event.total) || 1);
      elements.progress.value = Math.min(100, Math.max(2, (Number(event.current) / total) * 100));
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
      elements.progress.value = 100;
      setStatus(
        "success",
        "완료",
        `${event.chunks}개 구간 · ${(event.elapsedMs / 1000).toFixed(1)}초 만에 완료했습니다.`
      );
      setStep(2);
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
  setRunning(true);
  setStatus("processing", "접수 중", "서버에 원문을 안전하게 전달하고 있습니다.");
  setStep(1);
  elements.progress.value = 2;
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
  } finally {
    controller = undefined;
    setRunning(false);
    showResultState();
  }
}

elements.source.addEventListener("input", () => {
  elements.fileName.hidden = true;
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
  elements.fileName.hidden = true;
  elements.fileName.textContent = "";
  elements.progress.value = 0;
  setStep(0);
  setStatus("idle", "준비", "원문을 입력하면 변환 버튼이 활성화됩니다.");
  showResultState();
  refreshControls();
  elements.source.focus();
});
elements.copy.addEventListener("click", async () => {
  await navigator.clipboard.writeText(elements.result.value);
  const old = elements.copy.textContent;
  elements.copy.textContent = "복사됨";
  setTimeout(() => {
    elements.copy.textContent = old;
  }, 1200);
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
