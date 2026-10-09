# Works Log

## 2026-10-09 — Codex default effort lowered to high

**Request (user):** "코덱스는 high로 낮춰줘", after the report that GPT-6.1 Sol at xhigh took 278 s per call on a 2,332-char sample.

- `HUMANIZE_REASONING_EFFORT` `xhigh` → `high`. The Codex default is now `gpt-6.1-sol`/`high`; Claude stays `claude-opus-5-5`/`xhigh`. Same places as the previous change: `public/app.js` fallback, the static Codex effort `<option>` in `public/index.html`, README, `docs/operations.md`, `docs/code-analysis.md`, `docs/service-analysis.md`, and the unit, integration and e2e assertions.
- The owner's uncommitted blog-host policy lines (Codex `gpt-6.1-sol` xhigh fallback) are a separate Hermes policy and were not touched.
- Verification: build exit 0; vitest 739 passed / 9 skipped; Playwright e2e (side port 7899) 54 passed / 9 skipped.
- Same 2,332-char synthetic sample, one call with the production runner flags: `gpt-6.1-sol` high OK in **132,751 ms** (xhigh was 278,401 ms; the old default `gpt-5.6-sol`/medium ran real ~2,700-char jobs in 55–84 s for 2 calls).

## 2026-10-09 — Default models changed to GPT-6.1 Sol / Claude Opus 5.5, both at xhigh

**Request (user):** "기본 모델 변경, 코덱스는 지피티 6.1 솔 / 클로드는 오푸스 5.5 / 추론레벨은 둘다 xhigh", then "수정후 서버반영, 재시작, 깃에 커푸".

**What changed**
- `src/engine/model-policy.ts`: `HUMANIZE_MODEL` `gpt-5.6-sol` → `gpt-6.1-sol`, `HUMANIZE_REASONING_EFFORT` `medium` → `xhigh`; `CLAUDE_MODEL` `claude-fable-5-1` → `claude-opus-5-5`, `CLAUDE_REASONING_EFFORT` `high` → `xhigh`. The default model is listed first in each provider's options (GPT-5.6 Sol and Fable 5.1 move down). No model was added or removed.
- Pre-health fallbacks so the page never flashes the old defaults: `public/app.js` (`fallbackModelDefaults`, initial `modelOptions`) and the static `<option>`s in `public/index.html`.
- Docs: README (defaults; the benchmark note no longer claims the engine runs `medium`), `docs/operations.md`, `docs/code-analysis.md`, `docs/service-analysis.md` (counts were stale: now 7 Codex / 6 Claude).
- Tests: unit/integration assertions on the defaults and the Claude option order; e2e specs (`ui-state`, `ui-state-r2`, `local-model-defaults`). `local-model-defaults.spec.ts` had already been stale since the Haiku 5.5 commit `f84d388` (option list without Haiku); the e2e suite was not run for that commit, which is how it slipped. The A4 e2e case now seeds a saved `claude-fable-5-1`/`ultra` so it still tests a kept non-default model with an invalid effort.
- Saved user choices are unaffected: only explicit selections are stored, so users who never chose a model get the new defaults; explicit choices stay.

**Verification**
- Build exit 0; vitest 739 passed / 9 skipped (product venv as `PYTHON_COMMAND`); Playwright e2e on side port 7899 (`E2E_PORT=7899`, `PYTHON_COMMAND` set) 54 passed / 9 skipped. The first e2e attempt timed out because the side server's health was 503 ("Python 3.11 이상이 필요합니다") without `PYTHON_COMMAND`; the next run caught the stale static `<option>`s in `index.html`, fixed above.
- Live calls with the production runner flags and the legacy prompt, 527-char three-paragraph synthetic sample: `gpt-6.1-sol` xhigh OK in 191,705 ms; `claude-opus-5-5` xhigh OK in 54,074 ms.
- Latency: recent real codex jobs are one ~2,700-char chunk taking 55–84 s at `gpt-5.6-sol`/medium with 2 calls. After the deploy (restart PID 10842, `SUPER_SEJONG_V2_SHADOW=1` confirmed, `/api/health` serves the new `modelDefaults`), one call on a 2,332-char five-paragraph synthetic sample took **278,401 ms for `gpt-6.1-sol` xhigh** and **58,204 ms for `claude-opus-5-5` xhigh**, both OK. The per-call limit (`chunkTimeoutMs` 10 min) holds with about 2× margin, but a two-call Codex job of that size now takes roughly 8–10 minutes instead of about 1. Not changed: the timeout and the effort (the user chose xhigh).

## 2026-10-09 — Rewrite strength merged and deployed; GPT-6.1 Sol and Claude Haiku 5.5 added

**Request (user):** "깃 메인에 커밋푸쉬하고, 서버 반영 서버 재시작해, 그리고 최근데 코덱스랑 클로드 모델들이 새로 많이 추가됨 모델 업데이트들 해주고 수정되면 바로 서버반영 재시작해".

**Rewrite strength to main**
- Merged `sejong/wp19` into main as `374150d` (no-ff, on top of `259ad2c`); works-log commit `2a7c0e9`; pushed.
- The branch touched the three files that hold the owner's uncommitted personal lines (`docs/skills-guide.md`, `skills/humanize-kr/SKILL.md`, `skills/humanize-kr/references/workflow.md`). They were saved as a patch in the scratchpad, reset, the merge run, and the patch re-applied with `git apply --3way` (clean). They were then unstaged and stay uncommitted.
- Verification on main after the merge: `npm run build` exit 0; vitest 739 passed / 9 skipped (with `PYTHON_COMMAND` set to the product venv; with the default lookup it is 728 / 20 because the Office suites skip without lxml); skills and documents Python suites OK under both `SUPER_SEJONG_ENGINE=legacy` and `v2`.
- Restart (idle pre-check, 0 active / 0 queued): `SUPER_SEJONG_V2_SHADOW=1 … hermes-service.js restart` → `restarted`, PID 87874, `ready`; the flag is present in the process environment. `/api/health` lists the fifth option `rewrite` / "매우 강하게(다시쓰기)". The live engine stays legacy, where `rewrite` runs as 매우 강하게.

**Model audit (both providers, official sources)**
- Codex: `codex debug models` under codex-cli 0.161.0 lists a new visible model `gpt-6.1-sol` (priority 1, "Latest workhorse model", efforts low..ultra). `gpt-6-sol` is now "Previous generation", `gpt-5.6-sol` "Older generation". `gpt-5.5` (hidden) points its upgrade at `gpt-6.1-sol` and retires 2026-10-14 19:00 UTC. learn.chatgpt.com/docs/models recommends Astra, 6.1 Sol and 6 Luna and still lists 6 Sol and the 5.6 family. The latest stable CLI is 0.162.0 (2026-10-08); its release notes add no models (the catalog is server-side). Nothing else to add or remove.
- Claude: code.claude.com/docs/en/model-config lists Haiku 5.5 (`claude-haiku-5-5`, low..max, needs Claude Code 2.1.293; installed 2.1.295), and the `haiku` alias moved to it in 2.1.293. Fable 5 (`claude-fable-5`) stays out, as before: saved Fable 5 selections are auto-moved to the `fable` alias since 2.1.257. Older 4.x models stay out.
- Change: `src/engine/model-policy.ts` adds `gpt-6.1-sol` (GPT-6.1 Sol, low..ultra) and `claude-haiku-5-5` (Claude Haiku 5.5, low..max). Codex now offers 7 models and Claude 6. Defaults are unchanged (`gpt-5.6-sol`/medium, `claude-fable-5-1`/high); switching the default to 6.1 Sol was not requested.
- `tests/unit/model-settings.test.ts`, `README.md` and `docs/code-analysis.md` updated.
- Live call with the production runner flags (built `dist` runners, 1-sentence sample, effort low): `gpt-6.1-sol` OK in 14,320 ms; `claude-haiku-5-5` OK in 7,199 ms. Both returned valid schema JSON.
- Tests: build exit 0; vitest 739 passed / 9 skipped.

## 2026-10-08 — Fifth strength "매우 강하게(다시쓰기)" (rewrite) built and verified on a branch

**Request (user):** "크게 다시 쓰기도 원하는데 … '매우 강하게(다시쓰기)' 옵션을 추가하자, 대신 말투나 어투는 전체흐름과 맞아야함". The user then chose a fifth option, not a replacement of 매우 강하게, with 말투 following each paragraph's dominant level, and asked: "다시쓰기 작업 끝나면 검증하고 보고해".

**Branch:** `sejong/wp19` (from main `328fca1`), commit `7ba99cb`. Local only: not merged, not pushed.

**What it does (WP-19 agent, Opus)**
- New strength `rewrite`, labelled "매우 강하게(다시쓰기)", in every place that enumerates strengths: UI, server options, skill bridge, Python plan and CLI, schemas, docs.
- v2 behaviour:
  - The writer rewrites the chunk paragraph by paragraph.
  - Python decides each paragraph: accept, one retry naming its violations, or revert to base(x).
  - Voice: each output sentence must use the paragraph's dominant source level; question and request counts are kept; -시-, humble forms, persona and CMC are checked by presence per paragraph.
  - Floor, meaning, CTA and norms stay strict.
  - `flow_transition_added`/`sentence_added` and `clarity_longer_sentence` are not enforced. The runaway guard is replaced by a per-paragraph length ratio of 0.5–1.8.
