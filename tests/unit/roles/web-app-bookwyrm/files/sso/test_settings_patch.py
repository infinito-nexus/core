from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from utils.cache.files import read_text

from . import PROJECT_ROOT

PATCH_PATH = PROJECT_ROOT / "roles/web-app-bookwyrm/files/sso/settings_patch.py"

AUTH_MW = "django.contrib.auth.middleware.AuthenticationMiddleware"
SSO_MW = "bookwyrm.header_auth.ProxyHeaderMiddleware"
SSO_BACKEND = "bookwyrm.header_auth.ProxyHeaderBackend"
MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"

BASE_MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    AUTH_MW,
    "bookwyrm.middleware.RequireLoginNearlyEverywhere",
]


class TestSettingsSsoPatch(unittest.TestCase):
    """The patch appended to BookWyrm settings must wire the SSO bridge in only
    when PROXY_HEADER_SSO is truthy, and be completely inert otherwise."""

    def _apply(self, *, env, middleware=None):
        namespace = {
            "MIDDLEWARE": list(BASE_MIDDLEWARE if middleware is None else middleware)
        }
        code = compile(read_text(str(PATCH_PATH)), str(PATCH_PATH), "exec")
        with patch.dict(os.environ, env, clear=True):
            exec(code, namespace)
        return namespace

    def test_enabled_inserts_middleware_directly_after_auth(self):
        mw = self._apply(env={"PROXY_HEADER_SSO": "true"})["MIDDLEWARE"]
        self.assertIn(SSO_MW, mw)
        self.assertEqual(mw.index(SSO_MW), mw.index(AUTH_MW) + 1)

    def test_enabled_sets_backends_with_sso_first(self):
        namespace = self._apply(env={"PROXY_HEADER_SSO": "true"})
        self.assertEqual(
            namespace["AUTHENTICATION_BACKENDS"], [SSO_BACKEND, MODEL_BACKEND]
        )

    def test_disabled_is_inert(self):
        namespace = self._apply(env={"PROXY_HEADER_SSO": "false"})
        self.assertEqual(namespace["MIDDLEWARE"], BASE_MIDDLEWARE)
        self.assertNotIn("AUTHENTICATION_BACKENDS", namespace)

    def test_unset_is_inert(self):
        namespace = self._apply(env={})
        self.assertEqual(namespace["MIDDLEWARE"], BASE_MIDDLEWARE)
        self.assertNotIn("AUTHENTICATION_BACKENDS", namespace)

    def test_truthy_aliases_activate(self):
        for value in ("1", "yes", "TRUE", "Yes"):
            mw = self._apply(env={"PROXY_HEADER_SSO": value})["MIDDLEWARE"]
            self.assertIn(SSO_MW, mw, f"{value!r} should activate the bridge")

    def test_idempotent_no_double_insert(self):
        pre = list(BASE_MIDDLEWARE)
        pre.insert(pre.index(AUTH_MW) + 1, SSO_MW)
        mw = self._apply(env={"PROXY_HEADER_SSO": "true"}, middleware=pre)["MIDDLEWARE"]
        self.assertEqual(mw.count(SSO_MW), 1)


if __name__ == "__main__":
    unittest.main()
