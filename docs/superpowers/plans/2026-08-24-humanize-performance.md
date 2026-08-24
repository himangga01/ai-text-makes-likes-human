# Humanize Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every transformation on `gpt-5.6-sol` with reasoning effort `high` while routing short `light/standard` documents through one Codex call and processing genuinely chunked documents with a globally bounded concurrency of two.

**Architecture:** The vendored Python prepare step remains the lossless source of the chunk manifest, but an opt-in portal patch collapses eligible documents to one body span while retaining trailing passthrough content. TypeScript validates the route, processes chunks through a deterministic worker pool guarded by a global Codex semaphore, emits aggregate monotonic progress, and records metadata-only diagnostics. Existing gates, retry/rollback behavior, HTTP contracts, queue capacity, and cleanup paths remain authoritative.

**Tech Stack:** Node.js 24.19+, TypeScript 7 ESM, Express 5, Python 3.11+, Codex CLI 0.149+, Vitest 4, Playwright 1.62, PowerShell 5+ on Windows.

**Spec:** `docs/superpowers/specs/2026-08-24-humanize-performance-design.md`

## Global Constraints

- Every Codex invocation MUST pass `--model gpt-5.6-sol` and `--config model_reasoning_effort="high"`.
- Keep `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `--sandbox read-only`, schema output, and the 10-minute per-call timeout.
- `sourceChars <= 15000` routes to one body span only when `routeHint` is `light` or `standard`; `heavy`, over-limit, missing, and invalid routes stay chunked.
- Preserve the existing first `warn|abort` retry, second `abort` rollback, gate `error` failure, and full-document abort/error rejection semantics.
- Keep `TransformQueue` at one active job and three accepted jobs. Never run more than two Codex subprocesses globally.
- Never log source text, result text, prompts, filenames, Codex response bodies, or raw gate stdout/stderr.
- Keep `POST /api/transform` as `text/plain` with NDJSON output; do not add model selection or a new API surface.
- Preserve TXT/MD upload, MD download, copy, cancellation, visual snapshots, and WCAG tests already present in the working tree.
- The current workspace contains approved but uncommitted MD/progress/model work. Before creating a worktree, preserve that exact diff in a user-approved baseline commit or transfer it intact; never execute this plan from `HEAD` alone and silently lose those changes.
- Use TDD for every behavior change: add the focused test, observe the expected failure, implement only enough to pass, rerun the focused and affected suites, then commit.

## File Map

```text
src/engine/model-policy.ts               fixed model and reasoning constants
src/config.ts                            autoRoute and chunkConcurrency runtime settings
src/engine/diagnostics.ts                route, gate, timing, and diagnostic types
src/engine/python-engine.ts              manifest validation, portal flag, gate JSON parsing
vendor/humanize-engine/scripts/
  prepare_monolith_input.py              single-vs-chunked manifest generation
scripts/patches/
  humanize-engine-portal.patch           replayable newline and route patch
