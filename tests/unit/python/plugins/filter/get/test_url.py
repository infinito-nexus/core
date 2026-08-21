import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.get.url import FilterModule


class TestGetUrlFilter(unittest.TestCase):
    def setUp(self):
        self.get_url = FilterModule().filters()["get_url"]

    def test_string_domain(self):
        domains = {"app": "example.com"}
        url = self.get_url(domains, "app", "https")
        self.assertEqual(url, "https://example.com")

    def test_dict_domain(self):
        domains = {"app": {"primary": "primary.com", "secondary": "secondary.com"}}
        url = self.get_url(domains, "app", "http")
        self.assertEqual(url, "http://primary.com")

    def test_list_domain(self):
        domains = {"app": ["first.com", "second.com"]}
        url = self.get_url(domains, "app", "ftp")
        self.assertEqual(url, "ftp://first.com")

    def test_missing_application_id(self):
        domains = {"app": "example.com"}
        with self.assertRaises(AnsibleFilterError):
            self.get_url(domains, "missing", "https")

    def test_domains_not_dict(self):
        with self.assertRaises(AnsibleFilterError):
            self.get_url(["not", "a", "dict"], "app", "https")

    def test_empty_string_domain(self):
        domains = {"app": ""}
        with self.assertRaises(AnsibleFilterError):
            self.get_url(domains, "app", "https")

    def test_empty_dict_domain(self):
        domains = {"app": {}}
        with self.assertRaises(AnsibleFilterError):
            self.get_url(domains, "app", "https")

    def test_empty_list_domain(self):
        domains = {"app": []}
        with self.assertRaises(AnsibleFilterError):
            self.get_url(domains, "app", "https")

    def test_non_string_in_dict_domain(self):
        domains = {"app": {"key": 123}}
        with self.assertRaises(AnsibleFilterError):
            self.get_url(domains, "app", "https")

    def test_non_string_in_list_domain(self):
        domains = {"app": [123]}
        with self.assertRaises(AnsibleFilterError):
            self.get_url(domains, "app", "https")

    def test_protocol_not_string(self):
        domains = {"app": "example.com"}
        with self.assertRaises(AnsibleFilterError):
            self.get_url(domains, "app", 123)


if __name__ == "__main__":
    unittest.main()
