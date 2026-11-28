from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import types
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = (
    PROJECT_ROOT / "roles/web-app-pgadmin/files/python/reconcile_oauth2_roles.py"
)


def load_script() -> object:
    spec = importlib.util.spec_from_file_location("reconcile_oauth2_roles", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.matched = []

    def filter_by(self, **criteria):
        self.matched = [
            row
            for row in self.rows
            if all(getattr(row, key) == value for key, value in criteria.items())
        ]
        return self

    def first(self):
        return self.matched[0] if self.matched else None

    def one(self):
        assert len(self.matched) == 1
        return self.matched[0]

    def all(self):
        return list(self.matched)


class FakeBackend:
    def __init__(self, users):
        self.administrator = types.SimpleNamespace(id=1, name="Administrator")
        self.regular = types.SimpleNamespace(id=2, name="User")
        self.users = users
        self.created = []
        self.commits = 0
        self.create_error = ""

    def modules(self) -> dict:
        roles = [self.administrator, self.regular]
        session = types.SimpleNamespace(commit=self._commit)
        entries = {
            "config": {"APP_NAME": "pgAdmin 4"},
            "pgadmin": {"create_app": self._create_app},
            "pgadmin.model": {
                "Role": types.SimpleNamespace(query=FakeQuery(roles)),
                "User": types.SimpleNamespace(query=FakeQuery(self.users)),
                "db": types.SimpleNamespace(session=session),
            },
            "pgadmin.tools": {},
            "pgadmin.tools.user_management": {"create_user": self._create_user},
            "pgadmin.utils": {},
            "pgadmin.utils.constants": {"OAUTH2": "oauth2"},
        }
        out = {}
        for name, attrs in entries.items():
            module = types.ModuleType(name)
            for attr, value in attrs.items():
                setattr(module, attr, value)
            out[name] = module
        return out

    def _create_app(self, name):
        return types.SimpleNamespace(test_request_context=contextlib.nullcontext)

    def _create_user(self, data):
        if self.create_error:
            return False, self.create_error
        self.created.append(data)
        role = (
            self.administrator
            if data["role"] == self.administrator.id
            else self.regular
        )
        self.users.append(
            account(data["username"], data["auth_source"], [role], email=data["email"])
        )
        return True, ""

    def _commit(self):
        self.commits += 1


def account(username, auth_source, roles, email="") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        username=username, auth_source=auth_source, roles=roles, email=email
    )


