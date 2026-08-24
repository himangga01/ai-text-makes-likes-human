import { describe, expect, it } from "vitest";
import type { TransformDiagnostics } from "../../src/engine/diagnostics.js";
import {
  HUMANIZE_MODEL,
  HUMANIZE_REASONING_EFFORT
} from "../../src/engine/model-policy.js";
import {
  runLiveEngineFixture,
  type LiveEngineOptions,
  type LiveEngineResult
} from "../helpers/live-engine.js";

const live = process.env.RUN_CODEX_LIVE === "1" ? describe : describe.skip;
const RUNS_PER_CONFIGURATION = 3;
const LIVE_TIMEOUT_MS = 4 * 60 * 60 * 1000;

function shortFixture(): string {
  return Array.from(
    { length: 8 },
    (_, index) =>
      `## 성능 검증 ${index + 1}\n\n` +
      (`2026년 OpenAI 기조연설 ${index + 1}을 설명하는 자연스러운 한국어 문단입니다. ` +
        `"직접 인용 ${index + 1}"은 그대로 둡니다. `).repeat(5) +
      "\n\n"
  ).join("");
}

function longFixture(): string {
  const block = shortFixture();
  let result = block;
  while (Array.from(result).length <= 16_000) result += block;
  return result;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)]!;
}

