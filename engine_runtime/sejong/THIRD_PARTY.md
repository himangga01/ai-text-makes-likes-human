# Third-party notices for engine_runtime/sejong

Super Sejong Engine v2 is product-owned code. A few of its pieces are ports of the vendored 윤문 엔진
(`vendor/humanize-engine`, label 2.3.2, commit 9747f036cdc28a1a8aea4dc71fef1f7846eb96f7, from
https://github.com/himangga01/im-not-ai_fork, with the portal's local patch
`scripts/patches/humanize-engine-portal.patch`). The vendor code is MIT-licensed; its notice is
reproduced below and must stay with these files after `vendor/` is removed (DESIGN.md 4.1, WP-18).
No vendor module is imported at run time.

## Ported pieces

| v2 file | What was ported | Vendor source |
|---|---|---|
| `text.py` | `sanitize()`: zero-width, BOM, bidi and tag removal, special-space and line-break normalisation, recomposition of decomposed Hangul only (byte-for-byte the same behaviour, pinned by `tests/skills/test_sejong_text.py`) | `scripts/sanitize_text.py` |
| `floor.py` | quotation, heading, footnote and number checks: `check_quotes`, `check_headings`, `check_footnotes`, `extract_quotes`, `_is_protected_quote`, `_number_values`, `dropped_numbers`, `strip_summary_block` (failure code names unchanged) | `scripts/checks.py` |
| `commas.py` | the connective-ending comma regexes, the noun-list exception and the quotation exception of the comma stripper (the removal rule itself is new: count and position against the source sentence) | `scripts/strip_injected_commas.py` |
| `chunk.py` | footnote-block detection (`find_footnote_block_start`), the manifest v1 fields, lossless code-point spans with SHA-256, and the whitespace re-attachment of reassembly | `scripts/prepare_monolith_input.py`, `scripts/reassemble_chunks.py` |

Everything else in this directory (plan, apply, repair, verify, decide, check, the aligner, the voice,
meaning, CTA, flow, clarity and norm families, the diagnostics and their data files) is original to this
project or ported from the project's own research prototypes under `docs/research/super-sejong/v2/`.

## MIT License (vendor)

```
MIT License

Copyright (c) 2026 epoko77-ai

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
