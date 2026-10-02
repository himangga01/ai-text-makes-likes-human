# Works Log

## 2026-10-02 — Input size limits (100,000 chars, TXT/MD 1 MiB)

**Decision (user):** asked whether running without an input limit was OK, I recommended a cap. The user agreed to align with the existing DOCX/PPTX extracted-text limit:
- pasted text and TXT/MD: 100,000 characters
- TXT/MD files: also refused above 1 MiB before reading

**Why:**
- The server runs one job at a time (maxActiveJobs 1), with no login on the LAN, so one huge input holds the slot for hours and spends the owner's quota.
- Before the 09-30 fixes, inputs over roughly 60–80k chars failed at the final gate (an accidental cap). With that gate now 0.9 s at 100k, they would run to completion.
- Round-2 measured about 57 MB of Korean text adding roughly 650 MB of heap.

**Existing limits, unchanged:** DOCX/PPTX were already capped: 50 MiB file, 100,000 extracted chars, 250 MiB unzipped, 10 MiB per XML part, at most 3 documents held. TXT/MD had no limit at all, and the browser read the whole file.

**Changes** (commit `d9df30e`, pushed `2389733..d9df30e`)
- New `src/engine/input-limits.ts`: MAX_INPUT_CHARS 100,000, MAX_TEXT_FILE_BYTES 1 MiB, MAX_INPUT_BYTES 400,000 (4 bytes per code point). Characters are counted as code points after LF normalization.
- Server:
  - new public code INPUT_TOO_LARGE, message "원문은 100,000자 이하만 변환할 수 있습니다. 나눠서 변환해 주세요."
  - Content-Length over 400,000 gets 413 before the body is read
  - otherwise `streamRequestBody` stops and removes the partial file once the input passes 100,000 chars
  - `/api/health` and the desktop worker health serve `inputLimits`
- Desktop: the worker rejects over-limit text; main refuses TXT/MD over 1 MiB before `readFile`.
- Web UI:
  - `readTextFile` checks size before reading and length after decoding
  - typed text shows "N / 100,000자" in red, disables Transform and shows "글자 수 초과" with the message
  - the limits come from health, falling back to the same defaults
- Docs: README now states the limits instead of "고정 글자 수 제한은 없습니다"; operations.md describes the codes.
- Not limited: the skill path (engine_runtime/skill_gateway.py). It runs in the user's own agent session, not on the shared server.

**Verification**

| Check | Result |
|---|---|
| typecheck | exit 0 |
| vitest | 408 passed, 9 skipped (was 403) |
| Playwright (E2E_PORT=7894) | 53 passed, 9 skipped (3 new specs) |

- New tests:
  - request-body: limit and exact-limit
  - text-file: size before read, char limit, defaults equal the server's INPUT_LIMITS
  - api-transform: 413 for 400,001 bytes, NDJSON INPUT_TOO_LARGE for 100,001 Hangul chars, engine not run
  - api-health: inputLimits
  - e2e: input-limits.spec ×3
- I first forgot the desktop-worker test harness's module stub list; 5 tests failed. Adding the stub fixed it.
- dist was backed up and restored around the e2e run.

**Deployment:**
- Pre-check showed 0 active and 0 queued jobs. `npm run build`, then a supervisor restart: `restarted`, PID 39629, ready, health `inputLimits` = {100000, 1048576}.
- Live checks on :7882:

  | Request | Result |
  |---|---|
  | 400,001-byte body | 413 INPUT_TOO_LARGE |
  | 100,001 Hangul chars | NDJSON error INPUT_TOO_LARGE, not retryable |
  | normal 131-char Claude Sonnet 5.5 transform | done in 8,252 ms |

  The LAN page returns 200, and the served text-file.js contains the new check.

## 2026-09-30 — Two-round critical review of the whole codebase (functionality and bugs)

**Request:** spawn several subagents that critique the existing work from different perspectives in parallel. Re-verify valid feedback in the main session and accept it. Repeat the cycle twice, as a full code inspection focused on features and bugs.

**Where the result lives (not on main, not pushed):** local branch `review/round-fixes`, currently checked out.

| Commit | Content |
|---|---|
| `98faf03` | Round-1 fixes (WIP integration commit) |
| `b2214b3` | Round-2 engine and server fixes |
| `1744d6d` | Round-2 UI and desktop fixes |
| `cafd904` | Round-2 Python gates and skill path |

- Total change against `83787f9`: 54 files, +1348/−294.
- The live service on :7882 still runs the `83787f9` build (dist was backed up and restored around every e2e run). It was not restarted.

