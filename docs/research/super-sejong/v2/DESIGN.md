# Super Sejong Engine v2 — design

Date: 2026-10-04. Status: design for implementation; nothing here is shipped.
Scope: replace the vendored 윤문 엔진 (`vendor/humanize-engine`, label 2.3.2) completely. The LLM writer (Codex or Claude CLI) stays; Super Sejong Engine v2 owns ingest, protection, segmentation, diagnosis, prompting, post-processing, verification and decisions.

**Evidence labels.** Every number carries its source: `[T1]`…`[T12]` = the track reports in `v2/tracks/`, `[EVAL]` = `EVALUATION-2026-10-04.md`, `[CODE]` = read in the worktree, `[OD n]` = binding owner decision n (section 1.3), `[R]` = design reasoning, not measured. The tracks' own [M]/[C]/[R] labels still apply to the numbers quoted from them. All pair sets cited below were written by LLM authors; **no native Korean reader has rated anything** [EVAL §7, T2 §8, T3 §7, T6 §10].

---

## 1. Goals, non-goals, owner decisions

### 1.1 Goals

| # | Goal | How it is checked |
|---|---|---|
| G1 | Keep 말투 per sentence (level, mood, -시-, stance ending, persona, humble forms, CMC tokens). | Voice gate per aligned sentence; pair sets of [T2]; scorer of [T7]. |
| G2 | Fix only awkward Korean; "no edit" is a valid and common result. | Edit plan from high-precision detectors only; empty plan → no model call. |
| G3 | Preserve meaning: facts, numbers, names, quotes, negation, modality, roles, aspect, conditions. | Floor guards + meaning guards per sentence; aspect axis added. |
| G4 | Clarity, flow and CTA as criteria; never invent, drop, weaken or strengthen a CTA. | CTA ledger and gate [T6]; flow guards [T5]; clarity non-regression [T4]. |
| G5 | Idempotence: already-processed text returns nearly unchanged. | `v2(x)` on its own output and on the owner's drafts; `verify(x, x)` clean on every corpus document. |
| G6 | Cost not above the old engine. | 0 calls on an empty plan, at most 1 call + 1 targeted retry per chunk. |
| G7 | Same external contract where tests pin it; one switch for A/B (legacy vs v2). | Section 4. |

### 1.2 Non-goals

- Making text "less AI-like". LLM tells are not errors; they are suggest-only, genre-gated, and mostly "do not introduce" counters [T1 §3b, T3 §4, T8 §4.8].
- Style targets of any kind: sentence-length variance, ending variety, connective variety, change-rate targets, z-scores [T1 §6 Drop, T5 §5.2].
- Shortening, merging or reordering sentences or paragraphs; adding transitions, intros, outros or CTAs [T4 §5, T5 §5.2, T6 §9].
- A runtime LLM judge, a runtime spell-check service, any third-party MCP server [T11 §7, T12 Summary, OD 7].
- Shipping NIKL corpus text, dictionary text, owner text or model outputs in the repository [T9 D7, T7 §8].

### 1.3 Owner decisions (binding) and their design consequence

| OD | Decision | Consequence in v2 |
|---|---|---|
| 1 | 말투 is preserved strictly per sentence; the document profile is only a prompt aid. | Voice signature per sentence; gate and repair per aligned sentence; the profile appears in the prompt as one context line and never in a decision. E-7/E-2-style "unify/vary endings" rules are dropped. |
| 2 | 할께-type deliberate colloquial spellings and CMC tokens (ㅋㅋ ㅎㅎ ㅠㅠ ^^ ~, 뭐/진짜/사실) are kept by default; fixing them is opt-in, off by default. | They are `keep-token` protected spans; changing one is a voice violation. Flag `SUPER_SEJONG_FIX_COLLOQUIAL=1` turns the 할께 family into FIX and the CMC codes into info. |
| 3 | Misspellings such as 되요, 됬, 몇일, 금새 are errors and are fixed. | Closed, hand-written misspelling list, tier FIX, applied deterministically outside protected spans. |
| 4 | Spelling/grammar fixes only if honorifics do not change (no -시- or level change; 하실게요→해 주세요 is not allowed). | Every FIX rule must keep the voice signature (property test). The T6 `SILGE` repair (`-실게요 → -세요`) and the honorific-agreement fix (께서 … no -시-) are LEAVE. |
| 5 | Fix only awkward Korean; no edit is valid; meaning preserved incl. aspect; clarity/flow/CTA as criteria; CTA presence, force, specificity, deadline, channel kept; never invent a CTA. | Sections 3.3–3.9. |
| 6 | Already-processed text comes back nearly unchanged; main input = AI-written Naver blog drafts (~3,000 chars, mostly 합니다체 with 해요체 CTAs). | Replacement protocol: the model can only touch requested sentences; unrequested edits are reverted. Blog genre turns off the LLM-tell requests that are the owner's own voice. |
| 7 | No third-party MCP. Kiwi only offline or in a persistent worker. NLI blocked on licence → optional, shadow-first. | Regex backend is the runtime default; worker is optional (section 5.4, WP-16); NLI interface exists but cannot enforce. |
| 8 | Four bugs are fixed on main and assumed fixed in v2's base: P1 retry on unchanged text; `strip_injected_commas` deleting writer commas; `_order_swapped` on identical sentences; the blanket "keep protected sentences verbatim" rule (`rewrite-policy.ts:33`, `direct-text-fidelity.ts`). | v2 does not reintroduce any of them: no P1 axis, count/position comma rule, per-index ordering comparison, and per-edit guards instead of trigger-based protection. Each has a regression test in v2 (WP-5, WP-9, WP-10). |

---

## 2. Evidence summary (the numbers that drive the design)

| Design choice | Driving evidence | Source |
|---|---|---|
| Replace "rulebook + gate" with "diagnose → targeted requests → per-sentence verify". | On the owner's 10 Hermes drafts the old engine made 0 edits in 10/10; 463/640 sentences (72.3%) were blanket-protected by a regex; it spent 2 model calls for 0 edits in 8/10. | [T7 §0, §2] |
| Drop the P1 style-target axis and its retry. | `verify(x, x)` warns on 75% of blog posts (21/28), 81.2% of human essays, 99.5% of news; the identity can never pass; `comma_segment_length` points the wrong way. | [T1 §1.1–1.3], [T5 §0.6] |
| Do not send the vendor rulebook. | Only `quick-rules.md` (8,489 chars, 61 rules) reaches the model, whole, on every attempt incl. the conservative retry. E-2 fires on 100% of blog posts, E-7 on 35.7%, A-18 on 46.9% of blog sentences, E-1's condition holds for 96.1% of blog paragraphs. | [T1 §1.10, §1.8], [T4 §5] |
| Empty plan → no model call is the expected common case on the owner's drafts. | Norm detectors: 0 hits on the blog (28 posts, 81,743 chars) vs 17–20 per 10k on human student essays and 0.00–0.02 on LLM essays; glued dependent nouns 0 in 59,392 Hangul chars of the blog; mechanical library 3 hits (0.96 per 10k) on the 10 drafts; flow checks fire about 3 times in 28 posts; sentences of ≥ 28 eojeol are 0.84% of blog sentences (12 of 1,435). | [T3 Summary], [T9 §0.3], [T7 §2], [T5 §0.1], [T4 §0.3] |
| Per-sentence voice lock, never a document register. | Drafts: 521 합쇼체 vs 119 해요체 sentences (18.6%), 105 of them `-세요`; all 28 posts are 합쇼-dominant and every post has 해요체 sentences. The vendor caught 0/104 injected 해요↔합니다 drifts, the T2 gate 104/104. | [T7 §2], [T2 §6, Main results] |
| Port the T2 regex classifier and gate. | Blind holdout: regex 0.964 = Kiwi 0.964 vs TS `sentenceSpeechLevel` 0.736. Gate: 0/64 hard false positives, 64/64 drifts caught (hard+soft); 0 false flags on 1,202 paragraphs of voice-neutral edits; repair restored 620/620. | [T2 §2, §4] |
| CTA ledger and gate. | Vendor sees 2/144 CTA units (1.4%), v1 36/144. New gate: 0/322 force-neutral rewrites flagged, 459/487 violating rewrites blocked on the drafts; 0/108 hard false positives and 102/113 blocked on the pooled pair sets (tuned). The current engine misses invented CTAs 25/25 and "optional" weakening 25/25. 0/107 draft CTA sentences carry a wording defect. | [T6 §0, §6] |
| Flow guards relative to the writer's own text, not population thresholds. | Shipped gate: added transitions 0/56, dropped contrast 0/42, paragraph merge 0/56. Proposed guard 94–100% (in-sample) with 1/77 false alarms on benign edits. | [T5 §4] |
| Clarity = non-regression guard + one targeted action. | Only 2–3 of about 20 mechanical clarity checks reach usable precision; scope/reference/hedge defects 0–16% precision. | [T4 §0, §3] |
| Keep and extend the v1 meaning guards; NLI only as shadow. | Shipped guards: 11.7% overblock / 18.3% miss on the set never tuned on; T7's harder probes: 76.6% sensitivity, 48% overblock. NLI OR-veto cut misses 11/60 → 2/60 but the tested checkpoint has no licence. | [EVAL §2], [T7 §7], [T11 §3] |
| Aspect axis and explicitation gate. | E-2 maps `~고 있다` to the simple form (aspect change); literature supports keeping -고 있-/-어 있- and forbidding new 때문/그러나/따라서. | [T3 §5], [T8 §4 items 4–5] |
| Authority tiers FIX / SUGGEST / LEAVE. | NIKL rarely says "wrong, write X" (5/34 Q&A items, all spelling or agreement); NIKL expert edits are 50.7% spelling/spacing/punctuation; translationese items fire more on professional human prose than on LLM text. | [T9 §0.2, §0.5], [EVAL §5] |
| No whole-sentence re-spacing, no 다듬은 말 lexicon, no -적 deletion. | Kiwi `space()` flags 84.2% of news sentences; 다듬은 말 (filtered) fires on 82% of blog posts; -적 AUROC 0.81 essay, 0.51 abstract. | [T9 §7 M1b, M4], [T8 §1c] |
| Fix the comma stripper. | It removed 124 writer commas in 122 blog sentences after a one-word edit: 100% of the writer's commas in every touched sentence. | [T1 §1.7] |
| Fix splitter and chunker. | Glued terminators ("…한다.논문에서는"): 10.3% of LLM-abstract, 5.7% of human-essay, 19.5% of KLUE-hankyung boundaries; blog 3.4%. Chunker: 8.8% of packing seams start with a connective, 8.1% orphan an unmarked heading; numbered lines force cuts (median chunk 574 chars on synthetic long docs). | [T5 §2.1, §5.3] |
| Regex runtime; Kiwi only in a worker. | Kiwi per spawn 0.93 s and 582 MB; persistent worker 57 ms per 2×2.6k chars, 510 MB; the regex splitter misses only 0.4% of boundaries Kiwi and KSS agree on (blog). | [T11 §1.2] |
| Banded alignment, no quadratic paths. | T2 gate 0.15 s per 3k post but 11 s at 30k (quadratic); old `change_rate` 86 s on 20k repetitive chars, >120 s at 85k; T6 detect 11.7 s and compare 56.9 s on adversarial input before its fix. | [T2 §2], [EVAL §1], [T6 §0.7] |
| Minimal-edit contract with a closed taxonomy and an explicit "none" exit. | Korean GPT-4 GEC precision 0.44 (Maeng 2023); NIKL 2024 instruction corpus uses a closed 25-type list with an explicit "no error" exit. | [T8 §4 item 7], [T9 D3] |
| v1 style hints are not a repair engine. | v1's 15 style rules recall 12.7% (18/142) of injected seed defects; 0 findings on 49 natural controls. | [T7 §7] |

---

## 3. Pipeline

### 3.0 Overview

```
input ──► [1 ingest+protect] ──► [2 segment+chunk] ──► per chunk:
            sanitize, spans          paragraphs, sentences,
                                     manifest v1, seams
   [3 analyse] ─► plan.json (sentences+voice, CTA ledger, meaning ledger, findings by tier, requests)
        │
        ├─ plan.needsModel == false ─────────────────────────────┐   (no model call)
        ▼                                                        │
   [4 prompt] minimal-edit contract + voice sheet + requests     │
        ▼                                                        │
   writer LLM ─► {"replacements":[{id,text,reason}],…}           │
        ▼                                                        ▼
   [5 apply] replacements → candidate (full-text fallback)   candidate = source
        ▼                                                        │
   [6 repair] norms, CMC restore, voice graft, josa, commas ◄────┘
        ▼
   [7 verify per sentence] floor, meaning(+aspect), voice, CTA, flow, clarity, introduced norms, quantities, spans
        ▼
   [8 decide per sentence] accept | targeted retry (named violation, once) | revert sentence
        ▼
reassemble ──► [9 document verify] seams, duplicates, floor ──► output + diagnostics (codes and counts only)
```

Steps 3 and 5–8 are Python (shared by the server path, the agent-skill path and the Office path); TypeScript orchestrates, renders the prompt from the plan, calls the writer and parses its reply [R: one implementation of every detector and gate; the three paths cannot drift apart, which T1 lists as an unpinned behaviour, T1 §2 "Behaviours no test pins"].

### 3.1 Ingest and protect

- **Sanitize** = port of `sanitize_text.py` unchanged in behaviour (zero-width, BOM, bidi and tag characters removed, NBSP → space, recompose only decomposed Hangul; never NFKC of compatibility jamo [EVAL §6 G]); it is correct and 말투-neutral [T1 §5]. Report `00_sanitize.json` as today.
- **Protected spans** (`protect.py`), each with a policy:

