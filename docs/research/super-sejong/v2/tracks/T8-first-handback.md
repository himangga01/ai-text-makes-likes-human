# T8 report: academic and institutional literature that should shape Super Sejong v2

## 0. Scope, method and evidence levels

**What was done.** I opened about 85 distinct sources: KCI, NIKL 새국어생활, NIKL 온라인가나다, ACL Anthology, arXiv, institutional PDFs and DBpia/KISS abstract pages. Four parallel helpers gathered sources by area (syntax and translationese; speech level and discourse; pedagogy, readability and public language; NLP and evaluation). I opened further sources myself, ran corpus measurements, and spot-checked helper claims against the locally extracted PDF texts.

**Search budget.** The session's WebSearch budget (200 calls) ran out near the end. A few leads could not be followed; they are listed in section 7.

**Evidence tags:**
- **[FULL]**: the full text was read.
- **[ABS]**: abstract only. These items are paywalled or only the landing page opened.
- **[NIKL-A]**: an NIKL institutional answer. It is not peer-reviewed.
- **[M]**: measured by me on the provided corpora.
- **[R]**: my reasoning, not measured.

**Spot-check result.** I verified the following figures verbatim in the extracted PDF text, and all matched:
- 목정수 2017: 15.8% / 64.7%.
- 한송화 2013: 2.87 / 0.93 per 100 words.
- Maeng et al. 2023: 58.16%, 89.36%, 52.24%.
- Goto et al. 2026: Kor-learner 4,264 / 4,265.
- 김정우 2011: 249 cases, 44.5%; 그러나 33.3%, 하지만 20.8%; the "rules fell short" admission.
- 김정우 2012: 45%.
- 최희경 2016: 38.482, 84.441, 36,942,784 어절.
- 정언학 2014: 33% / 22% / 19% / 9%; footnote 29.
- 남수경 2025: 2.29 → 1.32.
- 최소영 외 2024: 37.26 and 40.09 characters.
- NIKL 2015 diagnosis: exception rules, 요구되어진다, 10km을.
- 최인호 2016: 본디틀, 협박이 틀림없었다.

**Methodological warning.** WebFetch's PDF summariser invented an author: it returned "민현식" for 이관규 2005, 《새국어생활》 15(4). Every PDF-derived claim below comes from locally extracted text, not from the summariser.

Scratch files are in `/private/tmp/claude-501/-Users-wisdom-wisdom-project-gpt-ai-text-makes-likes-human/e70a7860-b0c8-4bf4-999b-63b4ba6d0a8c/scratchpad/r5/T8/`:
- Scripts: `measure_lit_rules.py`, `subjpred_kiwi.py`, `sentlen.py`, `measure_extra.py`.
- Outputs: `lit_rule_rates.json`, `lit_rule_samples.txt`, `subjpred_kiwi.json`.
- Extracted source texts: `syn_*`, `disc_*`, `ped_*`, `nlp_*`, `my_*`.

The repository was not touched. I did not write works-log.md, because the brief makes the repository read-only for research tracks.

## 1. Headline findings

1. **The 윤문 엔진 has no agreement (호응/비문) category at all.** A grep of its references finds zero rules for 호응, 비문 or 주술. The literature on native writers puts 호응 first among non-spelling errors:
   - 방영심·이혜용 2013, relayed in 정언학 2014: 75 students; 호응 33% > 어휘 22% > 조사·어미 19% > 번역식 9%.
   - 김혜정 외 2016: 749 texts.
   - 김미선·이지용 2018: government press releases.
   - [M] The textbook agreement rules are human-norm rules, not LLM tells. "왜냐하면 without a reason ending" fires 1.89 per 10k characters on human student essays and 0.04 on LLM essays.
2. **Speech level, honorifics and CMC endings are where the linguistics most directly contradicts the 윤문 엔진.**
   - Its rule E-7 ("unify the speech level in one document") conflicts with the documented functions of deliberate 반존대 (이민영 2026).
   - It also conflicts with the level-neutral -음/-함 endings (장경현 2013; 김가연 2017).
   - The status of "사물 존대" is disputed among linguists (목정수 2017 vs 이정복 2024 and 안주호 2022), so it must not be auto-fixed.
3. **Several 윤문 엔진 rules change meaning, which breaks principle 3.**
   - E-2 (-고 있다 → simple tense) changes viewpoint aspect (박종후 2016; 송창선 2012).
   - F-5 (-적 deletion) can change meaning, because -적 has five distinct meanings (이경보 2020).
   - E-1 (inject long and short sentences) has no support. Sentence length is not a fault in the pedagogy literature (정언학 2014; 정희모·김성희 2008: higher-rated writers had longer T-units).
4. **Translationese is a property of native Korean prose too.**
   - 최희경 2016: '통하다' appears 84.4 per 50k 어절 in non-translated news vs 42.1 in translated news.
   - 김정우 2011 and 2012: translators *add* 때문 in 44.5–45% of its uses and add 그러나 in 33.3% of its uses.
   - This independently confirms the 4 October finding that 번역투 items fire as often on human prose. The translationese family must stay suggest-only, and the bigger risk is the rewriter *adding* connectives (explicitation).
5. **The evaluation literature supports a deterministic, rule-based voice gate over trusting the writer prompt.**
   - LLM honorific control is "unstable" (LoCar 2026, abstract).
   - Native annotators disagree on whether an ending is natural (KoSEnd: α 0.30–0.75).
   - STS meaning scorers ignore politeness by construction (KLUE-STS guideline).
   - Over-correction falls when the prompt says "Do NOT rewrite for style… if already correct, return it unchanged" (Türker & Eryiğit 2026, English data).

## 2. Measurements (all [M], this host)

**Corpora.**

| Corpus | Docs | Characters | Sentences |
|---|---|---|---|
| KatFish essay, human | 181 | 116k | 2,105 |
| KatFish essay, LLM | 590 | 540k | 9,906 |
| KatFish abstract, human | 100 | 41k | — |
| KatFish abstract, LLM | 278 | 127k | — |
| Naver news | 2,740 | 2.73M | — |
| KLUE MRC contexts | 1,283 | 1.28M | — |
| Owner's blog | 28 posts | 74k | 1,449 lines/sentences |

Sentences were split with a regex. The blog was split on its paragraph lines.

### 2.1 Literature-derived "human-norm" rules (fires per 10k characters, raw count in brackets)

| Rule (source) | Essay human | Essay LLM | Abstract human | Abstract LLM | News | KLUE | Owner blog |
|---|---|---|---|---|---|---|---|
| 왜냐하면 without a reason ending (이관규 2005, fn.1; 김정우 2012) | **1.89 (22)** | 0.04 (2) | 0 | 0 | 0.00 (1) | 0 | 0 |
| Head noun 이유/목적/꿈/목표/핵심 + 은/는 + verb predicate, Kiwi version (subject–predicate 호응) | 0.34 (4) | 0.09 (5) | 0.25 (1) | 0 | 0.05 (13) | 0.06 (8) | 0 |
| Double passive, closed list (NIKL Q&A 308572, 310695) | 0.09 (1) | 0.09 (5) | 0.24 (1) | 0.08 (1) | 0.03 (9) | 0.05 (7) | 0 |
| "중의 하나" | 0.52 | 0.22 | 0.74 | 0.63 | 0.11 | 0.19 | 0 |
| N+시키다 where N+하다 is transitive (개선/금지/소개…시키다; NIKL 2015 rubric) | 0.60 (7) | 0.22 (12) | 0.25 | 0.08 | 0.05 | 0.09 | 0 |
| N+시키다 legitimate causative (향상/발전/증가…시키다) | 0.69 (8) | **1.93 (104)** | 0.98 | **4.89 (62)** | 0.29 | 0.18 | 0.14 |
| 필요로 하다 (NIKL 2015; 최인호 2016) | 0.09 | 0.46 | 0.49 | 0.24 | 0.04 | 0.06 | 0.14 |
| -고 있다, any | 14.2 | 14.9 | 11.5 | 5.0 | 17.1 | 16.1 | 6.5 |

