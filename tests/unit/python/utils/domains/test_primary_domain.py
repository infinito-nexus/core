import unittest

from ansible.errors import AnsibleFilterError

from utils.domains.primary_domain import get_domain, get_primary_domain


class TestPrimaryDomain(unittest.TestCase):
    def test_string_value(self):
        domains = {"app": "example.com"}
        self.assertEqual(get_primary_domain(domains, "app"), "example.com")

    def test_dict_value(self):
        domains = {"app": {"primary": "primary.com", "secondary": "secondary.com"}}
        self.assertEqual(get_primary_domain(domains, "app"), "primary.com")

    def test_list_value(self):
        domains = {"app": ["first.com", "second.com"]}
        self.assertEqual(get_primary_domain(domains, "app"), "first.com")

    def test_get_domain_alias_delegates_to_primary_domain(self):
        domains = {"app": "example.com"}
        self.assertEqual(get_domain(domains, "app"), "example.com")

    def test_missing_application_id(self):
        domains = {"app": "example.com"}
        with self.assertRaises(AnsibleFilterError):
            get_primary_domain(domains, "missing")

    def test_domains_not_dict(self):
        with self.assertRaises(AnsibleFilterError):
            get_primary_domain(["not", "a", "dict"], "app")

    def test_empty_string(self):
        domains = {"app": ""}
        with self.assertRaises(AnsibleFilterError):
            get_primary_domain(domains, "app")

    def test_empty_dict(self):
        domains = {"app": {}}
        with self.assertRaises(AnsibleFilterError):
            get_primary_domain(domains, "app")

    def test_empty_list(self):
        domains = {"app": []}
        with self.assertRaises(AnsibleFilterError):
            get_primary_domain(domains, "app")

    def test_non_string_in_dict(self):
        domains = {"app": {"key": 123}}
        with self.assertRaises(AnsibleFilterError):
            get_primary_domain(domains, "app")

    def test_non_string_in_list(self):
        domains = {"app": [123]}
        with self.assertRaises(AnsibleFilterError):
            get_primary_domain(domains, "app")


if __name__ == "__main__":
    unittest.main()
