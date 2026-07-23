import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.curl import curl


_RETRY = " --retry 3 --retry-all-errors --retry-delay 2"


class TestCurlFilter(unittest.TestCase):
    def test_default_connect_timeout(self):
        self.assertEqual(
            curl(30), "curl -s --connect-timeout 5 --max-time 30" + _RETRY
        )

    def test_custom_values(self):
        self.assertEqual(
            curl(300, connect_timeout=10),
            "curl -s --connect-timeout 10 --max-time 300" + _RETRY,
        )

    def test_numeric_string_input(self):
        self.assertEqual(
            curl("45"), "curl -s --connect-timeout 5 --max-time 45" + _RETRY
        )

    def test_retries_zero_opts_out(self):
        self.assertEqual(
            curl(30, retries=0), "curl -s --connect-timeout 5 --max-time 30"
        )

    def test_custom_retries(self):
        self.assertEqual(
            curl(60, retries=5),
            "curl -s --connect-timeout 5 --max-time 60 --retry 5 --retry-all-errors --retry-delay 2",
        )

    def test_non_numeric_raises(self):
        with self.assertRaises(AnsibleFilterError):
            curl("plenty")

    def test_non_positive_raises(self):
        with self.assertRaises(AnsibleFilterError):
            curl(0)
        with self.assertRaises(AnsibleFilterError):
            curl(30, connect_timeout=-1)

    def test_negative_retries_raises(self):
        with self.assertRaises(AnsibleFilterError):
            curl(30, retries=-1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