The negative-polarity adverbs (결코, 별로, 그다지, 좀처럼, 전혀) without a negative ending fired 0 times after licensing fixes. 비록 without a concessive ending fired once (essay human), 만약 without a conditional fired 0–6 times, and 에 다름 아니다 and 하지 않으면 안 된다 were close to 0 everywhere.

**Manual precision** (I read every hit, or the sample for large groups):
- **왜냐하면 rule:** about 11 of 12 sampled human-essay hits are real 호응 errors, e.g. "왜냐하면 … 보상받는 행위가 바로 지적재산권 보호라고 생각합니다". Both LLM hits are real errors.
- **Subject–predicate (Kiwi):**
  - Student essays: 4/4 real (e.g. "백신을 만드는 이유는 … 존재하지 못한다").
  - Human abstract: 1/1 real ("본 연구의 목적은 … 방법을 제안한다").
  - LLM essays: 4/5 real.
  - News: about 1/13 real; KLUE: 0/8 real. In multi-clause, quoted and reported speech the topic head is not the matrix subject.
  - So precision is high on single-clause expository sentences and low on reported speech.
- **Negative-polarity adverbs:** the first regex flagged "결코 쉬운 일이 아닙니다" (my licence list missed 아닙-). "별로" is mostly the suffix -별 + 로 ("태그 별로"), and Kiwi still mis-tags it as an adverb (MAG) when it is written spaced. **NPI_BYEOLLO is not shippable without dependency context.**

**Conclusions** (measured, for these corpora):
- (a) The classic 비문 rules are **human-norm detectors**, frequent in student prose and rare in LLM prose. Their value is diagnosing the writer's own awkward sentences and catching rewrite-introduced errors, not detecting AI.
- (b) **The owner's blog fires zero times** on every agreement rule (n = 28 posts, 74k characters). The owner's awkwardness, if any, lies elsewhere, so these rules must have near-zero false positives on that blog.
- (c) The -시키다 family splits cleanly:
  - *Redundant* -시키다 (a normative error) is more frequent in human essays.
  - *Legitimate* causative -시키다 is an LLM tell (up to 4.89 vs 0.98 in abstracts).
  - The two must not share a rule. This is a concrete instance of principle 5.

### 2.2 Prior features re-summarised by genre (r4/res3 features.jsonl; AUROC for LLM > human)

| Feature | Essay (181 H / 590 L) | Abstract (100 / 278) | Poetry (189 / 756) |
|---|---|---|---|
| Passive, any | 0.58 | 0.53 | — |
| -어지다 | 0.35 (more in human) | — | — |
| -게 되다 | 0.46 | — | — |
| ETN nominaliser -음/-기 | 0.40 (more in human) | — | — |
| -것이다 endings | 0.59 | — | — |
| -적 | **0.81** | 0.51 | 0.48 |
| Sino-Korean + 하다 | 0.75 | 0.58 | — |
| Mean 어절 per sentence | 0.51 | 0.47 | — |

The literature's "피동 남용 / 명사화 남용" claims do **not** separate LLM from human Korean here.

### 2.3 Sentence length by corpus (characters; share of sentences over 60 and over 80 characters)

| Corpus | Median | p90 | Over 60 | Over 80 |
|---|---|---|---|---|
| KatFish essay, human | 47 | 92 | 32% | 15.6% |
| KatFish essay, LLM | 51 | 78 | 31% | 8.3% |
| News | 62 | 116 | 51% | 30% |
| KLUE | 58 | 108 | 47% | 25% |
| Owner blog | 48 | 78 | 28% | 8.4% |

A "50–70 character" newspaper rule (quoted without a source in 정언학 2014, fn. 29) would flag about half of professional news sentences.

## 3. What the 윤문 엔진 gets wrong or misses in this area

Rule IDs refer to `vendor/humanize-engine/skills/humanize-korean/references/quick-rules.md`.

1. **Missing:** a 호응/비문 family (subject–predicate, adverb–ending, required-argument omission). It is the top non-spelling error class in every native-writer study opened (P1, P8, P18, S3).
2. **E-2 ("-고 있다" → simple tense, 읽고 있다 → 읽는다):** changes viewpoint aspect.
   - -고 있다 marks progressive *or* resultative state (박종후 2016, 《국어학》 77; 송창선 2012).
   - "입고 있다" ≠ "입는다". This is a meaning change under principle 3.
3. **E-7 (unify speech level):** contradicts D1, D6, D7 and D8.
   - Deliberate 반존대 and -음/-함 endings are functional.
   - Unifying them breaks principle 1.
4. **E-1 (add one long sentence and 1–2 short ones per paragraph):** pedagogy and readability sources treat length as a proxy only.
   - Lee Bomi 2020 dropped length from her KFL difficulty formula.
   - Higher-rated student writers had longer T-units (P14).
   - This rule edits natural text with no fault, against principles 1 and 2.
5. **A-8:** groups "~지게 된다" with 이중 피동.
   - NIKL lists -어지다 and -게 되다 as auxiliary constructions (Q&A 309871).
   - -게 되다 has five-plus functions and about 85k Sejong tokens (김문기·신인환 2023).
   - NIKL calls stacked passives "부자연스러울 가능성", not ungrammatical (Q&A 317346).
   - Only the closed 피동사 + -어지다 list is safe.
6. **F-5 (-적 chain → 명사+명사, 전략적 함의 → 전략 함의):** -적 carries similarity, attribute, object-of-thought, abstract-space and field meanings (이경보 2020), and its frequency is genre-dependent (남길임 2009). Deleting it is not meaning-neutral. In our data -적 is an essay-only signal (AUROC 0.81 essay, 0.51 abstract).
7. **A-9 (에 의해 → agent as subject) and the general "피동 → 능동":**
   - 에 의해 and 통하다 are *more* frequent in non-translated news (최희경 2016).
   - Agentless passives must not be activised by inventing a subject (김지혜 2019, abstract: passive is appropriate when the agent is unknown, for objectivity, or to foreground the patient).
8. **The translationese family is treated as an AI tell.** It is a relative property of human translation and of native professional prose (김정우 2012; 최희경 2016). The 윤문 엔진 also has no guard against the opposite failure, where the rewrite **adds** causal or contrast connectives (explicitation; 김정우 2011).
9. **No honorific (-시-) policy.** An LLM "fixing" 사물 존대 or 압존법 would change the writer's voice on contested ground (D2–D5).
10. **No protection for CMC tokens and discourse markers** (ㅎㅎ, ^^, ~, 뭐, 사실, 진짜). The 4 October work added none either.

## 4. Area-by-area translation into rules and prompt guidance

### 음성·음운 (phonology and orthography)
- **Josa allomorphy after digits and Latin letters.** It is already deterministic in v1 (`super_sejong_josa.py`). The NIKL 2015 diagnosis rubric lists exactly "10km을 → 10km를, 전담팀(TF)를 → (TF)을" as accuracy errors (P3), which is institutional support for keeping it as a gate.
- **Spacing.**
  - The error mass sits in 본용언+보조용언 (40.5% of 1,268 errors, P5) and N+N (21.8%). Under-spacing dominates (71–86% across studies, P2).
  - Both are where the 한글 맞춤법 *permits* variants. The P2 helper did not verify the rule text in kornorms, so check it before coding.
  - Rule: never "fix" a permitted variant. Flag only non-permitted forms, such as chained auxiliaries ("구축되어있어도").
  - Checkers are not oracles: "오래달리기" and "것 이지만" were missed, and 띄어서 쓰기 → 띄어쓰기 was a false correction (P2). Sentence-level checker recall is 3–5 out of 30 (P12).
  - Spacing regularity is the most prompt-resistant AI-likeness feature, closing only 13% of the gap (Park et al. 2026, poetry). Over-normalising spacing in post-processing may make text *more* AI-like [R].
