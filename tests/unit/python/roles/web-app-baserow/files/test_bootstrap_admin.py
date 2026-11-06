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

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-baserow/files/python/bootstrap_admin.py"

DEFAULT_ENV = {
    "BOOTSTRAP_ADMIN_USERNAME": "alice",
    "BOOTSTRAP_ADMIN_EMAIL": "Alice@Example.com",
    "BOOTSTRAP_ADMIN_PASSWORD": "s3cret",
}
EMAIL = "alice@example.com"


def _fake_modules(
    user_cls: MagicMock, profile_cls: MagicMock, settings: MagicMock
) -> dict[str, ModuleType]:
    contrib_auth = ModuleType("django.contrib.auth")
    contrib_auth.get_user_model = MagicMock(return_value=user_cls)

    contrib = ModuleType("django.contrib")
    contrib.auth = contrib_auth

    django = ModuleType("django")
    django.contrib = contrib

    baserow_core_models = ModuleType("baserow.core.models")
    baserow_core_models.UserProfile = profile_cls

    baserow_core_handler = ModuleType("baserow.core.handler")
    baserow_core_handler.CoreHandler = MagicMock(
        return_value=MagicMock(get_settings=MagicMock(return_value=settings))
    )

    baserow_core_user_utils = ModuleType("baserow.core.user.utils")
    baserow_core_user_utils.normalize_email_address = lambda value: (
        value.strip().lower()
    )

    baserow_core_user = ModuleType("baserow.core.user")
    baserow_core_user.utils = baserow_core_user_utils

    baserow_core = ModuleType("baserow.core")
    baserow_core.models = baserow_core_models
    baserow_core.handler = baserow_core_handler
    baserow_core.user = baserow_core_user

    baserow = ModuleType("baserow")
    baserow.core = baserow_core

    return {
        "baserow": baserow,
        "baserow.core": baserow_core,
        "baserow.core.handler": baserow_core_handler,
        "baserow.core.models": baserow_core_models,
        "baserow.core.user": baserow_core_user,
        "baserow.core.user.utils": baserow_core_user_utils,
        "django": django,
        "django.contrib": contrib,
        "django.contrib.auth": contrib_auth,
    }


