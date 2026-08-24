import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { SpawnCommandRunner } from "../../src/process/command-runner.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";

const runner = new SpawnCommandRunner();
const script = path.resolve(
  "vendor/humanize-engine/scripts/prepare_monolith_input.py"
);

async function runPortalRoute(runDir: string) {
  return runner.run({
    command: "python",
    args: [
      script,
      "--chunk",
      "--portal-auto-route",
      "--run-dir",
      runDir,
      "--genre",
      "essay"
    ],
    cwd: runDir,
    timeoutMs: 120_000,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1" }
  });
}

describe("portal route manifest", () => {
  it("uses one body span for a short light or standard Markdown document", async () => {
    const runDir = await makeTestRoot("portal-route-short-");
    try {
      const shortMarkdown = Array.from({ length: 8 }, (_, index) =>
        `## 제목 ${index + 1}\n\n사람이 작성한 자연스러운 설명 문단입니다. ` +
        `OpenAI 기준값 ${index + 1}과 2026년 기록을 그대로 보존합니다.\n\n`
      ).join("");
      await writeFile(path.join(runDir, "01_input.txt"), shortMarkdown, "utf8");

      const result = await runner.run({
        command: "python",
        args: [
          script,
          "--chunk",
          "--portal-auto-route",
          "--run-dir",
          runDir,
          "--genre",
          "essay"
        ],
        cwd: runDir,
        timeoutMs: 120_000,
        env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1" }
      });

      expect(result.exitCode).toBe(0);
      const manifest = JSON.parse(
        await readFile(path.join(runDir, "chunk_manifest.json"), "utf8")
      );
      expect(manifest.processing_mode).toBe("single");
      expect(manifest.route_hint).toMatch(/^(light|standard)$/u);
      expect(manifest.body_chunk_count).toBe(1);
      expect(
        manifest.chunks.filter((item: { passthrough: boolean }) => !item.passthrough)
      ).toHaveLength(1);
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it("keeps a document over 15,000 characters on the chunked route", async () => {
    const runDir = await makeTestRoot("portal-route-long-");
    try {
      const paragraph =
        "연구개발 기록과 검증 근거를 문단별로 보존하고 실제 업무 흐름을 설명합니다. ";
      const source = `# 장문 문서\n\n${`${paragraph}\n\n`.repeat(380)}`;
      expect(source.length).toBeGreaterThan(15_000);
      await writeFile(path.join(runDir, "01_input.txt"), source, "utf8");

      const result = await runPortalRoute(runDir);

      expect(result.exitCode).toBe(0);
      const manifest = JSON.parse(
        await readFile(path.join(runDir, "chunk_manifest.json"), "utf8")
      );
      expect(manifest.processing_mode).toBe("chunked");
      expect(manifest.body_chunk_count).toBeGreaterThan(1);
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it("keeps trailing footnotes as one passthrough span without source loss", async () => {
    const runDir = await makeTestRoot("portal-route-footnote-");
    try {
      const source =
        "# 본문\n\n사람이 작성한 자연스러운 설명 문단입니다.\n\n" +
        "[1] 각주는 그대로 둔다.";
      await writeFile(path.join(runDir, "01_input.txt"), source, "utf8");

      const result = await runPortalRoute(runDir);

      expect(result.exitCode).toBe(0);
      const manifest = JSON.parse(
        await readFile(path.join(runDir, "chunk_manifest.json"), "utf8")
      );
      expect(manifest.processing_mode).toBe("single");
      expect(manifest.chunks).toHaveLength(2);
      expect(manifest.chunks.map((item: { passthrough: boolean }) => item.passthrough)).toEqual([
        false,
        true
      ]);
      expect(
        manifest.chunks
          .map((item: { start: number; end: number }) =>
            source.slice(item.start, item.end)
          )
          .join("")
      ).toBe(source);
    } finally {
      await removeTestRoot(runDir);
    }
  });
});
