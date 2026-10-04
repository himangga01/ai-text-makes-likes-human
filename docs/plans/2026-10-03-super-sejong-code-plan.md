# Super Sejong Engine: Code Modification Plan

Date: 3 October 2026. Basis: [two-round code/service review](../reports/2026-10-03-two-round-review.md) and the [14-axis research synthesis](../research/super-sejong/RESEARCH-SYNTHESIS.md). This plan distinguishes work completed in the reviewed working tree from the studies and changes that still need evidence. The goal is natural Korean revision with source meaning, register, and document structure intact; detector evasion is not a quality objective.

## Completed in this working tree

1. **Close concrete safety gaps.** Restrict Codex transformation tools and its working directory, bound process output and Office XML parsing, reject arbitrary DNS Host values, return fixed public errors, and keep a failed desktop import from changing the source/save reference.
2. **Strengthen preservation.** Share signed quantity and Korean numeral/unit checks across TXT/MD and Office. Add Super Sejong guards for sentence loss, selected negation targets and sentence-level modality, obligation, high-confidence participant swaps, and high-risk lexical reversals. Keep retry and source rollback as the safe fallback.
3. **Introduce bounded diagnostics.** Emit source-offset style hypotheses for two Korean public-prose constructions. Exclude code, quotations, and structural Markdown regions. Do not automatically apply a rewrite or score a writer.
4. **Align user-visible state.** Report accepted Office output characters, distinguish recognized import failures, and document the new Host policy.
5. **Verify regressions.** Run type checking, Python document/skill suites, Vitest, the relevant browser E2E slice, and an isolated live Codex fixture. A Windows-only desktop regression is written but needs execution on Windows.
6. **Benchmark the current service paths.** Pair 20 reproducibly sampled posts from one public Korean blog under the same model and routing. Record calls, retries, rollbacks, latency, final change status, and full-gate replay signals in the [benchmark report](../reports/2026-10-03-super-sejong-blog-benchmark.md). The ablation and Super Sejong each changed 17/20 outputs; Super Sejong made four more model calls and four more retries. A targeted 20-post meaning-flip probe exposed six misses for contracted `아닙니다`; correcting the negative-copula signature raised detection on those constructed cases from 14/20 to 20/20. Counting attached `안됩니다` as a negative surface also prevents a spacing-only correction from triggering a polarity alarm.

## Next research and implementation increments

| Priority | Change | Acceptance evidence required before enabling by default |
| --- | --- | --- |
| P0 | Build a licensed, provenance-tracked Korean revision evaluation set with explicit genre, audience, writer, topic, and meaning labels. | Rights recorded per source; held-out writer/topic/model splits; at least three blinded native-reader judgments per pilot pair with disagreement retained. |
| P0 | Expand the semantic ledger to clause-aligned predicate, role, negation scope, modality, temporal anchor, and discourse referent records. Give uncertain parses an explicit abstain result. | Adversarial minimal pairs plus legitimate paraphrase controls; report unsafe-accept and overblock rates by error type, not one aggregate accuracy. |
| P0 | Resolve the current gate's contrastive-paraphrase and sentence-boundary review flags without weakening its hard safety behavior. Keep source rollback until ambiguity is adjudicated. | Blindly label the four live replay cases plus held-out safe and unsafe controls; compare selective clause alignment or source-local restoration against the present conservative gate, including overblock and unsafe-accept rates. |
| P1 | Evaluate an optional pinned Kiwi morphology/sentence-span backend against the dependency-free baseline. Preserve original offsets and text. | Cross-platform packaging/license review, startup/memory/latency measurements, and a genre-diverse annotated set. The 14 designed examples in research C are insufficient. |
| P1 | Add genre/audience selection and quote-aware document register checks; calibrate diagnostic suggestions from licensed examples. Current style findings fired on only one of the 20 blog inputs, so expand their coverage only after measuring precision and no-edit controls. | Blinded reader preference and meaning-preservation comparison against no-edit and current engine; do not use authorship-detector AUC. |
| P1 | Test bidirectional Korean NLI or other semantic reranking only after hard anchors, with neutral/low-confidence abstention. | Held-out Korean edit data and stress cases for lexical overlap, negation, role swaps, and pragmatic changes; measure false acceptance of unsafe edits. |
| P2 | Extend long-document entity, terminology, timeline, and modality continuity checks. | Office and TXT/MD document-level contrasts including safe subject ellipsis and paragraph references; no structure or formatting regressions. |
| P2 | Broaden lexical/collocation suggestions with licensed dictionaries and usage corpus evidence. | Each rule documents a trigger, counterexample, genre boundary, attribution, false-positive rate, and opt-out/no-edit behavior. |

