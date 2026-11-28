from __future__ import annotations

import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
import unittest.mock as mock
import urllib.parse
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))

import usage

PYTHON_DIR = PROJECT_ROOT / "roles/web-app-keycloak/files/python"
TASKS = PROJECT_ROOT / "roles/web-app-keycloak/tasks/usage.yml"
PLAYBOOK = PROJECT_ROOT / "playbook-usage.yml"
REALM = "example.org"
CLIENT_ID = "usage"
SECRET = "5ec4e7" + "e" * 58
ADMIN = "administrator"
TOKEN = "usage-access-token"
POLL = 0.02


class PlainHTTPS(urllib.request.HTTPHandler):
    https_request = urllib.request.AbstractHTTPHandler.do_request_

    def https_open(self, req):
        return self.do_open(http.client.HTTPConnection, req)


def person(username: str, enabled: bool = True, service: str = "") -> dict:
    """
    Args:
        username: the username.
        enabled: whether the user is enabled.
        service: the client id of a service account, empty for a person.

    Returns:
        A full user representation of Keycloak.
    """
    user = {"id": f"id-{username}", "username": username, "enabled": enabled}
    if service:
        user["serviceAccountClientId"] = service
    return user


class FakeKeycloak:
    """
    Args:
        users: the user representations of the realm.
    """

    def __init__(self, users) -> None:
        self.users = list(users)
        self.calls: list[tuple[str, str]] = []
        self.fail = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": POLL},
            daemon=True,
        )
        self.thread.start()

    @property
    def url(self) -> str:
        return f"https://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                status, payload = fake.answer(
                    self.command, self.path, body, self.headers
                )
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self.serve()

            def do_POST(self) -> None:
                self.serve()

            def log_message(self, *args) -> None:
                return None

        return Handler

    def answer(self, method, raw, body, headers) -> tuple[int, object]:
        url = urllib.parse.urlsplit(raw)
        self.calls.append((method, url.path))
        if self.fail:
            return 503, {"error": "unavailable"}
        if url.path == f"/realms/{REALM}/protocol/openid-connect/token":
            form = dict(urllib.parse.parse_qsl(body.decode()))
            wanted = {
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": SECRET,
            }
            if form != wanted:
                return 401, {"error": "invalid_client"}
            return 200, {"access_token": TOKEN}
        if url.path != f"/admin/realms/{REALM}/users":
            return 404, {}
        if headers.get("Authorization") != f"Bearer {TOKEN}":
            return 401, {}
        query = dict(urllib.parse.parse_qsl(url.query))
        first = int(query.get("first", 0))
        return 200, self.users[first : first + int(query.get("max", 100))]


def request_for(fake: FakeKeycloak | None, result_dir: str, enabled=True) -> dict:
    """
    Args:
        fake: the fake Keycloak, None for a host without one.
        result_dir: where the count is written.
        enabled: the usage client switch.

    Returns:
        The request ``tasks/usage.yml`` puts on stdin.
    """
    return {
        "enabled": enabled,
        "host": "203.0.113.10",
        "url": fake.url if fake else "https://keycloak.invalid",
        "realm": REALM,
        "client_id": CLIENT_ID,
        "secret": SECRET if enabled else "",
        "admin": ADMIN,
        "cafile": "",
        "result_dir": result_dir,
    }


def run_main(request: dict) -> tuple[int, str, str, dict | None]:
    """
    Args:
        request: the stdin request.

    Returns:
        Exit code, stdout, stderr and the written result.
    """
    stdout, stderr = io.StringIO(), io.StringIO()
    opener = usage.opener(PlainHTTPS())
    with (
        mock.patch.object(usage, "tls_opener", lambda cafile: opener),
        redirect_stdout(stdout),
        redirect_stderr(stderr),
    ):
        code = usage.main(["usage.py"], io.StringIO(json.dumps(request)))
    path = Path(request["result_dir"], f"{request['host']}.json")
    if not path.exists():
        return code, stdout.getvalue(), stderr.getvalue(), None
    text = path.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
    return code, stdout.getvalue(), stderr.getvalue(), json.loads(text)


REALM_USERS = [
    person("ada"),
    person("grace"),
    person("linus", enabled=False),
    person("service-account-usage", service="usage"),
    person("service-account-example.org", service="example.org"),
    person(ADMIN),
    *(person(f"member{index:03d}") for index in range(150)),
]
ACTIVE_PEOPLE = 152


class UsageCountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)

    def fake(self, users):
        fake = FakeKeycloak(users)
        self.addCleanup(fake.stop)
        return fake

    def count(self, users) -> tuple[int, dict | None, FakeKeycloak]:
        fake = self.fake(users)
        code, _, stderr, result = run_main(request_for(fake, self.scratch.name))
        self.assertEqual(code, 0, stderr)
        return code, result, fake

    def test_the_count_is_active_people_only(self) -> None:
        _, result, fake = self.count(REALM_USERS)
        self.assertEqual(
            result,
            {"host": "203.0.113.10", "realm": REALM, "active_users": ACTIVE_PEOPLE},
        )
        self.assertEqual(
            [path for _, path in fake.calls].count(f"/admin/realms/{REALM}/users"), 2
        )

    def test_negative_control_a_count_of_every_user_fails(self) -> None:
        with mock.patch.object(usage, "active", lambda user, admin: True):
            _, result, _ = self.count(REALM_USERS)
        self.assertNotEqual(result["active_users"], ACTIVE_PEOPLE)
        self.assertEqual(result["active_users"], len(REALM_USERS))

    def test_each_skipped_kind_is_skipped_on_its_own(self) -> None:
        for name, user in (
            ("disabled", person("linus", enabled=False)),
            ("service account", person("service-account-usage", service="usage")),
            ("master administrator", person(ADMIN.upper())),
        ):
            with self.subTest(name):
                self.assertFalse(usage.active(user, ADMIN))
        self.assertTrue(usage.active(person("ada"), ADMIN))

    def test_a_host_without_the_usage_client_gets_no_call(self) -> None:
        fake = self.fake(REALM_USERS)
        code, _, stderr, result = run_main(
            request_for(fake, self.scratch.name, enabled=False)
        )
        self.assertEqual((code, fake.calls), (0, []), stderr)
        self.assertEqual(
            result, {"host": "203.0.113.10", "realm": REALM, "active_users": None}
        )

    def test_a_failed_count_writes_nothing_and_names_no_secret(self) -> None:
        fake = self.fake(REALM_USERS)
        fake.fail = True
        code, stdout, stderr, result = run_main(request_for(fake, self.scratch.name))
        self.assertEqual((code, result), (1, None))
        self.assertIn("HTTP 503", stderr)
        self.assertNotIn(SECRET, stdout + stderr)

    def test_a_malformed_request_is_refused(self) -> None:
        for name, change in (
            ("extra field", {"extra": "x"}),
            ("host with a slash", {"host": "../escape"}),
            ("plain http origin", {"url": "http://127.0.0.1:1"}),
        ):
            with self.subTest(name):
                request = {**request_for(None, self.scratch.name), **change}
                code, _, stderr, _ = run_main(request)
                self.assertEqual(code, 1)
                self.assertTrue(stderr.startswith("usage.py: "), stderr)


class UsageTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        (self.task,) = [
            t for t in load_yaml_any(str(TASKS)) if "ansible.builtin.command" in t
        ]

    def test_the_tasks_hand_usage_py_its_request_on_stdin_only(self) -> None:
        command = self.task["ansible.builtin.command"]
        self.assertEqual(
            command["argv"],
            [
                "{{ ansible_playbook_python }}",
                "{{ role_path }}/files/python/usage.py",
            ],
        )
        self.assertEqual(command["stdin"], "{{ kc_usage_request | to_json }}")
        self.assertEqual(set(self.task["vars"]["kc_usage_request"]), usage.REQUEST_KEYS)
        self.assertNotIn("environment", self.task)
        self.assertEqual(self.task["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}")

    def test_the_secret_is_read_only_while_the_switch_is_on(self) -> None:
        self.assertEqual(
            self.task["vars"]["kc_usage_request"]["secret"],
            "{{ KEYCLOAK_USAGE_CLIENT_SECRET if KEYCLOAK_USAGE_CLIENT_ENABLED | bool else '' }}",
        )

    def test_the_playbook_runs_only_the_usage_tasks_locally(self) -> None:
        (play,) = load_yaml_any(str(PLAYBOOK))
        self.assertEqual(
            (play["hosts"], play["connection"], play["gather_facts"]),
            ("web-app-keycloak", "local", False),
        )
        include = play["tasks"][-1]["ansible.builtin.include_role"]
        self.assertEqual(include, {"name": "web-app-keycloak", "tasks_from": "usage"})


if __name__ == "__main__":
    unittest.main()
