#!/usr/bin/env python3
"""Optional MCP server exposing Habitica to MCP clients (Claude Desktop,
the Claude Agent SDK, etc.).

The Skill in ``skills/habitica`` is the recommended way to use this project
from Claude Code and needs no dependencies. This MCP server exists so the same
functionality is reachable from clients that don't run filesystem skills. It
reuses the exact same engine (``habitica_client``) — including the mandatory
``x-client`` header — so behavior is identical everywhere.

Requires the official MCP SDK:  pip install -r mcp/requirements.txt
Credentials come from the environment (HABITICA_USER_ID / HABITICA_API_TOKEN),
typically supplied via the MCP client's ``env`` config, or from
~/.config/habitica/credentials.

Run directly for a stdio server:  python3 mcp/habitica_mcp.py
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

# Import the shared client from the skill's scripts directory (single source
# of truth). Override the location with HABITICA_CLIENT_DIR if you relocate it.
_HERE = os.path.dirname(os.path.abspath(__file__))
_CLIENT_DIR = os.environ.get(
    "HABITICA_CLIENT_DIR",
    os.path.abspath(os.path.join(_HERE, "..", "skills", "habitica", "scripts")),
)
sys.path.insert(0, _CLIENT_DIR)

import habitica_client as hc  # noqa: E402

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "The MCP SDK is not installed. Run: pip install -r mcp/requirements.txt\n"
    )
    raise

mcp = FastMCP("habitica")

_client: Optional[hc.HabiticaClient] = None


def _get_client() -> hc.HabiticaClient:
    global _client
    if _client is None:
        _client = hc.HabiticaClient(app_name="habitica-claude-mcp")
    return _client


def _safe(fn) -> Any:
    """Run fn(); convert HabiticaError into a clean message for the model."""
    try:
        return fn()
    except hc.HabiticaError as exc:
        return f"Error: {exc.detailed()}"


def _trim_task(task: dict) -> dict:
    out = {
        "id": task.get("id") or task.get("_id"),
        "type": task.get("type"),
        "text": task.get("text"),
    }
    if task.get("type") in ("todo", "daily"):
        out["completed"] = bool(task.get("completed"))
    if task.get("type") == "todo" and task.get("date"):
        out["due"] = str(task["date"])[:10]
    if task.get("priority") is not None:
        out["priority"] = task["priority"]
    if task.get("tags"):
        out["tags"] = task["tags"]
    checklist = task.get("checklist") or []
    if checklist:
        out["checklist"] = [
            {"id": i.get("id"), "text": i.get("text"), "completed": bool(i.get("completed"))}
            for i in checklist
        ]
    return out


def _build_reminder(
    time_text: str,
    date_text: str = "",
    timezone_offset: Optional[int] = None,
) -> dict:
    when = (
        hc.iso_datetime(date_text, time_text, timezone_offset)
        if date_text
        else hc.iso_time(time_text, timezone_offset)
    )
    return {"id": hc.new_uuid(), "startDate": when, "time": when}


CONFIRM_HINT = "Set confirm=true to proceed (the user must agree first)."


# -- reads -----------------------------------------------------------------

@mcp.tool()
def get_stats() -> dict:
    """Get the user's character stats: level, class, HP, MP, XP, gold."""
    def run():
        stats = (_get_client().get_user() or {}).get("stats", {}) or {}
        return {k: stats.get(k) for k in ("lvl", "class", "hp", "mp", "exp", "gp", "toNextLevel")}
    return _safe(run)


@mcp.tool()
def list_tasks(task_type: str = "") -> list:
    """List tasks. task_type: habits | dailys | todos | rewards | completedTodos
    (friendly forms like 'daily'/'todos' are accepted). Empty = all active tasks."""
    def run():
        tasks = _get_client().list_tasks(task_type or None) or []
        return [_trim_task(t) for t in tasks]
    return _safe(run)


@mcp.tool()
def get_task(task_id: str) -> dict:
    """Get a single task by id (full detail, including checklist item ids)."""
    return _safe(lambda: _get_client().get_task(task_id))


