from __future__ import annotations

import threading
import unittest

from utils.failover.sampling import (
    Round,
    Sampler,
    dual_writer_detail,
    dual_writer_windows,
    first_new_writer,
    gtid_choice_violation,
    gtid_total,
)


def _round(at_ms: int, *writers: str, gtids: dict | None = None) -> Round:
    names = ("a", "b", "c")
    return Round(
        at_ms=at_ms,
        writers={n: n in writers for n in names},
        gtids=gtids or {},
    )


class TestDualWriterWindows(unittest.TestCase):
    def test_single_writer_throughout_has_no_window(self):
        rounds = [_round(t, "a") for t in (0, 1000, 2000)]
        self.assertEqual(dual_writer_windows(rounds), [])

    def test_window_spans_from_first_dual_round_to_first_single_round(self):
        rounds = [
            _round(0, "a"),
            _round(1000, "a", "b"),
            _round(2000, "a", "b"),
            _round(3000, "b"),
        ]
        self.assertEqual(dual_writer_windows(rounds), [(1000, 3000)])

    def test_open_window_ends_at_the_last_round(self):
        rounds = [_round(0, "a", "b"), _round(5000, "a", "b")]
        self.assertEqual(dual_writer_windows(rounds), [(0, 5000)])

    def test_unreachable_instances_never_count_as_writers(self):
        rounds = [Round(at_ms=0, writers={"a": True, "b": None, "c": False})]
        self.assertEqual(dual_writer_windows(rounds), [])


class TestFirstNewWriter(unittest.TestCase):
    def test_ignores_rounds_before_the_fault_and_the_old_writer(self):
        rounds = [_round(0, "b"), _round(1000, "a"), _round(4000, "c")]
        self.assertEqual(first_new_writer(rounds, after_ms=500, old="a"), ("c", 4000))

    def test_none_when_nobody_took_over(self):
        rounds = [_round(1000, "a"), _round(2000)]
        self.assertIsNone(first_new_writer(rounds, after_ms=0, old="a"))


class TestGtid(unittest.TestCase):
    def test_total_sums_sequences_like_the_elector(self):
        self.assertEqual(gtid_total("0-1-10,1-2-5"), 15)
        self.assertEqual(gtid_total(""), 0)

    def test_unreadable_position_is_none(self):
        self.assertIsNone(gtid_total(None))
        self.assertIsNone(gtid_total("garbage"))

    def test_promoting_the_most_advanced_replica_passes(self):
        rounds = [
            _round(1000, gtids={"b": "0-1-100", "c": "0-1-90"}),
            _round(2000, "b", gtids={"b": "0-1-100", "c": "0-1-90"}),
        ]
        self.assertIsNone(gtid_choice_violation(rounds, fault_ms=500, old="a"))

    def test_promoting_a_lagging_replica_is_a_violation(self):
        rounds = [
            _round(1000, gtids={"b": "0-1-100", "c": "0-1-90"}),
            _round(2000, "c", gtids={"b": "0-1-100", "c": "0-1-90"}),
        ]
        violation = gtid_choice_violation(rounds, fault_ms=500, old="a")
        self.assertIn("c was promoted", violation)
        self.assertIn("b was at 100", violation)

    def test_a_peer_holding_the_winners_first_writes_is_no_violation(self):
        rounds = [
            _round(1000, gtids={"b": "0-1-450", "c": "0-1-450"}),
            _round(2000, "c", gtids={"b": "0-2-454", "c": "0-2-452"}),
        ]
        self.assertIsNone(gtid_choice_violation(rounds, fault_ms=500, old="a"))

    def test_old_writer_positions_are_not_compared(self):
        rounds = [_round(2000, "c", gtids={"a": "0-1-500", "c": "0-1-90"})]
        self.assertIsNone(gtid_choice_violation(rounds, fault_ms=500, old="a"))

    def test_no_promotion_is_reported(self):
        rounds = [_round(2000, gtids={"b": "0-1-1"})]
        self.assertIn("no instance", gtid_choice_violation(rounds, fault_ms=0, old="a"))


class TestDualWriterDetail(unittest.TestCase):
    def test_names_the_writers_and_the_wait_until_the_next_round(self):
        rounds = [
            _round(1000, "a"),
            _round(2000, "a", "b"),
            _round(64700, "b"),
        ]
        self.assertEqual(
            dual_writer_detail(rounds), "a+b at 2000, next round 62.7s later"
        )


class TestSampler(unittest.TestCase):
    def test_collects_rounds_and_errors_until_stopped(self):
        calls = []
        seen_two = threading.Event()

        def sample() -> Round:
            calls.append(1)
            if len(calls) == 2:
                seen_two.set()
                raise RuntimeError("node paused")
            return _round(len(calls), "a")

        sampler = Sampler(sample, interval_s=0.001).start()
        self.assertTrue(seen_two.wait(5))
        rounds = sampler.stop()
        self.assertGreaterEqual(len(rounds), 1)
        self.assertEqual(sampler.errors[0], "node paused")


if __name__ == "__main__":
    unittest.main()
