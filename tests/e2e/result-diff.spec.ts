import { expect, test } from "@playwright/test";

async function mountResultDiff(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.evaluate(async () => {
    const { createResultDiff } = await import("/result-diff.js");
    const container = document.createElement("div");
    container.id = "result-diff-test-host";
    document.body.replaceChildren(container);
    const statuses: unknown[] = [];
    Object.assign(window, {
      __resultDiffStatuses: statuses,
      __resultDiff: createResultDiff({
        container,
        onStatus: (status: unknown) => statuses.push(status)
      })
    });
  });
}

async function mountControlledResultDiff(
  page: import("@playwright/test").Page,
  renderBatchSize = 100
) {
  await page.goto("/");
  await page.evaluate(async batchSize => {
    const { createResultDiff } = await import("/result-diff.js");
    const { diffText } = await import("/text-diff.js");
    const container = document.createElement("div");
    container.id = "result-diff-test-host";
    document.body.replaceChildren(container);
    const statuses: unknown[] = [];
    const workers: any[] = [];
    const frames: FrameRequestCallback[] = [];
    const workerFactory = () => {
      const listeners = new Map<string, Array<(event: any) => void>>();
      const worker = {
        request: undefined as any,
        addEventListener(type: string, listener: (event: any) => void) {
          const registered = listeners.get(type) ?? [];
          registered.push(listener);
          listeners.set(type, registered);
        },
        postMessage(message: any) {
          this.request = message;
        },
        terminate() {},
        respond() {
          const result = diffText(
            this.request.source,
            this.request.target,
            this.request.options
          );
          for (const listener of listeners.get("message") ?? []) {
            listener({
              data: {
                type: "result",
                generation: this.request.generation,
                result
              }
            });
          }
        },
        fail(message: string) {
          for (const listener of listeners.get("error") ?? []) listener({ message });
        }
      };
      workers.push(worker);
      return worker;
    };
    Object.assign(window, {
      __resultDiffStatuses: statuses,
      __controlledDiff: { workers, frames },
      __resultDiff: createResultDiff({
        container,
        onStatus: (status: unknown) => statuses.push(status),
        workerThreshold: 1,
        workerFactory,
        renderBatchSize: batchSize,
        scheduleFrame: (callback: FrameRequestCallback) => frames.push(callback)
      })
    });
  }, renderBatchSize);
}

test("renders exact safe text with semantic change nodes and host-controlled modes", async ({ page }) => {
  await mountResultDiff(page);
  const source = '<img src=x onerror="window.__xss=1">\n기존 문장 👨‍👩‍👧‍👦';
  const target = '<script>window.__xss=2</script>\n새 문장 👩‍💻';

  const result = await page.evaluate(async ({ source, target }) => {
    const component = (window as any).__resultDiff;
    const rendered = await component.setResult(source, target);
    component.setMode("final");
    return rendered;
  }, { source, target });

  expect(result.status).toBe("rendered");
  await expect(page.locator(".result-diff__final")).toHaveText(target);
  await expect(page.locator(".result-diff__final")).toBeVisible();
  await expect(page.locator(".result-diff__changes")).toBeHidden();
  expect(await page.locator("#result-diff-test-host img, #result-diff-test-host script").count()).toBe(0);
  expect(await page.evaluate(() => (window as any).__xss)).toBeUndefined();

  await page.evaluate(() => (window as any).__resultDiff.setMode("diff"));
  await expect(page.locator(".result-diff__changes")).toBeVisible();
  await expect(page.locator(".result-diff__changes del").first()).toHaveAttribute("aria-label", /삭제 시작.*삭제 끝/s);
  await expect(page.locator(".result-diff__changes ins").first()).toHaveAttribute("aria-label", /삽입 시작.*삽입 끝/s);
  await expect(page.locator(".result-diff__copy-hint")).toContainText("삭제된 내용은 제외");
});

