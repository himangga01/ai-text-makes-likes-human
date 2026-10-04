# Code Analysis

Baseline analysis: October 2, 2026 (Asia/Seoul). Reviewed and updated: October 3, 2026.

Inspected source revision: `d9df30ee495b1e97764410e16785c245d77d25ff` on `main`. Application version: `0.4.0`. Vendored engine label: `2.3.2`; pinned upstream commit: `9747f036cdc28a1a8aea4dc71fef1f7846eb96f7`.

The original static analysis below describes the October 2 checkout at `d9df30e`. The October 3 changes are recorded in the addendum before it; this document now reflects the reviewed working tree. The October 2 pass did not run tests. The October 3 pass ran type checking, Python and Vitest suites, a browser E2E slice, and an isolated live Codex fixture. No deployment was performed.

## October 3 review addendum

Two independent rounds of code and service review found and reproduced failure modes in semantic preservation, runtime isolation, import state, and Office packaging. The current text and Office paths both use [Super Sejong semantic checks](../engine_runtime/super_sejong.py): selected negation and its target, obligation and possibility by sentence, high-confidence participant role exchange, and a small set of decision/trend antonyms. [Quantity normalization](../engine_runtime/quantities.py) now distinguishes recognized time units and Korean numeral one. The guards reject known drift; they do not prove full meaning equivalence. [Style findings](../src/engine/super-sejong.ts) are bounded, source-anchored model hints, never automatic replacement or a naturalness score. Their regex scan is bounded for long Hangul inputs and excludes protected textual regions.

The [Codex runner](../src/engine/codex-runner.ts) disables its tool surfaces for text transformation and executes in a disposable empty working directory. The [command runner](../src/process/command-runner.ts) caps combined CLI output. [Host validation](../src/network/private-address.ts) now rejects arbitrary DNS Host values in addition to the existing socket and Origin checks. The Express error handler and [Office routes](../src/documents/routes.ts) emit fixed public messages; known import failures have distinct stable codes. [Office package loading](../engine_runtime/documents/package.py) checks per-part and aggregate XML budgets during decompression. The desktop renderer/main import handshake commits a new source reference only after successful loading, preventing a failed import from leaving an incorrect save target. Text and Office completion counts reflect accepted output.

At the two-round review checkpoint: TypeScript typecheck passed; Vitest 420 passed/9 skipped; Python document tests 53 passed; Python skill tests 74 passed/4 skipped; browser E2E 54 passed/9 skipped; isolated Codex live fixture passed. The Windows-only desktop regression was added but cannot execute on macOS. The live fixture verifies a protected sample and cleanup, not a population-level naturalness improvement. Later benchmark-driven negation fixes have their own verification record and 20-post results in the [Codex handoff](HANDOFF-2026-10-04.md) and [benchmark report](reports/2026-10-03-super-sejong-blog-benchmark.md). See also the [two-round report](reports/2026-10-03-two-round-review.md), [English change plan](plans/2026-10-03-super-sejong-code-plan.md), and [research synthesis](research/super-sejong/RESEARCH-SYNTHESIS.md).

## 1. Architecture

The project provides a LAN web portal, a Windows Electron application and host-session Claude/Codex skills. The portal and desktop share TypeScript model runners and the text orchestration engine. Office documents use a separate block-editing pipeline. The skill Gateway receives edits from the current host session instead of invoking another model CLI.

```text
LAN browser -> Express routes -> shared transformation queue
Windows renderer -> trusted IPC -> Electron utility process
    -> text: Python preparation -> selected CLI -> restoration/fidelity checks
             -> retry/rollback -> reassembly -> full-document verification
    -> Office: Python package/block extraction -> selected CLI batch edits
               -> block validation/retry -> verified same-format export

Claude/Codex host session -> Gateway prepare/next/accept/finalize/cleanup
    -> host supplies rewritten text or block edits
    -> shared Python validation and optional/required local Node bridge
```

The frontend is plain JavaScript, HTML and CSS. The server uses strict TypeScript with NodeNext modules and Express 5. The Python engine is vendored; runtime execution does not require a sibling checkout. `package.json` declares Node `>=24.19.0`, but server preflight does not enforce it. Windows packages include Python; skill ZIPs also include Node.