- Legacy runs `rewrite` exactly as very-strong. So until v2 is switched on, the new option rewrites no more than 매우 강하게.
- Agent-reported numbers:
  - Constructed pairs: 4/96 good paragraphs falsely blocked; the held-out set had 0/27. 41/42 damaged paragraphs caught.
  - Seed rewrite mode: invariants clean on 212/212 records; gold 91/92.
  - The four existing strengths are byte-identical to main: 848 plan/check outcomes, 1,260 legacy prompts, 688 v2 prompts, 1,353 parser results.

**Lead verification**
- Own trials (`$SP/r5/wp19-lead/lead_rewrite.py`, a 3-paragraph text: 해요체 / 합쇼체 / 해체 with ㅋㅋ):
  - The first run falsely blocked a good rewrite on two counts.
    - P3 `voice_discourse_dropped`: the lead's own rewrite had changed 진짜 to 정말, which the colloquial rule correctly blocks.
    - P1 `voice_mood`: a real voice.py bug. "5시에 끝나요." was classified as a question because of the -나요 ending.
  - After the fix, 9/9 behave as expected:
    - a good rewrite and a sentence split are accepted;
    - each damage is flagged only in its paragraph: number, 합쇼→해요 drift, deadline drop, -시- loss (caught as `cta_dropped`), ㅋㅋ/~ drop, 반말→존댓말, weekday change;
    - merged paragraphs make the reply unusable.
  - At attempt 2, a still-drifted P2 reverts alone while P1 and P3 keep their rewrite.
- Fixes in voice.py:
  - 나요/가요 followed by a period count as a statement only for verbs whose stem ends in 나 or 가 (끝나요, 만나요, 일어나요, 가요). 하나요 and 있나요 stay questions.
  - The first, broader version broke `test_voice_violations_are_rejected` (그 뒤에 연락하나요.) and was narrowed.
  - "…중 하나이다." is now 해라체; archaic -나이다 only counts with 옵/사오 (비옵나이다). This is the agent's reported bug.
  - Regression tests were added.
- Final suites on `7ba99cb`:
  - tsc clean.
  - vitest: 739 passed / 9 skipped.
  - skills: 709 OK / 5 skipped with the switch unset and with v2.
  - documents: 93 OK in both engines.
  - Seed: gold 91/92 (SSB-186 unfixed); invariants clean on 212 records.
  - Lead probe: 32/32 and 36/36. Fluency set: 2/40.

**Open / for the user**
- Deviations the agent chose (to review):
  - In a paragraph, a sentence that keeps one of the paragraph's own source endings may stay off the dominant level.
  - 해체 and 해라체 count as one level inside a casual paragraph.
  - -시- is checked by presence only, so 궁금하신 → 궁금한 passes if another -시- remains in the paragraph.
  - Line count per paragraph must match the source.
  - A paragraph over 2,200 chars is reverted without a retry.
- Not run: Playwright e2e and desktop, `verify-skill-packages.mjs`, the Windows .ps1 fixture, and real-model rewrite runs.
- `ENGINE_VERSION` was not bumped.

## 2026-10-08 (later) — v2 shadow recording, first real jobs: 6 shadow jobs, 5 real

**Correction:** the scheduled review below was right at 10:07, but the portal ran 5 real direct-text jobs around 13:34. The user asked "기록 모드 데이터 왜 아직도 1건이야? 진짜 1건임?", and the report was rerun at 20:14. There are now 196 `transform_complete` events, 6 of them with `v2ShadowCounts`, and every shadow job recorded successfully.

**The 5 real jobs** (counts only; all at strength `strong`, 749–2,721 chars):
- Legacy made 2 calls per job, each with 1 retry.
  - 2 jobs rolled their chunk back to the source.
  - 1 more delivered text identical to the source.
  - So in 3 of 5 jobs, two model calls changed nothing.
- v2's gate on the delivered text:
  - It would accept all 5.
  - 0 meaning, voice, CTA, flow or norm codes fired on legacy's real edits.
  - 10 sentences would be reverted, all as `collateral_edit`: 4/15 and 6/14 in the two shorter jobs that legacy actually edited.
  - These are scope differences, not false positives. Legacy rewrites broadly at `strong`, while v2's minimal-edit contract changes only requested sentences plus up to max(3, 10%) open-review nominations, and candidate mode allows no nominations.
- v2 would have requested 2 sentences in all, SSJ-LV1 and SSJ-LV3; legacy left the LV1 one unchanged. Four LEAVE findings were reported (BOILERPLATE_ANNOUNCE ×3, CAUSAL_LEAD).
- `ms_overhead`: 52–93 ms per job.

**Implication for the switch**
- No evidence so far that v2's checks block legitimate real edits (n = 5).
- v2's `strong`/`very-strong` would change far less than legacy's, because v2's strengths add request tiers and open review but no broader rewrite. If the owner relies on `strong` for heavier rewriting, the strength semantics need adjusting before a switch.
- Keep collecting; rerun the report after more jobs.

## 2026-10-08 — Scheduled review of the v2 shadow recording: no real jobs yet

**Request:** the reminder the user asked for on 2026-10-05 ("며칠 뒤 기록 모드 결과 정리해줘") fired. Instructions: summarise with `scripts/sejong-shadow-report.py`, check the server flag, log in English, no merge or restart.

**Server state**
- PID 80242, started Mon Oct 5 21:16:07; status ready, 0 active and 0 queued jobs.
- `SUPER_SEJONG_V2_SHADOW=1` is in the process environment.
- Supervisor state is `{desired: running, consecutiveFailures: 0}`, so no watchdog restart happened since.

**Shadow data**
- `scripts/sejong-shadow-report.py` found 1 shadow job out of 191 `transform_complete` events. That job is the 78-char smoke test of 2026-10-05.
- `runtime/hermes-service.log` was last written at Oct 5 21:16, the restart. No text job, failure or Office job has been logged since.
- The portal was not used between 2026-10-05 and 2026-10-08, so there is nothing to analyse: no check codes, request rules, recording failures or rejected-output patterns.
- The only data point is that one smoke job:
  - v2 would accept it.
  - 1 sentence would be reverted as `collateral_edit`.
  - Plan: one SSJ-LV3 SUGGEST request, which legacy had fixed, and one N01 deterministic fix.
  - Overhead 117 ms.

**Conclusion for the v2 switch**
- Shadow evidence is insufficient: n = 1, and that one was synthetic. It neither supports nor blocks a switch.
- The switch decision rests on the earlier offline and real-model evidence:
  - lead probe 32/32 and 36/36 against legacy 30/32 and 18/36;
  - Codex runs where v2 edited 5 of 5 texts, legacy 2 of 5;
  - seed gold 91/92.
- Options for the user:
  1. Keep shadow on and use the portal normally, then rerun the report after about 20 real jobs.
  2. Replay a fixed set of texts through the live portal to fill the shadow log. This needs explicit approval for the model calls.
  3. Switch to `SUPER_SEJONG_ENGINE=v2`, which can be reverted with one env change and a restart, and judge v2's own output directly.
- Nothing was changed. The report script and log are unchanged, and there was no merge, restart or commit.

## 2026-10-05 — Three code reviews of the Super Sejong v2 work, all findings fixed, merged into main

**Request (user):** "최신 코드 수정내용을 중점으로 코드 리뷰 3회 진행, 문제점이나 버그 찾아봐", then "리뷰 끝나면 전부 수정하고 메인 반영해". Before that, works-log.md was committed and pushed (`b173c8f`).

**Reviews** were read-only and ran in parallel over `b3bc384..HEAD` (65 commits, 170 files).

| Round | Scope | Agent | Severity of confirmed findings |
|---|---|---|---|
| 1 | v2 Python core and legacy guard hotfixes | Opus | 4 medium, 4 low |
| 2 | TypeScript, shadow hook, ops | Opus | none high or medium, 4 low |
| 3 | skill and Office paths, report script, docs | Sonnet | 1 medium-low, 4 low, doc mismatches |

- Round 2 verified that the shadow hook never changes delivered text: byte-identical on 7.5k and 30k-char runs, no text leak, abort-safe.
- Round 3 verified that legacy skill and Office output is unchanged with the switch unset.
- The lead re-ran the top findings before fixing: the legacy 실수 and 증거 같은 false positives on the live tree, and the weekday spacing false positive.

**Fixes** (`495a394`, fast-forwarded into main `b173c8f` → `495a394`; not pushed; no restart)
- **Legacy guard (live as soon as merged, because the Python is read per job):**
  - 실수/말수/술수/철수 as whole words, and 일수 followed by a particle, are not the bound noun 수.
  - 거 같다 is the hedge only after an attributive ending, never 근거/증거/과거/이거.
  - Verified on the live tree: 실수가 없도록 → 실수하지 않도록 and 확실한 증거 같은 게 → 증거가 now exit 0. 신청하실수 → 신청하실 수 and 맞는 거 같아 → 것 같아 still exit 0.
