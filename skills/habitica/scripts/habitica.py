#!/usr/bin/env python3
"""Command-line interface for managing a Habitica account.

This is the executable the Habitica skill calls. It is a thin argparse layer
over ``habitica_client.HabiticaClient`` (the shared, dependency-free engine).

Design notes for whoever (human or agent) drives this:
  * Output is compact and human-readable by default; pass ``--json`` for the
    raw API ``data`` payload when you need to parse it.
  * Destructive or costly actions (delete, un-complete a daily/todo, buy a
    reward) refuse to run without ``--yes``. This is the authoritative safety
    gate; confirm with the user before passing ``--yes``.
  * ``--dry-run`` prints the HTTP request that would be sent and exits — it
    works without credentials.

Run ``habitica.py --help`` or ``habitica.py <command> --help`` for usage.
"""

from __future__ import annotations

import argparse
import json
import sys

from habitica_client import (
    HabiticaAuthError,
    HabiticaClient,
    HabiticaError,
    PlannedRequest,
    VALID_TASK_TYPES,
    iso_date,
    iso_datetime,
    iso_time,
    new_uuid,
)

PRIORITY_CHOICES = {"0.1": 0.1, "1": 1.0, "1.5": 1.5, "2": 2.0}
PRIORITY_LABEL = {0.1: "trivial", 1.0: "easy", 1.5: "medium", 2.0: "hard"}
REPEAT_DAYS = ("su", "m", "t", "w", "th", "f", "s")
DEFAULT_LIMIT = 50


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _task_id(task):
    return task.get("id") or task.get("_id")


def _short_id(task_id):
    return (task_id or "")[:8]


def emit(data, as_json):
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def print_dry_run(result):
    """If result is a PlannedRequest (dry-run), print it and return True."""
    if isinstance(result, PlannedRequest):
        print(repr(result))
        return True
    return False


def build_reminder(time_text, date_text=None, timezone_offset=None):
    when = (
        iso_datetime(date_text, time_text, timezone_offset)
        if date_text
        else iso_time(time_text, timezone_offset)
    )
    return {"id": new_uuid(), "startDate": when, "time": when}


# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------

def format_user(user):
    stats = user.get("stats", {}) or {}
    lvl = stats.get("lvl", "?")
    cls = stats.get("class", "?")
    hp = round(stats.get("hp", 0))
    mp = round(stats.get("mp", 0))
    exp = round(stats.get("exp", 0))
    gp = round(stats.get("gp", 0))
    to_next = round(stats.get("toNextLevel", 0))
    name = (user.get("profile", {}) or {}).get("name", "")
    header = f"{name} " if name else ""
    return (
        f"{header}(level {lvl} {cls})\n"
        f"  HP {hp}   MP {mp}   XP {exp}/{exp + to_next}   Gold {gp}"
    )


def format_task_line(task, tag_names=None):
    ttype = task.get("type")
    text = task.get("text", "").replace("\n", " ")
    tid = _task_id(task)
    if ttype in ("todo", "daily"):
        mark = "[x]" if task.get("completed") else "[ ]"
    elif ttype == "habit":
        up = "+" if task.get("up") else ""
        down = "-" if task.get("down") else ""
        mark = f"({up}{down or ''})" or "( )"
    elif ttype == "reward":
        mark = f"({round(task.get('value', 0))}gp)"
    else:
        mark = "-"

    extras = []
    if ttype == "todo" and task.get("date"):
        extras.append(f"due {str(task['date'])[:10]}")
    pr = task.get("priority")
    if pr in PRIORITY_LABEL and pr != 1.0:
        extras.append(PRIORITY_LABEL[pr])
    if tag_names:
        names = [tag_names.get(t) for t in task.get("tags", []) if tag_names.get(t)]
        if names:
            extras.append("#" + " #".join(names))
    cl = task.get("checklist") or []
    if cl:
        done = sum(1 for i in cl if i.get("completed"))
        extras.append(f"checklist {done}/{len(cl)}")
    suffix = ("  " + ", ".join(extras)) if extras else ""
    return f"{mark} {text}{suffix}  [{ttype}, id={tid}]"


def format_score_result(data, label):
    bits = []
    for key, name in (("hp", "HP"), ("exp", "XP"), ("gp", "Gold"), ("lvl", "Lvl")):
        if key in data:
            bits.append(f"{name} {round(data[key], 2)}")
    drop = (data.get("_tmp") or {}).get("drop")
    line = f"OK: {label}"
    if bits:
        line += "  (" + ", ".join(bits) + ")"
    if drop and drop.get("text"):
        line += f"\n  Drop: {drop['text']}"
    return line


