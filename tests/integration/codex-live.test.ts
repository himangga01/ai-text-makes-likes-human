import { describe, expect, it } from "vitest";
import { runLiveEngineFixture } from "../helpers/live-engine.js";

const live = process.env.RUN_CODEX_LIVE === "1" ? describe : describe.skip;

live("Codex live humanize", () => {
  it(
    "returns Korean text, preserves protected anchors, and cleans its workspace",
    async () => {
      const source =
        '2026년 OpenAI 행사에는 1,200명이 참여했다. "원문 인용은 그대로 둔다." 이를 통해 의미 있는 성과를 도출할 수 있었다.';

      const { result, runtimeChildren } = await runLiveEngineFixture(source);

      expect(result).toContain("2026년");
      expect(result).toContain("OpenAI");
      expect(result).toMatch(/1,?200명/u);
      expect(result).toContain('"원문 인용은 그대로 둔다."');
      expect(result.trim().length).toBeGreaterThan(0);
      expect(runtimeChildren).toEqual([]);
    },
    15 * 60 * 1000
  );
});