test("uses the HTTP module worker and renders a bounded truthful fallback for 50k input", async ({ page }) => {
  await mountResultDiff(page);
  const reconstruction = await page.evaluate(async () => {
    const source = "가".repeat(25_000);
    const target = "나".repeat(25_000);
    const rendered = await (window as any).__resultDiff.setResult(source, target);
    const changes = document.querySelector(".result-diff__changes")!;
    return {
      status: rendered.status,
      coarse: rendered.result.coarse,
      nodes: changes.childNodes.length,
      source: Array.from(changes.childNodes)
        .filter(node => !(node instanceof HTMLElement) || node.tagName !== "INS")
        .map(node => node.textContent).join(""),
      target: Array.from(changes.childNodes)
        .filter(node => !(node instanceof HTMLElement) || node.tagName !== "DEL")
        .map(node => node.textContent).join("")
    };
  });

  expect(reconstruction).toEqual({
    status: "rendered",
    coarse: true,
    nodes: 2,
    source: "가".repeat(25_000),
    target: "나".repeat(25_000)
  });
  await expect(page.locator(".result-diff__notice")).toContainText(/간략|한도/);
});

test("final-view selection keeps native copy behavior", async ({ page }) => {
  await mountResultDiff(page);
  const copied = await page.evaluate(async () => {
    const component = (window as any).__resultDiff;
    await component.setResult("삭제될 원문", "그대로 복사할 최종문");
    component.setMode("final");
    const finalView = document.querySelector(".result-diff__final")!;
    const range = document.createRange();
    range.selectNodeContents(finalView);
    const selection = getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    const data = new DataTransfer();
    data.setData("text/plain", "브라우저가 처리할 값");
    const statusCount = (window as any).__resultDiffStatuses.length;
    const event = new ClipboardEvent("copy", {
      bubbles: true,
      cancelable: true,
      clipboardData: data
    });
    document.dispatchEvent(event);
    return {
      prevented: event.defaultPrevented,
      text: data.getData("text/plain"),
      statusAdded: (window as any).__resultDiffStatuses.length - statusCount
    };
  });

  expect(copied).toEqual({
    prevented: false,
    text: "브라우저가 처리할 값",
    statusAdded: 0
  });
});

test("a new generation clears a superseded partial render and preserves the latest result", async ({ page }) => {
  await mountControlledResultDiff(page, 1);
  const state = await page.evaluate(async () => {
    const component = (window as any).__resultDiff;
    const controlled = (window as any).__controlledDiff;
    const changes = document.querySelector(".result-diff__changes")!;
    const finalView = document.querySelector(".result-diff__final")!;
    const tick = () => new Promise(resolve => setTimeout(resolve, 0));

    const first = component.setResult("OLD-A OLD-B", "OLD-A NEW-B");
    controlled.workers[0].respond();
    await tick();
    const partialBeforeSupersede = changes.textContent;

    const second = component.setResult("LATEST OLD", "LATEST FINAL");
    const pendingChanges = changes.textContent;
    const pendingFinal = finalView.textContent;
    controlled.workers[1].respond();

    for (let index = 0; index < 20; index += 1) {
      const frame = controlled.frames.shift();
      if (frame) frame(performance.now());
      await tick();
    }
    const [firstResult, secondResult] = await Promise.all([first, second]);
    return {
      partialBeforeSupersede,
      pendingChanges,
      pendingFinal,
      firstStatus: firstResult.status,
      secondStatus: secondResult.status,
      finalText: finalView.textContent,
      renderedText: changes.textContent
    };
  });

  expect(state.partialBeforeSupersede).toContain("OLD-A");
  expect(state.pendingChanges).toBe("");
  expect(state.pendingFinal).toBe("LATEST FINAL");
  expect(state.firstStatus).toBe("stale");
  expect(state.secondStatus).toBe("rendered");
  expect(state.finalText).toBe("LATEST FINAL");
  expect(state.renderedText).not.toContain("OLD-A");
});