| Kind | Detection | Policy |
|---|---|---|
| quote | paired “…” ‘…’ "…" 「…」 『…』, per paragraph (patch behaviour), linear-time masking; an unclosed opener masks to paragraph end | `freeze` (verbatim) |
| number+unit, date, %, %p, 배, money | quantities regexes from `quantities.py` and `super_sejong._NUM` | `freeze` |
| URL, e-mail, phone, handle, hashtag | regex | `freeze` |
| Latin name/acronym token | `workflow._NAME_TOKEN` | `freeze` |
| code fence, inline code, Markdown syntax (#, list markers, link targets, emphasis marks) | line and inline regex | `freeze` |
| heading line, footnote marker/definition | chunker heading rule (3.2), `checks.check_footnotes` rules | `freeze` |
| CMC token (ㅋㅋ ㅎㅎ ㅠㅠ ^^ ~ … !! emoticons) | T2 `cmc_tokens`, `EMO_RE` | `keep-token` (multiset per sentence must survive) |
| colloquial spelling (할께 family) and sentence-initial discourse markers (뭐, 진짜, 사실, …) | `data/voice_lexicon.json` | `keep-token` unless `SUPER_SEJONG_FIX_COLLOQUIAL=1` |

`freeze` spans cannot be edited by the model (prompt) or by any repair, and any change is a floor failure `protected_span_changed` on that sentence. `keep-token` spans may move inside the sentence but their multiset must survive [T2 §4 soft codes, T7 §3.2, OD 2].

### 3.2 Segmentation and chunking

**One sentence splitter** (`text.split_sentences`) replaces the three that exist (`_TERMINAL` in `super_sejong.py`, `sentencesIn` in `super-sejong.ts`, the vendor chunker) [T5 §2.1]:
- Boundaries: `[.!?。！？…]+` plus closing quotes/brackets, followed by whitespace **or** by a Hangul syllable or an uppercase/Latin word start (the glued-terminator fix), and every newline.
- Not boundaries: decimals and versions (`3.5`, `1.2.3`), list ordinals at line start (`1.`), abbreviations (`U.S.`, `e.g.`), URLs and e-mails (masked), ellipsis inside a quote, terminators inside a masked quote.
- Units carry code-point offsets (Python) **and** UTF-16 offsets (TS, prompt), paragraph index and kind (`body | heading | list | quote | button`).

**Chunking** (`chunk.prepare`) keeps the manifest v1 contract [T1 §2 prepare] and changes three things:
1. Single span for ≤ 15,000 chars, regardless of `route_hint` (the hint came from placeholder baselines [T1 §4 Baselines]). `route_hint` is emitted as `null`, `route_reason` as `"sejong:single"` or `"sejong:chunked"`. The owner's ~3,000-char drafts are always single-chunk [T7 §2].
2. **Heading rule fix.** A forced cut happens only before a Markdown `#` heading, a `제N장/절/편` line, a Roman-numeral heading, or an *unmarked heading*: a line ≤ 40 chars with no terminal punctuation, followed by a longer paragraph [T5 §5.3]. Lines starting `1. `, `1) `, `가. ` or `(주)` are list items or names, not headings. Consecutive small sections are packed together up to the target.
3. **Paragraph-first packing with seam rules.** Target 7,000 / cap 9,000 chars as today. Cut only at paragraph boundaries; move a cut one paragraph earlier when the next chunk would start with a connective or a demonstrative (이/그/이는/이를/이러한…) or when the previous chunk would end with an unmarked heading, provided the chunk stays ≥ 50% of target [T5 §5.3]. Each chunk records read-only **seam context**: the last 1–2 source paragraphs before it (≤ 600 chars) and the first paragraph after it (≤ 300 chars), taken from the source so chunks still run in parallel.

Reassembly keeps the whitespace re-attachment and SHA checks. A length-ratio failure (< 0.5 or > 2.0) **rolls back that chunk** and records `CHUNK_ROLLED_BACK` instead of failing the job [T1 §6 Improve 9].

### 3.3 Analyse: per-sentence signatures and diagnostics

`analyse` produces `plan.json` (shape in 3.12). For every sentence:

- **Voice signature** (T2 `signature`, regex backend): `level` ∈ {HAPSYO, HAEYO, HAERA, HAE, HAO, HAGE, NOMINAL, NONE}, `mood` ∈ {DECL, INTERR, IMPER, PROPOS, EXCL}, `honSi` (-시- on the final predicate), `siCount` (-시- anywhere), `stance` (ending family: 더라고요, 거든요, 잖아요, 네요, 죠, ㄹ게요, …), `persona` (저/제가/저희 vs 나/내가/우리), `humble` (드리다, 여쭙다, 뵙다), `addressee`, `cmc[]`, `discourse[]`, final eojeol. Quotation-internal levels are recorded separately [T2 §4].
- **CTA ledger** (T6 `detect`): per CTA unit `form, force(0–5), tier, polarity, action[], object, condition, deadline[], channel[], benefit[], intensity[], level, honSi, para`. Plain deontic statements (`~해야 합니다`) are tracked in the meaning ledger, not as CTAs [T6 §4].
- **Meaning ledger** (v1 `features` + new axes): negation count and short-negation targets, modality classes (OBLIG, PROHIBIT, NOREQ, REC, CAN±, HEDGE), quantifiers, bounds (이상/이하/초과/미만), lexical axes, participant frames, **aspect** (progressive -고 있-/-는 중이-, resultative -어 있-), **partial negation** ("모든 …는 것은 아니다") [T4 §6, T8 §4.5], signed quantities.
- **Diagnostics** with an authority tier. The table below is the complete v2 rule set; anything not listed is not sent to the model.

**Tiers.** FIX = a human-norm error (NIKL norm or high-precision agreement break): the engine applies it (`deterministic`) or sends a `request` the model should act on. SUGGEST = optional request the model may decline; never a failure if it remains. LEAVE = never requested; may still be a "do not introduce" counter in verification [T9 D4, T10 R1].

| Rule | Trigger (short) | Tier / action | Genres | Evidence (precision; rates per 10k chars) |
|---|---|---|---|---|
| SSJ-N01 bound-noun spacing | final-ㄹ syllable+수 있/없/밖에, final-ㄴ/ㄹ+것, final-ㄹ+때; excl. 실수 없이, 날것/들것/탈것/별것, 물때, 할수록 | FIX / deterministic | not poetry, quotes, headings, hashtags | 59/60 [T3 §4]; blog 0 [T3, T9] |
| SSJ-N02 `-지 않` spacing | 지않 not after 마/머/못 | FIX / deterministic | same | 20/20 [T3] |
| SSJ-N03 율/률 | 율 after non-ㄴ final, 률 after vowel/ㄴ; excl. surnames | FIX / request (expected form given) | all | 26/27 [T3]; LLM abstracts 0.47 [T3] |
| SSJ-N04 misspelling list | closed list `data/misspellings.json` class `error` (되요→돼요, 됬→됐, 몇일→며칠, 금새→금세, 거에요→거예요, 번번히→번번이, …) | FIX / deterministic | all, outside spans | 22/22 after fix [T3]; OD 3 |
| SSJ-N04c colloquial spelling | same list, class `colloquial`: the 할께 family (할께, 할께요, -ㄹ께); other pronunciation-based forms (할려면 …) wait for the owner's answer (9.2 item 1) | LEAVE (FIX/deterministic if opt-in) | — | OD 2 |
| SSJ-N05 이였/이예요 | final-consonant noun + 이였/이예요; excl. nouns ending in 이 (외톨이였던) | FIX / request (regex 24/30); deterministic only with the Kiwi worker (13/13) | all | [T3 §3] |
| SSJ-N06 로서/로써 | role noun+로써; 함으로서/됨으로서; 이로서 | FIX / request | all | 7/7 small n [T3] |
| SSJ-A01 왜냐하면 | sentence with 왜냐하면/왜냐면 and no reason ending (때문, 니까, 잖, 기에, 므로, 거든, 서이다) | FIX / request; success = reason ending present | not spoken transcripts, poetry | 25/26 [T3]; 11/12 [T8] |
| SSJ-A02 thought double | (제/저의/나의) 생각·의견은 … 생각합니다 | FIX / request | all | 10/10 [T3] |
| SSJ-A03 object+passive | 을/를 + verbal noun + 되다 adjacent; excl. -게 되다, 일관되게 | FIX / request; role guard must pass | all | 4/4 after fix [T3] |
| SSJ-A04 double passive | closed list (되어지, 보여지, 쓰여지, 나뉘어지, 읽혀지, 불려지); excl. 느껴지/여겨지/남겨지, -게 되다, 이루어지/만들어지 | FIX / request | prose only | 30/30 as category [T3]; closed list [T8 #10] |
| SSJ-A04s 잊혀지다 | 잊혀지- | SUGGEST | not poetry/lyrics | genre convention [T3] |
| SSJ-A06 negative-polarity adverb | 결코/좀처럼/차마/전혀 without negation (모르다 counts as negative) | FIX / request | all | ~1 hit in 5.13M chars; cheap [T3 §3] |
| SSJ-A07 비록/아무리/만약 agreement | missing concessive/conditional ending | FIX / request | all | rare [T3, T8 §1a] |
| SSJ-A05 redundancy (겹말) | `data/redundancy.json` (T3 list minus 해변가, 부상당하다 contested) | SUGGEST; never touch the number in 약 N 정도 | all | 52/55 [T3]; 겹말 is SUGGEST in NIKL policy [T9 D4] |
| CTA-SP1/SP2 CTA spacing | `[가-힣]{2,}해주세요` → `해 주세요`; 연락/문의/답변/회신/댓글/말씀/조언+주세요 | FIX / deterministic | all | NIKL 331217, 326874 [T6 §5] |
| CTA-SILGE `-실게요` | `실게요/실께요` | **LEAVE** (report only) | — | OD 4 overrides T6 `safe_repair` |
| CTA-BARAE 바래요 | 바래요 | SUGGEST | all | FP risk 빛이 바래요 [T6 §5] |
| CLR-LONG long multi-clause | ≥ max(28, genre P99) eojeol and ≥ 4 clause endings, no direct quote, not a CTA-fused sentence unless the CTA clause is kept verbatim | SUGGEST / request with `allowSplit` (strength ≥ medium) | blog/essay 28, news/abstract ~40 | essay 72%, news 23% TP; blog 6/12 [T4 §3–4] |
| CLR-APPROX2 | 약/대략/거의 + N + 가량/정도/쯤/안팎/내외 | SUGGEST (delete the trailing marker) | mostly news | 10/10 [T4] |
| Translationese hints | 가장 ~ 중 하나, ~에 있어서(narrowed), 을 필요로 하다, 을 가능하게 하다, A, B, 그리고 C, needless -시키다 (transitive base) | SUGGEST | essay, report, document | patterns 20/20–30/30; no human/LLM separation for -시키다 [T3 §3], [T8 #13] |
| v1 style rules kept as SUGGEST | PROCESS_NOMINALIZATION, PUBLIC_LANGUAGE_FRAME, THROUGH_CLUSTER, JEOK_CLUSTER (essay only), CAUSAL_LEAD, CONNECTOR_RUN (formal list; "keep if relations differ") | SUGGEST | essay, report (CONNECTOR_RUN all) | [EVAL §3], [T5 §6], [T8 #14] |
| Light-verb nominalisation (all genres, incl. blog) | N이 가능하다 → -(으)ㄹ 수 있다; N이 되다 (인정이 됩니다) → N되다; N이 이루어지다 → N되다/N하다; N을 진행하다·실시하다 → N하다; excl. quotes, legal/defined terms, and any rewrite that changes the CAN/MUST/NEG class | SUGGEST / request | all | lead decision 2026-10-04: the first live run after the main hotfixes produced exactly these edits (인정이 됩니다→인정됩니다, 진행이 가능하며→진행할 수 있으며, 요청이 이루어질→요청할) and all were meaning- and voice-preserving; NIKL easy-writing guidance recommends them [T4 §2]; without this row the owner's AI drafts would make 0 calls at medium |
| LLM tells | IMPORTANCE_FORMULA, CONCLUDING_SIGNPOST, DEMONSTRATIVE_THROUGH, ROLE_FORMULA→ROLE_ADJ (adjective+역할), BOILERPLATE_ANNOUNCE (quoted commitments excluded), 나가야, sentence-initial 이는 | SUGGEST in essay/report; **LEAVE in blog** (BOILERPLATE 1.22 and IMPORTANCE 1.83 per 10k are the owner's voice); always "do not introduce" | — | [T3 §3–4] |
| LEAVE (never requested) | ENDING_MONOTONY, INTENSIFIER_CLUSTER, CAPABILITY_HEDGE_CLUSTER (its guide changes modality), register mixing, honorific agreement and 사물 존칭 (OD 4), 에서의/로 인해/에 의해/로부터/이러한/그녀, cleft, modifier stacks, noun strings, scope/reference ambiguity, optional spacing (Arts. 43, 46–50), Kiwi re-spacing, 다듬은 말, -적 deletion, loanword substitution, connective variety, length/CV targets, vendor E-1/E-2/E-4/E-7/A-1/A-7/A-18/D-13/D-14 | LEAVE | — | [T1 §3a], [T3 §3], [T4 §3, §6 Tier C/D], [T5 §6], [T8 §3], [T9 §3] |
| SUGGEST, closed calque lists (WP-8b, 2026-10-05) | TR-GAJIDA (abstract noun + 을 가지고 있다), TR-JUNGE_ITDA (verbal noun + 중에 있다), TR-DAEHAE (에 대해서 + 안내/설명/논의 … 하다), TR-ROBUTEO (person noun + 으로부터 + receiving verb). Narrow closed-list versions of the LEAVE patterns above (로부터, vendor A-1/A-7): the LEAVE row still holds for the open patterns. Found missing in the lead's first real-model run (general genre). | SUGGEST | all | WP-8b report: precision 92/93, 13/13, 54/54, 20/20 on hand-checked samples of the T3 corpora (single LLM annotator; on a stricter "reads stiff in context" criterion TR-DAEHAE ≈14/50 and TR-ROBUTEO ≈7/20, mostly news style); 0 hits on the 28 owner posts and the seed blog items; NIKL 공공언어 바로 쓰기 (2022) pp. 42, 44, 54, 98, 100 treat 에 대하여/중에 있다/으로부터 as translationese |

Detectors run on the sentence text with `freeze` spans masked. A rule's guide line (Korean, one line) comes from `data/guides.ko.json`; it never claims NIKL backing for a SUGGEST rule [T9 D4].

### 3.4 Edit plan

`plan.build_plan(chunk, options)`:
1. Deterministic FIX findings are recorded with their fix (applied in step 6, so they also apply when no model call happens).
2. Request findings are grouped per sentence: **one request per sentence** (`R1…`), carrying all findings of that sentence (`rules[]`, spans, guides) and the sentence's voice line.
3. Strength decides which tiers become requests. The four strengths stay in the API (`REWRITE_OPTIONS`, `parseRewriteOptions` are pinned [CODE tests/unit/rewrite-policy.test.ts]); their meaning changes:

| Strength | Requests | Extra |
|---|---|---|
| normal (also every text-file job) | FIX | — |
| medium (owner's route) | FIX + SUGGEST | open review, as strong (lead decision 2026-10-04, 9.2 item 2): medium makes one call per chunk even when no rule fires, because the owner's drafts are AI-written and their awkwardness is mostly outside the mechanical rule set |
| strong | FIX + SUGGEST | open review: the model may nominate up to `max(3, ceil(0.1·n))` further sentences, each with a reason from the closed taxonomy (NIKL 25 types [T9 D3]) |
| very-strong | as strong | `allowSplit` on open-review sentences; full-text fallback allowed |

All strengths go through the same per-sentence verification; strength never relaxes voice, meaning, CTA or flow guards [R; T1 §4 P0 notes the old strength–gate clash].

4. `needsModel = requests non-empty or openReview.enabled`. **If false, no model call is made**; the candidate is the source plus deterministic fixes [T7 §10.2, G6].

Prediction to verify (not a measurement): on the 10 Hermes drafts at medium/blog, the v1 style findings were BOILERPLATE 4, IMPORTANCE 2, CAUSAL_LEAD 1, ENDING_MONOTONY 1 and the mechanical library found 3 NOMIN hits [T7 §2]; under the table above none of them is a request in blog genre (BOILERPLATE and IMPORTANCE are LEAVE in blog, ENDING_MONOTONY is LEAVE, CAUSAL_LEAD and the nominalisation hints are essay/report SUGGEST), and 0 of 107 draft CTA sentences carry a wording defect [T6 §0.6], so most drafts should make 0 calls at medium. WP-15 measures it.

### 3.5 Prompt

Built in TypeScript from `plan.json` (`src/engine/sejong/prompt.ts`). No rulebook is sent, on any attempt [T1 §6 Keep 4]. Sections:

1. **Role and data boundary.** Kept from today: the nonce-delimited `BEGIN_SOURCE_<nonce>`/`END_SOURCE_<nonce>` block and the injection-defence paragraph [CODE prompt-builder.ts].
2. **Minimal-edit contract** (fixed text, ≤ 2,500 chars):

```
너는 한국어 교정 보조자다. 아래 [요청]에 있는 문장만 다룬다.
- 요청마다 그 문장 전체를 고친 결과를 replacements에 하나 담는다. 고칠 이유가 없으면 그 요청을 생략한다. 생략은 정상 결과다.
- 표시된 어색한 부분만 고친다. 사실·수치·이름·인용·부정·가능·의무·추측·시제·상(-고 있-·-어 있-)·조건·행위 주체를 바꾸지 않는다.
- 말투 잠금: 각 문장의 마지막 어절(종결형)과 문장 유형(평서·의문·명령·청유), '-시-', 저/저희·드리다, ㅋㅋ·^^·~·할께 같은 표기, 사실·뭐·진짜 같은 담화 표지는 원문 그대로 둔다. 문서에 합쇼체와 해요체가 섞여 있으면 섞인 그대로 둔다.
- 새 접속어·전환 문구·요약·인사·CTA를 만들지 않는다. CTA 문장은 행동·대상·조건·기한·채널·강도를 그대로 둔다.
- 문장을 합치지 않는다. allowSplit 요청에서만 나눌 수 있고, 나눈 문장도 원문과 같은 말투로 끝낸다.
- [보호] 구간(따옴표 인용, 숫자, 링크, 영문 이름, 표기)은 한 글자도 바꾸지 않는다.
```

3. **Voice sheet** for requested sentences only, one line each, T2 format: `S7 해요체·명령·시 「확인하세요」 keep:[~]` [T2 §5].
4. **Document profile**, one line, labelled as context: `참고: 합쇼 82%, 해요 CTA·질문 섞임 — 섞임은 의도된 것` [T2 §5, OD 1].
5. **Requests** as JSON: `[{"id":"R1","sentence":"S7","text":"…","rules":["SSJ-A01"],"guides":["…"],"tier":"FIX","allowSplit":false,"frozen":["30%","「…」"],"prev":"…","next":"…"}]`. `frozen` lists the `freeze` spans inside that sentence (the [보호] items of the contract); `prev`/`next` are the neighbouring source sentences, read-only.
6. **Seam context** (chunked documents only): previous/next source paragraphs marked `참고 전용, 출력 금지` [T5 §5.3].
7. **Full chunk source** in the nonce block, read-only, so the model sees context; it may not output it.
8. **Output format**: the v2 schema below. Strict JSON, no Markdown fences.

```json
{"type":"object","additionalProperties":false,"required":["replacements","rewrittenText","warnings"],
 "properties":{
  "replacements":{"type":"array","maxItems":200,"items":{"type":"object","additionalProperties":false,
     "required":["id","text","reason"],
     "properties":{"id":{"type":"string","pattern":"^(R|S)[0-9]{1,4}$"},"text":{"type":"string","minLength":1,"maxLength":4000},
                   "reason":{"type":"string","maxLength":60}}}},
  "rewrittenText":{"type":"string"},
  "warnings":{"type":"array","maxItems":20,"items":{"type":"string","maxLength":300}}}}
```

`id` = a request id, or a sentence id (`S…`) only when open review is enabled. `rewrittenText` must be empty unless `plan.allowFullText` (very-strong) and `replacements` is empty.

**Retry prompt** (attempt 2, at most once per chunk): the same contract, only the failed requests, each with its named violations rendered in Korean, e.g. `R3 이전 답: 말투가 합쇼체 평서에서 해요체로 바뀌었다(voice_level). 종결 「없습니다」를 유지하라.` or `R5 이전 답: '반드시'가 사라졌다(modality_changed).` No style hints, no new requests [T1 §6 Keep 4].

### 3.6 Apply

`apply.apply_response(plan, source, response)`:
- Reject the whole response (`MODEL_OUTPUT_UNUSABLE`, counts as the attempt) if JSON/schema invalid, an id is unknown or repeated, or `rewrittenText` is used when not allowed.
- Per replacement: reject (→ status `rejected`, eligible for retry) if the text contains a newline, a `freeze` span of the sentence is not present verbatim, or the length ratio to the source sentence is outside [0.5, 2.0] (×2 for an `allowSplit` request). Otherwise splice it over the source sentence span (trailing whitespace kept).
- **Full-text fallback** (`rewrittenText`): align the full text to the source (3.8 aligner); a changed aligned sentence with a request becomes that request's replacement; a changed sentence without a request is reverted (`collateral_edit`). This also makes legacy-style replies usable.

### 3.7 Repair (deterministic, per aligned sentence, in this order)

1. **Norm fixes**: every FIX/deterministic finding (N01, N02, N04, CTA-SP1/2, and N05 when the worker is on) on the candidate sentence, outside `freeze` spans. They fix source errors too [OD 3] and are idempotent.
2. **CMC / keep-token restore**: a missing `keep-token` from the source sentence is reinserted at the corresponding position when the change is a pure deletion (T2 `restore_emoticons`), otherwise the sentence is marked for revert.
3. **Voice graft**: for `voice_level`, `voice_hon_si_*`, `voice_stance`, `voice_colloquial_changed`, copy the writer's own final eojeol and final punctuation back onto the rewritten clause when the lemma keys match; never for a mood change, a quotation or a NOMINAL/NONE sentence; residual violation → revert [T2 §4 Repair]. Grafting reuses the writer's own form and cannot invent a conjugation [T2].
4. **Josa repair**: introduced allomorph mismatches at `likely` level (v1 `super_sejong_josa.gate`/`repair`) [EVAL §4].
5. **Comma rule** (fix of `strip_injected_commas`): per aligned pair, let k = connective-ending commas in the source sentence; remove only candidate commas at positions not matched in a character alignment to the source sentence, and only while the count exceeds k; keep noun-list and quote exceptions; a sentence-initial 그리고/하지만/그러나/그런데 comma is removed only if newly inserted [T1 §6 Improve 4].

The old `restore_modality` step is not ported as a separate stage: a modality change is a meaning violation and leads to the same sentence revert in step 8, with all 해요체 forms covered (v1 catches 9/10 probes vs vendor 2/10 [T1 §1.6]). The report key `restoredSentences` keeps its name and counts meaning-family reverts.

### 3.8 Verify per sentence

**Alignment** (`align.py`), computed once per check and shared by every family: paragraph-first (paragraph counts usually equal; pair paragraphs by order and bigram cover), then a monotone banded DP inside each paragraph pair with moves 1:1, 1:2, 2:1, 1:0, 0:1 on character-bigram Dice; band = `2·|n−m| + 8`; global banded fallback when paragraph counts differ. In the replacement protocol most pairs are known by construction (sentence ids), and the aligner only resolves splits inside a replacement.

**Families and codes.** Codes are lowercase `[a-z_]{1,60}`, because the TS parser drops anything else from `shadowFailures` [CODE python-engine.ts verify()].

| Family | Hard codes | Soft codes | Default mode under v2 |
|---|---|---|---|
| floor (cannot be disabled) | `empty_output`, `quote_altered`, `heading_lost`, `heading_absorbed`, `footnote_count`, `footnote_numbers`, `footnote_def`, `footnote_anchor`, `number_injected`, `number_dropped`, `quantity_changed`, `name_changed`, `sentence_dropped`, `protected_span_changed`, `josa_mismatch` (certain) | — | enforce |
| meaning | `polarity_changed`, `modality_changed`, `lexical_polarity_changed`, `participant_role_changed`, `aspect_changed` (new), `partial_negation_changed` (new) | — | enforce |
| voice | `voice_level`, `voice_mood`, `voice_hon_si_dropped`, `voice_hon_si_added`, `voice_quote_level`, `voice_split_level`, `voice_merge_across_levels`, `voice_merge_lost_mood`, `voice_merge_lost_hon_si`, `voice_inserted_level` | `voice_stance`, `voice_persona_swap/dropped/added`, `voice_humble_dropped`, `voice_emoticon_dropped/added`, `voice_colloquial_changed`, `voice_discourse_dropped`, `voice_colloquial_added`, `voice_hon_si_elsewhere`, `voice_written_upshift` | enforce |
| CTA | `cta_dropped`, `cta_invented`, `cta_force_weakened`, `cta_force_strengthened`, `cta_polarity_flipped`, `cta_action_changed` (closed-class acts), `cta_action_count_changed`, `cta_condition_changed`, `cta_deadline_changed`, `cta_channel_changed`, `cta_benefit_dropped` | `cta_object_changed`, `cta_action_replaced`, `cta_moved`, `cta_to_deontic`, `cta_from_deontic`, `cta_offer_dropped` | enforce |
| flow | `flow_transition_added`, `flow_contrast_changed`, `flow_paragraph_count_changed`, `flow_order_changed`, `flow_duplicate`, `flow_context_leak`, `flow_seam_connective_changed` | `flow_sentence_added` | enforce; `flow_sentence_added` shadow (false-alarm rate on real rewrites unknown [T5 §6]) |
| clarity | `clarity_longer_sentence` (> source longest aligned + 2 eojeol or above the LONG trigger), `clarity_bare_demonstrative_added`, `clarity_agentless_oblig_added`, `clarity_acronym_gloss_dropped`, `clarity_number_marker_changed` (배, %p, 이상/이하), `clarity_list_structure_changed` | — | shadow (false-block rate unmeasured [T4 §6]) |
| norms (introduced-only) | `norm_introduced` (N01–N06, A04 list, misspelling list) | `tell_introduced` (LLM-tell count rose in the sentence: hayeot, cliché, IMPORTANCE, CONCLUDING, …) | enforce |
| request status (report only) | — | `FIXED`, `UNTOUCHED`, `STILL_PRESENT`, `LOST`, `DECLINED` per request; rule-specific success checks (A01 fixed only if a reason ending is present; deleting 왜냐하면 is logged separately) [T3 §6] | — |
| runaway | `change_rate_runaway` (chunk change rate ≥ 0.50 against the base; linear-time segmented measure) | — | enforce |
| NLI (optional) | — | `nli_mutual_entailment_failed` | off/shadow only [OD 7] |

Precision context: voice hard FP 0/64 [T2]; CTA hard FP 0/108 (tuned) [T6]; flow benign FA 1/77 [T5]; meaning overblock 11.7% (untuned) to 48% (T7 heavy-paraphrase probes) [EVAL, T7]. Because a false positive in v2 costs one sentence revert (that sentence stays as the writer wrote it, which OD 5 accepts) rather than a chunk rollback, the hard families can enforce from the first v2 release [R]. Shadow remains for families with no false-positive estimate at all.

### 3.9 Decide per sentence

For each source sentence s with candidate c(s):

| Situation | Attempt 1 | Attempt 2 |
|---|---|---|
| c(s) = base(s) (source + deterministic fixes) | `unchanged` / `deterministic` | same |
| changed, no request, not a deterministic fix | revert, `collateral_edit` | revert |
| changed, hard code in an enforced family | `retry` with the named violations (if the chunk's retry budget is unused) | revert |
| changed, soft code | repair (3.7); residual → `retry` | residual → revert |
| replacement rejected in apply | `retry` | revert |
| clean | `accepted` | `accepted` |

- One retry call per chunk at most; it contains all `retry` requests. Accepted sentences from attempt 1 are kept; attempt 2 edits apply on top of the attempt-1 decided candidate, and every sentence is verified again against the source.
- `base(s)` must pass verification against the source (invariant `verify(x, base(x)) == ∅`, tested on all fixtures), so reverting always yields a valid chunk.
- Chunk-level outcomes, mapped to the legacy gate contract: exit 0 = accepted (possibly with reverted sentences, reported as warning `SEJONG_SENTENCES_REVERTED`); exit 1 = accepted with residual soft or shadow-only findings at attempt 2 (`CHUNK_WARNING_ACCEPTED`); exit 2 = floor failure that survives reverts, `change_rate_runaway` at attempt 2, or unusable output twice (`CHUNK_ROLLED_BACK`); exit 3 = execution error (`VALIDATION_FAILED`). The legacy decision table (0 accept, 1/2 at attempt 1 retry, 2 at attempt 2 rollback, 1 at attempt 2 accept-with-warning, 3 error) is preserved [T1 §2 Gate].
- Change rate is only the runaway guard. There is no 0.30 warning band [T1 §4 P0, OD 5].

### 3.10 Document level

After reassembly, `verify --document` runs the floor on the whole text (footnotes need the whole document [CODE python-engine.ts documentContext]), the seam invariants (first sentence keeps its initial-connective class and demonstrative starter; no new first or last sentence; `flow_context_leak`: an output sentence with bigram cover ≥ 0.85 against the seam context and < 0.5 against its own source [T5 §5.3]), and adjacent near-duplicates across seams. A seam violation reverts the offending sentences; a residual floor failure reverts the whole document to the source with `DIRECT_TEXT_DOCUMENT_ROLLED_BACK` (code kept) instead of throwing `VALIDATION_FAILED` [R: the source is always a valid output; this is an intended contract change, see 4.5].

### 3.11 Why this is idempotent

- A sentence can only change through a request or a deterministic fix. Deterministic fixes are idempotent (`fix(fix(x)) = fix(x)`, tested). On a second pass, FIX rules no longer fire on fixed sentences, so only declined SUGGEST requests can re-trigger a call, and they change nothing when declined again.
- Unrequested edits are reverted by construction (`collateral_edit`).
- Evidence on the owner's genre: re-processing the 28 posts gives 0 voice flags [T2 §6]; `compare(x, x)` = 0 CTA findings on 3,909 corpus docs + 20 posts + 10 drafts [T6 §0.6]; 0 of 107 draft CTA sentences carry a wording defect [T6]; the norm layer has nothing to fix on the blog [T3, T9]. Baseline to beat: the text-file route changed 17/20 already-processed posts again [T7 §3.5].

### 3.12 JSON shapes

**Plan** (`plan-<chunk>.json`, schema `sejong-plan/1`):

```json
{
  "schema": "sejong-plan/1",
  "engine": {"id": "super-sejong", "version": "2.0.0"},
  "chunk": {"index": 1, "total": 1, "sourceSha256": "…", "chars": 3112},
  "options": {"inputKind": "direct-text", "strength": "medium", "genre": "blog",
              "fixColloquial": false, "deterministicFix": true, "openReview": false, "allowFullText": false},
  "sentences": [
    {"id": "S7", "start": 412, "end": 451, "startU16": 412, "endU16": 451, "para": 3, "kind": "body",
     "voice": {"level": "HAPSYO", "mood": "DECL", "honSi": false, "siCount": 0, "stance": "ㅂ니다",
               "persona": [], "humble": false, "cmc": [], "discourse": [], "final": "없습니다"},
     "cta": null, "meaning": ["NEG:1", "OBLIG:0", "ASPECT_PROG:1"], "findings": ["F3"]}
  ],
  "protected": [{"kind": "number", "start": 430, "end": 433, "policy": "freeze"}],
  "ctaLedger": [{"id": "C1", "sentence": "S30", "form": "request", "force": 4, "tier": "contact",
                 "polarity": "pos", "action": ["상담"], "object": "상담", "condition": "궁금한 점이 있으시면",
                 "deadline": [], "channel": [], "benefit": [], "intensity": [], "level": "haeyo", "honSi": true}],
  "findings": [{"id": "F3", "rule": "SSJ-A01", "tier": "FIX", "action": "request", "sentence": "S7",
                "start": 412, "end": 451, "fix": null}],
  "requests": [{"id": "R1", "sentence": "S7", "rules": ["SSJ-A01"], "tier": "FIX", "allowSplit": false,
                "guides": ["왜냐하면으로 시작한 문장은 '~기 때문이다'류 이유 표현으로 맺는다"]}],
  "deterministic": [{"finding": "F9", "sentence": "S12", "start": 640, "end": 642, "before": "됬", "after": "됐"}],
  "profile": {"dominant": "HAPSYO", "share": 0.82, "mixed": true, "line": "합쇼 82%, 해요 CTA·질문 섞임"},
  "seam": {"prev": [0, 0], "next": [0, 0]},
  "openReview": {"enabled": false, "maxSentences": 0},
  "needsModel": true,
  "stats": {"findingsByTier": {"FIX": 2, "SUGGEST": 1, "LEAVE": 6}}
}
```

**Check report** (`check-<chunk>-<attempt>.json`, schema `sejong-check/1`). The first five keys are the legacy gate JSON, unchanged [T1 §2 Gate]:

```json
{
  "gate": {"exit_code": 0},
  "hardFailures": [],
  "warningReasons": {"version": 1, "codes": []},
  "policy": "accept",
  "shadowFailures": ["clarity_longer_sentence"],
  "schema": "sejong-check/1",
  "attempt": 1,
  "sentences": [{"id": "S7", "request": "R1", "status": "accepted", "codes": [], "repairs": ["voice_graft"]}],
  "retry": [{"id": "R2", "sentence": "S9",
             "violations": [{"code": "voice_level", "detail": "HAPSYO->HAEYO", "keep": "없습니다"}]}],
  "requestStatus": {"FIXED": 1, "UNTOUCHED": 0, "STILL_PRESENT": 0, "LOST": 0, "DECLINED": 1},
  "counts": {"revertedSentences": 1, "revertedByFamily": {"voice": 1}, "collateralReverts": 0,
             "voiceGrafts": 1, "cmcRestored": 0, "normFixes": 1, "repairedParticles": 0,
             "removedCommas": 0, "restoredSentences": 0},
  "changeRate": 0.031
}
```

`warningReasons.codes` stays within the legacy closed list (`P0_CHANGE_RATE` … `UNKNOWN`) so the existing parser keeps working; v2 emits at most `P0_CHANGE_RATE`; `P1_STYLE_TARGET` is never emitted [CODE candidate-review.ts REASONS].

**Manifest**: version 1 unchanged, plus an optional block; `parseManifest` checks only the fields it knows and ignores unknown root keys [CODE python-engine.ts], and the skill gateway reads fields by name:
`"sejong": {"version": 1, "genre": "blog", "seams": [{"chunk": 2, "prev": [s, e], "next": [s, e]}]}`.

---

## 4. Replacement map

### 4.1 Vendor components

| Vendor component | Runtime caller today | v2 replacement or drop | Contract kept / changed |
|---|---|---|---|
| `ENGINE_VERSION` (2.3.2, commit 9747f03…) | `create-runtime.ts:30`, `preflight.ts:49-51` (requires 2.3.2), `package-desktop.mjs`, `package-skills.mjs`, `skill_gateway.py:101,136` | `engine_runtime/sejong/ENGINE_VERSION`: `engine=super-sejong` / `version=2.0.0` / `schema=1` | Same "version file + preflight + mid-job check" pattern, renamed deliberately with all readers in one package (WP-14) [T1 §6 Keep 5]. During A/B both files exist; preflight checks the file of the selected engine. |
| `quick-rules.md` (+ header, footer) | `codex-runner.ts`, `claude-runner.ts`, `document-prompt.ts`, `documents/workflow.py:67`, `skill_gateway.py next_chunk`, `skill-bridge.ts context` | **Dropped.** Plan-driven prompt (3.5). | Rules sent only when detected, with spans; none on retry. Footer self-grading ("변경률 10~25% = A", "S1 잔존 0") dropped [T1 §6 Drop 3]. |
| `ai-tell-taxonomy.md`, `diagnosis-rules.md`, `rewriting-playbook.md`, `build_quick_rules.py`, `build_diagnosis_rules.py` | none at runtime [T1 §1.10] | **Dropped** from the runtime tree. | No text reused. |
| `sanitize_text.py` | `prepare_monolith_input.py` | `sejong/text.py: sanitize()` (port) | Byte-identical output, `00_sanitize.json` kept. |
| `prepare_monolith_input.py` | `python-engine.ts prepare`, `skill_gateway.prepare` | `sejong/chunk.py: prepare()`; CLI `sejong_cli.py prepare` | Manifest v1 fields, lossless code-point spans, SHA, footnote passthrough, single ≤ 15,000. Changed: heading rule, paragraph-first seams, `route_hint` null, unused `00_chunk_NN_metrics.json` and `01_chunk_NN_input_with_metrics.txt` no longer written, `--genre essay` ignored (genre comes from options). Exit 0 / 1 unchanged. |
| `restore_modality.py` | `python-engine.ts restore` (step 1), `workflow.restore` | **Dropped as a stage**; meaning-family sentence revert (3.7–3.9). | Report key `restoredSentences` kept (meaning reverts); `skippedSentences` always 0 under v2. |
| `strip_injected_commas.py` | restore step 2 | `sejong/commas.py` (count/position rule) | Key `removedCommas` kept; writer commas never removed [OD 8]. |
| `reassemble_chunks.py` | `python-engine.ts reassemble`, `skill_gateway.finalize` | `sejong/chunk.py: reassemble()`; CLI `sejong_cli.py finalize` | Same output and report files; strict ratio failure → chunk rollback, not job failure. |
| `verify_gates.py` (P0–P5) | `workflow.verify` in-process | `sejong/verify.py` | P0 → runaway guard ≥ 0.50 only; **P1 dropped**; P2 → info `antithesis_lost` (report only); P3 hayeot/cliché → `tell_introduced` (soft); `colloquial_erased` → superseded by the voice gate; P4 → floor `number_dropped` (already hard in the product wrapper); P5 → meaning family. Exit 0–3 semantics kept. |
| `checks.py` | `workflow.verify` | `sejong/floor.py` (port of `check_quotes`, `check_headings`, `check_footnotes`, `extract_quotes`, `_is_protected_quote`, `_number_values`, `dropped_numbers`, `strip_summary_block`) | Failure code names unchanged (section 3.8 floor row). |
| `verify_change_rate.py`, `metrics.py`, `metrics_v2.py`, `baseline.json`, `baseline_v2.json` | none / P1 / route hint | **Dropped.** | Placeholder baselines and z-scores are meaningless [T1 §4, EVAL §5]. |
| `console.py` | vendor scripts | **Dropped.** | Runner already sets `PYTHONUTF8=1` [CODE python-engine.ts run()]. |
| `UPSTREAM.md`, `LICENSE` (MIT, © 2026 epoko77-ai) | — | Removed with `vendor/` (WP-18). | Ported code (sanitize, floor checks) is MIT-derived: keep the MIT notice in `engine_runtime/sejong/THIRD_PARTY.md`. |
| `scripts/sync-engine.ps1`, `scripts/patches/humanize-engine-portal.patch` | Windows sync; local patch | Removed in WP-18. | Every patch behaviour is carried over (4.2). |

### 4.2 Behaviours of the local patch, and where they live in v2

| Patch behaviour [T1 §2 "What the local patch changes"] | v2 home |
|---|---|
| Line endings preserved (`newline=""`) on rewrite | `sejong/io.py read_text/write_text` used by every CLI step |
| `--portal-auto-route`, `processing_mode` | `chunk.prepare` (single ≤ 15,000; `processing_mode` kept) |
| Quote pairing per paragraph | `protect.py` quote spans, `floor.check_quotes` |
| Footnote-definition rules; "GPT-4)" not a footnote marker | `floor.check_footnotes`, `chunk.prepare` passthrough |
| Consecutive numbered list items not headings | `chunk.prepare` heading rule (stricter: numbered lines are never forced cuts) |
| Banded alignment in `restore_modality`; no duplicate/reorder on restore | `align.py` (banded, monotone); reverts copy only the aligned source sentence |
| Noun-list and quote exceptions in the comma stripper | `commas.py` |
| Sanitize recomposes only decomposed Hangul | `text.sanitize` |
| Segmented, linear-time `change_rate` | `verify.change_rate` (sentence-segmented; no whole-text `SequenceMatcher`) |

### 4.3 Product callers

| Caller | v2 change | Package |
|---|---|---|
| `src/engine/humanize-engine.ts` (`HumanizeEngine`) | Kept as the **legacy** engine until WP-18; gains only the optional v2 shadow hook. | WP-17 |
| new `src/engine/sejong/engine.ts` (`SejongEngine`) | Same `transform(request): Promise<HumanizeResult>` contract, same events and diagnostics shape (plus optional fields). | WP-11 |
| `src/engine/python-engine.ts` | Legacy only. v2 uses `src/engine/sejong/python-adapter.ts`. | WP-11 |
| `src/engine/prompt-builder.ts`, `candidate-review.ts`, `direct-text-fidelity.ts`, `text-edits.ts`, `super-sejong.ts` | Legacy only; deleted in WP-18. v2: `sejong/prompt.ts`, `sejong/response.ts`; the TS style rules move to Python (`diagnose.py`). | WP-11, WP-18 |
| `src/engine/rewrite-policy.ts` | `REWRITE_OPTIONS`, `parseRewriteStrength`, `parseRewriteOptions` stay (API). Option descriptions change to the v2 strength meaning (3.4). `rewriteInstructions` is legacy only. | WP-11 |
| `src/engine/codex-runner.ts`, `claude-runner.ts` | Add `runPrompt(prompt, schemaPath, outputPath, signal, settings)`; `quickRulesPath` becomes optional (legacy). | WP-11 |
| `src/engine/document-prompt.ts`, `src/documents/document-engine.ts` | v2 document prompt without quick rules, with per-block requests and voice lines; Office keeps its before/after edit protocol (edits map to formatting runs). | WP-12 |
| `src/engine/diagnostics.ts` | Optional fields (5.2). | WP-11 |
| `src/config.ts`, `src/runtime/create-runtime.ts` | `engineRoot` (= `engine_runtime/sejong`), engine switch, v2 wiring; `vendorRoot` kept until WP-18. | WP-11 |
| `src/process/preflight.ts` | Version check of the selected engine. | WP-14 |
| `engine_runtime/workflow.py` | CLI unchanged; dispatches to `sejong.verify.verify_document` when `SUPER_SEJONG_ENGINE=v2`; legacy body untouched. | WP-10 |
| `engine_runtime/super_sejong.py`, `super_sejong_josa.py` | Become thin re-exports of `sejong.meaning` and `sejong.josa` so legacy imports and tests keep working. | WP-5, WP-8 |
| `engine_runtime/documents/model.py`, `workflow.py` | `apply_edits` calls `sejong.verify.verify_block(source, result)` (reject, never repair); `next_batch` drops `rulesPath`, adds the block plan. | WP-12 |
| `engine_runtime/skill_gateway.py`, `skill_bridge.py`, `scripts/skill-bridge.ts` | In-process `sejong.plan` and `sejong.check`; bridge ops `context-v2` (prompt from plan) and `parse-v2`; empty-plan chunks auto-advance without asking the host; engine id+version recorded in `job.json`. | WP-13 |
| `skills/humanize-kr/SKILL.md`, `references/workflow.md` | Remove `rulesPath`; describe the v2 response format. | WP-13 |
| `scripts/package-desktop.mjs`, `package-skills.mjs`, `verify-skill-packages.mjs`, `benchmark-speed.mjs`, `python-tests.mjs` | Include `engine_runtime/sejong/**`; stop requiring `vendor/` after WP-18. | WP-14 |

### 4.4 Contract details kept

- **Environment** [T1 §2]: `HUMANIZE_AUTO_ROUTE` (v2: only single vs chunked), `CODEX_CHUNK_CONCURRENCY` (1 or 2), `PYTHON_COMMAND`, `SUPER_SEJONG_MODE` (5.4), timeouts 120 s per Python step and 10 min per model call.
- **Restore report keys** (`RestoreReport`): `restoredSentences`, `skippedSentences`, `removedCommas`, `repairedParticles` are filled from the check report `counts` by the v2 adapter, so `TransformDiagnostics` keeps its meaning.
- **Gate JSON**: `gate.exit_code` 0–3 equal to the process exit code, `hardFailures`, `warningReasons{version:1,codes}`, `policy`, optional `shadowFailures` (lowercase codes) — exactly as parsed by `python-engine.ts verify()`.
- **Error codes to the API**: `ENGINE_OUTPUT_INVALID` (prepare/analyse/check/reassemble non-zero or malformed), `ENGINE_TIMEOUT`, `VALIDATION_FAILED` (a chunk check exit 3), `CLIENT_ABORTED`, `ENGINE_FAILED`, `MODEL_UNAVAILABLE` — unchanged.
- **Warning codes** kept with the same meaning: `CHUNK_PREPARE_WARNING`, `MODEL_WARNING`, `MODEL_OUTPUT_UNUSABLE`, `CHUNK_RETRY` (now: a targeted retry call), `CHUNK_ROLLED_BACK`, `CHUNK_WARNING_ACCEPTED`, `DIRECT_TEXT_DOCUMENT_ROLLED_BACK`, `DOCUMENT_REVIEW_RECOMMENDED`, `DOCUMENT_REVIEW` (Office).
- **Warning codes dropped under v2** (no longer produced): `DIRECT_TEXT_PROTECTED_SENTENCES`, `DIRECT_TEXT_PROTECTED_SENTENCES_RESTORED`, `DIRECT_TEXT_FIDELITY_RESTRICTED`, `STRUCTURE_FIDELITY_RESTRICTED` (per-sentence reverts replace them), `DIRECT_TEXT_CANDIDATE_REVIEW_RETRY` (P1 is gone), `MODALITY_RESTORED` (folded into `SEJONG_SENTENCES_REVERTED`).
- **Warning codes added**: `SEJONG_NO_EDIT_NEEDED` (plan empty, no model call), `SEJONG_SENTENCES_REVERTED` (count by family, no text). The UI shows warning messages and does not branch on codes [CODE grep of `src/`, `public/`].
- **Diagnostics** keep every existing field; no text, codes and counts only [EVAL §1 Observability].

### 4.5 Tests that pin behaviour and must change

| Test | What it pins | v2 action |
|---|---|---|
| `tests/unit/vendor-engine.test.ts` | exact ENGINE_VERSION text + existence of all 21 vendor files | Kept until WP-18, then replaced by `tests/unit/sejong-engine-files.test.ts` (pins `engine_runtime/sejong/ENGINE_VERSION` and the runtime file list). |
| `tests/unit/preflight.test.ts` | engine 2.3.2 required | Extended: selected engine's version; v2 requires `super-sejong` ≥ 2.0.0. |
| `tests/unit/python-engine.test.ts` | restore order, stderr keys, manifest mapping | Unchanged for legacy; new `tests/unit/sejong-python-adapter.test.ts`. |
| `tests/skills/test_gate_reasons.py` | P1 fixture `direct-live-quality.json`, 29/30/49/50% boundaries | Legacy unchanged; v2 test: no P1 ever, `change_rate_runaway` at ≥ 0.50, nothing at 0.30. |
| `tests/unit/prompt-builder.test.ts`, `rewrite-policy.test.ts` ("very strong prompt asks for broad sentence restructuring"), `candidate-review.test.ts` | legacy prompt and P1 review | Legacy only; v2 prompt tests in `tests/unit/sejong-prompt.test.ts`. The very-strong expectation changes intentionally (3.4). |
| `tests/unit/super-sejong.test.ts` | 15 TS style rules | Rule fixtures ported to Python (`test_sejong_diagnose.py`); intended changes: ROLE_FORMULA narrowed to adjective+역할, BOILERPLATE quoted-commitment guard, blog gating of IMPORTANCE/BOILERPLATE, ENDING_MONOTONY/INTENSIFIER/CAPABILITY_HEDGE → LEAVE. |
| `tests/skills/test_super_sejong_guards.py` (555 pairs, rate ceilings) | meaning guards | Must pass **unchanged** against `sejong.meaning` (through the shim). |
| `tests/skills/test_super_sejong_josa.py` | josa | Unchanged. |
| `tests/unit/direct-text-fidelity.test.ts` | blanket protection | Legacy only; deleted in WP-18 with the module. |
| `tests/integration/pipeline-fidelity.test.ts`, `humanize-engine.test.ts`, `rewrite-strength.test.ts`, `api-transform.test.ts`, `portal-route.test.ts`, `python-engine.test.ts` (integration) | end-to-end behaviour incl. P1-driven retries and full-gate `VALIDATION_FAILED` | Parameterised by engine. Intended v2 differences: no retry on unchanged text; empty plan → 0 calls; document-level floor failure → source + `DIRECT_TEXT_DOCUMENT_ROLLED_BACK` instead of `VALIDATION_FAILED`. |
| `tests/documents/test_documents.py`, `test_document_edge_cases.py` | Office MODAL/SHORT_NEGATION ordered checks, josa reject | MODAL/SHORT_NEGATION lists replaced by `verify_block` under v2 (shadow/off keep the old checks, as v1 did [EVAL §1 Office]). |
| `tests/skills/test_gateway.py`, `test_direct_gateway.py`, `test_preservation_edge_cases.py` | skill path, `rulesPath`, engine version | v2 variants; `rulesPath` removed. |
| `tests/unit/sync-engine.test.ts`, `windows-scripts.test.ts` (sync script) | Windows vendor sync | Deleted in WP-18. |
| `tests/unit/config.test.ts` | `vendorRoot` path | Adds `engineRoot`; `vendorRoot` assertion removed in WP-18. |

---

## 5. Module layout, public functions, data files, configuration

Product-owned engine code lives only in `engine_runtime/` and `src/engine/`. Evaluation tooling lives in `scripts/sejong-bench/` and never imports engine code [T7 §8].

### 5.1 Python: `engine_runtime/sejong/` (standard library only; Python ≥ 3.9 compatible like the T6 prototypes)

| Module | Public API (signatures) | Ported from |
|---|---|---|
| `__init__.py` | `ENGINE_ID = "super-sejong"`, `VERSION: str` (read from `ENGINE_VERSION`) | — |
| `types.py` | dataclasses `Unit(id, start, end, start_u16, end_u16, para, kind, text)`, `Document(text, paragraphs, units)`, `Span(kind, start, end, policy)`, `VoiceSig`, `Finding`, `Request`, `Plan`, `Violation(code, family, severity, sentence, detail)`, `SentenceVerdict`, `CheckReport`; `to_json()` / `from_json()` | — |
| `config.py` | `Flags.from_env(env=os.environ) -> Flags`; `family_mode(flags, family) -> Literal['enforce','shadow','off']` | `super_sejong.mode` |
| `io.py` | `read_text(path) -> str`, `write_text(path, text)` (newline-preserving) | patch |
| `text.py` | `sanitize(text) -> tuple[str, dict]`; `segment(text) -> Document`; `split_sentences(paragraph: str, base: int = 0) -> list[Unit]`; `mask_quotes(text: str) -> str` (linear) | vendor sanitize, T2/T5/T6 splitters |
| `protect.py` | `protected_spans(doc: Document, *, fix_colloquial: bool) -> list[Span]`; `freeze_intact(src_unit, out_text, spans) -> bool`; `keep_tokens(text) -> Counter` | T2 `cmc_tokens`, workflow `_NAME_TOKEN`, quantities |
| `align.py` | `align(src: list[Unit], out: list[Unit], *, band: Optional[int] = None) -> list[Pair]`; `align_documents(src: Document, out: Document) -> list[Pair]`; `Pair(src: tuple[int, ...], out: tuple[int, ...], score: float)` | T2 `align`, vendor `modality.align`, T7 `align` |
| `chunk.py` | `prepare(run_dir: Path, *, max_single: int = 15000, target: int = 7000, cap: int = 9000) -> dict` (writes manifest v1); `reassemble(run_dir: Path, output: str, report: str) -> dict` | vendor prepare/reassemble + T5 seam design |
| `voice.py` | `signature(sentence: str, kind: str = "body") -> VoiceSig`; `profile(doc) -> dict`; `sheet_line(unit, sig) -> str` | T2 `voice.py` (regex backend) |
| `voice_gate.py` | `check(src: Document, out: Document, pairs: list[Pair], *, fix_colloquial: bool = False) -> list[Violation]` | T2 `gate.py` |
| `voice_repair.py` | `repair_pair(src_unit, out_text, violations) -> tuple[str, list[str]]` (graft, emoticon restore, or revert marker) | T2 `repair.py` |
| `meaning.py` | `ledger(text) -> list[str]`; `compare(src_text, out_text) -> list[Violation]` (polarity, modality, lexical polarity, roles, aspect, partial negation); legacy wrappers `changed_polarity(...)` etc. | `super_sejong.py` |
| `floor.py` | `check(source, output, *, document=None) -> list[Violation]`; `check_pair(src_text, out_text, spans) -> list[Violation]` | `checks.py`, `workflow.verify` wrapper checks, `quantities.py` |
| `cta.py` | `detect(doc) -> tuple[list[CtaUnit], list[Unit]]`; `wording_findings(doc) -> list[Finding]`; `safe_repair(text, *, fix_colloquial: bool) -> tuple[str, list[str]]` (SP1, SP2; LGGE only if opt-in; **no SILGE**) | T6 `cta_detect_final.py` |
| `cta_gate.py` | `compare(src: Document, out: Document, pairs: list[Pair]) -> dict[str, list[Violation]]` (`hard`, `soft`, `info`) | T6 `cta_gate_final.py` (its own matcher replaced by `align`) |
| `flow.py` | `check(src: Document, out: Document, pairs, *, seam: Optional[dict] = None) -> list[Violation]`; `seam_check(document_src, document_out, manifest) -> list[Violation]` | T5 `flow_gate.py`, `flowlib.py` |
| `clarity.py` | `check(src: Document, out: Document, pairs) -> list[Violation]`; `long_review(unit, genre) -> bool`; `approx2(text) -> list[Finding]` | T4 `detect.py` (selected checks) |
| `diagnose.py` | `RULES: dict[str, Rule]` with `Rule(id, tier, action, genres, detect, guide_id, success)`; `diagnose(doc, *, genre, strength, fix_colloquial) -> list[Finding]` | T3 `detectors.py` kept rules, v1 TS style rules, T4, T6 wording |
| `norms.py` | `apply_fixes(text, findings, spans) -> tuple[str, list[str]]`; `introduced(src_text, out_text) -> list[Violation]` | T3, T9 D2 |
| `josa.py` | v1 API unchanged: `check`, `gate`, `repair` | `super_sejong_josa.py` |
| `commas.py` | `strip_injected(src_text: str, out_text: str) -> tuple[str, int]` | vendor stripper + T1 fix |
| `plan.py` | `build_plan(chunk_text: str, *, options: Options, chunk: ChunkInfo, context: Optional[str] = None) -> Plan` | T3 `span_verify.build_requests` |
| `apply.py` | `apply_response(plan: Plan, source: str, response: dict) -> ApplyResult(candidate, replaced, rejected, collateral)` | — |
| `repair.py` | `repair_candidate(plan, source, candidate, pairs) -> tuple[str, dict]` (order of 3.7) | — |
| `verify.py` | `verify_sentences(plan, source, candidate) -> list[SentenceVerdict]`; `verify_document(before: Path, after: Path, *, context: Optional[Path] = None, attempt: int = 1) -> dict` (legacy gate JSON); `verify_block(source: str, result: str) -> list[Violation]` (Office); `change_rate(a, b) -> float` | T3 `span_verify.verify`, `workflow.verify` |
| `decide.py` | `decide(plan, source, candidate, verdicts, *, attempt: int, base: str) -> Decision(candidate, retry, gate)` | — |
| `check.py` | `check(plan: Plan, source: str, *, response: Optional[dict] = None, candidate: Optional[str] = None, attempt: int = 1, base: Optional[str] = None) -> CheckReport` | — |
| `worker.py` (optional) | JSON-lines server; each request is `{"op": …, "id": …, …}` with op = analyse, check, kiwi or nli | T11 `kiwi_worker.py` |
| `nlp_kiwi.py`, `nli.py` (optional) | `KiwiBackend.signature(sentence)`, `copula(sentence)`; `NliBackend.mutual(a, b) -> float` (shadow only) | T2 Kiwi backend, T11 |
| `data/*.json` | see 5.3 | — |

CLI: `engine_runtime/sejong_cli.py` (a 20-line entry point that imports the package; it lives next to `workflow.py` so the existing path conventions hold):

```
sejong_cli.py prepare  --run-dir D [--analyse --input-kind K --strength S --genre G]   # manifest + plan-<i>.json per body chunk
sejong_cli.py analyse  --source chunk.txt [--context 01_input.txt] --chunk-index i --chunk-total n
                       --input-kind K --strength S --genre G --out plan.json
sejong_cli.py check    --plan plan.json --source chunk.txt (--response r.json | --candidate c.txt)
                       --attempt 1|2 [--base decided-1.txt] --out decided.txt --report check.json
sejong_cli.py verify   --before B --after A [--context C] [--attempt 1|2]        # legacy gate JSON on stdout
sejong_cli.py finalize --run-dir D --output 03_reassembled.md --report 03_reassembly_report.json  # reassemble + document verify + seam reverts
```

Exit codes: `prepare`/`analyse`/`finalize` 0 or 1; `check`/`verify` 0–3 equal to `gate.exit_code`.

### 5.2 TypeScript: `src/engine/sejong/`

| File | Exports |
|---|---|
| `types.ts` | `interface Plan`, `PlanRequest`, `PlanSentence`, `CheckReport`, `SejongResponse` (mirrors 3.12) |
| `config.ts` | `selectEngine(env = process.env): 'legacy' \| 'v2'`; `sejongFlags(env): SejongFlags` |
| `version.ts` | `readEngineVersion(engineRoot: string): Promise<{ id: 'super-sejong'; version: string; schema: number }>` |
| `python-adapter.ts` | `class SejongPython { prepare(runDir, signal, opts): Promise<ChunkManifest>; analyse(args, signal): Promise<Plan>; check(args, signal): Promise<CheckReport>; verifyDocument(before, after, signal, attempt?): Promise<GateResult>; finalize(runDir, signal): Promise<string> }` |
| `prompt.ts` | `buildSejongPrompt(input: { plan: Plan; source: string; nonce: string; attempt: 1 \| 2; retry?: CheckReport['retry'] }): string` |
| `response.ts` | `parseSejongResponse(raw: string, plan: Plan): SejongResponse` (throws `EngineError('ENGINE_OUTPUT_INVALID')`) |
| `response-schema.json` | schema of 3.5 |
| `engine.ts` | `class SejongEngine { constructor(options: { python: SejongPython; writer: SejongWriter; chunkConcurrency: 1 \| 2; model?: string; reasoningEffort?: string; now?: () => number }); transform(request: HumanizeRequest): Promise<HumanizeResult> }`; `interface SejongWriter { runPrompt(prompt: string, schemaPath: string, outputPath: string, signal: AbortSignal, settings?: ModelSettings): Promise<string> }` |
| `document-prompt.ts` | `buildSejongDocumentPrompt(input): string` (Office) |
| `worker-client.ts` (optional) | `class SejongWorker { start(); request<T>(op, payload, timeoutMs): Promise<T>; stop() }` — fail-open to the spawn path, never to "unchecked" [T11 §7] |

`TransformDiagnostics` gains optional fields: `engine: 'legacy' | 'v2'`, `chunksWithoutModelCall`, `planRequests: Record<'FIX' | 'SUGGEST' | 'REVIEW', number>`, `requestStatus: Record<string, number>`, `revertedSentences: Record<string, number>` (by family), `collateralReverts`, `voiceGrafts`, `cmcRestored`, `normFixes`, `sentenceRetries`, `v2ShadowCounts?: Record<string, number>` (legacy shadow mode only). Codes and counts only.

### 5.3 Data files and licences

| File | Content | Provenance / licence |
|---|---|---|
| `data/misspellings.json` | `[{wrong, right, class: "error" \| "colloquial", norm: "맞춤법 제N항" \| "NIKL Q&A <id>", exclusions[]}]` | Hand-written closed list; norm articles cited as references, no dictionary text copied (dictionary-derived lists would carry CC BY-SA 2.0 KR and share-alike [T9 §3]). Native-editor review before enabling new entries [T9 D1]. |
| `data/redundancy.json` | 겹말 pairs (T3 kept list; 해변가 removed, 부상당하다 contested) | Author-written; part of the 82-entry research lexicon, some entries rely on author knowledge and need native review [EVAL §5]. |
| `data/double_passive.json` | closed list + exclusions | Author-written from NIKL Q&A 310695/317346 [T3, T8 #10]. |
| `data/voice_lexicon.json` | persona, humble, addressee, discourse markers, CMC patterns, stance families, 하오/하게 stems | Port of T2 constants. |
| `data/cta_lexicon.json` | closed-class actions, channel patterns, force cues, exclusions | Port of T6 constants. |
| `data/connectives.json` | relation classes (additive, causal, summary, contrast), formal subset | Port of T5 `flowlib`. |
| `data/guides.ko.json` | one Korean guide line per rule; no authority claims for SUGGEST | Author-written. |

Not in the repository: NIKL 모두의 말뭉치 text (no redistribution; publishing results needs NIKL approval; commercial evaluation unconfirmed [T9 §4]), 표준국어대사전/우리말샘 text, the 다듬은 말 DB [T9 D7], the owner's posts or drafts, any model output [T7 §8]. The seed benchmark is original text with CC0-1.0 proposed, owner to assign [T7 §6]; it may stay in `docs/research/super-sejong/v2/benchmark/` and a subset may be copied to `tests/fixtures/sejong/`. Constructed pair sets (`T2_pairs*.json`, `T6_pairs_*.json`, the 555 meaning pairs) are project-authored and may live in `tests/skills/data/`. Kiwi (`kiwipiepy==0.24.0`, Apache-2.0) is not bundled by default; the optional worker installs it binary-only with `--require-hashes` and ships its NOTICE [T12 B11]. No NLI weights are shipped [T11 §3].

### 5.4 Configuration

| Variable | Values (default first) | Meaning |
|---|---|---|
| `SUPER_SEJONG_ENGINE` | `legacy` → `v2` at cutover | Which engine produces the delivered text (A/B switch). Read once per job and recorded in diagnostics. |
| `SUPER_SEJONG_MODE` | `enforce`, `shadow`, `off` | Under **legacy**: exactly the v1 semantics (tests pin them). Under **v2**: `enforce` = every family at its default mode (3.8); `shadow` = only floor + meaning enforce, voice/CTA/flow/clarity/norm families are computed and logged in `shadowFailures` without reverting (for measuring real-rewrite false positives on a test deployment, not for the owner's production use); `off` = floor + collateral revert only, SUGGEST requests disabled. The floor is never disabled. |
| `SUPER_SEJONG_GATE_<FAMILY>` | `MEANING`, `VOICE`, `CTA`, `FLOW`, `CLARITY`, `NORMS`, `NLI` = `enforce` / `shadow` / `off` | Per-family override of the MODE default. `NLI=enforce` is rejected (falls back to shadow) until a licence-clean model exists [OD 7]. |
| `SUPER_SEJONG_V2_SHADOW` | `0`, `1` | Under legacy: run v2 `analyse` on the source and v2 `verify` on the legacy output, log codes and counts in `v2ShadowCounts`; delivered text unchanged. |
| `SUPER_SEJONG_FIX_COLLOQUIAL` | `0`, `1` | OD 2 opt-in: 할께 family → FIX; CMC/discourse voice codes → info. |
| `SUPER_SEJONG_DETERMINISTIC_FIX` | `all`, `edited-only`, `off` | `all`: FIX/deterministic rules on every sentence (OD 3). `edited-only`: only inside sentences that received a replacement (T9 D1 tier A stance). `off`: owner opt-out [T3 §6]. |
| `SUPER_SEJONG_OPEN_REVIEW` | `strong`, `always`, `off` | Which strengths get the open review (3.4). |
| `SUPER_SEJONG_GENRE_DEFAULT` | `general`, `blog`, `essay`, `report`, `notice`, `document` | Genre when the request does not carry one. `general` enables only rules valid in every genre. The skill path sends `blog` for the owner's route; Office sends `document`. |
| `SUPER_SEJONG_WORKER` | `off`, `on` | Optional persistent Python worker (JSON lines over stdio). |
| `SUPER_SEJONG_KIWI` | `off`, `worker` | Kiwi features only inside the worker (N05 deterministic, signature cross-check); never per spawn [OD 7]. |
| existing | `HUMANIZE_AUTO_ROUTE`, `CODEX_CHUNK_CONCURRENCY`, `PYTHON_COMMAND` | Unchanged. |

---

## 6. Performance budgets

Targets are [R]; anchors are measured in the cited tracks. Budgets are per stage on the product Python, regex backend, no worker.

| Stage | 3k chars (owner draft) | 15k (single-chunk max) | 100k (service max) | Anchor |
|---|---|---|---|---|
| Python start + `import sejong` | ≤ 150 ms | — | — | bare interpreter 0.009 s [T11 §1.2] |
| sanitize + segment + protect | ≤ 10 ms | ≤ 50 ms | ≤ 300 ms | — |
| analyse (all detectors + plan) | ≤ 60 ms | ≤ 300 ms | ≤ 2 s total | v1 TS rules ≤ 37 ms at 50k [EVAL §3]; T6 detect ≈ 2 s on 38.9k news sentences [T6 §4] |
| check (apply + repair + verify + decide) | ≤ 150 ms | ≤ 600 ms | ≤ 600 ms per chunk | T2 gate 0.15 s at 3k unbanded, 11 s at 30k before banding [T2 §2]; T6 gate worst 0.52 s adversarial [T6 §0.7] |
| finalize (reassemble + document verify) | ≤ 300 ms | ≤ 1 s | ≤ 5 s | legacy 85k: 5.3 s after the change-rate fix [EVAL §1] |
| any adversarial 100k shape (unclosed quote, one 100k sentence, 8,000 CTA lines, repeated tokens) | — | — | ≤ 2 s per stage | v1 quote regex 0.87–4.7 s before its fix [EVAL §1] |
| RSS without Kiwi | ≤ 200 MB | | | Kiwi alone 582 MB per process [T11] |

Rules that make the budgets reachable:
- **Alignment is paragraph-first and banded** (band `2·|n−m| + 8`), O((n+m)·w); similarity by precomputed bigram sets. In the replacement protocol most pairs are known by id.
- **No whole-text `difflib.SequenceMatcher`.** Allowed only on one sentence pair, capped at 2,000 chars per side; longer → treated as changed. `change_rate` is sentence-segmented and linear.
- Regexes are reviewed for catastrophic backtracking; quote masking is a single scan; run-ons are analysed on their last 400 chars as in T6.
- Per-paragraph loops (flow sentence-order check, CTA window search) are bounded by paragraph size and capped at 200 sentences per paragraph.
- CI perf test: each stage on 10k and 100k synthetic and adversarial inputs; the 100k/10k time ratio must be ≤ 15.
- **Spawns per single-chunk job**: legacy 1 prepare + per attempt (3 restore + 1 verify) + reassemble + full verify = 7 without retry, 11 with [CODE python-engine.ts, humanize-engine.ts]. v2: `prepare --analyse` (1) + `check` per attempt (1–2) + `finalize` (1) = 3–4.
- **Model calls**: 0 when the plan is empty; at most 1 + 1 targeted retry per chunk. Legacy: 2 calls for 0 edits in 8/10 drafts [T7 §0.3]. Prompt size: legacy sends 8,489 chars of rules every call [T1 §1.10]; v2 sends ≤ 2,500 chars of contract plus about 150 chars per request plus the chunk.
- **Optional worker**: Kiwi startup 0.84 s once, then about 57 ms per 2×2.6k chars, RSS about 510 MB; NLI int8 +270 MB and 10–30 ms per changed pair [T11 §1.2, §3]. Idle timeout 10 min, restart on crash, per-request timeout; on any worker failure the spawn path runs the same regex code.

---

## 7. Evaluation and rollout

### 7.1 Protocol (T7), applied to v2

- **Arms**: A0 = legacy (commit c792440 for the pre-Super-Sejong engine, or `SUPER_SEJONG_ENGINE=legacy` on the v2 commit); A1 = 4b6a7a9 (optional subset); A2 = v2. Each arm runs from its own `git archive` copy, never from the main tree, never via `npm run test:e2e`, never against port 7882 [T7 §8].
- **Routes**: primary direct-text / medium (the owner's real path); secondary text-file / normal. Every job logs route, `SUPER_SEJONG_ENGINE`, `SUPER_SEJONG_MODE`, model, effort, arm sha, prompt/schema hashes, input/output sha256 [T7 §8].
- **Outcomes never come from an arm's own gate** (circularity, T7 §3.1): gold from reversible corruption, the frozen independent scorer (`scripts/sejong-bench/score.py`, a port of `T7_score.py` + `T7_voicefeat.py` that imports no engine code), blinded judges of another model family, and a human-rated subset.

| Tier | What | Needs | Gate for |
|---|---|---|---|
| A — offline | Pair sets (555 meaning, T2 64+64 and CMC 8+12, T6 A/B/C 221, T7 72 probes, T5-style mutations on constructed text), `verify(x, x)` property, deterministic stage on the seed set, perf budgets | nothing | merging each WP |
| B — stub writer | `SejongWriter` stub returning identity, gold-derived replacements, damaged replacements (ending flattening, -시- drop, CTA weakening, invented CTA, added transition, number change, collateral edit) on the 206 seed items + 6 composites | WP-10, WP-11 | shadow start |
| C — live writer, paired | Same item, both arms, one job at a time, order alternating by item hash; R=2 on a random subset | owner-run CLI | cutover |
| D — judges and humans | Pairwise blinded judges (both orders, two judges, κ ≥ 0.6 and swap consistency ≥ 80% else exploratory), human audit of a stratified subset, owner accept/reject per edit | Tier C outputs | superiority claims |

### 7.2 Data

- **Seed benchmark** (`v2/benchmark/seed_benchmark.jsonl`, 206 items; `seed_composites.jsonl`, 6 documents, one of 17,883 chars to force chunking; schema `seed_schema.json`): 142 injections, 92 primary; 91 items are correctly no-edit; 35 CTA-bearing items; 12 voice traps [T7 §6]. It is a dev/pilot set, not confirmatory. Under OD 3 the `SPELL` injections of the 되요/됬/몇일/금새 type count as errors to fix; under OD 4 the 7 voice-conflicting HONOR fixes (사물 존칭 -시- removal, 하실게요→해 주세요) become **must-leave** items, scored as harm if changed.
- **Owner's Hermes drafts**: `/Users/wisdom/.hermes/work/blog-new10-20261003/articles/*/body-original.txt` (10 drafts, 640 sentences, 31,204 chars [T7 §2]). Read-only, read into memory by the harness; only hashes, offsets and aggregates are written, to `$BENCH/private/` outside the repository [T7 §8]. Spiked variants (allomorph flips, 되어지다, spacing, 겹말, 함에 있어서; gold = the original sentence) are generated in memory and never persisted [T7 §3.5]. Archive future drafts the same way to reach the planned 40.
- **NIKL data** (instruction corpus 216, 2025 blog subset 255, 유사 문장 12, 기초 자료 211/267) only after a written approval that covers evaluation of a commercial product; kept outside git; results published only with NIKL approval [T9 §4, §10].

### 7.3 Metrics specific to v2

- Plan size and `needsModel` rate per genre; calls per job; retries; reverted sentences by family; collateral reverts; request status (FIXED / DECLINED / STILL_PRESENT).
- Spiked drafts: repair rate overall and split by the old engine's protected-sentence flag (the old engine's ceiling there is near zero by design [T7 §3.5]); collateral edits in the ~600 unspiked sentences (expected 0 by construction).
- Natural drafts: improving and harmful edits per 100 sentences, edit precision; harm bound with zero observed harm: 1.15 / 0.58 / 0.29 per 100 sentences at 10 / 20 / 40 drafts [T7 §3.5].
- Idempotence: a second v2 pass on v2 output and on already-processed posts; target ≤ 1 changed sentence per document and 0 voice violations.

### 7.4 Rollout stages and cutover criteria

| Stage | Entry | What runs | Exit criteria (all required) |
|---|---|---|---|
| S0 Build | WPs merged in the worktree | Tier A in CI | All Tier A pins pass (WP acceptance lists, section 8); `verify(x, x) == ∅` on every repo fixture and every seed item; perf budgets met. |
| S1 Offline corpus | S0 | Tier A on research corpora in the scratch area (KatFish, news, owner blog 28 posts, 10 drafts; in memory) | `verify(x, x)` clean on 100% of documents (legacy: 75–99.5% warn [T1]); v2 analyse on the 28 posts and 10 drafts: 0 FIX findings outside OD 3/OD 2 classes, and the plan-size distribution reported. |
| S2 Stub writer | S1 | Tier B | Gold-derived replacements: all 92 primary injections FIXED, 0 voice/CTA/meaning violations, 46/46 CTAs present (scorer self-test baseline [T7 §7]); every damage class reverted or retried; 0 collateral edits delivered. |
| S3 Production shadow | S2 | `SUPER_SEJONG_ENGINE=legacy`, `SUPER_SEJONG_V2_SHADOW=1` for ≥ 2 weeks or ≥ 100 jobs | Logs (codes and counts): v2 would-call rate, plan sizes by rule, v2 hard codes on legacy outputs (a measure of legacy drift), v2 timings within budget; no crash or timeout attributable to v2. |
| S4 Live pilot (Tier C) | S3 | Seed set (≈ 3.7 h writer time [T7 §5]) + 10 drafts natural + 10 drafts spiked, both arms, primary route | v2 calls per draft ≤ legacy (legacy: 2 calls in 8/10 drafts [T7 §0.3], ≈ 1.8 per draft if the other two used one call each); spiked repair rate ≥ 0.55 (T7's re-planned target for this route, n = 24 [T7 §5]) vs legacy; 0 voice and 0 CTA violations in delivered text by the independent scorer; harmful edits 0 on the 10 natural drafts; idempotence target met. |
| S5 Owner opt-in | S4 | `SUPER_SEJONG_ENGINE=v2` on the owner's skill route; legacy one switch away | Owner blind A/B on ≥ 20 drafts; no harmful edit found (bound 0.58 per 100 sentences at 20 drafts [T7 §3.5]); owner approval. |
| S6 Cutover | S5 | default `v2`; legacy kept ≥ 2 weeks / one release | No rollback to legacy needed in that window; diagnostics show no `CHUNK_ROLLED_BACK` spike. |
| S7 Vendor removal | S6 + owner approval | WP-18 | `vendor/` deleted; all tests green; packaging verified on Windows and macOS. |

Claims that v2 is *better* than the old engine on quality need the full T7 protocol (820 synthetic items, 40 natural + 40 spiked + 40 round-2 drafts, safety co-primaries S1–S5 with margins 3 pp meaning/voice and 5 pp CTA/controls, λ = 5 net benefit — margins and λ to be confirmed by the owner [T7 §4–5]). Cutover only needs "not worse and cheaper" on the owner's route plus the safety pins above.

**Deployment caution** [EVAL §7]: the Python stages run from the working tree, so a merged edit to `engine_runtime/*.py` changes live gate behaviour immediately, while TypeScript changes need a rebuild and restart. Therefore: (a) all v2 code lives under new paths (`engine_runtime/sejong/`, `src/engine/sejong/`) and is inert while `SUPER_SEJONG_ENGINE=legacy`; (b) edits to existing files (`workflow.py`, `super_sejong*.py`, `documents/model.py`, `skill_gateway.py`) keep the legacy branch byte-equivalent in behaviour and are covered by the existing tests; (c) development happens in the worktree, never in the main tree.

---

## 8. Implementation plan (work packages)

Each package lists owned files (no two packages own the same file), inputs, outputs, dependencies, tests and acceptance criteria. Python tests live in `tests/skills/`, TS tests in `tests/unit/` and `tests/integration/`.

### 8.1 Waves

```
Wave 0 (serial)    WP-0 contracts
Wave 1 (parallel)  WP-1 text/protect · WP-2 align · WP-14 version/preflight/packaging · WP-15a scorer
Wave 2 (parallel)  WP-3 chunk · WP-4 voice · WP-5 meaning+floor · WP-6 CTA · WP-7 flow+clarity
                   WP-8 diagnose+norms · WP-9 commas · WP-11a TS prompt/response/adapter (against fixtures)
Wave 3             WP-10 core glue + CLI  ──►  then in parallel: WP-11b SejongEngine integration ·
                   WP-12 Office · WP-13 skill path · WP-16 worker (optional) · WP-17 legacy shadow hook
Wave 4             WP-15b harness Tier B/C · rollout S1–S6 · WP-18 vendor removal
```

### 8.2 Packages

**WP-0 Contracts and scaffolding** (small; first).
- Owns: `engine_runtime/sejong/__init__.py`, `types.py`, `config.py`, `io.py`, `ENGINE_VERSION`, `schemas/{plan,check,response}.schema.json`, `src/engine/sejong/types.ts`, `config.ts`, `response-schema.json`, `tests/fixtures/sejong/{plan,check,response}-*.json`, `tests/skills/test_sejong_contracts.py`, `tests/unit/sejong-contracts.test.ts`.
- In: sections 3.12, 5.4. Out: types and schemas every other WP codes against.
- Tests: fixtures validate in both languages; `Flags.from_env` / `sejongFlags` truth tables (incl. `NLI=enforce` → shadow); lowercase code regex.
- Accept: both test files green; no runtime wiring changed.

**WP-1 Text, segmentation, protection.**
- Owns: `sejong/text.py`, `sejong/protect.py`, `tests/skills/test_sejong_text.py`.
- In: vendor `sanitize_text.py`, `super_sejong.sentences`, `T2_voice.split_sentences`, `T6_cta_detect_final.split_units/mask_quotes`, `T5_flowlib`. Out: `Document`/`Unit`/`Span`.
- Tests: sanitize byte-parity with the vendor on all repo fixtures and seed texts; glued terminator splits ("…한다.논문에서는") and non-splits (3.5, 1.2.3, U.S., URLs, e-mails, line-initial "1."); code-point and UTF-16 offsets with astral characters; spans for each kind in 3.1; `mask_quotes` on a 100k unclosed quote ≤ 50 ms.
- Accept: all tests; no superlinear path (10k vs 100k ratio ≤ 15).

**WP-2 Alignment.**
- Owns: `sejong/align.py`, `tests/skills/test_sejong_align.py`.
- In: `T2_gate.align`, vendor `restore_modality` align, `T7_score.align`. Out: `align`, `align_documents`.
- Tests: identity → all 1:1; split/merge/insert/delete recovered on the T2 pair set; paragraph count mismatch fallback; 100k chars ≤ 0.5 s.
- Accept: pair agreement with the T2 aligner ≥ 99% on the 128 T2 pairs; perf.

**WP-3 Chunking, seams, reassembly.**
- Owns: `sejong/chunk.py`, `tests/skills/test_sejong_chunk.py`.
- In: vendor prepare/reassemble, T5 §5.3. Out: manifest v1 (+ `sejong` block), seam contexts, reassembly report.
- Tests: lossless SHA; ≤ 15,000 → single; "(주)…", "1. …", "가. …" lines never force a cut; an unmarked heading stays with its body; cut moved off a connective/demonstrative start; seam contexts ≤ 600/≤ 300 chars; ratio failure → chunk rollback flag; manifest parsed by the current `parseManifest` (contract test via the TS fixture).
- Accept: on synthetic long documents built from the seed composites, 0 orphaned unmarked headings and connective-start packing seams ≤ 2% (target [R]; legacy 8.1% and 8.8% on T5's generator [T5 §5.3]; re-measure with T5's generator in the scratch area).

**WP-4 Voice lock.**
- Owns: `sejong/voice.py`, `voice_gate.py`, `voice_repair.py`, `data/voice_lexicon.json`, `tests/skills/test_sejong_voice.py`, `tests/skills/data/sejong_voice_pairs.json` (copies of `T2_pairs.json`, `T2_pairs_cmc.json`).
- Deps: WP-1, WP-2. Out: signatures, violations, repair actions, sheet lines.
- Tests: T2 pair sets; OD 4 fixtures (하실게요→해 주세요, 학부모님께서 … 작성하셔야→학부모가 … 작성해야, 궁금하신→궁금한 all flagged); OD 2 fixtures (진짜→정말, ㅋㅋ dropped, 할께→할게 flagged by default, info with opt-in); `check(x, x) == ∅`; 30k chars ≤ 0.3 s.
- Accept: hard false positives 0/64; hard catches ≥ 48/49 hard-expected; hard+soft 64/64; CMC set 0/8 flagged and 12/12 caught [T2 §4]; repair leaves 0 residual violations on the pair set.

**WP-5 Meaning and floor.**
- Owns: `sejong/meaning.py`, `sejong/floor.py`, `engine_runtime/super_sejong.py` (becomes a re-export shim), `tests/skills/test_sejong_meaning.py`, `tests/skills/data/sejong_aspect_pairs.json`.
- Deps: WP-1, WP-2. Out: `compare`, `ledger`, floor `check`.
- Tests: the existing `test_super_sejong_guards.py` unchanged and green; new aspect pairs (읽고 있다→읽는다 flagged; 읽고 있다→읽는 중이다 accepted) and partial-negation pairs; `_order_swapped` regression (identical sentence with two 전에/후에 frames → no flag) [T1 §1.9]; floor code names identical to `checks.py`.
- Accept: the 555-pair rates do not regress; T7's 72 probes reported (not gated); `compare(x, x) == ∅` on fixtures.

**WP-6 CTA ledger and gate.**
- Owns: `sejong/cta.py`, `sejong/cta_gate.py`, `data/cta_lexicon.json`, `tests/skills/test_sejong_cta.py`, `tests/skills/data/sejong_cta_pairs.json` (copies of `T6_pairs_A/B/C.json`).
- Deps: WP-1, WP-2.
- Tests: pair sets (tuned, so a regression pin only); `safe_repair` never applies SILGE and applies LGGE only with opt-in; `compare(x, x) == ∅`; adversarial (8,000 CTA lines, 32k repeated `문의해 주시면 `) ≤ 0.6 s; all codes lowercase.
- Accept: 0/108 preserving pairs hard-blocked, ≥ 102/113 violating pairs hard-blocked, ≥ 112/113 flagged [T6 §6].

**WP-7 Flow and clarity guards.**
- Owns: `sejong/flow.py`, `sejong/clarity.py`, `data/connectives.json`, `tests/skills/test_sejong_flow.py`, `tests/skills/data/sejong_flow_cases.json` (constructed text only).
- Deps: WP-1, WP-2.
- Tests: mutations F1a–c, F2a, F3a–b, F5, F8, F9, F12 on constructed passages; benign B0–B3; seam invariants and `flow_context_leak`; clarity guards (longer sentence, bare demonstrative, agentless obligation, acronym gloss, number marker, list structure).
- Accept: every hard mutation class detected on the constructed set; benign false alarms ≤ 1 per 77 benign cases (T5's in-sample rate [T5 §4]); `flow_sentence_added` and clarity codes emitted as shadow by default.

**WP-8 Diagnostics and norm layer.**
- Owns: `sejong/diagnose.py`, `sejong/norms.py`, `sejong/josa.py`, `engine_runtime/super_sejong_josa.py` (re-export shim that keeps the `--before/--after/--out/--json` CLI the legacy restore step runs), `data/misspellings.json`, `data/redundancy.json`, `data/double_passive.json`, `data/guides.ko.json`, `tests/skills/test_sejong_diagnose.py`.
- Deps: WP-1.
- Tests: T3 exclusions (머지않아, 못지않게, 외톨이였던, 실수 없이, 할수록, 해변가, 받지 않되); OD 3 (되요→돼요, 됬→됐, 몇일→며칠, 금새→금세 fixed deterministically); OD 2 (할께 untouched by default); OD 4 property: applying every FIX fix to its fixtures leaves the voice signature unchanged; v1 TS rule cases ported from `super-sejong.test.ts`; blog gating; `introduced()` flags a new 인식율 and nothing on an unchanged source; existing `test_super_sejong_josa.py` green.
- Accept: 0 FIX/SUGGEST findings on the 49 seed natural controls; the T3 precision fixtures pass; `apply_fixes` idempotent.

**WP-9 Comma rule.**
- Owns: `sejong/commas.py`, `tests/skills/test_sejong_commas.py`.
- Deps: WP-2.
- Tests: the T1 probe shape (one-word edit at sentence start) removes 0 writer commas; injected connective commas removed down to the source count; noun-list and quote exceptions; sentence-initial 그리고, only if new.
- Accept: 0 writer commas removed on the probe fixtures (legacy removed 100% in touched sentences [T1 §1.7]).

**WP-10 Core glue and CLI.**
- Owns: `sejong/plan.py`, `apply.py`, `repair.py`, `verify.py`, `decide.py`, `check.py`, `engine_runtime/sejong_cli.py`, `engine_runtime/workflow.py` (v2 dispatch only), `tests/skills/test_sejong_pipeline.py`.
- Deps: WP-0 to WP-9 (can start against stubs after WP-0).
- Tests: deterministic end-to-end on the seed set with three Python stub writers (identity → 0 changes; gold-derived replacements → all primary FIXED, 0 violations; damaged → reverted or retried); `verify_document(x, x)` clean; strength → tier mapping; empty plan → `needsModel=false`; collateral edits reverted in full-text fallback; decision table; gate JSON accepted by the current TS parser (contract fixture); OD 8 regressions (no P1, unchanged text never retried).
- Accept: all tests; perf budgets for analyse/check/finalize; `workflow.py` legacy behaviour unchanged (existing Python tests green).

**WP-11 TypeScript orchestration** (11a in wave 2 against fixtures, 11b after WP-10).
- Owns: `src/engine/sejong/{engine,python-adapter,prompt,response}.ts` (`version.ts` belongs to WP-14), `src/engine/codex-runner.ts`, `src/engine/claude-runner.ts` (add `runPrompt`), `src/engine/diagnostics.ts`, `src/engine/rewrite-policy.ts` (descriptions only), `src/config.ts`, `src/runtime/create-runtime.ts`, `tests/unit/sejong-*.test.ts`, `tests/integration/sejong-*.test.ts`.
- Out: `SejongEngine` selectable by `SUPER_SEJONG_ENGINE`.
- Tests: empty plan → 0 writer calls and `SEJONG_NO_EDIT_NEEDED`; retry prompt contains only failed requests and named violations, no rulebook text; response parser rejects unknown/duplicate ids, newlines, disallowed `rewrittenText`; diagnostics fields; existing unit and integration tests green with the default `legacy`; Tier-B stub run on the composites.
- Accept: legacy outputs byte-identical on the existing integration fixtures; v2 integration tests green.

**WP-12 Office path.**
- Owns: `engine_runtime/documents/model.py`, `engine_runtime/documents/workflow.py`, `src/documents/document-engine.ts`, `src/engine/sejong/document-prompt.ts`, `tests/documents/*` changes.
- Deps: WP-10, WP-11a.
- Tests: per-block plan and prompt; `verify_block` rejects voice/CTA/meaning/josa violations (reject, no repair); legacy and shadow modes keep the ordered MODAL/SHORT_NEGATION checks.
- Accept: `tests/documents` green in both engines.

**WP-13 Agent-skill path.**
- Owns: `engine_runtime/skill_gateway.py`, `engine_runtime/skill_bridge.py`, `scripts/skill-bridge.ts`, `skills/humanize-kr/SKILL.md`, `skills/humanize-kr/references/workflow.md`, `tests/skills/test_gateway.py`, `test_direct_gateway.py`, `test_preservation_edge_cases.py` changes.
- Deps: WP-10, WP-11a.
- Tests: empty-plan chunks auto-advance; v2 host response parsed; engine id+version mid-job change fails the job; finalize at attempt 2; no `rulesPath` in v2 responses.
- Accept: skill tests green in both engines; the in-process path and the server path give identical decisions on the seed composites (closes T1's "server vs skill equivalence" gap).

**WP-14 Version, preflight, packaging.**
- Owns: `src/engine/sejong/version.ts`, `src/process/preflight.ts`, `scripts/package-desktop.mjs`, `scripts/package-skills.mjs`, `scripts/verify-skill-packages.mjs`, `scripts/python-tests.mjs`, `tests/unit/preflight.test.ts`, `tests/unit/sejong-engine-files.test.ts`.
- Deps: WP-0.
- Accept: preflight passes for each engine with its own version file; packaged desktop and skill bundles contain `engine_runtime/sejong/**`; vendor-engine test untouched until WP-18.

**WP-15 Evaluation harness** (15a scorer in wave 1; 15b runner later).
- Owns: `scripts/sejong-bench/**` (scorer, packer, runner, spiker, report), no engine imports.
- Tests: scorer self-test reproduces T7's metamorphic results (identity 0/92 fixed; gold 92/92, 0 collateral, 46/46 CTAs; damage detection table [T7 §7]); harness writes only to `$BENCH` outside the repository; Hermes drafts opened read-only, no body text persisted.
- Accept: Tier B report on the seed set; Tier C runbook for the owner (the harness never runs the CLIs itself in CI).

**WP-16 Optional worker, Kiwi, NLI shadow.**
- Owns: `sejong/worker.py`, `sejong/nlp_kiwi.py`, `sejong/nli.py`, `src/engine/sejong/worker-client.ts`, `engine_runtime/sejong/requirements-worker.txt` (hash-pinned `kiwipiepy==0.24.0`, `kiwipiepy_model==0.24.0`), tests.
- Deps: WP-10. Off by default.
- Accept: worker failure falls back to the spawn path with identical regex decisions; Kiwi analyse ≤ 70 ms per 2×2.6k chars; NLI refuses enforce; no network access at runtime.

**WP-17 Legacy shadow hook.**
- Owns: `src/engine/humanize-engine.ts`.
- Deps: WP-10, WP-11a (adapter).
- Accept: with `SUPER_SEJONG_V2_SHADOW=1`, delivered text byte-identical to legacy; `v2ShadowCounts` populated (codes and counts only); overhead ≤ 300 ms per 3k job.

**WP-18 Vendor removal** (after S6 and owner approval).
- Owns: deletion of `vendor/humanize-engine/`, `scripts/sync-engine.ps1`, `scripts/patches/humanize-engine-portal.patch`, legacy TS modules (`prompt-builder.ts`, `candidate-review.ts`, `direct-text-fidelity.ts`, `text-edits.ts`, `super-sejong.ts`, `python-engine.ts`, `document-prompt.ts`, legacy part of `humanize-engine.ts`), their tests, `vendorRoot` config; default `SUPER_SEJONG_ENGINE=v2` and then removal of the switch.
- Accept: full test suite green; `vendor-engine.test.ts`, `sync-engine.test.ts` removed; packaging verified on Windows and macOS; `THIRD_PARTY.md` carries the MIT notice for ported code.

---

## 9. Risks and open questions

### 9.1 Risks

| Risk | Why it matters | Mitigation |
|---|---|---|
| Gate false-positive rates on **real** LLM rewrites are unknown. | Every voice, CTA, flow and clarity figure comes from constructed pairs or mechanical edits, labelled by one LLM annotator [T2 §8, T5 §10, T6 §10, T4 §8]. | Per-sentence revert makes a false positive cheap (that sentence keeps the writer's wording); S3 shadow logs and Tier C measure the real rates; clarity and `flow_sentence_added` start in shadow. |
| Meaning guards still miss about one change in five (18.3% on the untuned set) and overblock heavy paraphrase (48% on T7 probes). | Silent meaning drift is the worst failure. | Edits are small and request-scoped; the independent audit (not the engine) is the outcome; extend lexical axes from shadow logs; NLI as an optional shadow signal once licence-clean [EVAL §7, T7 §7, T11 §3]. |
| The writer may not follow the replacement protocol. | Unusable replies cost an attempt. | Full-text fallback with collateral revert; `MODEL_OUTPUT_UNUSABLE` counted; Tier C measures the rate per writer (Codex, Claude). |
| "Nothing happened" perception on clean drafts. | Most owner drafts may make 0 calls (3.4 prediction). | `SEJONG_NO_EDIT_NEEDED` message explains it; strong/very-strong add the open review; the owner decides the default for medium (9.2). |
| Strength semantics change. | UI text and one pinned test promise broad restructuring at very-strong [CODE rewrite-policy.ts]. | Intended change, owner to confirm; descriptions updated in WP-11. |
| CTA action synonyms (제출/내다, 준비/챙기다) are soft only. | A real action swap among open-class verbs can pass as soft. | Soft codes still trigger repair → retry → revert; a reviewed synonym lexicon could make part of it hard [T6 §10]. |
| Splitter and heading changes move chunk boundaries vs legacy. | Legacy-vs-v2 diffs on long documents are partly segmentation. | Record manifests per arm; compare on single-chunk documents first (the owner's drafts are single-chunk). |
| Kiwi supply chain (PyPI uploads without attestations). | Optional component only. | Binary-only, hash-pinned install; off by default [T12 B11]. |
| NIKL data terms. | Commercial evaluation and publication need written approval. | No NIKL data in git; apply as an institution; publish nothing without approval [T9 §4]. |
| Live-tree execution of Python stages. | Merged Python edits affect the live service immediately [EVAL §7]. | New paths, legacy default, legacy branches unchanged, worktree development (7.4). |

### 9.2 Open questions for the owner

1. Borderline spellings: which class do 할려면-type pronunciation spellings, 웬지/왠지-type confusions and 바래요 belong to — `error` (fixed, OD 3) or `colloquial` (kept, OD 2)? The design classifies only the 할께 family as colloquial and the OD 3 list as errors; the rest waits for this answer and a native-editor review of `misspellings.json` [T7 §11].
2. Should medium (the owner's route) include the open review, at the cost of one model call per chunk even when nothing is detected? Default here: no.
3. Is 하오체 `-ㅂ시다` compatible with 하십시오체, and is embedded -시- (연락 주시기 바랍니다) part of the lock or soft as now [T2 §8]?
4. Genre source: should the portal expose a genre selector, or is `general` (direct-text default) plus `blog` on the skill route enough?
5. Is the deterministic FIX tier on by default for every sentence (`all`), or only inside sentences that were edited anyway (`edited-only`, T9's stance)?
6. T7 margins (3 pp meaning and voice, 5 pp CTA and controls), harm bound (1.0 per 100 sentences), λ = 5, and whether the owner will accept/reject v2 edits per draft as ground truth [T7 §11].
7. Licence for the seed benchmark (CC0-1.0 proposed) [T7 §6].
8. A written NIKL inquiry about commercial-product evaluation with 모두의 말뭉치 (corpora 216, 255, 12, 211/267) [T9 §10].

### 9.2a Lead decisions (2026-10-04), pending owner confirmation

These defaults follow the owner's binding decisions and are used by the work packages until the owner says otherwise.

1. 할려면 → 하려면, 웬지 → 왠지: `error` (FIX, deterministic after a native review of `misspellings.json`), like 되요/됬/몇일 (OD 3). 바래요 stays SUGGEST because of 빛이 바래요. Only the 할께 family and CMC tokens are `colloquial`.
2. Medium includes the open review (one model call per chunk). Reason: the first live run after the main hotfixes showed the model fixing real awkwardness that no mechanical rule detects.
3. Embedded -시- is part of the hard lock (`voice_hon_si_*` counts every -시-, not only the final predicate). Reason: OD 4 and the live case 궁금하신 → 궁금한. 하오체 -ㅂ시다 is a distinct level.
4. No genre selector yet: `general` for direct text, `blog` on the agent-skill route.
5. Deterministic FIX applies to every sentence (`all`).
6. T7 margins and λ as proposed; the owner's per-edit accept/reject is welcome but not required.
7. Seed benchmark licence: CC0-1.0 proposed (the text is original).
8. The owner has applied to 모두의 말뭉치; ask about commercial-product evaluation in the same exchange.

### 9.3 Open technical questions

- Exact banding constant and the paragraph-pairing rule when the model splits a paragraph inside a replacement (forbidden, but must be detected): resolved in WP-2 by measurement.
- Whether the single retry should be allowed to revisit SUGGEST requests the model declined (current design: no).
- Whether `flow_sentence_added` can enforce after S3, given that splits inside `allowSplit` replacements are legitimate additions.
- Windows cold start and RSS for the optional worker are unmeasured [T11 §8].
- No Korean negation or adversarial NLI benchmark exists; any NLI evaluation must build its own probes [T11 §3].
