# Task 2 report: bounded Unicode diff and read-only result component

## Scope

Implemented only the Task 2 surface:

- `public/text-diff.js`
- `public/text-diff-worker.js`
- `public/result-diff.js`
- `tests/unit/text-diff.test.js`
- `tests/e2e/result-diff.spec.ts`

No app wiring, page markup, shared stylesheet, backend, or release file was changed. The component intentionally does not create the Korean option controls, final textarea, global copy button, or labels owned by Task 3.

## TDD evidence

The implementation followed observable red/green cycles.

1. Core reconstruction/Unicode tests were added first. RED failed because `public/text-diff.js` did not exist. GREEN: 10 focused cases passed after the line/word/grapheme diff was introduced.
2. The 10k/50k all-changed budget tests were added before bounds. RED was meaningful and severe: the 10k case took 9.3 seconds and the following case exhausted the Vitest worker's roughly 4 GB heap. GREEN: both inputs returned exact two-node coarse replacements in milliseconds.
3. Direct/worker/cancellation tests were added before the async engine. RED: all three failed with `createTextDiffEngine is not a function`. GREEN: 16/16 unit tests passed.
4. Browser component tests were added before `public/result-diff.js`. RED: all four failed to import the missing HTTP module. The first implementation made three pass; the deletion-only selection test then failed because `Range.cloneContents()` drops the selected `del` wrapper when only its contents are selected. The renderer was fixed to project selected live text nodes while excluding nodes under `del`; GREEN: 4/4 Playwright component tests passed.

Final fresh verification:

- `npm.cmd run typecheck`: exit 0.
- `npm.cmd test`: 41 test files passed, 1 skipped; 264 tests passed, 3 skipped.
- `npm.cmd run test:e2e -- tests/e2e/result-diff.spec.ts`: 4/4 passed in Chromium.
- Deterministic reconstruction fuzz: 2,000/2,000 randomized pairs reconstructed both inputs exactly.
- `git diff --check`: exit 0.

## Diff algorithm and bounds

`diffText(source, target, options?)` aligns newline-preserving line tokens, refines changed line runs using word tokens, then refines changed word runs using grapheme clusters. Myers frontier search is used at each level, with a shared operation and wall-clock budget. It does not allocate an N×M whole-input matrix. `Intl.Segmenter` supplies Unicode word and grapheme boundaries, so ZWJ emoji and combining sequences stay intact.

Defaults for direct computation are 250,000 operations, 100 ms, and 5,000 display nodes. The worker engine changes the wall-clock budget to 500 ms for total source plus target length at or above 10,000 UTF-16 code units. On any compute or node-budget overflow, it returns a truthful coarse replacement: the complete source as `delete` and the complete target as `insert`, omitting an empty side. It never reports overflow as unchanged.

Measured on this worktree during final verification:

| Fixture | Wall time | Counted operations | Nodes | Result |
| --- | ---: | ---: | ---: | --- |
| Small Korean replacement | 0.800 ms | 145 | 6 | refined |
| 10k all changed | 37.941 ms | 250,001 | 2 | coarse |
| 50k all changed | 20.160 ms | 250,001 | 2 | coarse |

Wall-clock timing is machine-dependent. The operation ceiling is deterministic. The time ceiling is cooperative and is checked between algorithm steps; module-worker execution prevents large computations from blocking the page even if a single platform segmentation call runs long.

## Public API for Task 3 integration

### `diffText(source, target, options?)`

Options:

- `maxOperations` (default `250000`)
- `maxTimeMs` (default `100`)
- `maxDisplayNodes` (default `5000`)

Return shape:

```js
{
  segments: Array<{ type: "equal" | "insert" | "delete", text: string }>,
  coarse: boolean,
  notice: string | null,
  displayNodes: number,
  operations: number,
  elapsedMs: number
}
```

Reconstruction invariants:

```js
source === segments.filter(x => x.type !== "insert").map(x => x.text).join("")
target === segments.filter(x => x.type !== "delete").map(x => x.text).join("")
```

### `createTextDiffEngine(options?)`

Options:

- `workerThreshold` (default `10000`, comparing total source plus target length)
- `workerUrl` (default `new URL("./text-diff-worker.js", import.meta.url)`; resolves under HTTP and `humanize://app`)
- `workerFactory(url, { type: "module" })` for the external Worker boundary
- `diffOptions` passed to `diffText`

