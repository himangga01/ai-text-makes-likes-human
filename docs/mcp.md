# MCP Server Guide

The portal ships a Model Context Protocol (MCP) server. An MCP client — Claude Code, Codex, or any agent host with
stdio MCP support — can call the portal as tools instead of going through the web page or the skill Gateway.

- Transport: stdio (JSON-RPC 2.0, one message per line). Protocol versions 2025-11-25, 2025-06-18, 2025-03-26 and
  2024-11-05 are negotiated.
- Every tool call is one portal job. The portal's queue, engines, model policy and preservation checks apply
  unchanged, so a result from MCP is exactly what the web page would deliver.
- No extra dependency: the server is plain Node (`src/mcp/`, built to `dist/mcp/server.js`).
- The portal must be running. It is managed by the Hermes service on this Mac (`http://127.0.0.1:7882`).

## Tools

| Tool | Arguments | Result |
|---|---|---|
| `humanize_text` | `text` (required, ≤100,000 chars), `strength`, `engine`, `model`, `effort` | The verified rewritten text, then a short report: strength, chunks, time and the portal's warnings. |
| `humanize_file` | `path` (required, absolute; `.txt` `.md` `.docx` `.pptx`), `outputPath`, `strength`, `engine`, `model`, `effort` | Writes a new file next to the source (`<name>-humanized.<ext>`, then `-2`, `-3`…) or at `outputPath`, and reports where. The source file is never changed and no existing file is overwritten. |
| `humanize_status` | none | The portal's health: readiness, CLIs, strength descriptions, model options and defaults, input limits, queue. |

- `strength`: `normal` (default), `medium`, `strong`, `very-strong`, `rewrite`. It applies to text and TXT/MD files.
  DOCX/PPTX keep the default strength (their edits stay inside formatting runs), and the tool refuses a strength for them.
- `engine`: `codex` (default) or `claude`. `model` and `effort` default to the portal's defaults; `humanize_status`
  lists the valid values.
- TXT/MD files are read like the web page reads them (UTF-8, UTF-16 with BOM, or CP949; at most 1 MiB) and written
  back as UTF-8. Office files may be up to 50 MiB.
- Long jobs send `notifications/progress` when the client passes a progress token. A `notifications/cancelled` from
  the client aborts the portal job.
- Tool failures come back as tool errors (`isError: true`) with the portal's message and code, for example
  `INVALID_MODEL_SETTINGS`, `QUEUE_FULL` or `PORTAL_UNREACHABLE`.

## Register the server

Build once (`npm run build`), then register `dist/mcp/server.js` with your client. Use the Node of the Hermes service
(`~/.hermes/node/bin/node`) or any Node 24.

Claude Code (`-s user` makes it available in every project; without it the server is added for the current project
only). Check it with `claude mcp list`, or `/mcp` inside a session:

```bash
claude mcp add -s user humanize-kr -- ~/.hermes/node/bin/node /Users/wisdom/wisdom_project/gpt/ai-text-makes-likes-human/dist/mcp/server.js
```

Codex (`~/.codex/config.toml`). Codex stops a tool call after 60 seconds by default, and a rewrite can take several
minutes plus queue time, so raise `tool_timeout_sec` (see [Time limits](#time-limits)):

```toml
[mcp_servers.humanize-kr]
command = "/Users/wisdom/.hermes/node/bin/node"
args = ["/Users/wisdom/wisdom_project/gpt/ai-text-makes-likes-human/dist/mcp/server.js"]
tool_timeout_sec = 3600
```

Any other stdio MCP client: command `node`, argument `<repo>/dist/mcp/server.js`.

To try it without changing any client configuration:

```bash
echo "Call humanize_status once and report the status." | claude -p --strict-mcp-config \
  --mcp-config '{"mcpServers":{"humanize-kr":{"command":"node","args":["<repo>/dist/mcp/server.js"]}}}' \
  --allowedTools mcp__humanize-kr__humanize_status
```

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `HUMANIZE_PORTAL_URL` | `http://127.0.0.1:7882` | Portal address. From another computer on the same LAN, use the server's address, e.g. `http://192.168.0.10:7882`. |

On another computer, check out and build this repository there, then pass the address with the registration:

```bash
claude mcp add -s user humanize-kr -e HUMANIZE_PORTAL_URL=http://192.168.0.10:7882 -- node <repo>/dist/mcp/server.js
```

For Codex, add `env = { HUMANIZE_PORTAL_URL = "http://192.168.0.10:7882" }` to the `[mcp_servers.humanize-kr]` table.
`humanize_file` reads and writes files on the computer where the MCP server runs and uploads them to the portal.

The portal accepts only private-network clients and has no login, so the MCP server inherits the same rule: run it on
the portal's machine or on the same LAN.

## Time limits

A call lasts as long as its portal job, including time waiting in the queue behind up to two other jobs. Three limits
apply:

| Layer | Limit |
|---|---|
| MCP client | Codex: `tool_timeout_sec`, 60 s by default; set it to `3600` (1 hour) as above, or higher for very long documents. Claude Code: if a call is cut off, start Claude Code with a larger `MCP_TOOL_TIMEOUT` in milliseconds, e.g. `MCP_TOOL_TIMEOUT=3600000 claude`. |
| MCP server | No limit of its own. It talks to the portal over `node:http`, because Node's built-in `fetch` drops a response that stays silent for 5 minutes, and a queued job or one long chunk sends nothing for that long. |
| Portal | Each chunk may run up to 10 minutes; a chunk that runs longer fails the job with `ENGINE_TIMEOUT`. A stuck job therefore ends on the portal side, and a generous client limit does not leave a call hanging forever. |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `PORTAL_UNREACHABLE` | The portal is not running or `HUMANIZE_PORTAL_URL` is wrong. Check `node dist/ops/hermes-service.js status`. |
| The client gives up after about a minute | The client's tool timeout is shorter than the job. Raise it (Codex `tool_timeout_sec`; Claude Code `MCP_TOOL_TIMEOUT`, in milliseconds); see [Time limits](#time-limits). |
| `ENGINE_TIMEOUT` | One chunk ran longer than 10 minutes on the portal. Retry, or choose a lighter model or effort. |
| `QUEUE_FULL` | Three jobs are already accepted. Retry when the queue drains. |
| `INVALID_MODEL_SETTINGS` | The model or effort is not offered. Call `humanize_status` for the list. |
| "DOCX·PPTX는 … 보통으로만" | A strength was given for an Office file. Drop `strength`. |
| "같은 이름의 파일이 이미 있습니다" | `outputPath` exists. Choose a new path, or omit it for an automatic name. |