- **v2 Python:**
  - Weekday extraction is symmetric (attached forms, bare lists, a single-letter parenthesis only after a date), with lists capped at 7. "월, " × 32000 now takes 0.007 s; it took 29.5 s before.
  - Key words carried by a remaining word count as no drop. Six 겹말 fixes pass, and B18/B35 are still caught.
  - Permission 그래도 is not contrast. An option-form question is not a CTA. A connective moved to the front is not counted as added; the T5 mutation 'add 먼저' is still caught.
  - -자면 skips only discourse frames. 가지고 있지는 않다 counts as negated. 연락이 끊기다 is no longer requested.
  - Support verbs are licensed only after meaning-carrying objects. 거→것 counts only where the source had 거 같다.
  - check keeps the source when the floor ladder had to fall back to it.
- **TypeScript and ops:**
  - The desktop package bundles the v2 response schema.
  - Rollback warnings name the reason.
  - A Python crash (exit 1 with no report or JSON) maps to `VALIDATION_FAILED`.
  - The shadow verdict follows the gate policy, so an attempt-1 exit 2 counts as a retry. Chunks left past the deadline become `chunks_skipped`.
  - The plan file name is read from the manifest.
- **Office:**
  - Only the over-budget edits are dropped; the requested fix stays.
  - A job pins its `SUPER_SEJONG_*` flags at prepare (`sejongEnv`; the pin is scoped to each dispatch call).
  - Skipped batches get a notice.
- **Skill gateway:** clearer Node-bridge, engine-pin and no-edit messages.
- **Report script:**
  - Verdicts follow policy; medians are consistent; step failures, gate exits, finding rules and `other_keys` are shown; no "None".
  - New `tests/skills/test_sejong_shadow_report.py`.
- **README and operations docs:**
  - The skill path follows the host session's environment, not a server restart.
  - Office requests deterministic fixes instead of applying them.
  - Clarity is shadow-only by default.
  - Added `SUPER_SEJONG_OPEN_REVIEW` and `SUPER_SEJONG_DETERMINISTIC_FIX`, plus the report script.

**Tests**
- tsc clean, desktop config too.
- vitest: 717 passed / 9 skipped.
- skills: 678 OK / 5 skipped with the switch unset, and the same with v2.
- documents: 93 OK in both engines.
- Seed: gold 91/92 (SSB-186 unfixed); invariants clean on 212 records.
- Lead probe: 32/32 and 36/36. Fluency set: 2/40.

**Not fixed, with reasons**
- A length-ratio chunk rollback in `chunk.reassemble` still restores the raw source chunk, not base(x). It is rare because the runaway guard comes first, and fixing it needs base text stored per chunk.
- The Office open-review cap can be used twice across attempts (up to about 2× the batch cap).
- An invalid `SUPER_SEJONG_GENRE_DEFAULT` on the skill path falls back to general, following the general fallback rule.
- In the worst case the shadow can delay a job by 15 s. This is bounded and documented.

**Deployment** (user: "서버 반영하고 재시작, 메인깃에 커푸")
- `/api/status` was idle. `npm run build` exited 0.
- Restarted with `SUPER_SEJONG_V2_SHADOW=1`: PID 47153 → 80242, status ready, LAN 200. Codex and Claude are ready, and the flag is in the process environment.
- Pushed `b173c8f..` to origin/main together with this log entry.

## 2026-10-05 — Super Sejong v2 merged into main; live server in v2 shadow recording; README section; pushed

**Request (user):** asked "1번으로 하면 세종엔진 사용하는건가?", then chose option 1 (shadow recording) with "오케이 그럼 일단 현재는 1번으로 서버에 반영". Mid-turn: "서버 반영, 재시작, 메인깃에 커푸", "그리고 리드미에 우리 세종 엔진에 대해서 정리해서 내용 추가" and "리드미 파일 정리하고 깃에 커푸".

**What changed**
- **main fast-forwarded** `b6a5d65` → `df37ec6` (the `super-sejong-engine` branch; main was its ancestor). The legacy engine stays the default (`SUPER_SEJONG_ENGINE` unset).
  - `skills/humanize-kr/SKILL.md` and `references/workflow.md` carry both the user's uncommitted "지혜 블로그" lines and the v2 additions, so those two files were stashed by tag (`pre-v2-merge-20261005-skill-docs`, sha `6c455cb`) and applied by sha after the merge.
  - The apply had no conflict. Only the user's 6 lines differ from HEAD, and the stash was dropped by tag.
  - The older stash (`pre-deploy-2026-09-09…`) is untouched. Backups of the four local files are in `$SP/r5/main-backup-20261005/`.
- **Docs commit** `f0949c2`.
  - README gains a "슈퍼세종엔진" section: what it does, principles, flow, the 2026-10-05 measurements, current state, switches and links.
  - The README is tidied: the v1 prototype and post-processing paragraphs move into that section, the dated handoff note moves to the development section, and "DOCX · PPTX 지원 (0.3.0)" becomes "릴리스 기록".
  - `docs/operations.md` documents `SUPER_SEJONG_V2_SHADOW=1` and `SUPER_SEJONG_ENGINE=v2` restarts, plus the watchdog caveat.
- **Deployment**
  - `/api/status` showed 0 active jobs. `npm run build` exited 0.
  - Restarted with `SUPER_SEJONG_V2_SHADOW=1 ~/.hermes/node/bin/node dist/ops/hermes-service.js restart`: PID 68128 → 47153, status ready, LAN 200.
  - The process environment shows `SUPER_SEJONG_V2_SHADOW=1` and the product Python. Codex and Claude are both ready.
- **Smoke job** (one Codex call, user-approved deploy check; 78-char constructed text, direct-text/medium):
  - Legacy delivered in 8.1 s with 1 call.
  - `diagnostics.v2ShadowCounts` was populated:
    - plan: 1 SUGGEST request (SSJ-LV3) and 1 deterministic fix (N01);
    - gate: v2 would accept, and the request was FIXED;
    - 1 sentence would be reverted as `collateral_edit`;
    - overhead: `ms_overhead` 117.
- **Pushed** `b3bc384..f0949c2` to origin/main: 63 commits (the four legacy hotfixes, the v2 branch, the docs commit).
  - `works-log.md` and the user's personal lines in `SKILL.md`, `references/workflow.md` and `docs/skills-guide.md` stay uncommitted, as before.

**Caveats**
- The Hermes cron `portal-watchdog` (`~/.hermes/scripts/portal-watchdog.sh` → `hermes-service.js watch`) restarts the server only after consecutive health failures.
  - On the user's request ("watchdog 스크립트에도 넣어줘") the script now runs `export SUPER_SEJONG_V2_SHADOW=1` before exec, so a watchdog restart keeps recording.
  - The original is backed up in `$SP/r5/main-backup-20261005/portal-watchdog.sh.bak`. Mode stays `-rwx------`; `sh -n` passes.
  - A manual run on the healthy server exited 0 with state `{desired: running, consecutiveFailures: 0}` and no restart (PID 47153 unchanged).
- Manual restarts must still pass `SUPER_SEJONG_V2_SHADOW=1` themselves.
- Shadow report: on the user's request ('며칠 뒤 기록 모드 결과 정리해줘') the lead added `scripts/sejong-shadow-report.py`.
  - Committed and pushed as `88ade0b` after a double check the user asked for ('커밋하고 푸시하기전에 … 더블체크').
    - Missing log: message, exit 1. Empty log: '0건' notice.
    - Synthetic log (broken line, a legacy-only job, 3 shadow jobs including a `shadow_failed` + `timeout_check` one): counts, families, rule ids and percentiles came out correct.
    - `--json` works. No document text appears in the output. No `__pycache__` was left.
    - Suites with the file present: tsc clean; vitest 715 passed / 9 skipped; skills 673 OK / 5 skipped; documents OK.
    - Packaging does not copy it; only `install-humanize-skill.ps1` is copied from `scripts/`.
    - Fixes made during the check: a missing log no longer raises a traceback, and sanitised rule keys display correctly (`tr_junge_itda` → TR-JUNGE_ITDA, `public_language_frame` → PUBLIC_LANGUAGE_FRAME).
  - It uses the standard library only, runs on the system Python 3.9.6, and outputs codes and counts.
  - It reads every `transform_complete` event that carries `v2ShadowCounts` and prints a Korean markdown summary: v2's verdict on the legacy output, the checks and codes that fire, the requests v2 would send, and the overhead percentiles.
  - First run: 1 shadow job, the smoke test, out of 191 logged jobs.
  - A session-only reminder is set for 2026-10-08 10:07 KST to run it and report. The reminder is lost if this Claude session ends; the script stays.
- Shadow counts cover the text path only (no Office). They judge legacy's output; they do not measure v2's own writing, which needs `SUPER_SEJONG_ENGINE=v2`.

## 2026-10-05 — Super Sejong v2: calque requests for every genre (WP-8b)

**Why:** in the real-model run (entry below) the writer was never asked to fix calques such as 넓은 공간을 가지고 있어서, 배송 준비중에 있습니다, 주문 건에 대해서 안내드립니다, 고객으로부터. The existing TR-* rules cover only essay, report and document, so the server's default genre (general) and blog got none of them. The user had asked to keep refining on the branch ("브랜치에서 더 다듬기").

