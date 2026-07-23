import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.curl import curl


class TestCurlFilter(unittest.TestCase):
    def test_default_connect_timeout(self):
        self.assertEqual(curl(30), "curl -s --connect-timeout 5 --max-time 30")

    def test_custom_values(self):
        self.assertEqual(
            curl(300, connect_timeout=10),
            "curl -s --connect-timeout 10 --max-time 300",
        )

    def test_numeric_string_input(self):
        self.assertEqual(curl("45"), "curl -s --connect-timeout 5 --max-time 45")

    def test_non_numeric_raises(self):
        with self.assertRaises(AnsibleFilterError):
            curl("plenty")

    def test_non_positive_raises(self):
        with self.assertRaises(AnsibleFilterError):
            curl(0)
        with self.assertRaises(AnsibleFilterError):
            curl(30, connect_timeout=-1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
