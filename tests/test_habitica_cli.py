import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "habitica" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import habitica  # noqa: E402
import habitica_client as hc  # noqa: E402


@contextlib.contextmanager
def isolated_env(**updates):
    old = os.environ.copy()
    os.environ.clear()
    os.environ.update(updates)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def run_cli(argv):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = habitica.main(argv)
    return code, out.getvalue(), err.getvalue()


class HabiticaCliTests(unittest.TestCase):
    def test_global_flags_work_after_subcommand(self):
        code, out, err = run_cli(["list", "--limit", "10", "--dry-run"])

        self.assertEqual(code, 0, err)
        self.assertIn("DRY-RUN GET", out)
        self.assertIn("/tasks/user", out)

    def test_reminders_include_start_date_and_time(self):
        code, out, err = run_cli([
            "add", "--dry-run",
            "--type", "todo",
            "--text", "demo",
            "--due", "2026-06-01",
            "--remind", "07:30",
        ])

        self.assertEqual(code, 0, err)
        self.assertIn('"startDate": "2026-06-01T07:30:00', out)
        self.assertIn('"time": "2026-06-01T07:30:00', out)

    def test_invalid_date_and_time_are_clean_errors(self):
        code, _out, err = run_cli([
            "add", "--dry-run", "--type", "todo", "--text", "demo",
            "--due", "2026-99-99",
        ])
        self.assertEqual(code, 1)
        self.assertIn("Expected date as YYYY-MM-DD", err)
        self.assertNotIn("Traceback", err)

        code, _out, err = run_cli([
            "add", "--dry-run", "--type", "todo", "--text", "demo",
            "--remind", "99:00",
        ])
        self.assertEqual(code, 1)
        self.assertIn("Expected time as HH:MM", err)
        self.assertNotIn("Traceback", err)

    def test_dates_can_use_habitica_timezone_offset(self):
        self.assertEqual(
            hc.iso_date("2026-06-01", timezone_offset=300),
            "2026-06-01T00:00:00-05:00",
        )
        self.assertEqual(
            hc.iso_datetime("2026-06-01", "07:30", timezone_offset=-120),
            "2026-06-01T07:30:00+02:00",
        )

    def test_authenticated_write_uses_account_timezone_offset(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen.append(("GET", self.path, None))
                self._send({
                    "success": True,
                    "data": {"preferences": {"timezoneOffset": 300}},
                })

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                seen.append(("POST", self.path, body))
                self._send({
                    "success": True,
                    "data": {"id": "task-id", "type": "todo", "text": body["text"]},
                })

            def _send(self, payload):
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with isolated_env(HABITICA_USER_ID="user", HABITICA_API_TOKEN="token"):
                code, _out, err = run_cli([
                    "add",
                    "--base-url", f"http://127.0.0.1:{server.server_port}",
                    "--type", "todo",
                    "--text", "demo",
                    "--due", "2026-06-01",
                ])
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0, err)
        self.assertEqual(seen[0][0], "GET")
        self.assertEqual(seen[0][1], "/user?userFields=preferences.timezoneOffset")
        self.assertEqual(seen[1][2]["date"], "2026-06-01T00:00:00-05:00")

    def test_update_checklist_refuses_whole_list_replacement(self):
        code, out, err = run_cli([
            "update", "task-id", "--checklist", "a", "b", "--dry-run",
        ])

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("would replace the whole checklist", err)

    def test_delete_guard_runs_before_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_creds = str(Path(tmp) / "missing")
            with isolated_env(HABITICA_CREDENTIALS=missing_creds):
                code, out, err = run_cli(["rm", "task-id"])

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("Re-run with --yes", err)
        self.assertNotIn("credentials not found", err.lower())

    def test_dry_run_direct_client_allows_missing_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_creds = str(Path(tmp) / "missing")
            with isolated_env(HABITICA_CREDENTIALS=missing_creds):
                client = hc.HabiticaClient(dry_run=True)
                planned = client.get_user()

        self.assertIn("DRY-RUN GET", repr(planned))
        self.assertNotIn("HABITICA_API_TOKEN", repr(planned))

    def test_dry_run_does_not_print_token(self):
        with isolated_env(HABITICA_USER_ID="user", HABITICA_API_TOKEN="secret-token"):
            client = hc.HabiticaClient(dry_run=True)
            planned = client.delete_task("abc")

        self.assertNotIn("secret-token", repr(planned))

    @unittest.skipUnless(os.name == "posix", "POSIX permissions only")
    def test_credentials_file_must_not_be_group_or_world_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "credentials"
            path.write_text(
                "HABITICA_USER_ID=user\nHABITICA_API_TOKEN=token\n",
                encoding="utf-8",
            )
            path.chmod(0o644)
            with isolated_env(HABITICA_CREDENTIALS=str(path)):
                with self.assertRaises(hc.HabiticaAuthError) as raised:
                    hc.load_credentials()

        self.assertIn("chmod 600", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
