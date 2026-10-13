from __future__ import annotations

import importlib.util
import types
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-pgadmin/files/python/administrator.py"
EMAIL = "administrator@example.org"
PASSWORD = "p$ssw0rd-from-the-users-spot"


def load_script() -> object:
    spec = importlib.util.spec_from_file_location("administrator", SCRIPT_PATH)
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


class FakeBackend:
    def __init__(self, user=None):
        self.admin = types.SimpleNamespace(id=1, name="Administrator")
        self.user = user
        self.created = []
        self.commits = 0

    def modules(self) -> dict:
        session = types.SimpleNamespace(commit=self._commit)
        entries = {
            "flask_security": {},
            "flask_security.utils": {
                "hash_password": lambda plain: f"hashed-{plain}",
                "verify_password": lambda plain, hashed: hashed == f"hashed-{plain}",
            },
            "pgadmin": {},
            "pgadmin.model": {
                "Role": types.SimpleNamespace(query=FakeQuery([self.admin])),
                "User": types.SimpleNamespace(
                    query=FakeQuery([self.user] if self.user else [])
                ),
                "db": types.SimpleNamespace(session=session),
            },
            "pgadmin.tools": {},
            "pgadmin.tools.user_management": {
                "create_user": self._create_user,
                "normalise_password": lambda plain: plain,
            },
            "pgadmin.utils": {},
            "pgadmin.utils.constants": {"INTERNAL": "internal"},
        }
        out = {}
        for name, attrs in entries.items():
            module = types.ModuleType(name)
            for attr, value in attrs.items():
                setattr(module, attr, value)
            out[name] = module
        return out

    def _create_user(self, data):
        self.created.append(data)
        return True, ""

    def _commit(self):
        self.commits += 1


def account(**overrides) -> types.SimpleNamespace:
    fields = {
        "email": EMAIL,
        "auth_source": "internal",
        "password": f"hashed-{PASSWORD}",
        "active": True,
        "locked": False,
        "login_attempts": 0,
        "roles": [],
    }
    fields.update(overrides)
    return types.SimpleNamespace(**fields)


class TestConvergeAdministrator(unittest.TestCase):
    def run_script(self, backend: FakeBackend) -> str:
        module = load_script()
        with patch.dict("sys.modules", backend.modules()):
            return module.converge(EMAIL, PASSWORD)

    def test_a_missing_administrator_is_created_with_the_spot_password(self) -> None:
        backend = FakeBackend()
        self.assertEqual(self.run_script(backend), "changed")
        self.assertEqual(backend.created[0]["email"], EMAIL)
        self.assertEqual(backend.created[0]["newPassword"], PASSWORD)
        self.assertEqual(backend.created[0]["role"], backend.admin.id)

    def test_a_rotated_password_reaches_the_existing_administrator(self) -> None:
        backend = FakeBackend()
        backend.user = account(password="hashed-an-older-secret", roles=[backend.admin])
        self.assertEqual(self.run_script(backend), "changed")
        self.assertEqual(backend.user.password, f"hashed-{PASSWORD}")
        self.assertEqual(backend.commits, 1)

    def test_a_locked_administrator_without_the_role_is_repaired(self) -> None:
        backend = FakeBackend()
        backend.user = account(locked=True, login_attempts=3, active=False)
        self.assertEqual(self.run_script(backend), "changed")
        self.assertEqual(
            (backend.user.locked, backend.user.login_attempts, backend.user.active),
            (False, 0, True),
        )
        self.assertIn(backend.admin, backend.user.roles)

    def test_a_converged_administrator_is_left_alone(self) -> None:
        backend = FakeBackend()
        backend.user = account(roles=[backend.admin])
        self.assertEqual(self.run_script(backend), "ok")
        self.assertEqual((backend.created, backend.commits), ([], 0))


if __name__ == "__main__":
    unittest.main()
