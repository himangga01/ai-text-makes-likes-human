import { expect, test, type Page } from "@playwright/test";

// The collapsed "MCP 연결 방법" guide at the very bottom of the page. It is web-only: the desktop app has no portal
// server for an MCP client to reach, so the guide is hidden there.

const ready = {
  status: "ready",
  checkedAt: "2026-09-09T07:00:00.000Z",
  providers: {
    codex: { ready: true, installed: true, authenticated: true, message: "Codex 사용 가능" },
    claude: { ready: true, installed: true, authenticated: true, message: "Claude 사용 가능" }
  }
};

async function openPage(page: Page) {
  await page.route("**/api/health", route => route.fulfill({ json: ready }));
  await page.goto("/");
  await expect(page.locator("#codex-connection")).toHaveAttribute("data-state", "ready");
}

test("the guide is the last thing on the page and starts collapsed", async ({ page }) => {
  await openPage(page);
  const summary = page.locator("#mcp-details > summary");
  await expect(summary).toBeVisible();
  await expect(summary).toHaveText("MCP 연결 방법");
  expect(await page.locator("#mcp-details").evaluate(element => (element as HTMLDetailsElement).open)).toBe(false);
  // Nothing inside is visible or reachable while collapsed.
  await expect(page.locator("#mcp-local-note")).toBeHidden();
  await expect(page.locator("#mcp-claude-mac")).toBeHidden();

  const placement = await page.evaluate(() => {
    const guide = document.querySelector("#mcp-help")!;
    const footer = document.querySelector(".portal-footer")!;
    const lastContent = [...document.body.children].filter(element => element.tagName !== "SCRIPT").at(-1);
    return {
      isLastElement: lastContent === guide,
      belowFooter: guide.getBoundingClientRect().top >= footer.getBoundingClientRect().bottom - 1
    };
  });
  expect(placement).toEqual({ isLastElement: true, belowFooter: true });
});

test("a click opens and closes the guide, and the local-only limit is stated", async ({ page }) => {
  await openPage(page);
  const summary = page.locator("#mcp-details > summary");
  await summary.click();
  await expect(page.locator("#mcp-local-note")).toBeVisible();
  await expect(page.locator("#mcp-local-note")).toContainText("이 포털을 실행하는 PC에서 연결합니다");
  await expect(page.locator("#mcp-local-note")).toContainText("http://127.0.0.1:7882");
  await expect(page.locator("#mcp-local-note")).toContainText("외부 접속 주소로는 연결되지 않습니다");
  await expect(page.locator("#mcp-local-note")).toContainText("로그인");
  await expect(page.locator("#mcp-details")).toContainText("HUMANIZE_PORTAL_URL");

  // The registration commands from docs/mcp.md, with placeholders instead of a real path.
  await expect(page.locator("#mcp-claude-mac")).toHaveText("claude mcp add -s user humanize-kr -- node <저장소 경로>/dist/mcp/server.js");
  await expect(page.locator("#mcp-claude-win")).toHaveText("claude mcp add -s user humanize-kr -- node <저장소 경로>\\dist\\mcp\\server.js");
  await expect(page.locator("#mcp-codex-mac")).toContainText("[mcp_servers.humanize-kr]");
  await expect(page.locator("#mcp-codex-mac")).toContainText("tool_timeout_sec = 3600");
  await expect(page.locator("#mcp-codex-win")).toContainText("tool_timeout_sec = 3600");
  await expect(page.locator("#mcp-timeout-mac")).toHaveText("MCP_TOOL_TIMEOUT=3600000 claude");
  await expect(page.locator("#mcp-check")).toContainText("--allowedTools mcp__humanize-kr__humanize_status");
  for (const tool of ["humanize_text", "humanize_file", "humanize_status"]) {
    await expect(page.locator("#mcp-details")).toContainText(tool);
  }
  for (const symptom of ["PORTAL_UNREACHABLE", "QUEUE_FULL", "MCP_TOOL_TIMEOUT", "docs/mcp.md"]) {
    await expect(page.locator("#mcp-details")).toContainText(symptom);
  }

  await summary.click();
  await expect(page.locator("#mcp-local-note")).toBeHidden();
  expect(await page.locator("#mcp-details").evaluate(element => (element as HTMLDetailsElement).open)).toBe(false);
});

test("the guide opens and closes from the keyboard", async ({ page }) => {
  await openPage(page);
  const summary = page.locator("#mcp-details > summary");
  await summary.focus();
  await expect(summary).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#mcp-local-note")).toBeVisible();
  await page.keyboard.press("Space");
  await expect(page.locator("#mcp-local-note")).toBeHidden();
  await page.keyboard.press("Space");
  await expect(page.locator("#mcp-local-note")).toBeVisible();
});

