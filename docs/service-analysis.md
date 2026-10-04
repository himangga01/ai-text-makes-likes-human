# Service Analysis

Baseline analysis: October 2, 2026 (Asia/Seoul). Reviewed and updated: October 3, 2026.

Inspected source revision: `d9df30ee495b1e97764410e16785c245d77d25ff` on `main`. Application version: `0.4.0`; Humanize label: `2.3.2`, pinned commit `9747f036cdc28a1a8aea4dc71fef1f7846eb96f7`.

The body below records the October 2 source at `d9df30e`; the October 3 addendum records the reviewed working tree. Product-fit statements remain implementation-based inferences, not customer research. The October 2 pass ran no tests; the October 3 pass ran automated and live-fixture checks. The September 5 analysis of `2ada4fb` is superseded.

## October 3 service review addendum

The portal now requires a localhost or literal private-IP Host as well as the existing socket and Origin checks. DNS and mDNS names are unsupported. This limits exposure but remains a network trust boundary, not user authentication. Codex text runs with its tool features disabled inside a disposable working directory; model-supplied warnings no longer appear verbatim in user-facing events. CLI output and Office XML decompression have explicit budgets. Import failures distinguish known size, protection, format, capacity, and disk conditions with fixed messages; unexpected internals are concealed.

The user-visible Office character count now follows accepted edit length; import source state is committed after a successful desktop load. These address concrete misleading progress and incorrect save-target scenarios found in review. The Super Sejong prototype contributes conservative meaning checks in TXT/MD and Office, plus bounded source-position style hints for model attention. It does not yet include a shipped morphology model, learned naturalness scorer, genre detector, or human-evaluated Korean-quality guarantee. The 14-axis [research synthesis](research/super-sejong/RESEARCH-SYNTHESIS.md) and [review report](reports/2026-10-03-two-round-review.md) separate the implemented rules from untested hypotheses. Isolated live Codex samples, the browser E2E suite, and automated suites passed on this host; the Windows-only desktop regression still requires Windows CI.

A later [20-post paired benchmark](reports/2026-10-03-super-sejong-blog-benchmark.md) found 17 final edits in each arm and a style finding in only one source. It documents an ablation of the current service, not an older release, and does not establish a naturalness or speed advantage. The [Codex handoff](HANDOFF-2026-10-04.md) records the later negation correction, verification checkpoint, and uncommitted workspace state.

## 1. Service Purpose and Practical Fit

HumanizeKR revises Korean prose while trying to preserve facts, assertions, numbers, names, quotations, structure and register. Its main practical value is the combined workflow: editing rules, provider choice, preservation checks, controlled retries/source restoration, review warnings and usable exports.

Office support makes reports, proposals and presentations plausible use cases. The implemented model fits individuals with existing model accounts and small trusted teams. CLI installation/login remains a prerequisite and a potential onboarding barrier. The portal has no user accounts, billing, database, durable document history or resumable external job service.

Sources: [README](../README.md), [Code Analysis](code-analysis.md), [Office support](documents.md).

## 2. Three Usage Surfaces

| Surface | Execution/prerequisites | User experience |
| --- | --- | --- |
| LAN portal | Node/Python server and an installed/authenticated supported CLI; visitors share the server owner's selected provider account. | Browser input, shared queue/progress, cancellation, text copy/Markdown download and Office download. |
| Windows app | Electron/Python bundled; native Claude or Codex CLI already installed/authenticated. | Local IPC worker, native dialogs/settings, TXT/MD/Office saves; no LAN server required. |
| Claude/Codex skill | Current host session supplies edits; Windows packaged Python/Node or suitable source runtime. | Gateway-driven workflow, new verified output file and optional direct-text comparison HTML; no nested model CLI. |

Runtime preflight permits either provider independently. The Windows `setup-portal.cmd` helper still requires Codex installation/login, so its normal setup path is stricter than the Claude-only runtime.

The source allowlist contains six Codex and five Claude model IDs. Defaults are `gpt-5.6-sol`/`medium` and `claude-fable-5-1`/`high`. These are selectable source settings, not account-access guarantees. Skills use the host's model instead of the application menu.

Sources: [preflight](../src/process/preflight.ts), [setup helper](../setup-portal.cmd), [model policy](../src/engine/model-policy.ts), [desktop guide](desktop.md), [skill guide](skills-guide.md).

## 3. Input and Result Experience