# --------------------------------------------------------------------------
# command implementations
# --------------------------------------------------------------------------

def cmd_stats(client, args):
    data = client.get_user()
    if print_dry_run(data):
        return
    if args.json:
        emit(data.get("stats", data), True)
    else:
        print(format_user(data))


def cmd_list(client, args):
    tasks = client.list_tasks(args.type)
    if print_dry_run(tasks):
        return
    tasks = tasks or []

    tag_names = None
    if args.tag or args.show_tags:
        tags = client.list_tags() or []
        tag_names = {(t.get("id") or t.get("_id")): t.get("name") for t in tags}
    if args.tag:
        wanted = args.tag.strip().lower()
        match_id = next(
            (tid for tid, n in tag_names.items() if str(n).strip().lower() == wanted),
            None,
        )
        if match_id is None:
            raise HabiticaError(f"No tag named {args.tag!r}.")
        tasks = [t for t in tasks if match_id in (t.get("tags") or [])]

    if args.json:
        emit(tasks, True)
        return
    if not tasks:
        print("(no tasks)")
        return
    limit = args.limit
    for task in tasks[:limit]:
        print(format_task_line(task, tag_names))
    if len(tasks) > limit:
        print(f"... {len(tasks) - limit} more (use --limit {len(tasks)} to see all)")


def cmd_get(client, args):
    task = client.get_task(args.id)
    if print_dry_run(task):
        return
    if args.json:
        emit(task, True)
        return
    print(format_task_line(task))
    if task.get("notes"):
        print(f"  notes: {task['notes']}")
    for item in task.get("checklist") or []:
        box = "[x]" if item.get("completed") else "[ ]"
        print(f"  {box} {item.get('text')}  (item id={item.get('id')})")


def _build_task_fields(client, args, *, for_update):
    fields = {}
    if for_update and args.checklist:
        raise HabiticaError(
            "`update --checklist` would replace the whole checklist and can "
            "discard item ids/progress. Use checklist-add, checklist-update, "
            "or checklist-rm instead."
        )
    reminder_date = args.due or args.start_date
    if args.due is not None:
        iso_date(args.due)
    if args.start_date is not None:
        iso_date(args.start_date)
    for reminder_time in args.remind or []:
        if reminder_date:
            iso_datetime(reminder_date, reminder_time)
        else:
            iso_time(reminder_time)

    timezone_offset = None
    if not client.dry_run and (args.due or args.start_date or args.remind):
        timezone_offset = client.get_timezone_offset()
    if getattr(args, "text", None) is not None:
        fields["text"] = args.text
    if args.notes is not None:
        fields["notes"] = args.notes
    if args.priority is not None:
        fields["priority"] = PRIORITY_CHOICES[args.priority]
    if not for_update:
        fields["type"] = args.type
    if args.due is not None:
        fields["date"] = iso_date(args.due, timezone_offset)
    if args.checklist:
        fields["checklist"] = [{"text": t} for t in args.checklist]
    if args.frequency is not None:
        fields["frequency"] = args.frequency
    if args.every is not None:
        fields["everyX"] = args.every
    if args.repeat:
        fields["repeat"] = {day: (day in args.repeat) for day in REPEAT_DAYS}
    if args.start_date is not None:
        fields["startDate"] = iso_date(args.start_date, timezone_offset)
    if args.remind:
        fields["reminders"] = [
            build_reminder(t, reminder_date, timezone_offset)
            for t in args.remind
        ]
    if args.tag and not for_update:
        # Resolve tag names to ids (one GET /tags); optionally auto-create.
        if client.dry_run:
            fields["tags"] = [f"<tag:{name}>" for name in args.tag]
        else:
            fields["tags"] = [
                client.resolve_tag_id(name, create_missing=args.create_tags)
                for name in args.tag
            ]
    return fields


def cmd_add(client, args):
    fields = _build_task_fields(client, args, for_update=False)
    data = client.create_task(**fields)
    if print_dry_run(data):
        return
    if args.json:
        emit(data, True)
    else:
        print(f"OK: created {args.type}: {data.get('text')}  [id={_task_id(data)}]")