## 2. Source Map

| Area | Sources | Responsibility |
| --- | --- | --- |
| Server/application | [server.ts](../src/server.ts), [app.ts](../src/app.ts) | Startup, address/Origin policy, health, requests/events and shutdown. |
| Runtime/readiness | [create-runtime.ts](../src/runtime/create-runtime.ts), [preflight.ts](../src/process/preflight.ts), [provider-health.ts](../src/runtime/provider-health.ts) | Construct both engines and independently probe installation/authentication. |
| Configuration/limits | [config.ts](../src/config.ts), [input-limits.ts](../src/engine/input-limits.ts) | Capacity, deadlines, paths and normalized input limits. |
| Models/strength | [model-policy.ts](../src/engine/model-policy.ts), [rewrite-policy.ts](../src/engine/rewrite-policy.ts) | Allowed model/effort pairs and direct-text editing scope. |
| Text orchestration | [humanize-engine.ts](../src/engine/humanize-engine.ts), [python-engine.ts](../src/engine/python-engine.ts) | Prepare, rewrite, restore, verify, retry, roll back, assemble and report diagnostics. |
| Text responses/guards | [text-edits.ts](../src/engine/text-edits.ts), [direct-text-fidelity.ts](../src/engine/direct-text-fidelity.ts), [candidate-review.ts](../src/engine/candidate-review.ts) | Exact anchors, structure/content checks, protected restoration and candidate review. |
| Super Sejong prototype | [super-sejong.ts](../src/engine/super-sejong.ts), [super_sejong.py](../engine_runtime/super_sejong.py), [quantities.py](../engine_runtime/quantities.py) | Source-anchored Korean style hypotheses and conservative semantic invariants shared by text/Office validation. |
| Providers/processes | [codex-runner.ts](../src/engine/codex-runner.ts), [claude-runner.ts](../src/engine/claude-runner.ts), [command-runner.ts](../src/process/command-runner.ts) | CLI flags, results, failure classification, deadlines and termination. |
| Queue/transport | [transform-queue.ts](../src/queue/transform-queue.ts), [request-body.ts](../src/transport/request-body.ts), [ndjson.ts](../src/transport/ndjson.ts) | Admission, UTF-8 reception and validated result delivery. |
| Office integration | [routes.ts](../src/documents/routes.ts), [artifact-store.ts](../src/documents/artifact-store.ts), [document-engine.ts](../src/documents/document-engine.ts) | Capability tokens, upload/download, retention/read leases and CLI orchestration. |
| Office editing | [package.py](../engine_runtime/documents/package.py), [model.py](../engine_runtime/documents/model.py), [workflow.py](../engine_runtime/documents/workflow.py) | ZIP/XML limits, extraction, edit contracts, preservation and export. |
| Desktop | [main.ts](../desktop/main.ts), [worker.ts](../desktop/worker.ts), [preferences.ts](../desktop/preferences.ts), [save-target.ts](../desktop/save-target.ts) | Trusted IPC, local processing/settings, dialogs and source-overwrite protection. |
| Browser | [app.js](../public/app.js), [transport.js](../public/transport.js), [document-file.js](../public/document-file.js), [text-file.js](../public/text-file.js) | Input/readiness, completion/cancellation, warnings and exports. |
| Comparison | [result-diff.js](../public/result-diff.js), [text-diff.js](../public/text-diff.js) | Direct-text comparison, final-text copying and bounded diff computation. |
| Host skills | [skill_gateway.py](../engine_runtime/skill_gateway.py), [skill_bridge.py](../engine_runtime/skill_bridge.py), [workflow.py](../engine_runtime/workflow.py), [skill-bridge.ts](../scripts/skill-bridge.ts) | File-based state, shared validation and host-provided edits. |
| Supervision | [hermes-service.ts](../src/ops/hermes-service.ts), [server-lock.ts](../src/runtime/server-lock.ts) | Desired state, process identity, serialized control and ownership/recovery. |