function markdownHeadings(value: string): string[] {
  return value
    .split(/\r?\n/u)
    .filter(line => /^## /u.test(line));
}

function quotedAnchors(value: string): string[] {
  return [...value.matchAll(/"[^"\r\n]+"/gu)].map(match => match[0]);
}

function occurrences(value: string, needle: string): number {
  let count = 0;
  let offset = 0;
  while (true) {
    const found = value.indexOf(needle, offset);
    if (found < 0) return count;
    count += 1;
    offset = found + needle.length;
  }
}

interface QualityResults {
  headingsExact: boolean;
  anchorsExact: boolean;
  fullGatePassed: boolean;
  cleanup: boolean;
  outputNonempty: boolean;
}

interface MeasuredRun {
  result: LiveEngineResult;
  quality: QualityResults;
}

function qualityResults(
  source: string,
  result: LiveEngineResult
): QualityResults {
  const expectedHeadings = markdownHeadings(source);
  const expectedAnchors = [...new Set(quotedAnchors(source))];
  const fullGate = result.diagnostics.gateCodes.at(-1);
  return {
    headingsExact:
      JSON.stringify(markdownHeadings(result.result)) ===
      JSON.stringify(expectedHeadings),
    anchorsExact: expectedAnchors.every(
      anchor => occurrences(result.result, anchor) === occurrences(source, anchor)
    ),
    fullGatePassed: fullGate === "GATE_OK" || fullGate === "GATE_WARN",
    cleanup: result.runtimeChildren.length === 0,
    outputNonempty: result.result.trim().length > 0
  };
}

async function runConfiguration(
  source: string,
  options: LiveEngineOptions
): Promise<MeasuredRun[]> {
  const runs: MeasuredRun[] = [];
  for (let index = 0; index < RUNS_PER_CONFIGURATION; index += 1) {
    const result = await runLiveEngineFixture(source, options);
    runs.push({ result, quality: qualityResults(source, result) });
  }
  return runs;
}

function allQuality(runs: MeasuredRun[]): QualityResults {
  return {
    headingsExact: runs.every(run => run.quality.headingsExact),
    anchorsExact: runs.every(run => run.quality.anchorsExact),
    fullGatePassed: runs.every(run => run.quality.fullGatePassed),
    cleanup: runs.every(run => run.quality.cleanup),
    outputNonempty: runs.every(run => run.quality.outputNonempty)
  };
}

function assertQuality(runs: MeasuredRun[]): void {
  const quality = allQuality(runs);
  expect(quality.headingsExact).toBe(true);
  expect(quality.anchorsExact).toBe(true);
  expect(quality.fullGatePassed).toBe(true);
  expect(quality.cleanup).toBe(true);
  expect(quality.outputNonempty).toBe(true);
  expect(
    runs.every(
      run =>
        run.result.diagnostics.model === HUMANIZE_MODEL &&
        run.result.diagnostics.reasoningEffort === HUMANIZE_REASONING_EFFORT
    )
  ).toBe(true);
}

function report(
  fixtureId:
    | "short-baseline"
    | "short-optimized"
    | "long-serial"
    | "long-parallel",
  source: string,
  runs: MeasuredRun[]
): void {
  const diagnostics = runs.map(run => run.result.diagnostics);
  const first = diagnostics[0]!;
  console.log(
    JSON.stringify({
      fixtureId,
      chars: Array.from(source).length,
      headings: markdownHeadings(source).length,
      model: first.model,
      effort: first.reasoningEffort,
      mode: first.processingMode,
      route: first.routeHint,
      bodyChunks: diagnostics.map(item => item.bodyChunks),
      codexCalls: diagnostics.map(item => item.codexCalls),
      retries: diagnostics.map(item => item.retries),
      gateCounts: diagnostics.map(item => item.gateCodes.length),
      maxObservedConcurrency: diagnostics.map(
        item => item.maxObservedCodexConcurrency
      ),
      timings: diagnostics.map(item => ({
        prepareMs: item.prepareMs,
        codexMs: item.codexMs,
        gateMs: item.gateMs,
        assembleMs: item.assembleMs,
        totalMs: item.totalMs
      })),
      p50Ms: median(diagnostics.map(item => item.totalMs)),
      quality: allQuality(runs)
    })
  );
}

function p50(runs: MeasuredRun[]): number {
  return median(runs.map(run => run.result.diagnostics.totalMs));
}

function diagnostics(runs: MeasuredRun[]): TransformDiagnostics[] {
  return runs.map(run => run.result.diagnostics);
}

live("Codex live performance gate", () => {
  it(
    "routes a short fixture through one Codex unit within forty percent of baseline p50",
    async () => {
      const source = shortFixture();
      const baseline = await runConfiguration(source, {
        autoRoute: false,
        chunkConcurrency: 1
      });
      const optimized = await runConfiguration(source, {
        autoRoute: true,
        chunkConcurrency: 1
      });

      report("short-baseline", source, baseline);
      report("short-optimized", source, optimized);
      assertQuality(baseline);
      assertQuality(optimized);
      expect(diagnostics(optimized).every(item => item.bodyChunks === 1)).toBe(
        true
      );
      expect(
        diagnostics(optimized).every(
          item =>
            item.processingMode === "single" &&
            (item.routeHint === "light" || item.routeHint === "standard")
        )
      ).toBe(true);
      expect(
        diagnostics(optimized).every(
          item => item.codexCalls === 1 || item.codexCalls === 2
        )
      ).toBe(true);
      expect(p50(optimized)).toBeLessThanOrEqual(p50(baseline) * 0.4);
    },
    LIVE_TIMEOUT_MS
  );

  it(
    "processes a long fixture at concurrency two within seventy percent of serial p50",
    async () => {
      const source = longFixture();
      const serial = await runConfiguration(source, {
        autoRoute: true,
        chunkConcurrency: 1
      });
      const parallel = await runConfiguration(source, {
        autoRoute: true,
        chunkConcurrency: 2
      });

      report("long-serial", source, serial);
      report("long-parallel", source, parallel);
      assertQuality(serial);
      assertQuality(parallel);
      expect(
        [...diagnostics(serial), ...diagnostics(parallel)].every(
          item =>
            item.processingMode === "chunked" &&
            item.routeHint === "heavy" &&
            item.bodyChunks > 1
        )
      ).toBe(true);
      expect(
        diagnostics(serial).every(item => item.maxObservedCodexConcurrency <= 1)
      ).toBe(true);
      expect(
        diagnostics(parallel).every(
          item => item.maxObservedCodexConcurrency <= 2
        )
      ).toBe(true);
      expect(p50(parallel)).toBeLessThanOrEqual(p50(serial) * 0.7);
    },
    LIVE_TIMEOUT_MS
  );
});