## Release gates and known limitations

Do not describe the current regex guards as semantic proof. The antonym list is intentionally small, sentence alignment is heuristic, and topic/focus changes can be context dependent. A passing Office package check preserves supported structure, not identical pagination. Keep unknown or conflicting analyses as source text. The Windows-only desktop regression and broad Korean-reader study remain outstanding. Re-run the K baseline whenever its imported runtime file changes; hashes and confusion matrices are revision-specific. Publish naturalness claims only after a predeclared, genre-stratified human evaluation with meaning preservation reported separately.

## Update, 4 October 2026

The 3 October prototype was reviewed, re-measured and revised; the record is [EVALUATION-2026-10-04.md](../research/super-sejong/EVALUATION-2026-10-04.md). The following items above are now done in the working tree:

- The semantic ledger was replaced by an event-based guard set with explicit frames for negation, ability, deontic force, hedges, certainty, quantifiers, bounds, participant roles and about 45 lexical axes.
  - Overblock / missed on a set it was never tuned on: 11.7% / 18.3%. The prototype measured 38.3% / 40.0% on the same set.
  - All 555 cross-author pairs are a regression test.
- Kiwi was evaluated and not adopted for the runtime (cost without an accuracy gain).
- A particle-agreement check repairs mismatches a rewrite introduced and blocks the remaining certain ones.
- Long-document `change_rate` is now linear in practice: 85k chars went from >120 s (timeout) to 5.3 s.
- The style diagnostics now have 15 rules, each measured against human and LLM corpora. Rules that fired as often on human prose were rejected.

Revised priorities:

| Priority | Change | Evidence required |
| --- | --- | --- |
| P0 | Deployment safety. Python stages are read from the working tree per job, and `npm run test:e2e` rebuilds the `dist/` that the watchdog runs. Separate the served tree from the development tree, or at least snapshot the engine at start-up. | The served engine does not change when the working tree is edited; a test pins this. |
| P0 | Run `SUPER_SEJONG_MODE=shadow` (or enforce) on real traffic and read `hardFailureCounts`, `shadowFailureCounts`, `repairedParticles` and `styleFindingsBefore/After`. | Per-code failure rates on production text, compared with the constructed-set rates. |
| P0 | Blinded native-reader judgments of meaning preservation and naturalness, including no-edit controls. Unchanged from 3 October and still the main gap. | At least three readers per pair; disagreement kept. |
| P1 | Extend lexical axes from rejected-chunk and shadow codes, not from intuition. About one meaning change in five still passes on the independent set, mostly through antonyms outside the axes. | Each new axis carries preserving controls; overblock on the independent set does not rise. |
| P1 | Register drift and document style sheet (prototyped by the discourse track, not shipped). | False-positive rate on real rewrites measured in shadow first. |
| P2 | Comma rules per genre (the only feature that separates human and LLM Korean in all three KatFish genres). Do not target the human median for poetry, where it is zero. | Per-genre held-out AUROC and a no-edit control. |
| P2 | Wire the 284-entry lexicon into suggestions only after native-editor review of the 99 author-knowledge entries and a licence check. | Per-entry provenance and false-positive rate. |
