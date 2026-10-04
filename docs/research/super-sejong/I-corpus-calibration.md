# Super Sejong Engine: corpus calibration and provenance audit

Research note, 2026-10-03. This note separates observed evidence, the small local probe, and a future human-subject or licensed-corpus study. It does **not** report a Korean human-versus-AI detector or estimate the prevalence of any style feature in either population.

## Question and target estimand

The useful product question is whether a proposed editing rule improves *perceived naturalness while preserving the writer's meaning*, within a stated genre and register. “Can a classifier identify an LLM?” is a different question. A correlation with corpus authorship can be caused by grade level, genre, prompt wording, document length, publication editing, or model family. It must not be presented as a universal Korean-language rule.

Let (Y(t,g,r)) be blind native-reader naturalness for text (t), genre (g), and register (r). For a proposed editing policy (E), estimate the paired difference (Y(E(t),g,r)-Y(t,g,r)) across **all eligible source texts** in the stated target population; an abstention returns the source and contributes zero change. Report the meaning-harm rate and abstention rate on that same population as separate primary outcomes. Naturalness gain *among only the accepted, meaning-preserving edits* is a useful secondary diagnostic, but selecting that subset after seeing edit outcomes can conceal harmful edits and overstate product benefit. Authors, prompts, and topics must be held out of tuning when feasible. These targets remain design proposals, not measured effects in this note.

## Source and rights audit