test("the guide names no personal path, host name or external address", async ({ page }) => {
  await openPage(page);
  const html = await page.locator("#mcp-help").innerHTML();
  expect(html).not.toMatch(/\/Users\//);
  expect(html).not.toMatch(/C:\\Users/i);
  // The only addresses are this computer's own.
  const addresses = [...html.matchAll(/https?:\/\/([^/:"'\s<]+)/g)].map(match => match[1]);
  expect(addresses.length).toBeGreaterThan(0);
  for (const host of addresses) expect(["127.0.0.1", "localhost"]).toContain(host);
});

test("opening the guide makes no request and breaks no content-security rule", async ({ page }) => {
  const violations: string[] = [];
  page.on("console", message => {
    if (/content security policy/i.test(message.text())) violations.push(message.text());
  });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", event => {
      console.error(`Content Security Policy violation: ${event.violatedDirective}`);
    });
  });
  await openPage(page);
  const origin = new URL(test.info().project.use.baseURL!).origin;
  const external: string[] = [];
  page.on("request", request => {
    if (!request.url().startsWith(origin)) external.push(request.url());
  });
  await page.locator("#mcp-details > summary").click();
  await expect(page.locator("#mcp-local-note")).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(external).toEqual([]);
  expect(violations).toEqual([]);
});

for (const [name, size] of [["desktop", { width: 1440, height: 1000 }], ["phone", { width: 390, height: 844 }]] as const) {
  test(`the open guide never widens the ${name} page`, async ({ page }) => {
    await page.setViewportSize(size);
    await openPage(page);
    await page.locator("#mcp-details > summary").click();
    await expect(page.locator("#mcp-local-note")).toBeVisible();
    const fit = await page.evaluate(() => ({
      page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      overflowing: [...document.querySelectorAll<HTMLElement>("#mcp-help *")]
        .filter(element => element.getBoundingClientRect().right > document.documentElement.clientWidth + 0.5)
        .map(element => element.tagName + (element.id ? `#${element.id}` : ""))
    }));
    expect(fit.page).toBeLessThanOrEqual(0);
    expect(fit.overflowing).toEqual([]);
  });
}

test("each command has a copy button that copies exactly the command", async ({ page }) => {
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: new URL(test.info().project.use.baseURL!).origin
  });
  await openPage(page);
  await page.locator("#mcp-details > summary").click();
  const buttons = page.locator("#mcp-help [data-copy-target]");
  const count = await buttons.count();
  expect(count).toBeGreaterThanOrEqual(8);
  for (let index = 0; index < count; index += 1) {
    const targetId = await buttons.nth(index).getAttribute("data-copy-target");
    await expect(page.locator(`#${targetId}`)).toHaveCount(1);
    await expect(buttons.nth(index)).toHaveAttribute("aria-label", /복사$/);
  }

  const button = page.locator('[data-copy-target="mcp-claude-mac"]');
  await button.click();
  await expect(button).toHaveText("복사됨");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "claude mcp add -s user humanize-kr -- node <저장소 경로>/dist/mcp/server.js"
  );
  await expect(button).toHaveText("복사");

  const toml = page.locator('[data-copy-target="mcp-codex-win"]');
  await toml.click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "[mcp_servers.humanize-kr]\ncommand = 'C:\\Program Files\\nodejs\\node.exe'\nargs = ['<저장소 경로>\\dist\\mcp\\server.js']\ntool_timeout_sec = 3600"
  );
});

test("a refused clipboard says so on the button instead of failing silently", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async () => { throw new Error("denied"); } }
    });
  });
  await openPage(page);
  await page.locator("#mcp-details > summary").click();
  const button = page.locator('[data-copy-target="mcp-build-mac"]');
  await button.click();
  await expect(button).toHaveText("복사 실패");
  await expect(button).toHaveText("복사");
});

test("the desktop app has no MCP guide", async ({ page }) => {
  await page.addInitScript(health => {
    (window as unknown as { humanizeDesktop: unknown }).humanizeDesktop = {
      health: async () => health,
      preferences: async () => ({ selectedEngine: "codex", models: {}, rewriteStrength: "normal" }),
      selectEngine: async () => {}
    };
  }, ready);
  await page.goto("/");
  await expect(page.locator("#network-scope")).toHaveText("내 PC에서 실행");
  await expect(page.locator("#mcp-help")).toBeHidden();
  await expect(page.locator("#mcp-details > summary")).toBeHidden();
  // The desktop page is otherwise intact.
  await expect(page.locator("#editor-shell")).toBeVisible();
});

test("the web page shows the guide and keeps the existing controls", async ({ page }) => {
  await openPage(page);
  await expect(page.locator("#mcp-help")).toBeVisible();
  await expect(page.locator("#editor-shell")).toBeVisible();
  await expect(page.locator("#network-scope")).toHaveText("비공개 접속");
});
