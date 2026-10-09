# Skills Usage Guide

This repository ships two agent skills. Both run inside an existing Claude Code or Codex session.

| Skill | Audience | Purpose | Source |
|---|---|---|---|
| `humanize-kr` | End users | Polish Korean prose (direct text, TXT, MD, DOCX, PPTX) while preserving facts, numbers, quotations, and structure | [`skills/humanize-kr`](../skills/humanize-kr/SKILL.md) |
| `update-humanize-engine` | Maintainers | Sync the upstream Humanize engine into the fork, then update and verify this service, its skills, and the Windows app | [`.agents/skills/update-humanize-engine`](../.agents/skills/update-humanize-engine/SKILL.md) |

Use `humanize-kr` for everyday rewriting. Use `update-humanize-engine` only for engine maintenance. It never rewrites user text.

Source reviewed on October 2, 2026: `d9df30e`, application `0.4.0`, engine pinned to fork commit `9747f03` (Humanize label 2.3.2). Direct text supports rewrite strength and standalone HTML comparison; later source updates also strengthened preservation and recovery. An existing ZIP or installed skill may contain an earlier bridge/Gateway despite the same version label. This documentation update did not rebuild packages or inspect installed skills. See [Code Analysis](code-analysis.md) and [Service Analysis](service-analysis.md).

---

## 1. `humanize-kr`

### 1.1 How it works

The **current host session** does the rewriting. The skill does not start another Claude or Codex CLI, and it does not need the web portal or the desktop app.

A bundled, file-based **Gateway** (`engine_runtime/skill_gateway.py`) does everything except the rewrite itself:

- splits the input into chunks
- supplies rules and per-attempt instructions
- restores protected wording
- verifies preservation and decides whether to retry
- reassembles and exports the result

The Gateway never calls an LLM.

```text
prepare ─► (rewrite chunk ─► accept)* ─► finalize ─► cleanup
               ▲                │
               └── next / retry ┘
```

### 1.2 Installation

#### Windows (packaged ZIP)

`npm run skills:build` creates one ZIP per host in `release/`:

- `humanize-kr-claude-<version>-win-x64.zip`
- `humanize-kr-codex-<version>-win-x64.zip`

Each ZIP bundles Python 3.14 (with `lxml`), Node 24.19.0, the Gateway, the Node bridge, and the vendored engine. No separate Python or Node install is needed.

```powershell
# Claude Code (installs to %USERPROFILE%\.claude\skills\humanize-kr)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-humanize-skill.ps1 `
  -HostName Claude -Scope User -Archive .\release\humanize-kr-claude-0.4.0-win-x64.zip -Replace

# Codex (installs to %USERPROFILE%\.agents\skills\humanize-kr)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-humanize-skill.ps1 `
  -HostName Codex -Scope User -Archive .\release\humanize-kr-codex-0.4.0-win-x64.zip -Replace
```

| Option | Effect |
|---|---|
| `-HostName Claude\|Codex` | Required. Selects `.claude/skills` or `.agents/skills`. |
| `-Scope User\|Project` | `User` (default) installs under the user profile. `Project` installs under `-ProjectRoot`. |
| `-Archive <zip>` | ZIP to install. If omitted, the newest matching ZIP next to the script (or in `release/`) is used. |
| `-Replace` | Backs up an existing install to `<host>/skill-backups/` before overwriting. Without it, an existing different install is kept and the script stops. |

Running the installer again with the same ZIP does nothing. If the skill is not listed, start a new session.

#### macOS / Linux (from source)

No packaged ZIP exists for these platforms yet. You need:

- **Python 3.11 or newer.** The macOS system `python3` is 3.9 and will not work. DOCX/PPTX also need `lxml`.
- **Node 24.19.0 or newer** for direct-text input. It runs the comparison and fidelity bridge. TXT/MD/DOCX/PPTX input works without Node.
- **The bridge artifact** for direct text and optional additional TXT/MD structural checks. Build it with `node scripts/build-skill-bridge.mjs`; this creates `build-resources/skill-bridge/skill-bridge.cjs`.

If Node is not on `PATH`, set `NODE_COMMAND` to the Node executable. To use the skill from a host, copy or symlink `skills/humanize-kr` together with `engine_runtime/` and `vendor/humanize-engine/` into the host's skills directory, keeping the packaged layout shown in §1.7.

For TXT/MD files, the extra JavaScript paragraph/Markdown/duplication guard is enabled only when Node and the bridge are available. Python preservation checks still run without them. Direct text requires the bridge. Build/copy the bridge from the matching source revision when updating; an older generated bridge does not automatically gain new source checks.

### 1.3 Invoking the skill

Type the request **in the host's chat input**, not in a terminal.

| Host | Prefix |
|---|---|
| Claude Code | `/humanize-kr` |
| Codex | `$humanize-kr` |

#### Direct text (supports strength and comparison)

```text
/humanize-kr Rewrite the text below very strongly and also create a change-comparison HTML.

