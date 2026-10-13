from __future__ import annotations

import io
import os
import runpy
import sys
import unittest
from contextlib import redirect_stdout
from types import ModuleType
from unittest.mock import MagicMock, patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-funkwhale/files/python/admin_state.py"

ENV = {"FUNKWHALE_ADMIN_USERNAME": "alice", "FUNKWHALE_ADMIN_PASSWORD": "s3cret"}


def _fake_modules(user: MagicMock | None) -> dict[str, ModuleType]:
    models = ModuleType("funkwhale_api.users.models")
    models.User = MagicMock(name="User")
    models.User.objects.filter.return_value.first.return_value = user
    users = ModuleType("funkwhale_api.users")
    users.models = models
    api = ModuleType("funkwhale_api")
    api.users = users
    return {
        "funkwhale_api": api,
        "funkwhale_api.users": users,
        "funkwhale_api.users.models": models,
    }


def _user(*, active=True, staff=True, superuser=True, password_ok=True) -> MagicMock:
    user = MagicMock(
        name="user", is_active=active, is_staff=staff, is_superuser=superuser
    )
    user.check_password.return_value = password_ok
    return user


class TestAdminState(unittest.TestCase):
    def _run(self, user: MagicMock | None) -> str:
        buf = io.StringIO()
        with (
            patch.dict(os.environ, ENV, clear=True),
            patch.dict(sys.modules, _fake_modules(user)),
            redirect_stdout(buf),
        ):
            runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
        return buf.getvalue().strip()

    def test_reports_a_missing_administrator(self) -> None:
        self.assertEqual(self._run(None), "FUNKWHALE_ADMIN=MISSING")

    def test_reports_ok_for_an_active_superuser_with_the_current_password(self) -> None:
        user = _user()
        self.assertEqual(self._run(user), "FUNKWHALE_ADMIN=OK")
        user.check_password.assert_called_once_with("s3cret")

    def test_reports_drift_on_a_rotated_password(self) -> None:
        self.assertEqual(self._run(_user(password_ok=False)), "FUNKWHALE_ADMIN=DRIFT")

    def test_reports_drift_on_missing_rights_or_an_inactive_account(self) -> None:
        for user in (_user(staff=False), _user(superuser=False), _user(active=False)):
            self.assertEqual(self._run(user), "FUNKWHALE_ADMIN=DRIFT")


if __name__ == "__main__":
    unittest.main()
