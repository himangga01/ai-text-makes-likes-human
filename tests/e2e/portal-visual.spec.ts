import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", route =>
    route.fulfill({
      json: {
        status: "ready",
        engine: "codex-cli",
        engineVersion: "0.149.0",
        humanizeVersion: "2.3.2",
        activeJobs: 0,
        queuedJobs: 0
      }
    })
  );
});

async function showState(
  page: import("@playwright/test").Page,
  state: "queued" | "processing" | "success" | "error"
) {
  await page.locator("#source-text").fill(
    "이 결과는 다양한 요인에 의해 도출되어진 것으로 판단됩니다."
  );
  await page.locator("#source-text").evaluate(element => {
    (element as HTMLTextAreaElement).blur();
  });
  await page.evaluate(selected => {
    const shell = document.querySelector("#editor-shell");
    const status = document.querySelector("#status");
    const chip = document.querySelector("#status-chip");
    const message = document.querySelector("#status-message");
    const progressPanel = document.querySelector<HTMLElement>("#progress-panel");
    const progress = document.querySelector("#progress");
    const progressValue = document.querySelector("#progress-value");
    const transform = document.querySelector("#transform-button");
    const cancel = document.querySelector("#cancel-button");
    const result = document.querySelector("#result-text");
    const empty = document.querySelector("#result-empty");
    if (!(shell && status && chip && message && progressPanel && progress && progressValue && transform && cancel && result && empty)) return;
    shell.dataset.state = selected;
    status.dataset.state = selected;
    chip.className = `status-chip status-${selected === "queued" ? "processing" : selected}`;
    progressPanel.hidden = selected === "error";
    transform.hidden = selected === "queued" || selected === "processing";
    cancel.hidden = !(selected === "queued" || selected === "processing");
    if (selected === "queued") {
      chip.textContent = "대기 2";
      message.textContent = "앞에 2건의 작업이 있습니다.";
      progress.removeAttribute("value");
      progressValue.textContent = "대기 중";
    } else if (selected === "processing") {
      chip.textContent = "변환 중";
      message.textContent = "2/4 구간을 다듬는 중입니다.";
      progress.value = 28.75;
      progressValue.textContent = "29%";
    } else if (selected === "success") {
      chip.textContent = "완료";
      message.textContent = "4개 구간 · 8.4초 만에 완료했습니다.";
      progress.value = 100;
      progressValue.textContent = "100%";
      result.value = "여러 요인으로 이런 결과가 나왔다.";
      empty.hidden = true;
    } else {
      chip.textContent = "검증 오류";
      message.textContent = "내용 보존 검증을 통과하지 못했습니다.";
    }
  }, state);
}

test.describe("desktop visual hierarchy", () => {
  test.use({
    viewport: { width: 1440, height: 1000 },
    colorScheme: "light",
    reducedMotion: "reduce"
  });

  test("idle desktop", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveScreenshot("portal-idle-desktop.png", {
      fullPage: true,
      animations: "disabled",
      maxDiffPixelRatio: 0.01
    });
  });

  test("ready desktop with TXT chip", async ({ page }) => {
    await page.goto("/");
    await page.locator("#text-file-input").setInputFiles({
      name: "sample.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("문장을 자연스럽게 다듬어 주세요.", "utf8")
    });
    await expect(page).toHaveScreenshot("portal-txt-ready-desktop.png", {
      fullPage: true,
      animations: "disabled",
      maxDiffPixelRatio: 0.01
    });
  });

  for (const state of ["queued", "processing", "success", "error"] as const) {
    test(`${state} desktop`, async ({ page }) => {
      await page.goto("/");
      await showState(page, state);
      await expect(page).toHaveScreenshot(`portal-${state}-desktop.png`, {
        fullPage: true,
        animations: "disabled",
        maxDiffPixelRatio: 0.01
      });
    });
  }
});

test.describe("mobile visual hierarchy", () => {
  test.use({
    viewport: { width: 390, height: 844 },
    colorScheme: "light",
    reducedMotion: "reduce"
  });

  test("idle mobile", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveScreenshot("portal-idle-mobile.png", {
      fullPage: true,
      animations: "disabled",
      maxDiffPixelRatio: 0.01
    });
  });

  for (const state of ["processing", "success"] as const) {
    test(`${state} mobile`, async ({ page }) => {
      await page.goto("/");
      await showState(page, state);
      await expect(page).toHaveScreenshot(`portal-${state}-mobile.png`, {
        fullPage: true,
        animations: "disabled",
        maxDiffPixelRatio: 0.01
      });
    });
  }
});
