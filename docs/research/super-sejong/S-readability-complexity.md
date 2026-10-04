# Super Sejong Engine: Korean readability and sentence complexity

Research note, 2026-10-03. This note distinguishes reading-level prediction for a defined audience from editing adult Korean prose for clarity and naturalness. The accompanying probe produces transparent descriptors, **not** a readability grade or quality score.

## Primary evidence and population boundaries

| Opened primary source | Evidence | Transfer boundary |
| --- | --- | --- |
| [Lee (2020), *A Study on the Development of a Formula for Measuring Difficulty of Korean Reading Texts*, KCI original record](https://kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002560113) | The study sampled **160 reading texts from four Korean textbooks**, examined vocabulary difficulty, grammatical difficulty, and sentence length against textbook grade, and compared a regression formula with expert ratings. The abstract reports that grammar and vocabulary together best explained the textbook grades. | This is a Korean-as-a-foreign-language textbook population. A coefficient or grade label from it cannot be assumed valid for native adult letters, fiction, legal prose, or our service's user text. The accessible publisher record provides an abstract, not the full model validation details. |
| [Choi (2005), primary journal record](https://journal.kci.go.kr/kosim/archive/articleView?artiId=ART001096488) | In the journal abstract's comparison of models for primary and secondary school texts, formulas tailored to narrower age ranges worked better; different features were useful for primary versus secondary material. | The accessible evidence here is the publisher's abstract, not a checked full-text model validation. Its textbook findings do not establish a universal threshold for adult writing. |
| [National Institute of Korean Language (NIKL), 2013 public-language teaching material](https://www.korean.go.kr/front/reportData/reportDataView.do?mn_id=&pageIndex=2&report_seq=752&searchOrder=) | The [PDF's sentence-length guidance, printed p. 132](https://www.korean.go.kr/common/download.do?c_file_name=1e6de9c9-37a3-4505-9d7d-387be3eb86f7_0.pdf&file_path=reportData&o_file_name=%EB%B0%94%EB%A5%B4%EA%B3%A0+%EC%89%AC%EC%9A%B4+%EA%B3%B5%EA%B3%B5%EC%96%B8%EC%96%B4.pdf), considers overly long sentences with too many ideas *and* overly short, under-informative sentences problematic; a long, grammatical sentence whose ideas are tightly connected can still be appropriate. | This is public-language guidance, not a validated numeric formula. “Shorter” is not a monotonic objective. The report landing page identifies the material as NIKL's training resource. |
| [NIKL (2020), press-release standardization report](https://www.korean.go.kr/front/reportData/reportDataView.do?mn_id=&pageIndex=1&report_seq=1044) | In the attached PDF's “sentence length” section (printed pp. 100–101), the report recommends compact sentences, appropriate connectors, and avoidance of noun strings produced by deleting needed particles/endings. It frames length as a communication issue alongside information order and visual presentation. | Its example “three lines” is a layout-dependent editorial recommendation for press releases, **not** a portable character count. It should not govern literary rhythm or all adult prose. |
| [Moon, Lee, and Cho (2022), study of Korean-language public-health materials](https://formative.jmir.org/2022/3/e30085) | The authors explicitly acknowledge that they used one readability tool, did not test actual readers, and omitted layout, figures, and video from the analysis. | Even an application of a tool to Korean-language health material cannot establish comprehension from a formula alone. We do not adopt its health-domain grade target for general writing. |

The source-based conclusion is narrower than “short sentences are good.” Readability depends on the *reader*, familiar vocabulary, grammar, purpose, document design, and what ideas must be related. For the Super Sejong Engine, a descriptor should trigger a review question: “Does this span burden the intended reader?” It should not silently shorten a source sentence or erase a dependent clause that carries a condition, exception, or contrast.

## Measurement design: explainable dimensions, no grade

The [probe script](scripts/S_readability_probe.py) uses only the Python standard library and eight AI-assistant-written examples. Its descriptors are deliberately observable:

- **Orthographic spans:** split only after `.`, `!`, or `?` followed by whitespace. A headline with no terminal punctuation remains one span; a decimal `3.5` is not split at its internal dot.
- **Eojeol:** whitespace-separated units. This is not a morpheme or word count and changes with spacing conventions.
- **Hangul syllable blocks:** Unicode precomposed Hangul characters (`가`–`힣`) only. Numerals, Latin letters, jamo, and punctuation do not contribute.
- **Mean/max eojeol and mean Hangul blocks per span:** length descriptors, not comprehension probabilities.
- **Commas and connective-cue hits:** a literal comma count and a narrow regex for selected endings. Cue hits are **not** a parser's count of subordinate clauses. It deliberately misses productive **-고**, which is ambiguous as a raw character sequence, and can misread lexical endings.

The script intentionally has no coefficients, grade mapping, risk threshold, or claim to implement Lee's or Choi's formula. Their methods depend on vocabulary and grammar grading resources and study populations not present in this small probe.

Run exactly:

```sh
python3 docs/research/super-sejong/scripts/S_readability_probe.py
```

The embedded `SAMPLES` list is canonically serialized with `json.dumps(SAMPLES, ensure_ascii=False, sort_keys=True, separators=(',', ':'))` and encoded in UTF-8. Its SHA-256 was **`55a4166ca245e873bf8565d67619a8933f603dbb13395967ea82371e67673bdd`** when measured. All texts are original constructed examples by an AI assistant; no textbook, NIKL, journal, or user text is stored or processed.

| Constructed example | Orthographic spans | Eojeol | Hangul blocks | Max eojeol in one span | Narrow connective hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| `notice_split` | 2 | 11 | 31 | 6 | 1 |
| `notice_joined` | 1 | 12 | 35 | 12 | 2 |
| `report_split` | 2 | 7 | 22 | 5 | 0 |
| `report_joined` | 1 | 11 | 35 | 11 | 1 |
| `technical_short` | 1 | 3 | 6 | 3 | 0 |
| `narrative_long` | 1 | 12 | 28 | 12 | 0 |
| `headline_fragment` | 1 | 4 | 8 | 4 | 0 |
| `decimal_boundary` | 2 | 4 | 10 | 2 | 0 |

These outputs verify the counting procedure on the fixed examples; they do **not** validate a readability theory. The public-notice pair differs not only in span count but also in politeness and causal framing. The report pair differs in word choice and passive/reporting style. Therefore even these adjacent examples cannot serve as a controlled study of length alone. The short `p값` sentence can be opaque to a reader unfamiliar with statistics; the longer sensory narrative may be easy for its intended reader. Neither conclusion can be proved by the displayed counts. The headline is intentionally a fragment; a punctuation-based sentence metric will call it one span despite lacking a complete finite sentence.

## Proposed product research, not a deployed rule

1. **Define audience and genre before calibration.** Separate public notices, customer replies, work reports, academic abstracts, literary prose, dialogue, and headlines. Do not compute one cross-genre mean or universal target.
2. **Keep the feature vector separate.** Record span length distribution, segmentation confidence, morphology-informed connective/ending complexity, lexical familiarity relative to an approved frequency resource, and information density. Display which dimension changed. Do not compress these into an opaque 0–100 “human-like” score.
3. **Evaluate source-preserving alternatives.** For a candidate split or simplification, retain all conditions, negations, quantities, actors, and discourse relations. Compare source and edited versions by blind Korean readers representing the intended audience. Ask both comprehension questions and naturalness/appropriateness judgments; preserve disagreement.
4. **Use matched minimal contrasts.** Test long but well-formed sentences against needlessly nested ones; short technical jargon against longer plain-language explanations; legitimate noun phrases against harmful particle deletion; literary cadence against monotonous sentence chopping. Match content as tightly as possible and keep a “no edit” option.
5. **Report per-group uncertainty.** Estimate rater agreement, confidence intervals for comprehension, and false-positive rates by genre/register. Evaluate whether a diagnostic actually changes editor decisions and reader outcomes. A formula developed on learner textbooks should be revalidated from scratch before extrapolation to native adults.

The practical near-term research prototype is therefore a **non-scoring complexity profile**: show the distribution of orthographic span lengths and let an editor inspect the longest spans in the context of the declared genre; show literal connective-cue matches as uncertain review candidates; and preserve the original until a meaning-safe edit is available. Neither the eight examples nor the cited studies establish a product threshold for these descriptors. Any proposed threshold remains a hypothesis until genre-matched reader testing supports it.

## Limitations and rights

- The eight examples are authored by an AI assistant, chosen to illustrate cases, and have no reader ratings, random sampling, or statistical power.
- The regex is not a Korean sentence segmenter or morpheme analyzer; abbreviations, quotations, ellipses, line breaks, URLs, nonstandard spacing, decomposed jamo, and **-고** constructions can make counts misleading.
- The [NIKL report page](https://www.korean.go.kr/front/reportData/reportDataView.do?mn_id=&pageIndex=1&report_seq=1044) marks its publication under Korea Open Government License type 4 (attribution, noncommercial, no derivatives). It was read and paraphrased for this research; its text is not redistributed or used as training data here. The [2005 journal record](https://journal.kci.go.kr/kosim/archive/articleView?artiId=ART001096488) also states noncommercial, unadapted reuse, while the [2020 KCI record](https://kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002560113) provides no CC license information. Source papers do not license their underlying textbook excerpts. Check current and dataset-specific terms before any future ingestion.
