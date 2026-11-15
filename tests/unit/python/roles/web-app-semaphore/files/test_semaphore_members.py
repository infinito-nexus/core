from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest import mock

from utils.cache.files import read_text

from ._semaphore_fake import (
    PYTHON_DIR,
    SUSPENSION_REFUSALS,
    WORKSPACE_ID,
    FakeSemaphore,
)

ALICE = "a1111111-0000-4000-8000-000000000001"
DAVE = "d1111111-0000-4000-8000-000000000004"
ERIN = "e1111111-0000-4000-8000-000000000005"
MEMBERS = (
    (ALICE, "alice", ["Owner"]),
    ("b1111111-0000-4000-8000-000000000002", "bob", ["Viewer"]),
    ("c1111111-0000-4000-8000-000000000003", "carol", ["Billing"]),
    (DAVE, "dave", ["Operator", "Viewer"]),
)
ADMIN_MEMBER = (ERIN, "erin", ["Admin"])
PSYCOPG2_STUB = """import os, time


def _note(line):
    with open(os.environ["STUB_RECORD"], "a", encoding="utf-8") as handle:
        handle.write(line + "\\n")


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        _note(sql.split()[0])
        if sql.startswith("SELECT"):
            time.sleep(30)

    def fetchone(self):
        return ("token",)


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _Cursor()

    def close(self):
        _note("CLOSE")


def connect(**_settings):
    return _Connection()
"""
TERMINATION_HANDLER = "    signal.signal(signal.SIGTERM, _terminate)\n"


def load_members():
    """Returns:
    The module ``files/python/semaphore_members.py``.
    """
    spec = spec_from_file_location(
        "semaphore_members", str(PYTHON_DIR / "semaphore_members.py")
    )
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def roster(*members):
    """Args:
    members: ``(id, username, groups)`` of each member.

    Returns:
        A roster as ``members.py settle`` writes it.
    """
    return {
        "workspace": WORKSPACE_ID,
        "members": [
            {
                "id": member_id,
                "username": username,
                "email": f"{username}@example.org",
                "emailVerified": True,
                "enabled": True,
                "groups": groups,
            }
            for member_id, username, groups in members
        ],
    }


def runners(roles):
    """Args:
    roles: ``{username: project role}``.

    Returns:
        The sorted usernames that may start a task.
    """
    return sorted(name for name, role in roles.items() if role == "task_runner")


