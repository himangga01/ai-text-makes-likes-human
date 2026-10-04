# sejong-bench: the independent scorer for Super Sejong v2

WP-15a of `docs/research/super-sejong/v2/DESIGN.md` (section 7, 8.2 WP-15). A port of T7's scorer
(`prototypes/T7_score.py`, `T7_voicefeat.py`, report `tracks/T7.md`) that scores a writer's output
against the seed benchmark (`benchmark/seed_benchmark.jsonl`, `seed_composites.jsonl`,
`seed_schema.json`). Deterministic checks only: no model call, no judge, no network.

**It imports no engine code.** Nothing from `engine_runtime/` or `src/`, and not the engine's
splitter, aligner or voice classifier either: a judge that shared code with the engine would stop
being independent (T7 section 3.1). `tests/skills/test_sejong_bench.py` fails on any such import,
relative import, `importlib` call or `sys.path` hack. Standard library only; Kiwi is optional.

## Files

| File | Role |
|---|---|
| `score.py` | `score_item`, `score_natural`, `aggregate`, `metrics_record`, seed loading, CLI |
| `voicefeat.py` | per-sentence voice features (level, ending class, honorifics, humble forms, first person); Kiwi or regex backend |
| `bench_text.py` | sentence segmentation and the monotone alignment (character-bigram Dice) |
| `bench_io.py` | the `$BENCH` write guard, the no-text metrics guard, hashes |
| `damage.py`, `selftest.py` | metamorphic writers and the self-test (not part of the judge hash) |

## Run it (product Python)

```
export PYTHON_COMMAND=/Users/wisdom/.hermes/hermes-agent/venv/bin/python
export BENCH=/some/dir/outside/any/git/work/tree        # default: the session scratchpad's bench/
$PYTHON_COMMAND scripts/sejong-bench/score.py selftest [--write]
$PYTHON_COMMAND scripts/sejong-bench/score.py score --outputs $BENCH/private/arm-a.jsonl --tag arm-a --arm A [--include-composites] [--fix-colloquial]
$PYTHON_COMMAND scripts/sejong-bench/score.py natural --manifest $BENCH/private/drafts.jsonl --tag drafts-a
$PYTHON_COMMAND scripts/sejong-bench/score.py hashes
```

`--backend auto|on|off` (before the subcommand) or `SEJONG_BENCH_KIWI=auto|on|off` picks the voice
backend: Kiwi if `kiwipiepy` imports (`auto`, the default), Kiwi or an error (`on`), regex only
(`off`). The backend name is stored in every metrics record; pin one for a sealed run.

- `--outputs`: JSONL, one `{"id": "SSB-017", "output": "..."}` per seed id. It is the writer's text:
  keep it under `$BENCH/private/` (this module never writes there) and never in the repository; a path
  inside the repository is refused. Ids that are not seed ids stop the run; seed ids without an output
  are counted as `records_without_output`.
- `natural`: scores rewrites of real text that has no gold (an owner draft, an already-processed post).
  `--manifest` is JSONL of `{"id", "source": path, "output": path}` (or `--source`/`--output`); files are
  opened read-only and read into memory. The source is its own gold: every prose sentence is a clean
  sentence, quotations, CMC tokens and 할께-type spellings found in it are protected, and every sentence
  with a CTA force above 0 is an explicit CTA. Without `--id` the id is `N-<first 12 hex of sha256(source)>`.

## What is scored (per record; all counts)

| Metric | Meaning |
|---|---|
| `spans[].status` | per injection: `FIXED_EXACT` (aligned sentence equals gold or an acceptable fix), `FIXED_PROBABLE` (defect regex gone and Dice to gold at least 0.6), `REWRITTEN_ADJUDICATE` (for a judge), `UNFIXED` (defect regex still matches), `DELETED` (no aligned sentence). The headline counts `primary` injections only: high confidence, not genre-dependent, not an LLM tell, and the gold fix leaves the sentence's voice unchanged. |
| `clean_sentences_touched` / `touched_sentence_index` | collateral edits: prose sentences without an injection that changed, split away or vanished |
| `voice_violations`, `voice_violations_by_feature` | per aligned sentence, any difference in level, ending class, honorific multiset, humble forms or first-person markers; no document register (OD 1). Sentences whose gold fix itself changes voice (사물 존칭 -시- removal, 하실게요 to 해 주세요; OD 4) are counted apart as `exempt_voice_conflicting_fix` |
| `protected_tokens_changed`, `optin_colloquial_fixed` | 할께-type spellings and CMC tokens (ㅋㅋ ㅎㅎ ㅠㅠ ^^ ~) are kept by default, so a changed one is over-editing (OD 2). `--fix-colloquial` scores the opposite expectation on the same items (kept: not fixed; removed without the fix: changed) |
| `quotes_changed` | quotations must stay verbatim |
| `cta[]`, `cta_invented_sentences` | per explicit CTA: `present`, `weakened`, `strengthened` by the force heuristic `force_of` (0 to 4); CTA sentences that appear in a CTA-free item |
| `invariants`, `invariants_violated(_ids)` | regex tier of the item's meaning invariants (`require_all`, `forbid_any`) |
| `numbers_dropped`, `numbers_added` | digit tokens missing from or new in the output (works on text without a ledger) |

`aggregate()` sums them; the summary file also reports over-editing on records that should come back
unchanged (natural controls, voice traps) and breaks the totals down by item type and genre.

