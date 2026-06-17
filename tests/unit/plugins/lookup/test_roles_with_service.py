"""Unit tests for ``plugins/lookup/roles_with_service.py``.

The lookup enumerates consumer roles for a given service by walking the
merged applications mapping. The applications loader is mocked so the
tests stay hermetic — no filesystem access into ``roles/``.
"""

import importlib.util
import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _DummyTemplar:
    def __init__(self, available_variables):
        self.available_variables = available_variables


class RolesWithServiceLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module(
            "plugins/lookup/roles_with_service.py",
            "lookup_roles_with_service",
        )

    def _make_lookup(self, available_vars: dict | None = None):
        lm = self.mod.LookupModule()
        lm._templar = _DummyTemplar(available_vars or {})
        return lm

    def _run(self, terms, applications: dict, vars_: dict | None = None):
        """Run the lookup with `get_merged_applications` and the `tls`
        sub-lookup patched to stay hermetic. The stubbed tls resolves
        ``[role_id, "url.base"]`` to a deterministic URL so the lookup
        can finish building each result entry without the real domain
        machinery."""
        lookup = self._make_lookup(vars_ or {})

        class _StubTls:
            def run(self, terms_, variables=None, **kwargs):
                return [f"https://{terms_[0]}.example.com"]

        with (
            patch.object(
                self.mod, "get_merged_applications", return_value=applications
            ),
            patch.object(self.mod.lookup_loader, "get", return_value=_StubTls()),
        ):
            return lookup.run(terms, variables=vars_ or {})

    def test_zero_terms_raises(self):
        with self.assertRaises(AnsibleError):
            self._run([], {})

    def test_two_terms_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["dashboard", "extra"], {})

    def test_blank_service_name_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["   "], {})

    def test_consumer_with_truthy_enabled_and_shared_is_included(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "dashboard": {"enabled": True, "shared": True},
                },
                "server": {"domains": {"canonical": ["foo.example.com"]}},
            },
        }
        result = self._run(["dashboard"], applications)
        self.assertEqual(
            result,
            [
                [
                    {
                        "id": "web-app-foo",
                        "canonical_domain": "foo.example.com",
                        "canonical_url": "https://web-app-foo.example.com",
                    }
                ]
            ],
        )

    def test_falsy_enabled_excludes_role(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "dashboard": {"enabled": False, "shared": True},
                },
                "server": {"domains": {"canonical": ["foo.example.com"]}},
            },
        }
        self.assertEqual(self._run(["dashboard"], applications), [[]])

    def test_falsy_shared_excludes_role(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "dashboard": {"enabled": True, "shared": False},
                },
                "server": {"domains": {"canonical": ["foo.example.com"]}},
            },
        }
        self.assertEqual(self._run(["dashboard"], applications), [[]])

    def test_missing_service_block_excludes_role(self):
        applications = {
            "web-app-foo": {
                "services": {"oidc": {"enabled": True}},
                "server": {"domains": {"canonical": ["foo.example.com"]}},
            },
        }
        self.assertEqual(self._run(["dashboard"], applications), [[]])

    def test_role_without_canonical_domain_is_skipped(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "dashboard": {"enabled": True, "shared": True},
                },
                "server": {"domains": {}},
            },
        }
        self.assertEqual(self._run(["dashboard"], applications), [[]])

    def test_canonical_as_string_is_accepted(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "dashboard": {"enabled": True, "shared": True},
                },
                "server": {"domains": {"canonical": "foo.example.com"}},
            },
        }
        result = self._run(["dashboard"], applications)
        self.assertEqual(
            result,
            [
                [
                    {
                        "id": "web-app-foo",
                        "canonical_domain": "foo.example.com",
                        "canonical_url": "https://web-app-foo.example.com",
                    }
                ]
            ],
        )

    def test_results_are_sorted_by_role_id(self):
        applications = {
            "web-app-zeta": {
                "services": {"prometheus": {"enabled": True, "shared": True}},
                "server": {"domains": {"canonical": ["zeta.example.com"]}},
            },
            "web-app-alpha": {
                "services": {"prometheus": {"enabled": True, "shared": True}},
                "server": {"domains": {"canonical": ["alpha.example.com"]}},
            },
            "web-app-mu": {
                "services": {"prometheus": {"enabled": True, "shared": True}},
                "server": {"domains": {"canonical": ["mu.example.com"]}},
            },
        }
        result = self._run(["prometheus"], applications)[0]
        self.assertEqual(
            [r["id"] for r in result],
            ["web-app-alpha", "web-app-mu", "web-app-zeta"],
        )

    def test_different_services_resolve_independently(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "dashboard": {"enabled": True, "shared": True},
                    "matomo": {"enabled": False, "shared": True},
                },
                "server": {"domains": {"canonical": ["foo.example.com"]}},
            },
            "web-app-bar": {
                "services": {
                    "dashboard": {"enabled": False, "shared": True},
                    "matomo": {"enabled": True, "shared": True},
                },
                "server": {"domains": {"canonical": ["bar.example.com"]}},
            },
        }
        dashboard_consumers = self._run(["dashboard"], applications)[0]
        matomo_consumers = self._run(["matomo"], applications)[0]
        self.assertEqual(
            [r["id"] for r in dashboard_consumers],
            ["web-app-foo"],
        )
        self.assertEqual(
            [r["id"] for r in matomo_consumers],
            ["web-app-bar"],
        )

    def test_non_dict_app_config_skipped(self):
        applications = {
            "web-app-foo": "not-a-dict",
            "web-app-bar": {
                "services": {"dashboard": {"enabled": True, "shared": True}},
                "server": {"domains": {"canonical": ["bar.example.com"]}},
            },
        }
        result = self._run(["dashboard"], applications)[0]
        self.assertEqual([r["id"] for r in result], ["web-app-bar"])

    def test_canonical_with_empty_first_entry_is_skipped(self):
        applications = {
            "web-app-foo": {
                "services": {"dashboard": {"enabled": True, "shared": True}},
                "server": {"domains": {"canonical": ["", "foo.example.com"]}},
            },
        }
        # First entry is empty string -> falsy -> skipped per the helper.
        self.assertEqual(self._run(["dashboard"], applications), [[]])

    def test_unrendered_jinja_strings_are_treated_as_truthy(self):
        """In a real Ansible play, ``get_merged_applications`` runs the
        merged payload through ``_render_with_templar`` so a value like
        ``"{{ 'web-app-dashboard' in group_names }}"`` arrives at this
        lookup as the literal ``True`` / ``False`` it resolved to.

        Without a templar (CLI smoke tests, scripts that call
        ``get_merged_applications(templar=None)``), the raw Jinja string
        passes through unchanged. Python's ``bool()`` on a non-empty
        string is ``True``, so the lookup is over-inclusive on that
        path. This test pins that contract: callers MUST run the
        applications payload through a templar before passing it in,
        otherwise every role with both keys present is returned
        regardless of deployment state.
        """
        applications = {
            "web-app-foo": {
                "services": {
                    "dashboard": {
                        "enabled": "{{ 'web-app-dashboard' in group_names }}",
                        "shared": "{{ 'web-app-dashboard' in group_names }}",
                    },
                },
                "server": {"domains": {"canonical": ["foo.example.com"]}},
            },
        }
        result = self._run(["dashboard"], applications)[0]
        self.assertEqual(
            [r["id"] for r in result],
            ["web-app-foo"],
            "non-empty Jinja string is truthy under bool(); the lookup "
            "relies on a templar-rendered payload for correct filtering",
        )

    def test_group_names_scopes_to_deployed_consumers(self):
        applications = {
            "web-app-foo": {
                "services": {"logout": {"enabled": True, "shared": True}},
                "server": {"domains": {"canonical": ["foo.example.com"]}},
            },
            "web-app-bar": {
                "services": {"logout": {"enabled": True, "shared": True}},
                "server": {"domains": {"canonical": ["bar.example.com"]}},
            },
        }
        result = self._run(
            ["logout"], applications, vars_={"group_names": ["web-app-foo"]}
        )[0]
        self.assertEqual([r["id"] for r in result], ["web-app-foo"])

    def test_self_provider_is_excluded(self):
        applications = {
            "web-svc-logout": {
                "services": {"logout": {"enabled": True, "shared": True}},
                "server": {"domains": {"canonical": ["logout.example.com"]}},
            },
            "web-app-foo": {
                "services": {"logout": {"enabled": True, "shared": True}},
                "server": {"domains": {"canonical": ["foo.example.com"]}},
            },
        }
        result = self._run(["logout"], applications)[0]
        self.assertEqual([r["id"] for r in result], ["web-app-foo"])

    def test_absent_group_names_keeps_all_consumers(self):
        applications = {
            "web-app-foo": {
                "services": {"logout": {"enabled": True, "shared": True}},
                "server": {"domains": {"canonical": ["foo.example.com"]}},
            },
            "web-app-bar": {
                "services": {"logout": {"enabled": True, "shared": True}},
                "server": {"domains": {"canonical": ["bar.example.com"]}},
            },
        }
        result = self._run(["logout"], applications)[0]
        self.assertEqual([r["id"] for r in result], ["web-app-bar", "web-app-foo"])


if __name__ == "__main__":
    unittest.main()
