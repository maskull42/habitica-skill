#!/usr/bin/env python3
"""Stdlib-only client for the Habitica API v3.

No third-party dependencies — uses only the Python standard library so the
skill works on any machine with Python 3.8+ and nothing to ``pip install``.

This module is the single source of truth for talking to Habitica. It is
imported by both the CLI (``habitica.py``) and the optional MCP server
(``mcp/habitica_mcp.py``), so behaviour (auth, the mandatory ``x-client``
header, rate-limit handling, error surfacing) stays identical everywhere.

Docs: https://habitica.com/apidoc/  ·  Usage rules:
https://github.com/HabitRPG/habitica/wiki/API-Usage-Guidelines
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

API_BASE = "https://habitica.com/api/v3"
DEFAULT_APP_NAME = "habitica-claude-skill"
DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 2  # retries on HTTP 429, in addition to the first attempt

# Habitica's task ``type`` query param uses plurals, and "dailys" is a
# long-standing API spelling (see HabitRPG/habitica#10027). We accept the
# friendly spellings and normalise to what the API actually expects.
_TYPE_ALIASES = {
    "habit": "habits",
    "habits": "habits",
    "daily": "dailys",
    "dailies": "dailys",
    "dailys": "dailys",
    "todo": "todos",
    "todos": "todos",
    "reward": "rewards",
    "rewards": "rewards",
    "completedtodos": "completedTodos",
    "completed": "completedTodos",
}
VALID_TASK_TYPES = ("habit", "daily", "todo", "reward")  # for creation


class HabiticaError(Exception):
    """An error returned by Habitica or raised while talking to it."""

    def __init__(self, message, *, status=None, code=None, errors=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.errors = errors or []

    def detailed(self):
        parts = [self.message or "Unknown error"]
        if self.code and self.code not in (self.message or ""):
            parts.append(f"(error: {self.code})")
        if self.status:
            parts.append(f"[HTTP {self.status}]")
        for e in self.errors:
            msg = e.get("message") if isinstance(e, dict) else str(e)
            if msg:
                parts.append(f"\n  - {msg}")
        return " ".join(parts)


class HabiticaAuthError(HabiticaError):
    """Missing or invalid credentials (or the x-client header)."""


SETUP_MESSAGE = (
    "Habitica credentials not found.\n\n"
    "Set them as environment variables (recommended, works everywhere):\n"
    "    export HABITICA_USER_ID=\"your-user-id\"\n"
    "    export HABITICA_API_TOKEN=\"your-api-token\"\n\n"
    "...or create a credentials file at "
    "~/.config/habitica/credentials (chmod 600):\n"
    "    HABITICA_USER_ID=your-user-id\n"
    "    HABITICA_API_TOKEN=your-api-token\n\n"
    "Find both values in Habitica under Settings -> Site Data / API:\n"
    "    https://habitica.com/user/settings/api"
)


def _credentials_file():
    override = os.environ.get("HABITICA_CREDENTIALS")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "habitica" / "credentials"


def _parse_env_file(path):
    """Parse a simple KEY=VALUE file (ignores blanks and # comments)."""
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        values[key.strip()] = val
    return values


def load_credentials():
    """Return (user_id, api_token, app_name), env first then config file.

    Raises HabiticaAuthError with an actionable message if not configured.
    """
    user_id = os.environ.get("HABITICA_USER_ID")
    token = os.environ.get("HABITICA_API_TOKEN")
    app = os.environ.get("HABITICA_APP_NAME") or os.environ.get("HABITICA_CLIENT")

    if not (user_id and token):
        path = _credentials_file()
        if path.is_file():
            data = _parse_env_file(path)
            user_id = user_id or data.get("HABITICA_USER_ID")
            token = token or data.get("HABITICA_API_TOKEN")
            app = app or data.get("HABITICA_APP_NAME") or data.get("HABITICA_CLIENT")

    if not (user_id and token):
        raise HabiticaAuthError(SETUP_MESSAGE)
    return user_id, token, (app or DEFAULT_APP_NAME)


def normalize_type(value):
    """Map a friendly task type to the API's query value (e.g. daily->dailys)."""
    if value is None:
        return None
    key = str(value).strip().lower()
    if key not in _TYPE_ALIASES:
        raise HabiticaError(
            f"Unknown task type {value!r}. Use one of: "
            "habits, dailys, todos, rewards, completedTodos."
        )
    return _TYPE_ALIASES[key]


def _local_tz():
    return _dt.datetime.now().astimezone().tzinfo


def iso_date(value):
    """'YYYY-MM-DD' -> ISO 8601 at local midnight (keeps the calendar date)."""
    d = _dt.datetime.strptime(value, "%Y-%m-%d")
    return d.replace(tzinfo=_local_tz()).isoformat()


def iso_time(value):
    """'HH:MM' -> ISO 8601 today at that local time (used for reminders)."""
    hour, _, minute = value.partition(":")
    now = _dt.datetime.now().astimezone()
    return now.replace(
        hour=int(hour), minute=int(minute or 0), second=0, microsecond=0
    ).isoformat()


def new_uuid():
    """A v4 UUID string (used for caller-supplied ids like reminders)."""
    return str(uuid.uuid4())


class PlannedRequest:
    """Returned instead of sending when the client is in dry-run mode."""

    def __init__(self, method, url, body):
        self.method = method
        self.url = url
        self.body = body

    def __repr__(self):
        out = f"DRY-RUN {self.method} {self.url}"
        if self.body is not None:
            out += "\n" + json.dumps(self.body, indent=2, ensure_ascii=False)
        return out


class HabiticaClient:
    """Thin, dependency-free wrapper over the Habitica v3 REST API."""

    def __init__(
        self,
        user_id=None,
        api_token=None,
        app_name=None,
        base=API_BASE,
        timeout=DEFAULT_TIMEOUT,
        dry_run=False,
        allow_missing_creds=False,
    ):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.dry_run = dry_run

        if user_id and api_token:
            self.user_id, self.api_token = user_id, api_token
            resolved_app = app_name or DEFAULT_APP_NAME
        else:
            try:
                env_user, env_token, env_app = load_credentials()
                self.user_id, self.api_token = env_user, env_token
                resolved_app = app_name or env_app
            except HabiticaAuthError:
                if not allow_missing_creds:
                    raise
                # Placeholders so --dry-run can render without real creds.
                self.user_id = user_id or "<HABITICA_USER_ID>"
                self.api_token = api_token or "<HABITICA_API_TOKEN>"
                resolved_app = app_name or DEFAULT_APP_NAME

        self.app_name = resolved_app
        # x-client format is "<authorUserId>-<appName>". For a personal/open
        # tool we prefix with the running user's own id; it is always present
        # and valid. Omitting x-client is a hard 400 (missingClientHeader) as
        # of ~July 2025 — this is the bug that breaks several third-party tools.
        self.x_client = f"{self.user_id}-{self.app_name}"

    # -- low-level ---------------------------------------------------------

    def _headers(self, send_auth=True, send_client=True):
        headers = {
            "Content-Type": "application/json",
            # A non-default UA avoids WAFs that reject "Python-urllib/x".
            "User-Agent": self.x_client,
        }
        if send_auth:
            headers["x-api-user"] = self.user_id
            headers["x-api-key"] = self.api_token
        if send_client:
            headers["x-client"] = self.x_client
        return headers

    def request(self, method, path, *, body=None, query=None, _send_client=True):
        """Make a request and return the unwrapped ``data`` payload.

        Raises HabiticaError (or HabiticaAuthError) on any failure — never
        returns a partial/empty result silently.
        """
        url = self.base + path
        if query:
            clean_q = {k: v for k, v in query.items() if v is not None}
            if clean_q:
                url += "?" + urllib.parse.urlencode(clean_q)

        if self.dry_run:
            return PlannedRequest(method, url, body)

        data = json.dumps(body).encode("utf-8") if body is not None else None
        attempt = 0
        while True:
            req = urllib.request.Request(
                url, data=data, method=method,
                headers=self._headers(send_client=_send_client),
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    status = getattr(resp, "status", None) or resp.getcode()
                    return self._unwrap(resp.read(), status)
            except urllib.error.HTTPError as exc:
                raw = exc.read()
                if exc.code == 429 and attempt < MAX_RETRIES:
                    time.sleep(self._retry_after(exc.headers))
                    attempt += 1
                    continue
                self._raise_http(raw, exc.code)
            except socket.timeout:
                raise HabiticaError(
                    f"Request to Habitica timed out after {self.timeout}s ({method} {path})."
                )
            except urllib.error.URLError as exc:
                raise HabiticaError(f"Could not reach Habitica: {exc.reason}")

    @staticmethod
    def _retry_after(headers):
        # Retry-After is in seconds and may be fractional; cap the wait.
        raw = headers.get("Retry-After")
        try:
            return min(float(raw), 60.0) if raw else 2.0
        except (TypeError, ValueError):
            return 2.0

    @staticmethod
    def _decode(raw):
        text = raw.decode("utf-8") if raw else ""
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_raw": text}

    def _unwrap(self, raw, status):
        payload = self._decode(raw)
        if isinstance(payload, dict):
            if payload.get("success") is False:
                self._raise_payload(payload, status)
            if "_raw" in payload:
                raise HabiticaError(
                    f"Unexpected non-JSON response (HTTP {status}): "
                    f"{payload['_raw'][:200]}",
                    status=status,
                )
            if "data" in payload:
                return payload["data"]
        return payload

    def _raise_http(self, raw, status):
        payload = self._decode(raw)
        if not isinstance(payload, dict):
            payload = {}
        self._raise_payload(payload, status)

    def _raise_payload(self, payload, status):
        code = payload.get("error")
        message = payload.get("message") or payload.get("_raw") or f"HTTP {status}"
        errors = payload.get("errors")
        # Verified live: bad creds -> 401 "invalid_credentials"; a missing
        # x-client header -> 400 "BadRequest" / "Missing x-client headers."
        # (we always send x-client, so the latter shouldn't happen).
        auth_codes = {
            "NotAuthorized", "missingAuthHeaders",
            "invalidCredentials", "invalid_credentials",
        }
        if status == 401 or code in auth_codes:
            raise HabiticaAuthError(message, status=status, code=code, errors=errors)
        raise HabiticaError(message, status=status, code=code, errors=errors)

    # -- user --------------------------------------------------------------

    def get_user(self):
        return self.request("GET", "/user")

    # -- tasks -------------------------------------------------------------

    def list_tasks(self, task_type=None):
        query = {"type": normalize_type(task_type)} if task_type else None
        return self.request("GET", "/tasks/user", query=query)

    def get_task(self, task_id):
        return self.request("GET", f"/tasks/{urllib.parse.quote(str(task_id))}")

    def create_task(self, **fields):
        body = {k: v for k, v in fields.items() if v is not None}
        return self.request("POST", "/tasks/user", body=body)

    def update_task(self, task_id, **fields):
        body = {k: v for k, v in fields.items() if v is not None}
        return self.request("PUT", f"/tasks/{urllib.parse.quote(str(task_id))}", body=body)

    def score_task(self, task_id, direction):
        if direction not in ("up", "down"):
            raise HabiticaError("direction must be 'up' or 'down'")
        return self.request(
            "POST", f"/tasks/{urllib.parse.quote(str(task_id))}/score/{direction}"
        )

    def delete_task(self, task_id):
        return self.request("DELETE", f"/tasks/{urllib.parse.quote(str(task_id))}")

    # -- checklist ---------------------------------------------------------

    def add_checklist_item(self, task_id, text):
        return self.request(
            "POST", f"/tasks/{urllib.parse.quote(str(task_id))}/checklist",
            body={"text": text},
        )

    def score_checklist_item(self, task_id, item_id):
        return self.request(
            "POST",
            f"/tasks/{urllib.parse.quote(str(task_id))}/checklist/{item_id}/score",
        )

    def update_checklist_item(self, task_id, item_id, text):
        return self.request(
            "PUT",
            f"/tasks/{urllib.parse.quote(str(task_id))}/checklist/{item_id}",
            body={"text": text},
        )

    def delete_checklist_item(self, task_id, item_id):
        return self.request(
            "DELETE",
            f"/tasks/{urllib.parse.quote(str(task_id))}/checklist/{item_id}",
        )

    # -- tags --------------------------------------------------------------

    def list_tags(self):
        return self.request("GET", "/tags")

    def create_tag(self, name):
        return self.request("POST", "/tags", body={"name": name})

    def delete_tag(self, tag_id):
        return self.request("DELETE", f"/tags/{urllib.parse.quote(str(tag_id))}")

    def add_tag_to_task(self, task_id, tag_id):
        return self.request(
            "POST",
            f"/tasks/{urllib.parse.quote(str(task_id))}/tags/{urllib.parse.quote(str(tag_id))}",
        )

    def resolve_tag_id(self, name, *, create_missing=False):
        """Return the id of the tag named ``name`` (case-insensitive).

        If not found: create it when create_missing=True, else raise with the
        list of available tag names.
        """
        tags = self.list_tags() or []
        wanted = name.strip().lower()
        for tag in tags:
            if str(tag.get("name", "")).strip().lower() == wanted:
                return tag.get("id") or tag.get("_id")
        if create_missing:
            created = self.create_tag(name)
            return created.get("id") or created.get("_id")
        available = ", ".join(sorted(t.get("name", "") for t in tags)) or "(none)"
        raise HabiticaError(
            f"No tag named {name!r}. Existing tags: {available}. "
            "Create it with `tag add` or pass --create-tags."
        )
