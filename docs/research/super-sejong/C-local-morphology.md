# Super Sejong Engine: local Korean morphology candidates

Research note C · 2026-10-03 · measured local probe, **not a product integration or general benchmark**

## Decision question

Could a local Korean morphological analyzer supply dependable sentence boundaries, particle and ending spans, and negation **cues** for a meaning-preserving rewriting engine? I compared the current [Kiwipiepy/Kiwi](https://github.com/bab2min/kiwipiepy) and [python-mecab-ko](https://python-mecab-ko.readthedocs.io/en/stable/) APIs on 14 hand-written, disclosed examples. Both are feasible as local components on this host. The experiment does **not** show that either can determine clause-level negation scope or guarantee correct syntactic roles.

## Candidate inventory and rights

| Candidate | Verified API and packaging | License evidence | Assessment for this project |
| --- | --- | --- | --- |
| Kiwipiepy 0.24.0 + model 0.24.0 | The [author's README](https://github.com/bab2min/kiwipiepy/blob/main/README.md) documents `Kiwi.tokenize`, installable wheels, and Python 3.9+; the available [v0.23.1 API documentation](https://bab2min.github.io/kiwipiepy/v0.23.1/kr/) describes `split_into_sents` with offsets, and the script confirms this call on 0.24.0. [PyPI 0.24.0](https://pypi.org/project/kiwipiepy/0.24.0/) lists macOS arm64, Linux and Windows wheels and Python ≥3.9. The model is an installed dependency. | PyPI marks [wrapper 0.24.0](https://pypi.org/project/kiwipiepy/0.24.0/) and [model 0.24.0](https://pypi.org/project/kiwipiepy-model/0.24.0/) as Apache-2.0. [Kiwi's own README](https://github.com/bab2min/Kiwi) says current engine/model are Apache-2.0 and **0.23.2 or earlier remain LGPL**. | Strong candidate when sentence segmentation and source offsets matter. Pin **0.24.0 or later with a separately verified license**; a lockfile drifting to 0.23.2 changes license obligations. |
| python-mecab-ko 1.3.7 + python-mecab-ko-dic 2.1.1.post2 | [Official usage documentation](https://python-mecab-ko.readthedocs.io/en/stable/) exposes `MeCab.parse()` with surface, POS, and source spans. [PyPI](https://pypi.org/project/python-mecab-ko/1.3.7/) provides a CPython 3.11 macOS arm64 wheel; dictionary is installed with the binding. | PyPI identifies [wrapper 1.3.7](https://pypi.org/project/python-mecab-ko/1.3.7/) as BSD-3-Clause and [dictionary package](https://pypi.org/project/python-mecab-ko-dic/2.1.1.post2/) as Apache-2.0. The wrapper's [license file](https://github.com/jonghwanhyeon/python-mecab-ko/blob/main/LICENSE) sets BSD notice/redistribution conditions. The underlying MeCab-ko/native components should be checked separately when shipping binaries. | Faster in this narrow run and useful as an independent tagger. The interface used here supplies token spans, not a tested sentence splitter. Some conjugations have compound POS labels such as `XSV+EC`. |
| KoNLPy | [Official documentation](https://www.konlpy.org/en/stable/api/konlpy/) wraps several analyzers (including Okt, Komoran, Kkma, and MeCab); its [installation guide](https://konlpy.org/en/latest/install/) describes additional platform dependencies, including Java for some analyzers. | The project's [LICENSE](https://github.com/konlpy/konlpy/blob/master/LICENSE) is GPL-3.0-or-later. Underlying analyzers have their own terms. | Useful comparison ecosystem, but **not installed or benchmarked** in this probe. Packaging and license review would be needed before bundling. |
| soynlp | The [author's README](https://github.com/lovit/soynlp) describes unsupervised word extraction and tokenizers. It explicitly recommends training on a sufficiently large, homogeneous corpus; its regex tokenizer does not morphologically divide an uninterrupted Hangul string. | Its [setup metadata](https://github.com/lovit/soynlp/blob/master/setup.py) declares GPLv3. | A possible domain lexicon discovery tool, not a drop-in substitute for a general sentence/particle analyzer; **not installed or benchmarked**. |

The current Kiwi project homepage describes a newer Apache license, while the actually tried older 0.23.2 wheel exposed LGPLv3 metadata. I briefly installed 0.23.2, then upgraded to 0.24.0 before the reported measurements. Package version and model version must therefore be recorded together. A package's top-level license label also does not automatically resolve the obligations of embedded native code or third-party dictionaries; check the shipped artifact and notices before distribution. [Kiwi release metadata](https://pypi.org/project/kiwipiepy/0.23.2/), [current release metadata](https://pypi.org/project/kiwipiepy/0.24.0/).

## Reproducible probe

Source: [`scripts/C_morphology_probe.py`](scripts/C_morphology_probe.py). It contains all 14 original sample strings, expected sentence spans, and the timing procedure; it prints detailed JSON with source offsets, POS tags, and the sample-set SHA-256. No downloaded corpus or private user text is used. The sample-set hash for this run was `87b2cf1e4ba0bc11fb08e43b4e2a2e8d782859ab8aa92b35407ac4a757eb9fbf`.

Clean rerun on a supported host:

```sh
python3.11 -m venv /tmp/sejong-morph-venv
/tmp/sejong-morph-venv/bin/python -m pip install 'kiwipiepy==0.24.0' 'kiwipiepy-model==0.24.0' 'python-mecab-ko==1.3.7' 'python-mecab-ko-dic==2.1.1.post2'
/tmp/sejong-morph-venv/bin/python docs/research/super-sejong/scripts/C_morphology_probe.py --repeats 100 --trials 5
```

The actual run used `/tmp/super-sejong-morph.4vzxSl/venv` on CPython 3.11.15, macOS 26.6.2, arm64. I first installed `kiwipiepy==0.23.2` with `python-mecab-ko==1.3.7`, then upgraded the Kiwi wrapper and model to `0.24.0`; the run used **only the final versions**. The measured command was:

```sh
/tmp/super-sejong-morph.4vzxSl/venv/bin/python docs/research/super-sejong/scripts/C_morphology_probe.py --repeats 100 --trials 5 > /tmp/super-sejong-morph.4vzxSl/probe.json
```

Timing measures warmed `Kiwi.tokenize` and `MeCab.parse` calls, 100 passes over 14 short strings per trial, with the median of five trials. The constructor, import, install, and any use of a sentence splitter are excluded. The two APIs differ in token representation: Kiwi usually returns separate morphemes and normalized forms; MeCab sometimes returns one surface token with a compound POS tag. The timing includes the Python conversion to a common token record and is therefore a **local workload measurement**, not a pure engine speed comparison. Kiwi ran with one worker; MeCab used its default configuration.

| Probe result | Kiwi 0.24.0 | python-mecab-ko 1.3.7 |
| --- | ---: | ---: |
| Calls per timed trial | 1,400 | 1,400 |
| Input characters per trial | 27,000 | 27,000 |
| Median trial wall time | 0.105272 s | 0.051557 s |
| Median apparent throughput | 256,477 characters/s | 523,687 characters/s |
| Top-level sentence spans matching hand-marked spans | 14/14 with `split_into_sents` | 12/14 with **our punctuation-tag heuristic**, not a built-in MeCab splitter |

The MeCab heuristic split on `SF` punctuation. It failed on the newline-only boundary (`사업은 종료됐다\n다음 단계는 검토 중이다`) and placed the closing quote in the wrong span for `그는 말했다. "안 간다." 나는 남았다.`. Those failures evaluate **the heuristic we wrote**, not MeCab's general sentence segmentation capability. Both methods matched the 12 simpler cases, including a decimal and a question/answer pair. This tiny designed set is not an accuracy estimate for either engine.

## Observed morphology relevant to rewrite safety

| Transparent sample | Observed result | Engine implication |
| --- | --- | --- |
| `그는 신청하지 않았다.` | Both emit `않/VX`; `그는 신청을 안 했다.` yields `안/MAG`; `그는 신청할 수 없었다.` yields `없/VA`. | One surface suffix or POS pattern cannot cover all negative constructions. A layered detector can use these as candidate cues. |
| `그는 신청을 거부했다.` | Neither returned an `안`/`않`/`없` cue. | Lexical refusal/denial needs a lexicon and contextual semantics; morpheme cues alone miss it. |
| `이용하지 않아도 됩니다. 반드시 신청해야 합니다.` | Both detect `않/VX` in the first sentence, while the phrase as a whole expresses permission/not requiring action. | The presence of a negative token does not determine the proposition's polarity, modal force, or scope. Parse clause operators before comparing meanings. |
| `민수는 보고서를 읽었다. 지영이 검토했다.` | Kiwi tagged the final `이` of `지영이` as `XSN` (person-name suffix); MeCab tagged it `JKS` (nominative). Both identified `는/JX` and `를/JKO` earlier. | Do not treat one tagger's `JKS` set as a complete subject detector. Name segmentation and ambiguous `이` affect role analysis. |
| `가격은 3.14만 원이다.` | Kiwi kept `3.14/SN` together; MeCab emitted `3/SN`, `./SY`, `14/SN`. | Preserve numeric spans independently of tokenization. Decimal punctuation is not necessarily a sentence boundary. |
| `그는 '안 간다'고 말했다.` | Both emit `안/MAG` inside the quotation; Kiwi marks quote punctuation separately, MeCab uses `SY`. | Quote/speaker boundaries are necessary before assigning a negative cue to the narrator's assertion. |

`Kiwi` token *forms* may differ from their original source substring, and multiple morphological pieces can share a source character offset (for example, conjugation). MeCab can combine morphological tags in one surface span. A rewrite engine must retain source offsets separately and must not rebuild text by concatenating normalized token forms. These behaviors are visible in the script's JSON output and consistent with the respective [Kiwi API examples](https://bab2min.github.io/kiwipiepy/v0.23.1/kr/) and [MeCab detailed parse API](https://python-mecab-ko.readthedocs.io/en/stable/).

## Recommendation and limits

For a first optional local analysis component, **Kiwi 0.24.0** is the more convenient candidate because it supplies morphology, source offsets, and sentence spans in one documented API with a current Apache-2.0 release. Use MeCab-ko as an independent comparison on difficult names/particles or as an alternative where throughput dominates and another sentence splitter is already present. The observed `지영이` disagreement is a reason to attach confidence and abstain on role-dependent edits, not to declare one analyzer generally superior. Keep candidate analysis separate from the rewrite engine's semantic decision: negation scope, modality, attribution, numbers, and predicate–argument fidelity require their own checks. A production choice still needs larger, genre-diverse annotated data, cross-platform packaging tests, startup/memory measurement, and reviewed transitive licenses. None of those were performed in this note.
