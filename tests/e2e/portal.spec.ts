import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

const readyHealth = {
  status: "ready",
  engine: "codex-cli",
  engineVersion: "0.149.0",
  humanizeVersion: "2.3.2",
  activeJobs: 0,
  queuedJobs: 0,
  rewriteOptions: [
    { id: "normal", label: "보통", description: "원래 표현을 살려 어색한 부분을 다듬습니다." },
    { id: "medium", label: "중간", description: "어휘와 길어진 표현을 더 자연스럽게 정리합니다." },
    { id: "strong", label: "강하게", description: "문장 구조와 반복 표현까지 적극적으로 바꿉니다." },
    { id: "very-strong", label: "매우 강하게", description: "뜻은 유지하고 글 전반의 표현과 문장 구성을 크게 바꿉니다." }
  ]
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", route => route.fulfill({ json: readyHealth }));
});

test("typing never transforms; clicking transforms exactly once", async ({ page }) => {
  let transformCalls = 0;
  let requestedEngine: string | null = null;
  await page.route("**/api/transform*", route => {
    transformCalls += 1;
    requestedEngine = new URL(route.request().url()).searchParams.get("engine");
    return route.fulfill({
      status: 200,
      contentType: "application/x-ndjson; charset=utf-8",
      body:
        '{"type":"accepted","jobId":"j1","position":0}\n' +
        '{"type":"progress","phase":"transform","current":1,"total":1,"message":"다듬는 중"}\n' +
        '{"type":"result-start"}\n' +
        '{"type":"result-delta","text":"자연스러운 결과"}\n' +
        '{"type":"done","sourceChars":5,"outputChars":9,"chunks":1,"elapsedMs":10}\n'
    });
  });

  await page.goto("/");
  await page.locator("#source-text").fill("원본 문구");
  await page.waitForTimeout(200);
  expect(transformCalls).toBe(0);
  await page.locator("#transform-button").click();
  await expect(page.locator("#result-text")).toHaveValue("자연스러운 결과");
  expect(transformCalls).toBe(1);
  expect(requestedEngine).toBe("codex");
  await expect(page.locator("#status-chip")).toContainText("완료");
});