담당자는 자료의 정리 작업을 수행한다. 이 방안은 강한 경쟁력을 가지고 있다.
```

#### Files (TXT, MD, DOCX, PPTX)

```text
/humanize-kr Polish "C:\Docs\report.docx" and save it as a new file next to the original.
```

Requests can be written in Korean or English. For Codex, replace the prefix with `$humanize-kr`.

### 1.4 Rewrite strength (direct text only)

| Strength | Gateway value | Editing scope |
|---|---|---|
| Normal (default) | `normal` | Keeps the original wording and smooths awkward spots. |
| Medium | `medium` | Tidies vocabulary and long-winded expressions. |
| Strong | `strong` | Actively changes sentence structure and repetition. |
| Very strong | `very-strong` | Keeps the meaning while substantially reworking wording and sentence composition. |
| Very strong (rewrite) | `rewrite` | Rewrites the most broadly. The default engine runs it exactly as `very-strong`; under Super Sejong v2 each paragraph is rewritten freely (sentences merged, split or reordered inside it) with every sentence in the paragraph's dominant speech level, while numbers, quotations, names, meaning and calls to action stay. Added 2026-10-08 (WP-19). |

- If no strength is given, `normal` is used. The strength is fixed for the life of a job.
- Strength is **not a guarantee** of how much text changes. Protected sentences (numbers, conditions, quotations) stay verbatim.
- If preservation cannot be confirmed after at most one conservative retry, the chunk reverts to the source.
- Strength and comparison do not apply to file inputs. The Gateway rejects `--strength` without `--input-kind`, any strength other than `normal` for `--input-kind text-file`, `direct-text` for Office files, and `--comparison-output` for Office documents.

### 1.5 Change comparison HTML (direct text only)

Ask explicitly, for example "also create a comparison HTML". You then receive two files:

1. the verified final text (`<name>-humanized.md`)
2. a standalone comparison file (`.html`) that opens in a browser without a server

The comparison uses these markers:

- **Light yellow:** inserted or changed text.
- **Light red with strikethrough:** deleted text.
- **Final view / copy:** contains only the verified final text, without deletions.

Very large differences may be shown as a single replacement block. The comparison is generated only after full-document verification succeeds.

### 1.6 What is preserved

- **Content:** facts, claims, numbers, proper nouns, direct quotations, headings, paragraph order, register or tone, and Markdown markers.
- **Hedges and obligations:** expressions such as "~해야 한다" and "~로 판단된다". Sentences that lose them are restored from the source.
- **Commas:** commas the model injects after connective endings are removed.
- **No additions:** no new facts, metaphors, or examples are added.
- **Source text is data:** instructions inside the source are never followed.
- **Files:** the original file is never overwritten. Output goes to a new path, with a number appended if the name exists.
- **DOCX/PPTX layout:** formatting, tables, and shapes are preserved. Speaker notes, headers, footers, footnotes, masters, and charts are preserved but **not rewritten**. The text preview is not a real page or slide layout, so check the result in Word or PowerPoint.

### 1.6.1 Limits and recovery differences

The portal/desktop 100,000-character text cap and 1 MiB TXT/MD loading cap are not enforced by the host-session TXT/MD Gateway. Office package limits still apply: 50 MiB compressed, 250 MiB expanded, 10 MiB per XML part, 10,000 entries, 100,000 extracted characters and 200 PPTX slides. Paragraphs above 9,000 characters are preserved.

Direct-text skill finalization refuses export when full-document fidelity fails. The portal/desktop can instead restore the entire prepared source before final Python validation. The workflows share major checks but should not be assumed to have identical recovery in every case. Gateway jobs remain until cleanup; this is distinct from the web/app Office artifact store's idle 30-minute expiry.

### 1.7 Gateway reference (for hosts and debugging)

Normally the host session drives these commands by following [`references/workflow.md`](../skills/humanize-kr/references/workflow.md), or [`references/documents.md`](../skills/humanize-kr/references/documents.md) for Office files. Run them manually only for debugging.

Packaged layout (paths are relative to the folder containing `SKILL.md`):

```text
humanize-kr/
├── SKILL.md
├── references/            workflow.md, documents.md
├── agents/openai.yaml     (Codex only)
├── engine_runtime/        skill_gateway.py, skill-bridge.cjs, workflow.py, documents/
├── vendor/humanize-engine/
├── python/                bundled interpreter (Windows)
├── node/                  bundled Node (Windows)
└── distribution.json      product, version, host, engine pin
```

Commands (prefix each with `<python> engine_runtime/skill_gateway.py`):

| Command | Arguments | Result |
|---|---|---|
| `prepare` | `--input <file>` `[--input-kind direct-text]` `[--strength <value>]` | Creates a job. Returns `job`, `sourceHash`, `status`, and paths for the first chunk. DOCX/PPTX return `kind: document`. |
| `next` | `--job <job>` | Returns the next pending chunk. Use it to resume after an interruption. |
| `accept` | `--job` `--chunk` `--attempt 1\|2` `--source-hash` `--response <json>` | Verifies one rewritten chunk. Returns the next `status`, `chunk`, and `attempt` to follow exactly. |
| `finalize` | `--job` `--output <new file>` `[--comparison-output <new .html>]` | Reassembles and verifies the full document, then writes the output. Returns `status: done` with `outputPath` and `comparisonPath`. |
| `cleanup` | `--job <job>` | Deletes only that job's workspace. Returns `status: cleaned`. |

Global options:

- `--workspace-root`: default `<system TEMP>/humanize-kr-skills`.
- `--vendor-root`: default is the bundled `vendor/humanize-engine`.

Prepare returns these paths when `status` is `rewrite`:

- `inputPath`: the chunk text to rewrite.
- `rulesPath`: Korean rewriting rules.
- `instructionsPath` and `sentencesPath`: direct text only. Re-read them on **every** attempt. They carry the strength, retry policy, and sentence spans.
- `responsePath`: where the host writes its answer.

Response format for text chunks (UTF-8 JSON, no code fences inside the text):

```json
{"rewrittenText": "full rewritten chunk", "warnings": []}
```

When `instructionsPath` requests compact edits (direct text), use this format instead:

```json
{"rewrittenText": "", "edits": [{"before": "phrase occurring exactly once in the source", "after": "replacement"}], "warnings": []}
```

- `warnings`: at most 20 items, each 300 characters or fewer.
- `before` must match exactly once in the **source**. It must not come from an earlier candidate.
- Never mix full text and edits in one response. The first attempt at `very-strong`, and candidate review, use full text with an empty `edits` array.

Office documents use a separate block-edit contract (`schemaVersion: 2`, `batchId`, `reviewedIds`, per-block `edits`). See [`references/documents.md`](../skills/humanize-kr/references/documents.md).

Input decoding for TXT/MD uses UTF-16 when a UTF-16 BOM is present. Otherwise it tries UTF-8 (with or without BOM), then falls back to CP949/EUC-KR. Line endings are normalized to LF.

### 1.8 Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Skill not listed | Start a new host session. Check the install path (`.claude/skills` for Claude, `.agents/skills` for Codex). |
| `Direct text requires the bundled Node bridge` | Node is missing or the bridge was not built. Run `node scripts/build-skill-bridge.mjs` (source install) or set `NODE_COMMAND`. |
| `Strength requires explicit input kind` / `Strength is available for direct text only` | `--strength` was passed for a file. Use `--input-kind direct-text` for chat text, or drop `--strength`. |
| `Office files cannot be direct text` / `Comparison export is available for direct text only` | Direct-text options were used with DOCX/PPTX. Remove them. |
| Source hash or manifest mismatch, `operation.lock` conflict | The source changed or another call is still running. Wait for it to finish, or start a new job with `prepare`. Do not delete unknown locks or edit state files. |
| Some sentences unchanged or restored | Expected. Protection or verification kept the source. Check the returned warnings. |
| Python errors on macOS | The 3.9 system Python is being used. Use Python 3.11 or newer. DOCX/PPTX also require `lxml`. |

---

## 2. `update-humanize-engine` (maintainers)

### 2.1 Scope

This skill runs the full engine update pipeline:

1. **Sync.** Merge upstream [`epoko77-ai/im-not-ai`](https://github.com/epoko77-ai/im-not-ai) into the fork [`himangga01/im-not-ai_fork`](https://github.com/himangga01/im-not-ai_fork) and push the fork.
2. **Integrate.** Bring the synced fork commit into this service through `vendor/humanize-engine`, together with its portal patch.
3. **Verify.** Run the full test suite.
4. **Rebuild.** Build the skill ZIPs and the portable Windows app.

It does not polish text. Asking only for a check, or restricting writes, limits the run to that scope.

Invoke it from the repository:

```text
$update-humanize-engine Sync upstream into the fork and update our service and release artifacts.
```

Or check only:

```text
$update-humanize-engine Check whether an engine update is available. Do not change anything.
```

### 2.2 Read-only update check

```sh
python .agents/skills/update-humanize-engine/scripts/check_upstream.py --project-root <service checkout>
```

| Option | Default | Purpose |
|---|---|---|
| `--project-root` | `C:/project/2026/ai-text-makes-likes-human` | Service checkout to read the pin from. On macOS, pass this repository's path. |
| `--upstream-url` | fork URL | Remote to compare against. |
| `--ref` | `HEAD` | Remote ref, e.g. `refs/heads/<branch>`. |
| `--history-repo` | – | Read-only checkout that contains both commits. Required when history cannot be determined. |

The helper prints JSON and never fetches, checks out, or modifies anything.

| `status` | Meaning | Next step |
|---|---|---|
| `up_to_date` | Pin equals the remote. | Report the current commit, and any uncommitted changes (`worktree_dirty`). |
| `update_available` | Remote is a descendant of the pin. | Use `latest_commit` as the fixed update target. |
| `upstream_behind` | The fork is older than the pin. | Sync upstream into the fork first, then re-check. Never apply an older fork. |
| `history_diverged` | Histories split. | Review ahead/behind counts and code differences. Never overwrite blindly. |
| `history_required` | Not enough history to decide. | Obtain both commits in an isolated repo and re-run with `--history-repo`. |
| `provenance_update_required` | Same code, different recorded source. | Align `sync-engine.ps1` and the provenance records with the fork. |
| `error` | Access, auth, or pin-format failure. | Not evidence of being up to date. Fix the cause and report it. |

### 2.3 Workflow summary

1. **Sync the fork.**
   - If the upstream and fork HEADs are equal, skip this step.
   - Otherwise clone the fork into an isolated folder and fetch upstream.
   - Fast-forward when the fork has no unique commits. Otherwise do a normal merge and resolve conflicts by reading both sides.
   - Push normally and confirm with `git ls-remote`. **Never force-push or reset away fork changes.**
2. **Compare the pin.** Run `check_upstream.py` as described in §2.2.
3. **Analyze.**
   - Check the service's `git status`. Never discard existing changes.
   - Check out the target commit separately and review code, rules, dependencies, and license changes.
   - Read [`references/portal-integration.md`](../.agents/skills/update-humanize-engine/references/portal-integration.md) first.
4. **Integrate in staging.**
   - `scripts/sync-engine.ps1` overwrites vendor files *before* validating the patch. Run `git apply --check` against a staging copy first.
   - Keep these in agreement: `ENGINE_VERSION`, `UPSTREAM.md`, the sync script pin, and the pin tests.
   - Sync with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/sync-engine.ps1 -Source <clean fork checkout>`.
