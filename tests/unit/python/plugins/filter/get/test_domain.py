import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.get.domain import FilterModule


class TestGetDomainFilter(unittest.TestCase):
    def setUp(self):
        self.get_domain = FilterModule().filters()["get_domain"]

    def test_string_value(self):
        domains = {"app": "example.com"}
        self.assertEqual(self.get_domain(domains, "app"), "example.com")

    def test_dict_value(self):
        domains = {"app": {"primary": "primary.com", "secondary": "secondary.com"}}
        self.assertEqual(self.get_domain(domains, "app"), "primary.com")

    def test_list_value(self):
        domains = {"app": ["first.com", "second.com"]}
        self.assertEqual(self.get_domain(domains, "app"), "first.com")

    def test_missing_application_id(self):
        domains = {"app": "example.com"}
        with self.assertRaises(AnsibleFilterError):
            self.get_domain(domains, "missing")

    def test_domains_not_dict(self):
        with self.assertRaises(AnsibleFilterError):
            self.get_domain(["not", "a", "dict"], "app")

    def test_empty_string(self):
        domains = {"app": ""}
        with self.assertRaises(AnsibleFilterError):
            self.get_domain(domains, "app")

    def test_empty_dict(self):
        domains = {"app": {}}
        with self.assertRaises(AnsibleFilterError):
            self.get_domain(domains, "app")

    def test_empty_list(self):
        domains = {"app": []}
        with self.assertRaises(AnsibleFilterError):
            self.get_domain(domains, "app")

    def test_non_string_in_dict(self):
        domains = {"app": {"key": 123}}
        with self.assertRaises(AnsibleFilterError):
            self.get_domain(domains, "app")

    def test_non_string_in_list(self):
        domains = {"app": [123]}
        with self.assertRaises(AnsibleFilterError):
            self.get_domain(domains, "app")


if __name__ == "__main__":
    unittest.main()
