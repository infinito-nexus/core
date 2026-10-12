from __future__ import annotations

import base64
import io
import runpy
import unittest
from contextlib import redirect_stdout
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-bookwyrm/files/python/site_design.py"
THEME_PATH = "css/themes/infinito.scss"
LOGO = base64.b64encode(b"logo-bytes").decode()
ENV = {
    "ADMIN_USERNAME": "administrator",
    "ADMIN_EMAIL": "administrator@example.com",
    "ADMIN_PASSWORD": "s3cret",
    "DESIGN_STATE": "present",
    "SITE_NAME": "BookWyrm",
    "THEME_NAME": "Corporate Design",
    "THEME_PATH": THEME_PATH,
    "LOGO_SMALL": LOGO,
    "LOGO": LOGO,
    "FAVICON": LOGO,
}


class FakeFieldFile:
    def __init__(self, name: str = ""):
        self.name = name
        self.deleted = False

    def __bool__(self) -> bool:
        return bool(self.name)

    def delete(self, save: bool = True) -> None:
        self.deleted = True
        self.name = ""

    def save(self, name: str, content, save: bool = True) -> None:
        self.name = f"logos/{name.rsplit('.', 1)[0]}_ab12cd.{name.rsplit('.', 1)[1]}"


def _site(**overrides) -> SimpleNamespace:
    values = {
        "install_mode": True,
        "name": "BookWyrm",
        "logo_small": FakeFieldFile(),
        "logo": FakeFieldFile(),
        "favicon": FakeFieldFile(),
        "default_theme_id": None,
        "default_theme": None,
        "save": MagicMock(),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _user(**overrides) -> MagicMock:
    user = MagicMock(
        is_superuser=True, is_staff=True, is_active=True, two_factor_auth=False
    )
    user.check_password.return_value = True
    user.groups.values_list.return_value = ["admin", "moderator"]
    for key, value in overrides.items():
        setattr(user, key, value)
    return user


def _modules(user, site, theme) -> tuple[dict[str, ModuleType], MagicMock]:
    models = MagicMock()
    models.User.objects.filter.return_value.first.return_value = user
    models.SiteSettings.get.return_value = site
    models.Theme.objects.filter.return_value.first.return_value = theme
    models.Theme.objects.create.return_value = SimpleNamespace(id=7)

    bookwyrm = ModuleType("bookwyrm")
    bookwyrm.models = models
    bookwyrm.settings = SimpleNamespace(DOMAIN="book.example.com")
    activitypub = ModuleType("bookwyrm.activitypub")
    activitypub.get_representative = MagicMock()

    auth_models = ModuleType("django.contrib.auth.models")
    auth_models.Group = MagicMock()
    files_base = ModuleType("django.core.files.base")
    files_base.ContentFile = lambda data: data

    return (
        {
            "bookwyrm": bookwyrm,
            "bookwyrm.activitypub": activitypub,
            "django": ModuleType("django"),
            "django.contrib": ModuleType("django.contrib"),
            "django.contrib.auth": ModuleType("django.contrib.auth"),
            "django.contrib.auth.models": auth_models,
            "django.core": ModuleType("django.core"),
            "django.core.files": ModuleType("django.core.files"),
            "django.core.files.base": files_base,
        },
        models,
    )


def _run(user, site, theme, **env) -> tuple[str, MagicMock]:
    modules, models = _modules(user, site, theme)
    out = io.StringIO()
    with (
        patch.dict("sys.modules", modules),
        patch.dict("os.environ", {**ENV, **env}),
        redirect_stdout(out),
    ):
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
    return out.getvalue(), models


class TestSiteDesign(unittest.TestCase):
    def test_fresh_instance_gets_administrator_title_logos_and_theme(self):
        site = _site()
        output, models = _run(None, site, None)
        self.assertIn("BOOKWYRM_RESULT=CHANGED", output)
        kwargs = models.User.objects.create_superuser.call_args.kwargs
        self.assertEqual(kwargs["localname"], "administrator")
        self.assertIs(kwargs["two_factor_auth"], False)
        self.assertFalse(site.install_mode)
        self.assertTrue(site.logo_small.name.startswith("logos/infinito-logo-small-"))
        self.assertTrue(site.favicon.name.endswith(".ico"))
        models.Theme.objects.create.assert_called_once_with(
            name="Corporate Design", path=THEME_PATH, loads=True
        )
        self.assertEqual(site.default_theme.id, 7)

    def test_converged_instance_reports_unchanged(self):
        fresh = _site()
        _run(None, fresh, None)
        site = _site(
            install_mode=False,
            logo_small=fresh.logo_small,
            logo=fresh.logo,
            favicon=fresh.favicon,
            default_theme_id=7,
        )
        user = _user()
        output, models = _run(user, site, SimpleNamespace(id=7))
        self.assertIn("BOOKWYRM_RESULT=UNCHANGED", output)
        user.set_password.assert_not_called()
        models.Theme.objects.create.assert_not_called()

    def test_rotated_password_converges_on_existing_account(self):
        user = _user()
        user.check_password.return_value = False
        output, _ = _run(
            user,
            _site(install_mode=False, default_theme_id=7),
            SimpleNamespace(id=7),
            LOGO_SMALL="",
            LOGO="",
            FAVICON="",
        )
        self.assertIn("BOOKWYRM_RESULT=CHANGED", output)
        user.set_password.assert_called_once_with("s3cret")

    def test_design_off_removes_own_theme_and_logos_only(self):
        ours = FakeFieldFile("logos/infinito-logo-small-0123456789ab_ab12cd.png")
        foreign = FakeFieldFile("logos/custom.png")
        theme = MagicMock()
        site = _site(
            install_mode=False, logo_small=ours, logo=foreign, default_theme_id=7
        )
        output, _ = _run(_user(), site, theme, DESIGN_STATE="absent")
        self.assertIn("BOOKWYRM_RESULT=CHANGED", output)
        self.assertTrue(ours.deleted)
        self.assertFalse(foreign.deleted)
        theme.delete.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
