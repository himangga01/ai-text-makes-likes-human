import { defineConfig, devices } from "@playwright/test";

// The managed service owns 7882 on an operator machine; E2E_PORT runs the suite beside it.
const port = process.env.E2E_PORT ?? "7882";
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure"
  },
  webServer: {
    // npm.cmd exists only on Windows; macOS and Linux use the npm shell script.
    command: process.platform === "win32" ? "npm.cmd run build && npm.cmd start" : "npm run build && npm start",
    url: `${baseURL}/api/health`,
    env: {
      HOST: "127.0.0.1",
      PORT: port,
      // A separate runtime root keeps the managed service's lock and jobs untouched.
      ...(process.env.E2E_PORT ? { HUMANIZE_RUNTIME_ROOT: "runtime/test-tmp/e2e" } : {})
    },
    reuseExistingServer: false,
    timeout: 30_000
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } }
  ]
});
