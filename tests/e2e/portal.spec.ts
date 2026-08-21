import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const readyHealth = {
  status: "ready",
  engine: "codex-cli",
  engineVersion: "0.149.0",
  humanizeVersion: "2.3.2",
  activeJobs: 0,
  queuedJobs: 0
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", route => route.fulfill({ json: readyHealth }));
});

test("typing never transforms; clicking transforms exactly once", async ({ page }) => {
  let transformCalls = 0;
  await page.route("**/api/transform", route => {
    transformCalls += 1;
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
  await expect(page.locator("#status-chip")).toContainText("완료");
});

test("TXT selection stays local until the transform button is clicked", async ({ page }) => {
  let transformCalls = 0;
  await page.route("**/api/transform", route => {
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

test("invalid file keeps the existing source", async ({ page }) => {
  await page.goto("/");
  await page.locator("#source-text").fill("기존 문구");
  await page.locator("#text-file-input").setInputFiles({
    name: "memo.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("바뀌면 안 됨", "utf8")
  });

  await expect(page.locator("#source-text")).toHaveValue("기존 문구");
  await expect(page.locator("#status")).toContainText(
    "TXT 파일만 불러올 수 있습니다."
  );
});

test("copy works on an HTTP LAN page without the Clipboard API", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined
    });
  });
  await page.route("**/api/transform", route =>
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

  await page.locator("#copy-button").click();

  await expect(page.locator("#copy-button")).toHaveText("복사됨");
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