def cmd_update(client, args):
    fields = _build_task_fields(client, args, for_update=True)
    if not fields and not args.tag:
        raise HabiticaError("Nothing to update; pass at least one field.")
    if client.dry_run:
        if fields:
            print_dry_run(client.update_task(args.id, **fields))
        for name in args.tag or []:
            print_dry_run(client.add_tag_to_task(args.id, f"<tag:{name}>"))
        return

    tag_ids = []
    for name in args.tag or []:
        tag_ids.append(
            (name, client.resolve_tag_id(name, create_missing=args.create_tags))
        )

    data = client.update_task(args.id, **fields) if fields else None
    if tag_ids:
        current = data or client.get_task(args.id)
        current_tags = set(current.get("tags") or [])
        data = current
        for name, tag_id in tag_ids:
            if tag_id in current_tags:
                continue
            data = client.add_tag_to_task(args.id, tag_id)
            current_tags.add(tag_id)
    if args.json:
        emit(data, True)
    else:
        print(f"OK: updated {data.get('type')}: {data.get('text')}  [id={_task_id(data)}]")


def _score(client, args, direction):
    """Shared logic for done/up/down, with reward + un-complete guards."""
    if client.dry_run:
        result = client.score_task(args.id, direction)
        print_dry_run(result)
        return

    task = client.get_task(args.id)  # also validates the id exists
    ttype = task.get("type")
    text = task.get("text", "")

    if direction == "up" and ttype == "reward":
        cost = round(task.get("value", 0))
        if not args.yes:
            raise HabiticaError(
                f"'{text}' is a REWARD — scoring it up SPENDS {cost} gold. "
                "Re-run with --yes to confirm the purchase."
            )
    if direction == "down" and ttype in ("daily", "todo"):
        if not args.yes:
            verb = "un-complete" if task.get("completed") else "penalize"
            raise HabiticaError(
                f"Scoring '{text}' down will {verb} this {ttype} (you lose progress/HP). "
                "Re-run with --yes to confirm."
            )

    data = client.score_task(args.id, direction)
    label = {
        ("up", "reward"): f"bought '{text}'",
    }.get((direction, ttype), f"scored {direction}: '{text}'")
    if args.json:
        emit(data, True)
    else:
        print(format_score_result(data, label))


def cmd_done(client, args):
    _score(client, args, "up")


def cmd_up(client, args):
    _score(client, args, "up")


def cmd_down(client, args):
    _score(client, args, "down")


def cmd_rm(client, args):
    if not args.yes and not client.dry_run:
        raise HabiticaError(
            f"Deleting task {args.id} is permanent. Re-run with --yes to confirm."
        )
    data = client.delete_task(args.id)
    if print_dry_run(data):
        return
    print(f"OK: deleted task {args.id}")


def cmd_checklist_add(client, args):
    data = client.add_checklist_item(args.task_id, args.text)
    if print_dry_run(data):
        return
    print(f"OK: added checklist item to {_short_id(args.task_id)}: {args.text}")


def cmd_checklist_check(client, args):
    data = client.score_checklist_item(args.task_id, args.item_id)
    if print_dry_run(data):
        return
    print(f"OK: toggled checklist item {args.item_id}")


def cmd_checklist_update(client, args):
    data = client.update_checklist_item(args.task_id, args.item_id, args.text)
    if print_dry_run(data):
        return
    print(f"OK: updated checklist item {args.item_id}")


def cmd_checklist_rm(client, args):
    if not args.yes and not client.dry_run:
        raise HabiticaError(
            f"Deleting checklist item {args.item_id} is permanent. Re-run with --yes."
        )
    data = client.delete_checklist_item(args.task_id, args.item_id)
    if print_dry_run(data):
        return
    print(f"OK: deleted checklist item {args.item_id}")


def cmd_tags(client, args):
    tags = client.list_tags()
    if print_dry_run(tags):
        return
    tags = tags or []
    if args.json:
        emit(tags, True)
        return
    if not tags:
        print("(no tags)")
    for tag in tags:
        print(f"{tag.get('name')}  [id={tag.get('id') or tag.get('_id')}]")


def cmd_tag_add(client, args):
    data = client.create_tag(args.name)
    if print_dry_run(data):
        return
    print(f"OK: created tag '{args.name}'  [id={data.get('id') or data.get('_id')}]")


def cmd_tag_assign(client, args):
    if client.dry_run:
        print_dry_run(client.add_tag_to_task(args.task_id, f"<tag:{args.tag}>"))
        return
    tag_id = client.resolve_tag_id(args.tag, create_missing=args.create_tags)
    data = client.add_tag_to_task(args.task_id, tag_id)
    print(f"OK: tagged {_short_id(args.task_id)} with '{args.tag}'")