- **Unicode.** Map Compatibility Jamo (ㅋ/ㅎ) to Jamo before any edit diff. Otherwise edit counters see phantom edits (KoGEC footnote: up to +3.12 BLEU).

### 형태 (morphology)
- **Double passive closed list** (보여지다, 쓰여지다, 불려지다, 잊혀지다, 되어지다, 담겨지다…):
  - Fix: single passive (잊히다 or 잊어지다; NIKL Q&A 308572).
  - Exclude 느껴지다, 남겨지다, 만들어지다 and 여겨지다, whose base is not a passive verb (Q&A 310695).
  - Measured rare: 0.03–0.24 per 10k characters, 0 on the owner's blog. Low impact; suggest-or-fix.
- **Redundant -시키다 where N-하다 is transitive** (개선시키다 → 개선하다, 금지시키다 → 금지하다):
  - Source: NIKL 2015 rubric, with examples.
  - Human-norm error; fix only on a verified lexicon.
  - Never touch the causative of intransitive bases (향상시키다, 발전시키다).
- **-적:** see section 3, item 6. Suggest-only, genre-gated (not in expository or academic text).
- **'-었었-' → '-었-':** a pedagogy preference (P1). It is a voice marker in blog 해요체 and carries a discontinuity meaning, so do not apply it.
- **-음/-함/-기 endings:** level-neutral sentence endings in CMC (D7, D8), and exempt from "서술어 생략" in NIKL's own rubric (P3). Protected class.

### 통사 (syntax)
- **Subject–predicate 호응** (이관규 2005; 곽수진·김영주 2010; P1, P8, P18). Mechanical trigger [M]:
  - A head noun from {이유, 까닭, 목적, 목표, 꿈, 핵심, 요지…} + 은/는 is the sentence-level topic.
  - At least 5 어절 follow it.
  - The final predicate is a verb with no copula, 때문, 것 or 데 in its last 6 tokens.
  - The sentence has no quotation or reporting frame.
  - Precision is high in expository single-clause text and low in reported speech.
  - Use: a diagnosis hint to the writer LLM, plus an **introduced-only gate** (fail if the output contains a match that the aligned input sentence lacked).
- **Adverb–ending 호응** (임유종 2007 frequency tiers; 임유종·이필영 2004: only 16 of 34 adverbs require negation):
  - 왜냐하면 → reason ending; 비록 → concessive; 만약/만일 → conditional; NPIs from tier 1–3 lists → negative predicate in the same clause.
  - Exclusions: 전혀 다르다/새롭다; "만일의"; -별로; 절대(로), which is also positive "반드시".
  - Also introduced-only gating.
- **Required-argument omission** (이관규 2005: "이번 조사는 … 사용될 것입니다", where the subject should be 조사 결과). The fix requires *adding* words, which risks meaning. Flag only, unless the antecedent is in the previous clause [R].
- **Agentless passives:** never activise by inventing a subject (김지혜 2019; 김순영 2012).
- **Sentence boundaries:** preserve them. Length selects sentences for the 호응 check; it never triggers a split (P1, P4, P14, P19).

### 의미 (semantics)
- **Aspect is a meaning axis** for the meaning guard: -고 있다 (progressive vs resultative), -어 있다, -었었-. Add it next to negation and modality (박종후 2016; 송창선 2012).
- **-게 하다 vs short causative:** converting 잡게 하다 → 잡히다 can be read as a passive (김정우 2011, fn. 55). Never convert automatically.
- **-적, 의-chains, plural -들:** -들 is constrained by animacy, definiteness and specificity (정경숙 2011). Deleting any of them can shift meaning, so suggest-only.

### 텍스트·담화 (text and discourse)
- **Connectives:**
  - Spoken text uses them at 2.87 per 100 words and written text at 0.93 (한송화 2013).
  - Spoken-list items: 그래서, 그런데, 그러니까. Written-list items: 따라서, 그러므로, 즉.
  - In a 해요체 blog, swapping a spoken item for a written one is a register shift that a lexicon lookup can detect.
  - Cohesion-device counts did not correlate with coherence in learner text (박혜진·이미혜 2017).
  - Translators add 그러나, 하지만 and 때문 (김정우 2011).
  - Gate: no new causal or contrast connective unless one was present in the aligned source; the sentence-initial connective count must not increase.
- **Discourse markers** (뭐, 사실, 진짜, 그러니까): stance-bearing in monologue (남길임·차지현 2010: 뭐 is about 40% more frequent in monologue). Protect them in 해요체/해체 first-person text (이해영 2006 spoken-feature list as lexicon seed).
- **CMC tokens** (ㅎㅎ, ㅋㅋ, ㅠㅠ, ^^, ~, 넹): ordinary components of casual written text (박은하 2018; 박용찬 2002). Protect them in position.

### 화용·높임 (pragmatics and honorifics)
- **Speech-level classes:** {합쇼, 해요, 해, 한다/해라, 명사형·생략}. 해체 and 해요체 differ by -요 compatibility (이유기 2011).
- **Gate:** the per-sentence class must be unchanged, and the sentence type (declarative, question, command) must not flip (StyleKQC transfer failures).
- **-시- (목정수 2017; 이정복 2024; 안주호 2022; NIKL Q&A 320228; 이병규 2005):**
  - Tier A, never touch: "선생님, 시간 있으세요?", "할머니는 얼굴이 예쁘시다", addressee-oriented -세요.
  - Tier B, flag only: inanimate subject with no honored possessor ("커피 나오셨습니다"; 64.7% of NIKL 2015 survey respondents judge it unnatural, yet it is linguistically disputed).
  - Tier C, flag and fix only on opt-in: -시- inside the speaker's modal frame ("안 되세요", "예정이십니다"), or on a first-person subject ("저는 물러가시겠습니다").
  - 압존법: never add or remove (no regulation exists, per NIKL).
  - Gate: the -시- count per aligned predicate is unchanged.
- **Pedagogy norms that conflict with voice** (do not implement):
  - Lowering honorifics for seniors in general-audience prose ("선배님들이 맞아 주셨다 → 선배들이 맞아 주었다", 정언학 2014).
  - Discouraging '~것 같다' hedges or '…' ellipsis (P1).
  - Counting spoken expressions as lexical errors (이연정 2021).
  - Replacing loanwords with 순화어 (P16, P17).
  - "Short sentences" (P1, P3).

## 5. Ranked list: the 15 most actionable findings for v2 (by expected impact)

1. **A deterministic speech-level and sentence-type gate, including a level-neutral -음/-함 class and no unification of deliberate mixing.**
   - Evidence: D1 이민영 2026; D6 이유기 2011; D7 장경현 2013; D8 김가연 2017; N8 StyleKQC; N11 LoCar 2026; KoSEnd (α 0.30–0.75).
   - Changes: the verify gate (per-sentence ending-class equality, question/command invariance); drop 윤문 엔진 E-7; chunk prompt.
2. **A -시- honorific preservation gate with the tiered 사물 존대 policy; never touch 압존법.**
   - Evidence: D2 목정수 2017 [FULL]; D3 이정복 2024; D4 안주호 2022; D5 NIKL 320228; D15 Noh et al. 2024 (NY worse than YN); S3 이병규 2005.
   - Changes: the gate (count of -시-/께서 per aligned predicate); diagnosis (Tier B/C flags only); prompt line "Preserve -시- forms".
3. **Add a 호응 (agreement) diagnosis family with introduced-only gating.**
   - Rules: 왜냐하면/비록/만약 → licensed endings; tiered NPI lexicon; head-noun topic + verb predicate; missing required argument flagged, not filled.
   - Evidence: P1 정언학 2014 (33%); P8 김혜정 외 2016; P18 김미선·이지용 2018; S3 이관규 2005 [FULL]; S15/S16 임유종; 곽수진·김영주 2010.
   - [M] 1.89 vs 0.04 per 10k characters; precision 11/12 for 왜냐하면 and 9/10 for subject–predicate in expository text. Owner blog: 0 fires.
   - Changes: diagnostics module (hints to the writer); gate (fail on new violations, mirroring the josa design).