class TestBootstrapAdmin(unittest.TestCase):
    def _run(
        self,
        *,
        existing: dict[str, MagicMock],
        signup_page: bool,
        verified: bool,
        env: dict[str, str] | None = None,
        superusers: dict[str, MagicMock] | None = None,
    ) -> tuple[str, MagicMock, MagicMock, MagicMock]:
        created_user = MagicMock(name="created_user")
        manager = MagicMock(name="objects")

        def _filter(**lookup: object) -> MagicMock:
            if "username" in lookup:
                match = existing.get(lookup["username"])
            elif lookup.get("is_superuser") is True:
                match = (superusers or {}).get(lookup.get("first_name"))
            else:
                match = None
            query = MagicMock(name="query")
            query.first.return_value = match
            query.order_by.return_value.first.return_value = match
            return query

        manager.filter.side_effect = _filter
        manager.create.return_value = created_user

        user_cls = MagicMock(name="User")
        user_cls.objects = manager
        profile = MagicMock(name="profile")
        profile.email_verified = verified
        profile.completed_onboarding = verified
        profile_cls = MagicMock(name="UserProfile")
        profile_cls.objects.get_or_create.return_value = (profile, False)
        settings = MagicMock(name="settings")
        settings.show_admin_signup_page = signup_page

        buf = io.StringIO()
        with (
            patch.dict(os.environ, env if env is not None else DEFAULT_ENV, clear=True),
            patch.dict(sys.modules, _fake_modules(user_cls, profile_cls, settings)),
            redirect_stdout(buf),
        ):
            runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

        return buf.getvalue().strip(), manager, profile, settings

    def test_creates_the_superuser_under_its_email_address(self) -> None:
        out, manager, profile, settings = self._run(
            existing={}, signup_page=True, verified=False
        )

        manager.create.assert_called_once_with(
            username=EMAIL,
            email=EMAIL,
            first_name="alice",
            is_staff=True,
            is_superuser=True,
        )
        manager.create.return_value.set_password.assert_called_once_with("s3cret")
        profile.save.assert_called_once_with(
            update_fields=["email_verified", "completed_onboarding"]
        )
        self.assertFalse(settings.show_admin_signup_page)
        settings.save.assert_called_once_with(update_fields=["show_admin_signup_page"])
        self.assertEqual(out, "BOOTSTRAP_STATE=changed")

    def test_moves_a_superuser_stored_under_the_username_to_its_email_address(
        self,
    ) -> None:
        legacy = MagicMock(name="legacy", username="alice", email=EMAIL, first_name="")
        out, manager, _profile, _settings = self._run(
            existing={"alice": legacy}, signup_page=False, verified=True
        )

        manager.create.assert_not_called()
        legacy.set_password.assert_not_called()
        self.assertEqual(legacy.username, EMAIL)
        self.assertEqual(legacy.first_name, "alice")
        legacy.save.assert_called_once_with(update_fields=["username", "first_name"])
        self.assertEqual(out, "BOOTSTRAP_STATE=changed")

    def test_converges_a_rotated_password_on_the_existing_superuser(self) -> None:
        current = MagicMock(
            name="current", username=EMAIL, email=EMAIL, first_name="alice"
        )
        current.check_password.return_value = False
        out, manager, _profile, _settings = self._run(
            existing={EMAIL: current}, signup_page=False, verified=True
        )

        manager.create.assert_not_called()
        current.check_password.assert_called_once_with("s3cret")
        current.set_password.assert_called_once_with("s3cret")
        current.save.assert_called_once_with(update_fields=["password"])
        self.assertEqual(out, "BOOTSTRAP_STATE=changed")

    def test_moves_the_superuser_to_a_changed_email_address(self) -> None:
        renamed = MagicMock(
            name="renamed",
            username="alice@old.example",
            email="alice@old.example",
            first_name="alice",
        )
        out, manager, _profile, _settings = self._run(
            existing={},
            signup_page=False,
            verified=True,
            superusers={"alice": renamed},
        )

        manager.filter.assert_any_call(first_name="alice", is_superuser=True)
        manager.create.assert_not_called()
        self.assertEqual(renamed.username, EMAIL)
        self.assertEqual(renamed.email, EMAIL)
        renamed.save.assert_called_once_with(update_fields=["username", "email"])
        self.assertEqual(out, "BOOTSTRAP_STATE=changed")

    def test_promotes_an_adopted_account_to_superuser(self) -> None:
        adopted = MagicMock(
            name="adopted",
            username=EMAIL,
            email=EMAIL,
            first_name="Alice",
            is_staff=False,
            is_superuser=False,
        )
        out, manager, _profile, _settings = self._run(
            existing={EMAIL: adopted}, signup_page=False, verified=True
        )

        manager.create.assert_not_called()
        self.assertTrue(adopted.is_staff)
        self.assertTrue(adopted.is_superuser)
        adopted.save.assert_called_once_with(update_fields=["is_staff", "is_superuser"])
        self.assertEqual(out, "BOOTSTRAP_STATE=changed")

    def test_reports_unchanged_when_everything_converged(self) -> None:
        current = MagicMock(
            name="current", username=EMAIL, email=EMAIL, first_name="alice"
        )
        out, manager, profile, settings = self._run(
            existing={EMAIL: current}, signup_page=False, verified=True
        )

        manager.create.assert_not_called()
        current.set_password.assert_not_called()
        current.save.assert_not_called()
        profile.save.assert_not_called()
        settings.save.assert_not_called()
        self.assertEqual(out, "BOOTSTRAP_STATE=unchanged")

    def test_missing_env_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            self._run(existing={}, signup_page=True, verified=False, env={})


if __name__ == "__main__":
    unittest.main()