5. **Verify.** Run the model-free checks first. See §2.4.
6. **Release.**
   - Rebuild the skill ZIPs and the portable EXE.
   - Self-sign with the existing certificate when applicable.
   - Confirm that `release/build-info.json`, both skills' `distribution.json` files, and the vendor pin match.
   - Keep the previous EXE for rollback.

Live-model runs and the 12-run performance benchmark consume account quota. They follow the approval rules in [`operations.md`](operations.md). Restarting production servers or publishing releases requires separate deployment approval.

### 2.4 Verification commands

Windows (as written in the skill):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTHONUTF8='1'; $env:RUN_CODEX_LIVE='0'
python vendor/humanize-engine/scripts/build_quick_rules.py --check
python vendor/humanize-engine/scripts/build_diagnosis_rules.py --check
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
npm.cmd run test:skills
npm.cmd run desktop:build
npm.cmd run test:documents
npm.cmd run test:desktop
npm.cmd run skills:build
node scripts/verify-skill-packages.mjs
npm.cmd run desktop:portable
git diff --check
```

macOS (a subset; Windows-only suites skip automatically, and packaging runs on Windows):

```sh
export PYTHON_COMMAND=$HOME/.hermes/hermes-agent/venv/bin/python   # any Python ≥ 3.11 with lxml
npm run typecheck
npm test
npm run test:skills
npm run test:documents
E2E_PORT=7893 npm run test:e2e   # runs beside the live service on 7882
```

When changing the detection helper itself, run the offline tests:

```sh
python .agents/skills/update-humanize-engine/scripts/test_check_upstream.py
```

---

## 3. Related documents

- [README](../README.md): product overview and Korean quick start
- [Desktop app and skill installation](desktop.md)
- [Office document support](documents.md)
- [Operations and macOS service management](operations.md)
- [0.4.0 release notes](releases/0.4.0.md)