@mcp.tool()
def list_tags() -> list:
    """List the user's tags with their ids."""
    def run():
        return [
            {"id": t.get("id") or t.get("_id"), "name": t.get("name")}
            for t in (_get_client().list_tags() or [])
        ]
    return _safe(run)


# -- task writes -----------------------------------------------------------

@mcp.tool()
def add_task(
    text: str,
    task_type: str = "todo",
    notes: str = "",
    priority: Optional[float] = None,
    due: str = "",
    checklist: Optional[list] = None,
    tags: Optional[list] = None,
    create_missing_tags: bool = False,
    frequency: str = "",
    every: Optional[int] = None,
    repeat_days: Optional[list] = None,
    start_date: str = "",
    reminders: Optional[list] = None,
) -> dict:
    """Create a task. task_type: habit | daily | todo | reward.
    priority: 0.1 trivial, 1 easy, 1.5 medium, 2 hard. due/start_date: 'YYYY-MM-DD'.
    repeat_days: subset of [su,m,t,w,th,f,s] (dailies). reminders: ['HH:MM', ...]."""
    def run():
        if due:
            hc.iso_date(due)
        if start_date:
            hc.iso_date(start_date)
        reminder_date = due or start_date
        for reminder_time in reminders or []:
            if reminder_date:
                hc.iso_datetime(reminder_date, reminder_time)
            else:
                hc.iso_time(reminder_time)

        client = _get_client()
        timezone_offset = None
        if due or start_date or reminders:
            timezone_offset = client.get_timezone_offset()
        fields: dict = {"type": task_type, "text": text}
        if notes:
            fields["notes"] = notes
        if priority is not None:
            fields["priority"] = priority
        if due:
            fields["date"] = hc.iso_date(due, timezone_offset)
        if checklist:
            fields["checklist"] = [{"text": t} for t in checklist]
        if tags:
            fields["tags"] = [
                client.resolve_tag_id(name, create_missing=create_missing_tags)
                for name in tags
            ]
        if frequency:
            fields["frequency"] = frequency
        if every is not None:
            fields["everyX"] = every
        if repeat_days:
            fields["repeat"] = {d: (d in repeat_days) for d in
                                ("su", "m", "t", "w", "th", "f", "s")}
        if start_date:
            fields["startDate"] = hc.iso_date(start_date, timezone_offset)
        if reminders:
            fields["reminders"] = [
                _build_reminder(t, reminder_date, timezone_offset)
                for t in reminders
            ]
        return _trim_task(client.create_task(**fields))
    return _safe(run)


@mcp.tool()
def update_task(
    task_id: str,
    text: Optional[str] = None,
    notes: Optional[str] = None,
    priority: Optional[float] = None,
    due: Optional[str] = None,
) -> dict:
    """Update a task's text, notes, priority (0.1/1/1.5/2), or due date ('YYYY-MM-DD')."""
    def run():
        if due is not None:
            hc.iso_date(due)
        client = _get_client()
        fields = {}
        if text is not None:
            fields["text"] = text
        if notes is not None:
            fields["notes"] = notes
        if priority is not None:
            fields["priority"] = priority
        if due is not None:
            fields["date"] = hc.iso_date(due, client.get_timezone_offset())
        if not fields:
            return "Error: nothing to update."
        return _trim_task(client.update_task(task_id, **fields))
    return _safe(run)


@mcp.tool()
def complete_task(task_id: str, confirm: bool = False) -> str:
    """Complete a to-do/daily or score a habit up. If the id is a REWARD this
    spends gold and requires confirm=true."""
    return _score(task_id, "up", confirm)


@mcp.tool()
def score_task(task_id: str, direction: str, confirm: bool = False) -> str:
    """Score a task 'up' or 'down'. Guarded (needs confirm=true) when scoring a
    daily/todo down (un-complete/penalty) or scoring a reward up (purchase)."""
    return _score(task_id, direction, confirm)