test("direct text strength is described, captured, persisted, and shown with its diff", async ({ page }) => {
  await page.route("**/api/health", route => route.fulfill({
    json: { ...readyHealth, claudeAvailable: true }
  }));
  let requestUrl = "";
  let releaseRequest!: () => void;
  const requestHeld = new Promise<void>(resolve => { releaseRequest = resolve; });
  let transformCalls = 0;
  await page.route("**/api/transform*", async route => {
    transformCalls += 1;
    requestUrl = route.request().url();
    await requestHeld;
    await route.fulfill({
      status: 200,
      contentType: "application/x-ndjson; charset=utf-8",
      body:
        '{"type":"accepted","jobId":"strength-1","position":0}\n' +
        '{"type":"result-start"}\n' +
        '{"type":"result-delta","text":"문장 구조를 바꿨습니다."}\n' +
        '{"type":"done","sourceChars":14,"outputChars":13,"chunks":1,"elapsedMs":20}\n'
    });
  });

  await page.goto("/");
  const group = page.locator("#rewrite-strength");
  await expect(group).toHaveAttribute("aria-describedby", "rewrite-strength-help");
  await expect(group.locator('input[name="rewrite-strength"]')).toHaveCount(4);
  await expect(group).toContainText("매우 강하게");
  await expect(group).toContainText("뜻은 유지하고 글 전반의 표현과 문장 구성을 크게 바꿉니다.");

  await page.locator('#rewrite-strength input[value="strong"]').check();
  await page.locator("#engine-option-claude").click();
  await expect(page.locator('input[name="engine"][value="claude"]')).toBeChecked();
  await expect(page.locator('#rewrite-strength input[value="strong"]')).toBeChecked();
  expect(transformCalls).toBe(0);

  await page.locator("#source-text").fill("문장 구조는 그대로입니다.");
  await page.locator("#transform-button").click();
  await expect(group.locator("input:enabled")).toHaveCount(0);
  releaseRequest();

  await expect(page.locator("#status-chip")).toHaveText("완료");
  const query = new URL(requestUrl).searchParams;
  expect(query.get("inputKind")).toBe("direct-text");
  expect(query.get("strength")).toBe("strong");
  await expect(page.locator("#result-strength")).toHaveText("사용한 변환 강도 · 강하게");
  await expect(page.locator("#result-view-controls")).toBeVisible();
  await expect(page.locator('#result-view-controls [data-result-mode="diff"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#result-diff-host ins")).not.toHaveCount(0);
  await expect(page.locator("#result-diff-host del")).not.toHaveCount(0);
  await expect(page.locator("#result-diff-host")).toContainText("바꿨습니다");
  await expect(page.locator("#change-legend")).toContainText("추가·변경");
  await expect(page.locator("#change-legend")).toContainText("삭제");

  await page.reload();
  await expect(page.locator('#rewrite-strength input[value="strong"]')).toBeChecked();
});

test("text files exclude direct-text controls and send only the text-file policy", async ({ page }) => {
  let requestUrl = "";
  await page.route("**/api/transform*", route => {
    requestUrl = route.request().url();
    return route.fulfill({
      status: 200,
      contentType: "application/x-ndjson; charset=utf-8",
      body:
        '{"type":"accepted","jobId":"file-policy","position":0}\n' +
        '{"type":"result-start"}\n' +
        '{"type":"result-delta","text":"파일 결과"}\n' +
        '{"type":"done","sourceChars":5,"outputChars":5,"chunks":1,"elapsedMs":20}\n'
    });
  });

  await page.goto("/");
  await page.locator('#rewrite-strength input[value="very-strong"]').check();
  await page.locator("#text-file-input").setInputFiles({
    name: "sample.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("파일 원문", "utf8")
  });
  await expect(page.locator("#rewrite-controls")).toBeHidden();
  await expect(page.locator("#result-view-controls")).toBeHidden();
  await page.locator("#transform-button").click();
  await expect(page.locator("#status-chip")).toHaveText("완료");
  const query = new URL(requestUrl).searchParams;
  expect(query.get("inputKind")).toBe("text-file");
  expect(query.get("strength")).toBe("normal");
  await expect(page.locator("#result-text")).toBeVisible();
  await expect(page.locator("#result-text")).toHaveValue("파일 결과");

  await page.locator("#source-text").fill("직접 입력으로 전환");
  await expect(page.locator("#rewrite-controls")).toBeVisible();
  await expect(page.locator('#rewrite-strength input[value="very-strong"]')).toBeChecked();
});

test("final view is literal, keyboard focused, and cleared by new input", async ({ page }) => {
  await page.route("**/api/transform*", route => route.fulfill({
    status: 200,
    contentType: "application/x-ndjson; charset=utf-8",
    body:
      '{"type":"accepted","jobId":"literal","position":0}\n' +
      '{"type":"result-start"}\n' +
      '{"type":"result-delta","text":"<img src=x onerror=alert(1)> 새 문장"}\n' +
      '{"type":"done","sourceChars":4,"outputChars":35,"chunks":1,"elapsedMs":20}\n'
  }));
  await page.goto("/");
  await page.locator("#source-text").fill("이전 문장");
  await page.locator("#transform-button").click();
  await expect(page.locator("#result-diff-host img")).toHaveCount(0);
  await expect(page.locator("#result-diff-host")).toContainText("<img src=x onerror=alert(1)> 새 문장");

  const finalButton = page.locator('[data-result-mode="final"]');
  await finalButton.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#result-text")).toBeFocused();
  await expect(page.locator("#result-text")).toHaveValue("<img src=x onerror=alert(1)> 새 문장");

  await page.locator("#source-text").fill("새 원문");
  await expect(page.locator("#result-view-controls")).toBeHidden();
  await expect(page.locator("#result-diff-host")).toBeHidden();
  await expect(page.locator("#result-text")).toHaveValue("");
});

test("completed output stays visible while a large comparison is still pending", async ({ page }) => {
  const source = "가".repeat(6000);
  const completed = "나".repeat(6000);
  await page.addInitScript(() => {
    class PendingWorker {
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: ((event: ErrorEvent) => void) | null = null;
      postMessage() {}
      terminate() {}
      addEventListener() {}
      removeEventListener() {}
      dispatchEvent() { return true; }
    }
    Object.defineProperty(window, "Worker", { configurable: true, value: PendingWorker });
  });
  await page.route("**/api/transform*", route => route.fulfill({
    status: 200,
    contentType: "application/x-ndjson; charset=utf-8",
    body: [
      { type: "accepted", jobId: "pending-diff", position: 0 },
      { type: "result-start" },
      { type: "result-delta", text: completed },
      { type: "done", sourceChars: 6000, outputChars: 6000, chunks: 1, elapsedMs: 20 }
    ].map(event => JSON.stringify(event)).join("\n") + "\n"
  }));
  await page.goto("/");
  await page.locator("#source-text").fill(source);
  await page.locator("#transform-button").click();
  await expect(page.locator("#status-chip")).toHaveText("완료");
  await expect(page.locator("#result-text")).toBeVisible();
  await expect(page.locator("#result-text")).toHaveValue(completed);
});

test("Claude selection sends the selected engine without starting on selection", async ({ page }) => {
  await page.route("**/api/health", route =>
    route.fulfill({ json: { ...readyHealth, claudeAvailable: true } })
  );
  const engines: Array<string | null> = [];
  await page.route("**/api/transform*", route => {
    engines.push(new URL(route.request().url()).searchParams.get("engine"));
    return route.fulfill({
      status: 200,
      contentType: "application/x-ndjson; charset=utf-8",
      body: [
        { type: "accepted", jobId: "claude", position: 0 },
        { type: "result-start" },
        { type: "result-delta", text: "Claude 결과" },
        { type: "done", sourceChars: 2, outputChars: 9, chunks: 1, elapsedMs: 10 }
      ].map(event => JSON.stringify(event)).join("\n") + "\n"
    });
  });

  await page.goto("/");
  await page.locator("#source-text").fill("원문");
  await expect(page.locator('input[value="claude"]')).toBeEnabled();
  await page.locator("#engine-option-claude").click();
  await expect(page.locator('input[value="claude"]')).toBeChecked();
  expect(engines).toEqual([]);
  await page.locator("#transform-button").click();
  await expect(page.locator("#status-chip")).toHaveText("완료");
  expect(engines).toEqual(["claude"]);
  await expect(page.locator("#result-text")).toHaveValue("Claude 결과");
});

test("TXT selection stays local until the transform button is clicked", async ({ page }) => {
  let transformCalls = 0;
  await page.route("**/api/transform*", route => {
    transformCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: "application/x-ndjson; charset=utf-8",
      body:
        '{"type":"accepted","jobId":"j2","position":0}\n' +
        '{"type":"result-start"}\n' +
        '{"type":"result-delta","text":"파일 결과"}\n' +
        '{"type":"done","sourceChars":17,"outputChars":5,"chunks":1,"elapsedMs":20}\n'
    });
  });

  await page.goto("/");
  await page.locator("#text-file-input").setInputFiles({
    name: "sample.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("문장을 자연스럽게 다듬어 주세요.", "utf8")
  });

  await expect(page.locator("#source-text")).toHaveValue(
    "문장을 자연스럽게 다듬어 주세요."
  );
  await expect(page.locator("#source-file-name")).toContainText(
    "sample.txt · UTF-8"
  );
  expect(transformCalls).toBe(0);
  await page.locator("#transform-button").click();
  await expect(page.locator("#result-text")).toHaveValue("파일 결과");
  expect(transformCalls).toBe(1);
});

