"""Unit tests for ``plugins/lookup/service_extensions.py``.

The lookup walks ``group_names`` and returns a
``{consumer_id: [extension, …]}`` map sourced from each role's merged
``meta/services.yml``. The ``applications`` lookup is mocked via
``lookup_loader`` so the tests stay hermetic.
"""

import importlib.util
import unittest
from unittest import mock
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


class ServiceExtensionsLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module(
            "plugins/lookup/service_extensions.py",
            "lookup_service_extensions",
        )

    def _make_lookup(self, available_vars: dict | None = None):
        lm = self.mod.LookupModule()
        lm._templar = _DummyTemplar(available_vars or {})
        lm._loader = mock.MagicMock()
        return lm

    def _run(
        self,
        terms,
        applications: dict,
        group_names: list[str],
    ):
        lookup = self._make_lookup({"group_names": group_names})
        with patch.object(self.mod, "lookup_loader") as loader_mock:
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [applications]
            )
            return lookup.run(terms, variables={"group_names": group_names})

    def test_zero_terms_raises(self):
        with self.assertRaises(AnsibleError):
            self._run([], {}, [])

    def test_two_terms_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["postgres", "extra"], {}, [])

    def test_blank_service_name_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["   "], {}, [])

    def test_non_list_group_names_raises(self):
        lookup = self._make_lookup({"group_names": "not-a-list"})
        with (
            patch.object(self.mod, "lookup_loader") as loader_mock,
            self.assertRaises(AnsibleError),
        ):
            loader_mock.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [{}])
            lookup.run(
                ["postgres"],
                variables={"group_names": "not-a-list"},
            )

    def test_role_with_extensions_is_included(self):
        applications = {
            "web-app-bookwyrm": {
                "services": {
                    "postgres": {
                        "enabled": True,
                        "extensions": ["bloom"],
                    },
                },
            },
        }
        result = self._run(["postgres"], applications, ["web-app-bookwyrm"])
        self.assertEqual(result, [{"web-app-bookwyrm": ["bloom"]}])

    def test_role_with_extensions_and_shared_false_is_included(self):
        applications = {
            "web-app-bookwyrm": {
                "services": {
                    "postgres": {
                        "enabled": True,
                        "shared": False,
                        "extensions": ["bloom"],
                    },
                },
            },
        }
        result = self._run(["postgres"], applications, ["web-app-bookwyrm"])
        self.assertEqual(result, [{"web-app-bookwyrm": ["bloom"]}])

    def test_role_not_in_group_names_is_skipped(self):
        applications = {
            "web-app-bookwyrm": {
                "services": {
                    "postgres": {
                        "enabled": True,
                        "extensions": ["bloom"],
                    },
                },
            },
        }
        result = self._run(["postgres"], applications, [])
        self.assertEqual(result, [{}])

    def test_role_with_disabled_service_is_skipped(self):
        applications = {
            "web-app-bookwyrm": {
                "services": {
                    "postgres": {
                        "enabled": False,
                        "extensions": ["bloom"],
                    },
                },
            },
        }
        result = self._run(["postgres"], applications, ["web-app-bookwyrm"])
        self.assertEqual(result, [{}])

    def test_role_without_extensions_field_is_omitted(self):
        applications = {
            "web-app-foo": {
                "services": {"postgres": {"enabled": True}},
            },
        }
        result = self._run(["postgres"], applications, ["web-app-foo"])
        self.assertEqual(result, [{}])

    def test_role_with_empty_extensions_list_is_omitted(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "postgres": {"enabled": True, "extensions": []},
                },
            },
        }
        result = self._run(["postgres"], applications, ["web-app-foo"])
        self.assertEqual(result, [{}])

    def test_multiple_roles_are_aggregated(self):
        applications = {
            "web-app-bookwyrm": {
                "services": {
                    "postgres": {
                        "enabled": True,
                        "extensions": ["bloom"],
                    },
                },
            },
            "web-app-discourse": {
                "services": {
                    "postgres": {
                        "enabled": True,
                        "extensions": ["pg_trgm", "vector"],
                    },
                },
            },
        }
        result = self._run(
            ["postgres"],
            applications,
            ["web-app-bookwyrm", "web-app-discourse"],
        )
        self.assertEqual(
            result,
            [
                {
                    "web-app-bookwyrm": ["bloom"],
                    "web-app-discourse": ["pg_trgm", "vector"],
                }
            ],
        )

    def test_different_service_keys_resolve_independently(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "postgres": {
                        "enabled": True,
                        "extensions": ["bloom"],
                    },
                    "mariadb": {
                        "enabled": True,
                        "extensions": ["someplugin"],
                    },
                },
            },
        }
        postgres = self._run(["postgres"], applications, ["web-app-foo"])[0]
        mariadb = self._run(["mariadb"], applications, ["web-app-foo"])[0]
        self.assertEqual(postgres, {"web-app-foo": ["bloom"]})
        self.assertEqual(mariadb, {"web-app-foo": ["someplugin"]})

    def test_non_dict_app_config_is_skipped(self):
        applications = {
            "web-app-foo": "not-a-dict",
            "web-app-bar": {
                "services": {
                    "postgres": {
                        "enabled": True,
                        "extensions": ["bloom"],
                    },
                },
            },
        }
        result = self._run(
            ["postgres"],
            applications,
            ["web-app-foo", "web-app-bar"],
        )
        self.assertEqual(result, [{"web-app-bar": ["bloom"]}])

    def test_extensions_with_blanks_are_filtered(self):
        applications = {
            "web-app-foo": {
                "services": {
                    "postgres": {
                        "enabled": True,
                        "extensions": ["bloom", "  ", ""],
                    },
                },
            },
        }
        result = self._run(["postgres"], applications, ["web-app-foo"])
        self.assertEqual(result, [{"web-app-foo": ["bloom"]}])


if __name__ == "__main__":
    unittest.main()
