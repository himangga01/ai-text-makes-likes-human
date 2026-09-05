import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:7882",
    trace: "retain-on-failure",
    screenshot: "only-on-failure"
  },
  webServer: {
    command: "npm.cmd run build && npm.cmd start",
    url: "http://127.0.0.1:7882/api/health",
    env: { HOST: "127.0.0.1", PORT: "7882" },
    reuseExistingServer: false,
    timeout: 30_000
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } }
  ]
});
