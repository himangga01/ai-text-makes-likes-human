# Super Sejong Engine: Review, Measurement and Revision, 4 October 2026

This record covers the review of the 3 October Super Sejong prototype and research corpus, five resumed research tracks, and the revisions they led to. Ten reviewers ran in parallel (two document reviews, three code reviews, five research tracks). The lead re-ran every claimed reproduction before accepting it. All numbers below were measured on this host (macOS, Apple Silicon). The pair sets were constructed by the authors named in each table; they are **not** production text, and **no Korean reader has rated any output**.

## 1. Findings that changed the engine

| Area | Finding (reproduced) | Change |
| --- | --- | --- |
| Meaning guards | The prototype blocked about half of ordinary paraphrases on an independent set and accepted most real meaning changes. Examples: "뿐만 아니라", "잘못", "어렵다→쉽지 않다" and "알지 못했다→몰랐다" were blocked; "안 갔어→갔어", "승인→반려", "올랐다→내렸다", "모든→일부", "이상→이하" and subject/object swaps passed. | Replaced by the event-based guard set (section 2). |
| Linguistics | 은/는 is an auxiliary (topic/contrast) particle, not a case marker; the synthesis and the code treated it as the subject. One-syllable nouns ("팀이") were invisible to role checks. | Topic particles no longer create role swaps by themselves; short nouns are read after a bare modifier ("상대 팀을"). The synthesis text is corrected. |
| Office path | Ordered-list equality of modal and short-negation cues rejected harmless clause reordering; a code reviewer measured 37.7% overblock with it kept. | In enforce mode, Super Sejong's sentence-aligned comparison replaces those checks. Shadow and off modes keep them, so shadow never weakens the Office gate. |
| Style hints | The quote-protection regex was quadratic: an unclosed “ in 50,000 chars took 0.87–4.7 s on the event loop. "집에 있어서" (locative + -어서) was flagged as translationese. Both original rules fired on about 3% of documents, with no human/LLM separation. | New diagnostics module (section 3). |
| Prompt context | Chunks of a split document were rewritten blind: the Python "chunk i/N, do not add transitions" header was written to disk but never delivered (`prepare_monolith_input.py` header vs `python-engine.ts`). | Chunk prompts now state the position and the document's dominant speech level. |
| Performance | `change_rate` used a quadratic character diff. Single-line paragraphs bypassed the line segmentation, and 10k+10k chars fell under the threshold: 20k repetitive chars took 86 s, and 85k exceeded the 120 s Python timeout after every model call had run. | Lines and sentences are segmented; unmatched blocks are bounded. 20k: 86 s → 1.4 s; 85k: >120 s → 5.3 s. Values changed by at most 0.0003 on 20 real-text comparisons (3k–60k chars). |
| Particles | No check for particle allomorphs left wrong by an edit (회의을, URL를, 10%으로). | Deterministic repair plus a gate (section 4). |
| Observability | Gate failure codes were parsed but never logged, and there was no way to disable or shadow the new guards. | `SUPER_SEJONG_MODE=enforce|shadow|off`; diagnostics now carry `hardFailureCounts`, `shadowFailureCounts`, `repairedParticles`, `styleFindingsBefore/After` (codes and counts only, no text). |

## 2. Meaning guards: three-author cross-evaluation

