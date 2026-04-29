# tests/unit/plugins/lookup/test_cert.py
import sys
import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError
from plugins.lookup.cert import LookupModule
from utils.cache import _reset_cache_for_tests

# Make "ansible.module_utils.tls_common" importable during plain unit tests.
import utils.tls_common as _tls_common

sys.modules.setdefault("ansible.module_utils.tls_common", _tls_common)


class TestCertPlanLookup(unittest.TestCase):
    def setUp(self):
        _reset_cache_for_tests()
        self.lookup = LookupModule()

        self.domains = {
            "web-app-a": "a.example",
            "web-app-b": ["b.example", "b-alt.example"],
            "web-app-c": {"primary": "c.example", "api": "api.c.example"},
        }

        self.applications = {
            "web-app-a": {},
            "web-app-b": {"server": {"tls": {"flavor": "self_signed"}}},
            "web-app-c": {
                "server": {
                    "tls": {"flavor": "self_signed", "domains_san": ["x.example"]}
                }
            },
            "web-app-off": {"server": {"tls": {"enabled": False}}},
        }

        # IMPORTANT (new strict behavior):
        # For TLS_SELFSIGNED_SCOPE=global, CURRENT_PLAY_DOMAINS_ALL MUST be list[str].
        self.vars = {
            "domains": self.domains,
            "applications": self.applications,
            "TLS_ENABLED": True,
            "TLS_MODE": "letsencrypt",
            "LETSENCRYPT_LIVE_PATH": "/etc/letsencrypt/live/",
            "TLS_SELFSIGNED_BASE_PATH": "/etc/infinito.nexus/selfsigned",
            "TLS_SELFSIGNED_SCOPE": "global",
            "CURRENT_PLAY_DOMAINS_ALL": [
                "a.example",
                "b.example",
                "b-alt.example",
                "c.example",
                "api.c.example",
            ],
        }

        # Route get_merged_domains / get_merged_applications through
        # variables['domains'] / variables['applications'] so tests stay hermetic.
        def _domains_from_vars(*, variables=None, **_kwargs):
            return (variables or {}).get("domains", {})

        def _applications_from_vars(*, variables=None, **_kwargs):
            return (variables or {}).get("applications", {})

        self._patchers = [
            patch(
                "plugins.lookup.cert.get_merged_domains",
                side_effect=_domains_from_vars,
            ),
            patch(
                "plugins.lookup.cert.get_merged_applications",
                side_effect=_applications_from_vars,
            ),
        ]
        for p in self._patchers:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patchers])

    def tearDown(self):
        _reset_cache_for_tests()

    def test_letsencrypt_plan_paths_and_sans_default(self):
        out = self.lookup.run(["web-app-a"], variables=self.vars, mode="app")[0]
        self.assertEqual(out["mode"], "letsencrypt")
        self.assertEqual(
            out["files"]["cert"], "/etc/letsencrypt/live/a.example/fullchain.pem"
        )
        self.assertEqual(
            out["files"]["key"], "/etc/letsencrypt/live/a.example/privkey.pem"
        )
        self.assertEqual(out["domains"]["san"], ["a.example"])

    def test_letsencrypt_plan_uses_cert_name_override(self):
        v = dict(self.vars)
        v["applications"] = dict(self.applications)
        v["applications"]["web-app-a"] = {
            "server": {"tls": {"letsencrypt_cert_name": "mycert"}}
        }

        out = self.lookup.run(["web-app-a"], variables=v, mode="app")[0]
        self.assertEqual(out["cert_id"], "mycert")
        self.assertEqual(
            out["files"]["cert"], "/etc/letsencrypt/live/mycert/fullchain.pem"
        )

    def test_selfsigned_global_scope(self):
        out = self.lookup.run(["web-app-b"], variables=self.vars, mode="app")[0]
        self.assertEqual(out["mode"], "self_signed")
        self.assertEqual(out["scope"], "global")
        self.assertEqual(out["cert_id"], "global")
        self.assertEqual(
            out["files"]["cert"], "/etc/infinito.nexus/selfsigned/global/fullchain.pem"
        )
        self.assertEqual(
            out["files"]["key"], "/etc/infinito.nexus/selfsigned/global/privkey.pem"
        )

        # New strict behavior:
        # SANs come from CURRENT_PLAY_DOMAINS_ALL (list[str]), plus primary_domain first.
        self.assertEqual(
            out["domains"]["san"],
            ["b.example", "a.example", "b-alt.example", "c.example", "api.c.example"],
        )

    def test_selfsigned_global_scope_requires_current_play_domains_all_list(self):
        v = dict(self.vars)
        del v["CURRENT_PLAY_DOMAINS_ALL"]
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-b"], variables=v, mode="app")

        v2 = dict(self.vars)
        v2["CURRENT_PLAY_DOMAINS_ALL"] = {"a.example": True}  # wrong type
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-b"], variables=v2, mode="app")

        v3 = dict(self.vars)
        v3["CURRENT_PLAY_DOMAINS_ALL"] = []  # empty list not allowed
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-b"], variables=v3, mode="app")

        v4 = dict(self.vars)
        v4["CURRENT_PLAY_DOMAINS_ALL"] = ["a.example", ""]  # empty string not allowed
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-b"], variables=v4, mode="app")

        v5 = dict(self.vars)
        v5["CURRENT_PLAY_DOMAINS_ALL"] = ["a.example", 123]  # non-string not allowed
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-b"], variables=v5, mode="app")

    def test_selfsigned_app_scope_paths(self):
        v = dict(self.vars)
        v["TLS_SELFSIGNED_SCOPE"] = "app"

        out = self.lookup.run(["web-app-b"], variables=v, mode="app")[0]
        self.assertEqual(out["scope"], "app")
        self.assertEqual(out["cert_id"], "web-app-b")
        self.assertEqual(
            out["files"]["cert"],
            "/etc/infinito.nexus/selfsigned/web-app-b/b.example/fullchain.pem",
        )
        self.assertEqual(
            out["files"]["key"],
            "/etc/infinito.nexus/selfsigned/web-app-b/b.example/privkey.pem",
        )

    def test_selfsigned_san_override(self):
        v = dict(self.vars)
        v["TLS_SELFSIGNED_SCOPE"] = "app"

        out = self.lookup.run(["web-app-c"], variables=v, mode="app")[0]
        self.assertEqual(out["domains"]["san"], ["c.example", "x.example"])

    def test_off_mode_returns_empty_files_and_san(self):
        v = dict(self.vars)
        v["domains"] = dict(self.domains)
        v["domains"]["web-app-off"] = "off.example"

        out = self.lookup.run(["web-app-off"], variables=v, mode="app")[0]
        self.assertEqual(out["enabled"], False)
        self.assertEqual(out["mode"], "off")
        self.assertEqual(out["files"]["cert"], "")
        self.assertEqual(out["files"]["key"], "")
        self.assertEqual(out["domains"]["san"], [])

    def test_want_path(self):
        val = self.lookup.run(
            ["web-app-a", "files.cert"], variables=self.vars, mode="app"
        )[0]
        self.assertEqual(val, "/etc/letsencrypt/live/a.example/fullchain.pem")

    def test_missing_required_when_needed(self):
        v = dict(self.vars)
        del v["LETSENCRYPT_LIVE_PATH"]
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-a"], variables=v, mode="app")

        v2 = dict(self.vars)
        v2["applications"] = dict(self.applications)
        v2["applications"]["web-app-a"] = {"server": {"tls": {"flavor": "self_signed"}}}
        del v2["TLS_SELFSIGNED_BASE_PATH"]
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-a"], variables=v2, mode="app")

    def test_invalid_scope(self):
        v = dict(self.vars)
        v["TLS_SELFSIGNED_SCOPE"] = "nope"
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-b"], variables=v, mode="app")

    def test_invalid_tls_mode_default(self):
        v = dict(self.vars)
        v["TLS_MODE"] = "invalid"
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-a"], variables=v, mode="app")

    # -------------------------------------------------------------------------
    # New tests for "Jinja-in-vars expansion inside lookup" logic
    # -------------------------------------------------------------------------

    def test_selfsigned_base_path_expands_jinja_from_hostvars(self):
        """
        TLS_SELFSIGNED_BASE_PATH may contain Jinja markers and must be expanded
        inside the lookup using the host context (hostvars[inventory_hostname]).
        """
        v = dict(self.vars)
        v["TLS_SELFSIGNED_BASE_PATH"] = "/etc/{{ SOFTWARE_DOMAIN }}/selfsigned"

        # Simulate real ansible lookup context
        v["inventory_hostname"] = "localhost"
        v["hostvars"] = {
            "localhost": {
                "SOFTWARE_DOMAIN": "infinito.nexus",
            }
        }

        out = self.lookup.run(["web-app-b"], variables=v, mode="app")[0]
        self.assertEqual(out["mode"], "self_signed")
        self.assertEqual(
            out["files"]["cert"], "/etc/infinito.nexus/selfsigned/global/fullchain.pem"
        )
        self.assertEqual(
            out["files"]["key"], "/etc/infinito.nexus/selfsigned/global/privkey.pem"
        )

    def test_letsencrypt_live_path_expands_jinja_from_hostvars(self):
        """
        LETSENCRYPT_LIVE_PATH may contain Jinja markers and must be expanded.
        """
        v = dict(self.vars)
        v["LETSENCRYPT_LIVE_PATH"] = "/etc/{{ SOFTWARE_DOMAIN }}/letsencrypt/live"

        v["inventory_hostname"] = "localhost"
        v["hostvars"] = {
            "localhost": {
                "SOFTWARE_DOMAIN": "infinito.nexus",
            }
        }

        out = self.lookup.run(["web-app-a"], variables=v, mode="app")[0]
        self.assertEqual(out["mode"], "letsencrypt")
        self.assertEqual(
            out["files"]["cert"],
            "/etc/infinito.nexus/letsencrypt/live/a.example/fullchain.pem",
        )
        self.assertEqual(
            out["files"]["key"],
            "/etc/infinito.nexus/letsencrypt/live/a.example/privkey.pem",
        )

    def test_jinja_expansion_missing_var_fails_hard(self):
        """
        With strict rendering, missing vars used inside the Jinja expression must
        raise an AnsibleError (no leaking "{{ ... }}" into configs).
        """
        v = dict(self.vars)
        v["TLS_SELFSIGNED_BASE_PATH"] = "/etc/{{ SOFTWARE_DOMAIN }}/selfsigned"

        # No SOFTWARE_DOMAIN present in either variables or hostvars context
        v["inventory_hostname"] = "localhost"
        v["hostvars"] = {"localhost": {}}

        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-b"], variables=v, mode="app")

    def test_jinja_expansion_uses_hostvars_over_lookup_vars(self):
        """
        If both `variables` and hostvars contain SOFTWARE_DOMAIN, hostvars should win
        (as implemented by ctx.update(hostvars[inventory_hostname])).
        """
        v = dict(self.vars)
        v["TLS_SELFSIGNED_BASE_PATH"] = "/etc/{{ SOFTWARE_DOMAIN }}/selfsigned"

        # variables has one value
        v["SOFTWARE_DOMAIN"] = "Wrong.Name"

        # hostvars has another, should win
        v["inventory_hostname"] = "localhost"
        v["hostvars"] = {
            "localhost": {
                "SOFTWARE_DOMAIN": "infinito.nexus",
            }
        }

        out = self.lookup.run(["web-app-b"], variables=v, mode="app")[0]
        self.assertEqual(
            out["files"]["cert"], "/etc/infinito.nexus/selfsigned/global/fullchain.pem"
        )

    def test_jinja_expression_that_renders_to_empty_triggers_failfast(self):
        """
        If Jinja renders to something that still contains Jinja markers, or is invalid,
        cert should fail fast. Here we use a construction that still contains Jinja
        after rendering by injecting literal braces.
        """
        v = dict(self.vars)
        # This will render to a string that still contains "{{ STILL_JINJA }}"
        v["TLS_SELFSIGNED_BASE_PATH"] = "/etc/{{ '{{ STILL_JINJA }}' }}/selfsigned"
        v["inventory_hostname"] = "localhost"
        v["hostvars"] = {"localhost": {"SOFTWARE_DOMAIN": "infinito.nexus"}}

        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-b"], variables=v, mode="app")


if __name__ == "__main__":
    unittest.main()
