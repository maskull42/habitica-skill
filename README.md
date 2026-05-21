# Habitica for Claude

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen.svg)

Let Claude read and manage your [Habitica](https://habitica.com) account — your
to-dos, habits, dailies, rewards, reminders, checklists, tags, and character
stats. It ships primarily as a **Claude Code Skill** backed by a tiny,
dependency-free Python CLI, plus an optional **MCP server** for other clients.

> "Add a todo to call the dentist Friday, high priority." · "What dailies do I
> still have today?" · "I finished my workout." · "What's my level and gold?"

## Why this exists

Habitica's API requires an `x-client` header on every authenticated request
(enforced since ~July 2025). Tools that omit it get a hard `400` and silently
stop working. This client always sends it correctly, surfaces API errors loudly
instead of failing quietly, respects Habitica's rate limit, and **guards
destructive or gold-spending actions** behind explicit confirmation. The whole
thing is auditable: standard-library Python and Markdown, no third-party code
holding your token.

## Features

- Full task management: list/create/update/complete/delete to-dos, habits,
  dailies, and rewards; checklists; tags; due dates and daily recurrence.
- Character stats: level, class, HP, MP, XP, gold.
- Safe by default: deleting, un-completing a daily/todo, or buying a reward
  requires a confirmation step.
- Zero install for the skill (Python 3.8+ stdlib only). The MCP server is the
  only piece with a dependency.

## Where it works

| Surface | Works? | How |
| --- | --- | --- |
| Claude Code (CLI / IDE / desktop) | ✅ | the Skill — plugin or `install.sh` |
| Claude Desktop, other MCP clients | ✅ | the MCP server |
| Claude Agent SDK / custom agents | ✅ | the MCP server, or `import habitica_client` |
| Claude API "skills" feature | ❌ | its sandbox has no network — use the MCP server |
| Claude.ai web chat | ❌ | no local code execution |

See [`docs/install.md`](docs/install.md) for full details and
[`docs/agent-sdk.md`](docs/agent-sdk.md) for SDK/API usage.

## Install (Claude Code)

**As a plugin (no clone):**

```text
/plugin marketplace add maskull42/habitica-skill
/plugin install habitica@habitica-marketplace
```

**Or clone and link:**

```bash
git clone https://github.com/maskull42/habitica-skill.git
cd habitica-skill
./install.sh          # symlink into ~/.claude/skills/  (use --copy to copy)
```

Restart Claude Code afterward so it discovers the skill.

## Credentials

Get your **User ID** and **API Token** at
<https://habitica.com/user/settings/api> (Settings → Site Data / API), then
provide them one of two ways:

```bash
export HABITICA_USER_ID="your-user-id"
export HABITICA_API_TOKEN="your-api-token"
```

or a file at `~/.config/habitica/credentials` (then `chmod 600 it`):

```
HABITICA_USER_ID=your-user-id
HABITICA_API_TOKEN=your-api-token
```

**Never commit your token.** Treat it like a password.

## Usage

Once installed, just talk to Claude about Habitica and it will use the skill.
Under the hood it runs the CLI, which you can also use directly:

```bash
SKILL=~/.claude/skills/habitica/scripts/habitica.py
python3 "$SKILL" stats
python3 "$SKILL" list --type todos
python3 "$SKILL" add --type todo --text "Buy milk" --due 2026-06-01 --priority 1.5
python3 "$SKILL" done <task-id>
python3 "$SKILL" add --type daily --text "Stretch" --repeat m w f --remind 07:30
python3 "$SKILL" --dry-run rm <task-id>   # preview without sending
```

Run `python3 "$SKILL" --help` (or `<command> --help`) for everything.

## Safety

These actions refuse to run without `--yes` (CLI) / `confirm=true` (MCP), and
the skill instructs Claude to confirm with you first:

- deleting a task, tag, or checklist item;
- scoring a daily/to-do **down** (un-completing / losing HP);
- "completing" a **reward** (which spends your gold).

Everything else — reading, adding, completing normal tasks, editing — runs
without prompting.

## Project layout

```
.claude-plugin/      plugin.json + marketplace.json (plugin install)
skills/habitica/     SKILL.md, reference.md, scripts/ (the skill + CLI)
mcp/                 habitica_mcp.py + requirements.txt (optional MCP server)
docs/                install + agent-SDK guides
install.sh           symlink/copy the skill into ~/.claude/skills
```

The single source of truth for API logic is
`skills/habitica/scripts/habitica_client.py`; the CLI and MCP server both use it.

## Development

No build step. After editing, sanity-check with:

```bash
python3 -m py_compile skills/habitica/scripts/*.py mcp/habitica_mcp.py
python3 skills/habitica/scripts/habitica.py --dry-run add --type todo --text demo
```

Contributions welcome — open an issue or PR. Please keep the skill/CLI
dependency-free (standard library only); dependencies belong only to the
optional MCP server.

## License & disclaimer

[MIT](LICENSE) © 2026 A.G. Elrod. Not affiliated with or endorsed by Habitica /
HabitRPG. Use of the Habitica API is subject to Habitica's
[terms](https://habitica.com/static/terms) and
[API guidelines](https://github.com/HabitRPG/habitica/wiki/API-Usage-Guidelines).
