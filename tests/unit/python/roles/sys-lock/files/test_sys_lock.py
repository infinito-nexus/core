#!/usr/bin/env python3
import importlib.util
from unittest import TestCase, main, mock

from . import PROJECT_ROOT


def load_target_module():
    script_path = (
        PROJECT_ROOT / "roles" / "sys-lock" / "files" / "python" / "sys-lock.py"
    )

    if not script_path.is_file():
        raise FileNotFoundError(f"Target script not found at: {script_path}")

    spec = importlib.util.spec_from_file_location("sys_lock_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


SCRIPT = load_target_module()


class ParseTimeToSecondsTests(TestCase):
    def test_bare_seconds(self):
        self.assertEqual(SCRIPT.parse_time_to_seconds("45s"), 45)

    def test_minutes_use_the_three_letter_unit(self):
        self.assertEqual(SCRIPT.parse_time_to_seconds("30min"), 1800)

    def test_hours(self):
        self.assertEqual(SCRIPT.parse_time_to_seconds("1h"), 3600)

    def test_the_longest_matching_unit_wins(self):
        """``min`` must not be read as the ``n``-less ``s`` or as bare digits."""
        self.assertEqual(SCRIPT.parse_time_to_seconds("2min"), 120)

    def test_an_unknown_unit_raises_rather_than_defaulting(self):
        with self.assertRaises(ValueError):
            SCRIPT.parse_time_to_seconds("10d")

    def test_a_bare_number_raises_rather_than_assuming_seconds(self):
        with self.assertRaises(ValueError):
            SCRIPT.parse_time_to_seconds("60")


class FilterServicesTests(TestCase):
    def test_it_drops_every_ignored_service(self):
        self.assertEqual(
            SCRIPT.filter_services(
                ["a.service", "b.service", "c.service"], ["b.service"]
            ),
            ["a.service", "c.service"],
        )

    def test_it_preserves_the_original_order(self):
        self.assertEqual(
            SCRIPT.filter_services(["c", "a", "b"], []),
            ["c", "a", "b"],
        )

    def test_ignoring_everything_leaves_nothing(self):
        self.assertEqual(SCRIPT.filter_services(["a", "b"], ["a", "b"]), [])


class GetMaxAttemptsTests(TestCase):
    def test_the_budget_is_the_timeout_divided_by_the_break(self):
        self.assertEqual(SCRIPT.get_max_attempts(60), 60 // SCRIPT.BREAK_TIME_SECONDS)

    def test_a_timeout_shorter_than_one_break_yields_no_attempts(self):
        self.assertEqual(SCRIPT.get_max_attempts(SCRIPT.BREAK_TIME_SECONDS - 1), 0)

    def test_the_result_is_a_whole_number_of_attempts(self):
        self.assertIsInstance(SCRIPT.get_max_attempts(61), int)


class CheckServiceActiveTests(TestCase):
    def _with_status(self, status):
        completed = mock.Mock()
        completed.stdout = status.encode("utf-8")
        return mock.patch.object(SCRIPT.subprocess, "run", return_value=completed)

    def test_active_counts_as_active(self):
        with self._with_status("active"):
            self.assertTrue(SCRIPT.check_service_active("x.service"))

    def test_activating_also_counts_as_active(self):
        """A service still starting must hold the lock, or the gate races it."""
        with self._with_status("activating"):
            self.assertTrue(SCRIPT.check_service_active("x.service"))

    def test_inactive_does_not(self):
        with self._with_status("inactive"):
            self.assertFalse(SCRIPT.check_service_active("x.service"))

    def test_failed_does_not(self):
        with self._with_status("failed"):
            self.assertFalse(SCRIPT.check_service_active("x.service"))


class CheckAnyServiceActiveTests(TestCase):
    def test_one_active_service_is_enough(self):
        with mock.patch.object(
            SCRIPT, "check_service_active", side_effect=[False, True]
        ):
            self.assertTrue(SCRIPT.check_any_service_active(["a", "b"]))

    def test_all_inactive_is_false(self):
        with mock.patch.object(SCRIPT, "check_service_active", return_value=False):
            self.assertFalse(SCRIPT.check_any_service_active(["a", "b"]))

    def test_an_empty_list_is_false(self):
        self.assertFalse(SCRIPT.check_any_service_active([]))


if __name__ == "__main__":
    main()
