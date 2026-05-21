# Habitica API reference (for this skill)

Detail behind the `habitica.py` CLI. Read this only when you need exact field
semantics, recurrence rules, or error/rate-limit behavior. Base URL:
`https://habitica.com/api/v3`. Official docs: https://habitica.com/apidoc/

## Authentication & the `x-client` header

Every request sends three headers (handled by the client; you never set them):

- `x-api-user` — the user's User ID
- `x-api-key` — the user's API Token
- `x-client` — **mandatory**, format `<userId>-<appName>`

The skill defaults `x-client` to `<HABITICA_USER_ID>-habitica-claude-skill`.
Omitting it is a hard failure (verified live: `400 BadRequest`, "Missing
x-client headers."). This is the bug that breaks several third-party tools.
Override the app-name suffix with `HABITICA_APP_NAME` (or `--app-name`); per
Habitica's guidelines you may instead prefix with the tool author's User ID.

Credentials load from environment variables first
(`HABITICA_USER_ID`, `HABITICA_API_TOKEN`, optional `HABITICA_APP_NAME`), then
from `~/.config/habitica/credentials` (`KEY=VALUE` lines; override the path with
`HABITICA_CREDENTIALS`). Get both values at
https://habitica.com/user/settings/api.

## Endpoints behind each command

| CLI | HTTP | Path |
| --- | --- | --- |
| `stats` | GET | `/user` |
| `list [--type T]` | GET | `/tasks/user[?type=T]` |
| `get <id>` | GET | `/tasks/:id` |
| `add` | POST | `/tasks/user` |
| `update <id>` | PUT | `/tasks/:id` |
| `done`/`up`/`down` | POST | `/tasks/:id/score/:direction` |
| `rm <id>` | DELETE | `/tasks/:id` |
| `checklist-add` | POST | `/tasks/:id/checklist` |
| `checklist-check` | POST | `/tasks/:id/checklist/:itemId/score` |
| `checklist-update` | PUT | `/tasks/:id/checklist/:itemId` |
| `checklist-rm` | DELETE | `/tasks/:id/checklist/:itemId` |
| `tags` | GET | `/tags` |
| `tag-add` | POST | `/tags` |
| `tag-assign` | POST | `/tasks/:taskId/tags/:tagId` |
| `tag-rm <id>` | DELETE | `/tags/:id` |

Tags live at `/tags` (not `/user/tags`). `tag-assign` uses the dedicated
`POST /tasks/:taskId/tags/:tagId` endpoint, so it adds a tag without rewriting
the task's whole `tags` array. `tag-assign`/`add --tag` resolve a tag *name* to
its id via one `GET /tags` (case-insensitive), creating it only with
`--create-tags`. A task `id` may also be an `alias` you set.

## Task fields (create / update body)

| Field | Types | Notes |
| --- | --- | --- |
| `type` | all | required on create: `habit`, `daily`, `todo`, `reward` |
| `text` | all | title |
| `notes` | all | description |
| `priority` | all | difficulty: `0.1` trivial, `1` easy (default), `1.5` medium, `2` hard |
| `date` | todo | due date (the CLI's `--due`), ISO 8601 |
| `checklist` | todo, daily | array of `{text}` (the API assigns each item an id) |
| `tags` | all | array of tag **ids** |
| `frequency` | daily | `daily`, `weekly` (default), `monthly`, `yearly` — controls how `everyX`/`repeat` are read |
| `everyX` | daily | interval, default 1 (e.g. `everyX:2`, `frequency:daily` = every other day) |
| `repeat` | daily | object with keys `su m t w th f s` (booleans); used when `frequency:weekly` |
| `startDate` | daily | when the daily becomes active, ISO 8601 |
| `daysOfMonth`, `weeksOfMonth` | daily | int arrays, used with `frequency:monthly` (not exposed by the CLI yet) |
| `reminders` | daily, todo | array of `{id, startDate?, time}` — see below |

### Dates and times

The CLI expands `--due`, `--start-date` (`YYYY-MM-DD`) and `--remind` (`HH:MM`)
to ISO 8601 using the **machine's local timezone**, so a due date keeps its
calendar day. If you run on a server in another timezone, pass full ISO strings
via `--json`-style updates or set the box's timezone accordingly.

### Reminders (least-verified)

Each reminder is `{id, startDate, time}` where `id` is a UUID (the client
generates one) and `time`/`startDate` are full ISO datetimes; for dailies the
time-of-day is what matters. Reminder field shapes are **not** strongly
documented in the official apidoc — treat `--remind` as best-effort and verify
behavior in the Habitica app after setting one.

## Scoring semantics

`POST /tasks/:id/score/:direction` (`up`/`down`):

- **to-do / daily** — `up` completes it, `down` un-completes/penalizes.
- **habit** — `up`/`down` increment the +/- counters (only the directions the
  habit enables).
- **reward** — `up` **purchases** it, spending `value` gold. (The CLI fetches
  the task first to detect this and other guarded cases.)

The response `data` contains stat **deltas and new values** (`delta`, `hp`,
`mp`, `exp`, `gp`, `lvl`) and a `_tmp` object that may include a `drop` — not
the full task. The CLI prints the resulting HP/XP/Gold/Lvl.

## Response & error envelopes

Success: `{ "success": true, "data": <payload>, "notifications": [...],
"appVersion": "...", "userV": N }`. The client returns just `data`.

Error: `{ "success": false, "error": "<code>", "message": "<human text>",
"errors": [ {"message","param","value"} ] }`. The client raises with the
`message`, `error` code, HTTP status, and any field `errors`. Verified-live
codes: bad credentials → `401 invalid_credentials`; missing `x-client` →
`400 BadRequest` ("Missing x-client headers.").

## Rate limits

30 requests per 60 seconds, per User ID or IP. Every response carries
`X-RateLimit-Limit` (30), `X-RateLimit-Remaining`, and `X-RateLimit-Reset`
(an HTTP **date string**, not a Unix epoch). Exceeding the limit returns
`429` with a `Retry-After` header in **seconds** (may be fractional); the client
honors it and retries up to twice. Don't poll in a loop; batch reads.

## Task `type` query values (the `dailys` quirk)

`GET /tasks/user?type=` accepts `habits`, `dailys`, `todos`, `rewards`,
`completedTodos`. Note **`dailys`** (a long-standing API spelling, see
HabitRPG/habitica#10027). The CLI accepts friendly forms (`daily`, `dailies`,
`todo`, …) and normalizes them, so you can use whichever; the raw API needs the
exact plural. Completed to-dos are excluded by default — pass
`--type completedTodos` to see them.

## Cron

Habitica runs "cron" (applies missed-daily damage, resets dailies) automatically
on the user's first activity after their Custom Day Start. There is a
`POST /cron` endpoint, but it is **not** exposed by this skill — it can cost the
user HP and should not be triggered casually.

## Out of scope (v1)

Gameplay actions — casting class skills, buying from the shop, pets/mounts,
quests, party/guild/social — are intentionally omitted. They follow the same
client + confirm-then-`--yes` pattern and can be added later.