test("malformed Office file keeps the existing source", async ({ page }) => {
  await page.goto("/");
  await page.locator("#source-text").fill("기존 문구");
  await page.locator("#text-file-input").setInputFiles({
    name: "memo.docx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: Buffer.from("바뀌면 안 됨", "utf8")
  });

  await expect(page.locator("#source-text")).toHaveValue("기존 문구");
  await expect(page.locator("#status")).toContainText(
    "DOCX/PPTX ZIP 문서를 읽지 못했습니다."
  );
});

test("Markdown stays local and the completed result downloads as Markdown", async ({
  page
}) => {
  let transformCalls = 0;
  await page.route("**/api/transform*", async route => {
    transformCalls += 1;
    if (transformCalls === 3) {
      return route.fulfill({
        status: 200,
        contentType: "application/x-ndjson; charset=utf-8",
        body:
          '{"type":"accepted","jobId":"md-error","position":0}\n' +
          '{"type":"error","code":"VALIDATION_FAILED","message":"검증 실패","retryable":false}\n'
      });
    }
    if (transformCalls === 5) {
      await new Promise(resolve => setTimeout(resolve, 300));
      return route
        .fulfill({
          status: 200,
          contentType: "application/x-ndjson; charset=utf-8",
          body: '{"type":"accepted","jobId":"md-cancel","position":0}\n'
        })
        .catch(() => undefined);
    }
    return route.fulfill({
      status: 200,
      contentType: "application/x-ndjson; charset=utf-8",
      body:
        '{"type":"accepted","jobId":"md-1","position":0}\n' +
        '{"type":"progress","phase":"sanitize","current":0,"total":1,"message":"준비 중"}\n' +
        '{"type":"progress","phase":"chunk","current":1,"total":1,"message":"구간 준비"}\n' +
        '{"type":"progress","phase":"transform","current":1,"total":1,"message":"다듬는 중"}\n' +
        '{"type":"progress","phase":"verify","current":1,"total":1,"message":"검증 중"}\n' +
        '{"type":"progress","phase":"assemble","current":1,"total":1,"message":"조립 중"}\n' +
        '{"type":"result-start"}\n' +
        '{"type":"result-delta","text":"# 제목\\n\\n자연스러운 결과"}\n' +
        '{"type":"done","sourceChars":12,"outputChars":16,"chunks":1,"elapsedMs":20}\n'
    });
  });

  await page.goto("/");
  await expect(page.locator("#download-button")).toBeHidden();
  await page.locator("#text-file-input").setInputFiles({
    name: "guide.v2.MD",
    mimeType: "text/markdown",
    buffer: Buffer.from("# 제목\n\n다듬을 본문", "utf8")
  });

  await expect(page.locator("#source-text")).toHaveValue(
    "# 제목\n\n다듬을 본문"
  );
  await expect(page.locator("#source-file-name")).toContainText(
    "guide.v2.MD · UTF-8"
  );
  expect(transformCalls).toBe(0);

  await page.locator("#transform-button").click();
  await expect(page.locator("#result-text")).toHaveValue(
    "# 제목\n\n자연스러운 결과"
  );
  await expect(page.locator("#download-button")).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await page.locator("#download-button").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("guide.v2-humanized.md");
  const downloadPath = await download.path();
  expect(downloadPath).not.toBeNull();
  expect(await readFile(downloadPath!, "utf8")).toBe(
    "# 제목\n\n자연스러운 결과"
  );

  await page.locator("#reset-button").click();
  await expect(page.locator("#source-text")).toHaveValue("");
  await expect(page.locator("#download-button")).toBeHidden();
  await page.locator("#text-file-input").setInputFiles({
    name: "guide.v2.MD",
    mimeType: "text/markdown",
    buffer: Buffer.from("# 제목\n\n다듬을 본문", "utf8")
  });

  await page.locator("#source-text").fill("직접 붙여넣은 새 원문");
  await expect(page.locator("#source-file-name")).toBeHidden();
  await page.locator("#transform-button").click();
  await expect(page.locator("#status-chip")).toHaveText("완료");
  await expect(page.locator("#download-button")).toBeHidden();

  await page.locator("#text-file-input").setInputFiles({
    name: "failed.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# 실패할 문서", "utf8")
  });
  await page.locator("#transform-button").click();
  await expect(page.locator("#status-chip")).toHaveText("오류");
  await expect(page.locator("#download-button")).toBeHidden();

  await page.locator("#text-file-input").setInputFiles({
    name: "plain.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("TXT 원문", "utf8")
  });
  await page.locator("#transform-button").click();
  await expect(page.locator("#status-chip")).toHaveText("완료");
  await expect(page.locator("#download-button")).toBeHidden();

  await page.locator("#text-file-input").setInputFiles({
    name: "cancel.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# 취소할 문서", "utf8")
  });
  await page.locator("#transform-button").click();
  await expect(page.locator("#cancel-button")).toBeVisible();
  await page.locator("#cancel-button").click();
  await expect(page.locator("#status-chip")).toHaveText("취소됨");
  await expect(page.locator("#download-button")).toBeHidden();

  await page.locator("#reset-button").click();
  await expect(page.locator("#download-button")).toBeHidden();
});