class MembersSyncTests(unittest.TestCase):
    def setUp(self):
        self.members = load_members()
        self.api = FakeSemaphore(self.members.SyncError)
        self.project_id = self.api.add_project(f"ws-{WORKSPACE_ID}")["id"]
        self.api.users.append({"id": 2, "username": "store", "admin": False})
        self.api.members[self.project_id][2] = "manager"
        self.roster = roster(*MEMBERS)
        self.log = []

    def sync(self, sync=None, suspended=False):
        before = len(self.api.writes)
        (sync or self.members.sync)(
            self.api,
            WORKSPACE_ID,
            self.project_id,
            self.roster,
            suspended,
            {"store"},
            self.log.append,
        )
        return self.api.writes[before:]

    def roles(self):
        return {
            self.api.username(uid): role
            for uid, role in self.api.members[self.project_id].items()
        }

    def failing_after(self, count):
        call = self.api.call
        state = {"writes": 0}

        def failing(method, path, body=None):
            if method != "GET":
                state["writes"] += 1
                if state["writes"] > count:
                    raise self.members.SyncError(f"{method} {path}: HTTP 502")
            return call(method, path, body)

        return failing

    def test_sync_finishes_after_a_failure_midway(self):
        original = self.api.call
        self.api.call = self.failing_after(3)
        with self.assertRaises(self.members.SyncError):
            self.sync()
        self.api.call = original
        self.assertTrue(self.sync())
        self.assertEqual(
            self.roles(),
            {
                "breakglass-admin": "owner",
                "store": "manager",
                "alice": "task_runner",
                "bob": "guest",
                "dave": "task_runner",
            },
        )
        self.assertEqual(self.sync(), [])

    def test_sync_finishes_after_a_failure_at_each_write(self):
        steps = len(self.sync())
        self.assertGreater(steps, 0)
        expected = self.roles()
        for step in range(steps):
            with self.subTest(step=step):
                self.setUp()
                original = self.api.call
                self.api.call = self.failing_after(step)
                with self.assertRaises(self.members.SyncError):
                    self.sync()
                self.api.call = original
                self.sync()
                self.assertEqual(self.roles(), expected)
                self.assertEqual(self.sync(), [])

    def test_negative_control_a_whole_list_sync_writes_again(self):
        def whole_list(api, workspace, project_id, roster, suspended, keep, log):
            users = {u["username"]: u for u in api.call("GET", "/users")}
            for member, role in self.members.desired_roles(roster, suspended).values():
                user_id = self.members.semaphore_user(api, member, users, log)
                api.call(
                    "POST",
                    f"/project/{project_id}/users",
                    {"user_id": user_id, "role": role},
                )

        for suspended in (False, True):
            with self.subTest(suspended=suspended):
                self.sync(whole_list, suspended)
                self.assertNotEqual(self.sync(whole_list, suspended), [])

    def test_a_suspended_sync_gives_every_mapped_member_guest(self):
        self.roster = roster(*MEMBERS, ADMIN_MEMBER)
        self.sync()
        self.assertEqual(runners(self.roles()), ["alice", "dave", "erin"])
        self.log.clear()
        self.assertTrue(self.sync(suspended=True))
        self.assertEqual(
            self.roles(),
            {
                "breakglass-admin": "owner",
                "store": "manager",
                "alice": "guest",
                "bob": "guest",
                "dave": "guest",
                "erin": "guest",
            },
        )
        self.assertEqual(
            self.log,
            [
                f"semaphore workspace={WORKSPACE_ID} user={member} role=guest"
                for member in (ALICE, DAVE, ERIN)
            ],
        )
        self.assertEqual(self.sync(suspended=True), [])
        self.sync(suspended=False)
        self.assertEqual(runners(self.roles()), ["alice", "dave", "erin"])
        self.assertEqual(self.roles()["bob"], "guest")
        self.assertNotIn("carol", self.roles())

    def test_negative_control_a_sync_that_drops_the_flag_keeps_task_runner(self):
        def unsuspended(api, workspace, project_id, roster, suspended, keep, log):
            self.members.sync(api, workspace, project_id, roster, False, keep, log)

        self.roster = roster(*MEMBERS, ADMIN_MEMBER)
        self.sync(unsuspended, suspended=True)
        self.assertEqual(runners(self.roles()), ["alice", "dave", "erin"])

    def test_remove_takes_only_the_leaving_member_out(self):
        self.sync()
        self.members.remove_role(
            self.api, WORKSPACE_ID, self.project_id, "bob", {"store"}, lambda line: None
        )
        self.assertNotIn("bob", self.roles())
        self.assertIn("alice", self.roles())
        before = len(self.api.writes)
        for username in ("store", "breakglass-admin", None):
            self.members.remove_role(
                self.api,
                WORKSPACE_ID,
                self.project_id,
                username,
                {"store"},
                lambda line: None,
            )
        self.assertEqual(self.api.writes[before:], [])


