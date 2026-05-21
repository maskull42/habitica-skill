---
name: habitica
description: Read and modify the user's Habitica account — to-dos, habits, dailies, rewards, reminders, checklists, tags, and character stats (HP, XP, gold, level). Use whenever the user mentions Habitica, or asks to add, list, complete, check off, score, or delete a to-do, habit, or daily, manage checklists or tags, or check their level, gold, streak, or stats. Runs a bundled stdlib Python CLI against the Habitica API v3.
---

# Habitica

Manage the user's Habitica account through a bundled command-line tool. All
operations go through one script — never call the Habitica API directly.

## How to run it

Always invoke the bundled CLI by its skill-relative path so it works on any
install (personal, project, or plugin):

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/habitica.py" <command> [options]
```

- Default output is compact and human-readable. Add `--json` only when you need
  to parse a result programmatically (it's more verbose — prefer the default to
  keep context small).
- Add `--dry-run` to preview the exact HTTP request without sending it. Global
  flags like `--dry-run` and `--json` work before or after the subcommand.
- Requires Python 3.8+ and configured credentials (see **First-run setup**).

## Guardrails — read before acting

Some actions are destructive or spend in-game currency. The CLI **refuses** them
unless you pass `--yes`. Before passing `--yes`, you MUST:

1. State plainly what will change (which task, that it's permanent / costs gold /
   loses progress), then
2. get the user's explicit confirmation, then
3. re-run the command with `--yes`.

Actions that require this confirm-then-`--yes` flow:

| Action | Why it's guarded |
| --- | --- |
| `rm <id>` | permanently deletes a task |
| `tag-rm <id>` | deletes a tag and removes it from **all** tasks |
| `checklist-rm <task> <item>` | permanently deletes a checklist item |
| `down <id>` (a daily or to-do) | un-completes it / costs HP |
| `done`/`up` on a **reward** | spends the user's gold (a purchase) |

Never invent or auto-pass `--yes`. Never delete or buy something the user only
described loosely — confirm the specific item first. Everything else (reading,
adding, completing a normal task, editing) needs no `--yes`.

## Permissions

On first use, Claude Code will prompt to run the `python3 …habitica.py` command.
Approve it; choose "don't ask again" to persist the approval. (This skill ships
no `allowed-tools` allowlist so it stays portable across machines.)

## Command reference

Reading:
- `stats` — level, class, HP, XP, gold.
- `list [--type T] [--tag NAME] [--show-tags] [--limit N]` — list tasks.
  `T` is one of `habits`, `dailys`, `todos`, `rewards`, `completedTodos`
  (friendly forms like `daily`/`todos` are accepted and normalized).
- `get <id>` — one task with notes and checklist item ids.
- `tags` — list tags with their ids.

Tasks:
- `add --type <habit|daily|todo|reward> --text "..."` plus optional
  `--notes`, `--priority <0.1|1|1.5|2>`, `--due YYYY-MM-DD` (todos),
  `--checklist "a" "b"`, `--tag NAME` (repeatable, `--create-tags` to make new),
  and for dailies `--frequency <daily|weekly|monthly|yearly> --every N
  --repeat su m t w th f s --start-date YYYY-MM-DD --remind HH:MM`.
- `update <id> [same field flags]` — change text/notes/priority/due/recurrence,
  set reminders, or add tags with `--tag`. It refuses `--checklist`; use the
  dedicated checklist commands so item ids and progress are preserved.
- `done <id>` — complete a to-do/daily or score a habit up.
- `up <id>` / `down <id>` — score a habit (+/–); `down` on a daily/todo is guarded.
- `rm <id> --yes` — delete (guarded).

Checklists & tags:
- `checklist-add <taskId> --text "..."`
- `checklist-check <taskId> <itemId>` — toggle done.
- `checklist-update <taskId> <itemId> --text "..."`
- `checklist-rm <taskId> <itemId> --yes` — delete (guarded).
- `tag-add --name "..."`
- `tag-assign <taskId> --tag NAME [--create-tags]`
- `tag-unassign <taskId> --tag NAME`
- `tag-rm <tagId> --yes` — delete (guarded).

Task ids are shown in `list`/`get` output as `id=…`. Use the full id in
follow-up commands. See `reference.md` for the full field semantics (priority
values, the daily `repeat` object, reminders, the `dailys` spelling quirk,
rate limits, and error handling) — read it only when you need that detail.

## Workflow recipes

**Morning review.** Run `list --type dailys` and `list --type todos`; summarize
what's still incomplete and what's due today. Offer to mark things done.

**Log a completion.** When the user says "I did X" / "finished X": run `list`
(of the likely type) to find the matching task and its id. If exactly one
matches, `done <id>` and report the XP/gold change. If several could match, ask
which one before scoring.

**Add a to-do.** From "remind me to … / add a todo to …", run `add --type todo
--text "…"`. Infer `--due` from any date the user gives and `--priority` from
urgency words ("urgent"→2, "important"→1.5, "whenever"→0.1); otherwise omit them.

**Create a habit or daily.** For recurring things, use `--type daily` with
`--repeat`/`--frequency`; for +/- behaviors use `--type habit`. Confirm the
recurrence you chose.

**Weekly cleanup.** `list --type todos`, point out stale/duplicate items, and
for any the user agrees to remove, delete them one at a time with the
confirm-then-`--yes` flow.

## First-run setup

If any command prints "Habitica credentials not found", help the user configure
them — do **not** ask them to paste their token into the chat. Tell them:

1. Open https://habitica.com/user/settings/api (Settings → Site Data / API) and
   copy their **User ID** and **API Token**.
2. Either export environment variables in their shell profile:
   `export HABITICA_USER_ID=…` and `export HABITICA_API_TOKEN=…`,
   or create `~/.config/habitica/credentials` (then
   `chmod 600 ~/.config/habitica/credentials`) with lines
   `HABITICA_USER_ID=…` and `HABITICA_API_TOKEN=…`.
3. Re-run the command. Verify with `stats`.
