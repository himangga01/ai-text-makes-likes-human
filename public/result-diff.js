import { createTextDiffEngine } from "./text-diff.js";

const COPY_HINT = "변경 비교에서 복사하면 삭제된 내용은 제외됩니다. 비교 영역 밖까지 선택하려면 최종문 보기에서 복사하세요.";
const COPY_OUTSIDE_MESSAGE = "비교 영역 밖까지 선택했습니다. 빠짐없이 복사하려면 최종문 보기에서 복사하세요.";
const COPY_DELETION_MESSAGE = "삭제된 내용만 선택되어 클립보드를 바꾸지 않았습니다.";

function abortError(message = "비교 작업이 취소되었습니다.") {
  return new DOMException(message, "AbortError");
}

function emitStatus(onStatus, type, message) {
  onStatus?.({ type, message });
}

function intersects(range, node) {
  try {
    return range.intersectsNode(node);
  } catch {
    return false;
  }
}

function isExcludedText(node, changes) {
  for (let parent = node.parentElement; parent && parent !== changes; parent = parent.parentElement) {
    if (parent.tagName === "DEL" || parent.hasAttribute("data-diff-marker")) return true;
  }
  return false;
}

function selectedFinalText(range, changes) {
  const walker = changes.ownerDocument.createTreeWalker(changes, NodeFilter.SHOW_TEXT);
  let text = "";
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!intersects(range, node) || isExcludedText(node, changes)) continue;
    const value = node.data;
    const start = range.startContainer === node ? range.startOffset : 0;
    const end = range.endContainer === node ? range.endOffset : value.length;
    text += value.slice(start, end);
  }
  return text;
}

/**
 * Creates copy/context-menu handlers for a rendered comparison.
 * `handleCopy` returns one of: unhandled, copied, deletion-only, outside.
 */
export function createDiffCopyHandlers({ root, changes, onStatus, getSelection }) {
  const readSelection = getSelection ?? (() => root.ownerDocument.getSelection());

  function classify() {
    const selection = readSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      return { kind: "none", selection };
    }
    const range = selection.getRangeAt(0);
    if (!intersects(range, root)) return { kind: "none", selection };
    if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) {
      return { kind: "outside", selection, range };
    }
    if (!changes.contains(range.startContainer) || !changes.contains(range.endContainer)) {
      return { kind: "outside", selection, range };
    }
    return { kind: "diff", selection, range };
  }

  return {
    handleCopy(event) {
      const selected = classify();
      if (selected.kind === "none") return "unhandled";
      event.preventDefault();
      if (selected.kind === "outside") {
        emitStatus(onStatus, "copy-warning", COPY_OUTSIDE_MESSAGE);
        return "outside";
      }

      const finalText = selectedFinalText(selected.range, changes);
      if (!finalText && selected.selection.toString()) {
        emitStatus(onStatus, "copy-warning", COPY_DELETION_MESSAGE);
        return "deletion-only";
      }
      if (!event.clipboardData) {
        emitStatus(onStatus, "copy-warning", "클립보드에 접근할 수 없습니다. 최종문 보기에서 복사하세요.");
        return "unavailable";
      }
      event.clipboardData.clearData();
      event.clipboardData.setData("text/plain", finalText);
      emitStatus(onStatus, "copied", "삭제된 내용을 제외하고 최종문 기준으로 복사했습니다.");
      return "copied";
    },

    handleContextMenu() {
      const selected = classify();
      if (selected.kind === "diff") {
        emitStatus(onStatus, "copy-hint", "오른쪽 클릭으로 복사해도 삭제된 내용은 제외됩니다.");
      } else if (selected.kind === "outside") {
        emitStatus(onStatus, "copy-warning", COPY_OUTSIDE_MESSAGE);
      }
      return selected.kind;
    }
  };
}

function changeNode(document, segment) {
  if (segment.type === "equal") return document.createTextNode(segment.text);
  const node = document.createElement(segment.type === "insert" ? "ins" : "del");
  const KoreanType = segment.type === "insert" ? "삽입" : "삭제";
  node.className = `result-diff__${segment.type}`;
  node.textContent = segment.text;
  node.setAttribute("aria-label", `${KoreanType} 시작 ${segment.text} ${KoreanType} 끝`);
  return node;
}

