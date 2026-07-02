"""Unit tests for the ``sso`` lookup plugin.

The plugin is a thin wrapper around
``utils.roles.applications.services.sso.get_sso_config`` — these tests
focus on the lookup-shape contract (term parsing, want-path selection,
error paths). Resolver semantics are covered by
``tests/unit/utils/roles/applications/services/test_sso.py``.
"""

import importlib
import importlib.util
import sys
import unittest
from unittest import mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    # Mirror test_sso_oidc_plugin.py's defensive sys.modules eviction so
    # sibling tests cannot leak a stubbed config module into this load.
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


def _apps(
    *,
    enabled=False,
    shared=False,
    flavor=None,
    oauth2_origin_host=None,
    oauth2_origin_port=None,
    oauth2_acl=None,
    oauth2_allowed_groups=None,
    include_app=True,
):
    if not include_app:
        return {}
    sso: dict = {"enabled": enabled, "shared": shared}
    if flavor is not None:
        sso["flavor"] = flavor
    oauth2_sub: dict = {}
    if oauth2_origin_host is not None or oauth2_origin_port is not None:
        oauth2_sub["origin"] = {
            **({"host": oauth2_origin_host} if oauth2_origin_host is not None else {}),
            **({"port": oauth2_origin_port} if oauth2_origin_port is not None else {}),
        }
    if oauth2_acl is not None:
        oauth2_sub["acl"] = oauth2_acl
    if oauth2_allowed_groups is not None:
        oauth2_sub["allowed_groups"] = oauth2_allowed_groups
    if oauth2_sub:
        sso["oauth2"] = oauth2_sub
    return {"web-app-x": {"services": {"sso": sso}}}


class SsoLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module("plugins/lookup/sso.py", "sso")

    def _run(self, applications, terms):
        lk = self.mod.LookupModule()
        lk._loader = mock.MagicMock()
        with mock.patch.object(self.mod, "lookup_loader") as loader_mock:
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [applications]
            )
            return lk.run(terms, variables={"applications": applications})

    # --- term parsing ----------------------------------------------------

    def test_zero_terms_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(_apps(), [])

    def test_three_terms_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(_apps(), ["web-app-x", "is_enabled", "extra"])

    def test_empty_application_id_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(_apps(), [""])

    def test_unknown_want_path_raises(self):
        with self.assertRaises(AnsibleError) as ctx:
            self._run(_apps(enabled=True), ["web-app-x", "bogus_key"])
        self.assertIn("unknown want_path", str(ctx.exception))

    # --- want-path resolution -------------------------------------------

    def test_default_returns_full_dict(self):
        # No want-path → entire resolver dict.
        result = self._run(_apps(enabled=True, flavor="oauth2"), ["web-app-x"])
        self.assertEqual(len(result), 1)
        payload = result[0]
        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["flavor"], "oauth2")
        self.assertTrue(payload["is_proxy_gated"])

    def test_explicit_all_returns_full_dict(self):
        result = self._run(_apps(enabled=True), ["web-app-x", "all"])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], dict)

    def test_is_enabled_returns_bool(self):
        result = self._run(_apps(enabled=True), ["web-app-x", "is_enabled"])
        self.assertEqual(result, [True])

    def test_is_proxy_gated_true_for_oauth2(self):
        result = self._run(
            _apps(enabled=True, flavor="oauth2"), ["web-app-x", "is_proxy_gated"]
        )
        self.assertEqual(result, [True])

    def test_is_proxy_gated_false_for_oidc(self):
        result = self._run(
            _apps(enabled=True, flavor="oidc"), ["web-app-x", "is_proxy_gated"]
        )
        self.assertEqual(result, [False])

    def test_is_proxy_gated_false_when_disabled(self):
        result = self._run(
            _apps(enabled=False, flavor="oauth2"), ["web-app-x", "is_proxy_gated"]
        )
        self.assertEqual(result, [False])

    def test_flavor_returns_string(self):
        result = self._run(
            _apps(enabled=True, flavor="oauth2"), ["web-app-x", "flavor"]
        )
        self.assertEqual(result, ["oauth2"])

    def test_oauth2_origin_host_returns_value(self):
        result = self._run(
            _apps(enabled=True, flavor="oauth2", oauth2_origin_host="application"),
            ["web-app-x", "oauth2_origin_host"],
        )
        self.assertEqual(result, ["application"])

    def test_oauth2_origin_port_stringified(self):
        result = self._run(
            _apps(enabled=True, flavor="oauth2", oauth2_origin_port=8000),
            ["web-app-x", "oauth2_origin_port"],
        )
        self.assertEqual(result, ["8000"])

    def test_oauth2_acl_returns_dict(self):
        acl = {"whitelist": ["/api/", "/static/"]}
        result = self._run(
            _apps(enabled=True, flavor="oauth2", oauth2_acl=acl),
            ["web-app-x", "oauth2_acl"],
        )
        self.assertEqual(result, [acl])

    def test_oauth2_allowed_groups_returns_list(self):
        groups = ["/roles/web-app-x/admin"]
        result = self._run(
            _apps(enabled=True, flavor="oauth2", oauth2_allowed_groups=groups),
            ["web-app-x", "oauth2_allowed_groups"],
        )
        self.assertEqual(result, [groups])

    def test_missing_app_returns_defaults(self):
        # No app entry → resolver gives defaults; want='is_enabled' → False.
        result = self._run({}, ["web-app-x", "is_enabled"])
        self.assertEqual(result, [False])

    def test_empty_want_path_treated_as_all(self):
        # Whitespace-only want collapses to 'all' per the docstring.
        result = self._run(_apps(enabled=True), ["web-app-x", "  "])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], dict)


if __name__ == "__main__":
    unittest.main()