class MembersMainTests(unittest.TestCase):
    def setUp(self):
        self.members = load_members()
        self.api = FakeSemaphore(self.members.SyncError)
        self.project_id = self.api.add_project(f"ws-{WORKSPACE_ID}")["id"]
        self.api.users.append({"id": 2, "username": "store", "admin": False})
        self.api.members[self.project_id][2] = "manager"
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.roster_file = Path(scratch.name) / "roster.json"
        self.roster_file.write_text(json.dumps(roster(MEMBERS[0])), encoding="utf-8")
        self.connections = []
        self.members.connect = self.connect
        self.members.mint = lambda connection, env: "token"
        self.members.revoke = lambda connection, token: None
        self.members.workspace_project = lambda connection, workspace: self.project_id
        self.members.Api = lambda root, token: self.api

    def connect(self, env):
        self.connections.append(env["WORKSPACE"])
        return mock.Mock()

    def main(self, suspended):
        env = {
            "WORKSPACE": WORKSPACE_ID,
            "WORKSPACE_SUSPENDED": suspended,
            "SEMAPHORE_API_URL": "http://127.0.0.1:3000/api",
            "SEMAPHORE_STORE_USERNAME": "store",
        }
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.members.main(
                ["sync", str(self.roster_file)],
                {k: v for k, v in env.items() if v is not None},
            )
        return code, out.getvalue(), err.getvalue()

    def test_main_refuses_a_missing_or_malformed_flag_before_any_call(self):
        for value, _ in SUSPENSION_REFUSALS:
            with self.subTest(value=value):
                code, _, err = self.main(value)
                self.assertEqual(code, 2)
                self.assertIn("WORKSPACE_SUSPENDED is missing or malformed", err)
                self.assertEqual(self.connections, [])
                self.assertEqual(self.api.writes, [])

    def test_main_hands_the_flag_to_the_sync(self):
        cases = (("false", "task_runner"), ("true", "guest"), ("false", "task_runner"))
        for value, role in cases:
            with self.subTest(value=value):
                code, out, err = self.main(value)
                self.assertEqual(code, 0, err)
                self.assertIn(
                    f"semaphore workspace={WORKSPACE_ID} user={ALICE} role={role}",
                    out.splitlines(),
                )
        self.assertEqual(self.connections, [WORKSPACE_ID] * 3)


class MembersTerminationTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        (self.root / "psycopg2.py").write_text(PSYCOPG2_STUB, encoding="utf-8")
        self.record = self.root / "record"

    def stopped_run(self, script):
        """Args:
        script: the semaphore_members.py to run.

        Returns:
            ``(exit code, statements)`` of a ``remove`` stopped by SIGTERM
            while it waits on the database after the token was minted.
        """
        env = {
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(self.root),
            "STUB_RECORD": str(self.record),
            "WORKSPACE": WORKSPACE_ID,
            "SEMAPHORE_API_URL": "http://127.0.0.1:9/api",
            "SEMAPHORE_ADMIN_USERNAME": "admin",
            "SEMAPHORE_API_TOKEN_NAME": "members",
            "SEMAPHORE_STORE_USERNAME": "store",
            **dict.fromkeys(
                (
                    "SEMAPHORE_DB_HOST",
                    "SEMAPHORE_DB_PORT",
                    "SEMAPHORE_DB",
                    "SEMAPHORE_DB_USER",
                    "SEMAPHORE_DB_PASS",
                ),
                "unused",
            ),
        }
        process = subprocess.Popen(
            [sys.executable, str(script), "remove"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(process.kill)
        deadline = time.monotonic() + 10
        while "SELECT" not in self.statements():
            self.assertLess(
                time.monotonic(), deadline, "the run never reached the database wait"
            )
            time.sleep(0.05)
        process.send_signal(signal.SIGTERM)
        return process.wait(timeout=10), self.statements()

    def statements(self):
        """Returns:
        The first word of every statement the stub recorded, and CLOSE.
        """
        if not self.record.exists():
            return []
        return self.record.read_text(encoding="utf-8").split()  # nocheck: cache-read

    def test_a_stopped_task_revokes_its_admin_token(self):
        code, statements = self.stopped_run(PYTHON_DIR / "semaphore_members.py")
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertEqual(statements, ["INSERT", "SELECT", "DELETE", "CLOSE"])

    def test_negative_control_without_the_handler_the_token_stays(self):
        source = read_text(str(PYTHON_DIR / "semaphore_members.py"))
        self.assertIn(TERMINATION_HANDLER, source)
        script = self.root / "semaphore_members.py"
        script.write_text(source.replace(TERMINATION_HANDLER, ""), encoding="utf-8")
        code, statements = self.stopped_run(script)
        self.assertEqual(code, -signal.SIGTERM)
        self.assertEqual(statements, ["INSERT", "SELECT"])


if __name__ == "__main__":
    unittest.main()