**Process**
- **Round 1:** five read-only reviewers, each owning a disjoint part of the codebase:
  - model/settings/desktop/scripts
  - server/queue/lifecycle/supervisor
  - the TS rewrite pipeline
  - the Python preservation engine and DOCX/PPTX
  - frontend UX
- **Round 1 results:** 47 findings. The main session re-ran every repro script or checked the code. 44 were accepted and 3 deferred. Four fork agents in isolated worktrees implemented disjoint file sets, each test-first. The main session reviewed each diff and cherry-picked it.
- **Main-session correction to round 1:** a timed-out attempt 1 was made to skip its retry. Round 2 later reverted timeouts to fail the job.
- **Round 2:** five reviewers with new perspectives:
  - regression hunt on the server changes
  - regressions and false positives in the pipeline guards
  - a Python gate false-positive/false-negative audit on a 121-pair corpus
  - the frontend/server contract
  - a fresh sweep of the skill, desktop, document and health paths
- **Round 2 results:** 37 findings, all key ones reproduced in the main session. Three fork agents fixed them.
- **Worktree base problem:** the isolated worktrees were created from `main` (83787f9), not the integration commit. All three agents noticed and rebased to `98faf03` before editing. Verified: all round-2 commits have parent `98faf03`.

**Most important bugs found and fixed**
- **Silent content loss on uploads:** TXT/MD uploads and legacy API calls had no structural guard. A dropped or duplicated sentence was delivered with GATE_OK (C1, reproduced).
  - Round 2 showed the first fix over-reached: it rolled back 12 of 35 legitimate punctuation/split edits.
  - Final design: file inputs check layout, Markdown markers, prompt echo, and a split-robust duplicate rule. Drops are caught by the new Python `sentence_dropped`. Direct text keeps sentence counts.
  - False positives on the reviewer corpus went from 7/29 to 0/29.
- **Regression introduced in round 1, caught in round 2 by three reviewers independently:**
  - Per-chunk recovery (C4) caught ENGINE_OUTPUT_INVALID. The runners mapped every non-zero CLI exit (429 usage limit, expired login, network) to that code.
  - So a job whose every CLI call failed ended as "완료" with the source text. Reproduced: a fake 429 runner gave `RESOLVED calls=2 same=true`.
  - Fix: a new public code `ENGINE_FAILED` (retryable) for non-zero exits and Claude `is_error` envelopes; it fails the job. Timeouts fail the job again. A job whose every chunk was unusable throws.
  - After the fix: `THREW ENGINE_FAILED calls=1`.
- **Modality restore corrupting text:** when the model reordered parallel sentences, the restore pasted the wrong source sentence. One claim was lost, another duplicated, and the gate accepted it (D1, reproduced).
- **Full-document gate cost:** it was quadratic. Large documents timed out at the last step after spending every model call: 100k chars took 73.4 s against a 120 s timeout, and the synthetic 60k case took 186.9 s. After the fix, 100k realistic chars take 0.9 s.
- **Orphaned CLI children:** detached CLI children survived a server crash or SIGKILL and kept spending quota (B1, reproduced). Fixed with a child registry killed on exit, and a supervisor that kills the server's child groups before its SIGKILL.
- **Wrong error reporting and model handling:**
  - A CLI model rejection surfaced as "결과 형식 오류". Now MODEL_UNAVAILABLE, checked only on failed runs, because Claude prints the tag as a warning on successful runs too.
  - Document errors were always "VALIDATION_FAILED, retryable" with raw English text.
  - Desktop preferences pinned defaults on first run.
- **Python gate false positives (round-2 audit, 121-pair corpus):**
  - Round-1 gates raised false positives from 20.3% to 31.6%: 세대/열대/천장/십분 read as numbers, casing fixes read as name changes.
  - After the round-2 fixes: false positives 25/79 → 2/79, false negatives 13/42 → 3/42.
  - Only one real miss remains: numbers swapped between entities.
  - The remaining false positives are date reformatting and 1시간→한 시간 (deferred).
- **Frontend:**
  - The page died entirely when site storage was blocked (E1, reproduced in node).
  - A late cancel after `done` wiped the result and deleted the finished Office document.
  - The health poll locked Transform every 60 s.
  - The TXT save default overwrote the source.
  - The copy label got stuck.
  - Status handling was stale after recovery.
  - The model re-sync was missing for documents.
  - Network errors appeared in English.
