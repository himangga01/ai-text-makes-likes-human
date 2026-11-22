import { copyFile, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { checkDirectTextFidelity } from "../../src/engine/direct-text-fidelity.js";
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
        repairedParticles: 0,
        restoredLexicalSentences: 0,
        skippedLexicalSentences: 0,
        lexicalRestoreFailures: 0
      });
      expect(await readFile(afterPath, "utf8")).toBe(text);
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it("puts a sentence with an injected lexicon headword back to the source, keeping CRLF", async () => {
    const runDir = await makeTestRoot();
    try {
      const before = "올해 매출은 크게 늘었다.\r\n이 결과를 여러 관점에서 살펴본다.\r\n";
      const beforePath = path.join(runDir, "before.txt");
      const afterPath = path.join(runDir, "after.txt");
      await writeFile(beforePath, before, "utf8");
      await writeFile(afterPath, before.replace("관점에서", "렌즈로"), "utf8");

      const report = await engine.restore(beforePath, afterPath, new AbortController().signal);

      expect(report).toMatchObject({ restoredSentences: 0, restoredLexicalSentences: 1, skippedLexicalSentences: 0, lexicalRestoreFailures: 0 });
      expect(await readFile(afterPath, "utf8")).toBe(before);
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it("returns the lexical check block and replaceable nouns only for a source that uses a lexicon headword", async () => {
    const runDir = await makeTestRoot();
    try {
      const sourcePath = path.join(runDir, "chunk-1-source.txt");
      await writeFile(sourcePath, "이 문제를 세 가지 렌즈로 본다.\r\n", "utf8");
      const found = await engine.lexicalHints(sourcePath, new AbortController().signal);
      expect(found.failed).toBe(false);
      expect(found.hints.startsWith("[어휘 점검]\n")).toBe(true);
      expect(found.hints.endsWith("\n[어휘 점검 끝]")).toBe(true);
      expect(found.hints).toContain("[우선] 렌즈");
      expect(found.replaceableNouns).toContain("렌즈");

      await writeFile(sourcePath, "오늘은 비가 왔다.\n", "utf8");
      expect(await engine.lexicalHints(sourcePath, new AbortController().signal)).toEqual({ hints: "", replaceableNouns: [], failed: false });
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it("names 렌즈 as replaceable so the direct-text concept guard accepts 관점 in its place", async () => {
    const runDir = await makeTestRoot();
    try {
      const sourcePath = path.join(runDir, "chunk-1-source.txt");
      const source = "이번 분기 실적을 세 가지 렌즈로 살펴보면 흐름이 달라 보인다.\n";
      const rewrite = "이번 분기 실적을 세 가지 관점에서 살펴보면 흐름이 달라 보인다.\n";
      await writeFile(sourcePath, source, "utf8");
      const found = await engine.lexicalHints(sourcePath, new AbortController().signal);

      expect(found.failed).toBe(false);
      expect(found.hints).toContain("[우선] 렌즈");
      expect(found.replaceableNouns).toContain("렌즈");
      // The real Python result feeds the real guard: it rejects the swap without the noun and accepts it with.
      expect(checkDirectTextFidelity(source, rewrite).violations).toBeGreaterThan(0);
      expect(checkDirectTextFidelity(source, rewrite, found.replaceableNouns).violations).toBe(0);
      // Only that noun: dropping 실적 stays a violation.
      expect(checkDirectTextFidelity(source, rewrite.replace("실적을 ", ""), found.replaceableNouns).violations).toBeGreaterThan(0);
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it("flags neither a longer word containing 렌즈 nor a quoted mention", async () => {
    const runDir = await makeTestRoot();
    try {
      const sourcePath = path.join(runDir, "chunk-1-source.txt");
      for (const text of ["콘택트렌즈를 끼고 안경을 벗었다.\n", "그는 \"세 가지 렌즈\"라고 말했다.\n"]) {
        await writeFile(sourcePath, text, "utf8");
        expect(await engine.lexicalHints(sourcePath, new AbortController().signal)).toEqual({ hints: "", replaceableNouns: [], failed: false });
      }
    } finally {
      await removeTestRoot(runDir);
    }
  });

  it("reports a lexical check that cannot run as failed, with no block and no nouns", async () => {
    const runDir = await makeTestRoot();
    try {
      const failed = { hints: "", replaceableNouns: [], failed: true };
      const signal = new AbortController().signal;
      // The source file is missing: the script exits 1.
      expect(await engine.lexicalHints(path.join(runDir, "missing-source.txt"), signal)).toEqual(failed);

      // The vendor tree has no lexical layer: still exit 1, while the script itself (engine_runtime/) is found.
      const sourcePath = path.join(runDir, "chunk-1-source.txt");
      await writeFile(sourcePath, "이 문제를 세 가지 렌즈로 본다.\n", "utf8");
      const withoutLayer = new PythonEngine({
        pythonCommand,
        vendorRoot: path.resolve("vendor/no-such-engine"),
        runner: new SpawnCommandRunner()
      });
      expect(await withoutLayer.lexicalHints(sourcePath, signal)).toEqual(failed);
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