**Not scored here** (separate tiers, T7 section 4): a Kiwi audit of meaning, blinded LLM judges,
human adjudication of `REWRITTEN_ADJUDICATE`. The regex meaning tier misses role swaps (T07 and T09
in the self-test), so it is a floor, not the meaning outcome.

## What is written, and where

Only to `$BENCH` (`metrics/<tag>.jsonl`, `metrics/<tag>.summary.json`, `selftest/`). `resolve_bench()`
refuses a directory inside the repository or inside any git work tree (a `.git` in it or in an
ancestor), and `bench_path()` refuses `..` and absolute parts. Every record passes
`check_metrics_record()` before it is written: only `null`, booleans, numbers and printable-ASCII
strings of at most 120 characters, so no Korean text (a draft, a model output, a seed sentence) can be
persisted by this module even by mistake. A record carries ids, sha256 of input, output and gold,
character counts, the scorer hash (`bench_io.scorer_sha256()`, over the judge's own source files),
the voice backend, and the counts above. The seed set may live in the repository (original text); model
outputs and Hermes drafts may not.

## Self-test (T7 section 7, reproduced)

`selftest` runs five writers over the 206 seed items and the eight damage writers, and fails (exit 1)
on any difference from T7's numbers. With Kiwi 0.24.0 and with the regex backend it prints:

| Writer, scored in the default configuration | Result |
|---|---|
| identity | primary fixed 0/92; 0 changed outputs; 0/438 clean sentences touched; 0/571 voice violations (7 exempt) |
| gold | primary fixed 92/92 (142/142 `FIXED_EXACT`); 115 changed; 0/438 touched; 0/571 voice; 0/21 quotes; 0/28 protected tokens; CTA present 46/46; invariants violated 0/40 |
| gold plus the opt-in colloquial fix, default config | over-editing: 10/438 sentences touched, 10/28 protected tokens changed, 1/21 quotes (the fix inside a quotation) |
| the same, option ON | protected tokens changed 1/28, opt-in fixes 9 |

| Damage | Detected |
|---|---|
| ending flattened (거든요/더라고요 to 습니다) | 11/11 |
| first-person marker dropped | 17/17 |
| honorific -시- dropped | 3/3 |
| explicit CTA replaced | 35/35 |
| collateral edit | 202/202 |
| colloquial or CMC change | 14/14 |
| sentence level changed | 134/140 (the 6 misses are the exempt voice-conflicting fixes: J60 J61 J62 J64 A10 V11) |
| meaning flip (regex tier) | 20/22 (T07, T09: role swaps) |

It also checks what the port added: the six composite documents (identity 0 fixed, gold all fixed and
clean; D06 is the 18,597-character document that forces chunking), natural mode on the 206 seed texts
(identity clean; the same damages caught: 140/140, 11/11, 17/17, 3/3, CTA 40/40, collateral 205/205,
protected tokens 15/15), banded against full alignment on D06, and all 212 records against
`seed_schema.json` (full JSON Schema validation when `jsonschema` is importable, else the required keys). The CTA heuristic agrees with T7's hand-labelled ledger on 49/50 CTAs (A28 differs);
T7 wrote it after reading that ledger, so this is not an accuracy estimate.

## Backends, and what changed from T7

The numbers above are the same with both backends, but the features are not: the regex backend is an
approximation of Kiwi's tags. T7's regex fallback counted the colloquial ending 할께 as the honorific
particle 께, so correcting 할께 to 할게 read as a lost honorific (8 false violations with the opt-in
gold). This port fixes that and widens the -시- patterns (embedded 하시면, 주시기, 문의하신, 하실게요,
교수님이신), the first-person forms (제가, 내, 나에게) and the 께 exclusions (함께, 두께, 7시께).
Disagreement with Kiwi (sentences whose honorific or first-person features differ): 6 of 2,262 on the
seed texts and their damaged variants (in-sample: the regexes were tuned on them); 400 of 10,970 on
KatFish essays and Naver news (out of sample), of which 11 are honorific and 389 first-person, and 270
of those are Kiwi tagging 우리 where the regex does not (211 in 우리나라). On the scored self-test
outputs (1,474, default configuration) the voice result is identical for 1,469 and every other
field is identical for all of them. Remaining regex blind spots: a verb stem outside the listed ones
with an embedded -시-, and cities such as 충주시는. A sealed run should pin a backend; Kiwi is the
reference.

Other changes from `T7_score.py` (none alters a self-test number): the seed builder's `segment` and
`voice_profile` are ported into `bench_text.py` and `voicefeat.py` (the prototype imported the seed
builder); the quote mask is precomputed; alignment is exact up to 250,000 cells and banded beyond
(a band of `|n - m| + 24` around the line from the first to the last sentence pair; a 100,000-character text scores in about 0.4 s); under the opt-in
configuration a colloquial token that is removed without the fix counts as changed; `numbers_*`,
`touched_*`, natural mode, the metrics guard, the CLI and the summary are new.

## Limits

- The seed set is one LLM author's work, unreviewed by a native annotator, short items (median 57
  characters), a dev and pilot set, not a confirmatory one (T7 section 6).
- `force_of`, the regex meaning tier and the regex voice backend are heuristics. None of them is the
  meaning or quality outcome.
- The Tier C runner, the packer for blinded judges and the Hermes-draft spiker are WP-15b; this package
  is the frozen scorer they call.
