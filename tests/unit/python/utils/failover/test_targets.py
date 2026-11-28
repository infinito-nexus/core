from __future__ import annotations

import unittest

from utils.failover.targets import (
    CEILINGS_S,
    ENGINES,
    FAULTS,
    MIN_REPLICAS_MAX_LAG_S,
    RECLONE_CEILING_S,
    RENEW_DEADLINE_S,
    ROLLING_GOAL_S,
    SAMPLE_TOLERANCE_S,
    budget_s,
    evaluate,
    evaluate_isolated_master,
    evaluate_reclone,
    evaluate_stall,
    evaluate_writer_move,
    evaluate_writer_overlap,
)


class TestBudgetTable(unittest.TestCase):
    def test_every_engine_has_a_budget_for_every_fault(self):
        for engine in ENGINES:
            for fault in FAULTS:
                self.assertGreater(budget_s(engine, fault), 0, (engine, fault))

    def test_no_budget_exceeds_its_ceiling(self):
        for engine in ENGINES:
            for fault, ceiling in CEILINGS_S.items():
                self.assertLessEqual(budget_s(engine, fault), ceiling, (engine, fault))

    def test_redis_node_budget_covers_a_split_sentinel_vote(self):
        self.assertEqual(budget_s("redis", "node"), 31)

    def test_unknown_engine_fails(self):
        with self.assertRaises(KeyError):
            budget_s("mongodb", "kill")


class TestEvaluate(unittest.TestCase):
    def test_within_budget_and_nothing_lost_passes(self):
        verdict = evaluate("postgres", "kill", gap_s=20.0, lost=0, interval_s=0.2)
        self.assertEqual(verdict.failures, [])

    def test_gap_over_budget_fails(self):
        verdict = evaluate("postgres", "kill", gap_s=29.0, lost=0, interval_s=0.2)
        self.assertEqual(len(verdict.failures), 1)
        self.assertIn("29.0", verdict.failures[0])

    def test_durable_tier_fails_on_any_loss(self):
        verdict = evaluate("mariadb", "node", gap_s=1.0, lost=1, interval_s=0.2)
        self.assertTrue(any("lost" in f for f in verdict.failures))

    def test_best_effort_tier_tolerates_ten_seconds_of_writes(self):
        ok = evaluate("redis", "node", gap_s=1.0, lost=50, interval_s=0.2)
        self.assertEqual(ok.failures, [])
        self.assertTrue(ok.notes)
        bad = evaluate("redis", "node", gap_s=1.0, lost=51, interval_s=0.2)
        self.assertTrue(bad.failures)

    def test_rolling_goal_is_reported_not_failed(self):
        verdict = evaluate(
            "postgres", "rolling", gap_s=ROLLING_GOAL_S + 0.5, lost=0, interval_s=0.2
        )
        self.assertEqual(verdict.failures, [])
        self.assertTrue(any("goal" in n for n in verdict.notes))

    def test_standalone_steady_state_has_a_tight_budget(self):
        self.assertTrue(
            evaluate("openldap", "none", gap_s=3.0, lost=0, interval_s=0.2).failures
        )

    def test_rolling_gap_over_the_ceiling_names_the_ceiling(self):
        verdict = evaluate("postgres", "rolling", gap_s=11.0, lost=0, interval_s=0.2)
        self.assertTrue(any("10s ceiling" in f for f in verdict.failures))


class TestWriterOverlap(unittest.TestCase):
    def test_overlap_within_the_renew_deadline_is_noted(self):
        verdict = evaluate_writer_overlap([(0, 8000)])
        self.assertEqual(verdict.failures, [])
        self.assertTrue(verdict.notes)

    def test_overlap_beyond_the_renew_deadline_fails(self):
        limit_ms = int((RENEW_DEADLINE_S + SAMPLE_TOLERANCE_S) * 1000)
        verdict = evaluate_writer_overlap([(0, 1000), (5000, 5000 + limit_ms + 1)])
        self.assertEqual(len(verdict.failures), 1)

    def test_no_overlap_is_silent(self):
        verdict = evaluate_writer_overlap([])
        self.assertEqual((verdict.failures, verdict.notes), ([], []))


class TestWriterMove(unittest.TestCase):
    def test_move_within_the_budget_passes(self):
        self.assertEqual(
            evaluate_writer_move("openldap", "node", moved_after_s=20.0).failures, []
        )

    def test_late_or_missing_move_fails(self):
        late = budget_s("openldap", "node") + SAMPLE_TOLERANCE_S + 1
        self.assertTrue(
            evaluate_writer_move("openldap", "node", moved_after_s=late).failures
        )
        self.assertTrue(
            evaluate_writer_move("openldap", "node", moved_after_s=None).failures
        )


class TestReclone(unittest.TestCase):
    def test_within_fifteen_minutes_passes(self):
        self.assertEqual(evaluate_reclone(RECLONE_CEILING_S).failures, [])

    def test_late_or_never_fails(self):
        self.assertTrue(evaluate_reclone(RECLONE_CEILING_S + 1).failures)
        self.assertTrue(evaluate_reclone(None).failures)


class TestStall(unittest.TestCase):
    def test_stalled_and_resumed_passes(self):
        self.assertEqual(evaluate_stall(acked_while_down=[], resumed=True).failures, [])

    def test_ack_without_replicas_or_no_resume_fails(self):
        self.assertEqual(
            len(evaluate_stall(acked_while_down=[7], resumed=False).failures), 2
        )


class TestIsolatedMaster(unittest.TestCase):
    def test_writes_within_the_lag_window_pass(self):
        verdict = evaluate_isolated_master(
            accepted_ms=[1000, 9000], isolated_ms=0, limit_s=MIN_REPLICAS_MAX_LAG_S
        )
        self.assertEqual(verdict.failures, [])
        self.assertTrue(verdict.notes)

    def test_writes_after_the_lag_window_fail(self):
        late = int((MIN_REPLICAS_MAX_LAG_S + SAMPLE_TOLERANCE_S) * 1000) + 1
        verdict = evaluate_isolated_master(
            accepted_ms=[late], isolated_ms=0, limit_s=MIN_REPLICAS_MAX_LAG_S
        )
        self.assertTrue(verdict.failures)

    def test_a_restarted_stale_master_may_take_no_write_at_all(self):
        verdict = evaluate_isolated_master(accepted_ms=[1], isolated_ms=0, limit_s=None)
        self.assertTrue(verdict.failures)
        self.assertEqual(
            evaluate_isolated_master(
                accepted_ms=[], isolated_ms=0, limit_s=None
            ).failures,
            [],
        )


if __name__ == "__main__":
    unittest.main()
