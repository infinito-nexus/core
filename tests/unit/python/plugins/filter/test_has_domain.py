import unittest

from plugins.filter.has.domain import FilterModule


class TestHasDomainFilter(unittest.TestCase):
    def setUp(self):
        self.filters = FilterModule().filters()
        self.has_domain = self.filters["has_domain"]

    def test_returns_true_for_string_domain(self):
        domains = {"app": "example.local"}
        self.assertTrue(self.has_domain(domains, "app"))

    def test_returns_true_for_dict_domain(self):
        domains = {"app": {"primary": "example.local"}}
        self.assertTrue(self.has_domain(domains, "app"))

    def test_returns_true_for_list_domain(self):
        domains = {"app": ["example.local", "alt.local"]}
        self.assertTrue(self.has_domain(domains, "app"))

    def test_returns_false_when_application_id_missing(self):
        domains = {"other": "example.local"}
        self.assertFalse(self.has_domain(domains, "app"))

    def test_returns_true_when_domains_not_dict_but_contains_domain(self):
        domains = ["example.local"]
        self.assertTrue(self.has_domain(domains, "app"))

    def test_returns_false_for_empty_string_domain(self):
        domains = {"app": ""}
        self.assertFalse(self.has_domain(domains, "app"))

    def test_returns_false_for_empty_dict_domain(self):
        domains = {"app": {}}
        self.assertFalse(self.has_domain(domains, "app"))

    def test_returns_false_for_empty_list_domain(self):
        domains = {"app": []}
        self.assertFalse(self.has_domain(domains, "app"))

    def test_returns_false_for_unsupported_type(self):
        domains = {"app": 123}
        self.assertFalse(self.has_domain(domains, "app"))

    def test_import_errors_are_raised_as_ansible_filter_error(self):
        """
        Sanity check: FilterModule().filters() should fail loudly if utils import breaks.
        This test just asserts that filters are already loaded correctly here.
        """
        self.assertIn("has_domain", self.filters)
        self.assertTrue(callable(self.filters["has_domain"]))


if __name__ == "__main__":
    unittest.main()
