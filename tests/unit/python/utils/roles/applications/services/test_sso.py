from __future__ import annotations

import unittest

from jinja2.filters import do_urlencode

from plugins.filter.merge.with_defaults import merge_with_defaults
from utils.roles.applications.services.sso import (
    SsoConfigConflictError,
    get_sso_config,
    is_potentially_enabled,
    logout_url,
    proxy_instances,
    restricted_locations,
)

KEYCLOAK_LOGOUT = "https://auth.example.org/realms/r/protocol/openid-connect/logout"
ONION = "a" * 56 + ".onion"
CONFIG_FILE = "oauth2-proxy-keycloak.cfg"
ALPHA_FILE = "oauth2-proxy-keycloak-alpha.yml"
ADMIN_GROUPS = ["/roles/web-app-x/administrator"]


def _apps(
    *,
    enabled=False,
    shared=False,
    flavor=None,
    oauth2_origin_host=None,
    oauth2_origin_port=None,
    oauth2_acl=None,
    oauth2_allowed_groups=None,
    oauth2_claim_headers=None,
    oauth2_allow_all_users=None,
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
    if oauth2_claim_headers is not None:
        oauth2_sub["claim_headers"] = oauth2_claim_headers
    if oauth2_allow_all_users is not None:
        oauth2_sub["allow_all_users"] = oauth2_allow_all_users
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
        self.assertEqual(res["oauth2_claim_headers"], [])
        self.assertIs(res["oauth2_any_email"], False)

    def test_any_email_reads_the_declared_switch(self):
        apps = _apps(enabled=True, flavor="oauth2")
        for declared, expected in ((True, True), ("true", True), ("False", False)):
            with self.subTest(declared=declared):
                apps["web-app-x"]["services"]["sso"]["oauth2"] = {"any_email": declared}
                res = get_sso_config(apps, "web-app-x")
                self.assertIs(res["oauth2_any_email"], expected)

    def test_claim_headers_pass_through_as_strings(self):
        res = get_sso_config(
            _apps(
                enabled=True, flavor="oauth2", oauth2_claim_headers=["NAME", "LOCALE"]
            ),
            "web-app-x",
        )
        self.assertEqual(res["oauth2_claim_headers"], ["NAME", "LOCALE"])

    def test_non_list_claim_headers_collapse_to_empty(self):
        res = get_sso_config(
            _apps(enabled=True, flavor="oauth2", oauth2_claim_headers="NAME"),
            "web-app-x",
        )
        self.assertEqual(res["oauth2_claim_headers"], [])

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


class Oauth2AllowAllUsersTests(unittest.TestCase):
    def test_defaults_to_false_when_absent(self):
        res = get_sso_config(_apps(enabled=True, flavor="oauth2"), "web-app-x")
        self.assertIs(res["oauth2_allow_all_users"], False)

    def test_reads_the_declared_opt_in(self):
        res = get_sso_config(
            _apps(enabled=True, flavor="oauth2", oauth2_allow_all_users=True),
            "web-app-x",
        )
        self.assertIs(res["oauth2_allow_all_users"], True)

    def test_parses_rendered_strings_like_pass_access_token(self):
        for value, expected in (("True", True), ("yes", True), ("False", False)):
            with self.subTest(value=value):
                res = get_sso_config(
                    _apps(enabled=True, flavor="oauth2", oauth2_allow_all_users=value),
                    "web-app-x",
                )
                self.assertIs(res["oauth2_allow_all_users"], expected)

    def test_coexists_with_an_empty_allowed_groups_list(self):
        res = get_sso_config(
            _apps(
                enabled=True,
                flavor="oauth2",
                oauth2_allowed_groups=[],
                oauth2_allow_all_users=True,
            ),
            "web-app-x",
        )
        self.assertEqual(
            (res["oauth2_allow_all_users"], res["oauth2_allowed_groups"]), (True, [])
        )

    def test_false_keeps_the_allowed_groups(self):
        res = get_sso_config(
            _apps(
                enabled=True,
                flavor="oauth2",
                oauth2_allowed_groups=ADMIN_GROUPS,
                oauth2_allow_all_users=False,
            ),
            "web-app-x",
        )
        self.assertEqual(res["oauth2_allowed_groups"], ADMIN_GROUPS)

    def test_together_with_allowed_groups_raises(self):
        with self.assertRaises(SsoConfigConflictError):
            get_sso_config(
                _apps(
                    enabled=True,
                    flavor="oauth2",
                    oauth2_allowed_groups=ADMIN_GROUPS,
                    oauth2_allow_all_users=True,
                ),
                "web-app-x",
            )

    def test_the_conflict_names_the_application_and_both_keys(self):
        with self.assertRaises(SsoConfigConflictError) as ctx:
            get_sso_config(
                _apps(
                    enabled=True,
                    flavor="oauth2",
                    oauth2_allowed_groups=ADMIN_GROUPS,
                    oauth2_allow_all_users=True,
                ),
                "web-app-x",
            )
        for name in (
            "web-app-x",
            "services.sso.oauth2.allow_all_users",
            "services.sso.oauth2.allowed_groups",
        ):
            with self.subTest(name=name):
                self.assertIn(name, str(ctx.exception))

    def test_an_inventory_empty_list_replaces_the_role_groups(self):
        role = _apps(enabled=True, flavor="oauth2", oauth2_allowed_groups=ADMIN_GROUPS)
        inventory = _apps(
            enabled=True,
            flavor="oauth2",
            oauth2_allowed_groups=[],
            oauth2_allow_all_users=True,
        )
        res = get_sso_config(merge_with_defaults(role, inventory), "web-app-x")
        self.assertEqual(
            (res["oauth2_allow_all_users"], res["oauth2_allowed_groups"]), (True, [])
        )


def _client_apps(client) -> dict:
    """
    Args:
        client: the ``services.sso.oauth2.client`` value of ``web-app-x``.

    Returns:
        A payload whose oauth2-gated ``web-app-x`` declares ``client``.
    """
    return {
        "web-app-x": {
            "services": {
                "sso": {
                    "enabled": True,
                    "flavor": "oauth2",
                    "oauth2": {"client": client},
                }
            }
        }
    }


class Oauth2ClientTests(unittest.TestCase):
    def test_no_declared_client_keeps_the_shared_one(self):
        for apps in (_apps(enabled=True, flavor="oauth2"), _client_apps({})):
            with self.subTest(apps=apps):
                self.assertEqual(get_sso_config(apps, "web-app-x")["oauth2_client"], {})

    def test_a_declared_client_yields_its_id_and_scopes(self):
        res = get_sso_config(
            _client_apps({"id": " x-gate ", "scopes": ["kc-admin-api"]}), "web-app-x"
        )
        self.assertEqual(
            res["oauth2_client"], {"id": "x-gate", "scopes": ["kc-admin-api"]}
        )

    def test_an_empty_scope_list_is_a_valid_declaration(self):
        res = get_sso_config(_client_apps({"id": "x-gate", "scopes": []}), "web-app-x")
        self.assertEqual(res["oauth2_client"], {"id": "x-gate", "scopes": []})

    def test_a_client_without_id_or_scopes_fails_loudly(self):
        for client in (
            {"scopes": ["kc-admin-api"]},
            {"id": "", "scopes": []},
            {"id": "x-gate"},
            {"id": "x-gate", "scopes": "kc-admin-api"},
            "x-gate",
        ):
            with self.subTest(client=client):
                with self.assertRaises(ValueError) as ctx:
                    get_sso_config(_client_apps(client), "web-app-x")
                self.assertIn("web-app-x", str(ctx.exception))
                self.assertIn("services.sso.oauth2.client", str(ctx.exception))


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


class TestRestrictedLocations(unittest.TestCase):
    def test_a_location_gets_an_internal_auth_uri_and_its_group_query(self):
        self.assertEqual(
            restricted_locations(
                [{"location": "/admin", "groups": ["roles/web-app-x/administrator"]}]
            ),
            [
                {
                    "location": "/admin",
                    "groups": ["/roles/web-app-x/administrator"],
                    "auth_uri": "/oauth2/auth-restricted-0",
                    "upstream": "/oauth2/auth?allowed_groups=/roles/web-app-x/administrator",
                }
            ],
        )

    def test_several_groups_are_comma_joined_and_encoded(self):
        gate = restricted_locations(
            [{"location": "/x", "groups": ["/roles/a b/one", "//roles/c/two"]}]
        )[0]
        self.assertEqual(gate["groups"], ["/roles/a b/one", "/roles/c/two"])
        self.assertEqual(
            gate["upstream"],
            "/oauth2/auth?allowed_groups=/roles/a%20b/one,/roles/c/two",
        )

    def test_each_entry_gets_its_own_auth_uri(self):
        gates = restricted_locations(
            [
                {"location": "/a", "groups": ["/g"]},
                {"location": "/b", "groups": ["/g"]},
            ]
        )
        self.assertEqual(
            [gate["auth_uri"] for gate in gates],
            ["/oauth2/auth-restricted-0", "/oauth2/auth-restricted-1"],
        )

    def test_an_entry_without_location_or_groups_fails_loudly(self):
        for entry in (
            {"groups": ["/g"]},
            {"location": "/a"},
            {"location": "/a", "groups": []},
        ):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                restricted_locations([entry])

    def test_a_missing_or_non_list_value_yields_no_gate(self):
        self.assertEqual(restricted_locations([]), [])
        self.assertEqual(restricted_locations(None), [])
        self.assertEqual(
            get_sso_config(_apps(enabled=True, flavor="oauth2"), "web-app-x")[
                "oauth2_restricted_locations"
            ],
            [],
        )


class TestLogoutUrl(unittest.TestCase):
    def test_an_app_without_the_proxy_logs_out_at_the_provider(self):
        self.assertEqual(logout_url(KEYCLOAK_LOGOUT, False), KEYCLOAK_LOGOUT)

    def test_a_proxy_gated_app_signs_out_of_oauth2_proxy_first(self):
        self.assertEqual(
            logout_url(KEYCLOAK_LOGOUT, True),
            "/oauth2/sign_out?rd=https%3A//auth.example.org/realms/r/protocol/openid-connect/logout",
        )

    def test_the_rd_encoding_matches_the_jinja_urlencode_filter(self):
        self.assertEqual(
            logout_url(KEYCLOAK_LOGOUT, True),
            f"/oauth2/sign_out?rd={do_urlencode(KEYCLOAK_LOGOUT)}",
        )


class TestProxyInstances(unittest.TestCase):
    def test_a_clearnet_app_keeps_the_single_unsuffixed_instance(self):
        self.assertEqual(
            proxy_instances(["app.example.org"], CONFIG_FILE, ALPHA_FILE),
            [
                {
                    "network": "clearnet",
                    "service": "sso-proxy",
                    "port_key": "sso",
                    "config_file": CONFIG_FILE,
                    "alpha_config_file": ALPHA_FILE,
                }
            ],
        )

    def test_an_onion_sibling_gets_its_own_labelled_instance(self):
        instances = proxy_instances(
            ["app.example.org", f"app.{ONION}"], CONFIG_FILE, ALPHA_FILE
        )
        self.assertEqual([i["network"] for i in instances], ["clearnet", "tor"])
        self.assertEqual(
            instances[1],
            {
                "network": "tor",
                "service": "sso-proxy-onion",
                "port_key": "sso_onion",
                "config_file": "oauth2-proxy-keycloak-onion.cfg",
                "alpha_config_file": "oauth2-proxy-keycloak-alpha-onion.yml",
            },
        )

    def test_an_onion_only_app_runs_one_unsuffixed_instance_on_tor(self):
        self.assertEqual(
            proxy_instances([f"app.{ONION}"], CONFIG_FILE, ALPHA_FILE),
            [
                {
                    "network": "tor",
                    "service": "sso-proxy",
                    "port_key": "sso",
                    "config_file": CONFIG_FILE,
                    "alpha_config_file": ALPHA_FILE,
                }
            ],
        )

    def test_named_canonical_domains_yield_one_instance_per_network(self):
        instances = proxy_instances(
            {
                "filer": "filer.example.org",
                "master": "master.example.org",
                "filer_onion": f"filer.{ONION}",
                "master_onion": f"master.{ONION}",
            },
            CONFIG_FILE,
            ALPHA_FILE,
        )
        self.assertEqual(
            [i["service"] for i in instances], ["sso-proxy", "sso-proxy-onion"]
        )

    def test_a_config_file_without_extension_takes_the_label_as_suffix(self):
        instances = proxy_instances(
            ["app.example.org", f"app.{ONION}"], "proxy", "alpha"
        )
        self.assertEqual(
            [i["config_file"] for i in instances], ["proxy", "proxy-onion"]
        )
        self.assertEqual(
            [i["alpha_config_file"] for i in instances], ["alpha", "alpha-onion"]
        )


if __name__ == "__main__":
    unittest.main()
