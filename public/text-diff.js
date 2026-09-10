const lineBreakPattern = /[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+/gu;
const wordSegmenter = new Intl.Segmenter(undefined, { granularity: "word" });
const graphemeSegmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });
const DEFAULT_MAX_OPERATIONS = 250_000;
const DEFAULT_MAX_TIME_MS = 100;
const DEFAULT_MAX_DISPLAY_NODES = 5_000;
const COARSE_NOTICE = "세부 비교 한도를 넘어 전체 교체로 간략히 표시했습니다.";

class BudgetExceeded extends Error {}

function now() {
  return globalThis.performance?.now?.() ?? Date.now();
}

function positiveLimit(value, fallback) {
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function createBudget(options) {
  const startedAt = now();
  const maxOperations = positiveLimit(options.maxOperations, DEFAULT_MAX_OPERATIONS);
  const maxTimeMs = positiveLimit(options.maxTimeMs, DEFAULT_MAX_TIME_MS);
  let operations = 0;

  return {
    consume(amount = 1) {
      operations += amount;
      if (operations > maxOperations || now() - startedAt > maxTimeMs) {
        throw new BudgetExceeded();
      }
    },
    stats() {
      return { operations, elapsedMs: now() - startedAt };
    }
  };
}

function lines(text) {
  return text.match(lineBreakPattern) ?? [];
}

function words(text) {
  return Array.from(wordSegmenter.segment(text), item => item.segment);
}

function graphemes(text) {
  return Array.from(graphemeSegmenter.segment(text), item => item.segment);
}

function append(segments, type, text) {
  if (!text) return;
  const previous = segments.at(-1);
  if (previous?.type === type) previous.text += text;
  else segments.push({ type, text });
}

function sequenceDiff(source, target, budget) {
  if (source.length === 0) return target.map(text => ({ type: "insert", text }));
  if (target.length === 0) return source.map(text => ({ type: "delete", text }));

  const frontier = new Map([[1, 0]]);
  const trace = [];
  const maximum = source.length + target.length;

  for (let distance = 0; distance <= maximum; distance += 1) {
    budget.consume();
    trace.push(new Map(frontier));
    for (let diagonal = -distance; diagonal <= distance; diagonal += 2) {
      budget.consume();
      const down = frontier.get(diagonal + 1) ?? -1;
      const right = frontier.get(diagonal - 1) ?? -1;
      let x = diagonal === -distance || (diagonal !== distance && right < down)
        ? down
        : right + 1;
      let y = x - diagonal;

      while (x < source.length && y < target.length && source[x] === target[y]) {
        budget.consume();
        x += 1;
        y += 1;
      }
      frontier.set(diagonal, x);
      if (x >= source.length && y >= target.length) {
        return backtrack(trace, source, target, distance);
      }
    }
  }
  return [];
}

function backtrack(trace, source, target, finalDistance) {
  let x = source.length;
  let y = target.length;
  const reversed = [];

  for (let distance = finalDistance; distance >= 0; distance -= 1) {
    const frontier = trace[distance];
    const diagonal = x - y;
    const down = frontier.get(diagonal + 1) ?? -1;
    const right = frontier.get(diagonal - 1) ?? -1;
    const previousDiagonal = diagonal === -distance || (diagonal !== distance && right < down)
      ? diagonal + 1
      : diagonal - 1;
    const previousX = frontier.get(previousDiagonal) ?? 0;
    const previousY = previousX - previousDiagonal;

    while (x > previousX && y > previousY) {
      reversed.push({ type: "equal", text: source[x - 1] });
      x -= 1;
      y -= 1;
    }
    if (distance === 0) break;
    if (x === previousX) {
      reversed.push({ type: "insert", text: target[y - 1] });
      y -= 1;
    } else {
      reversed.push({ type: "delete", text: source[x - 1] });
      x -= 1;
    }
  }

  const result = [];
  for (const operation of reversed.reverse()) append(result, operation.type, operation.text);
  return result;
}

function refineChanged(sourceText, targetText, budget) {
  budget.consume(sourceText.length + targetText.length);
  const wordDiff = sequenceDiff(words(sourceText), words(targetText), budget);
  const refined = [];
  let removed = "";
  let inserted = "";

  const flush = () => {
    if (!removed && !inserted) return;
    budget.consume(removed.length + inserted.length);
    for (const segment of sequenceDiff(graphemes(removed), graphemes(inserted), budget)) {
      append(refined, segment.type, segment.text);
    }
    removed = "";
    inserted = "";
  };

  for (const segment of wordDiff) {
    if (segment.type === "equal") {
      flush();
      append(refined, "equal", segment.text);
    } else if (segment.type === "delete") removed += segment.text;
    else inserted += segment.text;
  }
  flush();
  return refined;
}

function refineLineDiff(lineDiff, budget) {
  const result = [];
  let removed = "";
  let inserted = "";

  const flush = () => {
    if (!removed && !inserted) return;
    for (const segment of refineChanged(removed, inserted, budget)) {
      append(result, segment.type, segment.text);
    }
    removed = "";
    inserted = "";
  };

  for (const segment of lineDiff) {
    if (segment.type === "equal") {
      flush();
      append(result, "equal", segment.text);
    } else if (segment.type === "delete") removed += segment.text;
    else inserted += segment.text;
  }
  flush();
  return result;
}

function coarseResult(source, target, budget) {
  const segments = [];
  append(segments, "delete", source);
  append(segments, "insert", target);
  return {
    segments,
    coarse: true,
    notice: COARSE_NOTICE,
    displayNodes: segments.length,
    ...budget.stats()
  };
}

export function diffText(source, target, options = {}) {
  const sourceText = String(source);
  const targetText = String(target);
  const budget = createBudget(options);
  const maxDisplayNodes = positiveLimit(options.maxDisplayNodes, DEFAULT_MAX_DISPLAY_NODES);

  try {
    budget.consume(sourceText.length + targetText.length);
    const lineDiff = sequenceDiff(lines(sourceText), lines(targetText), budget);
    const segments = refineLineDiff(lineDiff, budget);
    if (segments.length > maxDisplayNodes) return coarseResult(sourceText, targetText, budget);
    return {
      segments,
      coarse: false,
      notice: null,
      displayNodes: segments.length,
      ...budget.stats()
    };
  } catch (error) {
    if (!(error instanceof BudgetExceeded)) throw error;
    return coarseResult(sourceText, targetText, budget);
  }
}

function abortError(message = "비교 작업이 취소되었습니다.") {
  return new DOMException(message, "AbortError");
}

export function createTextDiffEngine({
  workerThreshold = 10_000,
  workerUrl = new URL("./text-diff-worker.js", import.meta.url),
  workerFactory = (url, options) => new Worker(url, options),
  diffOptions = {}
} = {}) {
  let generation = 0;
  let active = null;
  let disposed = false;

  const cancelActive = () => {
    if (!active) return;
    const cancelled = active;
    active = null;
    cancelled.worker.terminate();
    cancelled.reject(abortError());
  };

  return {
    compute(source, target, options = {}) {
      if (disposed) return Promise.reject(abortError("폐기된 비교 엔진입니다."));
      cancelActive();
      generation += 1;
      const currentGeneration = generation;
      const sourceText = String(source);
      const targetText = String(target);
      const mergedOptions = { ...diffOptions, ...options };

      if (sourceText.length + targetText.length < workerThreshold) {
        return Promise.resolve(diffText(sourceText, targetText, mergedOptions));
      }

      return new Promise((resolve, reject) => {
        let worker;
        try {
          worker = workerFactory(workerUrl, { type: "module" });
        } catch (error) {
          reject(error);
          return;
        }

        active = { generation: currentGeneration, worker, reject };
        worker.addEventListener("message", event => {
          if (active?.generation !== currentGeneration) return;
          const message = event.data;
          if (message?.generation !== currentGeneration) return;
          active = null;
          worker.terminate();
          if (message.type === "result") resolve(message.result);
          else reject(new Error(message.message || "텍스트 비교에 실패했습니다."));
        });
        worker.addEventListener("error", event => {
          if (active?.generation !== currentGeneration) return;
          active = null;
          worker.terminate();
          reject(new Error(event.message || "텍스트 비교 작업자를 시작하지 못했습니다."));
        });
        worker.postMessage({
          type: "diff",
          generation: currentGeneration,
          source: sourceText,
          target: targetText,
          options: {
            ...mergedOptions,
            maxTimeMs: mergedOptions.maxTimeMs ?? 500,
            maxDisplayNodes: mergedOptions.maxDisplayNodes ?? DEFAULT_MAX_DISPLAY_NODES
          }
        });
      });
    },

    cancel() {
      generation += 1;
      cancelActive();
    },

    dispose() {
      if (disposed) return;
      disposed = true;
      generation += 1;
      cancelActive();
    }
  };
}