**Merged on `super-sejong-engine`** (local, not pushed; HEAD `df37ec6`):
- `bb420c0` (WP-8b agent) adds four closed-list SUGGEST rules for all genres.

  | Rule | Pattern | Hand-checked precision |
  |---|---|---|
  | TR-GAJIDA | abstract noun + 을 가지고 있다 | 92/93 |
  | TR-JUNGE_ITDA | verbal noun + 중에 있다 | 13/13 |
  | TR-DAEHAE | 에 대해서 + 안내/설명/논의 … 하다 | 54/54 |
  | TR-ROBUTEO | person noun + 으로부터 + receiving verb | 20/20 |

  - Samples come from the T3 corpora: 5.14M chars of KatFish, news and KLUE. One LLM annotator labelled them; no native reader.
  - A stricter criterion ("the original reads stiff in context") gives TR-DAEHAE about 14/50 and TR-ROBUTEO about 7/20, mostly in news style.
  - 0 hits on the 28 owner blog posts and the seed blog items, so blog precision is undefined.
  - All four fire on the real-run sentences. Natural collocations (관심을 가지고 있다) and time phrases (회의 중에 있었던 일) do not fire.
- `268dbac` (lead): `voice_written_upshift` counted 이었 even after a final consonant. So "진행 중에 있었다 → 진행 중이었다", a TR-JUNGE_ITDA repair, was flagged. 이었 now counts only after a vowel-final syllable. DESIGN 3.3 gains a row for the four rules next to the LEAVE row they narrow.

**Decisions (lead)**
- Kept all four rules in every genre, against the agent's suggestion to make TR-DAEHAE and TR-ROBUTEO LEAVE in report and document.
  - NIKL 「공공언어 바로 쓰기」 (2022), pp. 42, 44, 54, 98, 100, treats 에 대하여, 중에 있다 and 으로부터 as translationese in exactly those public-document genres.
  - The weak strict-criterion numbers come from news text, which is not a target genre.
  - A SUGGEST request may be declined, and every edit is gate-verified.
- Not shipped (agent measured):
  - 에 대해 + 이야기/답변/질문 …: 17/40.
  - 으로부터 with organisation sources: it would fire on seed natural control SSB-025, and 에서 adds a place reading.

**Tests** at `df37ec6`:
- tsc clean.
- vitest: 715 passed / 9 skipped.
- skills: 673 OK / 5 skipped in both engines.
- documents: OK in both engines.
- Seed: gold stub 91/92, identity 0/438 touched, verify(x, x) and verify(x, base(x)) clean on all 212 records.
- Lead probe: 32/32 good fixes passed, 36/36 damage caught. Fluency: 2/40 meaning blocks, unchanged.

**Main hotfix deployed the same night:** `b6a5d65` (거 같다 = 것 같다), on the user's request. Details are in the real-model entry below.

**Real-model rerun after WP-8b** (user: "1번 고고"):
- Same 5 constructed texts, v2 only, Codex writer, v2 HEAD `df37ec6`; 7 calls, 15–29 s per text.
- Every text delivered with 0 reverted sentences, and every sentence kept its level.

| Text | Requests and outcome |
|---|---|
| T1 | TR-GAJIDA FIXED: 넓은 공간을 가지고 있어서 → 공간이 넓어서. Also 편이였어요 → 편이었어요 and "10분 정도의 시간이 소요됩니다" → "10분 정도 소요됩니다" (합쇼체 kept). 가 보려구요 kept. 1 call. |
| T2 | LV3 FIXED (진행될 예정입니다); LV1 declined this run. 신청하실 수. One retry for `voice_hon_si_dropped`, resolved on attempt 2. 2 calls. |
| T3 | A04 FIXED (발생되고). TR-GAJIDA + CONNECTOR_RUN FIXED: 장점과 단점을 동시에 가지고 있는 → 장점과 단점이 동시에 있는. 데에 있어서 → 데; 기울여야 할 필요 → 기울일 필요. 1 call. |
| T4 | TR-DAEHAE FIXED: 주문 건에 대해서 안내드립니다 → 주문 건을 안내드립니다. TR-JUNGE_ITDA FIXED: 배송 준비중에 있습니다 → 배송 준비 중입니다. Also 연락주세요 → 연락 주세요. 보내드릴께요 kept. 1 call. |
| T5 | 갔다 왔어. A05 FIXED: 같이 동행 → 동행. 최고인 거 같아ㅎㅎ, after one `voice_written_upshift` retry. The model kept the spoken 거, so the WP-10f retry wording works. 2 calls. |

- Model calls for the real-model work so far: 27 in total (20 earlier, 7 here).

## 2026-10-04 — First real-model run of Super Sejong v2 (Codex, 5 constructed texts) and the fixes it found

**Request (user):** "진행" for a real-model trial of v2, about 20 calls, without touching the live server. Afterwards "브랜치에서 더 다듬기".

**Setup**
- `$SP/r5/tierc/run.mts` builds the production runtime (`createProductionRuntime`) of the v2 worktree with `HUMANIZE_RUNTIME_ROOT` in the scratchpad, so the managed service and its runtime directory are untouched.
- Each job runs through `runtime.engine.transform` (Codex writer) at direct-text/medium.
- The same five constructed texts went through v2 (`SUPER_SEJONG_ENGINE=v2`) and legacy. Constructed text only, 166–226 chars each:
  - T1 blog in 해요체 with ㅋㅋ/~
  - T2 notice in 합쇼체
  - T3 report in 해라체
  - T4 customer service, mixed levels
  - T5 반말 blog
- Model calls: 20 in total (v2 7, legacy 8, reruns 5).

**Results (first run)**

| Text | Legacy | v2 |
|---|---|---|
| T1 | 2 calls, 29 s, whole chunk rolled back (`DIRECT_TEXT_FIDELITY_RESTRICTED`) | 1 call, 12 s: 편이였어요→편이었어요 (deterministic), "10분 정도의 시간이 소요됩니다"→"10분 정도 소요됩니다" (합쇼체 kept in a 해요 text) |
| T2 | 1 call, 14 s, 4 good edits | 2 calls, 20 s, 4 good edits (LV3, spacing, LV1, 경우에는→경우); requests FIXED 2/2 |
| T3 | 2 calls, 31 s, rolled back | 1 call, 14 s: 추세 redundancy, 데에 있어서→데, 발생되어지고→발생되고, 기울여야 할 필요→기울일 필요 |
| T4 | 2 calls, 32 s, rolled back | 1 call, 13 s: 대해서→대해, 준비중→준비 중, 연락주세요→연락 주세요; 보내드릴께요 kept (owner rule) |
| T5 | 1 call, 13 s, 3 edits | 2 calls, 16 s: 2 edits; one sentence reverted (meaning) |

- Legacy rolled back 3 of 5 texts; v2 delivered minimal edits on 5 of 5 with every sentence's level kept.

**Problems found and fixed**
1. **T5 meaning false positive.** "최고인거 같아ㅎㅎ" → "최고인 것 같아ㅎㅎ" raised `modality_changed`, because the hedge rule reads 것 같다 but not the spoken 거 같다. The live legacy gate does the same (confirmed on main: 맞는 거 같아 → 맞는 것 같아 is also flagged).
   - Fix `b6a5d65` on branch `hotfix/geo-gat`: `features()` reads 거 같다 as 것 같다 on both sides.
   - Merged into v2 (`bd89935`).
   - Deployed to main on the user's request ("핫픽스 메인 반영하고 서버 재시작해"):
     - `/api/status` was idle beforehand.
     - `git merge --ff-only` moved main `7394230` → `b6a5d65`; the hotfix touches only `super_sejong.py` and its test, so no stash was needed.
     - `npm run build` exited 0; the restart moved PID 39250 → 68128, status ready; LAN returns 200.
     - On the live tree, 최고인거 같아 → 최고인 것 같아 and 맞는 거 같아 → 맞는 것 같아 now give exit 0, and dropping the hedge (올 거 같아요 → 와요) still gives exit 2 with `modality_changed`.
     - Not pushed. The user's uncommitted files are unchanged. The hotfix worktree and branch were removed.
2. **Colloquial spelling changed (T1).** 가 보려구요 → 가 보려고요 broke the owner's "구어 표기는 기본 유지" rule.
   - `cbb6d99`: the spoken -구 after 려/다/라/냐/자 and the -구요 of a past or existential stem (했구요, 있구요) are now colloquial keep tokens.
3. **거 → 것 in casual sentences (T5).** The model's fix also changed 거 to 것, a written upshift.
   - `cbb6d99`: 것 같다 counts as `voice_written_upshift` in 해요체/해체 only; in 합쇼체/해라체 것 같다 is the expected form.
4. **Upshift retry gave the wrong form to keep.** In the rerun the retry said to keep the final "같아", so Codex answered "것 같아" again.
   - `b0709d3`: the violation now carries the source's spoken form ("거 같아").
   - Final rerun: Codex returned "최고인 거 같아ㅎㅎ" on attempt 2; all 3 edits were kept and nothing was reverted.