- **Server and supervisor:**
  - A reused PID after reboot blocked startup forever. The lock now stores the kernel boot identity.
  - An empty supervisor `owner.json` bricked every command.
  - A DELETE during a transform could be undone.
  - Shutdown-killed jobs showed "you cancelled".
  - A double SIGINT from npm took the hard-exit path.
- **Skill path:** it lacked the server's structural check, whitespace alignment and invalid-reply recovery. Now at parity through new bridge operations.
- **Stale test bundle:** the skill bridge bundle used by the tests dated from 2026-09-10. It is now rebuilt on every test run.
- **Vendor engine patch:** `scripts/patches/humanize-engine-portal.patch` was regenerated twice. It covers 7 files, and applying it to pristine upstream reproduces the modified vendor tree byte for byte. UPSTREAM.md and sync-engine.ps1 are consistent with it.

**Verification (integrated branch, cafd904)**

| Check | Before (83787f9) | After |
|---|---|---|
| typecheck | — | exit 0 |
| vitest | 333 passed, 1 failed | 403 passed, 0 failed, 9 skipped |
| test:documents | 32 OK | 40 OK |
| test:skills | 25 OK | 63 OK (4 skipped) |
| Playwright (E2E_PORT=7894) | 29 passed, 1 failed | 50 passed, 0 failed, 9 skipped |

- The Playwright skips are Windows-only visual baselines.
- The rule index `--check` scripts pass, and `git diff --check` is clean.

**Correction to the 2026-09-29 entry:** the `document-lifecycle` failure came from the test building its config with `loadConfig({})`, which ignored PYTHON_COMMAND. It now honors it and passes.

**Deferred (decisions for the user)**
- B5: no input size or duration cap (README promises no fixed limit).
- B10: Host-header / DNS-rebinding hardening (could affect LAN access by hostname).
- B4: a descendant process holding the stdio pipes (no current path).
- Undetectable Korean personal-name changes.
- Date and 한 시간 number reformatting.
- Clearing the desktop text source on reset (the overwrite guard is kept on purpose).

**Behavior changes users will notice**
- New hard failures that retry, then roll back the chunk: `sentence_dropped`, `name_changed` (casefolded set of Latin words and Hanja runs), and changed number words.
- CLI failures and timeouts now fail the job with a clear Korean message instead of returning the source.
- The medium effort label is now "Medium · 균형"; the engine default gets " · 기본".
- The Windows visual baselines may need re-capturing because of the new label text and the result-diff wrapper.

**Deployment (approved by the user, 2026-09-30)**
- The integration branch was squashed into one commit on main, `2389733`. Its tree is byte-identical to the verified `cafd904`.
- Re-checked on main: typecheck exit 0, vitest 403 passed.
- Pushed `83787f9..2389733` to origin/main. The local `review/round-fixes` branch was deleted after the tree-equality check.
- Deployed with `npm run build` (exit 0), then `~/.hermes/node/bin/node dist/ops/hermes-service.js restart`. The pre-check showed 0 active and 0 queued jobs.
- Supervisor result: `restarted`, new PID 11023, status `ready`. Codex 0.159.0 and Claude 2.1.285 are ready; the Claude CLI had auto-updated from 2.1.284. Documents are available, the old PID is gone, and the LAN page returns 200.
- Live smoke on :7882, using the 131-char sample:

  | Request | Result |
  |---|---|
  | Claude Sonnet 5.5, low | done in 9,313 ms, 1 chunk |
  | Codex GPT-6 Sol, low | done in 31,799 ms, 1 chunk |
  | GPT-5.5 | rejected with INVALID_MODEL_SETTINGS |

  - Health serves `modelDefaults`, and the served `connection-settings.js` contains the round-1 `resolveModelSelection`.

## 2026-09-30 — GPT-5.5 removed, live service rebuilt and restarted

**What changed** (commit `83787f9`, pushed to `origin/main`, `1de151a..83787f9`)
- `src/engine/model-policy.ts`: removed `gpt-5.5` at the user's request (it retires 2026-10-14). Codex now offers 6 models: `gpt-5.6-sol`, `gpt-6-astra`, `gpt-6-sol`, `gpt-6-luna`, `gpt-5.6-terra`, `gpt-5.6-luna`. The comment now cites the Codex 0.159.0 catalog and records why GPT-5.5 is left out.
- `tests/unit/model-settings.test.ts`: asserts `gpt-5.5` is rejected.
- `README.md`: notes the GPT-5.5 removal.

**Codex auto-update noticed:** the Codex CLI updated itself from 0.157.1 to 0.159.0 at 2026-09-29 23:58 (symlink `~/.local/bin/codex` → `~/.codex/packages/standalone/current`). `codex debug models` under 0.159.0 returns the same 9 entries (7 visible) as under 0.157.1, so nothing new to add.

