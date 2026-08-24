import { describe, expect, it } from "vitest";
import type { TransformDiagnostics } from "../../src/engine/diagnostics.js";
import {
  HUMANIZE_MODEL,
  HUMANIZE_REASONING_EFFORT
} from "../../src/engine/model-policy.js";
import {
  isLiveEngineFailure,
  runLiveEngineFixture,
  type LiveEngineFailure,
  type LiveEngineOptions,
  type LiveEngineResult
} from "../helpers/live-engine.js";

const live = process.env.RUN_CODEX_LIVE === "1" ? describe : describe.skip;
const RUNS_PER_CONFIGURATION = 3;
const LIVE_TIMEOUT_MS = 4 * 60 * 60 * 1000;

function shortFixture(): string {
  return Array.from(
    { length: 8 },
    (_, index) => {
      const section = index + 1;
      const paragraphs = Array.from(
        { length: 4 },
        (_, offset) =>
          `2026년 OpenAI 기조연설 ${section}의 준비 기록 ${offset + 1}은 ` +
          `발표 자료와 회의 메모를 대조해 핵심 내용을 확인한 한국어 문단입니다. ` +
          `담당자는 고유 확인 번호 ${section}-${offset + 1}을 남기고 사실과 의견을 구분했습니다.`
      ).join("\n\n");
      return (
        `## 성능 검증 ${section}\n\n` +
        `${paragraphs}\n\n` +
        `담당자는 "직접 인용 ${section}"을 원문 그대로 보존했습니다.\n\n`
      );
    }
  ).join("");
}

function longFixture(): string {
  const themes = [
    "연구 기록",
    "고객 피드백",
    "보안 점검",
    "품질 검증",
    "데이터 정리",
    "배포 계획"
  ] as const;
  const evidence = ["회의록", "실험표", "검토표", "변경 이력"] as const;
  const actions = ["확인", "분류", "대조", "보완"] as const;

  return Array.from({ length: 24 }, (_, index) => {
    const section = index + 1;
    const serial = String(section).padStart(2, "0");
    const theme = themes[index % themes.length]!;
    const paragraphs = Array.from({ length: 4 }, (_, offset) => {
      const step = offset + 1;
      const item = evidence[(index + offset) % evidence.length]!;
      const action = actions[(index * 2 + offset) % actions.length]!;
      return (
        `${serial}번째 ${theme} 검토의 ${step}단계에서는 ${item}을 기준으로 자료를 대조했습니다. ` +
        `담당자는 ${action} 항목을 별도로 표시하고 2026년 OpenAI 관련 고유 식별자 ` +
        `${serial}-${step}의 사실관계를 기록했습니다. 이 기록은 다음 단계에서 누락 여부를 ` +
        `확인하는 근거로 사용되며 다른 섹션의 자료와 섞이지 않습니다.`
      );
    }).join("\n\n");
    return (
      `## ${serial}. ${theme} 성능 검증\n\n` +
      `${paragraphs}\n\n` +
      `검토 책임자는 "장문 검증 인용 ${serial}"을 원문 그대로 유지했습니다.\n\n`
    );
  }).join("");
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

type FixtureId =
  | "short-baseline"
  | "short-optimized"
  | "long-serial"
  | "long-parallel";

function failConfiguration(
  fixtureId: FixtureId,
  error: unknown,
  write: (line: string) => void = line => console.log(line)
): never {
  const failure: LiveEngineFailure = isLiveEngineFailure(error)
    ? error
    : {
        publicCode: "INTERNAL_ERROR",
        gateCodes: [],
        elapsedMs: 0,
        cleanup: false
      };
  const metadata = { fixtureId, ...failure };
  write(JSON.stringify(metadata));
  expect(failure.cleanup).toBe(true);
  expect.fail(`Live configuration failed: ${JSON.stringify(metadata)}`);
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
  fixtureId: FixtureId,
  source: string,
  options: LiveEngineOptions
): Promise<MeasuredRun[]> {
  const runs: MeasuredRun[] = [];
  try {
    for (let index = 0; index < RUNS_PER_CONFIGURATION; index += 1) {
      const result = await runLiveEngineFixture(source, options);
      runs.push({ result, quality: qualityResults(source, result) });
    }
  } catch (error) {
    failConfiguration(fixtureId, error);
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
  fixtureId: FixtureId,
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
      const baseline = await runConfiguration("short-baseline", source, {
        autoRoute: false,
        chunkConcurrency: 1
      });
      const optimized = await runConfiguration("short-optimized", source, {
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
      const serial = await runConfiguration("long-serial", source, {
        autoRoute: true,
        chunkConcurrency: 1
      });
      const parallel = await runConfiguration("long-parallel", source, {
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

describe("performance fixture contracts", () => {
  it("keeps the short fixture between three and five thousand code points with eight headings", () => {
    const source = shortFixture();
    const chars = Array.from(source).length;

    expect(chars).toBeGreaterThanOrEqual(3_000);
    expect(chars).toBeLessThanOrEqual(5_000);
    expect(markdownHeadings(source)).toHaveLength(8);
  });

  it("builds a long fixture in range with twenty-four unique headings", () => {
    const source = longFixture();
    const chars = Array.from(source).length;
    const headings = markdownHeadings(source);

    expect(chars).toBeGreaterThanOrEqual(16_000);
    expect(chars).toBeLessThanOrEqual(20_000);
    expect(headings).toHaveLength(24);
    expect(new Set(headings).size).toBe(headings.length);
  });

  it("emits only allowlisted failure metadata before failing", () => {
    const reports: string[] = [];
    const failure: LiveEngineFailure = {
      publicCode: "VALIDATION_FAILED",
      gateCodes: ["GATE_OK", "GATE_ABORT"],
      elapsedMs: 123,
      cleanup: true
    };

    expect(() =>
      failConfiguration(
        "long-serial",
        failure,
        (line: string) => reports.push(line)
      )
    ).toThrow();
    expect(reports).toHaveLength(1);
    expect(JSON.parse(reports[0]!)).toEqual({
      fixtureId: "long-serial",
      publicCode: "VALIDATION_FAILED",
      gateCodes: ["GATE_OK", "GATE_ABORT"],
      elapsedMs: 123,
      cleanup: true
    });
  });
});
