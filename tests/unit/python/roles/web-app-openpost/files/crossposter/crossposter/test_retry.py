from __future__ import annotations

import random
import unittest
from datetime import UTC, datetime
from email.utils import format_datetime

from crossposter import retry

NOW = 1_800_000_000.0


def seeded(seed: int) -> random.Random:
    return random.Random(seed)  # noqa: S311 reproducible jitter for the assertions


class TestBackoff(unittest.TestCase):
    def test_the_jitter_stays_within_the_exponential_window(self) -> None:
        rng = seeded(7)
        for attempt in range(1, 8):
            window = min(3600, 30 * 2 ** (attempt - 1))
            for _ in range(50):
                self.assertLessEqual(retry.backoff(attempt, 30, 3600, rng), window)

    def test_the_window_is_capped(self) -> None:
        rng = seeded(1)
        self.assertLessEqual(
            max(retry.backoff(40, 30, 3600, rng) for _ in range(200)), 3600
        )

    def test_jitter_spreads_the_delays(self) -> None:
        rng = seeded(3)
        self.assertGreater(
            len({round(retry.backoff(4, 30, 3600, rng), 3) for _ in range(20)}), 10
        )


class TestServerHints(unittest.TestCase):
    def test_retry_after_seconds(self) -> None:
        self.assertEqual(retry.server_delay({"Retry-After": "120"}, NOW), 120)

    def test_retry_after_http_date(self) -> None:
        when = format_datetime(datetime.fromtimestamp(NOW + 90, tz=UTC), usegmt=True)
        self.assertEqual(retry.server_delay({"retry-after": when}, NOW), 90)

    def test_epoch_rate_limit_reset(self) -> None:
        self.assertEqual(
            retry.server_delay({"x-rate-limit-reset": str(int(NOW + 45))}, NOW), 45
        )

    def test_iso_rate_limit_reset(self) -> None:
        iso = (
            datetime.fromtimestamp(NOW + 30, tz=UTC).isoformat().replace("+00:00", "Z")
        )
        self.assertEqual(retry.server_delay({"X-RateLimit-Reset": iso}, NOW), 30)

    def test_delta_rate_limit_reset(self) -> None:
        self.assertEqual(retry.server_delay({"RateLimit-Reset": "12"}, NOW), 12)

    def test_without_hints_there_is_no_server_delay(self) -> None:
        self.assertEqual(retry.server_delay({}, NOW), 0)

    def test_a_reset_in_the_past_means_no_wait(self) -> None:
        self.assertEqual(
            retry.server_delay({"x-rate-limit-reset": str(int(NOW - 10))}, NOW), 0
        )


class TestDelay(unittest.TestCase):
    def test_the_server_hint_wins_over_a_shorter_backoff(self) -> None:
        rng = seeded(5)
        self.assertGreaterEqual(
            retry.delay(1, {"Retry-After": "600"}, NOW, 30, 3600, rng), 600
        )

    def test_without_a_hint_the_backoff_applies(self) -> None:
        rng = seeded(5)
        self.assertLessEqual(retry.delay(2, {}, NOW, 30, 3600, rng), 60)


class TestTransient(unittest.TestCase):
    def test_network_errors_rate_limits_and_server_errors_are_transient(self) -> None:
        for status in (None, 408, 425, 429, 500, 502, 503, 504):
            self.assertTrue(retry.transient(status), status)

    def test_client_errors_are_permanent(self) -> None:
        for status in (400, 401, 403, 404, 409, 422):
            self.assertFalse(retry.transient(status), status)
