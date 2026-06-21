"""Unit tests for the variant-deploy runtime-budget guard."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from cli.administration.deploy.development import runtime_budget as rb


class _Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class TestParseDurationSeconds(unittest.TestCase):
    def test_units_and_plain_seconds(self) -> None:
        cases = {
            "6h": 21600,
            "48h": 172800,
            "90m": 5400,
            "3600": 3600,
            "3600s": 3600,
            "1.5h": 5400,
            " 2H ": 7200,
        }
        for raw, want in cases.items():
            self.assertEqual(rb._parse_duration_seconds(raw), want, raw)

    def test_unset_or_invalid_returns_none(self) -> None:
        for raw in ["", "   ", "abc", "h", "12x"]:
            self.assertIsNone(rb._parse_duration_seconds(raw), raw)


class TestRuntimeBudget(unittest.TestCase):
    def test_unset_budget_never_exhausts(self) -> None:
        clock = _Clock()
        with (
            patch.object(rb.time, "monotonic", clock),
            patch.object(rb, "warning") as mock_warning,
            patch.dict(os.environ, {"INFINITO_MAX_RUNTIME": ""}),
        ):
            budget = rb.RuntimeBudget()
            self.assertIsNone(budget.max_seconds)
            budget.start_round()
            clock.t = 10_000
            budget.end_round()
            self.assertFalse(budget.exhausted(1, 3))
            mock_warning.assert_not_called()

    def test_first_round_always_runs(self) -> None:
        clock = _Clock()
        with (
            patch.object(rb.time, "monotonic", clock),
            patch.dict(os.environ, {"INFINITO_MAX_RUNTIME": "1s"}),
        ):
            budget = rb.RuntimeBudget()
            self.assertFalse(budget.exhausted(0, 3))

    def test_exhausts_and_warns_when_projection_exceeds(self) -> None:
        clock = _Clock()
        with (
            patch.object(rb.time, "monotonic", clock),
            patch.object(rb, "warning") as mock_warning,
            patch.dict(os.environ, {"INFINITO_MAX_RUNTIME": "3600"}),
        ):
            budget = rb.RuntimeBudget()
            budget.start_round()
            clock.t = 1000
            budget.end_round()
            # elapsed 1000 + longest 1000 + 1800 buffer = 3800 > 3600
            self.assertTrue(budget.exhausted(1, 3))
            mock_warning.assert_called_once()

    def test_does_not_exhaust_when_projection_fits(self) -> None:
        clock = _Clock()
        with (
            patch.object(rb.time, "monotonic", clock),
            patch.object(rb, "warning") as mock_warning,
            patch.dict(os.environ, {"INFINITO_MAX_RUNTIME": "2h"}),
        ):
            budget = rb.RuntimeBudget()
            budget.start_round()
            clock.t = 1000
            budget.end_round()
            # elapsed 1000 + longest 1000 + 1800 buffer = 3800 <= 7200
            self.assertFalse(budget.exhausted(1, 3))
            mock_warning.assert_not_called()

    def test_longest_round_tracks_max(self) -> None:
        clock = _Clock()
        with (
            patch.object(rb.time, "monotonic", clock),
            patch.dict(os.environ, {"INFINITO_MAX_RUNTIME": "1h"}),
        ):
            budget = rb.RuntimeBudget()
            budget.start_round()
            clock.t = 1000
            budget.end_round()
            clock.t = 1200
            budget.start_round()
            clock.t = 1700
            budget.end_round()
            self.assertEqual(budget._longest_round, 1000)


if __name__ == "__main__":
    unittest.main()
