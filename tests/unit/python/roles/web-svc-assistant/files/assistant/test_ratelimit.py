from __future__ import annotations

import unittest

from . import load

ratelimit = load("ratelimit")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestRateLimiter(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.limiter = ratelimit.RateLimiter(3, 60, clock=self.clock)

    def test_requests_within_the_limit_pass(self) -> None:
        verdicts = [self.limiter.check("198.51.100.7") for _ in range(3)]
        self.assertEqual([v.allowed for v in verdicts], [True, True, True])

    def test_the_request_over_the_limit_says_when_to_retry(self) -> None:
        for _ in range(3):
            self.limiter.check("198.51.100.7")
        self.clock.now += 20
        verdict = self.limiter.check("198.51.100.7")
        self.assertEqual(verdict, ratelimit.Verdict(False, 40))

    def test_the_window_slides(self) -> None:
        for _ in range(3):
            self.limiter.check("198.51.100.7")
        self.clock.now += 60
        self.assertTrue(self.limiter.check("198.51.100.7").allowed)

    def test_each_client_has_its_own_budget(self) -> None:
        for _ in range(3):
            self.limiter.check("198.51.100.7")
        self.assertTrue(self.limiter.check("198.51.100.8").allowed)
        self.assertFalse(self.limiter.check("198.51.100.7").allowed)

    def test_an_idle_client_is_forgotten(self) -> None:
        self.limiter.check("198.51.100.7")
        self.clock.now += 120
        self.limiter.check("198.51.100.8")
        self.assertEqual(self.limiter.clients(), 1)

    def test_a_limit_below_one_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            ratelimit.RateLimiter(0, 60)


class TestClientKey(unittest.TestCase):
    def test_the_proxy_set_address_is_the_key(self) -> None:
        self.assertEqual(
            ratelimit.client_key({"x-real-ip": "203.0.113.4"}), "203.0.113.4"
        )

    def test_a_request_without_the_header_shares_one_budget(self) -> None:
        self.assertEqual(ratelimit.client_key({}), ratelimit.UNKNOWN_CLIENT)


if __name__ == "__main__":
    unittest.main()