| Input | Controls/result | Portal/desktop limits |
| --- | --- | --- |
| Typed/pasted text | Four strengths, final-text comparison/copy, desktop text save. | 100,000 normalized Unicode code points. |
| TXT/MD | Preview/encoding, normal file-editing policy without strength/comparison; browser MD download, desktop TXT/MD save. | 1 MiB file and 100,000 normalized code points. |
| DOCX/PPTX | Location-based block preview/counts/warnings and new verified same-format file. | 50 MiB package, 100,000 extracted characters, 200 PPTX slides plus ZIP/XML limits. |

TXT/MD decoding supports UTF-8/BOM, BOM-marked UTF-16 and CP949/EUC-KR. Browser selection is local. Office selection uploads/parses the package for preview; LLM rewriting still requires the transform button. The Office preview is not a rendered page/slide.

Direct-text comparison shows yellow insertions/changes and red strike-through deletions; final view/copy/export uses only the final verified text. Large differences may be shown as coarse replacements within the diff budget. File inputs lack these controls. Editing loaded TXT/MD clears metadata, changing the next job to direct text and affecting export eligibility.

Users see queue position, stage/work-unit progress and elapsed time, not an estimated completion time. Warnings remain in a deduplicated panel and affect the completion label. A missing `done` fails the operation; late cancellation after `done` preserves the result.

Sources: [browser workflow](../public/app.js), [text loading](../public/text-file.js), [Office transport](../public/document-file.js), [comparison](../public/result-diff.js).

## 4. Quality Policy and Tradeoffs

Both providers share text orchestration: prepare input, apply a structured response, restore lost identifiable modality, remove injected commas, check fidelity/preservation, retry at most once, then reassemble and verify the full document before delivery.

Direct text uses strict sentence/paragraph/heading/concept guards and literal preservation for recognized factual, quotation, modality and condition-bearing sentences. TXT/MD has a different policy: sentence splitting/merging may be allowed, with layout/Markdown/duplication checks and Python sentence-drop detection. The shared wrapper treats recognized factual failures such as changed quantities, missing numbers or altered quotations as hard failures. Character-change warning/abort thresholds remain 30%/50%.

Office edits stay within approved text ranges and original structure. Numeric/entity-bearing sentences, quotations, fields and unsupported structures may make blocks partly or fully immutable. Invalid block edits cause one retry, then source preservation if unresolved. Export checks unchanged package parts and changed XML/text correspondence, but does not prove identical Word pagination or PowerPoint layout.

The tradeoff is conservative editing: strength changes the permitted editing scope, without guaranteeing visible change amount. A completed result can contain preserved regions/review warnings. CLI failure and timeout are failures rather than preservation outcomes.

Very-strong candidate review is restricted to a fidelity-passing first draft with only a recognized style warning, followed by a real second call. Validation remains heuristic and cannot prove all semantic equivalence, arbitrary Korean-name preservation or subject/value associations.

Skills share major checks but not identical recovery in every environment. Python-only TXT/MD lacks the optional JavaScript structural guard; direct-text skill finalization rejects whole-document fidelity failure instead of the app's full-source restoration.

Sources: [text engine](../src/engine/humanize-engine.ts), [shared verification](../engine_runtime/workflow.py), [Office validation](../engine_runtime/documents/model.py), [skill Gateway](../engine_runtime/skill_gateway.py).

## 5. Capacity, Latency and Failures

The portal accepts three combined text-upload reservations, queued transformations and active transformations. One transform runs at a time across providers/formats. Office upload/preparation occupies a separate store of three records; completed documents occupy it until removal/expiry.

Text auto-routing normally uses one body chunk for up to 15,000 prepared code points with light/standard diagnosis; other inputs are split. Text concurrency defaults to one and the supervisor forces one; two is experimental. Office batches are serial. Each text body chunk can require two model calls; Office retries also add calls. There is no automatic provider fallback during a failing job or total-document deadline.

| Condition | Current source behavior |
| --- | --- |
| Shared Python/engine prerequisites fail or neither CLI is ready | Degraded health; transformations unavailable. |
| One provider unavailable | The other can run when shared prerequisites are ready. |
| Model/effort outside the allowlist | Pre-admission `INVALID_MODEL_SETTINGS`. |
| Runtime rejects a model | Recognized errors become `MODEL_UNAVAILABLE`. |
| Transform capacity full / server shutting down | `429 QUEUE_FULL` / `503 SERVER_SHUTDOWN`. |
| Text exceeds entry-point cap | `INPUT_TOO_LARGE`; declared bodies over 400,000 bytes receive early `413`. |
| CLI failure or timeout | `ENGINE_FAILED` or `ENGINE_TIMEOUT`; no false source-only success. |
| Successful text calls provide unusable edits | One retry, then chunk rollback; all chunks unusable twice fails the job. |
| Text preservation fails | Retry/restore as appropriate; final Python abort/error prevents successful output. |
| Office fails after acceptance | Temporary record removed; reselect the file. Pre-admission rejection keeps prepared input. |
| Browser cancels/disconnects | Abort active work, release reservation and attempt owned-workspace cleanup. |
| Server restart | In-memory queue/index lost; stale jobs cleaned; no automatic job resumption. |

