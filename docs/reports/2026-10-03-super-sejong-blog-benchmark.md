# Super Sejong Engine: paired benchmark on 20 Korean blog posts

3 October 2026. This is a service-path ablation and a targeted safety probe, not a Korean naturalness validation study.

## Corpus and sampling

The source was the public [wisdom_jhk Naver blog](https://blog.naver.com/wisdom_jhk). Its prologue displayed 28 unique post IDs when sampled. A Fisher–Yates shuffle of those 28 IDs, using a 32-bit linear-congruential generator initialized with `20261003` (`state = 1664525 * state + 1013904223`, modulo `2^32`; `j = state % (i + 1)`), selected the first 20 IDs. Repeating the shuffle against the fetched prologue reproduced all 20 selections. The blog showed 456 total posts, so this is random **within the 28 prologue-visible posts**, not a uniform sample of all 456. The frame favors recent administrative guidance and includes some older school-violence posts.

The selected public `PostView.naver` pages were fetched for corpus extraction. The input comprises visible text and quotation components inside `.se-main-container`; image text, link previews, maps, tags, and the post title were excluded. Zero-width formatting characters were removed. The same prepared body was sent to both arms. The 20 bodies total 55,683 Unicode code points; median length is 2,868.5 (range 1,914–3,155). Source and output prose are kept outside the repository; the [sample manifest](2026-10-03-super-sejong-blog-sample.json) records all 28 frame IDs and the selected post IDs, URLs, titles, character counts, and full source hashes without reproducing article text.

## Paired service-path protocol

Both arms use the current working tree's text-file transformation pipeline, Codex CLI `gpt-5.6-sol` at `medium` reasoning effort, automatic routing, one active job at a time, and the same prepared source for a given ID. All posts route to one body chunk. Execution order alternates by post to reduce a one-sided time trend. Results are saved after each arm. The older, manually chunked pilot was excluded from every result below.

**Existing-engine ablation:** The prompt omits only the Super Sejong style-findings block. The Python gate disables only `changed_polarity`, `changed_sentence_modality`, `changed_lexical_polarity`, and `changed_participant_roles`; all other current service safeguards, including quantity, quote, name, sentence-loss, restoration, retry, and rollback logic, remain shared. **Super Sejong:** The current prompt and all four checks are enabled. This isolates the incremental Super Sejong implementation in the current tree; it is not a comparison with a historical release binary. Model calls are stochastic and unseeded, so differences between separately generated outputs cannot by themselves establish a causal quality gain.

Operational outcomes are completed jobs, final source preservation versus any change, wall time, Codex calls, retries, and chunk rollbacks. A Unicode `SequenceMatcher` ratio describes edit distance from the original; it is **not** a naturalness score. Final outputs are also replayed through the same full Super Sejong gate to identify review flags, not to assert independently adjudicated semantic errors.

## Live results

All 40 arm runs completed without execution errors. Each arm used the same model and effort for a given post, with one body chunk per post. The [machine-readable metrics](2026-10-03-super-sejong-blog-metrics.json) include every post's latency, calls, retries, rollbacks, accepted-change status, edit distance, and replay flags; they contain no article body or generated prose.

| Metric across 20 posts | Existing-engine ablation | Super Sejong |
| --- | ---: | ---: |
| Completed jobs | 20 | 20 |
| Median wall time per job | 69.4 s | 76.7 s |
| Mean wall time per job | 86.3 s | 82.1 s |
| Total wall time | 1,726.5 s | 1,642.3 s |
| Codex calls / retries | 29 / 9 | 33 / 13 |
| Final outputs different from source | 17 | 17 |
| Rolled-back chunks | 3 | 3 |
| Median source edit distance, character sequence ratio | 0.670% | 0.368% |
| Final outputs flagged by full Super Sejong gate replay | 4 | 0 |

In paired order, Super Sejong finished faster on 11 posts and the existing-engine ablation on nine; the median within-post difference (Super Sejong minus existing) was −10.0 s. This differs from subtracting the two arm medians because medians of paired differences and differences of medians are distinct statistics. The aggregate mean difference was −4.2 s per post, with substantial variation across model calls; this experiment does not establish a dependable speed advantage. Both arms changed 15 of the same posts; each alone changed two, and neither changed one.

The four replay flags on existing-engine outputs are **review signals**, not four proven meaning errors. A manual check of triggering spans found sentence-boundary changes and contrastive paraphrases such as a negative-copula construction recast as an additive or comparative one. Some preserve the apparent claim while others change emphasis or modality. The current surface-count gate intentionally abstains on those cases; a blinded semantic adjudication with acceptable-paraphrase controls is needed to estimate its overblock rate. Zero flags in the Super Sejong arm partly follows from enforcing that same gate during generation and therefore is not an independent accuracy measurement. Style findings were present in only one source post, so the live contrast largely concerns verification rather than the quality of Korean style guidance.

| Post ID | Source chars | Existing seconds / calls | Sejong seconds / calls | Final changed, existing / Sejong | Existing output replay |
| --- | ---: | ---: | ---: | :---: | :--- |
| [224430121623](https://blog.naver.com/wisdom_jhk/224430121623) | 2,765 | 19.4 / 1 | 68.0 / 2 | Y / Y | — |
| [223831095432](https://blog.naver.com/wisdom_jhk/223831095432) | 2,834 | 96.3 / 1 | 108.2 / 1 | Y / Y | review flag |
| [224429088499](https://blog.naver.com/wisdom_jhk/224429088499) | 3,027 | 50.7 / 2 | 87.8 / 2 | Y / N | — |
| [224424763003](https://blog.naver.com/wisdom_jhk/224424763003) | 2,955 | 76.6 / 1 | 65.5 / 2 | Y / Y | — |
| [224417487008](https://blog.naver.com/wisdom_jhk/224417487008) | 2,863 | 53.3 / 1 | 89.0 / 2 | Y / Y | — |
| [224426833726](https://blog.naver.com/wisdom_jhk/224426833726) | 2,874 | 193.3 / 2 | 92.9 / 2 | N / Y | — |
| [224346212081](https://blog.naver.com/wisdom_jhk/224346212081) | 2,275 | 154.8 / 2 | 131.8 / 2 | N / Y | — |
| [224042992615](https://blog.naver.com/wisdom_jhk/224042992615) | 2,741 | 162.2 / 2 | 199.4 / 2 | N / N | — |
| [224425687796](https://blog.naver.com/wisdom_jhk/224425687796) | 3,015 | 153.2 / 2 | 137.6 / 2 | Y / Y | — |
| [224424492063](https://blog.naver.com/wisdom_jhk/224424492063) | 2,955 | 51.8 / 1 | 27.5 / 1 | Y / Y | review flag |
| [224203838093](https://blog.naver.com/wisdom_jhk/224203838093) | 1,914 | 54.1 / 1 | 45.2 / 1 | Y / Y | — |
| [224374972689](https://blog.naver.com/wisdom_jhk/224374972689) | 2,983 | 103.8 / 2 | 108.3 / 2 | Y / Y | review flag |
| [224430442212](https://blog.naver.com/wisdom_jhk/224430442212) | 3,051 | 32.6 / 1 | 33.9 / 1 | Y / Y | — |
| [224423687749](https://blog.naver.com/wisdom_jhk/224423687749) | 2,800 | 85.4 / 2 | 54.3 / 1 | Y / Y | — |
| [224422386089](https://blog.naver.com/wisdom_jhk/224422386089) | 3,155 | 25.0 / 1 | 54.2 / 2 | Y / Y | — |
| [224423571743](https://blog.naver.com/wisdom_jhk/224423571743) | 2,985 | 50.1 / 1 | 24.5 / 1 | Y / Y | — |
| [224428125730](https://blog.naver.com/wisdom_jhk/224428125730) | 2,559 | 125.4 / 2 | 85.4 / 2 | Y / N | — |
| [223773934750](https://blog.naver.com/wisdom_jhk/223773934750) | 2,063 | 125.4 / 1 | 150.5 / 2 | Y / Y | review flag |
| [224427917810](https://blog.naver.com/wisdom_jhk/224427917810) | 2,817 | 62.2 / 2 | 45.9 / 2 | Y / Y | — |
| [224419408694](https://blog.naver.com/wisdom_jhk/224419408694) | 3,052 | 50.9 / 1 | 32.4 / 1 | Y / Y | — |

## Targeted negation probe and code correction

One deliberately meaning-reversing substitution was made in a copy of each of the 20 blog bodies: `할 수 있습니다 → 할 수 없습니다`, otherwise `아닙니다 → 입니다`, otherwise `해야 합니다 → 하지 않아도 됩니다`. These 20 constructed positives test specific negation/possibility failures, not the prevalence of real model errors or the false-positive rate. The existing-engine gate aborted 0/20; the initial Super Sejong implementation aborted 14/20. The six misses all involved contracted negative-copula `아닙니다`. After recognizing `아닙니다` and attributive `아닌`, the corrected Super Sejong gate aborted 20/20. [Per-post probe results](2026-10-03-super-sejong-negation-probe.json) contain only IDs, mutation types, and gate codes. The original 36-case polarity research probe was rerun against the revised implementation and its counts stayed unchanged; its implementation hash is updated in [research axis K](../research/super-sejong/K-polarity-signature.md).

The live pilot also showed an overblock: changing the spacing of prohibitive `안됩니다` to `안 됩니다` was incorrectly counted as an added negative cue. The gate now treats the attached spelling `안됩니다` as a negative surface, so this spacing-only correction does not look like a polarity flip. This is a preservation check, **not** a blanket spelling replacement. The [National Institute of Korean Language](https://m.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=216&pageIndex=1&qna_seq=308650) distinguishes the lexical word `안되다` from the spaced negation `안 되다`; meaning and context determine the spelling.

## Interpretation limits

The source texts come from one writer and topic cluster, and no blind native-reader naturalness or semantic labels were collected. Style findings occurred in only one of the 20 original bodies, so this corpus mainly tests the semantic gate and the service's tendency to leave already edited prose alone. The injected negation probe is intentionally favorable to a negation-sensitive gate and has no negative controls; its 20/20 detection must not be advertised as general recall or accuracy. Gate replay flags require human review. Latency reflects sequential live CLI calls and provider variability rather than a controlled load test. No claim of better Korean naturalness follows from these numbers alone.
