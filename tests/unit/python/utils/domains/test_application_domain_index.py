import unittest

from ansible.errors import AnsibleError

import utils.domains.application_domain_index as _application_domain_index


class TestApplicationDomainIndex(unittest.TestCase):
    def setUp(self):
        self.applications = {
            "web-app-a": {
                "domains": {
                    "canonical": ["a.example"],
                    "aliases": ["www.a.example", "A.ALIAS.EXAMPLE"],
                }
            },
            "web-app-b": {
                "domains": {
                    "canonical": "b.example",
                    "aliases": [],
                }
            },
            "web-app-c": {
                "domains": {
                    "canonical": {"web": "c.example", "api": "api.c.example"},
                    "aliases": {"www": "www.c.example"},
                }
            },
            "web-app-nested": {
                "domains": {
                    "canonical": {
                        "web": ["nested.example", "NESTED2.example"],
                        "api": {"v1": "api.nested.example"},
                    },
                    "aliases": [
                        {"alt": "alt.nested.example"},
                        ["ALT2.nested.example", {"deep": ["deep.nested.example"]}],
                    ],
                }
            },
            "web-app-no-server": {},
            "web-app-server-not-dict": "nope",
            "web-app-domains-not-dict": {"domains": "nope"},
        }

    def test_iter_app_domains_empty_on_invalid_structure(self):
        self.assertEqual(
            list(
                _application_domain_index.iter_app_domains(
                    self.applications["web-app-no-server"]
                )
            ),
            [],
        )
        self.assertEqual(
            list(
                _application_domain_index.iter_app_domains(
                    self.applications["web-app-server-not-dict"]
                )
            ),
            [],
        )
        self.assertEqual(
            list(
                _application_domain_index.iter_app_domains(
                    self.applications["web-app-domains-not-dict"]
                )
            ),
            [],
        )

    def test_iter_app_domains_flattens_all_supported_shapes(self):
        got_a = list(
            _application_domain_index.iter_app_domains(self.applications["web-app-a"])
        )
        self.assertEqual(
            got_a,
            ["a.example", "www.a.example", "A.ALIAS.EXAMPLE"],
        )

        got_b = list(
            _application_domain_index.iter_app_domains(self.applications["web-app-b"])
        )
        self.assertEqual(got_b, ["b.example"])

        got_c = list(
            _application_domain_index.iter_app_domains(self.applications["web-app-c"])
        )
        self.assertEqual(got_c, ["c.example", "api.c.example", "www.c.example"])

        got_nested = list(
            _application_domain_index.iter_app_domains(
                self.applications["web-app-nested"]
            )
        )
        self.assertEqual(
            got_nested,
            [
                "nested.example",
                "NESTED2.example",
                "api.nested.example",
                "alt.nested.example",
                "ALT2.nested.example",
                "deep.nested.example",
            ],
        )

    def test_build_domain_index_case_insensitive(self):
        idx = _application_domain_index.build_domain_index(self.applications)

        self.assertEqual(idx["a.example"], "web-app-a")
        self.assertEqual(idx["www.a.example"], "web-app-a")
        self.assertEqual(idx["a.alias.example"], "web-app-a")
        self.assertEqual(idx["b.example"], "web-app-b")
        self.assertEqual(idx["c.example"], "web-app-c")
        self.assertEqual(idx["api.c.example"], "web-app-c")
        self.assertEqual(idx["www.c.example"], "web-app-c")
        self.assertEqual(idx["nested.example"], "web-app-nested")
        self.assertEqual(idx["nested2.example"], "web-app-nested")
        self.assertEqual(idx["api.nested.example"], "web-app-nested")
        self.assertEqual(idx["alt.nested.example"], "web-app-nested")
        self.assertEqual(idx["alt2.nested.example"], "web-app-nested")
        self.assertEqual(idx["deep.nested.example"], "web-app-nested")

    def test_build_domain_index_type_check(self):
        with self.assertRaises(AnsibleError):
            _application_domain_index.build_domain_index("nope")  # type: ignore[arg-type]

    def test_build_domain_index_detects_collision_case_insensitive(self):
        apps = {
            "app1": {"domains": {"canonical": ["X.EXAMPLE"], "aliases": []}},
            "app2": {"domains": {"canonical": ["x.example"], "aliases": []}},
        }
        with self.assertRaises(AnsibleError) as ctx:
            _application_domain_index.build_domain_index(apps)
        self.assertIn("domain collision", str(ctx.exception).lower())

    def test_resolve_app_id_for_domain_found(self):
        self.assertEqual(
            _application_domain_index.resolve_app_id_for_domain(
                self.applications, "a.example"
            ),
            "web-app-a",
        )
        self.assertEqual(
            _application_domain_index.resolve_app_id_for_domain(
                self.applications, "WWW.A.EXAMPLE"
            ),
            "web-app-a",
        )
        self.assertEqual(
            _application_domain_index.resolve_app_id_for_domain(
                self.applications, "api.c.example"
            ),
            "web-app-c",
        )
        self.assertEqual(
            _application_domain_index.resolve_app_id_for_domain(
                self.applications, "DEEP.NESTED.EXAMPLE"
            ),
            "web-app-nested",
        )

    def test_resolve_app_id_for_domain_not_found_or_empty(self):
        self.assertIsNone(
            _application_domain_index.resolve_app_id_for_domain(
                self.applications, "missing.example"
            )
        )
        self.assertIsNone(
            _application_domain_index.resolve_app_id_for_domain(self.applications, "")
        )
        self.assertIsNone(
            _application_domain_index.resolve_app_id_for_domain(
                self.applications, "   "
            )
        )
        self.assertIsNone(
            _application_domain_index.resolve_app_id_for_domain(self.applications, None)  # type: ignore[arg-type]
        )

    def test_resolve_app_id_for_domain_raises_on_collision(self):
        apps = {
            "app1": {"domains": {"canonical": ["x.example"], "aliases": []}},
            "app2": {"domains": {"canonical": ["X.EXAMPLE"], "aliases": []}},
        }
        with self.assertRaises(AnsibleError):
            _application_domain_index.resolve_app_id_for_domain(apps, "x.example")


if __name__ == "__main__":
    unittest.main()
