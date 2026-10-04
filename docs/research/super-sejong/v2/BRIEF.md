# Super Sejong Engine v2 — research brief (4 October 2026)

## Goal

The service rewrites Korean prose with an LLM writer (Codex or Claude CLI). Today a vendored upstream engine,
the "윤문 엔진" (`vendor/humanize-engine`, upstream epoko77-ai/im-not-ai, label 2.3.2), decides what to fix and
checks the result. **Super Sejong Engine v2 must replace that engine completely** and be measurably better than
it, not a copy of it. The LLM stays the writer; Super Sejong owns everything around it.

## Product principles from the owner (in priority order)

1. **Keep the writer's voice (말투 유지).** Speech level (하십시오체/해요체/해라체/해체 …), honorific relations,
   written vs spoken register, first-person and persona markers, and sentence-final style stay as the writer chose,
   sentence by sentence. A rewrite that changes 말투 is a failure even if it reads well.
2. **Fix only awkward Korean (어색한 한국어).** Ungrammatical or unnatural Korean is the target: broken
   agreement (호응), translationese, needless passives/nominalisations, redundancy, wrong particles, unnatural word
   order, etc. Natural text is left alone; "no edit" is a valid result.
3. **Meaning is preserved.** Facts, numbers, names, quotes, headings, paragraph order, negation, modality and
   participant roles do not change (the current guards in `engine_runtime/super_sejong.py` already do part of this).
4. **Quality criteria to use: clarity (명확성), flow (흐름), CTA (calls to action).** Clarity and flow may be
   improved only within principles 1–3. A CTA in the source must stay present, equally strong and equally specific;
   its awkward wording may be fixed. Super Sejong must never invent a CTA.
5. Evidence over intuition: every rule needs a trigger, counterexamples, a false-positive estimate and a genre
   boundary. Human-norm violations and "LLM tells" are different things; say which one a rule targets.

The owner's main real use is rewriting their own Naver blog posts (public: https://blog.naver.com/wisdom_jhk; post
IDs in `docs/reports/2026-10-03-super-sejong-blog-sample.json`). Blog genre, 말투 and CTAs matter most.
Do not store or quote full post bodies in reports; short excerpts (one sentence) as examples are fine.

## What the 윤문 엔진 does today (all of it must be covered or deliberately dropped)

Worktree (read this copy, not the main tree): `/Users/wisdom/wisdom_project/gpt/ai-text-makes-likes-human/.worktrees/super-sejong-engine`

- Rulebook given to the model: `vendor/humanize-engine/skills/humanize-korean/references/quick-rules.md`
  (+ header/footer), `ai-tell-taxonomy.md`, `diagnosis-rules.md`, `rewriting-playbook.md`; builders in
  `vendor/humanize-engine/scripts/build_quick_rules.py`, `build_diagnosis_rules.py`.
- Pre-processing: `scripts/sanitize_text.py`, `scripts/prepare_monolith_input.py` (protection, chunking).
- Post-processing: `scripts/restore_modality.py`, `scripts/strip_injected_commas.py`, `scripts/reassemble_chunks.py`.
- Gates and metrics: `scripts/verify_gates.py`, `scripts/verify_change_rate.py`, `scripts/checks.py`,
  `references/metrics.py`, `references/metrics_v2.py`, `references/baseline*.json` (placeholder values).
- Local patch on top of upstream: `scripts/patches/humanize-engine-portal.patch`.
- Product code that calls it: `src/engine/python-engine.ts`, `src/engine/humanize-engine.ts`,
  `src/engine/prompt-builder.ts`, `src/engine/document-prompt.ts` (Office), `src/engine/codex-runner.ts`,
  `src/engine/claude-runner.ts`, `engine_runtime/workflow.py` (wraps the gates), `engine_runtime/documents/*`
  (Office path), `engine_runtime/skill_gateway.py` (agent-skill path), `skills/humanize-kr/`.
- Super Sejong v1 already shipped on top (commit 4b6a7a9): meaning guards `engine_runtime/super_sejong.py`, particle
  repair `engine_runtime/super_sejong_josa.py`, style diagnostics `src/engine/super-sejong.ts`.
  Read `docs/research/super-sejong/EVALUATION-2026-10-04.md` first: it records what was measured, what was rejected
  (e.g. rules that fire as often on human prose), and the known limits.
- Earlier research reports A–S: `docs/research/super-sejong/*.md`; lexicon data:
  `docs/research/super-sejong/data/2026-10-04/lexicon/*.json`.

## Data and tools available

- Scratch root `SP=/private/tmp/claude-501/-Users-wisdom-wisdom-project-gpt-ai-text-makes-likes-human/e70a7860-b0c8-4bf4-999b-63b4ba6d0a8c/scratchpad`
- KatFish (human vs 4 LLM generators; essay 770, abstract 378, poetry 945 lines, JSONL):
  `$SP/research/B/katfish_repo/katfish_dataset/{essay,abstract,poetry}.jsonl` (+ README in `katfish_repo`).
- Naver news sample `$SP/research/B/naver_news_test.csv`; KLUE MRC passages `$SP/research/B/klue_mrc_*.json`.
- Prior track scripts and features: `$SP/research/<A..S>/`, `$SP/r4/res1..res5/` (e.g. `$SP/r4/res3/features.jsonl`).
- Python 3.11 with the Kiwi morphological analyser (kiwipiepy): `$SP/research/I/venv/bin/python`.
  Product Python: `/Users/wisdom/.hermes/hermes-agent/venv/bin/python` (3.11, lxml). System python3 is 3.9 — avoid.
- Web search and fetch are allowed. NIKL (국립국어원) resources, papers, style guides and public UX-writing guides
  are expected sources.

## Rules for every track

- Write only in your own directory `$SP/r5/<track>/`. The repository is read-only for research tracks.
- Do not run codex/claude CLIs, call the live portal (port 7882), build, restart, commit or push.
- Do not open credentials or personal config (~/.codex, ~/.claude.json, ~/.claude/*, .env, keychains).
- Report in English (Korean examples are fine). Structure: findings with evidence level, operational rules or
  designs, measurements (with n and method), what the 윤문 엔진 gets wrong or misses in your area, concrete
  recommendations for v2, open questions. Your final message is the report and must stand alone.