def _score(task_id: str, direction: str, confirm: bool) -> str:
    def run():
        client = _get_client()
        task = client.get_task(task_id)
        ttype, text = task.get("type"), task.get("text", "")
        if direction == "up" and ttype == "reward" and not confirm:
            cost = round(task.get("value", 0))
            return (f"REFUSED: '{text}' is a reward — scoring up SPENDS {cost} gold. "
                    + CONFIRM_HINT)
        if direction == "down" and ttype in ("daily", "todo") and not confirm:
            return (f"REFUSED: scoring '{text}' down un-completes/penalizes this "
                    f"{ttype}. " + CONFIRM_HINT)
        data = client.score_task(task_id, direction)
        verb = "Bought" if (direction == "up" and ttype == "reward") else f"Scored {direction}"
        bits = ", ".join(f"{k.upper()} {round(data[k], 2)}"
                         for k in ("hp", "exp", "gp", "lvl") if k in data)
        return f"OK: {verb} '{text}'. {bits}".strip()
    return _safe(run)


@mcp.tool()
def delete_task(task_id: str, confirm: bool = False) -> str:
    """Permanently delete a task. Requires confirm=true."""
    if not confirm:
        return f"REFUSED: deleting task {task_id} is permanent. " + CONFIRM_HINT
    return _safe(lambda: (_get_client().delete_task(task_id), f"OK: deleted task {task_id}")[1])


# -- checklist -------------------------------------------------------------

@mcp.tool()
def add_checklist_item(task_id: str, text: str) -> str:
    """Add a checklist item to a task."""
    return _safe(lambda: (_get_client().add_checklist_item(task_id, text),
                          f"OK: added checklist item to {task_id}")[1])


@mcp.tool()
def check_checklist_item(task_id: str, item_id: str) -> str:
    """Toggle a checklist item's completed state."""
    return _safe(lambda: (_get_client().score_checklist_item(task_id, item_id),
                          f"OK: toggled checklist item {item_id}")[1])


@mcp.tool()
def update_checklist_item(task_id: str, item_id: str, text: str) -> str:
    """Edit a checklist item's text."""
    return _safe(lambda: (_get_client().update_checklist_item(task_id, item_id, text),
                          f"OK: updated checklist item {item_id}")[1])


@mcp.tool()
def delete_checklist_item(task_id: str, item_id: str, confirm: bool = False) -> str:
    """Delete a checklist item. Requires confirm=true."""
    if not confirm:
        return f"REFUSED: deleting checklist item {item_id} is permanent. " + CONFIRM_HINT
    return _safe(lambda: (_get_client().delete_checklist_item(task_id, item_id),
                          f"OK: deleted checklist item {item_id}")[1])


# -- tags ------------------------------------------------------------------

@mcp.tool()
def create_tag(name: str) -> str:
    """Create a tag."""
    def run():
        data = _get_client().create_tag(name)
        return f"OK: created tag '{name}' (id={data.get('id') or data.get('_id')})"
    return _safe(run)


@mcp.tool()
def assign_tag(task_id: str, tag_name: str, create_if_missing: bool = False) -> str:
    """Assign a tag (by name) to a task; optionally create the tag if missing."""
    def run():
        client = _get_client()
        tag_id = client.resolve_tag_id(tag_name, create_missing=create_if_missing)
        client.add_tag_to_task(task_id, tag_id)
        return f"OK: tagged {task_id} with '{tag_name}'"
    return _safe(run)


@mcp.tool()
def remove_tag(task_id: str, tag_name: str) -> str:
    """Remove a tag from one task without deleting the tag globally."""
    def run():
        client = _get_client()
        tag_id = client.resolve_tag_id(tag_name)
        client.remove_tag_from_task(task_id, tag_id)
        return f"OK: removed tag '{tag_name}' from {task_id}"
    return _safe(run)


@mcp.tool()
def delete_tag(tag_id: str, confirm: bool = False) -> str:
    """Delete a tag (removes it from ALL tasks). Requires confirm=true."""
    if not confirm:
        return f"REFUSED: deleting tag {tag_id} removes it from all tasks. " + CONFIRM_HINT
    return _safe(lambda: (_get_client().delete_tag(tag_id), f"OK: deleted tag {tag_id}")[1])


if __name__ == "__main__":
    mcp.run()
