"""Unit tests for the ``sso`` lookup plugin.

The plugin is a thin wrapper around
``utils.roles.applications.services.sso.get_sso_config`` — these tests
focus on the lookup-shape contract (term parsing, want-path selection,
error paths). Resolver semantics are covered by
``tests/unit/python/utils/roles/applications/services/test_sso.py``.
"""

import importlib
import importlib.util
import sys
import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    with mock.patch.dict(sys.modules):
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
    oauth2_pass_access_token=None,
    oauth2_allow_all_users=None,
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
    if oauth2_pass_access_token is not None:
        oauth2_sub["pass_access_token"] = oauth2_pass_access_token
    if oauth2_allow_all_users is not None:
        oauth2_sub["allow_all_users"] = oauth2_allow_all_users
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

    def test_proxy_instances_follow_the_app_domains_and_keycloak_config_file(self):
        applications = {
            **_apps(enabled=True, flavor="oauth2"),
            "web-app-keycloak": {
                "services": {
                    "sso_proxy": {
                        "configuration_file": "proxy.cfg",
                        "alpha_configuration_file": "proxy-alpha.yml",
                    }
                }
            },
        }
        domains = {"web-app-x": ["x.example.org", "x." + "a" * 56 + ".onion"]}
        lk = self.mod.LookupModule()
        lk._loader = mock.MagicMock()
        with mock.patch.object(self.mod, "lookup_loader") as loader_mock:
            loader_mock.get.side_effect = lambda name, **_k: mock.MagicMock(
                run=lambda *_a, **_kw: [domains if name == "domains" else applications]
            )
            result = lk.run(
                ["web-app-x", "proxy_instances"],
                variables={"applications": applications},
            )
        self.assertEqual(
            [
                (i["service"], i["port_key"], i["config_file"], i["alpha_config_file"])
                for i in result[0]
            ],
            [
                ("sso-proxy", "sso", "proxy.cfg", "proxy-alpha.yml"),
                (
                    "sso-proxy-onion",
                    "sso_onion",
                    "proxy-onion.cfg",
                    "proxy-alpha-onion.yml",
                ),
            ],
        )

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

    def test_default_returns_full_dict(self):
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

    def test_pass_access_token_defaults_to_false(self):
        result = self._run(
            _apps(enabled=True, flavor="oauth2"),
            ["web-app-x", "oauth2_pass_access_token"],
        )
        self.assertEqual(result, [False])

    def test_pass_access_token_reads_the_declared_opt_in(self):
        result = self._run(
            _apps(enabled=True, flavor="oauth2", oauth2_pass_access_token=True),
            ["web-app-x", "oauth2_pass_access_token"],
        )
        self.assertEqual(result, [True])

    def test_pass_access_token_accepts_a_rendered_string(self):
        result = self._run(
            _apps(enabled=True, flavor="oauth2", oauth2_pass_access_token="True"),
            ["web-app-x", "oauth2_pass_access_token"],
        )
        self.assertEqual(result, [True])

    def test_pass_access_token_rejects_a_rendered_false_string(self):
        result = self._run(
            _apps(enabled=True, flavor="oauth2", oauth2_pass_access_token="False"),
            ["web-app-x", "oauth2_pass_access_token"],
        )
        self.assertEqual(result, [False])

    def test_allow_all_users_defaults_to_false(self):
        result = self._run(
            _apps(enabled=True, flavor="oauth2"),
            ["web-app-x", "oauth2_allow_all_users"],
        )
        self.assertEqual(result, [False])

    def test_allow_all_users_reads_the_declared_opt_in(self):
        result = self._run(
            _apps(enabled=True, flavor="oauth2", oauth2_allow_all_users="True"),
            ["web-app-x", "oauth2_allow_all_users"],
        )
        self.assertEqual(result, [True])

    def test_allow_all_users_with_allowed_groups_fails_the_lookup(self):
        with self.assertRaises(AnsibleError) as ctx:
            self._run(
                _apps(
                    enabled=True,
                    flavor="oauth2",
                    oauth2_allowed_groups=["/roles/web-app-x/admin"],
                    oauth2_allow_all_users=True,
                ),
                ["web-app-x", "oauth2_allowed_groups"],
            )
        self.assertIn("web-app-x", str(ctx.exception))

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
        result = self._run({}, ["web-app-x", "is_enabled"])
        self.assertEqual(result, [False])

    def test_empty_want_path_treated_as_all(self):
        result = self._run(_apps(enabled=True), ["web-app-x", "  "])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], dict)


class SsoLookupInsideTheApplicationsRenderTests(unittest.TestCase):
    GATED = "{{ 'web-app-keycloak' in group_names }}"

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module("plugins/lookup/sso.py", "sso")

    def _gated(self, applications, group_names):
        variables = {"group_names": group_names}
        lk = self.mod.LookupModule()
        lk._loader = DataLoader()
        lk._templar = Templar(loader=lk._loader, variables=variables)
        with mock.patch.object(self.mod, "lookup_loader") as loader_mock:
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [applications]
            )
            return lk.run(["web-app-x", "is_proxy_gated"], variables=variables)

    def test_an_unrendered_flag_counts_only_once_rendered(self):
        applications = _apps(enabled=self.GATED, shared=self.GATED, flavor="oauth2")
        self.assertEqual([False], self._gated(applications, []))
        self.assertEqual([True], self._gated(applications, ["web-app-keycloak"]))

    def test_a_templated_flavor_renders_before_it_is_checked(self):
        applications = _apps(
            enabled=True, flavor="{{ 'oauth2' if group_names else 'oidc' }}"
        )
        self.assertEqual([False], self._gated(applications, []))
        self.assertEqual([True], self._gated(applications, ["web-app-x"]))


if __name__ == "__main__":
    unittest.main()
