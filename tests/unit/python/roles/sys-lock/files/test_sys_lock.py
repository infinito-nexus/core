#!/usr/bin/env python3
import importlib.util
import io
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


def fake_systemctl(active_state, sub_state):
    """Build a ``subprocess.run`` stand-in answering like systemctl.

    Args:
        active_state: value reported for ``ActiveState`` and by ``is-active``.
        sub_state: value reported for ``SubState``.

    Returns:
        A callable for ``mock.patch.object(..., side_effect=...)``.
    """

    def run(argv, **_kwargs):
        completed = mock.Mock()
        if "is-active" in argv:
            completed.stdout = f"{active_state}\n".encode()
        else:
            completed.stdout = (
                f"ActiveState={active_state}\nSubState={sub_state}\n".encode()
            )
        return completed

    return run


class CheckServiceActiveTests(TestCase):
    def _with_state(self, active_state, sub_state):
        return mock.patch.object(
            SCRIPT.subprocess,
            "run",
            side_effect=fake_systemctl(active_state, sub_state),
        )

    def test_a_running_simple_service_holds_the_lock(self):
        with self._with_state("active", "running"):
            self.assertTrue(SCRIPT.check_service_active("x.service"))

    def test_a_oneshot_in_its_main_process_holds_the_lock(self):
        with self._with_state("activating", "start"):
            self.assertTrue(SCRIPT.check_service_active("x.service"))

    def test_a_unit_winding_down_holds_the_lock(self):
        with self._with_state("deactivating", "stop-post"):
            self.assertTrue(SCRIPT.check_service_active("x.service"))

    def test_a_reloading_unit_holds_the_lock(self):
        with self._with_state("reloading", "reload"):
            self.assertTrue(SCRIPT.check_service_active("x.service"))

    def test_a_unit_past_its_main_process_holds_the_lock(self):
        with self._with_state("activating", "start-post"):
            self.assertTrue(SCRIPT.check_service_active("x.service"))

    def test_a_unit_waiting_in_its_own_lock_does_not(self):
        with self._with_state("activating", "start-pre"):
            self.assertFalse(SCRIPT.check_service_active("x.service"))

    def test_a_finished_remain_after_exit_unit_does_not(self):
        with self._with_state("active", "exited"):
            self.assertFalse(SCRIPT.check_service_active("x.service"))

    def test_inactive_does_not(self):
        with self._with_state("inactive", "dead"):
            self.assertFalse(SCRIPT.check_service_active("x.service"))

    def test_failed_does_not(self):
        with self._with_state("failed", "failed"):
            self.assertFalse(SCRIPT.check_service_active("x.service"))

    def test_an_unknown_unit_does_not(self):
        with self._with_state("inactive", "dead"):
            self.assertFalse(SCRIPT.check_service_active("missing.service"))


class TwoWaitersTests(TestCase):
    def test_two_units_waiting_on_each_other_both_pass(self):
        with (
            mock.patch.object(
                SCRIPT.subprocess,
                "run",
                side_effect=fake_systemctl("activating", "start-pre"),
            ),
            mock.patch.object(SCRIPT.time, "sleep") as sleep,
        ):
            SCRIPT.main(["a.service", "b.service"], ["a.service"], 60)
            SCRIPT.main(["a.service", "b.service"], ["b.service"], 60)
        sleep.assert_not_called()


class TimeoutTests(TestCase):
    def test_a_timeout_fails_the_unit_by_default(self):
        with (
            mock.patch.object(SCRIPT, "check_service_active", return_value=True),
            mock.patch.object(SCRIPT.time, "sleep"),
            self.assertRaises(SCRIPT.AttemptError),
        ):
            SCRIPT.main(["busy.service"], [], SCRIPT.BREAK_TIME_SECONDS * 2)

    def test_a_timeout_warns_and_returns_when_asked_to_proceed(self):
        with (
            mock.patch.object(SCRIPT, "check_service_active", return_value=True),
            mock.patch.object(SCRIPT.time, "sleep"),
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            SCRIPT.main(
                ["busy.service"],
                [],
                SCRIPT.BREAK_TIME_SECONDS * 2,
                proceed_on_timeout=True,
            )
        self.assertIn("proceeding without it", stderr.getvalue())
        self.assertNotIn("All required services have stopped", stdout.getvalue())


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
