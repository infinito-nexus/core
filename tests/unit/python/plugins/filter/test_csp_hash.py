import base64
import hashlib
import unittest

from plugins.filter.csp_filters import FilterModule


class TestCspHash(unittest.TestCase):
    def setUp(self):
        self.f = FilterModule().filters()["csp_hash"]

    def test_it_returns_the_quoted_sha256_source_of_the_snippet(self):
        snippet = "body{margin:0}"
        digest = base64.b64encode(hashlib.sha256(snippet.encode()).digest()).decode()
        self.assertEqual(self.f(snippet), f"'sha256-{digest}'")

    def test_one_changed_byte_changes_the_source(self):
        self.assertNotEqual(self.f("a{color:red}"), self.f("a{color:red} "))


if __name__ == "__main__":
    unittest.main()