Methods:

- `compute(source, target, options?) -> Promise<DiffResult>`
- `cancel()`
- `dispose()`

Starting another job terminates and rejects the previous job with `AbortError`. Every worker message carries a generation; results from prior generations are ignored. `dispose()` is idempotent and rejects later computation.

### `createResultDiff(options)`

Required option:

- `container`: the element whose children the component owns

Optional integration options:

- `onStatus({ type, message })`
- `workerFactory`
- `workerThreshold`
- `scheduleFrame(callback)` (defaults to `requestAnimationFrame`)
- `renderBatchSize` (default `100` segments)

Returned methods:

- `await setResult(source, finalText)` returns `{ status: "rendered", result }` or `{ status: "stale" }` when superseded/reset/disposed while in flight.
- `setMode("diff" | "final")` lets host controls switch the component's two read-only views.
- `reset()` cancels active work and clears source/result content.
- `dispose()` cancels work and removes document/event listeners. It is idempotent.

The component emits only text nodes plus semantic `ins`/`del` nodes. It does not use `innerHTML`, parse Markdown, or transform either string. The final view is a `pre`, so whitespace and newlines remain literal. Each `ins`/`del` has an aria label containing Korean insertion/deletion start and end wording. CSS hooks are:

- `.result-diff`
- `.result-diff__copy-hint`
- `.result-diff__notice`
- `.result-diff__changes`
- `.result-diff__final`
- `.result-diff__insert`
- `.result-diff__delete`

The component always displays this hint: `변경 비교에서 복사하면 삭제된 내용은 제외됩니다. 비교 영역 밖까지 선택하려면 최종문 보기에서 복사하세요.`

Within the diff view, native Ctrl+C and context-menu copy go through the document `copy` event. A valid selection is projected to equal plus inserted text and writes only `text/plain`. A deletion-only selection cancels the copy without writing, preserving the current clipboard and reporting a notice. A selection crossing the component boundary also cancels without writing and directs the user to final-text view. Selection in final view retains normal browser behavior. The lower-level tested contract is also exported as `createDiffCopyHandlers({ root, changes, onStatus, getSelection? })`, returning `handleCopy(event)` and `handleContextMenu(event)`.

## Caveats for integration

- Task 3 must call `dispose()` when permanently replacing/removing the component; `reset()` is enough for ordinary new runs.
- Host mode controls should call `setMode` and use their own pressed/selected state. The component intentionally creates no buttons.
- Component creation replaces all children of its `container`; give it a dedicated host element.
- The coarse notice should stay visible. It explains why a large or high-edit-distance input has only a whole-source deletion and whole-target insertion.
- `Intl.Segmenter`, module workers, `Range.intersectsNode`, and the ClipboardEvent `clipboardData` path are available in the project's current Electron/Chromium target. No compatibility dependency or CDN was added.

## Review fix round 1: final-view native copy

The document-level copy handler originally classified every selection inside the component root but outside `.result-diff__changes` as a cross-boundary selection. As a result, selecting text wholly inside `.result-diff__final` called `preventDefault()` and emitted the cross-boundary warning even though diff-specific filtering did not apply.

A focused Playwright regression was added first. RED reproduced the problem with `prevented: true` and one added warning status where native behavior required `prevented: false` and no status. The classifier now returns `unhandled` immediately when the range does not intersect the diff pane. A range that intersects the diff but has either endpoint outside it remains `outside`, so the existing cross-boundary and deletion-only protections are unchanged. The focused regression then passed; the complete component file is covered again in the verification recorded for the fix commit.

## Review fix round 2: generation-safe rendered state

The component previously updated the latest final text and generation at the start of `setResult`, but kept the prior diff DOM until the next computation returned. A worker rejection therefore left a visible comparison belonging to an earlier source/final pair. A render superseded between animation-frame batches could likewise leave its already appended batch visible while the next worker was pending.

Two focused Playwright regressions were added before the fix. RED observed `OLD-A ` from a superseded partial render and `PREVIOUS SOURCEFINAL` from the prior successful render during the next generation; both expected an empty comparison pane. The new generation now clears the comparison pane before starting computation while retaining the new final text and visible component shell. The current-generation error path also clears any partial comparison defensively. GREEN verified that the superseded call resolves with `status: "stale"`, the latest call renders successfully, and a rejected worker rethrows its error while leaving the latest final text intact and no older/partial diff nodes.