## 3. HTTP and Event Contract

| Request | Current behavior |
| --- | --- |
| `GET /` and static assets | Serve `public/` with security headers and no-store caching. |
| `GET /api/health` | Refresh cached preflight; return ready/degraded status, providers, model options/defaults, rewrite options, input limits and active/queued counts. Ready responses also query Office dependency availability. |
| `POST /api/transform` | Accept `text/plain`; query parameters choose `engine`, optional `model`/`effort` and optional `inputKind`/`strength`. Omitted engine defaults to Codex. |
| `POST /api/documents` | Receive raw DOCX/PPTX with URL-encoded `x-file-name`; return preview, block counts, ID and capability token. Selection uploads/parses Office but does not start an LLM rewrite. |
| `POST /api/documents/:id/transform` | Validate Bearer token and engine/model settings, reserve the shared queue and stream transformation events. |
| `GET /api/documents/:id/result` | Download the verified same-format result with its token; hold a read lease during transfer. |
| `DELETE /api/documents/:id` | Authorize removal, abort work and clean the owned artifact when work/read leases settle. |

All `/api` routes share an Origin check: supplied Origin must equal request protocol/Host; native clients without Origin remain permitted. Socket addresses must be loopback or recognized private IPv4/IPv6, and Host must be localhost or a literal allowed local/private IP. There is no application login or TLS listener.

Text rejection before streaming can use `400` for invalid settings, `413` for declared size, `415` for content type, `429` for capacity or `503` for readiness/shutdown. Office upload errors return `400`; transform rejection has its own structured codes and preserves the prepared record before acceptance.

Accepted transforms use NDJSON: `accepted`, `queued`, `progress`, `warning`, text `result-start`/`result-delta` or Office `document-result`, then `done` or `error`. HTTP `200` alone is not success. Text delivery begins after full verification, rather than exposing live model tokens. The common UI requires `done`, clears incomplete results on failure and preserves completed results after late cancellation/stream error.

Sources: [app.ts](../src/app.ts), [document routes](../src/documents/routes.ts), [contracts.ts](../src/contracts.ts), [browser event handling](../public/app.js).

## 4. Input Limits, Routing and Admission

| Setting | Current source behavior |
| --- | --- |
| Listen address/port | Default `0.0.0.0:7882`, overridable with `HOST`/`PORT`. |
| Portal/desktop direct text and TXT/MD | At most 100,000 Unicode code points after CR/CRLF-to-LF normalization. |
| Portal/desktop TXT/MD loading | At most 1 MiB, checked before reading; decoded length is also checked. |
| Text HTTP early rejection | Declared `Content-Length` above 400,000 bytes returns `413`; normalized character count is enforced while receiving other requests. |
| Office package | 50 MiB compressed, 250 MiB decompressed, 10 MiB per XML part, 10,000 ZIP entries. |
| Office extracted content | 100,000 characters, 200 PPTX slides; paragraphs over 9,000 characters are preserved. |
| Portal transform capacity | Three combined text-upload reservations, queued transforms and active transforms; one active job across providers/formats. |
| Office artifact capacity | Separately, three document records including prepared/completed documents. Upload/parsing uses this store, not a transformation-queue reservation. |
| Text chunk concurrency | One by default; two is an explicit experiment. The supervisor forces one. |
| Office batch concurrency | One. |
| Model/Python deadline | Ten minutes per CLI call; two minutes per normal Python/Gateway invocation. No total-document deadline. |
| Free-disk guard | At least 1 GiB before text reception or Office upload. |

TXT/MD decoding supports UTF-8/BOM, BOM-marked UTF-16LE/BE and CP949/EUC-KR fallback. BOM-less UTF-16 containing NULs is refused. TXT/MD selection is local in the browser; Office selection uploads the package for inspection.

Text preparation uses genre `essay`. With auto-routing enabled, up to 15,000 prepared code points and a `light`/`standard` diagnosis normally produce one body chunk; other inputs are split. Recognized trailing footnotes can pass through. Python code-point offsets are applied with `Array.from(source)`.