test("progress and status stay monotonic across all transform phases", async ({ page }) => {
  await page.addInitScript(() => {
    const values: Array<number | "indeterminate"> = [];
    const statusMessages: string[] = [];
    Object.defineProperty(window, "__progressValues", {
      configurable: true,
      value: values
    });
    Object.defineProperty(window, "__statusMessages", {
      configurable: true,
      value: statusMessages
    });
    window.addEventListener("DOMContentLoaded", () => {
      const statusMessage = document.querySelector("#status-message");
      if (!statusMessage) return;
      new MutationObserver(records => {
        for (const record of records) {
          for (const node of record.addedNodes) {
            const message = node.textContent?.trim();
            if (message) statusMessages.push(message);
          }
        }
      }).observe(statusMessage, { childList: true });
    });
    const descriptor = Object.getOwnPropertyDescriptor(
      HTMLProgressElement.prototype,
      "value"
    );
    if (!descriptor?.get || !descriptor.set) return;
    Object.defineProperty(HTMLProgressElement.prototype, "value", {
      configurable: true,
      get() {
        return descriptor.get!.call(this);
      },
      set(value: number) {
        values.push(Number(value));
        descriptor.set!.call(this, value);
      }
    });
    const removeAttribute = HTMLProgressElement.prototype.removeAttribute;
    Object.defineProperty(HTMLProgressElement.prototype, "removeAttribute", {
      configurable: true,
      value(name: string) {
        if (name === "value") values.push("indeterminate");
        return removeAttribute.call(this, name);
      }
    });
  });
  await page.route("**/api/transform*", route =>
    route.fulfill({
      status: 200,
      contentType: "application/x-ndjson; charset=utf-8",
      body:
        '{"type":"accepted","jobId":"progress-1","position":0}\n' +
        '{"type":"queued","position":2}\n' +
        '{"type":"progress","phase":"sanitize","current":0,"total":1,"message":"준비 중"}\n' +
        '{"type":"progress","phase":"chunk","current":1,"total":1,"message":"구간 준비"}\n' +
        '{"type":"progress","phase":"transform","current":2,"total":2,"completedUnits":1,"totalUnits":4,"message":"2/2 변환"}\n' +
        '{"type":"progress","phase":"transform","current":1,"total":2,"completedUnits":2,"totalUnits":4,"message":"1/2 변환"}\n' +
        '{"type":"progress","phase":"verify","current":2,"total":2,"completedUnits":3,"totalUnits":4,"message":"2/2 검증"}\n' +
        '{"type":"progress","phase":"verify","current":1,"total":2,"completedUnits":4,"totalUnits":4,"message":"1/2 검증"}\n' +
        '{"type":"progress","phase":"assemble","current":1,"total":1,"message":"조립"}\n' +
        '{"type":"result-start"}\n' +
        '{"type":"result-delta","text":"결과"}\n' +
        '{"type":"done","sourceChars":2,"outputChars":2,"chunks":2,"elapsedMs":30}\n'
    })
  );

  await page.goto("/");
  await page.locator("#source-text").fill("원문");
  await page.locator("#transform-button").click();
  await expect(page.locator("#status-chip")).toHaveText("완료");
  await expect(page.locator("#progress-value")).toHaveText("100%");

  const records = await page.evaluate(
    () =>
      (
        window as Window & {
          __progressValues: Array<number | "indeterminate">;
        }
      ).__progressValues
  );
  const queuedIndex = records.indexOf("indeterminate");
  expect(queuedIndex).toBeGreaterThanOrEqual(0);
  expect(records.slice(queuedIndex + 1)).toContain(5);
  const values = records.filter(
    (value): value is number => typeof value === "number"
  );
  expect(values).toEqual(expect.arrayContaining([5, 15, 33.75, 52.5, 71.25, 90, 95, 100]));
  for (let index = 1; index < values.length; index += 1) {
    expect(values[index]).toBeGreaterThanOrEqual(values[index - 1]!);
  }
  const statusMessages = await page.evaluate(
    () =>
      (
        window as Window & {
          __statusMessages: string[];
        }
      ).__statusMessages
  );
  const workStatusMessages = statusMessages.filter(message =>
    /^(?:전체 작업 [1-4]\/4 진행 중입니다\.|[12]\/2 (?:변환|검증))$/.test(message)
  );
  expect(workStatusMessages).toEqual([
    "전체 작업 1/4 진행 중입니다.",
    "전체 작업 2/4 진행 중입니다.",
    "전체 작업 3/4 진행 중입니다.",
    "전체 작업 4/4 진행 중입니다."
  ]);
  await expect(page.locator("#progress")).toHaveAttribute("value", "100");
});

