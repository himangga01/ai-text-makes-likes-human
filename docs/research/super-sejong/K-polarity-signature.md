# Super Sejong Engine — Korean polarity-signature probe (research axis K)

Evidence and local probe rerun: 2026-10-03. The executable research artifact is [`scripts/K_polarity_probe.py`](scripts/K_polarity_probe.py). It **imports but does not modify** the current `engine_runtime/super_sejong.py` implementation. Its hand-written contrast set and regex rules are a transparent feasibility probe, not an accuracy benchmark or a product-ready Korean negation parser.

## Linguistic and NLP evidence opened

- [Jong-Bok Kim, *The Syntactic Structures of Korean*, Chapter 8](https://www.cambridge.org/core/books/abs/syntactic-structures-of-korean/negation-and-related-phenomena/ABFE84B5568EA3443AD3ED8615F2E512) describes pre-predicate **안/못** and post-predicate **-지 않다** as different structures; its examples distinguish **못** (inability) from **안** (negation). The probe's decision to normalize short and long forms only within the same cue category is an inference from that distinction, not a rule supplied by the chapter.
- [Jung et al., Thunder-KoNUBench, Findings of ACL 2026](https://aclanthology.org/2026.findings-acl.324.pdf) distinguishes short/long 안 and 못, prohibitive **-지 말다**, lexical complementary antonyms, and *local negation* in dependent or coordinated clauses. Its 4,784-item multiple-choice benchmark tested 47 LLMs; the authors report degradation under negation. The paper explicitly says its constructed negation task does not evaluate natural contextual understanding. Thus our pairwise rewrite gate still needs its own contextual Korean validation.
- [Sells, *Negation Scope and Negative Polarity Items in Korean*, 2005 author-uploaded paper](https://www.researchgate.net/publication/253978674_Negation_Scope_and_Negative_Polarity_Items_in_Korean) distinguishes short and long negation and lexically negative **없다/모르다**. Its discussion of **아무도**, **하나도**, and **밖에** shows why a cue count cannot represent negative-polarity-item licensing or quantifier meaning. The author-uploaded text was directly opened; this probe does not reuse its examples as data.
- [Park and Dubinsky, *Effects of Focus on Scope Relations between Quantifiers and Negation in Korean*, 2020](https://journals.linguisticsociety.org/proceedings/index.php/PLSA/article/view/4670) argues that focus marking interacts with the scope of quantifiers and negation. [Cheol-Woo Park, *On the Scope of Negation in Korean*, 2013](https://k-knowledge.kr/srch/read.jsp?id=285292193) relates scope to syntax and information structure in its abstract. Both are reasons to treat clause-index matching as an approximation, not a semantic analysis.
- [Changsoo Kim, *A Study on Korean Negation “an” and “anh”*, 2009](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001346094) analyzes short/long negation with quantifier scope and NPI licensing. This is a theoretical account, not a ready-made extraction algorithm.

**Lexical refusal is deliberately separate from grammatical negation.** A verb such as **거부하다** denotes an act of refusal; it is not interchangeable with **-지 않다**. We monitor it as a protected action-polarity cue because changing *거부했다* to *승인했다* changes the event, while *거부했다* to *거절했다* can be a contextually valid paraphrase. The small synonym class in this script is a hypothesis, not a dictionary-based semantic rule.

## Probe design

The comparison's baseline calls the product's `changed_polarity(source, candidate)` **without** its optional aligned clause pairs. The current function first compares counts of selected short and long negative surfaces over the whole input. When both sides contain the same number of detected short negatives, it also compares counters of `(안/못 cue, approximate predicate stem)` targets. With alignment, it can additionally compare counts within supplied pairs. The 36-case table therefore measures this one unaligned subcheck, **not** the product's combined drift decision. Other current guards inspect such things as sentence modality, selected lexical opposites, obligation cues, and participant roles; their contribution is not included in these metrics. The prototype instead splits at punctuation and contrastive **-지만**, then constructs an ordered list of clause signatures. Each signature is a sorted tuple of `(cue category, approximate predicate stem)` observations, including duplicates. It normalizes **안 V** with **V-지 않다** as `NEG`, **못 V** with **V-지 못하다** as `UNABLE`, records **V-지 말다** separately as a prohibited command, and watches lexically negative states and refusal/prohibition verbs. It retains multiple cues in a clause instead of reducing double negation to odd/even parity. Any signature mismatch is a *review flag*.

This is **not** a claim that a matching signature proves semantic equivalence. Regular expressions cannot derive the full scope of negation, resolve zero arguments, distinguish quoted speech from the narrator, analyze focus particles, or determine whether an apparent antonym is complementary. A mismatch can also be a harmless paraphrase. In a service, this signal would be one diagnostic input to the meaning-preservation gate, with uncertain cases kept unchanged or shown for human review.

The script includes 36 original, hand-labeled source–candidate pairs: eight surface morphology, six lexical events, six double-negation, six predicate/time scope, six contrastive clause, and four prohibitive-command cases. Gold `drift=True` means **polarity, inability, prohibited action, its target, or the time of a negated event is materially changed**. It is *not* a label for all factual, style, or register drift: for example, a change of politeness is labeled safe **for this focused task**. The labels were authored alongside the prototype, without independent annotation.

## Exact local output

Command run from repository root:

```sh
python3 docs/research/super-sejong/scripts/K_polarity_probe.py --summary
```

The 36-case set SHA-256 was `764be5373ea2f6ad2d0da9875c9b5a25d89c82ce904dc0b5fb421d1d822e7cc9`; the imported implementation file SHA-256 was `650ce18082f7075d063b645cacb4b507510382600fd8ab6d83c49eba56b098c6`. This is the implementation after the blog-benchmark negation-form corrections; rerunning the probe left its 36-case counts unchanged. **Positive** means the guard flags a potentially unsafe edit. TP is flagged drift; FP is a flagged safe pair under this task's labels; FN is unflagged drift. Precision and recall below are descriptive values **on these 36 authored pairs only**.

| Probe | TP | FP | FN | TN | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Current unaligned `changed_polarity` subcheck | 11 | 1 | 11 | 13 | 0.917 | 0.500 |
| Clause/predicate signature prototype | 21 | 2 | 1 | 12 | 0.913 | 0.955 |

| Category (cases) | Baseline TP/FP/FN/TN | Prototype TP/FP/FN/TN |
| --- | --- | --- |
| Morphology (8) | 4/1/0/3 | 4/0/0/4 |
| Lexical events (6) | 0/0/4/2 | 4/1/0/1 |
| Double negation (6) | 4/0/1/1 | 5/0/0/1 |
| Scope (6) | 2/0/2/2 | 3/0/1/2 |
| Contrastive clauses (6) | 1/0/2/3 | 3/1/0/2 |
| Prohibitive commands (4) | 0/0/2/2 | 2/0/0/2 |

Prototype **false positives**: `L6` (*자료가 없다* → *자료가 존재하지 않는다*) because lexical absence and compositional negation were not unified; `C4` because semantically corresponding contrastive clauses were reordered. Its **false negative** is `S3` (*오늘 안 간다* → *내일 안 간다*): the negation target is unchanged but the time of the negated event changes. These three examples show why morphology, clause alignment, and temporal interpretation need more than this regex signature. The current unaligned subcheck's false positive was `M6`; its false negatives were `L1`–`L4`, `D5`, `S1`, `S3`, `C1`, `C2`, `P1`, and `P3`. Some of those may be flagged by other current product guards, but this probe did not measure their combined result. The full command without `--summary` prints every sentence, gold label, cue signature, and prediction for auditing.

## Limits and next experiment

The contrast set was authored alongside the rules; its high apparent recall is **in-sample** and must not be reported as expected real-world performance or as a measured improvement over the whole product gate. The prototype also watches lexical and prohibitive cues that the current `changed_polarity` subcheck does not; their comparison illustrates a difference in coverage, not an isolated benefit of clause signatures. The current subcheck's new short-negation target comparison also explains some of its results, so the table is not a pure count-versus-signature ablation. The probe uses no morphological analyzer and no independent native-Korean annotation. It does not handle quoted negation, **밖에** and other negative-polarity items, ambiguous quantifiers, evidential or conditional scope, non-**지만** connective clauses, morphological irregularity beyond a few listed forms, or document context. Lexical refusal/prohibition patterns are tiny and could match words in unrelated contexts. Clause reordering causes a false alarm. A future study should freeze these rules, then evaluate on a rights-cleared, independently annotated Korean rewrite set stratified by genre and negation subtype, counting false accepts and false rejects separately. Where available and licensed, an actual morphological/dependency analysis plus aligned predicate arguments and temporal anchors could replace the regex proxy. No product integration follows from these 36 observations alone.