Office batches use approximately 7,000 source characters, 96 blocks and 48,000 serialized bytes. An eligible block exceeding a batch budget can run alone. Fully protected blocks are excluded from model calls.

The text size limits are enforced at portal/desktop entry points, not in the reusable text engine or host-session TXT/MD Gateway. Office package limits apply in the skill path too.

Sources: [limits](../src/engine/input-limits.ts), [body reception](../src/transport/request-body.ts), [queue](../src/queue/transform-queue.ts), [artifact store](../src/documents/artifact-store.ts), [Office extraction](../engine_runtime/documents/model.py), [skill preparation](../engine_runtime/skill_gateway.py).

## 5. Text Rewrite and Preservation

1. Prepare/sanitize input and validate manifest coverage against the prepared source.
2. Request exact unique source-phrase replacements or full rewritten text. Local parsing sorts anchors and rejects overlap, ambiguity and mixed response forms. Direct-text very-strong first attempts request full text.
3. Align outer whitespace. For very-strong direct text, restore a protected sentence whose protected elements changed, only when mechanical correspondence can be established.
4. Restore identifiable lost modality and remove injected connective commas. Ambiguous restoration is reported instead of guessed.
5. Run JavaScript fidelity checks and the common Python verification wrapper.
6. Retry at most once for unusable successful model output, fidelity violations or a retry gate decision. A second unusable/aborting response or unresolved fidelity violation restores the chunk; a second warning can be accepted with review advice.
7. Reassemble strictly. A direct-text full-document fidelity violation restores the prepared full source before final Python verification. Final abort/error fails; a warning allows delivery with review advice.

Direct-text guards preserve line layout, Markdown markers/headings, sentence counts/order and recognized concepts. Protected sentences (numbers, quotations, modality, negation, conditions, multiple explicit subjects) may be rephrased only when their numbers (in order), quotation marks and modality/negation/condition markers survive unchanged; sentences with several explicit subjects stay verbatim. Newly introduced protected meaning is rejected. These are lexical/structural heuristics, not semantic-equivalence proof.

TXT/MD and legacy requests use structural checks for line layout, Markdown markers, prompt-boundary echo and duplicated source sentences. Sentence split/merge may be allowed by file-editing rules; Python additionally checks dropped content. Direct-text sentence-count/strength policy does not apply to files.

The production wrapper in `engine_runtime/workflow.py` upgrades recognized quote, heading, footnote, number injection/loss, signed quantity, Latin/Hanja name-set and sentence-drop failures to abort. Upstream advisory fact checks therefore do not describe the application's final policy. Character change rate still warns at 30% and aborts at 50%.

A `P1_STYLE_TARGET` warning on its own is advisory: `workflow.verify` returns exit 0 with `advisoryReasons: ["P1_STYLE_TARGET"]`, because P1 compares comma metrics with placeholder baselines and warned on most unchanged human text. P1 together with any other warning or hard failure still retries. The very-strong candidate review, which only ran on P1-only warnings, is therefore no longer reached through the real gate.

CLI execution failure, model rejection and timeout fail the job. If every text body chunk returns unusable output on both attempts, the job fails with `ENGINE_OUTPUT_INVALID` rather than reporting source-only success.

Sources: [orchestration](../src/engine/humanize-engine.ts), [fidelity](../src/engine/direct-text-fidelity.ts), [shared verification](../engine_runtime/workflow.py), [candidate review](../src/engine/candidate-review.ts).

## 6. Office Editing and Host Skills

DOCX/PPTX are validated ZIP/XML packages. Supported body paragraphs, table cells and text shapes become identified blocks. Original XML paths and style identities remain local; the model receives text and editing constraints rather than permission to modify the package directly.

Response v2 uses ordered `reviewedIds` plus changed blocks with exact source anchors; v1 remains readable. The adapter validates document/batch/block identity, exact source, nonoverlapping edits, formatting/control boundaries, protected spans, valid XML characters, length, modality/negation, signed quantities and a 50% paragraph-change ceiling. Invalid block edits cause one batch retry, then source preservation for unresolved blocks. Malformed batch identity/response fails rather than following ordinary block retry.

