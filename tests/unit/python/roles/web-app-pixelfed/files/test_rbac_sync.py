import contextlib
import io
import json
import subprocess
import types
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "roles" / "web-app-pixelfed" / "files" / "python" / "rbac_sync.py"
)
ENVIRON = {
    "RBAC_SYNC_CONTAINER_BIN": "/usr/bin/container",
    "RBAC_SYNC_CID": "db1",
    "MYSQL_PWD": "secret",
    "PIXELFED_DB_USER": "pixelfed",
    "PIXELFED_DB_NAME": "pixelfed",
    "PIXELFED_RBAC_KEPT": json.dumps(["administrator"]),
}
PREFIX = [
    "/usr/bin/container",
    "exec",
    "-i",
    "-e",
    "MYSQL_PWD",
    "db1",
    "mariadb",
    "-u",
    "pixelfed",
    "-D",
    "pixelfed",
    "--batch",
    "--raw",
    "--skip-column-names",
]


def load_module():
    module = types.ModuleType("pixelfed_rbac_sync")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


def account(user_id, username, is_admin=0, email=None):
    return {
        "id": user_id,
        "username": username,
        "email": f"{username}@example.org" if email is None else email,
        "is_admin": is_admin,
    }


def member(username, email=None):
    return {
        "username": username,
        "email": f"{username}@example.org" if email is None else email,
        "name": username,
    }


class FakeMariadb:
    def __init__(self, users, mappings, returncode=0):
        self.users = users
        self.mappings = mappings
        self.returncode = returncode
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs["input"]))
        if "FROM users" in kwargs["input"]:
            rows = self.users
        elif "FROM user_oidc_mappings" in kwargs["input"]:
            rows = self.mappings
        else:
            rows = []
        stdout = "".join(json.dumps(row) + "\n" for row in rows)
        return subprocess.CompletedProcess(
            argv, self.returncode, stdout=stdout, stderr="ERROR 1045\n"
        )


class PixelfedRbacPlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = load_module().plan

    def test_a_member_matched_by_username_is_promoted(self):
        result = self.plan([account(1, "Alice")], [], [member("alice", email="")], [])
        self.assertEqual([user["username"] for user in result["promote"]], ["Alice"])

    def test_a_member_matched_by_email_is_promoted(self):
        result = self.plan(
            [account(1, "a.smith", email="Alice@Example.org")],
            [],
            [member("alice")],
            [],
        )
        self.assertEqual([user["username"] for user in result["promote"]], ["a.smith"])

    def test_a_member_matched_by_its_oidc_mapping_is_promoted(self):
        result = self.plan(
            [account(7, "renamed", email="other@example.org")],
            [{"user_id": 7, "oidc_id": "Alice"}],
            [member("alice")],
            [],
        )
        self.assertEqual([user["id"] for user in result["promote"]], [7])

    def test_a_flagged_non_member_is_demoted(self):
        result = self.plan(
            [account(2, "mallory", is_admin=1)], [], [member("alice")], []
        )
        self.assertEqual([user["username"] for user in result["demote"]], ["mallory"])
        self.assertEqual(result["promote"], [])

    def test_the_kept_administrator_is_never_changed(self):
        result = self.plan(
            [account(1, "Administrator", is_admin=1)], [], [], ["administrator"]
        )
        self.assertEqual(result, {"promote": [], "demote": []})

    def test_an_account_without_email_does_not_match_a_member_without_email(self):
        result = self.plan(
            [{"id": 3, "username": "bob", "email": None, "is_admin": 1}],
            [{"user_id": 9, "oidc_id": None}],
            [member("alice", email="")],
            [],
        )
        self.assertEqual([user["username"] for user in result["demote"]], ["bob"])

    def test_a_converged_account_is_left_alone(self):
        result = self.plan(
            [account(1, "alice", is_admin=1), account(2, "biber")],
            [],
            [member("alice")],
            [],
        )
        self.assertEqual(result, {"promote": [], "demote": []})


class PixelfedRbacSyncTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def run_main(self, fake, administrators):
        environ = {**ENVIRON, "RBAC_ADMINISTRATORS": json.dumps(administrators)}
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.mod.main(environ, fake)
        return stdout.getvalue().splitlines()

    def test_members_are_promoted_and_outsiders_demoted_by_id(self):
        fake = FakeMariadb(
            [
                account(4, "alice"),
                account(5, "mallory", is_admin=1),
                account(6, "biber"),
            ],
            [],
        )
        output = self.run_main(fake, [member("alice")])

        self.assertEqual(
            output, ["CHANGED alice admin=true", "CHANGED mallory admin=false"]
        )
        self.assertEqual([argv for argv, _ in fake.calls], [PREFIX, PREFIX, PREFIX])
        self.assertEqual(
            fake.calls[2][1],
            "UPDATE users SET is_admin = 1 WHERE id IN (4);\n"
            "UPDATE users SET is_admin = 0 WHERE id IN (5);",
        )

    def test_member_values_never_reach_the_sql_text(self):
        fake = FakeMariadb([account(4, "alice'); DROP TABLE users; --")], [])
        self.run_main(fake, [member("alice'); DROP TABLE users; --")])

        self.assertNotIn("DROP", fake.calls[2][1])
        self.assertEqual(
            fake.calls[2][1], "UPDATE users SET is_admin = 1 WHERE id IN (4);"
        )

    def test_the_password_travels_by_name_only(self):
        fake = FakeMariadb([account(4, "alice", is_admin=1)], [])
        self.run_main(fake, [member("alice")])

        for argv, _ in fake.calls:
            self.assertNotIn("secret", argv)

    def test_a_converged_site_writes_nothing_and_says_so(self):
        fake = FakeMariadb([account(4, "alice", is_admin=1), account(6, "biber")], [])
        output = self.run_main(fake, [member("alice")])

        self.assertEqual(output, ["UNCHANGED"])
        self.assertEqual(len(fake.calls), 2)

    def test_a_failing_client_fails_the_hook_with_its_exit_code(self):
        fake = FakeMariadb([], [], returncode=1)
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            self.run_main(fake, [])

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("ERROR 1045", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
