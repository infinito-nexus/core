from __future__ import annotations

import unittest
from typing import ClassVar

from cli.administration.deploy.ci import timings
from tests.utils.ci.job_names import deploy_job_name
from utils.github.variant.pools import DISTROS, FILESYSTEMS


def _job(
    name: str,
    *,
    minutes: float,
    conclusion: str = "success",
    status: str = "completed",
) -> dict:
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "startedAt": "2026-09-23T10:00:00Z",
        "completedAt": f"2026-09-23T{10 + int(minutes) // 60:02d}:{int(minutes) % 60:02d}:00Z",
    }


class TestSamples(unittest.TestCase):
    """Which jobs a duration is read off, and which are left out."""

    def test_a_failed_job_is_not_measured(self) -> None:
        jobs = [
            _job(deploy_job_name("docker", "web-app-matomo", "0"), minutes=10),
            _job(
                deploy_job_name("swarm", "web-app-matomo", "0"),
                minutes=90,
                conclusion="failure",
            ),
        ]
        grouped = timings.samples(jobs)
        self.assertEqual(
            sorted(grouped["mode"]),
            ["compose"],
            "a failed job's duration measures the failure, not the axis",
        )

    def test_a_job_without_both_timestamps_is_left_out(self) -> None:
        job = _job(deploy_job_name("docker", "web-app-matomo", "0"), minutes=10)
        del job["completedAt"]
        self.assertEqual(timings.samples([job])["mode"], {})

    def test_a_title_that_carries_no_row_is_left_out(self) -> None:
        self.assertEqual(
            timings.samples([_job("🧪 Unit tests", minutes=5)])["mode"], {}
        )

    def test_every_axis_of_one_title_is_attributed(self) -> None:
        job = _job(
            deploy_job_name(
                "swarm",
                "web-app-matomo",
                "0",
                tor=True,
                distro=DISTROS[0],
                filesystem=FILESYSTEMS[0],
            ),
            minutes=30,
        )
        grouped = timings.samples([job])
        self.assertEqual(sorted(grouped["mode"]), ["swarm"])
        self.assertEqual(sorted(grouped["tor"]), ["tor"])
        self.assertEqual(sorted(grouped["distro"]), [DISTROS[0]])
        self.assertEqual(sorted(grouped["filesystem"]), [FILESYSTEMS[0]])


class TestRanking(unittest.TestCase):
    """Cheapest first, and only for values that were seen often enough."""

    _GROUPED: ClassVar[dict[str, dict[str, list[float]]]] = {
        "mode": {
            "swarm": [600.0, 600.0, 600.0],
            "compose": [300.0, 300.0, 300.0],
            "host": [1.0],
        },
        "tor": {},
        "distro": {},
        "filesystem": {},
    }

    def test_the_cheapest_measured_value_wins(self) -> None:
        self.assertEqual(timings.fastest(self._GROUPED, "mode"), "compose")

    def test_a_single_observation_does_not_steer_the_run(self) -> None:
        self.assertNotIn(
            "host",
            [
                value
                for value, _median, _count in timings.ranking(self._GROUPED, "mode")
            ],
            "one job is a queue wait, not a measurement",
        )

    def test_the_median_ignores_one_long_tail(self) -> None:
        grouped = {
            "mode": {"compose": [300.0, 300.0, 9000.0], "swarm": [400.0] * 3},
            "tor": {},
            "distro": {},
            "filesystem": {},
        }
        self.assertEqual(timings.fastest(grouped, "mode"), "compose")

    def test_among_restricts_the_choice(self) -> None:
        self.assertEqual(
            timings.fastest(self._GROUPED, "mode", among=("swarm",)), "swarm"
        )

    def test_nothing_measured_enough_returns_none(self) -> None:
        self.assertIsNone(
            timings.fastest(self._GROUPED, "mode", minimum=99),
            "None tells the caller to leave the axis to the rotation",
        )


if __name__ == "__main__":
    unittest.main()