| Candidate | Directly verified content | Current obstacle for a reusable paired corpus |
| --- | --- | --- |
| [KatFish / KatFishNet, ACL 2025](https://aclanthology.org/2025.acl-long.1030/) and its [author repository](https://github.com/Shinwoo-Park/katfishnet) | Human and four-model texts across argumentative essays, poetry, and paper abstracts; repository exposes `essay.jsonl`, `poetry.jsonl`, and `abstract.jsonl`. The authors study spacing, part-of-speech combinations, and comma behavior. | The repository presents no explicit dataset license ([GitHub repository metadata](https://api.github.com/repos/Shinwoo-Park/katfishnet) reports `license: null` as checked). “Publicly viewable” is not a reuse grant. Human originals derive from other corpora, so upstream rights also need checking. No text was imported here. |
| [LREAD author repository](https://github.com/Shinwoo-Park/lread/) | Releases labeled Korean argumentative-essay evaluation phases and a rubric for human attribution; grade/persona and model are part of the design. | The [repository metadata](https://api.github.com/repos/Shinwoo-Park/lread) reports no license. The essays are one genre, not a general writing sample. No text was imported here. |
| [LEDE dataset card](https://huggingface.co/datasets/NeurIPS-2026-LEDE/LEDE-dataset) and [author code repository](https://github.com/DSAIL-SKKU/LEDE) | Generated news across Korean and English, multiple categories, models, and strategies. The dataset card marks the data CC BY-NC 4.0; the code repository has an MIT license. Human news sources must be obtained separately. | The code license does not extend the dataset license. The released generated texts alone do not form a matched human/AI comparison, and NC terms are a constraint for commercial product work. No text was imported here. |
| [AI-Hub data policy](https://aihub.or.kr/intrcn/guid/usagepolicy.do) and [AI-Hub FAQ](https://aihub.or.kr/aihubnews/faq/list.do?currMenu=146&topMenu=104) | The general policy describes application/identity steps, attribution, a stated training-use purpose, and restrictions on access, overseas transfer, and redistribution. The FAQ says trained derivatives may be used commercially with attribution but raw datasets may not be shared. | The policy, FAQ, and particular dataset terms must be reconciled before use; feature-analysis-only calibration may require clarification of the stated purpose. A public repository copy of AI-Hub source text should not be assumed freely redistributable. We did not apply for or download AI-Hub data. |

**Decision.** No candidate examined supplied a clearly reusable, paired, genre-matched Korean human/generated set that we could lawfully incorporate into this repository and product workflow without further review. We therefore ran the transparent constructed-style probe below. This is a conservative operational decision, not a legal opinion or a claim that private scholarship with these sources is forbidden.

## Local probe: constructed styles, not authorship labels

The [executable script](scripts/I_corpus_probe.py) embeds 16 short Korean texts on eight paired topics (meeting, delivery, rain, class, reservation, repair, library, walk). **All 16 were composed by an AI assistant for this probe.** `concrete` and `formulaic` name intended styles; neither label means “human” or “AI-generated.” Each text has two sentences. Pairs share a topic but differ in details, claims, and register; they are **not** meaning-matched source/edit pairs and cannot estimate an editing effect. We committed no external corpus or personal information.

Reproduce with standard-library Python 3:

```sh
python3 docs/research/super-sejong/scripts/I_corpus_probe.py
```

The script hashes `json.dumps(SAMPLES, ensure_ascii=False, sort_keys=True, separators=(',', ':'))` as UTF-8. For the measured sample set, SHA-256 is `da930c3247b21a0371a8db21b2cec5a38b0f307945a164b38484206ff31e2d8c`. The command prints the hash, group means, and all paired character ratios. Feature definitions are directly inspectable in `features()`: non-whitespace Unicode code points, whitespace-separated *eojeol*, regex-delimited sentences, literal ASCII comma count, a fixed five-item transition list, and eojeol type/token ratio. These are deliberately simple observables, not linguistic parses.

| Mean per 8 texts | Concrete style | Formulaic style |
| --- | ---: | ---: |
| Non-whitespace characters | 45.250 | 53.250 |
| Eojeol | 15.500 | 15.500 |
| Sentences | 2.000 | 2.000 |
| Characters per sentence | 22.625 | 26.625 |
| ASCII commas per 100 characters | 1.618 | 2.111 |
| Listed transitions per 100 characters | 0.000 | 1.888 |
| Eojeol type/token ratio | 0.992 | 0.984 |

The formulaic/concrete length ratio averaged **1.182**, and individual ratios ranged **1.022–1.415**. Even this topic-paired set has a substantial length imbalance. The transition difference is built into the examples (each formulaic paragraph uses *또한*), so it tests counting and provenance transparency, **not** whether transition frequency detects AI authorship. Type/token ratios near one are expected for such short passages and are not interpretable as lexical richness. Punctuation and sentence segmentation are heuristic; abbreviations, quotation, ellipsis, and multimodal markup would require a better segmenter. No significance test, accuracy, AUC, editing-effect estimate, or human/AI provenance claim follows from these 16 constructed texts.

## What the published evidence does and does not establish

The [KatFishNet authors' repository](https://github.com/Shinwoo-Park/katfishnet) reports punctuation-feature AUC values of 94.88 for essays, 73.10 for poetry, and 75.62 for abstracts in its stated unseen-model protocol. This **observed genre variation in one experimental design** argues against transferring a single punctuation threshold to every Korean writing task. The paper also compares spacing and POS features; those statistics are candidate diagnostics, not normative rules for writing. In particular, a poem may intentionally omit spacing or punctuation, and a polished official notice may legitimately contain regular connectives.

The [LEDE dataset card](https://huggingface.co/datasets/NeurIPS-2026-LEDE/LEDE-dataset) lists 21 models, 17 news categories, and four generation strategies. That diversity is useful for studying generation variation, but category, strategy, model, and source newsroom still need separate accounting. The card states the human originals are separate. Pairing generated news with arbitrary human essays would mostly compare genre.

## Protocol for defensible Super Sejong calibration

1. **Resolve rights and provenance before ingestion.** Record provider, dataset version/commit, file hash, permitted purposes, redistribution, retention, privacy restrictions, and human authorship/AI-generation evidence. Keep restricted raw text outside the product repository. Deletion and access controls follow the provider's terms.
2. **Define the product population.** Sample essays, customer messages, reviews, and formal documents separately; also stratify by audience, age/education where relevant, register, editing history, and length. Do not collapse those into one “natural Korean” norm.
3. **Build genuinely paired material.** Match topic, intent, facts, genre, audience, requested length, and source period. Preserve the prompt and generation settings. When human text is used as a source, separately document whether the generated text paraphrases, continues, or writes from the same outline. These are different tasks.
4. **Separate authors and prompts across splits.** Deduplicate near-copies before splitting. Hold out human authors, source collections, prompts, topics, and model families for distinct robustness checks. Publish the split construction and confidence intervals, not just one aggregate number.
5. **Measure edits, not only attribution.** Native Korean raters blinded to system identity should judge naturalness, register fit, and clarity with source/output presentation order randomized; meaning-preservation judgments also require access to the source and relevant context. Retain disagreements. Count abstentions and all harmful accepted edits in the full policy evaluation, then separately describe accepted edits. Explicitly test negation, numbers, named entities, honorifics, quotation, dialect, and poetry as safety cases.
6. **Use language features conditionally.** Estimate punctuation, ending, spacing, POS, and discourse-feature distributions *within* each genre/register and length bin. Compare candidate editing rules against no-edit and simple-baseline controls. Reject a rule if it harms meaning or a legitimate register, regardless of any detector score.

For the current engine, the safe near-term use is as a **diagnostic design**: identify repeated formulaic connectives and register monotony, propose local edits, then verify meaning. Do not make an authorship assertion or use a detector score as a naturalness objective. A licensed, independent human corpus and blind ratings are prerequisites for calibration thresholds.

## Limitations and open decisions

- The local set has a single AI-assistant author, intentionally stylized contrasts, eight topics, no independent human references, no human ratings, and no statistical power for generalization.
- Eojeol tokenization and regex sentence splitting are fragile; punctuation distribution varies by genre, editing policy, and publication medium.
- The examined candidates do not establish rights to republish original human passages here. Dataset-specific terms may change; recheck before any future download or deployment.
- Future inference should report per-genre intervals and failure examples, including texts whose “formulaic” style is required by accessibility, legal drafting, or institutional voice.