**Deployment**
- Pre-check: supervisor status `healthy`, PID 80769, `activeJobs` 0, `queuedJobs` 0.
- `npm run build` (exit 0), then `~/.hermes/node/bin/node dist/ops/hermes-service.js restart`. It was run with the Hermes Node on purpose: the supervisor uses `process.execPath` as the server's Node and to recognise the managed process, and the running server used that binary.
- Result: `outcome: restarted`, new PID 21902 (started 2026-09-30 00:01:12), status `ready`, Codex 0.159.0 and Claude 2.1.284 both ready. Old PID 80769 gone; port 7882 served by 21902; LAN URL `http://192.168.0.22:7882/` returns 200.
- Live checks on 7882: `/api/health` lists Claude `fable-5-1, opus-5-5, sonnet-5-5, sonnet-5, opus-5` and the 6 Codex models above. Sonnet 5.5 `low` transform completed (1 chunk, 11,818 ms). A `gpt-5.5` request is rejected with `INVALID_MODEL_SETTINGS`.

**Verification:** typecheck exit 0; unit + integration 329 passed, 1 failed (the known `document-lifecycle` system-`python3` failure), 13 skipped.

## 2026-09-29 — Claude Sonnet 5.5 added, GPT-5.2 removed, full model audit

**Why:** the earlier Opus 5.5 commit (`7e3cf07`) missed Claude Sonnet 5.5. The user pointed this out and asked for a proper re-check of both the Claude and Codex model lists. Root cause: only the models already in the working-tree diff were verified; the current Claude lineup was never cross-checked.

**What changed** (commit `1de151a`, pushed to `origin/main`, `7e3cf07..1de151a`)
- `src/engine/model-policy.ts`: added `claude-sonnet-5-5` (`low`..`max`); removed `gpt-5.2`; catalog comment now names Codex 0.157.1 / Claude Code 2.1.284.
- `tests/unit/model-settings.test.ts`: Sonnet 5.5 in the option-list expectation, and new assertions: Sonnet 5.5 `max` accepted and `ultra` rejected; `gpt-6-sol` `ultra` accepted; `gpt-6-luna` `ultra` rejected; `gpt-5.2` rejected.
- `README.md`: Sonnet 5.5 (needs Claude Code 2.1.284+) and a note that GPT-5.2 was removed.

**Sources checked**
- Claude: Claude Code docs (`code.claude.com/docs/en/model-config`) list `claude-sonnet-5-5`, requiring v2.1.284+, efforts `low`..`max`. Installed CLI is exactly 2.1.284. The claude-api reference (cached 2026-09-25) agrees on ID and effort levels.
- Codex: `codex debug models` and `~/.codex/models_cache.json` (fetched 2026-09-29 14:48 UTC, client 0.157.1) list 7 visible models, all already offered. `gpt-5.2` is absent. OpenAI docs (`learn.chatgpt.com/docs/models`) show nothing newer than GPT-6 Astra/Sol/Luna and list GPT-5.2 as deprecated for ChatGPT sign-in. Release notes for 0.158.0/0.159.0 (latest on npm: 0.159.0) mention no catalog changes.
- One conflict: the docs page (read through a summarizer) listed GPT-6 Sol efforts up to Max only, but the CLI catalog lists `ultra`, and a live `gpt-6-sol`/`ultra` call returned OK. Kept `ultra`.

**Live verification**
- Direct CLI calls with the runner's exact flags: `claude-sonnet-5-5` `low` and `max` OK; `gpt-6-sol` `low` and `ultra` OK; `gpt-5.2` failed with `400 The 'gpt-5.2' model is not supported when using Codex with a ChatGPT account` (login mode: ChatGPT).
- End to end on a test instance of the current source (`tsx src/server.ts`, port 7893, `HUMANIZE_RUNTIME_ROOT` in the scratchpad, same `PYTHON_COMMAND`/CLI paths as the live service), 131-char sample: Sonnet 5.5 `low` completed in 9,620 ms, GPT-6 Sol `low` in 27,371 ms, 1 chunk each, facts preserved. `gpt-5.2` is now rejected up front with `INVALID_MODEL_SETTINGS`. The test instance was stopped afterwards.
- Removing a model is safe for saved settings: `public/app.js` `renderModelControls` falls back to the first option, and `desktop/preferences.ts:22` drops an invalid saved selection.
- Typecheck exit 0; unit + integration 329 passed, 1 failed (same `document-lifecycle` failure as before, see correction below), 13 skipped.

