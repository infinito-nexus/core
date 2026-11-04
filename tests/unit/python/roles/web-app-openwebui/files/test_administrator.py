from __future__ import annotations

import asyncio
import importlib.util
import types
import unittest
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-openwebui/files/python/administrator.py"
EMAIL = "Administrator@Example.org"
PASSWORD = "p$ssw0rd-from-the-users-spot"


def load_script() -> object:
    spec = importlib.util.spec_from_file_location("administrator", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        "os.environ",
        {
            "OPENWEBUI_ADMIN_EMAIL": EMAIL,
            "OPENWEBUI_ADMIN_NAME": "administrator",
            "OPENWEBUI_ADMIN_PASSWORD": PASSWORD,
        },
    ):
        spec.loader.exec_module(module)
    return module


class FakeBackend:
    """Stands in for the open_webui models the script imports in-process."""

    def __init__(self, user=None, hashed=None):
        self.user = user
        self.hashed = hashed
        self.created = []
        self.passwords = []
        self.roles = []

    def modules(self) -> dict:
        users = types.SimpleNamespace(
            get_user_by_email=self._get_user_by_email,
            update_user_role_by_id=self._update_role,
        )
        auths = types.SimpleNamespace(
            insert_new_auth=self._insert_auth,
            authenticate_user=self._authenticate,
            update_user_password_by_id=self._update_password,
        )
        out = {}
        for name, attrs in (
            ("open_webui.models.users", {"Users": users}),
            ("open_webui.models.auths", {"Auths": auths}),
            (
                "open_webui.utils.auth",
                {"get_password_hash": self._hash, "verify_password": self._verify},
            ),
        ):
            module = types.ModuleType(name)
            for attr, value in attrs.items():
                setattr(module, attr, value)
            out[name] = module
        return out

    async def _get_user_by_email(self, email):
        return self.user if self.user and self.user.email == email else None

    async def _insert_auth(self, email, password, name, role):
        self.created.append((email, password, name, role))
        return types.SimpleNamespace(id="created", email=email, role=role)

    async def _authenticate(self, email, verify):
        return self.user if await verify(self.hashed) else None

    async def _update_password(self, user_id, hashed):
        self.passwords.append((user_id, hashed))
        return True

    async def _update_role(self, user_id, role):
        self.roles.append((user_id, role))

    async def _hash(self, password):
        return f"hashed-{password}"

    async def _verify(self, plain, hashed):
        return hashed == f"hashed-{plain}"


class TestConvergeAdministrator(unittest.TestCase):
    def run_script(self, backend: FakeBackend) -> str:
        module = load_script()
        with patch.dict("sys.modules", backend.modules()):
            return asyncio.run(module.converge())

    def test_a_missing_administrator_is_created_with_the_spot_password(self) -> None:
        backend = FakeBackend()
        self.assertEqual(self.run_script(backend), "CHANGED created")
        self.assertEqual(
            backend.created,
            [(EMAIL.lower(), f"hashed-{PASSWORD}", "administrator", "admin")],
        )

    def test_an_account_in_the_state_found_on_the_stack_is_promoted_and_reset(
        self,
    ) -> None:
        user = types.SimpleNamespace(id="u1", email=EMAIL.lower(), role="user")
        backend = FakeBackend(user, hashed="hashed-an-older-password")
        self.assertEqual(self.run_script(backend), "CHANGED password role")
        self.assertEqual(backend.passwords, [("u1", f"hashed-{PASSWORD}")])
        self.assertEqual(backend.roles, [("u1", "admin")])

    def test_a_rotated_password_reaches_an_existing_administrator(self) -> None:
        user = types.SimpleNamespace(id="u1", email=EMAIL.lower(), role="admin")
        backend = FakeBackend(user, hashed="hashed-an-older-password")
        self.assertEqual(self.run_script(backend), "CHANGED password")
        self.assertEqual(backend.roles, [])

    def test_a_converged_administrator_is_left_alone(self) -> None:
        user = types.SimpleNamespace(id="u1", email=EMAIL.lower(), role="admin")
        backend = FakeBackend(user, hashed=f"hashed-{PASSWORD}")
        self.assertEqual(self.run_script(backend), "OK")
        self.assertEqual(
            (backend.created, backend.passwords, backend.roles), ([], [], [])
        )


if __name__ == "__main__":
    unittest.main()