test("a rejected worker leaves the latest final text without an older diff", async ({ page }) => {
  await mountControlledResultDiff(page);
  const state = await page.evaluate(async () => {
    const component = (window as any).__resultDiff;
    const controlled = (window as any).__controlledDiff;
    const changes = document.querySelector(".result-diff__changes")!;
    const finalView = document.querySelector(".result-diff__final")!;

    const first = component.setResult("PREVIOUS SOURCE", "PREVIOUS FINAL");
    controlled.workers[0].respond();
    await first;
    const previousChanges = changes.textContent;

    const rejected = component.setResult("FAILED SOURCE", "LATEST FINAL");
    const pendingChanges = changes.textContent;
    controlled.workers[1].fail("worker rejected");
    let errorMessage = "";
    try {
      await rejected;
    } catch (error) {
      errorMessage = (error as Error).message;
    }
    return {
      previousChanges,
      pendingChanges,
      afterFailureChanges: changes.textContent,
      finalText: finalView.textContent,
      rootVisible: !(document.querySelector(".result-diff") as HTMLElement).hidden,
      errorMessage
    };
  });

  expect(state.previousChanges).toContain("PREVIOUS");
  expect(state.pendingChanges).toBe("");
  expect(state.afterFailureChanges).toBe("");
  expect(state.finalText).toBe("LATEST FINAL");
  expect(state.rootVisible).toBe(true);
  expect(state.errorMessage).toBe("worker rejected");
});

test("diff selection copy emits only final text and preserves the clipboard for unsafe ranges", async ({ page }) => {
  await mountResultDiff(page);
  await page.evaluate(async () => {
    await (window as any).__resultDiff.setResult(
      "그는 아주 빠르다.",
      "그는 빠르고 정확하다."
    );
  });

  const wholeDiffCopy = await page.evaluate(() => {
    const changes = document.querySelector(".result-diff__changes")!;
    const range = document.createRange();
    range.selectNodeContents(changes);
    const selection = getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    const data = new DataTransfer();
    const event = new ClipboardEvent("copy", { bubbles: true, cancelable: true, clipboardData: data });
    document.dispatchEvent(event);
    return { text: data.getData("text/plain"), types: [...data.types], prevented: event.defaultPrevented };
  });
  expect(wholeDiffCopy).toEqual({
    text: "그는 빠르고 정확하다.",
    types: ["text/plain"],
    prevented: true
  });

  const deletionOnly = await page.evaluate(() => {
    const deletion = document.querySelector(".result-diff__changes del")!;
    const range = document.createRange();
    range.selectNodeContents(deletion);
    const selection = getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    const data = new DataTransfer();
    data.setData("text/plain", "기존 클립보드");
    const event = new ClipboardEvent("copy", { bubbles: true, cancelable: true, clipboardData: data });
    document.dispatchEvent(event);
    return {
      text: data.getData("text/plain"),
      prevented: event.defaultPrevented,
      statuses: (window as any).__resultDiffStatuses
    };
  });
  expect(deletionOnly.text).toBe("기존 클립보드");
  expect(deletionOnly.prevented).toBe(true);
  expect(JSON.stringify(deletionOnly.statuses)).toContain("삭제된 내용만");

  const outsideRange = await page.evaluate(() => {
    const outside = document.createElement("span");
    outside.textContent = "외부";
    document.body.prepend(outside);
    const changes = document.querySelector(".result-diff__changes")!;
    const range = document.createRange();
    range.setStart(outside.firstChild!, 0);
    range.setEnd(changes.lastChild!, changes.lastChild!.textContent!.length);
    const selection = getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    const data = new DataTransfer();
    data.setData("text/plain", "기존 클립보드");
    const event = new ClipboardEvent("copy", { bubbles: true, cancelable: true, clipboardData: data });
    document.dispatchEvent(event);
    return {
      text: data.getData("text/plain"),
      prevented: event.defaultPrevented,
      statuses: (window as any).__resultDiffStatuses
    };
  });
  expect(outsideRange.text).toBe("기존 클립보드");
  expect(outsideRange.prevented).toBe(true);
  expect(JSON.stringify(outsideRange.statuses)).toContain("최종문 보기");
});

test("reset clears rendered text and dispose makes later work unavailable", async ({ page }) => {
  await mountResultDiff(page);
  const state = await page.evaluate(async () => {
    const component = (window as any).__resultDiff;
    await component.setResult("원문", "결과");
    component.reset();
    const afterReset = document.querySelector("#result-diff-test-host")!.textContent;
    component.dispose();
    let errorName = "";
    try {
      await component.setResult("다시", "실행");
    } catch (error) {
      errorName = (error as Error).name;
    }
    return { afterReset, errorName };
  });

  expect(state.afterReset).not.toContain("원문");
  expect(state.afterReset).not.toContain("결과");
  expect(state.errorName).toBe("AbortError");
});
