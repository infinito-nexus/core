from __future__ import annotations

import os
import sys
import unittest
from types import ModuleType
from unittest.mock import patch

from utils.cache.files import read_text

from . import PROJECT_ROOT

PATCH_PATH = PROJECT_ROOT / "roles/web-app-baserow/files/sso/settings_patch.py"

SSO_ROUTE = "api/infinito/sso/"
SSO_MODULE = "baserow.infinito_sso"

BASE_URLPATTERNS = ["baserow.core.urls", "baserow.api.urls"]


def _fake_django_urls() -> ModuleType:
    module = ModuleType("django.urls")
    module.include = lambda dotted_path: ("include", dotted_path)
    module.path = lambda route, view: ("path", route, view)
    return module


class TestSettingsSsoPatch(unittest.TestCase):
    """The patch appended to Baserow settings must mount the SSO endpoints only
    when PROXY_HEADER_SSO is truthy, and be completely inert otherwise."""

    def _apply(self, *, env, urlpatterns=None):
        namespace = {
            "urlpatterns": list(
                BASE_URLPATTERNS if urlpatterns is None else urlpatterns
            )
        }
        urls = _fake_django_urls()
        django = ModuleType("django")
        django.urls = urls
        code = compile(read_text(str(PATCH_PATH)), str(PATCH_PATH), "exec")
        with (
            patch.dict(sys.modules, {"django": django, "django.urls": urls}),
            patch.dict(os.environ, env, clear=True),
        ):
            exec(code, namespace)
        return namespace

    def test_enabled_mounts_the_sso_include_first(self):
        urlpatterns = self._apply(env={"PROXY_HEADER_SSO": "true"})["urlpatterns"]
        self.assertEqual(urlpatterns[0], ("path", SSO_ROUTE, ("include", SSO_MODULE)))

    def test_enabled_keeps_the_existing_routes_behind_it(self):
        urlpatterns = self._apply(env={"PROXY_HEADER_SSO": "true"})["urlpatterns"]
        self.assertEqual(urlpatterns[1:], BASE_URLPATTERNS)

    def test_disabled_is_inert(self):
        namespace = self._apply(env={"PROXY_HEADER_SSO": "false"})
        self.assertEqual(namespace["urlpatterns"], BASE_URLPATTERNS)
        self.assertNotIn("_infinito_sso_path", namespace)
        self.assertNotIn("_infinito_sso_include", namespace)

    def test_unset_is_inert(self):
        namespace = self._apply(env={})
        self.assertEqual(namespace["urlpatterns"], BASE_URLPATTERNS)
        self.assertNotIn("_infinito_sso_path", namespace)
        self.assertNotIn("_infinito_sso_include", namespace)

    def test_truthy_aliases_activate(self):
        for value in ("1", "yes", "on", "TRUE", "Yes"):
            urlpatterns = self._apply(env={"PROXY_HEADER_SSO": value})["urlpatterns"]
            self.assertEqual(
                urlpatterns[0],
                ("path", SSO_ROUTE, ("include", SSO_MODULE)),
                f"{value!r} should mount the bridge",
            )

    def test_unknown_value_is_inert(self):
        namespace = self._apply(env={"PROXY_HEADER_SSO": "maybe"})
        self.assertEqual(namespace["urlpatterns"], BASE_URLPATTERNS)


if __name__ == "__main__":
    unittest.main()
