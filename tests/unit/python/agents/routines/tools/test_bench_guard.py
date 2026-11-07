from __future__ import annotations

import unittest

from agents.routines.tools.bench_guard import (
    Measurement,
    invalid_reasons,
    language_reason,
)

_CLEAN = Measurement(source="profile_tasks", image="sha256:aaa")


class TestComparisonGuard(unittest.TestCase):
    def test_a_like_for_like_comparison_may_be_judged(self) -> None:
        self.assertEqual(invalid_reasons(_CLEAN, _CLEAN), [])

    def test_red_fixture_a_shared_machine_discards_the_comparison(self) -> None:
        for job in ("gate", "deploy", "translation"):
            with self.subTest(job=job):
                disturbed = Measurement(
                    source="profile_tasks", image="sha256:aaa", neighbours=(job,)
                )
                self.assertEqual(
                    invalid_reasons(_CLEAN, disturbed),
                    [f"after: the machine also ran {job}"],
                )

    def test_an_unrelated_neighbour_does_not_discard(self) -> None:
        quiet = Measurement(
            source="profile_tasks", image="sha256:aaa", neighbours=("editor",)
        )
        self.assertEqual(invalid_reasons(quiet, _CLEAN), [])

    def test_mixed_sources_or_images_discard(self) -> None:
        self.assertEqual(
            invalid_reasons(
                _CLEAN, Measurement(source="TASKS RECAP", image="sha256:bbb")
            ),
            [
                "measured from profile_tasks and TASKS RECAP",
                "the two runs started from different image states",
            ],
        )

    def test_a_one_time_cost_or_hidden_retries_discard(self) -> None:
        self.assertEqual(
            invalid_reasons(
                Measurement(source="profile_tasks", image="sha256:aaa", retries=3),
                Measurement(
                    source="profile_tasks", image="sha256:aaa", one_time_cost=True
                ),
            ),
            [
                "before: 3 FAILED - RETRYING hide a failure",
                "after: paid a one-time cost",
            ],
        )


class TestLanguageChoice(unittest.TestCase):
    def test_python_always_stands(self) -> None:
        self.assertEqual(
            language_reason(
                "python", measured_cost="process_spawns", every_deploy=True
            ),
            "",
        )

    def test_red_fixture_spawns_and_round_trips_keep_python(self) -> None:
        for cost in ("process_spawns", "round_trips"):
            with self.subTest(cost=cost):
                self.assertIn(
                    "one Python process",
                    language_reason("rust", measured_cost=cost, every_deploy=True),
                )

    def test_a_cpu_bound_loop_on_every_deploy_may_leave_python(self) -> None:
        self.assertEqual(
            language_reason("rust", measured_cost="cpu_bound_loop", every_deploy=True),
            "",
        )

    def test_a_cpu_bound_loop_off_the_deploy_path_keeps_python(self) -> None:
        self.assertNotEqual(
            language_reason("rust", measured_cost="cpu_bound_loop", every_deploy=False),
            "",
        )

    def test_an_unmeasured_cost_keeps_python(self) -> None:
        self.assertNotEqual(
            language_reason("go", measured_cost="", every_deploy=True), ""
        )


if __name__ == "__main__":
    unittest.main()
