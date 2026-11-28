"""Lint: the runner pool's per-deploy budgets name the deploy they were measured on.

``make runner-count`` divides the host's RAM, CPUs and free disk by the budgets
of :data:`utils.runner.count.CALIBRATION`. A budget is only as good
as its measurement, so the file MUST record the measured full deploy: its
applications, commit and date next to the peak memory, CPU and disk growth.
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.runner.count import CALIBRATION, record_problems


class TestRunnerCalibration(unittest.TestCase):
    def test_every_budget_carries_its_measured_deploy(self) -> None:
        if not CALIBRATION.is_file():
            self.skipTest(f"{CALIBRATION.name} is not recorded yet")
        problems = record_problems(load_yaml_any(str(CALIBRATION)))
        self.assertEqual(problems, [], f"{CALIBRATION}: " + "; ".join(problems))

    def test_a_budget_without_its_record_fails(self) -> None:
        budgets_only = {"peak_memory": "8g", "cpus": 4, "disk_growth": "20g"}
        self.assertEqual(
            record_problems(budgets_only),
            ["applications is missing", "commit is missing", "date is missing"],
        )


if __name__ == "__main__":
    unittest.main()