def cmd_tag_unassign(client, args):
    if client.dry_run:
        print_dry_run(client.remove_tag_from_task(args.task_id, f"<tag:{args.tag}>"))
        return
    tag_id = client.resolve_tag_id(args.tag)
    data = client.remove_tag_from_task(args.task_id, tag_id)
    print(f"OK: removed tag '{args.tag}' from {_short_id(args.task_id)}")


def cmd_tag_rm(client, args):
    if not args.yes and not client.dry_run:
        raise HabiticaError(
            f"Deleting tag {args.id} removes it from ALL tasks. Re-run with --yes."
        )
    data = client.delete_tag(args.id)
    if print_dry_run(data):
        return
    print(f"OK: deleted tag {args.id}")


# --------------------------------------------------------------------------
# argument parser
# --------------------------------------------------------------------------

def _add_runtime_args(parser, *, include_limit=False, suppress_defaults=False):
    default = argparse.SUPPRESS if suppress_defaults else None
    bool_default = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument("--json", action="store_true", default=bool_default,
                        help="output raw JSON data")
    parser.add_argument("--dry-run", action="store_true", default=bool_default,
                        help="print the request that would be sent, then exit")
    parser.add_argument("--app-name", default=default,
                        help="override the x-client app name")
    parser.add_argument("--base-url", default=default,
                        help="override the API base URL")
    parser.add_argument("--timeout", type=int, default=default,
                        help="request timeout in seconds")
    if include_limit:
        parser.add_argument("--limit", type=int,
                            default=argparse.SUPPRESS if suppress_defaults else DEFAULT_LIMIT,
                            help=f"max rows for `list` (default {DEFAULT_LIMIT})")


def _add_common_subcommand_args(parser, *, include_limit=False):
    _add_runtime_args(parser, include_limit=include_limit, suppress_defaults=True)


def _add_task_field_args(parser, *, require_text):
    parser.add_argument("--text", required=require_text, help="task title")
    parser.add_argument("--notes", help="longer description")
    parser.add_argument("--priority", choices=list(PRIORITY_CHOICES),
                        help="difficulty: 0.1 trivial, 1 easy, 1.5 medium, 2 hard")
    parser.add_argument("--due", metavar="YYYY-MM-DD", help="due date (todos)")
    parser.add_argument("--checklist", nargs="+", metavar="ITEM",
                        help="checklist item texts")
    parser.add_argument("--tag", action="append", metavar="NAME",
                        help="tag name (repeatable); resolved to an id")
    parser.add_argument("--create-tags", action="store_true",
                        help="create --tag names that don't exist yet")
    parser.add_argument("--frequency", choices=["daily", "weekly", "monthly", "yearly"],
                        help="daily recurrence frequency")
    parser.add_argument("--every", type=int, metavar="N", help="everyX interval")
    parser.add_argument("--repeat", nargs="+", choices=list(REPEAT_DAYS),
                        metavar="DAY", help="weekly repeat days: su m t w th f s")
    parser.add_argument("--start-date", metavar="YYYY-MM-DD", help="daily start date")
    parser.add_argument("--remind", action="append", metavar="HH:MM",
                        help="reminder time (repeatable); best-effort")


