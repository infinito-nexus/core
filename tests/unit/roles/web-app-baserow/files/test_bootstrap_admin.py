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

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-baserow/files/bootstrap_admin.py"

DEFAULT_ENV = {
    "BOOTSTRAP_ADMIN_USERNAME": "alice",
    "BOOTSTRAP_ADMIN_EMAIL": "alice@example.com",
    "BOOTSTRAP_ADMIN_PASSWORD": "s3cret",
}


def _fake_django_modules(
    user_cls: MagicMock, profile_cls: MagicMock
) -> dict[str, ModuleType]:
    contrib_auth = ModuleType("django.contrib.auth")
    contrib_auth.get_user_model = MagicMock(return_value=user_cls)

    contrib = ModuleType("django.contrib")
    contrib.auth = contrib_auth

    django = ModuleType("django")
    django.contrib = contrib

    baserow_core_models = ModuleType("baserow.core.models")
    baserow_core_models.UserProfile = profile_cls

    baserow_core = ModuleType("baserow.core")
    baserow_core.models = baserow_core_models

    baserow = ModuleType("baserow")
    baserow.core = baserow_core

    return {
        "baserow": baserow,
        "baserow.core": baserow_core,
        "baserow.core.models": baserow_core_models,
        "django": django,
        "django.contrib": contrib,
        "django.contrib.auth": contrib_auth,
    }


class TestBootstrapAdmin(unittest.TestCase):
    def _run(
        self, *, created: bool, env: dict[str, str] | None = None
    ) -> tuple[str, MagicMock, MagicMock, MagicMock, MagicMock]:
        if not SCRIPT_PATH.is_file():
            raise FileNotFoundError(f"bootstrap_admin.py not found at: {SCRIPT_PATH}")

        user_instance = MagicMock(name="user")
        manager = MagicMock(name="objects")
        manager.get_or_create.return_value = (user_instance, created)

        user_cls = MagicMock(name="User")
        user_cls.objects = manager
        profile = MagicMock(name="profile")
        profile.email_verified = False
        profile.completed_onboarding = False
        profile_manager = MagicMock(name="profile_objects")
        profile_manager.get_or_create.return_value = (profile, False)
        profile_cls = MagicMock(name="UserProfile")
        profile_cls.objects = profile_manager

        buf = io.StringIO()
        with (
            patch.dict(os.environ, env if env is not None else DEFAULT_ENV, clear=True),
            patch.dict(sys.modules, _fake_django_modules(user_cls, profile_cls)),
            redirect_stdout(buf),
        ):
            runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

        return buf.getvalue().strip(), user_instance, manager, profile, profile_manager

    def test_creates_new_superuser(self) -> None:
        out, user, manager, profile, profile_manager = self._run(created=True)

        manager.get_or_create.assert_called_once_with(
            username="alice",
            defaults={
                "email": "alice@example.com",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        user.set_password.assert_called_once_with("s3cret")
        user.save.assert_called_once_with()
        profile_manager.get_or_create.assert_called_once_with(user=user)
        profile.save.assert_called_once_with(
            update_fields=["email_verified", "completed_onboarding"]
        )
        self.assertEqual(out, "created")

    def test_skips_password_when_user_exists(self) -> None:
        out, user, manager, profile, profile_manager = self._run(created=False)

        manager.get_or_create.assert_called_once()
        user.set_password.assert_not_called()
        user.save.assert_not_called()
        profile_manager.get_or_create.assert_called_once_with(user=user)
        profile.save.assert_called_once_with(
            update_fields=["email_verified", "completed_onboarding"]
        )
        self.assertEqual(out, "exists")

    def test_missing_env_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            self._run(created=True, env={})


if __name__ == "__main__":
    unittest.main()