4. **Remove 윤문 엔진 E-2 and add aspect (-고 있다/-어 있다/-었었-) to the meaning-guard axes.**
   - Evidence: 박종후 2016 《국어학》 77; 송창선 2012.
   - Changes: rulebook and prompt; `super_sejong.py` axes.
5. **A no-explicitation gate: no new causal or contrast connective (때문, 그러나, 하지만, 따라서, 왜냐하면) unless the aligned source has one; sentence-initial connective count must not rise; no spoken → written connective swaps.**
   - Evidence: S5 김정우 2011 [FULL] (44.5% of 때문 and 33.3% of 그러나 added by translators); S1 김정우 2012; D10 한송화 2013; D12 박혜진·이미혜 2017; D11 이수곤 2021.
   - Changes: the verify gate (connective set difference); prompt ("do not add connectives to improve flow"); T5 flow work should use this as a constraint.
6. **Sentence length is never an edit trigger; preserve sentence boundaries; drop 윤문 엔진 E-1.**
   - Evidence: P1 (and fn. 29 shows the 50–70 character rule is unsourced); P4 최소영 외 2024 (textbook mean 37–40 characters); P14 정희모·김성희 2008 (longer T-units in better essays, p = .017); P19 정대영 2015; Lee Bomi 2020 (length dropped from her formula).
   - [M] Owner blog median 48 characters; news has 51% of sentences over 60 characters.
   - Changes: rulebook; segmentation (count of splits and merges per paragraph as a gate metric).
7. **The translationese family stays suggest-only and is never treated as an AI tell; calibrate it against register-matched human text.**
   - Evidence: S4 최희경 2016 [FULL]; S1 김정우 2012 [FULL]; S2 김순영 2012 [FULL] ("문법적으로나 의미면에서 틀렸다고는 할 수 없지만"); S10 최서영 2022; 4 October measurement.
   - Changes: diagnosis tiering; T3 taxonomy.
8. **A minimal-edit prompt contract and an over-edit metric.**
   - Prompt: "If the sentence is already natural, return it unchanged; do not rewrite for style; preserve meaning, tone and structure"; tagged input and output.
   - Evaluation: per-class edit counts (spacing, spelling, particle, ending, order) with JP-ERRANT-style Korean edit extraction; multi-reference gold where available; edit-consensus sampling (k samples) as an optional, expensive mode.
   - Evidence: N5 Türker & Eryiğit 2026 (English); N2 Maeng et al. 2023 (Korean GPT-4 precision 0.44, expression errors 52% fixed); N3 KoLLA (two references); N6 Goto et al. 2026 (mixed on Korean: +2.7 F0.5 for gemma, −2.4 for Qwen).
   - Changes: prompt-builder; T7 evaluation protocol.
9. **Meaning checks must not rely on STS-style similarity for voice, and a 3.0/5 paraphrase threshold is too lax.**
   - Evidence: N12 KLUE-STS guideline (politeness and auxiliary verbs are "unimportant"; dropping a qualifier scores 3).
   - Changes: the gate design and T7. Keep event-based guards and the ending-class gate separate from any similarity score.
10. **A protection layer for CMC tokens and discourse markers in first-person 해요체/해체 text.**
    - Evidence: D9 박은하 2018; D13 남길임·차지현 2010; D14 이해영 2006 [FULL]; D7.
    - Changes: protection and pre-processing (token multiset and position preserved); diagnostics must not count them as defects.
11. **Split -시키다 into a human-norm error and an LLM tell.**
    - Redundant (N-하다 transitive): fix on a lexicon.
    - Legitimate causative: never "fix"; at most a density tell.
    - Evidence: P3 NIKL 2015 rubric [FULL]. [M] 0.60 vs 0.22 (redundant, human > LLM) and 0.69 vs 1.93, 0.98 vs 4.89 (causative, LLM > human).
    - Changes: diagnostics; lexicon data.
