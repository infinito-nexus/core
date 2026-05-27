import unittest

from ansible.errors import AnsibleFilterError

# Import the filter plugin
from plugins.filter.to_primary_domain import FilterModule


class TestToPrimaryDomain(unittest.TestCase):
    def setUp(self):
        self.filtermod = FilterModule()

    def test_valid_domains(self):
        cases = [
            ("example.com", "example.com"),
            ("www.example.com", "example.com"),
            ("foo.bar.example.com", "example.com"),
            ("mail.test.example.co.uk", "example.co.uk"),
            ("test.foo.bar.jp", "bar.jp"),
        ]
        for input_domain, expected in cases:
            with self.subTest(domain=input_domain):
                self.assertEqual(
                    self.filtermod.to_primary_domain(input_domain), expected
                )

    def test_invalid_domains(self):
        invalid_cases = [
            "localhost",  # not a real domain
            1234,  # not a string
            "",  # empty string
        ]
        for input_domain in invalid_cases:
            with (
                self.subTest(domain=input_domain),
                self.assertRaises(AnsibleFilterError),
            ):
                self.filtermod.to_primary_domain(input_domain)


if __name__ == "__main__":
    unittest.main()