Readiness checks installation/authentication, not inference with every model. Health refresh is cached for three seconds; the visible idle UI polls every 60 seconds and supports manual/visibility/error rechecks. Active/queued counters omit upload reservations and retained Office records, so they are not a complete maintenance-idle signal.

Historical records show performance improvements for specific inputs. The September 30 work log reports a realistic 100,000-character validation check falling from 73.4 seconds to 0.9 seconds after removal of a quadratic bottleneck. This is validation-step timing, not total transformation latency. September 9 speed results and the September 10 pre-fix strength baseline retain their model/input caveats and were not rerun here.

Sources: [config](../src/config.ts), [queue](../src/queue/transform-queue.ts), [artifacts](../src/documents/artifact-store.ts), [work log](../works-log.md), [speed evidence](research/2026-09-09-speed-loop-results.md), [strength evidence](research/2026-09-10-strength-live-evaluation.md).

## 6. Access, Data Flow and Retention

The portal permits loopback/private socket addresses, restricts Host to localhost or allowed local/private IP literals, and compares supplied browser Origin with protocol/Host. This is address-based scope, not user authentication or proof of same-Wi-Fi membership. There is no application TLS, per-user quota or account separation. A proxy changes the visible socket address and needs a deliberate trust policy.

| Data | Lifetime/scope |
| --- | --- |
| Portal/desktop text jobs | Local source/intermediate/final files until normal completion/failure/cancellation cleanup. |
| Office input/result | Package copies and Python jobs retained for an idle 30-minute lifetime; active work/read leases protect ongoing processing/saving. Repeated downloads are possible before expiry. |
| Portal logs | Transform metadata, counts/timings/codes and fixed CLI failure reasons; no intentional source/result-body logging. |
| Desktop settings | Persistent CLI paths and engine/model/effort/strength, without document history. |
| Skill jobs/results | Gateway jobs until cleanup; exported results preserved; host conversation retention follows host settings. |

Startup clears stale server jobs; desktop/Office cleanup targets owned work. Codex ephemeral execution and Claude session-persistence flags describe local CLI behavior, not remote provider retention. Text is sent to the selected provider and is not processed entirely offline.

Sources: [text lifecycle](../src/app.ts), [Office retention](../src/documents/artifact-store.ts), [desktop worker](../desktop/worker.ts), [Codex runner](../src/engine/codex-runner.ts), [Claude runner](../src/engine/claude-runner.ts), [skill workflow](../skills/humanize-kr/references/workflow.md).

## 7. Operations and Distribution State

Windows portal helpers and a macOS supervisor are provided. The supervisor records desired state, serializes control, verifies process/health PID, and supports start/stop/restart/status/watch/logs. Watch reconciles once; periodic execution needs an external scheduler. A responsive degraded CLI state is reported rather than repaired by restarting.

| Historical record | What that record establishes |
| --- | --- |
| September 30, `2389733` | Review fixes integrated on main, built/restarted, with selected CLI smoke and readiness records. |
| October 2, `d9df30e` | Text limits built/deployed; health limits, oversized-request rejection and a short Claude request recorded. |
| This documentation update | Current source inspected and documents updated; no deployment/runtime check. |

Those are historical entries in [works-log.md](../works-log.md), not current live observations. Source, compiled `dist/`, EXE, ZIP and installed skill may have different update dates. Unchanged `0.4.0`/`2.3.2` labels do not establish equal code; source commits and package build metadata/hashes identify artifacts. Installed packages were not inspected/rebuilt in this task.

See [operations.md](operations.md) for controls/recovery and [desktop.md](desktop.md) for distribution prerequisites.

## 8. Improvement Priorities Inferred from Source

1. Make source/package/deployment identity explicit instead of relying on unchanged version labels.
2. Explain preserved regions, warnings and input-mode differences so users can understand conservative outcomes.
3. Address integration gaps if requested: setup's Codex dependency, incomplete health counters, Office output-count accounting and bridge-dependent skill checks. They are documented observations, not fixes or new reproduction results.
4. If usage extends beyond a trusted small team, reassess shared-account admission, long-job waiting, total-job budgets, authentication and durable recovery.

[Code Analysis](code-analysis.md) details current findings and superseded September 5 issues. Historical passing tests and sample calls are dated evidence; they do not establish current test status, quality, latency, account access or live deployment state for this documentation-only task.