def build_parser():
    p = argparse.ArgumentParser(
        prog="habitica.py",
        description="Manage a Habitica account (todos, habits, dailies, "
                    "rewards, checklists, tags, stats).",
    )
    _add_runtime_args(p, include_limit=True)

    sub = p.add_subparsers(dest="command", required=True)

    stats = sub.add_parser("stats", help="show your level, HP, XP, gold")
    _add_common_subcommand_args(stats)
    stats.set_defaults(func=cmd_stats)

    whoami = sub.add_parser("whoami", help="alias for stats")
    _add_common_subcommand_args(whoami)
    whoami.set_defaults(func=cmd_stats)

    lst = sub.add_parser("list", help="list tasks")
    _add_common_subcommand_args(lst, include_limit=True)
    lst.add_argument("--type", help="habits | dailys | todos | rewards | completedTodos")
    lst.add_argument("--tag", metavar="NAME", help="only tasks with this tag")
    lst.add_argument("--show-tags", action="store_true", help="render tag names")
    lst.set_defaults(func=cmd_list)

    get = sub.add_parser("get", help="show one task by id")
    _add_common_subcommand_args(get)
    get.add_argument("id")
    get.set_defaults(func=cmd_get)

    add = sub.add_parser("add", help="create a task")
    _add_common_subcommand_args(add)
    add.add_argument("--type", required=True, choices=list(VALID_TASK_TYPES))
    _add_task_field_args(add, require_text=True)
    add.set_defaults(func=cmd_add)

    upd = sub.add_parser("update", help="update a task")
    _add_common_subcommand_args(upd)
    upd.add_argument("id")
    _add_task_field_args(upd, require_text=False)
    upd.set_defaults(func=cmd_update)

    for name, fn, helptext in (
        ("done", cmd_done, "complete a task (score up)"),
        ("up", cmd_up, "score a task up"),
        ("down", cmd_down, "score a task down (un-complete/penalize)"),
    ):
        sp = sub.add_parser(name, help=helptext)
        _add_common_subcommand_args(sp)
        sp.add_argument("id")
        sp.add_argument("--yes", action="store_true", help="confirm guarded scoring")
        sp.set_defaults(func=fn)

    rm = sub.add_parser("rm", help="delete a task")
    _add_common_subcommand_args(rm)
    rm.add_argument("id")
    rm.add_argument("--yes", action="store_true", help="confirm deletion")
    rm.set_defaults(func=cmd_rm)

    ca = sub.add_parser("checklist-add", help="add a checklist item")
    _add_common_subcommand_args(ca)
    ca.add_argument("task_id")
    ca.add_argument("--text", required=True)
    ca.set_defaults(func=cmd_checklist_add)

    cc = sub.add_parser("checklist-check", help="toggle a checklist item")
    _add_common_subcommand_args(cc)
    cc.add_argument("task_id")
    cc.add_argument("item_id")
    cc.set_defaults(func=cmd_checklist_check)

    cu = sub.add_parser("checklist-update", help="edit a checklist item's text")
    _add_common_subcommand_args(cu)
    cu.add_argument("task_id")
    cu.add_argument("item_id")
    cu.add_argument("--text", required=True)
    cu.set_defaults(func=cmd_checklist_update)

    cr = sub.add_parser("checklist-rm", help="delete a checklist item")
    _add_common_subcommand_args(cr)
    cr.add_argument("task_id")
    cr.add_argument("item_id")
    cr.add_argument("--yes", action="store_true", help="confirm deletion")
    cr.set_defaults(func=cmd_checklist_rm)

    tags = sub.add_parser("tags", help="list tags")
    _add_common_subcommand_args(tags)
    tags.set_defaults(func=cmd_tags)

    ta = sub.add_parser("tag-add", help="create a tag")
    _add_common_subcommand_args(ta)
    ta.add_argument("--name", required=True)
    ta.set_defaults(func=cmd_tag_add)

    tas = sub.add_parser("tag-assign", help="assign a tag to a task")
    _add_common_subcommand_args(tas)
    tas.add_argument("task_id")
    tas.add_argument("--tag", required=True, metavar="NAME")
    tas.add_argument("--create-tags", action="store_true",
                     help="create the tag if it doesn't exist")
    tas.set_defaults(func=cmd_tag_assign)

    tu = sub.add_parser("tag-unassign", help="remove a tag from a task")
    _add_common_subcommand_args(tu)
    tu.add_argument("task_id")
    tu.add_argument("--tag", required=True, metavar="NAME")
    tu.set_defaults(func=cmd_tag_unassign)

    tr = sub.add_parser("tag-rm", help="delete a tag (removes it from all tasks)")
    _add_common_subcommand_args(tr)
    tr.add_argument("id")
    tr.add_argument("--yes", action="store_true", help="confirm deletion")
    tr.set_defaults(func=cmd_tag_rm)

    return p


def _preflight_guards(args):
    if args.dry_run:
        return
    if args.command == "rm" and not args.yes:
        raise HabiticaError(
            f"Deleting task {args.id} is permanent. Re-run with --yes to confirm."
        )
    if args.command == "checklist-rm" and not args.yes:
        raise HabiticaError(
            f"Deleting checklist item {args.item_id} is permanent. Re-run with --yes."
        )
    if args.command == "tag-rm" and not args.yes:
        raise HabiticaError(
            f"Deleting tag {args.id} removes it from ALL tasks. Re-run with --yes."
        )


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        _preflight_guards(args)
        client = HabiticaClient(
            app_name=args.app_name,
            base=args.base_url or "https://habitica.com/api/v3",
            timeout=args.timeout or 30,
            dry_run=args.dry_run,
            allow_missing_creds=args.dry_run,
        )
        args.func(client, args)
        return 0
    except HabiticaAuthError as exc:
        print(exc.detailed() if exc.status else str(exc), file=sys.stderr)
        return 2
    except HabiticaError as exc:
        print(f"Error: {exc.detailed()}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
