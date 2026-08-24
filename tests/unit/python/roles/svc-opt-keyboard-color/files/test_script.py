#!/usr/bin/env python3
import datetime
import importlib.util
from unittest import TestCase, main

from . import PROJECT_ROOT


def load_target_module():
    script_path = (
        PROJECT_ROOT
        / "roles"
        / "svc-opt-keyboard-color"
        / "files"
        / "python"
        / "script.py"
    )

    if not script_path.is_file():
        raise FileNotFoundError(f"Target script not found at: {script_path}")

    spec = importlib.util.spec_from_file_location("keyboard_color_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


SCRIPT = load_target_module()

COLOR_TIMES = {
    "06:00": ("ff0000", "00ff00"),
    "12:00": ("00ff00", "0000ff"),
    "18:00": ("0000ff", "ff0000"),
}


class HexToRgbTests(TestCase):
    def test_it_splits_a_six_digit_string_into_three_channels(self):
        self.assertEqual(SCRIPT.hex_to_rgb("ff8000"), (255, 128, 0))

    def test_it_reads_each_channel_as_base_sixteen(self):
        self.assertEqual(SCRIPT.hex_to_rgb("0a0b0c"), (10, 11, 12))

    def test_a_short_string_is_rejected_rather_than_padded(self):
        with self.assertRaises(ValueError):
            SCRIPT.hex_to_rgb("fff")

    def test_a_long_string_is_rejected_rather_than_truncated(self):
        with self.assertRaises(ValueError):
            SCRIPT.hex_to_rgb("ff8000ff")


class CalculateColorTests(TestCase):
    def test_ratio_zero_is_the_start_color(self):
        self.assertEqual(SCRIPT.calculate_color("ff0000", "00ff00", 0), "ff0000")

    def test_ratio_one_is_the_end_color(self):
        self.assertEqual(SCRIPT.calculate_color("ff0000", "00ff00", 1), "00ff00")

    def test_the_midpoint_interpolates_every_channel(self):
        self.assertEqual(SCRIPT.calculate_color("000000", "ffffff", 0.5), "808080")

    def test_every_channel_stays_two_digits_wide(self):
        result = SCRIPT.calculate_color("000000", "0f0f0f", 0.5)
        self.assertEqual(len(result), 6)
        self.assertEqual(result, "080808")


class GetCurrentPeriodTests(TestCase):
    def test_a_time_inside_a_period_returns_that_period_colors(self):
        self.assertEqual(
            SCRIPT.get_current_period(datetime.time(12, 0), COLOR_TIMES),
            ("ff0000", "00ff00"),
        )

    def test_a_time_before_the_first_period_wraps_to_the_last(self):
        self.assertEqual(
            SCRIPT.get_current_period(datetime.time(3, 0), COLOR_TIMES),
            ("0000ff", "ff0000"),
        )

    def test_a_time_after_the_last_period_returns_the_first(self):
        self.assertEqual(
            SCRIPT.get_current_period(datetime.time(23, 0), COLOR_TIMES),
            ("ff0000", "00ff00"),
        )


class CalculateTransitionRatioTests(TestCase):
    def test_the_start_of_a_window_is_ratio_zero(self):
        self.assertEqual(
            SCRIPT.calculate_transition_ratio(
                datetime.time(6, 0), datetime.time(6, 0), datetime.time(12, 0)
            ),
            0,
        )

    def test_the_end_of_a_window_is_ratio_one(self):
        self.assertEqual(
            SCRIPT.calculate_transition_ratio(
                datetime.time(12, 0), datetime.time(6, 0), datetime.time(12, 0)
            ),
            1,
        )

    def test_the_middle_of_a_window_is_ratio_one_half(self):
        self.assertEqual(
            SCRIPT.calculate_transition_ratio(
                datetime.time(9, 0), datetime.time(6, 0), datetime.time(12, 0)
            ),
            0.5,
        )

    def test_a_zero_length_window_returns_zero_instead_of_dividing_by_it(self):
        self.assertEqual(
            SCRIPT.calculate_transition_ratio(
                datetime.time(6, 0), datetime.time(6, 0), datetime.time(6, 0)
            ),
            0,
        )


if __name__ == "__main__":
    main()
