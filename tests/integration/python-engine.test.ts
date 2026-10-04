import { copyFile, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { PythonEngine } from "../../src/engine/python-engine.js";
import { SpawnCommandRunner } from "../../src/process/command-runner.js";
import { makeTestRoot, removeTestRoot } from "../helpers/test-root.js";
import { pythonCommand } from "../helpers/python-command.js";

const engine = new PythonEngine({
  pythonCommand,
  vendorRoot: path.resolve("vendor/humanize-engine"),
  runner: new SpawnCommandRunner()
});

describe("PythonEngine integration", () => {
  it("prepares, verifies, and losslessly reassembles a short document", async () => {
    const runDir = await makeTestRoot();
    try {
      await copyFile(
        path.resolve("tests/fixtures/short-korean.txt"),
        path.join(runDir, "01_input.txt")
      );
      const signal = new AbortController().signal;
      const manifest = await engine.prepare(runDir, signal);
      const source = await readFile(path.join(runDir, manifest.sourceFile), "utf8");

      for (const chunk of manifest.chunks.filter(item => !item.passthrough)) {
        await writeFile(
          path.join(runDir, chunk.rewrittenFile!),
          source.slice(chunk.start, chunk.end),
          "utf8"
        );
      }

      const outputPath = await engine.reassemble(runDir, signal);
      expect(await readFile(outputPath, "utf8")).toBe(source);
      const gate = await engine.verify(
        path.join(runDir, manifest.sourceFile),
        outputPath,
        signal
      );
      expect(gate.status).toBe("ok");
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it("restores a hedge the rewrite turned into an assertion", async () => {
    const runDir = await makeTestRoot();
    try {
      const before =
        "이 수치는 낮은 것으로 판단된다. 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.\n";
      const after =
        "이 수치는 낮은 수치다. 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.\n";
      const beforePath = path.join(runDir, "before.txt");
      const afterPath = path.join(runDir, "after.txt");
      await writeFile(beforePath, before, "utf8");
      await writeFile(afterPath, after, "utf8");

      const report = await engine.restore(
        beforePath,
        afterPath,
        new AbortController().signal
      );

      expect(report).toMatchObject({ restoredSentences: 1, removedCommas: 0 });
      expect(await readFile(afterPath, "utf8")).toBe(before);
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it("keeps CRLF line endings through the restore step", async () => {
    const runDir = await makeTestRoot();
    try {
      const text =
        "첫 문단이다.\r\n\r\n둘째 문단은 그대로 둔다.\r\n";
      const beforePath = path.join(runDir, "before.txt");
      const afterPath = path.join(runDir, "after.txt");
      await writeFile(beforePath, text, "utf8");
      await writeFile(afterPath, text, "utf8");

      const report = await engine.restore(
        beforePath,
        afterPath,
        new AbortController().signal
      );

      expect(report).toEqual({
        restoredSentences: 0,
        skippedSentences: 0,
        removedCommas: 0,
        repairedParticles: 0
      });
      expect(await readFile(afterPath, "utf8")).toBe(text);
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it("creates multiple body chunks for a document over 15,000 characters", async () => {
    const runDir = await makeTestRoot();
    try {
      const paragraph =
        "이 문단은 장문 자동 분할을 검증한다. 수치 1,200과 OpenAI는 그대로 유지한다. 문장 경계에서 안전하게 나뉘어야 한다.\n\n";
      const source = `# 장문 테스트\n\n${paragraph.repeat(230)}`;
      expect(source.length).toBeGreaterThan(15_000);
      await writeFile(path.join(runDir, "01_input.txt"), source, "utf8");

      const manifest = await engine.prepare(
        runDir,
        new AbortController().signal
      );

      expect(manifest.bodyChunkCount).toBeGreaterThanOrEqual(2);
      expect(manifest.chunks.map(chunk => [chunk.start, chunk.end])).toEqual(
        expect.arrayContaining([[0, manifest.chunks[0]!.end]])
      );
      const sanitized = await readFile(path.join(runDir, "01_input.txt"), "utf8");
      expect(
        manifest.chunks.map(chunk => sanitized.slice(chunk.start, chunk.end)).join("")
      ).toBe(sanitized);
    } finally {
      await removeTestRoot(runDir);
    }
  });
});

it('accepts the recorded P1-only warning as advisory through the real Python adapter',async()=>{
 const {default:fixture}=await import('../fixtures/direct-live-quality.json');
 const runDir=await makeTestRoot();
 try{
  const before=path.join(runDir,'before.txt'),after=path.join(runDir,'after.txt');
  await writeFile(before,fixture.source);await writeFile(after,fixture.candidate);
  // P1 alone no longer forces a retry: its baselines are placeholders and it warns on most unchanged text.
  expect(await engine.verify(before,after,new AbortController().signal)).toMatchObject({status:'ok',exitCode:0,policy:'accept',hardFailures:[],warningReasons:{version:1,codes:[]}});
 }finally{await removeTestRoot(runDir);}
});
