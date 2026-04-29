# tests/unit/plugins/lookup/test_domain_lookup.py
import os
import sys
import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError


def _ensure_repo_root_on_syspath():
    # tests/unit/plugins/lookup/test_domain_lookup.py -> repo_root
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


_ensure_repo_root_on_syspath()

from plugins.lookup.domain import LookupModule  # noqa: E402


class TestDomainLookup(unittest.TestCase):
    """Unit tests for the `domain` lookup.

    The plugin delegates the canonical-domains map build to
    utils.cache.domains.get_merged_domains. These tests patch that helper
    so we assert only the plugin's dispatch + primary-domain extraction logic,
    not the merge pipeline (which has its own integration tests).
    """

    def setUp(self):
        self.lookup = LookupModule()

    def run_lookup(self, application_id, domains_map):
        with patch(
            "plugins.lookup.domain.get_merged_domains",
            return_value=domains_map,
        ):
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
            with patch(
                "plugins.lookup.domain.get_merged_domains",
                return_value={"app": "example.com"},
            ):
                self.lookup.run(terms=[], variables={})

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
            with patch(
                "plugins.lookup.domain.get_merged_domains",
                return_value={"app": "example.com"},
            ):
                self.lookup.run(terms=[123], variables={})


if __name__ == "__main__":
    unittest.main()
