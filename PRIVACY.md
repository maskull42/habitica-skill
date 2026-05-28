# Privacy Policy

**Effective:** 2026-05-28

The Habitica-for-Claude plugin and its accompanying MCP server (this
"Software") collect no information about you, send nothing to the author, and
operate no servers, telemetry, or analytics.

## What the Software is

A local tool that runs on your machine when invoked by Claude Code or another
MCP client. The author hosts no infrastructure of any kind.

## How your data flows

- **Habitica credentials** (User ID, API token) — read from your local
  environment variables or `~/.config/habitica/credentials` and sent only as
  authentication headers on requests to Habitica's API. Never logged, copied,
  or transmitted elsewhere.
- **Habitica account data** (tasks, stats, tags, checklists) — exchanged with
  **Habitica only**, in response to your prompts. Same data flow as using
  Habitica's own website. Habitica's handling is governed by its
  [Privacy Policy](https://habitica.com/static/privacy).
- **`x-client` header** — Habitica's API requires identifying traffic. This
  Software sends `<your-user-id>-habitica-claude-skill` (or
  `-habitica-claude-mcp` for the MCP server). Sent only to Habitica.
- **API responses** — returned to your local Claude Code session and visible
  to Claude (the language model) as conversation context. Anthropic's handling
  of that context is governed by Anthropic's privacy policy.

## What the Software does not do

- Does not transmit anything to the author.
- Does not include analytics, telemetry, crash reports, or "phone-home"
  mechanisms.
- Does not access any service other than Habitica's API.
- Does not write credentials to logs.

## Verify it yourself

The Software is open source under the [MIT License](LICENSE). The entire HTTP
client is in
[`skills/habitica/scripts/habitica_client.py`](skills/habitica/scripts/habitica_client.py)
(standard library only) and the MCP server in
[`mcp/habitica_mcp.py`](mcp/habitica_mcp.py). Both use the same
`HabiticaClient`, so any audit of one applies to the other.

## Questions

Open an issue at <https://github.com/maskull42/habitica-skill/issues>.

## Changes

Material changes will appear in this file's git history.
