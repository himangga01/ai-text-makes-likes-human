# Vendored Humanize Engine

Source: https://github.com/himangga01/im-not-ai_fork
Version: 2.3.2
Commit: 9747f036cdc28a1a8aea4dc71fef1f7846eb96f7

The runtime is copied so the portal has no sibling-repository dependency.

Portal patch: scripts/patches/humanize-engine-portal.patch

- Preserves user-content LF/CRLF exactly with newline="".
- Adds the opt-in --portal-auto-route manifest path for short light/standard documents.
- Feeds the source text to the v2.6 route tell counter in --chunk mode so short documents are not misrouted to light.
- Keeps LF/CRLF intact in restore_modality.py and strip_injected_commas.py file I/O.
- Pairs quotes per paragraph with matching marks, treats only marker-backed N) blocks at the end or before a heading as footnote definitions (with document-wide markers for chunks), ignores version-like markers such as GPT-4), and treats consecutively numbered list items, but not table-of-contents entries, as non-headings (checks.py).
- Never lets modality restoration duplicate a sentence or restore a reordered pair, while still restoring parallel sentences, and bands sentence alignment for long documents (restore_modality.py).
- Keeps noun-list commas, including lists of nouns ending in -go, and commas inside multi-sentence quotes (strip_injected_commas.py).
- Recomposes only decomposed Hangul instead of NFC-normalizing the whole text (sanitize_text.py).
- Compares long texts line by line in change_rate so the full-document gate stays linear (metrics_v2.py).