Export modifies approved text nodes, preserves untouched package parts byte for byte, compares changed XML after restoring allowed text/space attributes, and re-extracts output to check block/text correspondence. A new output path is published exclusively/atomically. Headers, footers, notes, masters, charts, SmartArt, equations and unsupported objects are preserved rather than rewritten. This does not prove identical rendered pagination or slide layout.

The host Gateway follows `prepare -> next/accept -> finalize -> cleanup`, checks source/manifest hashes and operation ownership, and never calls an LLM itself. Direct text requires the Node bridge for shared policy/fidelity/HTML comparison. TXT/MD works without Node; the JavaScript structural guard is conditional on bridge availability, while Python checks remain active. Office uses the common Python adapter.

Finalization differs: portal/desktop direct text can restore the entire prepared source on full fidelity failure; skill direct text refuses export on that failure. The paths share rules but do not have identical recovery behavior.

Sources: [Office model/export](../engine_runtime/documents/model.py), [Office workflow](../engine_runtime/documents/workflow.py), [skill Gateway](../engine_runtime/skill_gateway.py), [bridge](../engine_runtime/skill_bridge.py).

## 7. Providers, Readiness and Lifecycle

| Policy | Codex | Claude |
| --- | --- | --- |
| Source default | `gpt-5.6-sol` / `medium` | `claude-fable-5-1` / `high` |
| Configured IDs | `gpt-5.6-sol`, `gpt-6-astra`, `gpt-6-sol`, `gpt-6-luna`, `gpt-5.6-terra`, `gpt-5.6-luna` | `claude-fable-5-1`, `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-sonnet-5`, `claude-opus-5` |
| CLI mode | Ephemeral exec, ignore user config/rules, read-only sandbox, schema/final-message file | Restricted print mode, strict MCP config, no tools/session persistence, JSON schema/envelope |
| Readiness | Version command, parsed Codex 0.x minimum 0.149, login status | Version command, auth status with `loggedIn: true` |

This is the application's allowlist, not independently verified provider access. Codex effort options reach ultra except Luna entries, which stop at max; Claude stops at max. Validated settings reach initial calls and retries. Skill model choice belongs to the host session.

Shared preflight requires Python 3.11+ and engine label `2.3.2`; either ready provider makes the runtime ready. Claude no longer depends on Codex login. Health refresh has a three-second cache and in-flight deduplication. Visible idle UI polls every 60 seconds, refreshes on visibility/manual action and rechecks relevant execution errors. Transform routes use cached readiness instead of probing each request.

Prompts travel over stdin with randomized source boundaries and `shell: false`. The process runner tracks children and kills process trees on timeout/cancel and normal exit cleanup. Shutdown starts listener closure, aborts queue/document work before waiting for connections, cleans jobs and releases the lock; forced exit is bounded by 15 seconds. Supervisor forced SIGKILL first kills known server child groups; arbitrary external SIGKILL cannot run exit hooks.

Server ownership uses atomic lock publication and boot-aware identity. Supervisor controls serialize operations and verify process/health identity. `watch` reconciles once and attempts recovery after three failed observations; recurring execution needs an external scheduler. A responsive degraded service is reported as degraded rather than restarted to repair authentication.

Sources: [models](../src/engine/model-policy.ts), [runtime](../src/runtime/create-runtime.ts), [probes](../src/runtime/provider-health.ts), [process runner](../src/process/command-runner.ts), [shutdown](../src/server.ts), [supervisor](../src/ops/hermes-service.ts).

## 8. Storage, Diagnostics and UI

Text source/intermediate/result files live in private workspaces until normal completion/failure/cancellation cleanup. Office artifacts/Python jobs remain for an idle 30-minute lifetime to support repeated saving; active work/read leases defer removal. Startup clears stale server jobs, and desktop/store initialization clears owned old jobs. Portal queues/indexes are in memory and do not resume after restart.

Transformation logs contain metadata and fixed failure reasons, not intentionally source/result bodies. CLI streams have a combined output budget; captured text and Python details remain transient. Desktop settings persist CLI paths and explicit engine/model/effort/strength choices without document history. Skill jobs remain until cleanup; host conversation retention is governed by the host.

