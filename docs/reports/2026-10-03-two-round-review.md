# Two-Round Code and Service Review — 3 October 2026

Scope: the LAN portal, desktop app, TXT/MD and Office pipelines, model runners, runtime/supervision, user-visible failure paths, and the new Super Sejong prototype. Reviewers examined security/privacy, semantic fidelity, reliability, tests, product behavior, and research fit in two adversarial rounds. The main session reproduced actionable findings and applied the fixes. This record describes the working tree; it is not a deployment or production incident report.

## Round 1: accepted findings and changes

| Finding confirmed in code or a failing test | Change |
| --- | --- |
| Model-runner tool access, untrusted warning text, unbounded CLI output | Disabled Codex tool features for transformation, used an empty disposable working directory, replaced raw model warnings with fixed notices, capped combined process output. |
| Arbitrary DNS Host combined with a valid-looking Origin, and detailed server error leakage | Restricted Host to localhost/private IP literals; added fixed Express and Office public errors. |
| Office ZIP parts could consume too much parser memory | Applied per-part and aggregate XML limits during streaming decompression. |
| A failed desktop import could leave the previous source paired with the wrong save target | Added a successful-import acknowledgment before committing a new source reference, plus reset clearing. |
| TXT/MD and Office accepted lost sentences, negation changes, obligation movement, or participant-role changes | Added conservative Super Sejong semantic guards and regression contrasts. |
| Office completion used source character count despite accepted edits | Computes output length from accepted edits and reports it through the service and desktop. |
| Windows CI helper depended on a logged-in Codex CLI | Replaced the test's external authentication dependency with a local command stub. |

The interrupted Codex session had already introduced `/api/status` and an Office preview character-count fix. Those changes were retained and included in review. A text-request abort/error ordering regression was also corrected and unit tested; a full unfinished-chunked-HTTP reproduction remains unproven.

## Round 2: challenges to the first fixes

The second pass found both missed semantic changes and overblocking. The main session reproduced `안 먹고` losing or moving its negation, `한 시간` changing to `한 분`, `세 달` to `세 주`, two people exchanging subject/object roles, possibility moving between projects, and selected approval/trend antonyms. It also reproduced erroneous rejection of `민수는` → `민수가` and `한 시간` → `1시간`. Targeted guards now distinguish those cases, while acknowledging that regexes and a two-pair antonym list cannot ensure general equivalence.

A separate reviewer demonstrated quadratic synchronous time in the initial TypeScript Hangul style regex on long unmatched text. Bounded patterns and a 50,000-character no-match regression now keep that path short. Generic `자료를 통해` was removed as a presumed style problem; inline code and quoted literals are excluded. Another reviewer showed that the first Office XML budget was checked only *after* materializing a whole ZIP member; the check now occurs as chunks are read. Office import failures now keep actionable public categories without exposing internal paths. README and service documentation now state the literal-IP Host policy. The polarity research report was recalculated after the runtime changed.

## Verification and limits

At the end of these two review rounds on this host: TypeScript typecheck passed; Vitest 420 passed and 9 skipped; Python document tests 53 passed; Python skill tests 74 passed and 4 skipped; browser E2E 54 passed and 9 skipped; an isolated live Codex fixture passed and cleaned its workspace. A second isolated live sample changed `자료를 검토하는 과정에서 오류를 발견했다.` to `자료를 검토하다가 오류를 발견했다.`, retained the following sentence, received two `GATE_OK` results, and left no runtime children. The first browser E2E run exposed a stale assertion for the old Office error message; it passed after the assertion was updated and the full suite reran. The first live-fixture attempt used the managed runtime directory and failed its cleanup assertion because other service directories already existed; rerunning in an isolated runtime passed. The Windows desktop save-target regression was authored but cannot run on macOS. These are the **Round 2 checkpoint** counts; the subsequent benchmark exposed a negation miss and added tests, whose later verification is recorded in the [handoff](../HANDOFF-2026-10-04.md). These checks validate specific paths and contrasts, not an overall Korean naturalness improvement or complete semantic equivalence.

Research output: 14 axis reports and four executable probes under [Super Sejong research](../research/super-sejong/RESEARCH-SYNTHESIS.md). The C probe reproduced its 14 designed sentence spans with Kiwi; the K 36-case probe remains an in-sample feasibility comparison. Neither result is a production accuracy estimate. Blind native-reader and licensed-corpus evaluation are still required before claiming a measurable naturalness gain.
