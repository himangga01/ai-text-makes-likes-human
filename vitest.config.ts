import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/unit/**/*.{test,spec}.{ts,js}", "tests/integration/**/*.{test,spec}.{ts,js}"],
    restoreMocks: true,
    clearMocks: true
  }
});
