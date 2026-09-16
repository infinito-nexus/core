import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.update.collection_source import (
    RATIO,
    WINDOW,
    append_sample,
    decide,
    load_history,
)


def _samples(galaxy, git, count=WINDOW):
    return [{"galaxy": galaxy, "git": git} for _ in range(count)]


class TestAppendSample(unittest.TestCase):
    def test_the_window_never_grows_past_its_size(self):
        history = _samples(10.0, 10.0, WINDOW)

        grown = append_sample(history, {"galaxy": 99.0, "git": 1.0})

        self.assertEqual(len(grown), WINDOW)
        self.assertEqual(grown[-1], {"galaxy": 99.0, "git": 1.0})

    def test_the_oldest_sample_is_the_one_dropped(self):
        history = [{"galaxy": float(i), "git": 1.0} for i in range(WINDOW)]

        grown = append_sample(history, {"galaxy": 99.0, "git": 1.0})

        self.assertEqual(grown[0]["galaxy"], 1.0)


class TestDecide(unittest.TestCase):
    def test_below_a_full_window_the_default_is_left_alone(self):
        history = _samples(300.0, 10.0, WINDOW - 1)

        verdict = decide(history, "galaxy")

        self.assertFalse(verdict.changed)
        self.assertEqual(verdict.samples, WINDOW - 1)

    def test_exactly_the_ratio_swaps_the_preferred_source(self):
        history = _samples(30.0, 10.0)

        verdict = decide(history, "galaxy")

        self.assertTrue(verdict.changed)
        self.assertEqual(verdict.proposed, "git")

    def test_just_under_the_ratio_keeps_the_preferred_source(self):
        history = _samples(10.0 * RATIO - 0.1, 10.0)

        self.assertFalse(decide(history, "galaxy").changed)

    def test_a_failed_install_ranks_worse_than_any_duration(self):
        history = _samples(None, 10.0)

        verdict = decide(history, "galaxy")

        self.assertTrue(verdict.changed)
        self.assertEqual(verdict.proposed, "git")
        self.assertEqual(verdict.medians["galaxy"], float("inf"))

    def test_the_faster_source_is_never_swapped_away_from(self):
        history = _samples(10.0, 300.0)

        self.assertFalse(decide(history, "galaxy").changed)

    def test_both_sources_failing_changes_nothing(self):
        history = _samples(None, None)

        self.assertFalse(decide(history, "galaxy").changed)

    def test_a_single_outlier_does_not_move_the_median(self):
        history = _samples(10.0, 10.0, WINDOW - 1)
        history = append_sample(history, {"galaxy": 9000.0, "git": 10.0})

        self.assertFalse(decide(history, "galaxy").changed)

    def test_the_verdict_is_taken_from_the_preferred_side(self):
        history = _samples(10.0, 30.0)

        verdict = decide(history, "git")

        self.assertTrue(verdict.changed)
        self.assertEqual(verdict.proposed, "galaxy")


class TestLoadHistory(unittest.TestCase):
    def test_a_missing_file_reads_as_an_empty_history(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(load_history(Path(tmp) / "absent.json"), [])

    def test_a_corrupt_file_reads_as_an_empty_history(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            path.write_text("{not json", encoding="utf-8")

            self.assertEqual(load_history(path), [])

    def test_a_written_history_round_trips(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            history = _samples(1.0, 2.0, 3)
            path.write_text(json.dumps(history), encoding="utf-8")

            self.assertEqual(load_history(path), history)


if __name__ == "__main__":
    unittest.main()