function createStructure(container) {
  const document = container.ownerDocument;
  const root = document.createElement("section");
  root.className = "result-diff";
  root.hidden = true;

  const hint = document.createElement("p");
  hint.className = "result-diff__copy-hint";
  hint.textContent = COPY_HINT;

  const notice = document.createElement("p");
  notice.className = "result-diff__notice";
  notice.setAttribute("role", "status");
  notice.hidden = true;

  const changes = document.createElement("pre");
  changes.className = "result-diff__changes";
  changes.tabIndex = 0;
  changes.setAttribute("aria-label", "원문과 최종문의 변경 비교");

  const final = document.createElement("pre");
  final.className = "result-diff__final";
  final.tabIndex = 0;
  final.setAttribute("aria-label", "최종문");
  final.hidden = true;

  root.append(hint, notice, changes, final);
  container.replaceChildren(root);
  return { root, notice, changes, final };
}

/**
 * Standalone, read-only result renderer.
 *
 * API: setResult(source, finalText), setMode("diff" | "final"), reset(), dispose().
 * Host applications own the mode controls, labels, textarea and global copy button.
 */
export function createResultDiff({
  container,
  onStatus,
  workerFactory,
  workerThreshold,
  scheduleFrame = callback => requestAnimationFrame(callback),
  renderBatchSize = 100
}) {
  if (!container?.ownerDocument) throw new TypeError("container는 DOM 요소여야 합니다.");
  const elements = createStructure(container);
  const engine = createTextDiffEngine({ workerFactory, workerThreshold });
  const document = container.ownerDocument;
  const copyHandlers = createDiffCopyHandlers({
    root: elements.root,
    changes: elements.changes,
    onStatus
  });
  let generation = 0;
  let disposed = false;
  let mode = "diff";

  const onCopy = event => copyHandlers.handleCopy(event);
  const onContextMenu = () => copyHandlers.handleContextMenu();
  document.addEventListener("copy", onCopy);
  elements.changes.addEventListener("contextmenu", onContextMenu);

  function setMode(nextMode) {
    if (nextMode !== "diff" && nextMode !== "final") {
      throw new RangeError('mode는 "diff" 또는 "final"이어야 합니다.');
    }
    mode = nextMode;
    elements.root.dataset.mode = mode;
    elements.changes.hidden = mode !== "diff";
    elements.final.hidden = mode !== "final";
  }

  async function renderSegments(segments, expectedGeneration) {
    elements.changes.replaceChildren();
    for (let index = 0; index < segments.length; index += renderBatchSize) {
      if (expectedGeneration !== generation || disposed) throw abortError();
      const fragment = document.createDocumentFragment();
      for (const segment of segments.slice(index, index + renderBatchSize)) {
        fragment.append(changeNode(document, segment));
      }
      elements.changes.append(fragment);
      if (index + renderBatchSize < segments.length) {
        await new Promise(resolve => scheduleFrame(resolve));
      }
    }
  }

  return {
    async setResult(source, finalText) {
      if (disposed) throw abortError("폐기된 결과 비교에는 내용을 설정할 수 없습니다.");
      generation += 1;
      const expectedGeneration = generation;
      elements.root.hidden = false;
      elements.final.textContent = String(finalText);
      elements.notice.hidden = true;
      elements.notice.textContent = "";
      emitStatus(onStatus, "computing", "변경 내용을 비교하고 있습니다.");

      try {
        const result = await engine.compute(String(source), String(finalText));
        if (expectedGeneration !== generation || disposed) return { status: "stale" };
        await renderSegments(result.segments, expectedGeneration);
        if (expectedGeneration !== generation || disposed) return { status: "stale" };
        if (result.notice) {
          elements.notice.textContent = result.notice;
          elements.notice.hidden = false;
        }
        setMode(mode);
        emitStatus(onStatus, "rendered", result.notice ?? "변경 비교를 표시했습니다.");
        return { status: "rendered", result };
      } catch (error) {
        if (error?.name === "AbortError" && (expectedGeneration !== generation || disposed)) {
          return { status: "stale" };
        }
        emitStatus(onStatus, "error", error instanceof Error ? error.message : String(error));
        throw error;
      }
    },

    setMode,

    reset() {
      generation += 1;
      engine.cancel();
      elements.changes.replaceChildren();
      elements.final.textContent = "";
      elements.notice.textContent = "";
      elements.notice.hidden = true;
      elements.root.hidden = true;
      emitStatus(onStatus, "reset", "변경 비교를 초기화했습니다.");
    },

    dispose() {
      if (disposed) return;
      disposed = true;
      generation += 1;
      engine.dispose();
      document.removeEventListener("copy", onCopy);
      elements.changes.removeEventListener("contextmenu", onContextMenu);
    }
  };
}
