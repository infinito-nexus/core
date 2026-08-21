from __future__ import annotations

import unittest

from utils.roles.applications.services.sso import (
    get_sso_config,
    is_potentially_enabled,
)


def _apps(
    *,
    enabled=False,
    shared=False,
    flavor=None,
    oauth2_origin_host=None,
    oauth2_origin_port=None,
    oauth2_acl=None,
    oauth2_allowed_groups=None,
) -> dict:
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


class GetSsoConfigTests(unittest.TestCase):
    def test_defaults_when_app_missing(self):
        res = get_sso_config({}, "web-app-x")
        self.assertEqual(res["enabled"], False)
        self.assertEqual(res["shared"], False)
        self.assertEqual(res["flavor"], "oidc")
        self.assertFalse(res["is_enabled"])
        self.assertFalse(res["is_proxy_gated"])
        self.assertFalse(res["is_oidc_native"])
        self.assertFalse(res["is_saml"])

    def test_disabled_collapses_all_predicates(self):
        res = get_sso_config(_apps(enabled=False, flavor="oauth2"), "web-app-x")
        self.assertFalse(res["is_enabled"])
        self.assertFalse(res["is_proxy_gated"])
        self.assertFalse(res["is_oidc_native"])

    def test_enabled_oidc_default_flavor(self):
        res = get_sso_config(_apps(enabled=True), "web-app-x")
        self.assertTrue(res["is_enabled"])
        self.assertTrue(res["is_oidc_native"])
        self.assertFalse(res["is_proxy_gated"])
        self.assertEqual(res["flavor"], "oidc")

    def test_enabled_oauth2_flavor_is_proxy_gated(self):
        res = get_sso_config(_apps(enabled=True, flavor="oauth2"), "web-app-x")
        self.assertTrue(res["is_enabled"])
        self.assertTrue(res["is_proxy_gated"])
        self.assertFalse(res["is_oidc_native"])
        self.assertFalse(res["is_saml"])

    def test_enabled_saml_flavor(self):
        res = get_sso_config(_apps(enabled=True, flavor="saml"), "web-app-x")
        self.assertTrue(res["is_saml"])
        self.assertFalse(res["is_proxy_gated"])
        self.assertFalse(res["is_oidc_native"])

    def test_unknown_flavor_falls_back_to_oidc(self):
        res = get_sso_config(_apps(enabled=True, flavor="bogus"), "web-app-x")
        self.assertEqual(res["flavor"], "oidc")
        self.assertTrue(res["is_oidc_native"])

    def test_non_string_flavor_falls_back_to_oidc(self):
        res = get_sso_config(_apps(enabled=True, flavor=42), "web-app-x")
        self.assertEqual(res["flavor"], "oidc")

    def test_shared_field_round_trips(self):
        res = get_sso_config(_apps(enabled=True, shared=True), "web-app-x")
        self.assertTrue(res["shared"])

    def test_predicate_keys_present_when_app_has_partial_block(self):
        apps = {"web-app-x": {"services": {"sso": {"enabled": True}}}}
        res = get_sso_config(apps, "web-app-x")
        for key in (
            "enabled",
            "shared",
            "flavor",
            "is_enabled",
            "is_proxy_gated",
            "is_oidc_native",
            "is_saml",
        ):
            self.assertIn(key, res, f"missing key {key}")


class Oauth2SubPropertiesTests(unittest.TestCase):
    def test_defaults_when_oauth2_block_missing(self):
        res = get_sso_config(_apps(enabled=True, flavor="oauth2"), "web-app-x")
        self.assertEqual(res["oauth2_origin_host"], "")
        self.assertEqual(res["oauth2_origin_port"], "")
        self.assertEqual(res["oauth2_acl"], {})
        self.assertEqual(res["oauth2_allowed_groups"], [])

    def test_origin_host_and_port_pass_through(self):
        res = get_sso_config(
            _apps(
                enabled=True,
                flavor="oauth2",
                oauth2_origin_host="application",
                oauth2_origin_port=8000,
            ),
            "web-app-x",
        )
        self.assertEqual(res["oauth2_origin_host"], "application")
        self.assertEqual(res["oauth2_origin_port"], "8000")  # stringified

    def test_origin_port_string_pass_through(self):
        res = get_sso_config(
            _apps(enabled=True, flavor="oauth2", oauth2_origin_port="9090"),
            "web-app-x",
        )
        self.assertEqual(res["oauth2_origin_port"], "9090")

    def test_acl_dict_pass_through(self):
        res = get_sso_config(
            _apps(
                enabled=True,
                flavor="oauth2",
                oauth2_acl={"whitelist": ["/api/", "/static/"]},
            ),
            "web-app-x",
        )
        self.assertEqual(res["oauth2_acl"], {"whitelist": ["/api/", "/static/"]})

    def test_acl_non_dict_falls_back_to_empty(self):
        res = get_sso_config(
            _apps(enabled=True, flavor="oauth2", oauth2_acl="bogus"),
            "web-app-x",
        )
        self.assertEqual(res["oauth2_acl"], {})

    def test_allowed_groups_list_pass_through(self):
        groups = ["/roles/web-app-x/administrator", "/roles/web-app-x/biber"]
        res = get_sso_config(
            _apps(enabled=True, flavor="oauth2", oauth2_allowed_groups=groups),
            "web-app-x",
        )
        self.assertEqual(res["oauth2_allowed_groups"], groups)

    def test_allowed_groups_non_list_falls_back_to_empty(self):
        res = get_sso_config(
            _apps(enabled=True, flavor="oauth2", oauth2_allowed_groups="bogus"),
            "web-app-x",
        )
        self.assertEqual(res["oauth2_allowed_groups"], [])

    def test_oauth2_sub_keys_exposed_even_when_flavor_is_oidc(self):
        res = get_sso_config(
            _apps(
                enabled=True,
                flavor="oidc",
                oauth2_origin_host="application",
                oauth2_origin_port=8080,
            ),
            "web-app-x",
        )
        self.assertEqual(res["oauth2_origin_host"], "application")
        self.assertFalse(res["is_proxy_gated"])  # still oidc


class IsPotentiallyEnabledTests(unittest.TestCase):
    def test_none_is_not_potentially_enabled(self):
        self.assertFalse(is_potentially_enabled(None))

    def test_literal_false_is_not_potentially_enabled(self):
        self.assertFalse(is_potentially_enabled(False))

    def test_literal_true_is_potentially_enabled(self):
        self.assertTrue(is_potentially_enabled(True))

    def test_string_false_case_insensitive_is_not_potentially_enabled(self):
        for v in ("false", "False", "FALSE", "  false  "):
            with self.subTest(value=v):
                self.assertFalse(is_potentially_enabled(v))

    def test_string_true_is_potentially_enabled(self):
        self.assertTrue(is_potentially_enabled("true"))

    def test_jinja_template_string_is_potentially_enabled(self):
        self.assertTrue(
            is_potentially_enabled("{{ 'web-app-keycloak' in group_names }}")
        )

    def test_empty_string_is_potentially_enabled(self):
        self.assertTrue(is_potentially_enabled(""))


if __name__ == "__main__":
    unittest.main()
