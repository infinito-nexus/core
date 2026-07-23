import sys
import unittest
from unittest import mock
from unittest.mock import patch

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _ensure_repo_root_on_syspath():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


_ensure_repo_root_on_syspath()

from plugins.lookup.domain import LookupModule  # noqa: E402


class TestDomainLookup(unittest.TestCase):
    """Unit tests for the `domain` lookup.

    The plugin delegates the canonical-domains map build to the `domains`
    lookup reached through the Ansible lookup loader. These tests patch that
    loader so we assert only the plugin's dispatch + primary-domain extraction
    logic, not the merge pipeline (which has its own integration tests).
    """

    def setUp(self):
        self.lookup = LookupModule()
        self.lookup._loader = mock.MagicMock()

    def run_lookup(self, application_id, domains_map):
        with patch("plugins.lookup.domain.lookup_loader") as loader_mock:

            def _get(name, *a, **k):
                if name == "domains":
                    return mock.MagicMock(run=lambda *_a, **_k: [domains_map])
                return mock.MagicMock(run=lambda *_a, **_k: [{}])

            loader_mock.get.side_effect = _get
            return self.lookup.run(
                terms=[application_id],
                variables={},
            )

    def test_string_domain(self):
        self.assertEqual(
            self.run_lookup("app", {"app": "example.com"}), ["example.com"]
        )

    def test_list_domain(self):
        self.assertEqual(
            self.run_lookup("app", {"app": ["example.com", "alt.example.com"]}),
            ["example.com"],
        )

    def test_dict_domain(self):
        self.assertEqual(
            self.run_lookup(
                "app",
                {"app": {"primary": "example.com", "secondary": "alt.example.com"}},
            ),
            ["example.com"],
        )

    def test_missing_application_id(self):
        with self.assertRaises(AnsibleError):
            self.run_lookup_raw([])

    def test_unknown_application_id(self):
        with self.assertRaises(AnsibleError):
            self.run_lookup("unknown", {"app": "example.com"})

    def test_empty_string_domain(self):
        with self.assertRaises(AnsibleError):
            self.run_lookup("app", {"app": ""})

    def test_empty_list_domain(self):
        with self.assertRaises(AnsibleError):
            self.run_lookup("app", {"app": []})

    def test_empty_dict_domain(self):
        with self.assertRaises(AnsibleError):
            self.run_lookup("app", {"app": {}})

    def test_invalid_application_id_type(self):
        with self.assertRaises(AnsibleError):
            self.run_lookup_raw([123])

    def run_lookup_raw(self, terms):
        with patch("plugins.lookup.domain.lookup_loader") as loader_mock:
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [{"app": "example.com"}]
            )
            return self.lookup.run(terms=terms, variables={})


if __name__ == "__main__":
    unittest.main()
