import { defineConfig } from "@playwright/test";
export default defineConfig({ testDir: "tests/desktop", timeout: 60_000, workers: 1, fullyParallel: false,
  expect: { timeout: 15_000 }, outputDir: "test-results/desktop", reporter: "list" });