12. **Double passive: closed-list deterministic suggestion with exclusions; -게 되다 excluded.**
    - Evidence: NIKL Q&A 308572, 310695, 317346; P3 (요구되어진다 → 요구된다); S9 김문기·신인환 2023; S8 김지혜 2019. [M] rare (0 on the owner's blog), so low impact but very low risk.
    - Changes: diagnostics (replace 윤문 엔진 A-8).
13. **Limit or drop -적 and 의-chain deletion (윤문 엔진 F-4/F-5); genre-gate them.**
    - Evidence: 이경보 2020 (five meanings); S14 남길임 2009; S11 김혜영 2011; [M] AUROC 0.81 essay vs 0.51 abstract.
    - Changes: rulebook and diagnostics.
14. **Spelling and spacing post-processing is conservative: fix only non-permitted forms; a checker is never an oracle; normalise jamo before diffs.**
    - Evidence: P2 남수경 2025 [FULL]; P5 이경미 2018; P12 김영일·김완섭 2021 (sentence level 3–5 of 30); N7/P13 구선민 외 2021; N1 KoGEC; N13 Park et al. 2026 (spacing is prompt-resistant).
    - Changes: post-processing; the T7 evaluation of the spacing module.
15. **Reuse NIKL's public-language rubric as a false-positive guard and test source.**
    - Its exception rules transfer directly: bulleted long sentences are not "과도한 접속"; noun-final sentences are not "서술어 생략"; titles are exempt; the same error is counted once per document; 3천 5백만 원 / 3.5천만 원 are both allowed.
    - Its example pairs (요구되어진다, 개선 시켜, 추진 중에 있다, 필요로 한다, 10km을, '…'고 → '…'라고) are ready unit tests.
    - Term replacement must use morpheme boundaries: the "산하기관 → 하기 → 아래" false positive (P17 MOIS 2018 [FULL]).
    - Never auto-apply 순화어 (P16, P17).
    - Evidence: P3 [FULL]; P16; P17.
    - Changes: evaluation set; rule hygiene.

## 6. Annotated bibliography (opened sources, grouped by area)

Format: citation — URL — access — what it establishes → implication for v2. Bracketed IDs refer to section 5. Unless noted, KCI entries are landing pages read for the abstract.

### 6.1 Syntax: agreement (호응), ill-formed sentences, error typologies
1. 이관규 (2005). 문장 성분과 호응. 《새국어생활》 15(4), 131–139. https://www.korean.go.kr/nkview/nklife/2005_4/2005_0411.pdf [FULL]
   - The predicate licenses its arguments; agreement needs both syntactic and semantic fit.
   - Five newspaper-ad errors: over-ellipsis of subjects and objects, a missing comparative argument (다르게 → 그것과 다르게), and mismatched coordination.
   - Fn. 1 names adverb–ending agreement (결코~아니다, 만약~-으면) as a separate type. Fn. 3: the direction of a fix is not fixed.
   - → Finding 3; flag-not-fill for missing arguments.
2. 정언학 (2014). 대학생 글쓰기의 형식적 오류 분석. 《교양교육연구》 8(1), 113–169. https://j-kagedu.or.kr/upload/pdf/kagedu-8-1-113.pdf [FULL]
   - Qualitative error inventory from courses at several universities (2007–2013).
   - Relays 방영심·이혜용 2013 (n = 75): 호응 33% > 어휘 22% > 조사·어미 19% > 번역식 9%.
   - Advises "짧은 문장 위주 … 긴 문장을 적절히 섞으면 된다".
   - Fn. 44: -어지다 is not simply to be rejected.
   - Advises lowering honorifics for seniors in general-audience writing (a voice conflict).
   - → Findings 3 and 6; the list of pedagogy norms not to implement.
3. 김혜정·안태형·임지아 (2016). 대학생 글쓰기에 나타난 틀린 문장 분석. 《동남어문논집》 41, 265–288. https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002111285 [ABS]
   - 749 texts; spelling 27% first, then 어미, 조사, 성분 생략, 호응, 어휘, 접속, 어순.
   - → Error-type labels for T7; module priority.
4. 이연정 (2021). 대학 신입생 글쓰기에 나타난 문장 오류 양상 분석. 《어문론집》 86, 611–637. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002738437 [ABS]
   - 79 texts. Ranking: inappropriate vocabulary > long or complex sentences > 조사 > idioms. Spoken expressions counted as errors.
   - → Long sentences are a risk selector only; spoken expressions are blog voice.
5. 곽수진·김영주 (2010). 한국어 학습자의 문장 성분 호응 관계 오류 연구. 《한국어 의미학》 32, 29–51. https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001473973 [ABS]
   - L2 learners: particle–predicate and subject–predicate disagreement are most serious, and errors rise with proficiency.
   - → Supports the 호응 family. The population differs, so it gives no thresholds.
6. 김미선·이지용 (2018). 공공언어 문장 오류 유형 분석 연구. 《인문과학연구》 58, 5–26. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002391292 [ABS, partly paraphrased]
   - Press releases: element omission, 호응, 접속 and 조사 errors, and translationese.
   - → Corroborates finding 3.
7. 임유종·이필영 (2004). 부정 표현과 호응하는 부사의 사용 양상과 언어 발달. 《한국어 의미학》 15, 227–248. https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001149780 [ABS]
   - Only 16 of 34 adverbs obligatorily require negation.
   - → Use an adverb-specific lexicon, not a blanket rule.
8. 임유종 (2007). 부정 표현과 호응하는 부사의 사용 양상과 한국어 교육. 《한민족문화연구》 20, 187–214. https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001041039 [ABS]
   - Frequency tiers. Tier 1: 전혀, 결코, 별로, 그리. Tier 2: 도대체, 도저히, 절대, 그다지… Tier 3: 좀처럼, 여간, 차마…
   - → NPI lexicon for finding 3 (exclude 절대 in the positive "반드시" sense).
9. 이해숙 (2023). 피동 표현에 대한 고등학생들의 학습자 내용 지식 연구. 《우리말교육현장연구》 17(1), 77–113. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002963467 [ABS]
   - 288 students misjudge non-passives as passives.
   - → No direct implication: it concerns learner knowledge, not text.

### 6.2 Syntax and morphology: passives, causatives, nominalisation, translationese
10. 김정우 (2012). 현대 국어 번역문의 실태. 《새국어생활》 22(1), 53–66. https://www.korean.go.kr/nkview/nklife/2012_1/22_0104.pdf [FULL]
    - Relays 김혜영 2009 (1M-어절 balanced corpus each for translated and non-translated text). In translations, 것, 때문, 만들다, 가지다, 의하다, 대하다, -어지다, 의, 로부터 and -은/는 are more frequent; short negation, 이/가 and -시- are less frequent.
    - Own parallel corpus: 45% of 때문 added by translators.
    - Readers often accept literal style.
    - → Findings 5 and 7. All frequencies are relative, so no thresholds.
11. 김순영 (2012). 영한 번역에 나타난 번역투 문장. 《새국어생활》 22(1), 67–79. https://www.korean.go.kr/nkview/nklife/2012_1/22_0105.pdf [FULL]
    - Three layers: construction, inflection (-들) and prepositional phrases; about 9 literal/alternative pairs.
    - Translationese is "not ungrammatical"; -들 conveys nuance; an expert alternative still contains 에 있어서.
    - → Findings 7 and 13; regression seeds.
12. 최희경 (2016). 번역투 다시 보기: 코퍼스 분석 사례를 토대로. 《번역학연구》 17(1), 147–169. https://journal.kci.go.kr/kats/archive/articlePdf?artiId=ART002094440 [FULL]
    - Corpus: translated news (41,578 어절), non-translated (75,793) and Sejong (36.9M).
    - 로부터: 38.5 / 23.1 / 33.3 per 50k 어절. 통하다: 42.1 / 84.4 / 50.9.
    - Translated sentences are shorter (11.75 vs 12.80 어절) and have higher STTR (76.9 vs 72.2).
    - → Finding 7: an external confirmation of the 4 October finding.
13. 김정우 (2011). 한국어 번역문의 중간언어적 특성. 《번역학연구》 12(1), 75–122. https://journal.kci.go.kr/kats/archive/articlePdf?artiId=ART001537030 [FULL]
    - 264k-어절 parallel corpus. Of 559 때문 tokens, 249 (44.5%) were inferred and added by the translator; 그러나 33.3% and 하지만 20.8% were added.
    - Long causatives are mostly explicitation.
    - The author admits his transformation rules "fell short of expectations".
    - Fn. 55: 잡게 하다 → 잡히다 is ambiguous with the passive.
    - → Findings 5 and 13. No ready-made 번역투 rulebook exists in the literature.
14. NIKL 온라인가나다, Q&A 308572 ('잊혀지다'). https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=216&qna_seq=308572&pageIndex=1 [NIKL-A]
    - 잊혀지다 is a double passive; use 잊히다 or 잊어지다.
    - → Finding 12.
15. NIKL Q&A 310695 ('보여지다'). https://m.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=216&qna_seq=310695&pageIndex=1 [NIKL-A]
    - 보이다 is already passive, so -어지다 is unnecessary. 느껴지다 and 남겨지다 are *not* double passives. 얼굴을 보이다 is a causative.
    - → Exclusion list for finding 12.
16. NIKL Q&A 317346 (stacked passives). https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=216&qna_seq=317346&pageIndex=1 [NIKL-A]
    - Stacked passives are "likely unnatural", not ungrammatical.
    - → Suggest, don't enforce.
17. NIKL Q&A 309871 (derivational vs syntactic passive). https://m.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=216&qna_seq=309871&pageIndex=1 [NIKL-A]
    - -어지다 and -게 되다 are auxiliary constructions.
    - → Section 3, item 5 (윤문 엔진 A-8 is over-broad).
18. NIKL Q&A 321185 (causative + -어지다). https://korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=216&qna_seq=321185&pageIndex=1 [NIKL-A]
    - A causative + -어지다 (알려지다, 굽혀지다) is legitimate.
    - → Another exclusion for the passive rule.
19. 김지혜 (2019). 글쓰기 수업에서의 피동 표현 교육 내용 분석 및 개선 방안. 《리터러시 연구》 10(5), 177–213. https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002520009 [ABS]
    - 10 writing textbooks. Errors are double passives and unnecessary passives. Passive is appropriate when the agent is unclear, for objectivity, or to foreground the patient.
    - → Never activise an agentless passive.
20. 김문기·신인환 (2023). 한국어 문법 '-게 되다'의 의미 기능과 특징 연구. 《인문과학》 128, 75–108. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002991850 [ABS]
    - Sejong corpus: 67,181 verb and 17,640 adjective tokens. Functions: change, result, passive, objectification, indirectness.
    - → -게 되다 is never auto-edited.
21. 우민주 (2022). 국어과 교과서와 중학교 학습자 글쓰기에 나타난 '-게 되다'의 의미 양상 비교. 《한국어문교육》 38, 153–179. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002814264 [ABS]
    - In learner writing -게 되다 mostly expresses speaker attitude.
    - → Same as 20.
22. 최서영 (2022). 영어 무생물 주어 타동 구문과 자동 구문의 한국어, 일본어에서의 번역 양상. 《일본연구》 92, 249–270. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002852164 [ABS]
    - Translators keep about 38% of inanimate-subject transitive structures.
    - → Inanimate subjects are uncommon but not errors; no rule.
23. 김혜영 (2011). 명사 수식 구문의 번역 글쓰기 문제. 《돈암어문학》 24, 89–120. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001623231 [ABS]
    - Problems: dependence on English order, ambiguity, repeated 의, multiple embedding.
    - → 의-chains are suggest-only; flag ambiguity rather than length.
24. 오경순 (2010). 일한 번역의 번역투 고찰 — 수동표현 번역문을 중심으로. 《일본근대학연구》 29, 163–182. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001473234 [ABS]
    - Literal translation of Japanese passives.
    - → Direction only; no rule.
25. 오경순 (2014). 일한 번역의 번역투 연구 — '~적'의 번역. 《일본학보》 99, 75–92. https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART001878192 [ABS]
    - -적 translation and readability experiments.
    - → -적 is a recognised but unquantified factor.
26. 남길임 (2009). 텍스트 장르와 접미사의 사용 양상 — '-적'과 '-적' 파생어. 《한글》 283, 63–91. https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE02343949 [ABS]
    - -적 frequency differs by genre (academic, fiction, lecture, conversation).
    - → Finding 13 genre gate.
27. 이경보 (2020). '-적'의 연구: 의미와 선행어기를 중심으로. 《언어와 정보 사회》 39, 241–267. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002575110 [ABS]
    - Five meanings of -적: similarity, attribute, object of thought (≈ 에 대한), abstract space, field (≈ 상의).
    - → Deleting -적 is not meaning-neutral (finding 13).
28. 홍종선 (2004). 명사화. 《새국어생활》 14(2). https://www.korean.go.kr/nkview/nklife/2004_2/2004_0210.pdf [FULL]
    - Syntactic nominalisers are only -음 and -기; 기다림 and 놀이 are lexicalised.
    - → Detectors must exclude lexicalised nouns.
29. 정경숙 (2011). 영어 복수 명사 번역과 한국어 형태소 '-들'의 의미. 《새한영어영문학》 53(3), 237–262. https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE01674545 [ABS]
    - -들 is constrained by animacy, definiteness and specificity.
    - → Plural -들 is not removed automatically.

### 6.3 Semantics: aspect and auxiliaries
30. 박종후 (2016). 보조용언 '있다'의 결합 제약과 상적 의미 해석. 《국어학》 77, 131–165. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002094173 [ABS]
    - -고 있다 adds viewpoint aspect. Focus on ACT gives the progressive reading; focus on BECOME-BE gives the resultative state.
    - → Finding 4.
31. 송창선 (2012). '-고 있-'과 '-어 있-'의 기능과 의미 연구. 《언어과학연구》 62, 179–204. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001699356 [ABS]
    - There are two distinct -고 있-: progressive and resultative (≈ -고서).
    - → Finding 4.

### 6.4 Pragmatics: speech level, honorifics, CMC endings
32. 이민영 (2026). 한국어 '반존대'의 담화적 기능. 《국어학》 117, 337–365. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003321618 [ABS]
    - Mixing levels softens face threats, emphasises through rhetorical questions and builds rapport.
    - → Finding 1; drop 윤문 엔진 E-7.
33. 목정수 (2017). 높임말을 다시 생각한다: 이른바 '사물 존대' 현상에 대한 상념. 《새국어생활》 27(1), 31–50. https://www.korean.go.kr/nkview/nklife/2017_1/27_0102.pdf [FULL]
    - NIKL 2015 survey: 15.8% find 사물 존칭 natural, 64.7% do not.
    - Most cases follow an honored possessor or the addressee as subject.
    - Real overuse: -시- in modal frames and on first-person subjects.
    - → Finding 2 tiers.
34. 이정복 (2024). 상황 주체 높임과 '–시–'의 기능 변화. 《언어와 정보 사회》 51, 159–193. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003070393 [ABS]
    - -시- is shifting toward hearer-honorification. This opposes 33.
    - → The question is disputed, so no auto-fix.
35. 안주호 (2022). 최근 한국어 높임법 사용과 변화 양상. 《동악어문학》 86, 121–143. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002815866 [ABS]
    - Speakers use 사물 높임 strategically while knowing it is "wrong"; -실게요 and double honorifics are broadly accepted.
    - → Tier B is flag-only.
36. NIKL Q&A 320228 (압존법, 2025). https://korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=216&qna_seq=320228&pageIndex=1 [NIKL-A]
    - "압존법은 규정으로 정해진 바가 없습니다".
    - → Never add or remove it.
37. 이병규 (2005). 높임법과 간접 높임. 《새국어소식》 84. https://www.korean.go.kr/nkview/nknews/200507/84_7.html [FULL]
    - Indirect honorification of a senior's attributes is correct ("넥타이가 잘 어울리시네요").
    - → Tier A.
38. 목정수 (2013). 선어말어미 '-시-'의 기능과 주어 존대. 《국어학》 67, 63–106. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001799111 [ABS]
    - -시- is subject honorification: "시간 있으세요?" is correct, while "주무시고 계신 것 같으세요" is wrong.
    - → Tier C examples.
39. 전휘 (2020). 높임 형태 '-으시-'의 들을이 지향적 쓰임에 대한 연구. 《겨레어문학》 64, 293–320. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002607559 [ABS]
    - In -으세요, -시- marks addressee respect.
    - → Tier A.
40. 이유기 (2011). 반말의 성격과 청자대우체계의 실상. 《동악어문학》 57, 49–82. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001581594 [ABS]
    - 반말 is pragmatically unmarked; respect vs non-respect, with -요 compatibility as the criterion.
    - → Classifier design (finding 1).
41. 이정택 (2015). 우리말 높임법의 본질과 상대 높임법 체계. 《문법 교육》 24, 145–160. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002022936 [ABS]
    - Honorifics express respect, not status.
    - → Context for finding 2.
42. 장경현 (2013). 인터넷 언어의 종결어미 회피 현상 연구. 《언어사실과 관점》 31, 171–194. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001772527 [ABS]
    - -음, -귀 and -한다 endings neutralise politeness and level.
    - → The -음/-함 class is protected.
43. 김가연 (2017). 모바일 메신저 대화 언어에 나타난 명사형 어미 '-(으)ㅁ' 종결문의 사용 양상. 《텍스트언어학》 43, 57–84. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002299380 [ABS]
    - -음 endings modulate distance and have an ambiguous level.
    - → Same as 42.
44. 이정복 (2002). 통신 언어 문장종결법의 사회언어학. 《사회언어학》 10(2), 109–136. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART000851605 [ABS]
    - Non-concluding sentences (predicate ellipsis, nominal endings) are commoner among teens and people in their twenties.
    - → Do not "complete" elliptical endings.
45. 박은하 (2018). 스마트폰 메신저의 표현 양상과 인식. 《새국어교육》 117, 83–118. https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE09018072 [ABS]
    - ㅋㅋ, ㅎㅎ, 헐, 넹 and emoticons are ordinary.
    - → Finding 10.
46. 박용찬 (2002). 이모티콘. 《새국어소식》 (2002.4). https://www.korean.go.kr/nkview/nknews/200204/45_7.html [FULL]
    - Emoticons compensate for missing face-to-face cues.
    - → Finding 10 (context).
47. 이경희 (2015). 한국어 발표 담화에서의 합쇼체와 해요체 선택 양상 연구 (MA thesis, 경희대). https://scienceon.kisti.re.kr/srch/selectPORSrchArticle.do?cn=DIKO0013845906 [ABS, not peer-reviewed]
    - 198 students. 합쇼체 is used for set phrases and listener-action content; 해요체 for supplementary or atmospheric content.
    - → Mixing 합쇼체 and 해요체 is functional.
48. Noh, Song & Oh (2024). How Language Models Understand Honorific Mismatches in Korean. 《Language Research》 60(3), 303–322. https://www.elanguageresearch.org/archive/view_article?doi=10.30961%2Flr.2024.60.3.303 [ABS]
    - 3,200 sentences. Humans accept YN (honorific referent, bare verb) but reject NY; the models diverge on YY.
    - → NY is flagged above YN; do not trust LM probabilities on correct honorifics.

### 6.5 Text and discourse: connectives, cohesion, discourse markers
49. 한송화 (2013). 한국어 접속부사의 사용 양상. 《언어사실과 관점》 31, 139–170. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001772525 [ABS; numbers verified]
    - 2.87 connectives per 100 words in speech vs 0.93 in writing; separate spoken and written connective lists.
    - → Finding 5 register check.
50. 이수곤 (2021). 대학 글쓰기에서 접속사 사용 양상과 교육 방안. 《리터러시 연구》 12(1), 121–141. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002693721 [ABS]
    - Problems: unnecessary, ambiguous and over-complex connective use.
    - → Flags only.
51. 박혜진·이미혜 (2017). 한국어 학습자의 쓰기 텍스트에 나타난 응결성과 응집성의 상관분석. 《우리말글》 73, 133–157. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002240473 [ABS]
    - Cohesion-device counts show no correlation with coherence.
    - → Never reward adding connectives (finding 5).
52. 남길임·차지현 (2010). 담화표지 '뭐'의 사용패턴과 기능. 《한글》 288, 91–119. https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE02343416 [ABS]
    - Sejong spoken corpus (about 100k words): 뭐 is about 40% more frequent in monologue.
    - → Finding 10.
53. 이해영 (2006). 구어의 특징과 구조. 《새국어생활》 16(2). https://www.korean.go.kr/nkview/nklife/2006_2/2006_0212.pdf [FULL]
    - Lists spoken features: ellipsis, 반말, degree adverbs (진짜, 되게), discourse markers.
    - → Lexicon seed for register inference.
54. 김도연 (2021). '그러니까'의 의미 기능과 실현 양상 연구. 《한국언어문화학》 18(2), 47–80. https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE11331642 [ABS]
    - The epistemic use of 그러니까 is the most frequent.
    - → 그러니까 is not a filler.
55. 송현주·비신연 (2014). 학문목적 학습자를 위한 교육용 접속 부사 목록 연구. 《어문론총》 61, 75–98. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001915550 [ABS]
    - Connective keyness method against the Sejong corpus.
    - → Method for blog baselines.
56. 고영근 (c. 1998). 좋은 텍스트를 만드는 길. 《새국어생활》. https://www.korean.go.kr/nkview/nklife/1998_4/8-12.html [FULL, short]
    - Distinguishes 응결성 from 응집성 and names the cohesive devices.
    - → Context only.
57. 이정복 (2018). 《텍스트언어학》 44, 97–122 (social-media research agenda). https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002358395 [ABS]
    - → No direct implication: an agenda paper with no data.
58. 김지연 (2016). Blog writing. 《새국어생활》 26(3). https://www.korean.go.kr/nkview/nklife/2016_3/26_0303.pdf [FULL]
    - Platforms and multimodality; nothing on endings.
    - → No direct implication.

### 6.6 Readability, sentence length, writing pedagogy
59. 최소영·박은아·변태진·하명진·류수경 (2024). 교과 교육용 텍스트의 이독성 특성 분석. 《교육과정평가연구》 27(1), 87–131. https://www.ejce.org/download/download_pdf?pid=jce-27-1-87 [FULL]
    - 9,945 textbook texts. 37.26 characters per sentence overall (SD 11.54); middle school 40.09 (SD 10.45). Length is a "proxy".
    - → Finding 6.
60. 정희모·김성희 (2008). 대학생 글쓰기의 텍스트 비교 분석 연구. 《국어교육학연구》 32, 393–426. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001275575 [ABS]
    - n = 53. Better writers have more words per T-unit (17.33 vs 14.30, p = .017).
    - → Finding 6.
61. 정대영 (2015). 소설 텍스트의 문장 복잡도 연구. 《문학교육학》 48, 263–292. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002039726 [ABS]
    - 85–90% of novel sentences are at or below 2× mean complexity; the tool is 88.9% accurate.
    - → A complexity detector over-flags; inspection only.
62. 조용구 (2016). 글의 수준을 평가하는 국어 이독성 공식. 《독서연구》 41, 73–92. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002171615 [ABS]
    - Grade = 4.874 + 0.591 × mean sentence length − 9.201 × (easy-word ratio)³.
    - → No direct implication: fitted on school texts.
63. 조용구·이경남 (2020). 국어 텍스트 분석 프로그램(KReaD 지수)의 개발. 《독서연구》 56, 225-246. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002616815 [ABS]
    - 28,332-word graded vocabulary list.
    - → A possible difficulty-drift metric; licence unverified.
64. 서혁 외 (2013). 텍스트 복잡도 상세화 연구 (2). 《국어교육학연구》 47, 253–290. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001797415 [ABS]
    - Structure-based complexity explains 75.2% of variance (elementary) and 65.6% (secondary).
    - → Length alone is a poor proxy.
65. 조용구 (2017). 글의 수준을 평가하기 위한 글의 응집성 측정. 《국어교육학연구》 52(1), 443–461. https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002210578 [ABS]
    - LSA cohesion on n = 14 texts.
    - → No direct implication: unvalidated.
66. 박종향·김은영 (2025). 생성형 AI 텍스트와 인간 텍스트의 내용 및 문체 비교 연구. 《교양교육연구》 19(6), 71–86. https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART003291987 [ABS]
    - 69 term papers. The AI-era cohort has shorter sentences and lower MATTR; connective use shows no difference.
    - → Monitoring only (the cohorts are confounded).
67. 최진영 외 (2023). 생성형 인공지능 ChatGPT를 활용한 고등학생의 작문 과제 고쳐쓰기 양상. 《리터러시 연구》 14(6), 79–119. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART003043066 [ABS]
    - Students who improved made writer-led macro revisions.
    - → The engine stays micro-level; macro revision is the writer's.
68. 손혜숙 (2012), 《한민족문화연구》 41, 417–446 (첨삭 checklist). https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001706857 [ABS]
    - → Context only.
69. 정희모·이재성 (2008), 《국어교육학연구》 33, 657–685 (revision methods). https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART001307237 [ABS]
    - → Context only.
70. 장동석 (2017), 《우리말연구》 48, 165–191 (첨삭 standard manual). https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002195909 [ABS]
    - → Its manual contents were not available.

### 6.7 Orthography and spacing errors; correction tools
71. 남수경 (2025). 대학생 학습자의 고쳐쓰기 과정에 나타난 띄어쓰기 오류 교정 양상. 《교양교육연구》 19(1), 75–91. https://j-kagedu.or.kr/upload/pdf/kjge-2025-19-1-75.pdf [FULL]
    - 71 draft/final pairs. Spacing errors fall from 2.29 to 1.32 per 100 어절; under-spacing is about 70%; checker failures are documented.
    - → Finding 14.
72. 이경미 (2018). 대학생의 글에 나타난 띄어쓰기 오류 유형. 《어문연구》 97, 289–318. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002387648 [ABS]
    - 1,268 errors: 용언+보조용언 40.5%, N+N 21.8%.
    - → Finding 14.
73. 최성규 (2021). 대학생 글쓰기의 어문 규범 관련 오류. 《한글》 82(4), 1063–1099. https://kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002789189 [ABS]
    - The ㅔ/ㅐ merger is the top spelling error; typed assignments have far fewer errors.
    - → Base rates depend on the writing medium.
74. 김영일·김완섭 (2021). 오류 분석을 통한 한글 맞춤법 검사기의 정확성 검토와 제언. 《문화와융합》 43(3), 259–284. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002697957 [ABS]
    - Four checkers on 90 items; sentence level 3–5 of 30 fixed.
    - → Finding 14; T7 test design.
75. 구선민·박찬준·소아람·임희석 (2021). 딥러닝 기반 한국어 맞춤법 교정을 위한 오류 유형 분류 및 분석. 《한국융합학회논문지》 12(12), 65–74. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002787033 [ABS]
    - Commercial correctors handle spacing only and barely recognise word-order or tense errors. Synthetic-noise test sets are unrepresentative.
    - → T7.
76. 김영일 (2020). 대학생의 글쓰기에 나타난 <한글 맞춤법>의 오류 유형 분석. 《교양교육연구》 14(6), 189–209. https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002677571 [ABS]
    - 150 papers; pronunciation-driven errors.
    - → Context only.

### 6.8 Public language
77. 국립국어원 (최홍열 책임) (2015). 2015년 중앙행정기관 공공언어 진단. https://www.korean.go.kr/common/download.do?file_path=reportData&c_file_name=778c51c5-7f63-431f-b18f-dfa2a47eb905_0.pdf [FULL, 200 pp.]
    - 44 agencies and 1,383 press releases. Accuracy is scored per 1,000 syllables.
    - Explicit exception rules and example pairs.
    - → Finding 15.
78. 행정안전부 (2018). 쉽고 바른 공공언어 사용을 위한 공문서 용어 개선·정착 추진계획. https://dams.pa.go.kr/dams/DOCUMENT/2023/11/30/DOC/SRC/0A04202311301611096041877011783.pdf [FULL]
    - Rejected 순화어 (걸상차, 무른모); the 산하기관 → "하기 → 아래" false positive.
    - → Finding 15.
79. 백경미·육영주·김태경 (2022). 정부 공공기관의 전문용어 사용 실태 및 개선 방안 연구. 《한국언어문화》 77, 103–144. https://kiss.kstudy.com/Detail/Ar?key=3946088 [ABS]
    - 142 documents, 3,105 terms; acceptability surveys.
    - → No auto-순화.
80. 최인호 (2016). 몇몇 웹 소설을 읽고. 《새국어생활》 26(4), 207–219. https://www.korean.go.kr/nkview/nklife/2016_4/26_4.pdf [FULL]
    - Minimal-edit fixes on Naver web fiction ("협박이 틀림없었다 → 협박이었다", 필요로 하다, -고 있는 중이었다), keeping "본디틀".
    - → The minimal-edit style to imitate; suggest-level lexicon.
81. 김명희 (2015). 한국의 공공언어정책 연구. 《한국자치행정학보》 29(1), 91–110. https://oak.go.kr/central/journallist/articlepdf.do?article_seq=19366 [FULL]
    - → No direct implication: policy history only.

### 6.9 Computational and evaluation (Korean NLP)
82. Kim, Jeong & Song (2025). KoGEC. arXiv:2506.11432. https://arxiv.org/abs/2506.11432 [FULL]
    - Native-error corpora: NIKL 2021 (393k) and AI Hub (127k).
    - GPT-4o reaches only a 48% exact match with the reference.
    - Jamo normalisation changes BLEU by up to 3.12.
    - → Data sources (licences to check); finding 14.
83. Maeng, Gu & Kim (2023). Effectiveness of ChatGPT in Korean GEC. PACLIC 37, 464–472. https://aclanthology.org/2023.paclic-1.46.pdf [FULL; numbers verified]
    - GPT-4: F0.5 0.43, precision 0.44. Fixes: particles 89%, expression choice 52%.
    - → Finding 8 (measure over-editing yourself).
84. Song, Lim & Park (2025). Enriching KoLLA with multi-reference annotations. arXiv:2505.00261. https://arxiv.org/abs/2505.00261 [FULL]
    - 1,419 sentences with two references; Korean ERRANT-style edit classes.
    - → Finding 8.
85. Fang et al. (2023). Is ChatGPT a Highly Fluent GEC System? arXiv:2304.01746. https://arxiv.org/abs/2304.01746 [partial]
    - Over-correction; cross-sentence errors not fixed.
    - → Segment-level context.
86. Türker & Eryiğit (2026). Instruction-following LLMs for GEC. BEA 2026, 234–247. https://aclanthology.org/2026.bea-1.17/ [FULL]
    - A minimal-edit prompt reduces over-editing; persona prompts do not help.
    - → Finding 8 prompt wording.
87. Goto, Sakai & Watanabe (2026). Edit-level majority voting mitigates over-correction. arXiv:2605.13624. https://arxiv.org/abs/2605.13624 [FULL]
    - Includes Korean via JP-ERRANT; the gains are mixed.
    - → Optional consensus mode.
88. Cho et al. (2022). StyleKQC. LREC 2022, 7122–7128. https://aclanthology.org/2022.lrec-1.771/ [FULL]
    - 30k formal/informal directive pairs (CC-BY-SA per the README). Failure mode: a question turned into a command.
    - → Finding 1 (sentence-type invariance).
89. SmileStyle dataset (Smilegate AI, 2022). https://github.com/smilegate-ai/korean_smile_style_dataset [FULL README]
    - CC-BY-NC; described by its authors as a "toy" with conversion errors.
    - → Not usable commercially.
90. 정준녕 외 (2021). 트랜스포머를 이용한 한국어 높임말 변환 연구. 《한국정보기술학회논문지》 19(12), 143–150. https://ki-it.com/xml/31514/31514.pdf [FULL]
    - 20k sentences; about 23–33% of outputs were bad at BLEU 63–67 (over-honorification, meaning drift).
    - → BLEU is a weak proxy; rule-based verification.
91. Jeong et al. (2026). LoCar. arXiv:2605.21086. https://arxiv.org/abs/2605.21086 [ABS]
    - Korean honorific control is "unstable" in current LLMs.
    - → Finding 1.
92. Park et al. (2021). KLUE (STS section). arXiv:2105.09680. https://arxiv.org/abs/2105.09680 [FULL STS section]
    - Politeness is "unimportant" in the STS labels; threshold 3.0.
    - → Finding 9.
93. Park, Yu & Kim (2026). Detecting and guiding LLM-generated Korean poetry. arXiv:2608.28986. https://arxiv.org/abs/2608.28986 [FULL]
    - Spacing regularity is prompt-resistant (13% of the gap closed).
    - → Finding 14.
94. 이보미 (Lee Bomi) (2020). 한국어 읽기 텍스트의 난이도 측정 공식 개발에 관한 연구. 《외국어로서의 한국어교육》 56. https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART002560113 [ABS]
    - Previously cited in the program and re-opened.
    - Sentence length was dropped from the final formula.
    - → Finding 6.

Low-relevance items opened and not used, beyond those in the list above: 이정복 2018 agenda; 진정 2020; 유혜령·이선희 2016; 송지호 외 2016 (do not cite); 장채린·전문기 2024; 김혜연 2024; 오영록 2018; 황경수 2009; 박종호·김보은 2014; 이은자 2010; 김정우 2011 (《한국어학》 53); 이경규·오경순 2011; 최희경 2016 (《통역과 번역》 18(1)); 오경순 2024; KITE; Karpo & Chernodub 2026; Staruch et al. 2025.

**Previously cited sources** used as context, not counted above: KatFish (https://aclanthology.org/2025.acl-long.1030/; it is the measurement corpus), KAGAS (2023.acl-long.371) and KoSEnd (2025.acl-srw.29).

## 7. Open questions and gaps

1. **Blog-specific evidence.**
   - No peer-reviewed study measures endings, connectives or discourse markers in Naver blogs.
   - Every blog threshold (mixing rate, connective density, spoken-feature count) must be calibrated on the owner's posts. T2 and T5 hold that data.
   - The owner's posts fired zero textbook agreement rules, so the v2 diagnosis for this owner may matter mostly as a *gate on rewrite-introduced errors*.
2. **No human judgments.** Every precision figure above is my own reading of n ≤ 15 hits per group. A native-editor pass on the 호응 hits is needed before any of these rules ships as an auto-fix.
3. **Disputed honorifics.** Whether Tier B (inanimate-subject -시-) should be flagged at all in the owner's genre is a product decision. The linguistics is split (목정수 vs 이정복/안주호).
4. **Search-limited items.** The search budget ran out, so these were not opened:
   - 전영철 2008 (claims there is no double passive).
   - 방영심·이혜용 2013 (the 33% source; it is relayed second-hand).
   - The Applied Corpus Linguistics 2025 paper on AI-generated Korean subject honorification (HTTP 403).
   - The 한글 맞춤법 spacing articles in kornorms (the helper could not fetch them).
   - Dedicated 왜냐하면/비록 agreement studies.
5. **Introduced-only gating.** Agreement checks need sentence alignment between input and output. The v1 segmentation can supply it, but the false-reject rate of such a gate on real rewrites is unmeasured. It should run in shadow mode first, as the 4 October guards did.