**Not added, with reasons**
- `claude-haiku-4-5`: the API rejects `effort` on Haiku 4.5, and this service always sends `--effort`. A live CLI call returned OK, so the CLI appears to accept or drop the flag, which would make the effort selector meaningless. Not a new model either.
- Older IDs still accepted by Claude Code (`claude-fable-5`, `claude-opus-4-8/4-7/4-6`, `claude-sonnet-4-6/4-5`): not added, to keep the curated list to current generations.

**Correction to the previous entry**
- The `document-lifecycle` failure (`No module named 'lxml'`) is not a missing package on the service: the live service's `PYTHON_COMMAND` (`~/.hermes/hermes-agent/venv/bin/python`, 3.11.15) has `lxml` 6.1.3. The test runs against the shell's system `python3` (3.9 from Command Line Tools) and does not read `PYTHON_COMMAND`. Not fixed.

**Left open**
- The live service on port 7882 (PID 80769, `dist/` built 2026-09-27 17:02) still serves the old list: no Sonnet 5.5, and `gpt-5.2` is still there. It needs `npm run build` and a restart. Not done, because the service is managed outside this repo.
- GPT-5.5 retires 2026-10-14 per OpenAI docs; it is still in the list.
- The Claude CLI must be 2.1.284+ for Sonnet 5.5; there is still no version gate in code.

## 2026-09-29 — Claude Opus 5.5 support verified and pushed

**What changed** (commit `7e3cf07`, pushed to `origin/main`, `5da719f..7e3cf07`)
- `src/engine/model-policy.ts`: added `claude-opus-5-5` (efforts `low`..`max`), `gpt-6-sol` (`low`..`ultra`), `gpt-6-luna` (`low`..`max`) to `MODEL_OPTIONS`. These edits were already in the working tree; this session verified and committed them.
- `tests/unit/model-settings.test.ts`: option-list expectation plus new assertions: Opus 5.5 accepts `max`, rejects `ultra`, and is rejected under the `codex` engine.
- `README.md`: added a line for the new models, noting Opus 5.5 needs Claude Code 2.1.280+.

**Analysis: how a new model reaches users**
- `MODEL_OPTIONS` is the single source. `/api/health` (server) and `desktop/worker.ts` return it as `modelOptions`, and `public/app.js` builds the model/effort dropdowns from that response. Adding an entry is enough for the web and desktop UI; no frontend edit is needed.
- `parseModelSettings` validates model plus effort per engine; `ClaudeRunner` passes them as `--model` / `--effort`.
- There is no CLI version gate in code. With a Claude CLI older than 2.1.280, an Opus 5.5 request would fail as the generic "Claude exited without a valid result". Documented in the README only; not addressed in code.

**Verification**
- `npm run typecheck`: exit 0.
- `vitest run tests/unit`: 252 passed, 6 skipped.
- `vitest run tests/unit tests/integration`: 329 passed, 1 failed, 13 skipped. The failure (`document-lifecycle.test.ts`) is `No module named 'lxml'`: this Mac's Python lacks `lxml==6.1.3` (documented prerequisite in `docs/documents.md`). Unrelated to this change; not fixed.
- Playwright e2e was not run: port 7882 was held by the running service (PID 80769, `dist/server.js`, started 2026-09-27 17:03), and it was left running.
- Installed Claude CLI: 2.1.284. Direct CLI call with the runner's exact flags and `--model claude-opus-5-5`: OK at `--effort low` and `--effort max`; `modelUsage` reports `claude-opus-5-5`.
- Live service `/api/health` already lists `claude-opus-5-5` (dist built 2026-09-27 17:02).
- End-to-end transform through the live service (`engine=claude&model=claude-opus-5-5&effort=low`, 131-char, 3-sentence Korean sample): `done` in 18,366 ms, 1 chunk, 125 output chars. Numbers (2026, 3분기, 12%) and modal expressions were preserved; one retry and a "review recommended" warning were raised, which is the normal preservation path.

**Left open**
- `docs/code-analysis.md` and `docs/service-analysis.md` stay untracked and uncommitted. They are dated 2026-09-05, describe revision `2ada4fb`, and are stale (e.g. Claude default `claude-opus-5`, DOCX "not implemented").
- `docs/operations.md:12` still says the Claude default is `claude-opus-5`/`medium`; actual default is `claude-fable-5-1`/`high`.
- The Claude path emits warning code `CODEX_WARNING` for model notes (pre-existing naming).
