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
});