class TestReconcileOauth2Roles(unittest.TestCase):
    def run_script(self, backend: FakeBackend, members: list) -> list:
        module = load_script()
        with patch.dict("sys.modules", backend.modules()):
            return module.converge(members)

    def test_a_member_without_an_account_is_created_as_administrator(self) -> None:
        backend = FakeBackend(users=[])
        changes = self.run_script(
            backend, [{"username": "alice", "email": "alice@example.org"}]
        )
        self.assertEqual(changes, ["alice=Administrator"])
        self.assertEqual(backend.created[0]["auth_source"], "oauth2")
        self.assertEqual(backend.created[0]["role"], backend.administrator.id)

    def test_a_member_without_an_email_is_not_pre_provisioned(self) -> None:
        backend = FakeBackend(users=[])
        self.assertEqual(
            self.run_script(backend, [{"username": "alice", "email": ""}]), []
        )
        self.assertEqual(backend.created, [])

    def test_an_existing_user_member_is_promoted(self) -> None:
        backend = FakeBackend(users=[])
        backend.users.append(account("alice", "oauth2", [backend.regular]))
        changes = self.run_script(
            backend, [{"username": "alice", "email": "alice@example.org"}]
        )
        self.assertEqual(changes, ["alice=Administrator"])
        self.assertEqual(backend.users[0].roles, [backend.administrator])

    def test_a_non_member_administrator_is_demoted(self) -> None:
        backend = FakeBackend(users=[])
        backend.users.append(account("mallory", "oauth2", [backend.administrator]))
        self.assertEqual(self.run_script(backend, []), ["mallory=User"])
        self.assertEqual(backend.users[0].roles, [backend.regular])

    def test_the_internal_default_administrator_is_left_alone(self) -> None:
        backend = FakeBackend(users=[])
        internal = account("admin@example.org", "internal", [backend.administrator])
        backend.users.append(internal)
        self.assertEqual(self.run_script(backend, []), [])
        self.assertEqual(internal.roles, [backend.administrator])

    def test_a_converged_directory_writes_nothing(self) -> None:
        backend = FakeBackend(users=[])
        backend.users.append(account("alice", "oauth2", [backend.administrator]))
        backend.users.append(account("bob", "oauth2", [backend.regular]))
        changes = self.run_script(
            backend, [{"username": "alice", "email": "alice@example.org"}]
        )
        self.assertEqual(changes, [])
        self.assertEqual(backend.created, [])

    def test_a_member_without_a_username_is_ignored(self) -> None:
        backend = FakeBackend(users=[])
        changes = self.run_script(backend, [{"username": "", "email": "x@example.org"}])
        self.assertEqual(changes, [])
        self.assertEqual(backend.created, [])

    def test_a_demotion_is_committed(self) -> None:
        backend = FakeBackend(users=[])
        backend.users.append(account("mallory", "oauth2", [backend.administrator]))
        self.run_script(backend, [])
        self.assertEqual(backend.commits, 1)

    def test_an_internal_account_named_like_a_member_still_gets_an_oauth2_account(
        self,
    ) -> None:
        backend = FakeBackend(users=[])
        backend.users.append(account("alice", "internal", [backend.regular]))
        changes = self.run_script(
            backend, [{"username": "alice", "email": "alice@example.org"}]
        )
        self.assertEqual(changes, ["alice=Administrator"])
        self.assertEqual(backend.users[0].roles, [backend.regular])

    def test_a_failed_account_creation_stops_the_run(self) -> None:
        backend = FakeBackend(users=[])
        backend.create_error = "email taken"
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            self.run_script(
                backend, [{"username": "alice", "email": "alice@example.org"}]
            )
        self.assertEqual(raised.exception.code, 1)
        self.assertIn(
            "[FAIL] creating the OAuth2 account alice failed: email taken",
            stderr.getvalue(),
        )
        self.assertEqual(backend.commits, 0)

    def run_main(self, backend: FakeBackend, env: dict) -> str:
        module = load_script()
        stdout = io.StringIO()
        with (
            patch.dict("sys.modules", backend.modules()),
            patch.dict("os.environ", env, clear=True),
            contextlib.redirect_stdout(stdout),
        ):
            module.main()
        return stdout.getvalue()

    def test_main_fails_without_the_member_list(self) -> None:
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            self.run_main(FakeBackend(users=[]), {})
        self.assertEqual(raised.exception.code, 1)
        self.assertIn(
            "[FAIL] PGADMIN_RBAC_ADMINISTRATORS is not set.", stderr.getvalue()
        )

    def test_main_reports_every_written_role(self) -> None:
        backend = FakeBackend(users=[])
        backend.users.append(account("mallory", "oauth2", [backend.administrator]))
        members = [{"username": "alice", "email": "alice@example.org"}]
        output = self.run_main(
            backend, {"PGADMIN_RBAC_ADMINISTRATORS": json.dumps(members)}
        )
        self.assertEqual(output, "CHANGED alice=Administrator\nCHANGED mallory=User\n")

    def test_main_reports_a_converged_directory(self) -> None:
        backend = FakeBackend(users=[])
        output = self.run_main(backend, {"PGADMIN_RBAC_ADMINISTRATORS": "[]"})
        self.assertEqual(output, "UNCHANGED\n")


if __name__ == "__main__":
    unittest.main()