**Tests** at v2 `53a38ea` (= wp10f):
- tsc clean.
- vitest: 715 passed / 9 skipped.
- skills: 662 OK / 5 skipped in both engines.
- documents: OK in both engines.
- Lead probe 32/32 good fixes passed and 36/36 damaging edits caught; fluency set 2/40 meaning blocks.
- Hotfix branch `b6a5d65` on main: vitest 483 passed / 9 skipped; skills 113 OK / 4 skipped; documents OK.

**Open**
- T1/T2 left some translationese (넓은 공간을 가지고 있어서, 홈페이지를 통해서) that no rule requests. The open review picked them up only in one of two runs, which is model non-determinism.

## 2026-10-04 — Super Sejong v2 wave 3: TS engine, Office, shadow hook, meaning hardening; three legacy hotfixes deployed

**Request (user):** keep going with the v2 replacement engine on its own branch ("좋아 킵 고잉"). Merging into main stays opt-in.

**Branch state:** `super-sejong-engine` is local and not pushed; HEAD is `e37fa16`. Wave 3 merged:

| Commit | Package | Content |
|---|---|---|
| `aa1e799` | WP-10c (lead) | flow reads stacked initial connectives together; new floor code `weekday_changed` |
| `bea1c58` | WP-11b | `SejongEngine` (TS), `runPrompt` on both runners, v2 diagnostics. `SUPER_SEJONG_ENGINE=v2` selects it at start-up. |
| `d8653af` | WP-12 | Office path under v2: per-block plan, reject-only `verify_block`, retries only failed blocks |
| `d02b100` | WP-17 | legacy shadow hook (`SUPER_SEJONG_V2_SHADOW=1`): codes and counts only, no model call |
| `71833b7` | WP-10b | `condition_dropped`, `temporal_order_changed`, per-clause roles, A06 + 별로/도저히/일절, 뵈요→봬요, 이였→이었, `content_dropped` (shadow) |
| `3398012` | WP-10d (lead) | `key_word_dropped` enforced; common fluency drops licensed |
| `d6d557e` | WP-13 | agent-skill path under v2: in-process plan/check, empty-plan chunks decided without the host, engine pinned in job.json, bridge ops `context-v2`/`parse-v2` |
| `ac5d9de` | WP-11c (lead) | chunk rollback keeps base(x) on the server and skill paths; retry prompt names S ids |

Lead follow-ups: `054ca8b` and `e382eab` add Korean wording for the new codes; `0a3de90` adds a test allowance; `1c6aa7b` merges the legacy hotfixes into v2.

**Measured**
- Tests at `e37fa16`:
  - tsc clean (desktop config too).
  - vitest: 715 passed / 9 skipped.
  - skills: 661 OK / 5 skipped with the switch unset, and 661 OK / 5 skipped with `SUPER_SEJONG_ENGINE=v2`.
  - documents: OK in both engines.
- WP-13: in-process and CLI decisions are identical on all 6 seed composites (plans, every check report, delivered text). Five of the six go through attempt 2.
- WP-11b legacy byte-identity: runner command lines, prompts and engine results digest identical to `91a23b2`, compared with `cmp`.
- WP-11b Tier-B stub run (6 seed composites, real Python CLI): 127/161 primary injections fixed, 0 untouched paragraphs changed, 0 rollbacks.
- WP-12: legacy Office output unchanged (batch files, job.json, exported DOCX/PPTX bytes). tests/documents: 92 OK in both engines.
- WP-17: delivered text byte-identical with the hook on; overhead about 60–70 ms per 3k-char job (budget 300 ms).
- WP-10b seed gold stub: 91/92 primary injections fixed (was 87/92; only SSB-186, 거의, is still unfixed by design). The 555 meaning-pair rates are unchanged.
- Lead probe on constructed pairs (`$SP/r5/probe/probe.py`): 32 good fixes that must pass and 36 damaging edits that must be caught.

  | Gate | Good fixes passed | Damage caught |
  |---|---|---|
  | v2 at `91a23b2` | 26/32 | 32/36 |
  | v2 at `ec7bae4` | 32/32 | 36/36 |
  | legacy Python gate (hotfix branch) | 30/32 | 18/36 |

  The legacy production path also has the TS voice lock, which this table does not include.
- Constructed fluency edits (`fluency.py`, 40): 2 meaning blocks, both borderline (필요한 시점 → 해야 할 때; 해결될 수 있는 → 해결되지 않는다).

- Hermes drafts (10 articles; body-original and body-final; read-only; counts only, temporary copies deleted):
  - At normal, every one of the 20 bodies has 0 requests and 0 deterministic fixes, so v2 makes 0 writer calls.
  - At medium, there are still 0 requests and 0 fixes. Each body makes 1 call, only for the open review (up to max(3, 10%) sentences the writer may nominate).
  - The rule layer finds nothing to fix in these drafts.

**Decisions (lead) and reasons**
- `content_dropped` stays in shadow.
  - Licensing redundancy pairs, support verbs (결정을 내리다), postpositional verbs (에 대해서), the "N 작업을 진행하다" head noun and a purpose noun kept by 위해 took gold false blocks from 14/374 to 0/374.
  - It still fires on 6/40 constructed fluency edits.
- `key_word_dropped` is enforced instead (soft: one retry, then that sentence reverts).
  - It covers a closed list of time, participant/manner and cost words, plus place-name swaps.
  - Gold 0/374; seed preserve probes 0/25; 0 preserve pairs flagged.
  - It catches 함께/미리 drops and 서울시청→부산시청.
  - Reason: a false block costs one sentence its edit; a miss delivers a silent loss of content.
- Rejected: enforcing all of `content_dropped`. It went to 4/32 false blocks on the lead probe once the licences were tightened for gold.
- The document gate under v2 now reports the codes an SSJ-A06 request licenses for its own repair (polarity, modality, lexical) as review hints, not rollbacks. The Tier-B test now allows them.
- New redundancy entries RD_gachi_donghaeng, RD_seodulleo_geuphi, RD_geujeya_biroso and RD_mili_yeyak are author knowledge, marked "needs native review". This session's web-search budget was used up, so no source was found. RD_saeroun_sinjepum was widened under its existing NIKL source.

**Legacy hotfixes, deployed to main**
- The user chose "지금 반영" (merge into main and restart). Three commits on `b3bc384`; each fixes a correct writer fix that the live gate rolled back.

  | Commit | Fix the gate rejected | Hard failure |
  |---|---|---|
  | `8a2eb9b` | 할수 있다 → 할 수 있다 | `modality_changed` |
  | `ec7ba05` | 안되요 → 안 돼요 | `polarity_changed` |
  | `7394230` | 신분증을 필요로 합니다 → 신분증이 필요합니다 | `modality_changed` |

- Suites on the branch: vitest 483 passed / 9 skipped; skills 113 OK / 4 skipped; documents OK.
- The same commits are merged into the v2 branch, because v2's meaning family imports `super_sejong.py`.
- Deployment:
  - `/api/status` showed 0 active and 0 queued jobs before the merge.
  - `git merge --ff-only` moved main `b3bc384` → `7394230`. No stash was needed: the hotfix touches only `engine_runtime/super_sejong.py` and its test, not the user's uncommitted files, which kept their 6 lines.
  - `npm run build` exited 0, then the Hermes-node supervisor restarted the service: PID 55915 → 39250, status ready.
  - LAN `http://192.168.0.22:7882/` returns 200.
  - On the live tree, `workflow.py` now gives exit 0 for 할수 있다 → 할 수 있다, 안되요 → 안 돼요 and 필요로 합니다 → 필요합니다. All three were exit 2 before.
  - Not pushed; the user asked for merge and restart only. The hotfix worktree and branch were removed.

**Open**
- `DocumentEngine` still points `quickRulesPath` at an empty placeholder under v2. It can use `runPrompt` now.
- Real-model (Tier C) runs have not been done. They need the user's go-ahead because they spend Codex/Claude quota.

## 2026-10-04 — Super Sejong v2 implementation: WP-0 to WP-10 merged on the v2 branch; legacy 수-spacing false positive

**Request (user):** build Super Sejong Engine v2 to replace the vendored engine, on a branch kept apart from main ("이 작업은 새 브랜치를 따로 생성해서 메인이랑 분리해서 진행한다"), then "좋아 킵 고잉". Merging into main stays opt-in ("메인 브랜치에 머지하는건 내가 요청할때만").

**Branch state:** `super-sejong-engine` is local only and not pushed; HEAD is `91a23b2`.
- Each work package (WP) ran in its own worktree on branch `sejong/wpN` and was merged `--no-ff`. The worktree and branch were then removed.
- Merged so far: WP-0 contracts, WP-1 text/protect, WP-2 align, WP-3 chunk, WP-4 voice, WP-5 meaning/floor, WP-6 CTA, WP-7 flow/clarity, WP-8 diagnose/norms/josa, WP-9 commas, WP-11a TS prompt/response/adapter, WP-14 version/preflight/packaging, WP-15a scorer.
- WP-10 (`205c026`, merge `91a23b2`) adds the pipeline glue: plan, apply, repair, verify, decide, check, and `engine_runtime/sejong_cli.py`.
  - CLI subcommands: prepare, analyse, check, verify, finalize.
  - `workflow.py` switches to v2 only when `SUPER_SEJONG_ENGINE=v2`. Legacy output is byte-identical and pinned by a test.
  - `THIRD_PARTY.md` carries the vendor MIT notice for the ported pieces.

