from __future__ import annotations

import io
import json
import os
import runpy
import sys
import unittest
from contextlib import redirect_stdout
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from utils.cache.files import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-taiga/files/python/reconcile_superusers.py"


def account(
    username: str,
    *,
    email: str | None = None,
    superuser: bool = False,
    staff: bool | None = None,
    system: bool = False,
) -> SimpleNamespace:
    """Build one Taiga user row.

    Args:
        username: Taiga login of the account.
        email: address of the account, ``<username>@example.org`` when omitted.
        superuser: ``is_superuser`` before the reconcile.
        staff: ``is_staff`` before the reconcile, follows ``superuser`` when omitted.
        system: ``is_system`` of the account.

    Returns:
        A user stand-in whose ``save`` is a mock.
    """
    return SimpleNamespace(
        username=username,
        email=f"{username}@example.org" if email is None else email,
        is_superuser=superuser,
        is_staff=superuser if staff is None else staff,
        is_system=system,
        save=MagicMock(name=f"save_{username}"),
    )


def member(username: str, email: str | None = None) -> dict[str, str]:
    """Build one entry of an ``rbac_members`` list.

    Args:
        username: directory login of the member.
        email: directory address of the member, ``<username>@example.org`` when omitted.

    Returns:
        The ``{username, email, name}`` mapping the RBAC hook receives per member.
    """
    return {
        "username": username,
        "email": f"{username}@example.org" if email is None else email,
        "name": username,
    }


def fake_django(users: list[SimpleNamespace]) -> dict[str, ModuleType]:
    """Build the Django modules the script imports.

    Args:
        users: accounts ``get_user_model().objects.order_by`` yields.

    Returns:
        The ``sys.modules`` entries for ``django`` down to ``django.contrib.auth``.
    """
    user_cls = MagicMock(name="User")
    user_cls.objects.order_by.return_value = users
    contrib_auth = ModuleType("django.contrib.auth")
    contrib_auth.get_user_model = MagicMock(return_value=user_cls)
    contrib = ModuleType("django.contrib")
    contrib.auth = contrib_auth
    django = ModuleType("django")
    django.contrib = contrib
    return {
        "django": django,
        "django.contrib": contrib,
        "django.contrib.auth": contrib_auth,
    }


class TestReconcileSuperusers(unittest.TestCase):
    def _run(
        self,
        users: list[SimpleNamespace],
        administrators: list[dict[str, str]],
        kept: list[str],
    ) -> list[str]:
        env = {
            "TAIGA_RBAC_ADMINISTRATORS": json.dumps(administrators),
            "TAIGA_RBAC_KEPT_SUPERUSERS": json.dumps(kept),
        }
        buf = io.StringIO()
        with (
            patch.dict(os.environ, env, clear=True),
            patch.dict(sys.modules, fake_django(users)),
            redirect_stdout(buf),
        ):
            runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
        return buf.getvalue().splitlines()

    def test_a_member_matched_by_username_is_promoted(self) -> None:
        biber = account("biber", email="unrelated@example.org")
        lines = self._run([biber], [member("Biber", email="other@example.org")], [])

        self.assertTrue(biber.is_superuser)
        self.assertTrue(biber.is_staff)
        biber.save.assert_called_once_with()
        self.assertEqual(lines, ["CHANGED promoted biber"])

    def test_a_member_matched_by_email_is_promoted(self) -> None:
        biber = account("biber")
        lines = self._run(
            [biber], [member("keycloak-name", email=" Biber@Example.org ")], []
        )

        self.assertTrue(biber.is_superuser)
        self.assertEqual(lines, ["CHANGED promoted biber"])

    def test_a_superuser_outside_the_role_group_is_demoted(self) -> None:
        mapache = account("mapache", superuser=True)
        lines = self._run([mapache], [], [])

        self.assertFalse(mapache.is_superuser)
        self.assertFalse(mapache.is_staff)
        mapache.save.assert_called_once_with()
        self.assertEqual(lines, ["CHANGED demoted mapache"])

    def test_a_staff_flag_without_superuser_outside_the_role_group_is_demoted(
        self,
    ) -> None:
        mapache = account("mapache", staff=True)
        lines = self._run([mapache], [], [])

        self.assertFalse(mapache.is_staff)
        self.assertEqual(lines, ["CHANGED demoted mapache"])

    def test_every_changed_account_gets_its_own_line(self) -> None:
        biber = account("biber")
        mapache = account("mapache", superuser=True)
        lines = self._run([biber, mapache], [member("biber")], [])

        self.assertEqual(lines, ["CHANGED promoted biber", "CHANGED demoted mapache"])

    def test_the_bootstrap_superuser_keeps_its_flags_outside_the_role_group(
        self,
    ) -> None:
        administrator = account("administrator", superuser=True)
        lines = self._run([administrator], [], ["Administrator"])

        self.assertTrue(administrator.is_superuser)
        administrator.save.assert_not_called()
        self.assertEqual(lines, ["UNCHANGED"])

    def test_a_system_account_is_left_alone(self) -> None:
        bot = account("taiga-bot", superuser=True, system=True)
        lines = self._run([bot], [], [])

        self.assertTrue(bot.is_superuser)
        bot.save.assert_not_called()
        self.assertEqual(lines, ["UNCHANGED"])

    def test_an_account_without_email_matches_no_member_without_email(self) -> None:
        other = account("other", email="", superuser=True)
        lines = self._run([other], [member("ghost", email="")], [])

        self.assertFalse(other.is_superuser)
        self.assertEqual(lines, ["CHANGED demoted other"])

    def test_converged_flags_report_no_change(self) -> None:
        biber = account("biber", superuser=True)
        mapache = account("mapache")
        lines = self._run([biber, mapache], [member("biber")], [])

        biber.save.assert_not_called()
        mapache.save.assert_not_called()
        self.assertEqual(lines, ["UNCHANGED"])

    def test_a_missing_member_list_stops_the_reconcile(self) -> None:
        with (
            patch.dict(os.environ, {"TAIGA_RBAC_KEPT_SUPERUSERS": "[]"}, clear=True),
            patch.dict(sys.modules, fake_django([])),
            self.assertRaises(KeyError),
        ):
            runpy.run_path(str(SCRIPT_PATH), run_name="__main__")


if __name__ == "__main__":
    unittest.main()
