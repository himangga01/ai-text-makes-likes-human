# Vendored Humanize Engine

Source: https://github.com/epoko77-ai/im-not-ai
Version: 2.3.2
Commit: 31a66d165a9cc6c26c4c1246553f95d0468d27fb

The runtime is copied so the portal has no sibling-repository dependency.

Portal patch: scripts/patches/humanize-engine-portal.patch

- Preserves user-content LF/CRLF exactly with newline="".
- Adds the opt-in --portal-auto-route manifest path for short light/standard documents.
- Feeds the source text to the v2.6 route tell counter in --chunk mode so short documents are not misrouted to light.
- Keeps LF/CRLF intact in restore_modality.py and strip_injected_commas.py file I/O.