test("copy works on an HTTP LAN page without the Clipboard API", async ({ page }) => {
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: "http://127.0.0.1:7882"
  });
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined
    });
  });
  await page.route("**/api/transform*", route =>
    route.fulfill({
      status: 200,
      contentType: "application/x-ndjson; charset=utf-8",
      body:
        '{"type":"accepted","jobId":"j3","position":0}\n' +
        '{"type":"result-start"}\n' +
        '{"type":"result-delta","text":"복사할 결과"}\n' +
        '{"type":"done","sourceChars":2,"outputChars":6,"chunks":1,"elapsedMs":20}\n'
    })
  );
  await page.goto("/");
  await page.locator("#source-text").fill("원문");
  await page.locator("#transform-button").click();
  await expect(page.locator("#result-text")).toHaveValue("복사할 결과");

  await page.locator("#result-diff-host del").evaluate(element => {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(element);
    selection?.removeAllRanges();
    selection?.addRange(range);
  });

  await page.locator("#copy-button").click();

  await expect(page.locator("#copy-button")).toHaveText("복사됨");
  expect(await page.evaluate(async () => {
    delete (navigator as Navigator & { clipboard?: Clipboard }).clipboard;
    return navigator.clipboard.readText();
  })).toBe("복사할 결과");
  expect(await page.evaluate(() => window.getSelection()?.toString())).toContain("원문");
});