Browser warnings remain in a deduplicated panel and affect the completion label. Direct-text diff uses the final verified output; copy/export excludes displayed deletions. Diff operation/time/node budgets may produce a coarse whole replacement. File input lacks strength/comparison. Editing loaded TXT/MD clears metadata and makes the next job direct text.

Electron disables renderer Node integration, enables context isolation/sandbox, denies navigation/new windows and checks IPC sender/frame. Local processing uses a utility worker, not an HTTP server. Native saves reject the opened source path; Office saves hold a read lease through the dialog/copy.

## 9. Current Static Findings and Limits

These observations were first recorded on October 2. The rows below show their disposition after the October 3 review and fixes.

| Observation | Evidence and implication |
| --- | --- |
| Windows setup requires Codex | [setup-portal.cmd](../setup-portal.cmd) checks Codex presence/login despite Claude-only runtime support. Setup has stricter prerequisites than runtime. |
| Health omits capacity/retention state | [app.ts](../src/app.ts) exposes active/queued transforms, not upload reservations or Office records/imports/readers. Zero displayed jobs is not a complete maintenance-idle check. |
| Health timestamp is response time | [runtime](../src/runtime/create-runtime.ts) can reuse a probe for three seconds while [app.ts](../src/app.ts) stamps a new `checkedAt`. API-only transforms also use cached readiness until refreshed. |
| Readiness does not prove model access | [probes](../src/runtime/provider-health.ts) do not infer with all models and have no Claude model-specific minimum-version gate. Recognized runtime rejection becomes `MODEL_UNAVAILABLE`. |
| Office output count corrected | [Office workflow](../engine_runtime/documents/workflow.py) computes accepted edit length; [routes](../src/documents/routes.ts) and [desktop worker](../desktop/worker.ts) use it in completion events. |
| Resource bounds remain partial | There is no total-job deadline; [command-runner.ts](../src/process/command-runner.ts) now caps combined CLI output. Skill TXT/MD has no shared-server input cap. |
| Network scope remains address-based | Private socket, literal Host and Origin checks do not establish same-Wi-Fi membership or user identity. Proxy deployment still needs a deliberate trust policy. |
| Preservation is heuristic | Number/name/quantity sets and sentence alignment do not prove all subject/value associations or arbitrary Korean-name/meaning preservation. Literal direct-text/Office protection reduces some risks. |
| Skill guards depend on bridge | Python-only TXT/MD omits the optional JavaScript structure check, and skill direct-text finalization differs from app rollback. Package/bridge freshness is separate from source freshness. |
| Version labels do not identify artifacts | Later fixes retain `0.4.0`/`2.3.2`. Source commits and build metadata/hashes are needed to identify deployed/installed code. |

The old findings about startup-only health, shared Codex readiness, disappearing warnings, unchecked stream completion, shutdown ordering and unrestricted portal text size are superseded. Detailed gate reasons are still reduced in aggregate logs, but direct-text diagnostics now include skipped restorations, protected sentences, fidelity restrictions and rollback counts.

## 10. Evidence Boundary

The repository contains Vitest unit/integration, Python document/skill, browser and Electron suites. [CI](../.github/workflows/ci.yml) runs on Windows with Node 24/Python 3.12 and invokes typecheck, main tests, build and browser tests. Dedicated document/skill/desktop commands exist but are not separately invoked by that workflow.

September 30/October 2 results are historical records in [works-log.md](../works-log.md). Earlier [speed measurements](research/2026-09-09-speed-loop-results.md) and [strength baseline](research/2026-09-10-strength-live-evaluation.md) retain their dates/models/caveats and are not fresh verification.

The October 3 review included code fixes, automated suites, browser E2E, and two isolated live Codex samples. These establish behavior for tested inputs, not running production readiness, compiled-artifact equality, installed-skill freshness, population-level Korean quality, or performance across hosts. Product interpretation and historical deployment context are in [Service Analysis](service-analysis.md).