Three authors wrote pair sets independently: the code reviewer (395 pairs, tuned its v2 on them), the morphology researcher (120 pairs, tuned its own prototype on them), and the lead (40 pairs, written before seeing any candidate's results). Each candidate was then scored on every set. "Overblock" means a preserving pair was flagged; "missed" means a changing pair was accepted.

| Pair set | Prototype (3 Oct) | Morphology prototype, regex backend | Code reviewer v2 | **Shipped (v2 + lead fixes)** |
| --- | --- | --- | --- | --- |
| Lead, 20/20 | 50% / 75% | 50% / 45% | 25% / 30% | 5% / 0% (tuned on it) |
| Morphology researcher, 60/60 | 38.3% / 40.0% | 30.0% / 8.3% (own set) | 11.7% / 20.0% | **11.7% / 18.3% (never tuned on)** |
| Code reviewer, 207/188 | 27.1% / 68.6% | 29.0% / 52.7% | 3.4% / 0% (own set) | 3.9% / 0% |

The honest generalisation figure is the morphology researcher's set: about one paraphrase in nine is still sent back for a conservative retry, and about one meaning change in five still passes. The code reviewer's own blind pre-fix measurement agrees in magnitude (overblock 10.6%, unsafe-accept 16.7%).

The lead's fixes are general rules, not sentence patches: short negation with any predicate ending, with locative 안 excluded (상자 안 자료); double negation that means obligation (~지 않으면 안 된다, ~지 않을 수 없다); 알지 못하다 = 모르다 and a know/not-know axis; inflected 늘린다/줄인다/올린다/내린다; 반드시 and 꼭 as certainty; 누구든 and similar as universal quantifiers; two-word participants (우리 팀 / 상대 팀).

The Kiwi analyser was evaluated and **not** adopted for the runtime:
- **Licence:** Apache-2.0 for 0.24.0 (0.23.2 was LGPL).
- **Cost:** about 0.9 s cold start and 0.4–0.6 GB per process, while the pipeline spawns Python per gate. Windows packaging adds about 130 MB.
- **Accuracy:** most of the measured gain came from the cue categories, not the analyser.

It remains useful for offline evaluation. All 555 pairs ship as `tests/skills/data/super_sejong_pairs.json`, and `tests/skills/test_super_sejong_guards.py` fails if any set regresses past its recorded rate.

## 3. Style diagnostics

The new module (`src/engine/super-sejong.ts`, 15 rules) was measured on KatFish human and LLM essays and abstracts, plus Naver news and KLUE text as human controls (5.09M characters):
- **Aggregate rate:** the 13 added rules fire 4.97 times per 10k chars on human essays and abstracts, against 38.65 on LLM ones.
- **Documents with a finding:** 21% of human documents, against 76% of LLM documents.
- **Strongest rules (human / LLM per 10k chars):**
  - IMPORTANCE_FORMULA ("~하는 것이 중요합니다"): 0.34 / 9.46
  - CONCLUDING_SIGNPOST: 0 / 5.52
  - DEMONSTRATIVE_THROUGH ("이를 통해"): 0.09 / 4.89
  - CONNECTOR_RUN: 0.77 / 6.35
- **Rejected after measurement**, because human prose uses them as much or more: "에 의해", "로부터", "에 대해/대한", "을 가지다", "의" chains, "이러한", "~하고 있다".
- **PUBLIC_LANGUAGE_FRAME** is now limited to unambiguous frames: "~함에 있어서", "~하는 데 있어서", "~에 있어서는/의/도".

Prompt behaviour:
- Each finding carries its source excerpt and a one-line Korean guide for its rule.
- Hints are not sent on the conservative retry or on candidate review.
- Findings are counted before and after each chunk, so whether the hints change anything can now be measured from production diagnostics.
- Every 50,000-char adversarial shape runs in at most 37 ms.

These rates show that the rules separate the corpus. They do **not** show that rewriting the flagged phrases makes Korean read better. That still needs blinded reader judgments.

## 4. Particle (josa) agreement

`engine_runtime/super_sejong_josa.py` uses Unicode syllable arithmetic (final consonant = (code − 0xAC00) mod 28, ㄹ = 8) and pronunciation tables for digits, Latin letters, units and symbols.

| Measure | Result |
| --- | --- |
| Constructed cases, non-Hangul stems (acronym, number, unit, bracket) | 80/80, 39/39, 12/12, 9/9 |
| Numeral reader against an independent spell-out | 40,035 numbers, 0 mismatches |
| False alarms on 4.81M chars of human text, "certain" level | 0 strict false positives; the flags found real source typos (참석를, 효과을, 100%이) |
| Injected-error repair | 1,672 of 1,672 restored exactly |

How it is used:
- Only mismatches the rewrite introduced are acted on; errors already in the writer's text are left alone.
- The server restore step repairs them deterministically (`repairedParticles`).
- `verify` blocks a remaining certain mismatch (`josa_mismatch`).
- The Office path rejects instead of repairing, because edits map to formatting runs.
- No word list is bundled: the optional lexicon's licence is unverified. Without it, the checker covers non-Hangul stems and the unambiguous Hangul families. 이/가 and 은/는 after Hangul nouns are hint-level only, for example 작가, 사과, 고양이과.

## 5. Corpus findings that constrain future rules

- **Commas:** comma features are the only ones that separate human from LLM Korean in all three KatFish genres and for all four generators. Per-sentence comma share AUROC is 0.93 (essay), 0.77 (abstract) and 0.73 (poetry). The existing injected-comma stripper is supported, but human poetry's median is zero commas, so "match the human median" is not a valid target.
- **Genre-specific rules:** most other rules apply to one genre only. "수 있다 ≥4" fires on 14% of human essays vs 54% of LLM essays, but on 3.0% vs 2.9% of abstracts. Several upstream metrics are noise on this data: `da_streak_rate`, `deul_overuse_rate`, `double_particle_count`, `pronoun_density`.
- **Placeholder baseline:** `baseline_v2.json` is entirely placeholder, so its z-scores are meaningless. The "low TTR = AI-like" assumption is not supported: length-robust MATTR runs the other way.
- **Lexicon data:** the resumed lexicon track produced 284 entries — translationese 48, redundancy (겹말) 82, boilerplate 63, confusables 44, collocations 47. Each has provenance and a licence note.
  - Only the boilerplate family separated human from LLM text measurably.
  - NIKL's own translationese items fire more on professional human prose (news) than on LLM text, so they stay suggest-only.
  - 99 entries rely on author knowledge and need native-editor review.
  - The data is kept under `data/2026-10-04/lexicon/` for research; it is not wired into prompts.
- **Rhythm thresholds:** sentence-level rhythm signals did not separate the classes; document-level ones did. Proposed per-genre thresholds are recorded in `data/2026-10-04/rhythm_thresholds.txt`, but are not used yet.

## 6. Corrections to the 3 October documents

- **SYNTHESIS (particle description):** the claim that 은/는 ↔ 이/가 is a "safe recast" and that 은/는 → 을/를 moves a participant "from agent toward patient" is corrected. 은/는 is an auxiliary particle (NIKL Q&A 310153 and 333508, as cited in reports A and F).
- **Benchmark interpretation:**
  - With 20 posts, the paired time difference was −4.2 s, with a bootstrap 95% CI of (−19.7, +10.2).
  - The minimum detectable effect is about 22 s, and the call and retry differences are within noise (sign test p = 0.22).
  - The replay flags (4 vs 0) are circular, because the Super Sejong arm enforced the same gate during generation.
  - The negation probe was positive-only and was tuned on the same 20 mutations.
- **HANDOFF and code analysis:** they described an obligation guard on TXT/MD. At the time, `obligation_count` was used only on the Office path.
- **Research report spot checks:** about 75 cited URLs were opened, with no dead links and three content mismatches.
  - H: NIKL Q&A 332328 does not state the haeyo/hapsyo contrast attributed to it.
  - J: the label for NIKL Q&A 316366 is wrong.
  - G: NFKC of compatibility jamo silently produces broken syllables (NFKC('ㄱㅏㄱ') = '가' + U+1100), not '각'.
  - The four probe scripts reproduce their published hashes and numbers.

## 7. Limits and next evidence needed

- **No human judgments.** No blinded native-reader evaluation of naturalness or meaning preservation exists. Every rate above is over constructed or corpus-derived pairs.
- **Unseen vocabulary.** Antonyms and direction words outside the approximately 45 lexical axes are still accepted. Shadow-mode logs (`shadowFailureCounts`) and rejected-chunk codes are the intended data source for extending them.
- **Unmeasured rules.** The register-drift and document style-sheet checks prototyped by the discourse track are not shipped as gates, because their false-positive rate on real rewrites is unknown. Only the speech-level summary in the chunk prompt is used.
- **Deployment risk.** The Python stages run from the working tree, so editing `engine_runtime/*.py` changes live gate behaviour immediately. The TypeScript side changes only after a rebuild and restart. `npm run test:e2e` rebuilds `dist/`, which the hourly watchdog executes.