**WP-10 measurements:** stub writers on the 206-item seed set, medium strength, regex backend.

| Writer | Result |
|---|---|
| Identity | output = base(x) on every item; 0/438 clean sentences touched; 0 retries |
| Gold replacements | 87/92 primary injections fixed (86 exact, 1 probable); 0 collateral; 0 voice, quote, number or CTA damage; 21 retries |
| Gold, normal strength | 36/92 fixed with 21 calls |
| Damaged, full-text mode | 0 damage delivered in all 11 classes |
| Damaged, replacement mode | 3 misses: meaning flip 2/22 (T08 role swap, T20 전에→뒤에), transition 1/206 |

- The 5 unfixed gold items (SSB-044/049/185/186/190) involve negative-polarity adverbs (별로, 도저히, 일절) that are outside the A06 list.
- Invariants: `verify(x, x)` and `verify(x, base(x))` are clean on all 212 records.
- Performance at 100k chars: analyse 1.37 s, finalize 0.58 s, check ≤ 85 ms per chunk. All are within DESIGN §6.
- Tests at `91a23b2`:
  - tsc clean.
  - vitest: 595 passed / 9 skipped.
  - skills: 593 OK / 5 skipped. The baseline was 560; the 33 added tests are WP-10's.
  - documents: 54 OK.
- WP-10 changed other packages' files: `meaning.py` now compares both sides after `norms.fix_text` and after collapsing the closed A04 double-passive list, so the engine's own fixes are not flagged as meaning changes. `check.schema.json` also accepts sentence ids for open-review retries. The 555 meaning-pair rates are unchanged.

**Cross-package bugs fixed during integration (lead, before the WP-10 merge)**
- voice: the spacing fix 하실수 → 하실 수 was counted as an added -시-. Bound nouns written apart are now counted the same as attached ones.
- text: chatty blog lines ("…잠이 안 와~") were treated as unmarked headings and frozen. 해체 endings and CMC marks now mean "not a heading"; 개요/필요/중요 are excepted.
- protect: dotted versions were partly frozen ("1.2" of "1.2.3"). Now the whole version is frozen.
- commas: `restore_dropped` required an identical left word. It now matches by connective ending.

**Lead end-to-end check through the CLI** (constructed blog text, scratchpad only)
- Accepted: the deterministic 신청하실수 → 신청하실 수 fix and the SSJ-LV3 rewrite 진행이 이루어질 → 진행될.
- Caught and retried: -시- and ㅋㅋ dropped, 남겨주세요 → 남겨줘. Attempt 2 and finalize behaved as specified.
- Gaps found and assigned to WP-10b:
  - 뵈요 → 봬요 is blocked as `voice_humble_dropped`, because voice does not know 봬.
  - A reply that drops 함께 / 미리 / 예정 passes every family. The legacy gate misses this too.
  - The temporal and role flips listed above.

**Live main bug found by the same check (not deployed)**
- On main `b3bc384`, the legacy gate treats a correct spacing fix as a meaning change:

  | Fix | Hard failure |
  |---|---|
  | 할수 있다 → 할 수 있다 | `modality_changed` |
  | 볼수 없었다 → 볼 수 없었다 | `polarity_changed` + `modality_changed` |

  This forces a retry and then a rollback.
- Cause: in `engine_runtime/super_sejong.py`, `_CAN_POS`/`_CAN_NEG` match `(?<![가-힣])수`, which only reads a spaced 수.
- Fix prepared as `8a2eb9b` on local branch `hotfix/bound-noun-spacing` (worktree `.worktrees/hotfix-su`). Nothing was merged or deployed; that waits for the user.
  - `features()` reads 수 spaced after an attributive ㄹ ending on both sides. 할수록 and 할수밖에 are untouched.
  - 6 regression cases added. An attached 범인일수 있다 → 범인이다 is still caught.
  - Suites on the hotfix branch: tsc clean; vitest 483 passed / 9 skipped; skills 113 OK / 4 skipped; documents OK.

**Running now (wave 3, each in its own worktree)**
- WP-10b: content-drop and temporal-order meaning codes, 뵈요/봬요, A06 additions, T08.
- WP-11b: `SejongEngine` TS integration.
- WP-12: Office path.
- WP-13: skill path.
- WP-17: legacy shadow hook.

**Open**
- NIKL corpus approval is pending; the user has applied.
- v2 cutover is not scheduled; the plan is shadow mode first.
- Vendor removal (WP-18) needs the user's approval.

## 2026-10-04 — Main hotfixes: wasted retries, writer commas, order-swap rollback, frozen protected sentences, voice lock

**Request (user):** fix all four main bugs found by the v2 research ("2번은 모두 수정"), then "기능 버그 수정한거는 메인 브랜치에 머지하고, 서버에 반영하고, 서버 재시작해".

Work was done in a hotfix worktree off main, then fast-forwarded. The worktree and branch were removed afterwards.

**Commits (pushed `4b6a7a9..b3bc384`)**
- `f926eaa`:
  - P1-only gate warnings are advisory: exit 0 with `advisoryReasons`, no retry.
  - New `engine_runtime/comma_guard.py` keeps writer commas: it aligns each edited sentence with its source sentence and removes only added commas. Used on the server and skill paths.
  - `_order_swapped` takes the best match per ordering. Before, every unchanged sentence with "…하기 전에 … 한 후에" was rolled back.
  - Protected direct-text sentences may now be edited when their protected elements survive.
- `2046c28`:
  - Protected markers are compared by meaning class (가능 ↔ 수 있, 경우 ↔ -면).
  - Numbers and quotes are compared in order.
  - Multi-subject sentences keep their noun order instead of being frozen.
  - "N이 되다" complements are no longer counted as subjects.
  - Light nouns (진행·실시·시행) may be dropped, and a noun may become its 하다/되다/받다 verb.
- `b3bc384`: voice lock (see the live check below for why). Per sentence it checks:
  - speech level and honorific -시- count (T2 noun exclusions);
  - question, request and propositive mood, and stance ending;
  - humble verbs and CMC marks.

  Results on the T2 pair set:

  | Pairs | Flagged |
  |---|---|
  | 60 non-structural preserving pairs | 1 (a real -시- loss) |
  | 64 drifting pairs | 52, counting splits/merges, which direct text already rejects |

  The rewrite policy now states the per-sentence voice rule.

**Tests**
- f926eaa: tsc clean; vitest 472 passed / 9 skipped; documents OK; skills 112 OK / 4 skipped.
- b3bc384: vitest 483 passed / 9 skipped; the rest unchanged.
- One vitest run on f926eaa had a single failure that did not reproduce on 2 reruns (test name not captured).

**Behaviour changes, with tests updated to match**
- The P1-only candidate-review retry is no longer reached through the real gate.
  - 6 integration tests that only exercised it were removed; 2 were rewritten as "accepted on the first call".
  - The skill-gateway P1 test was rewritten the same way.
  - `candidate-review.ts` is now dead code, left for v2 to remove.
- Two restoration tests (TS integration and skill gateway) now expect the de-nominalised "자료의 구분이 이루어지고 …" rewrite to be kept.
- The role-swap restoration test is unchanged and passes.

**Merging into main**
- The main tree has the user's uncommitted personal lines in `skills/humanize-kr/SKILL.md`. Each merge that touched that file was handled the same way:
  1. Stash that file alone, with a unique tag.
  2. `git merge --ff-only`.
  3. `git stash apply <sha>`.
  4. Drop the entry by tag.
- Both lines survived with no conflict markers. A backup is in the scratchpad.

**Deployment**
- `/api/status` showed 0 active jobs before each merge.
- `npm run build`, then a Hermes-node supervisor restart.
- PIDs: 4118 → 38731 → 48827 → 55915.
- LAN `http://192.168.0.22:7882/` returns 200 and both providers are ready.

**Live checks** (Claude Sonnet 5.5 low, direct-text, strength medium, 3 sentences full of protected elements)

| Stage | Calls | Time | Result |
|---|---|---|---|
| Before the fixes | 2 | 11–13 s | Source returned unchanged |
| After `f926eaa` | 2 | — | No P1 warning, but the TS fidelity guard rolled back the natural edits (wording-level markers) |
| After `2046c28` | 1 | 4.7 s | Edits applied inside protected sentences, but "궁금하신 → 궁금한" dropped an honorific |
| After `b3bc384`, run 1 | 1 | 5.3 s | Edits applied, honorific kept; the model dropped a writer comma itself |
| After `b3bc384`, run 2 | 1 | 4.4 s | Edits applied, honorific and comma kept |

- Edits applied after `2046c28`: 인정이 됩니다 → 인정됩니다, 진행이 가능하며 → 진행할 수 있으며, 누락되는 경우에는 → 누락되면.
- The comma dropped in b3bc384 run 1 was the model's own deletion, not our stripper; v2 can restore it.

**Open**
- The voice lock misses persona swaps, 해체-level changes and nominal↔finite changes; the full v2 classifier covers these.
- Per-sentence revert instead of chunk retry/rollback is v2 work.
- The design doc (`.worktrees/super-sejong-engine/docs/research/super-sejong/v2/DESIGN.md`, 787 lines, 19 work packages) is drafted but not reviewed.

