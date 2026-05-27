#!/usr/bin/env python3

import unittest

from utils.cert_utils import CertUtils


class TestCertUtilsMatches(unittest.TestCase):
    def setUp(self):
        # prepare your test cases
        self.tests = [
            # Exact matches
            ("example.com", "example.com", True),
            ("www.example.com", "www.example.com", True),
            ("api.example.com", "api.example.com", True),
            # Wildcard matches
            ("sub.example.com", "*.example.com", True),
            ("www.example.com", "*.example.com", True),
            # Wildcard non-matches
            ("example.com", "*.example.com", False),  # base domain is not covered
            ("deep.sub.example.com", "*.example.com", False),  # too deep
            (
                "sub.deep.example.com",
                "*.deep.example.com",
                True,
            ),  # correct: one level below
            # Special cases
            ("deep.api.example.com", "*.api.example.com", True),
            (
                "api.example.com",
                "*.api.example.com",
                False,
            ),  # base not covered by wildcard
            # Completely different domains
            ("test.other.com", "*.example.com", False),
        ]

    def test_matches(self):
        for domain, san, expected in self.tests:
            with self.subTest(domain=domain, san=san):
                result = CertUtils.matches(domain, san)
                self.assertEqual(
                    result,
                    expected,
                    msg=f"CertUtils.matches({domain!r}, {san!r}) returned {result}, expected {expected}",
                )


if __name__ == "__main__":
    unittest.main()