scripts/sync-engine.ps1                  patch check/apply after pinned upstream copy
src/engine/codex-semaphore.ts            global Codex subprocess permits
src/engine/chunk-pool.ts                 bounded worker pool and sibling cancellation
src/engine/humanize-engine.ts            per-chunk worker, diagnostics, pool integration
src/contracts.ts                         aggregate progress fields
public/progress.js                       aggregate progress mapping with legacy fallback
src/app.ts                               dependency wiring and metadata-only logs
tests/unit/*                             focused contract and concurrency tests
tests/integration/*                      real Python routing/reassembly and fake-Codex flows
tests/helpers/live-engine.ts             configurable live engine runner
tests/integration/performance-live.test.ts opt-in short/long benchmark gate
README.md, docs/operations.md             model, routing, rollback, benchmark runbook
```

---

### Task 1: Freeze the Model Policy and Add Safe Runtime Switches

**Files:**
- Create: `src/engine/model-policy.ts`
- Modify: `src/engine/codex-runner.ts`
- Modify: `src/config.ts`
- Test: `tests/unit/codex-runner.test.ts`
- Test: `tests/unit/config.test.ts`

**Interfaces:**
- Produces: `HUMANIZE_MODEL`, `HUMANIZE_REASONING_EFFORT`, `AppConfig.autoRoute`, and `AppConfig.chunkConcurrency`.
- Consumed later by: `CodexRunner`, `createProductionRuntime`, diagnostics, Python routing, and the live benchmark.

- [ ] **Step 1: Preserve the approved working-tree baseline**

Run the existing verification before moving or committing anything:

```powershell
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
git status --short
```

Expected: typecheck/build exit 0, Vitest reports `94 passed | 1 skipped`, Playwright reports `16 passed`, and the status contains the approved MD/progress/model files. If counts changed because new tests were added after this plan, require zero failures rather than restoring old counts.

- [ ] **Step 2: Write failing config and model-policy tests**

Add these behaviors to `tests/unit/config.test.ts`:

```ts
it("starts conservatively with auto-route enabled and serial chunk execution", () => {
  const config = loadConfig({}, process.cwd());
  expect(config.autoRoute).toBe(true);
  expect(config.chunkConcurrency).toBe(1);
});

it.each(["0", "3", "1.5", "fast"])(
  "rejects invalid CODEX_CHUNK_CONCURRENCY=%s",
  value => {
    expect(() =>
      loadConfig({ CODEX_CHUNK_CONCURRENCY: value }, process.cwd())
    ).toThrow("CODEX_CHUNK_CONCURRENCY must be 1 or 2");
  }
);

it("allows the benchmark to select concurrency two", () => {
  expect(
    loadConfig({ CODEX_CHUNK_CONCURRENCY: "2" }, process.cwd())
      .chunkConcurrency
  ).toBe(2);
});
```

Update `tests/unit/codex-runner.test.ts` to import and assert literal policy values:

```ts
import {
  HUMANIZE_MODEL,
  HUMANIZE_REASONING_EFFORT
} from "../../src/engine/model-policy.js";

expect(HUMANIZE_MODEL).toBe("gpt-5.6-sol");
expect(HUMANIZE_REASONING_EFFORT).toBe("high");
```

- [ ] **Step 3: Run the tests and verify RED**

Run:

```powershell
npm.cmd test -- tests/unit/config.test.ts tests/unit/codex-runner.test.ts
```

Expected: FAIL because `model-policy.ts`, `autoRoute`, and `chunkConcurrency` do not exist. The existing exact Codex argument assertion may already pass because the approved model pin is in the working tree; the new policy import and config assertions must fail.

- [ ] **Step 4: Implement the fixed policy and conservative config**

Create `src/engine/model-policy.ts`:

```ts
export const HUMANIZE_MODEL = "gpt-5.6-sol" as const;
export const HUMANIZE_REASONING_EFFORT = "high" as const;
```

Use those constants in `CodexRunner`:

```ts
import {
  HUMANIZE_MODEL,
  HUMANIZE_REASONING_EFFORT
} from "./model-policy.js";

// inside args
"--model",
HUMANIZE_MODEL,
"--config",
`model_reasoning_effort="${HUMANIZE_REASONING_EFFORT}"`,
```

Extend `AppConfig` and `loadConfig`:

```ts
readonly autoRoute: boolean;
readonly chunkConcurrency: 1 | 2;

const concurrency = Number(env.CODEX_CHUNK_CONCURRENCY ?? 1);
if (concurrency !== 1 && concurrency !== 2) {
  throw new Error("CODEX_CHUNK_CONCURRENCY must be 1 or 2");
}

autoRoute: env.HUMANIZE_AUTO_ROUTE !== "0",
chunkConcurrency: concurrency,
```

`HUMANIZE_AUTO_ROUTE=0` is a benchmark-only rollback switch; any value other than exact `"0"` keeps routing enabled.

- [ ] **Step 5: Run focused and global tests**

Run:

```powershell
npm.cmd test -- tests/unit/config.test.ts tests/unit/codex-runner.test.ts
npm.cmd run typecheck
```

Expected: all focused tests and typecheck pass.

- [ ] **Step 6: Commit**

```powershell
git add src/engine/model-policy.ts src/engine/codex-runner.ts src/config.ts tests/unit/codex-runner.test.ts tests/unit/config.test.ts
git commit -m "feat: pin humanize model and add performance switches"
```

---

### Task 2: Make the Vendored Prepare Step Produce a Single-Body Manifest

**Files:**
- Create: `scripts/patches/humanize-engine-portal.patch`
- Modify: `vendor/humanize-engine/scripts/prepare_monolith_input.py`
- Modify: `scripts/sync-engine.ps1`
- Modify: `vendor/humanize-engine/UPSTREAM.md`
- Create: `tests/integration/portal-route.test.ts`
- Test: `tests/integration/python-engine.test.ts`

**Interfaces:**
- Consumes: existing `compute_route_hint`, `find_footnote_block_start`, `compute_chunk_spans`, and the pinned upstream commit.
- Produces: manifest fields `route_hint`, `route_reason`, `processing_mode`, plus a `--portal-auto-route` CLI flag whose absence preserves upstream behavior.

- [ ] **Step 1: Write a direct Python routing integration test**

Create `tests/integration/portal-route.test.ts`. Use `makeTestRoot`, `SpawnCommandRunner`, and `writeFile` to invoke the real script. The core assertions must be literal:

```ts
const shortMarkdown = Array.from({ length: 8 }, (_, index) =>
  `## 제목 ${index + 1}\n\n사람이 작성한 자연스러운 설명 문단입니다. ` +
  `OpenAI 기준값 ${index + 1}과 2026년 기록을 그대로 보존합니다.\n\n`
).join("");

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
expect(manifest.chunks.filter((item: { passthrough: boolean }) => !item.passthrough)).toHaveLength(1);
```

Add a second case whose generated input is longer than 15,000 characters and assert `processing_mode === "chunked"` with `body_chunk_count > 1`.

Add a third case ending in `[1] 각주는 그대로 둔다.` and assert one body span followed by one `passthrough: true` span; joining every `[start,end)` source slice must equal the input byte-for-byte.

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
npm.cmd test -- tests/integration/portal-route.test.ts
```

Expected: FAIL because `--portal-auto-route` is unrecognized and `processing_mode` is absent.

- [ ] **Step 3: Add the opt-in Python route selector**

In `prepare_monolith_input.py`, add this helper next to `compute_chunk_spans`:

```py
def compute_portal_spans(
    text: str,
    route: dict | None,
) -> tuple[list[dict], list[str], str]:
    hint = route.get("route_hint") if route else None
    if len(text) <= CHUNK_RECOMMEND_MIN_CHARS and hint in {"light", "standard"}:
        footnote_start = find_footnote_block_start(text)
        body_end = footnote_start if footnote_start is not None else len(text)
        spans: list[dict] = []
        if body_end > 0:
            spans.append({"start": 0, "end": body_end, "passthrough": False})
        if footnote_start is not None:
            spans.append({
                "start": footnote_start,
                "end": len(text),
                "passthrough": True,
            })
        joined = "".join(text[item["start"]:item["end"]] for item in spans)
        if joined != text:
            raise ChunkingError("portal single-route lossless self-check failed")
        return spans, [], "single"

    spans, warnings = compute_chunk_spans(text)
    return spans, warnings, "chunked"
```

Move full-document metrics and `compute_route_hint` before span selection. Keep ordinary `--chunk` behavior unchanged:

```py
if args.portal_auto_route:
    spans, warnings, processing_mode = compute_portal_spans(text, route)
else:
    spans, warnings = compute_chunk_spans(text)
    processing_mode = "chunked"
```

Add the CLI option:

```py
p.add_argument(
    "--portal-auto-route",
    action="store_true",
    help="포털 전용: route_hint light/standard 15,000자 이하를 single manifest로 생성",
)
```

Add `"processing_mode": processing_mode` beside existing manifest route fields. Suppress the old “--chunk 비권장” warning only when `processing_mode == "single"`; retain it for ordinary upstream `--chunk` calls.

- [ ] **Step 4: Convert portal modifications into one replayable patch**

Create `scripts/patches/humanize-engine-portal.patch` as a unified diff against pinned upstream commit `c4d03d4859acda143f0b04b4bbdb56c5e6a94db1`. It must contain exactly these portal-owned behaviors:

```text
prepare_monolith_input.py:
  input_path.write_text(..., newline="")
  compute_portal_spans(...)
  --portal-auto-route
  processing_mode manifest field
  route calculation before span selection

reassemble_chunks.py:
  output_path.write_text(..., newline="")
```

Do not include generated files, version metadata, quick rules, or unrelated upstream formatting in the patch. Verify that the current vendor files contain exactly the patch by checking the reverse application from the repository root:

```powershell
git apply --reverse --check --whitespace=nowarn scripts/patches/humanize-engine-portal.patch
```

The reverse check must exit 0. The forward check belongs in `sync-engine.ps1` immediately after it copies clean pinned upstream files; do not reverse or discard working-tree changes merely to test the patch.

- [ ] **Step 5: Make sync-engine replay the patch and fail closed**

Replace the two ad-hoc `.Replace()` operations in `scripts/sync-engine.ps1` with this flow:

```powershell
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$patchPath = Join-Path $PSScriptRoot 'patches\humanize-engine-portal.patch'

& git -C $repoRoot apply --check --whitespace=nowarn -- $patchPath
if ($LASTEXITCODE -ne 0) {
  throw 'Portal humanize patch no longer applies to the pinned upstream files.'
}
& git -C $repoRoot apply --whitespace=nowarn -- $patchPath
if ($LASTEXITCODE -ne 0) {
  throw 'Failed to apply portal humanize patch.'
}
```

Keep `ENGINE_VERSION` writing. Update `UPSTREAM.md` so it names `scripts/patches/humanize-engine-portal.patch`, newline preservation, and auto-route explicitly.

- [ ] **Step 6: Run focused integration checks**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync-engine.ps1
npm.cmd test -- tests/integration/portal-route.test.ts tests/integration/python-engine.test.ts tests/unit/vendor-engine.test.ts
$env:PYTHONDONTWRITEBYTECODE='1'
python .\vendor\humanize-engine\scripts\build_quick_rules.py --check
python .\vendor\humanize-engine\scripts\build_diagnosis_rules.py --check
```

Expected: routing, reassembly, vendor pin, and generated reference checks pass.

- [ ] **Step 7: Commit**

```powershell
git add scripts/patches/humanize-engine-portal.patch scripts/sync-engine.ps1 vendor/humanize-engine/scripts/prepare_monolith_input.py vendor/humanize-engine/scripts/reassemble_chunks.py vendor/humanize-engine/UPSTREAM.md tests/integration/portal-route.test.ts tests/integration/python-engine.test.ts
git commit -m "perf: add route-aware single document manifests"
```

---

### Task 3: Validate Route Metadata and Parse Safe Gate Codes

**Files:**
- Create: `src/engine/diagnostics.ts`
- Modify: `src/engine/python-engine.ts`
- Test: `tests/unit/python-engine.test.ts`

**Interfaces:**
- Produces: `RouteHint`, `ProcessingMode`, `GateCode`, extended `ChunkManifest`, and extended `GateResult`.
- Consumed later by: `HumanizeEngine`, metadata-only logs, progress routing, and live benchmark reports.

- [ ] **Step 1: Write failing manifest and gate parser tests**

Extend the manifest fixture in `tests/unit/python-engine.test.ts`:

```ts
route_hint: "standard",
route_reason: "카운트형 티 3건 · risk_band medium — 단일 윤문 권장",
processing_mode: "single",
```

Assert:

```ts
expect(manifest.routeHint).toBe("standard");
expect(manifest.routeReason).toContain("단일 윤문 권장");
expect(manifest.processingMode).toBe("single");
```

Add invalid table cases for `route_hint: "fast"` and `processing_mode: "parallel"`; both must reject with public code `ENGINE_OUTPUT_INVALID`.

Change the gate fake output to include real mixed stdout plus JSON:

```ts
const gateStdout = `[P3 golden] PASS\n${JSON.stringify({
  golden: [],
  gate: { verdict: "WARN", exit_code: 1 }
}, null, 2)}\n`;

expect(result.gateCodes).toEqual(["GATE_WARN"]);
```

Add malformed and exit-code-mismatch cases; they must reject with `ENGINE_OUTPUT_INVALID` and must never return raw stdout as a diagnostic code.

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
npm.cmd test -- tests/unit/python-engine.test.ts
```

Expected: FAIL because route fields and `gateCodes` are missing.

- [ ] **Step 3: Create shared diagnostic enums**

Create `src/engine/diagnostics.ts`:

```ts
import {
  HUMANIZE_MODEL,
  HUMANIZE_REASONING_EFFORT
} from "./model-policy.js";

export type RouteHint = "light" | "standard" | "heavy";
export type ProcessingMode = "single" | "chunked";
export type GateCode =
  | "GATE_OK"
  | "GATE_WARN"
  | "GATE_ABORT"
  | "GATE_ERROR";

export interface ChunkTiming {
  codexMs: number;
  gateMs: number;
}

export interface TransformDiagnostics {
  model: typeof HUMANIZE_MODEL;
  reasoningEffort: typeof HUMANIZE_REASONING_EFFORT;
  processingMode: ProcessingMode;
  routeHint: RouteHint | null;
  sourceChars: number;
  bodyChunks: number;
  codexCalls: number;
  retries: number;
  gateCodes: GateCode[];
  maxObservedCodexConcurrency: number;
  prepareMs: number;
  codexMs: number;
  gateMs: number;
  assembleMs: number;
  totalMs: number;
}
```

- [ ] **Step 4: Validate manifest enums and the final JSON report**

Extend `ChunkManifest`:

```ts
routeHint: RouteHint | null;
routeReason: string | null;
processingMode: ProcessingMode;
```

Use exact enum validators; route failure from the Python script is represented by `null`, while a missing `processing_mode` is invalid after Task 2.

Parse the last line-starting JSON object from gate stdout, validate `gate.exit_code` equals the actual process exit code, and map only the exit code:

```ts
function parseGateReport(stdout: string): Record<string, unknown> {
  const starts = [...stdout.matchAll(/^\{/gmu)].map(match => match.index!);
  for (const start of starts.reverse()) {
    try {
      const value: unknown = JSON.parse(stdout.slice(start).trim());
      return record(value, "gate report");
    } catch {
      // Continue to an earlier line-starting object.
    }
  }
  throw invalid("Unable to parse gate JSON report");
}

const GATE_CODES = [
  "GATE_OK",
  "GATE_WARN",
  "GATE_ABORT",
  "GATE_ERROR"
] as const;

const report = parseGateReport(result.stdout);
const gate = record(report.gate, "gate report.gate");
if (integer(gate.exit_code, "gate report.gate.exit_code") !== exitCode) {
  throw invalid("Gate report exit code mismatch");
}

return {
  status: statuses[exitCode],
  exitCode,
  gateCodes: [GATE_CODES[exitCode]]
};
```

Do not retain `stdout` in `GateResult`. Tests needing fake gate details must provide `gateCodes` directly.

- [ ] **Step 5: Pass the portal route flag from PythonEngine**

Add `autoRoute?: boolean` to `PythonEngineOptions`, store `this.autoRoute = options.autoRoute ?? true`, and construct prepare args as:

```ts
const args = [
  this.script("prepare_monolith_input.py"),
  "--chunk",
  ...(this.autoRoute ? ["--portal-auto-route"] : []),
  "--run-dir",
  path.resolve(runDir),
  "--genre",
  "essay"
];
```

In `createProductionRuntime`, pass `autoRoute: config.autoRoute` when constructing `PythonEngine`; do not read `process.env` inside the engine.

- [ ] **Step 6: Run focused tests and typecheck**

Run:

```powershell
npm.cmd test -- tests/unit/python-engine.test.ts tests/integration/portal-route.test.ts tests/integration/python-engine.test.ts
npm.cmd run typecheck
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add src/engine/diagnostics.ts src/engine/python-engine.ts tests/unit/python-engine.test.ts
git commit -m "feat: validate humanize routing and gate metadata"
```

---

### Task 4: Extract Sequential Chunk Processing and Add Diagnostics

**Files:**
- Modify: `src/engine/humanize-engine.ts`
- Modify: `src/app.ts`
- Test: `tests/unit/humanize-engine.test.ts`
- Test: `tests/integration/api-transform.test.ts`

**Interfaces:**
- Consumes: `ProcessingMode`, `GateCode`, `ChunkTiming`, model constants, and the current `CodexAdapter`/`PythonAdapter`.
- Produces: `ChunkTaskResult`, `TransformDiagnostics`, and a behavior-preserving `processChunk()` path at concurrency one.

- [ ] **Step 1: Update fake manifest and gate constructors**

Every `ChunkManifest` test helper must include:

```ts
routeHint: "standard",
routeReason: "test route",
processingMode: "single",
```

Update gate constructors:

```ts
const ok = (): GateResult => ({
  status: "ok",
  exitCode: 0,
  gateCodes: ["GATE_OK"]
});
```

Use the corresponding code for warn, abort, and error.

- [ ] **Step 2: Write a failing diagnostics test**

Inject a deterministic clock through `HumanizeEngineOptions.now`:

```ts
const ticks = [0, 5, 15, 18, 20, 27, 30, 35, 40];
const now = () => ticks.shift() ?? 40;

const engine = new HumanizeEngine({
  python,
  codex,
  chunkConcurrency: 1,
  now
});

const result = await engine.transform(request);
expect(result.diagnostics).toMatchObject({
  model: "gpt-5.6-sol",
  reasoningEffort: "high",
  processingMode: "single",
  routeHint: "standard",
  bodyChunks: 1,
  codexCalls: 1,
  retries: 0,
  gateCodes: ["GATE_OK"],
  maxObservedCodexConcurrency: 1
});
```

Extend the constructor contract in the same RED cycle:

```ts
export interface HumanizeEngineOptions {
  python: PythonAdapter;
  codex: CodexAdapter;
  chunkConcurrency: 1 | 2;
  now?: () => number;
  maxObservedCodexConcurrency?: () => number;
}
```

Use `performance.now` as the production clock and `() => 1` as the temporary observation default until the real semaphore is wired in Task 6.

Add a warned chunk case and assert `codexCalls: 2`, `retries: 1`, and two gate codes. Keep the existing retry and rollback output assertions.

- [ ] **Step 3: Run the focused test and verify RED**

Run:

```powershell
npm.cmd test -- tests/unit/humanize-engine.test.ts
```

Expected: FAIL because diagnostics and the new constructor options do not exist.

- [ ] **Step 4: Extract one behavior-preserving chunk worker**

Add these internal types to `humanize-engine.ts`:

```ts
interface ChunkTaskContext {
  source: string;
  workspace: JobWorkspace;
  signal: AbortSignal;
  onWorkUnit(): void;
}

export interface ChunkTaskResult {
  chunkIndex: number;
  warnings: HumanizeWarning[];
  codexCalls: number;
  retries: number;
  gateCodes: GateCode[];
  timings: ChunkTiming;
}
```

Move the current first call, gate, one retry, rollback, and warning logic into:

```ts
private async processChunk(
  chunk: ChunkManifest["chunks"][number],
  context: ChunkTaskContext
): Promise<ChunkTaskResult>
```

Do not change ordering yet. Keep the original `for` loop and `await this.processChunk(...)` one at a time. Call `onWorkUnit()` once after first Codex completion and once after final gate/rollback completion.

- [ ] **Step 5: Aggregate diagnostics without content fields**

Add `diagnostics` to `HumanizeResult`. Measure `prepare`, all Codex, all gates, reassembly/full gate, and total with `now()`. Sum chunk results in manifest order. Import fixed model constants rather than duplicating strings.

`codexMs` and `gateMs` are sums of per-call durations and may exceed wall-clock `totalMs` after concurrency is enabled. Include the final full-document gate code in `gateCodes`; keep `assembleMs` limited to reassembly wall time.

In `app.ts`, log only:

```ts
logger.info({
  event: "transform_complete",
  jobId,
  sourceChars: result.sourceChars,
  outputChars: result.outputChars,
  chunks: result.chunks,
  elapsedMs: Date.now() - startedAt,
  diagnostics: result.diagnostics
});
```

Update `tests/integration/api-transform.test.ts` fake results to include a complete literal diagnostics object. Assert response NDJSON still omits diagnostics and contains no model, route, source, or prompt fields.

- [ ] **Step 6: Run focused and regression tests**

Run:

```powershell
npm.cmd test -- tests/unit/humanize-engine.test.ts tests/integration/api-transform.test.ts tests/integration/humanize-engine.test.ts
npm.cmd run typecheck
```

Expected: all pass and existing retry/rollback/cancellation behavior remains unchanged.

- [ ] **Step 7: Commit**

```powershell
git add src/engine/humanize-engine.ts src/app.ts tests/unit/humanize-engine.test.ts tests/integration/api-transform.test.ts tests/integration/humanize-engine.test.ts
git commit -m "refactor: isolate chunk work and record safe diagnostics"
```

---

### Task 5: Build the Global Semaphore and Bounded Worker Pool

**Files:**
- Create: `src/engine/codex-semaphore.ts`
- Create: `src/engine/chunk-pool.ts`
- Create: `tests/unit/codex-semaphore.test.ts`
- Create: `tests/unit/chunk-pool.test.ts`

**Interfaces:**
- Produces: `CodexSemaphore.run(signal, task)`, `CodexSemaphore.maxObserved`, and `runChunkPool(items, concurrency, parentSignal, worker)`.
- Consumed later by: `CodexRunner` and `HumanizeEngine`.

- [ ] **Step 1: Write failing semaphore tests**

Use deferred promises to prove the third task cannot begin before one of the first two releases:

```ts
const semaphore = new CodexSemaphore(2);
let active = 0;
let maxActive = 0;
const releases = [deferred<void>(), deferred<void>(), deferred<void>()];

const tasks = releases.map(item =>
  semaphore.run(new AbortController().signal, async () => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    await item.promise;
    active -= 1;
  })
);

await vi.waitFor(() => expect(active).toBe(2));
expect(maxActive).toBe(2);
releases[0]!.resolve();
await vi.waitFor(() => expect(semaphore.maxObserved).toBe(2));
```

Add a queued-abort case: aborting before permit acquisition rejects with an error whose public code is `CLIENT_ABORTED` and never runs the callback.

- [ ] **Step 2: Write failing chunk-pool tests**

Test literal input `[1,2,3,4]` with concurrency 2. Resolve workers in order `2,1,4,3`; expect returned results `["one","two","three","four"]` and max active 2.

Add a failure case where item 2 rejects. The worker for item 1 must observe the combined abort signal, queued items 3 and 4 must never start, and the pool must wait until item 1 settles before rejecting with item 2's error.

Add table cases for concurrency `0`, `-1`, `1.5`, and `NaN`; each must reject with `"Chunk concurrency must be a positive integer"` before any worker starts.

- [ ] **Step 3: Run and verify RED**

Run:

```powershell
npm.cmd test -- tests/unit/codex-semaphore.test.ts tests/unit/chunk-pool.test.ts
```

Expected: FAIL because both modules are missing.

- [ ] **Step 4: Implement the semaphore**

`CodexSemaphore` must validate capacity as a positive integer, remove aborted waiters, release permits in `finally`, and expose only numeric metadata. Implement the complete permit lifecycle as follows:

```ts
import { EngineError } from "./errors.js";

interface Waiter {
  grant(): void;
}

function cancelled(): EngineError {
  return new EngineError("CLIENT_ABORTED", true, "Codex permit wait cancelled");
}

export class CodexSemaphore {
  readonly capacity: number;
  private active = 0;
  private observed = 0;
  private readonly waiters: Waiter[] = [];

  constructor(capacity: number) {
    if (!Number.isInteger(capacity) || capacity < 1) {
      throw new Error("Codex semaphore capacity must be a positive integer");
    }
    this.capacity = capacity;
  }

  get maxObserved(): number {
    return this.observed;
  }

  async run<T>(signal: AbortSignal, task: () => Promise<T>): Promise<T> {
    await this.acquire(signal);
    try {
      return await task();
    } finally {
      this.release();
    }
  }

  private async acquire(signal: AbortSignal): Promise<void> {
    if (signal.aborted) throw cancelled();
    if (this.active < this.capacity) {
      this.active += 1;
      this.observed = Math.max(this.observed, this.active);
      return;
    }

    await new Promise<void>((resolve, reject) => {
      const waiter: Waiter = {
        grant: () => {
          signal.removeEventListener("abort", onAbort);
          this.active += 1;
          this.observed = Math.max(this.observed, this.active);
          resolve();
        }
      };
      const onAbort = (): void => {
        const index = this.waiters.indexOf(waiter);
        if (index >= 0) this.waiters.splice(index, 1);
        reject(cancelled());
      };
      signal.addEventListener("abort", onAbort, { once: true });
      this.waiters.push(waiter);
    });
  }

  private release(): void {
    this.active -= 1;
    this.waiters.shift()?.grant();
  }
}
```

The tests must prove `active` never becomes negative, an aborted waiter is removed before a later release, and a throwing task still releases its permit.

- [ ] **Step 5: Implement the bounded pool**

Use one job-local controller and fixed worker loops:

```ts
function clientAbortedError(): EngineError {
  return new EngineError("CLIENT_ABORTED", true, "Chunk pool cancelled");
}

export async function runChunkPool<T, R>(
  items: readonly T[],
  concurrency: number,
  parentSignal: AbortSignal,
  worker: (item: T, signal: AbortSignal) => Promise<R>
): Promise<R[]> {
  if (!Number.isInteger(concurrency) || concurrency < 1) {
    throw new Error("Chunk concurrency must be a positive integer");
  }
  const failure = new AbortController();
  const signal = AbortSignal.any([parentSignal, failure.signal]);
  const results = new Array<R>(items.length);
  let cursor = 0;
  let firstError: unknown;

  const runWorker = async (): Promise<void> => {
    while (!signal.aborted) {
      const index = cursor++;
      if (index >= items.length) return;
      try {
        results[index] = await worker(items[index]!, signal);
      } catch (error) {
        firstError ??= error;
        failure.abort();
        return;
      }
    }
  };

  await Promise.allSettled(
    Array.from({ length: Math.min(concurrency, items.length) }, runWorker)
  );
  if (firstError !== undefined) throw firstError;
  if (parentSignal.aborted) throw clientAbortedError();
  return results;
}
```

Define `clientAbortedError()` in this module using `EngineError("CLIENT_ABORTED", true, ...)`; do not throw a generic `AbortError` that would become `INTERNAL_ERROR`.

- [ ] **Step 6: Run focused tests and mutation checks**

Run:

```powershell
npm.cmd test -- tests/unit/codex-semaphore.test.ts tests/unit/chunk-pool.test.ts
npm.cmd run typecheck
```

Mentally mutate capacity 2 to 3, remove `finally`, remove `failure.abort()`, and return completion order instead of input order. At least one test must fail for each mutation.

- [ ] **Step 7: Commit**

```powershell
git add src/engine/codex-semaphore.ts src/engine/chunk-pool.ts tests/unit/codex-semaphore.test.ts tests/unit/chunk-pool.test.ts
git commit -m "feat: add bounded Codex and chunk concurrency"
```

---

### Task 6: Integrate Concurrency Two Without Changing Validation Semantics

**Files:**
- Modify: `src/engine/codex-runner.ts`
- Modify: `src/engine/humanize-engine.ts`
- Modify: `src/app.ts`
- Test: `tests/unit/codex-runner.test.ts`
- Test: `tests/unit/humanize-engine.test.ts`
- Test: `tests/integration/humanize-engine.test.ts`

**Interfaces:**
- Consumes: `CodexSemaphore`, `runChunkPool`, `AppConfig.chunkConcurrency`, `ProcessingMode`, and `processChunk()`.
- Produces: runtime-wide max two Codex subprocesses and mode-aware per-job concurrency.

- [ ] **Step 1: Write a failing Codex permit test**

Extend `CodexRunnerOptions` in the test fixture with a fake permit pool. Assert the fake's `run` method wraps the `CommandRunner.run` call exactly once for first and retry attempts. A runner error must still release the permit.

The wished-for interface is:

```ts
export interface CodexPermitPool {
  readonly maxObserved: number;
  run<T>(signal: AbortSignal, task: () => Promise<T>): Promise<T>;
}
```

- [ ] **Step 2: Write a failing four-chunk concurrency test**

Create a deferred fake Codex that records active calls and produces output by source text. Use a `chunked` manifest with four body spans and gates that all return OK. Configure `chunkConcurrency: 2`.

Assert:

```ts
expect(codex.maxActive).toBe(2);
expect(await readFile(result.finalPath, "utf8")).toBe("111222333444");
expect(result.diagnostics.maxObservedCodexConcurrency).toBe(2);
expect(result.diagnostics.codexCalls).toBe(4);
```

Resolve later chunks before earlier chunks to prove reassembly order is independent of completion order.

Add a `single` manifest with `chunkConcurrency: 2`; assert `maxActive === 1`.

- [ ] **Step 3: Write a failing sibling-cancellation test**

Start two chunk workers. Make chunk 2 reject with `ENGINE_OUTPUT_INVALID`; chunk 1 must observe abort and settle. Assert chunks 3 and 4 never start, reassembly is never called, and transform rejects only after active count reaches zero.

- [ ] **Step 4: Run and verify RED**

Run:

```powershell
npm.cmd test -- tests/unit/codex-runner.test.ts tests/unit/humanize-engine.test.ts
```

Expected: FAIL because permit wrapping and pooled execution are not integrated.

- [ ] **Step 5: Wire the global semaphore into CodexRunner**

Add `permitPool: CodexPermitPool` to `CodexRunnerOptions` and wrap only the subprocess interval:

```ts
const command = await this.options.permitPool.run(signal, () =>
  this.options.runner.run({
    command: this.options.codexCommand,
    args,
    cwd: path.dirname(sourcePath),
    stdin: prompt,
    timeoutMs: this.options.timeoutMs,
    signal,
    env: { ...process.env, NO_COLOR: "1" }
  })
);
```

Prompt building and output parsing do not consume a permit.

- [ ] **Step 6: Replace the sequential loop with mode-aware pool execution**

In `HumanizeEngine.transform()`:

```ts
const concurrency =
  manifest.processingMode === "single" ? 1 : this.chunkConcurrency;
const chunkResults = await runChunkPool(
  bodyChunks,
  concurrency,
  request.signal,
  (chunk, signal) => this.processChunk(chunk, { ...context, signal })
);
```

Sort or consume `chunkResults` by manifest order before emitting buffered warnings and aggregating diagnostics. Do not call reassemble until the pool fully settles.

In `createProductionRuntime`, construct one semaphore and share it with the sole CodexRunner:

```ts
const codexSemaphore = new CodexSemaphore(2);
const codex = new CodexRunner({ ...options, permitPool: codexSemaphore });
const engine = new HumanizeEngine({
  python,
  codex,
  chunkConcurrency: config.chunkConcurrency,
  maxObservedCodexConcurrency: () => codexSemaphore.maxObserved
});
```

When producing one job's diagnostics, clamp the lifetime semaphore observation to that job's chosen concurrency:

```ts
const maxObservedCodexConcurrency = Math.min(
  this.maxObservedCodexConcurrency(),
  concurrency
);
```

This keeps single-route diagnostics at 1 even after an earlier chunked job reached the global maximum 2.

- [ ] **Step 7: Run concurrency, regression, and cancellation tests**

Run:

```powershell
npm.cmd test -- tests/unit/codex-runner.test.ts tests/unit/humanize-engine.test.ts tests/integration/humanize-engine.test.ts tests/unit/command-runner.test.ts
npm.cmd run typecheck
```

Expected: all pass; retry, rollback, full gate, process-tree cancellation, and output order remain unchanged.

- [ ] **Step 8: Commit**

```powershell
git add src/engine/codex-runner.ts src/engine/humanize-engine.ts src/app.ts tests/unit/codex-runner.test.ts tests/unit/humanize-engine.test.ts tests/integration/humanize-engine.test.ts
git commit -m "perf: process long document chunks concurrently"
```

---

### Task 7: Emit Aggregate Monotonic Progress

**Files:**
- Modify: `src/contracts.ts`
- Modify: `src/engine/humanize-engine.ts`
- Modify: `public/progress.js`
- Test: `tests/unit/humanize-engine.test.ts`
- Test: `tests/unit/progress.test.js`
- Test: `tests/e2e/portal.spec.ts`
- Test: `tests/e2e/portal-visual.spec.ts`

**Interfaces:**
- Produces: optional wire-compatible `completedUnits` and `totalUnits` fields; the engine always emits them, while the browser retains the old phase fallback.
- Consumed by: `progressForEvent()` and the existing status/progress DOM.

- [ ] **Step 1: Write failing pure progress tests**

Add literal aggregate cases:

```js
expect(progressForEvent({
  type: "progress",
  phase: "transform",
  current: 4,
  total: 4,
  completedUnits: 1,
  totalUnits: 4
})).toBe(33.75);

expect(progressForEvent({
  type: "progress",
  phase: "verify",
  current: 1,
  total: 4,
  completedUnits: 4,
  totalUnits: 4
})).toBe(90);
```

Use the sequence `[0,1,3,2,4]` as emitted completed values only in a malformed-event test; valid engine events must be `[0,1,2,3,4]`. Assert malformed aggregate fields fall back to the existing phase calculation rather than returning NaN.

- [ ] **Step 2: Write a failing engine event test**

Run four chunks with out-of-order fake completion. Capture events and assert every emitted aggregate pair has `totalUnits === 8`, `completedUnits` is exactly `[1,2,3,4,5,6,7,8]`, and retry warnings do not increase `totalUnits`.

- [ ] **Step 3: Write a failing E2E stream test**

Update the mocked NDJSON stream to include aggregate fields in deliberately mixed phases:

```text
transform completedUnits=1 totalUnits=4
transform completedUnits=2 totalUnits=4
verify    completedUnits=3 totalUnits=4
verify    completedUnits=4 totalUnits=4
```

Assert observed progress values contain `33.75`, `52.5`, `71.25`, `90`, `95`, `100` and never decrease. Keep queued indeterminate removal/restoration assertions.

- [ ] **Step 4: Run and verify RED**

Run:

```powershell
npm.cmd test -- tests/unit/progress.test.js tests/unit/humanize-engine.test.ts
npm.cmd run test:e2e -- --grep "progress stays"
```

Expected: FAIL because aggregate fields are ignored/not emitted.

- [ ] **Step 5: Extend the event contract compatibly**

Add optional fields so old fixtures remain valid:

```ts
type TransformProgressEvent = {
  type: "progress";
  phase: TransformPhase;
  current: number;
  total: number;
  completedUnits?: number;
  totalUnits?: number;
  message: string;
};
```

The engine must always populate them for transform/verify phases. Use one synchronous counter incremented after first Codex completion and after final gate/rollback completion; JavaScript's event loop makes the increment atomic between awaits.

- [ ] **Step 6: Prefer aggregate progress in the browser**

At the start of the `progress` case:

```js
const completedUnits = Number(event.completedUnits);
const totalUnits = Number(event.totalUnits);
if (
  Number.isFinite(completedUnits) &&
  Number.isFinite(totalUnits) &&
  totalUnits > 0 &&
  completedUnits >= 0 &&
  completedUnits <= totalUnits
) {
  return clampProgress(15 + 75 * (completedUnits / totalUnits));
}
```

Retain current phase mapping below this branch.

- [ ] **Step 7: Run unit, E2E, and visual tests**

Run:

```powershell
npm.cmd test -- tests/unit/progress.test.js tests/unit/humanize-engine.test.ts
npm.cmd run test:e2e
```

Expected: all E2E and visual snapshots pass without updating snapshots unless the approved status copy/layout actually changed. Never update snapshots merely to hide a regression.

- [ ] **Step 8: Commit**

```powershell
git add src/contracts.ts src/engine/humanize-engine.ts public/progress.js tests/unit/humanize-engine.test.ts tests/unit/progress.test.js tests/e2e/portal.spec.ts tests/e2e/portal-visual.spec.ts tests/e2e/portal-visual.spec.ts-snapshots
git commit -m "feat: report aggregate concurrent progress"
```

---

### Task 8: Add the Opt-In Live Performance Gate

**Files:**
- Modify: `tests/helpers/live-engine.ts`
- Create: `tests/integration/performance-live.test.ts`
- Modify: `package.json`
- Modify: `README.md`
- Modify: `docs/operations.md`

**Interfaces:**
- Consumes: `PythonEngineOptions.autoRoute`, engine `chunkConcurrency`, and `TransformDiagnostics`.
- Produces: `runLiveEngineFixture(source, options)`, metadata-only p50 comparison, and `npm.cmd run test:performance`.

- [ ] **Step 1: Write a skipped-by-default performance test**

Create deterministic fixture builders inside `performance-live.test.ts`:

```ts
function shortFixture(): string {
  return Array.from({ length: 8 }, (_, index) =>
    `## 절 ${index + 1}\n\n` +
    `2026년 OpenAI 기준 ${index + 1}을 설명하는 자연스러운 한국어 문단입니다. ` +
    `"직접 인용 ${index + 1}"은 그대로 둡니다. `.repeat(5) +
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
```

Guard with:

```ts
const live = process.env.RUN_CODEX_LIVE === "1" ? describe : describe.skip;
```

For the short fixture, run three baseline calls with `autoRoute:false, chunkConcurrency:1` and three optimized calls with `autoRoute:true, chunkConcurrency:1`. Assert optimized diagnostics have bodyChunks 1, calls 1 or 2, exact headings/anchors, and `optimizedP50 <= baselineP50 * 0.4`.

For the long fixture, run three calls at concurrency 1 and three at concurrency 2. Assert `maxObservedCodexConcurrency <= 2`, quality checks match, and `parallelP50 <= serialP50 * 0.7`.

- [ ] **Step 2: Run without opt-in and verify the suite skips safely**

Run:

```powershell
npm.cmd test -- tests/integration/performance-live.test.ts
```

Expected: the file is discovered and skipped; it makes zero Codex calls.

- [ ] **Step 3: Extend the live helper with explicit options**

Use this interface:

```ts
export interface LiveEngineOptions {
  autoRoute: boolean;
  chunkConcurrency: 1 | 2;
  onEvent?: EventSink;
}

export interface LiveEngineResult {
  result: string;
  diagnostics: TransformDiagnostics;
  runtimeChildren: string[];
}
```

Construct `PythonEngine`, `CodexSemaphore`, `CodexRunner`, and `HumanizeEngine` using those options rather than mutating process-wide environment between runs. Preserve preflight, unique workspace creation, cleanup in `finally`, and the final empty runtime assertion.

- [ ] **Step 4: Add the explicit package script and safe report**

Add:

```json
"test:performance": "cross-env RUN_CODEX_LIVE=1 vitest run tests/integration/performance-live.test.ts"
```

The test may print one JSON object per configuration containing only fixture ID, chars, headings, model, effort, mode, route, chunk/call/retry/gate counts, timings, p50, and boolean quality results. It must never print source/result snippets or paths.

- [ ] **Step 5: Document run cost and rollback before executing live**

In README and operations docs, state that the benchmark makes 12 measured transformations, consumes the server PC's Codex quota, requires no active portal jobs, and writes no source/result artifacts. Document:

```powershell
$env:CODEX_CHUNK_CONCURRENCY='1'
npm.cmd run test:performance
Remove-Item Env:CODEX_CHUNK_CONCURRENCY
```

Also document runtime rollback as setting `CODEX_CHUNK_CONCURRENCY=1` before `npm.cmd start`.

- [ ] **Step 6: Run non-live regression tests**

Run:

```powershell
npm.cmd test -- tests/integration/codex-live.test.ts tests/integration/performance-live.test.ts
npm.cmd run typecheck
```

Expected: both live suites are skipped without `RUN_CODEX_LIVE=1`, and typecheck passes.

- [ ] **Step 7: Commit the harness before spending quota**

```powershell
git add tests/helpers/live-engine.ts tests/integration/performance-live.test.ts package.json README.md docs/operations.md
git commit -m "test: add opt-in humanize performance benchmark"
```

- [ ] **Step 8: Run the approved live benchmark**

Confirm `/api/health` shows `activeJobs: 0` and stop the portal server so the benchmark owns the Codex budget. Then run:

```powershell
npm.cmd run test:performance
```

Expected: both p50 thresholds and every quality/cleanup assertion pass. If either threshold or quality gate fails, retain the JSON metadata output, do not lower quality thresholds, and do not proceed to the default-concurrency switch in Task 9.

---

### Task 9: Promote the Proven Default, Verify Release, and Restart the Portal

**Files:**
- Modify: `src/config.ts`
- Modify: `tests/unit/config.test.ts`
- Modify: `README.md`
- Modify: `docs/operations.md`
- Test: all existing suites

**Interfaces:**
- Consumes: successful Task 8 benchmark evidence.
- Produces: final default `chunkConcurrency: 2`, documented rollback `1`, and a running verified portal.

- [ ] **Step 1: Gate this task on benchmark evidence**

Proceed only when Task 8 reports all of the following:

```text
short bodyChunks = 1
short codexCalls <= 2
short optimized p50 <= 40% of baseline p50
long concurrency max <= 2
long parallel p50 <= 70% of serial p50
heading/anchor/full-gate/cleanup checks = true
```

If any line fails, keep default concurrency 1, leave `CODEX_CHUNK_CONCURRENCY=2` available for further experiments, document the measured failure, and stop before claiming the performance design complete.

- [ ] **Step 2: Write the failing final-default test**

Change the default assertion in `tests/unit/config.test.ts`:

```ts
it("uses proven two-way chunk concurrency by default", () => {
  expect(loadConfig({}, process.cwd()).chunkConcurrency).toBe(2);
});
```

Run:

```powershell
npm.cmd test -- tests/unit/config.test.ts
```

Expected: FAIL because Task 1 intentionally left the default at 1.

- [ ] **Step 3: Switch only the proven default**

Change:

```ts
const concurrency = Number(env.CODEX_CHUNK_CONCURRENCY ?? 2);
```

Keep validation and the explicit environment rollback unchanged. Update docs to state final defaults: auto-route on, short light/standard single, heavy/over-15k chunked, global Codex max 2, `CODEX_CHUNK_CONCURRENCY=1` rollback.

- [ ] **Step 4: Run the complete release suite**

Run in this order:

```powershell
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
npm.cmd run test:live
git diff --check
git status --short
```

Expected: no failures; live protected anchors and workspace cleanup pass. Visual snapshots may change only if the approved status UI changed and were visually reviewed.

- [ ] **Step 5: Commit the final default and operations docs**

```powershell
git add src/config.ts tests/unit/config.test.ts README.md docs/operations.md
git commit -m "perf: enable proven two-way chunk processing"
```

- [ ] **Step 6: Start and verify the portal**

Run:

```powershell
npm.cmd start
```

From a second PowerShell process:

```powershell
$health = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:3210/api/health' -TimeoutSec 10
$health.StatusCode
$health.Content
```

Expected: HTTP 200, `status:"ready"`, zero active/queued jobs. Open Chrome at `http://localhost:3210`, run the short fixture once, and confirm single route, progress 100%, exact headings/anchors, and no console warnings/errors. Keep the resulting Chrome tab open for handoff.

---

## Final Review Checklist

- [ ] `gpt-5.6-sol` and `high` appear in one policy module and every Codex call test.
- [ ] Auto-route is opt-in at the vendor CLI boundary and on by default only in the portal.
- [ ] Missing/invalid route metadata falls back to chunked, never single.
- [ ] Single manifests keep trailing passthrough and pass lossless reassembly.
- [ ] Chunk concurrency and global Codex concurrency never exceed two.
- [ ] Worker failure/cancellation waits for siblings before cleanup.
- [ ] Retry, rollback, gate error, and full-document gate tests remain green.
- [ ] Aggregate progress is monotonic and legacy events still render.
- [ ] Diagnostics/logs contain metadata only.
- [ ] Live short and long p50 thresholds pass before default concurrency changes.
- [ ] README and operations document benchmark quota and rollback.
- [ ] Full unit, integration, build, E2E, visual, live, and health checks pass.