## 2026-10-04 — Super Sejong v2 research: 12 tracks toward replacing the 윤문 엔진

**Request (user):** Super Sejong was meant to *replace* the vendored 윤문 엔진, not sit on top of it. Redo the research on a separate branch, isolated from main. It must be better than the old engine, not a copy, and use clarity, flow and CTA as criteria. The key point is to keep 말투 and fix only awkward Korean.

Later additions from the user:
- Research the listed institutions and fields (국립국어원, 한국어학회, 한국학중앙연구원, "한글연구소", KFL, Korean NLP) and the papers.
- Look for MCP servers and plugins, with a mandatory security check before any use.
- "조사하고나서 대기해": stop after the research and wait.

**Decisions by the user**
- Subagents run on Opus 5.5 high or Sonnet 5.5 xhigh, chosen by difficulty.
- The LLM stays the writer; v2 replaces everything around it.
- 말투 is preserved strictly per sentence ("문장마다 원래 말투 그대로 유지해야함").
- Colloquial spellings and CMC tokens (할께, ㅋㅋ, ^^, ~) are kept by default; fixing them is an opt-in.
- The published 지혜 blog posts were already processed by the 윤문 엔진.
- Hermes keeps the drafts at `~/.hermes/work/blog-new10-20261003/articles/*/` (body-original / -humanized / -final). Read-only use is approved.

**Setup**
- Branch `super-sejong-engine` at `4b6a7a9`, in worktree `.worktrees/super-sejong-engine`.
  - It is a separate worktree because the live server reads Python from the main tree per job.
  - `node_modules` is symlinked and listed in `.git/info/exclude`.
- Agent definitions `~/.claude/agents/sejong-opus-high.md` and `sejong-sonnet-xhigh.md` (model + `effort` frontmatter).
  - Creating the agents directory for the first time required a session restart (`claude --continue`); Claude Code docs confirm this.
- Research brief and per-track prompts in the session scratchpad `r5/`.

**Tracks**
- Opus high: T1 engine dissection, T2 voice lock, T3 awkward Korean, T8 literature, T11 NLP tooling, T12 MCP discovery and security audit.
- Sonnet xhigh: T4 clarity, T5 flow, T6 CTA, T7 evaluation, T9 NIKL resources, T10 AKS/KFL/philology.
- The session's WebSearch budget (200) ran out late in the run. WebFetch still worked until near the end; T9 also ran out of fetches.

**Key findings, each spot-checked or reproduced by the lead**

| Track | Finding | Lead check |
|---|---|---|
| Real drafts | All 10 Hermes drafts are byte-identical across original/humanized/final; the 윤문 엔진 made 0 edits. `protected_sentence_count` 42–49 per article, 463/640 (72%). 8/10 went attempt-1 "retry" → attempt-2 "accept-with-warning", both with 0 edits. | Lead measured |
| T7 | The protection is our own product rule, not vendor: `src/engine/rewrite-policy.ts:33` (from `e09df96`, 2026-09-10) tells the model to keep every sentence with numbers, dates, quotes, possibility, negation, obligation, condition or multiple subjects verbatim. The 10-03 benchmark's changes (17/20) came from the text-file route, which has no such protection. | Lead confirmed the rule |
| T1 | The vendor gate warns on unchanged human text 75–99.5% of the time (P1 comma z-scores against placeholder baselines), forcing a wasted retry. | Lead: 25/30 KatFish human essays → P1 warn |
| T1 | `strip_injected_commas` deletes the writer's own commas in any edited sentence. | Lead: 2/2 removed after a one-word edit |
| T1 | v1 bug: `_order_swapped` flags an identical sentence with two 전에/후에 frames, so it rolls back. | Lead reproduced on KatFish essay index 150 |
| T1 | No voice guard, no CTA guard; only `quick-rules.md` reaches the model. | — |
| T2 | Per-sentence speech-level classifier (regex, 8 levels): 0.964 on a blind holdout (n=110) vs 0.736 for the current TS function. Gate catches 104/104 one-sentence and half-post 해요↔합니다 drifts vs vendor 0/104; 0 false flags on 1,202 paragraphs of voice-neutral edits; graft/revert repair restores 620/620. | Lead: 10/10 on new pairs |
| T3 | Mechanical norm errors (spacing, 율/률, misspellings, 로서/로써) fire 17–20 per 10k chars in human student essays, ~0 in LLM text, and 0 in the blog. 11 kept rules with precision 0.92–1.00. | Lead recount: 17.55 vs 17.21 per 10k; 율/률 0.47 exact |
| T4 | Clarity acts mainly as a non-regression guard. Blog sentence length: P95 21, P99 26 eojeol; 0.4% ≥30. | Lead: exact match |
| T5 | The shipped gate passes added transitions, wrong contrast connectives and paragraph merges. Five flow guards proposed, with 1/77 benign false alarms in-sample. | Lead: all three pass with exit 0 |
| T6 | CTA detector P 103/103, R 103/107 on drafts frozen before tuning. The CTA gate blocks 90.3% of 113 violating rewrites vs 42.5% for the current gate. | Lead: 7/8 new pairs correct; 1 overblock on a synonym condition clause (준비되면→갖춰지면) |
| T7 | Seed benchmark: 206 items + 6 composites. v1 guards on 72 new probes: 76.6% sensitivity, 48% overblock. Protocol with safety non-inferiority margins and power calculations. | Lead: 212 records validate against the schema |
| T8 | ~85 sources. 15 ranked findings: per-sentence ending-class gate; -시- tiers; length never triggers edits; no new connectives (explicitation); aspect (-고 있다) as a meaning axis; 호응 family; minimal-edit prompt. | Spot numbers consistent with T3 |
| T9 | NIKL expert edits: 304,046 cases, spacing 41.4%. 온라인가나다 answers firmly only on spelling and 호응 breaks. Corpus catalogue and terms collected. | Lead checked both in the source text |
| T10 | NIKL's 25 native-writer error types exist. The 2025 online-posting corpus has 73,176 Naver blog + 42,937 Instagram posts. AKS adds little. No AI-era "한글연구소" found. | Lead checked both |
| T11 | Kiwi in a persistent worker takes 57 ms per 2×2.6k chars vs 0.93 s per spawn. Bidirectional KLUE-NLI as OR-veto: untuned set misses 11/60 → 2/60, code1 overblock 8 → 15/207. The tested checkpoint has no licence. | Lead recomputed independently: identical numbers |
| T12 | No third-party MCP for the product. Rejected: Naver/PNU/나라 spell-check scrapers (one spoofs X-Forwarded-For), koreandict-mcp-server (reads `~/.cursor/mcp.json` and `.env`), kisti-mcp (logs keys), paper-search-mcp (Sci-Hub, TLS off). Safe for pinned research use: korea-scholarship-mcp `8ed87e3`, arxiv-mcp-server 0.8.0. | Lead read the source for two rejects and one safe pick. Nothing installed. NIKL stdict data mirror `42c0d01` (657 MB XML) downloaded to the scratchpad only. |

**Production-affecting issues found on main (not fixed; the user has not decided)**
- P1 warn → wasted retry on unchanged text.
- The comma stripper deletes writer commas.
- `_order_swapped` false rollback.
- Flow-guard gaps.
- The direct-text protection rule makes the skill path a no-op on the owner's genre.

**Files**
- Reports T1–T12, the brief, prototypes (voice/gate/repair, detectors, flow gate, CTA detector/gate, scorer) and the seed benchmark are copied to the worktree's `docs/research/super-sejong/v2/`.
- They are uncommitted. The scratchpad in `/private/tmp` may be wiped.
- Some T2/T5 examples contain the owner's business and personal name. Review before any commit.
- No NIKL corpus or blog bodies were stored.

**Limits**
- Every hand label and constructed pair comes from a single LLM annotator; no native-reader judgement exists.
- No live LLM rewrite runs were made.
- Windows was not measured.

**Open, for the user**
- Apply to 모두의 말뭉치 (procedure given to the user). The site page showed a "일부 기능 장애로 신청 불가" notice, unverified.
- Get NIKL dictionary and KCI API keys.
- MCP installation (recommended: none).
- Main hotfixes.
- Whether 되요/됬/몇일 count as colloquial.
- Voice-conflicting fixes (하실게요→해 주세요).
- Licence path for the NLI model.
- Evaluation margins.

**Status:** research complete. Design and implementation have not started, per the user's instruction to wait. Nothing was committed or pushed.

## 2026-10-04 — Super Sejong Engine: review, resumed research, guard rewrite, performance fixes

**Request (user):** review the MD files Codex wrote on 10-03 (research synthesis, code plan, handoff, benchmark), resume the interrupted research tracks with subagents, review the Super Sejong code, and find and apply logic, performance and other improvements. Constraints: subagents on Sonnet 5.5 only, no git commit/push, stop and wait after the changes.

**How:**
- Ten Sonnet 5.5 subagents in parallel: 2 document reviews, 3 code reviews, 5 research tracks (morphology, lexicon, corpus calibration, josa, discourse).
- All edits were made in a scratch worktree, a detached snapshot `4fa16a3` of HEAD `c792440` plus the full working tree.
- The lead re-ran every claimed reproduction before accepting it.
- The diff was applied to the main working tree only after `/api/status` showed 0 active and 0 queued jobs. Python stages are read per job, so they go live on save.
- Full record: `docs/research/super-sejong/EVALUATION-2026-10-04.md`.

