"""The sampler decides when a request is worth comparing across options."""

from __future__ import annotations

import unittest

from . import SAMPLING

Sampler = SAMPLING.Sampler


class SamplerRequestsTestCase(unittest.TestCase):
    def test_it_fires_once_per_interval_and_starts_counting_again(self) -> None:
        sampler = Sampler("requests", 3)

        self.assertEqual(
            [sampler.due() for _ in range(7)],
            [False, False, True, False, False, True, False],
        )

    def test_an_interval_of_one_compares_every_request(self) -> None:
        sampler = Sampler("requests", 1)

        self.assertEqual([sampler.due() for _ in range(3)], [True, True, True])

    def test_an_interval_below_one_is_raised_to_one(self) -> None:
        sampler = Sampler("requests", 0)

        self.assertTrue(sampler.due())


class SamplerSecondsTestCase(unittest.TestCase):
    def test_the_first_request_fires_and_the_next_waits_out_the_interval(self) -> None:
        now = [100.0]
        sampler = Sampler("seconds", 10, clock=lambda: now[0])

        self.assertTrue(sampler.due())
        now[0] = 105.0
        self.assertFalse(sampler.due())
        now[0] = 110.0
        self.assertTrue(sampler.due())

    def test_the_clock_is_only_advanced_by_a_firing_request(self) -> None:
        now = [0.0]
        sampler = Sampler("seconds", 10, clock=lambda: now[0])
        sampler.due()

        now[0] = 9.0
        self.assertFalse(sampler.due())
        now[0] = 9.5
        self.assertFalse(sampler.due())
        now[0] = 10.0
        self.assertTrue(sampler.due())


class SamplerProbabilityTestCase(unittest.TestCase):
    def test_a_draw_below_the_odds_fires(self) -> None:
        sampler = Sampler("probability", 4, draw=lambda: 0.2)

        self.assertTrue(sampler.due())

    def test_a_draw_on_or_above_the_odds_does_not(self) -> None:
        sampler = Sampler("probability", 4, draw=lambda: 0.25)

        self.assertFalse(sampler.due())


class UnknownTriggerTestCase(unittest.TestCase):
    def test_it_falls_back_to_the_time_based_rule(self) -> None:
        """An unknown trigger must not compare every request forever."""
        now = [0.0]
        sampler = Sampler("whatever", 10, clock=lambda: now[0])

        self.assertTrue(sampler.due())
        self.assertFalse(sampler.due())


if __name__ == "__main__":
    unittest.main()