test("copying a partial comparison projects the selection to final text", async ({ page }) => {
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: "http://127.0.0.1:7882"
  });
  await page.route("**/api/transform*", route => route.fulfill({
    status: 200,
    contentType: "application/x-ndjson; charset=utf-8",
    body:
      '{"type":"accepted","jobId":"diff-copy","position":0}\n' +
      '{"type":"result-start"}\n' +
      '{"type":"result-delta","text":"앞 새 표현 뒤"}\n' +
      '{"type":"done","sourceChars":8,"outputChars":8,"chunks":1,"elapsedMs":20}\n'
  }));
  await page.goto("/");
  await page.locator("#source-text").fill("앞 이전 표현 뒤");
  await page.locator("#transform-button").click();
  const changes = page.locator("#result-diff-host .result-diff__changes");
  await expect(changes.locator("del")).toContainText("이전");
  await expect(changes.locator("ins")).toContainText("새");
  await changes.evaluate(element => {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(element);
    selection?.removeAllRanges();
    selection?.addRange(range);
  });
  await page.keyboard.press("Control+C");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("앞 새 표현 뒤");
});

test("idle portal has no WCAG A or AA violations and touch targets are large", async ({ page }) => {
  await page.goto("/");
  const scan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(scan.violations).toEqual([]);

  for (const selector of [
    "#text-file-button",
    "#transform-button",
    "#reset-button"
  ]) {
    const box = await page.locator(selector).boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(44);
  }
});
