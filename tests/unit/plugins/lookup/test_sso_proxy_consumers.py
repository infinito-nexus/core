"""Unit tests for the ``sso_proxy_consumers`` lookup plugin.

The plugin enumerates roles whose merged config satisfies
``services.sso.flavor == 'oauth2'`` AND ``services.sso.enabled``
potentially-truthy. The shape test (no terms) and the predicate test
(only oauth2-flavored, enabled consumers appear) are pinned here so
future contract changes are caught.
"""

import importlib
import importlib.util
import sys
import unittest
from unittest import mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    for key in (
        "utils.roles.applications.config",
        "utils.roles.applications",
        "utils",
        "utils.cache.applications",
        "utils.cache",
        "utils.roles.applications.services.sso",
        "utils.roles.applications.services",
    ):
        sys.modules.pop(key, None)
    importlib.import_module("utils.roles.applications.config")
    importlib.import_module("utils.cache.applications")
    importlib.import_module("utils.roles.applications.services.sso")

    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _role(*, enabled=True, flavor="oauth2"):
    sso: dict = {"enabled": enabled, "flavor": flavor}
    return {"services": {"sso": sso}}


class SsoProxyConsumersLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module(
            "plugins/lookup/sso_proxy_consumers.py", "sso_proxy_consumers"
        )

    def setUp(self):
        self._original_loader = self.mod.lookup_loader
        self._stub_payload = None

        loader_mock = mock.MagicMock()
        loader_mock.get.return_value = mock.MagicMock(
            run=lambda *_a, **_k: [self._stub_payload]
        )
        self.mod.lookup_loader = loader_mock

    def tearDown(self):
        self.mod.lookup_loader = self._original_loader

    def _run(self, applications, terms=None):
        self._stub_payload = applications
        lk = self.mod.LookupModule()
        lk._loader = mock.MagicMock()
        return lk.run(terms or [], variables={"applications": applications})

    # --- term-shape contract --------------------------------------------

    def test_positional_terms_raise(self):
        with self.assertRaises(AnsibleError):
            self._run({}, ["extra-arg"])

    # --- enumeration ----------------------------------------------------

    def test_empty_applications_returns_empty_list(self):
        result = self._run({})
        self.assertEqual(result, [[]])

    def test_oauth2_enabled_consumer_is_included(self):
        apps = {"web-app-a": _role(enabled=True, flavor="oauth2")}
        result = self._run(apps)
        self.assertEqual(result, [["web-app-a"]])

    def test_oidc_consumer_is_excluded(self):
        apps = {"web-app-a": _role(enabled=True, flavor="oidc")}
        self.assertEqual(self._run(apps), [[]])

    def test_disabled_oauth2_consumer_is_excluded(self):
        apps = {"web-app-a": _role(enabled=False, flavor="oauth2")}
        self.assertEqual(self._run(apps), [[]])

    def test_mixed_apps_only_oauth2_enabled_returned(self):
        apps = {
            "web-app-a": _role(enabled=True, flavor="oauth2"),
            "web-app-b": _role(enabled=True, flavor="oidc"),
            "web-app-c": _role(enabled=False, flavor="oauth2"),
            "web-app-d": _role(enabled=True, flavor="oauth2"),
            "web-app-e": {"services": {}},  # no sso block at all
        }
        result = self._run(apps)
        self.assertEqual(result, [["web-app-a", "web-app-d"]])

    def test_result_is_alphabetically_sorted(self):
        apps = {
            "web-app-zeta": _role(enabled=True, flavor="oauth2"),
            "web-app-alpha": _role(enabled=True, flavor="oauth2"),
            "web-app-mu": _role(enabled=True, flavor="oauth2"),
        }
        result = self._run(apps)
        self.assertEqual(result, [["web-app-alpha", "web-app-mu", "web-app-zeta"]])

    def test_jinja_enabled_string_is_treated_as_potentially_truthy(self):
        # An unrendered Jinja string (the dynamic-flag form) is the merged
        # payload's shape for SSO-gated roles; the resolver renders it to
        # a bool via Python's bool(...) → True (non-empty string truthy).
        apps = {
            "web-app-a": {
                "services": {
                    "sso": {
                        "enabled": "{{ 'web-app-keycloak' in group_names }}",
                        "flavor": "oauth2",
                    }
                }
            }
        }
        result = self._run(apps)
        self.assertEqual(result, [["web-app-a"]])


if __name__ == "__main__":
    unittest.main()