**Bugs found and reproduced**

| Area | Reproduction | Fix |
|---|---|---|
| Meaning guards (prototype) | On an independent 60/60 pair set: 38.3% of paraphrases blocked, 40.0% of meaning changes accepted. Blocked: 뿐만 아니라, 잘못, 어렵다→쉽지 않다, 알지 못했다→몰랐다. Accepted: 안 갔어→갔어, 승인→반려, 올랐다→내렸다, 모든→일부, 이상→이하, subject/object swaps. | `engine_runtime/super_sejong.py` replaced with event-based guards (v3, below). |
| `change_rate` (vendor metrics_v2) | A quadratic char diff; single-line paragraphs bypassed line segmentation. 20k repetitive chars took 86 s; 85k exceeded the 120 s Python timeout after all model calls had run. | Line, then sentence, segmentation, with bounded unmatched blocks. 20k: 86 s → 1.4 s; 85k: >120 s → 5.3 s; max value difference 0.0003 on 20 real texts (3k–60k chars). Vendor patch regenerated and verified byte-identical with `git apply` and `patch -p1`; UPSTREAM.md matches the sync-engine.ps1 generator. |
| Style hints (TS) | The quote-protection regex was quadratic: an unclosed “ in 50k chars blocked the event loop 0.87–4.7 s. "집에 있어서" was flagged as translationese. | New `src/engine/super-sejong.ts`, 15 rules; every 50k-char adversarial shape runs in ≤37 ms. |
| Chunk prompts | The Python "chunk i/N" header was written to disk but never sent to the model. | Chunk prompts now carry the position and the document's dominant speech level. |
| Office path | Ordered-list equality of modal and short-negation cues rejected harmless clause reordering (37.7% overblock measured by a code reviewer). | Enforce mode uses Super Sejong's sentence-aligned comparison instead. |
| Office, shadow mode (found during the docs pass) | With `SUPER_SEJONG_MODE=shadow`, the Office path ran neither the old list checks nor the new comparison, so "제출해야 한다 → 제출할 수 있다" was accepted. Enforce and off both rejected it. | Shadow and off now keep the legacy checks; test `test_shadow_mode_keeps_the_ordered_modal_check`. |
| Particles | No check for allomorphs that an edit left wrong (URL를, 10%으로, AI이). | New `engine_runtime/super_sejong_josa.py`: repair in restore, `josa_mismatch` gate in verify, rejection on the Office path. |
| Observability | Gate failure codes were parsed but never logged; there was no way to shadow the new guards. | `SUPER_SEJONG_MODE=enforce|shadow|off`. Diagnostics add `hardFailureCounts`, `shadowFailureCounts`, `repairedParticles` and `styleFindingsBefore/After` (codes and counts only). |

**Meaning guards (v3), cross-evaluated on three independently written sets (overblock / missed)**

| Set | Prototype | Code reviewer v2 | Shipped v3 |
|---|---|---|---|
| Lead, 20/20 (written blind; v3 tuned on it) | 50% / 75% | 25% / 30% | 5% / 0% |
| Morphology researcher, 60/60 (never tuned on) | 38.3% / 40.0% | 11.7% / 20.0% | 11.7% / 18.3% |
| Code reviewer, 207/188 | 27.1% / 68.6% | 3.4% / 0% | 3.9% / 0% |

- The honest generalisation figure is the middle row.
- All 555 pairs are now a regression test (`tests/skills/data/super_sejong_pairs.json`, `test_super_sejong_guards.py`) with per-set rate thresholds.

**Other changes**
- `quantities.py` skips the idiom "두 번 다시".
- `src/app.ts`: a Host rejection on a non-API path shows a Korean page listing the LAN URLs; the API returns `HOST_NOT_ALLOWED` with a hint.
- `hermes-service.ts`: falls back to `/api/health` when `/api/status` returns 404 (older builds).
- `codex-runner.ts`: the comment now says `--disable unified_exec` is ignored on CLI 0.160, so the sandbox is the real containment.
- `python-engine.ts`:
  - restore runs a third step (josa);
  - an `output-limit` termination is treated as invalid output;
  - `shadowFailures` is parsed with a strict code pattern.

**Docs**
- `EVALUATION-2026-10-04.md` (new) and research data under `docs/research/super-sejong/data/2026-10-04/`:
  - a 284-entry lexicon, kept for research only and not wired in;
  - calibration data;
  - rhythm thresholds;
  - the lead pair set.
- `operations.md` gains:
  - a `SUPER_SEJONG_MODE` section with a mode table;
  - the new diagnostics fields;
  - `/api/status`;
  - a warning that the watchdog does not inherit the mode;
  - a warning that `npm run test:e2e` rebuilds the served `dist/` and that Python edits go live on save.
- `RESEARCH-SYNTHESIS.md`: the particle claim was corrected. 은/는 is an auxiliary particle, so 은/는↔이/가 is not automatically safe.
- Code plan: a 4 October update with revised priorities.
- Handoff: an addendum.

**Corrections to Codex's 10-03 documents**
- The benchmark difference is within noise: paired −4.2 s, bootstrap 95% CI (−19.7, +10.2), MDE about 22 s, sign test p = 0.22.
- The replay flag counts (4 vs 0) are circular.
- The obligation guard covered only the Office path.
- About 75 cited URLs were spot-checked: no dead links, three content mismatches (reports H, J and G).

**Decisions and rejected proposals**
- **Kiwi analyser:** not adopted for the runtime. It is Apache-2.0 at 0.24.0 but costs about 0.9 s cold start and 0.4–0.6 GB per process (Python is spawned per gate), plus about 130 MB on Windows. Most of the accuracy gain came from the cue categories, not the analyser.
- **Josa lexicon:** not bundled because its licence is unverified. Without it, 이/가 and 은/는 after Hangul nouns stay at hint level.
- **Register-drift and term-drift gates:** not shipped, because their false-positive rate on real rewrites is unmeasured.
- **Style rules rejected:** human prose uses them as much or more than LLM prose: 에 의해, 로부터, 에 대해/대한, 을 가지다, 의-chains, 이러한, ~하고 있다.
- **Review item rejected:** the desktop reset race. The UI disables reset during import and IPC is ordered.
- The user's personal blog policy line in `skills/humanize-kr/SKILL.md` was left untouched.

**Verification (main working tree, macOS)**

| Check | Result |
|---|---|
| typecheck | clean |
| vitest | 472 passed, 9 skipped (420 at the end of the 10-03 review) |
| test:documents | 54 OK (53 + the shadow-mode test) |
| test:skills | 102 OK, 4 skipped (guards 18, josa 7 new) |

- **Not run:**
  - Playwright E2E (it rebuilds the served `dist/`);
  - Windows checks;
  - a live model benchmark of the revised engine;
  - any native-reader evaluation.
- A security reviewer subagent opened `~/.codex/auth.json` and `~/.claude.json` (byte count only); this was reported to the user.

**Commit, push and deployment (user asked: "일단 메인 깃에 커푸하고 서버에 반영하고 서버재시작해")**
- Pre-commit E2E: `E2E_PORT=7893 npx playwright test`, 54 passed and 9 skipped.
- Commit `4b6a7a9` was pushed to `origin/main` (`c792440..4b6a7a9`): 93 files, including Codex's uncommitted 10-03 work (review fixes, research and reports).
- Left out of the commit and still modified in the working tree:
  - `works-log.md` (standing rule).
  - The user's personal "지혜 블로그" host/quota policy lines in `skills/humanize-kr/SKILL.md`, `skills/humanize-kr/references/workflow.md` and `docs/skills-guide.md`. Those changes were nothing but that policy, and they include a local `~/.hermes` path. They would ship to skill users, so they are left for the user to decide.
- Deployment:
  - Before: `/api/status` showed 0 active and 0 queued jobs.
  - Ran `npm run build`, then `~/.hermes/node/bin/node dist/ops/hermes-service.js restart`.
  - Result: `restarted`, PID 80787 → 4118, `ready`, Codex and Claude both ready. Port 7882 is served by 4118; the LAN URL `http://192.168.0.22:7882/` returns 200.
  - A disallowed Host gets the Korean page listing `http://192.168.0.22:7882`, and the API gets `HOST_NOT_ALLOWED`.
- Live smoke test (Claude Sonnet 5.5, low effort, 148 chars):
  - Completed in 13.2 s.
  - The new diagnostics fields are present: `hardFailureCounts` {}, `shadowFailureCounts` {}, `styleFindingsBefore/After` 2/2, `repairedParticles` 0.
  - Gate codes were WARN ×3 with 1 retry, and the output came back identical to the source. The 09-30 smoke showed the same WARN ×3 + 1 retry pattern before Super Sejong, so this is not new. It was not investigated.
- The server now runs the committed code. The Python and TS halves are in sync and the mode is the default `enforce`.
- Open:
  - human evaluation;
  - lexical axes beyond the ~45;
  - separating the served tree from the development tree;
  - why short inputs warn on every attempt and come back unchanged.

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
