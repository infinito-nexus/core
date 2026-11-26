"""``utils.tests.workers`` splits one CPU budget over the suites running side by side."""

from __future__ import annotations

import io
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

from utils.tests import workers as module

SUITES = ("integration", "unit", "lint", "external")
MAKE_TEST = ["test-external", "test-integration", "test-lint", "test-unit"]
FLOOR_KEY = "INFINITO_TEST_EXTERNAL_WORKERS_MIN"


def _report(directory: Path, suite: str, seconds: float) -> None:
    (directory / f"{suite}.xml").write_text(
        f'<testsuites><testsuite><testcase classname="tests.{suite}.test_a.TestA" '
        f'name="test_a" time="{seconds}"/></testsuite></testsuites>'
    )


class TestWorkers(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.reports = Path(self._tmp.name)

    def _split(
        self, siblings: list[str], cpus: int, target: float, external_floor: int
    ) -> dict[str, int]:
        environ = {FLOOR_KEY: str(external_floor)}
        return {
            suite: module.workers(
                suite,
                siblings,
                cpus,
                target,
                self.reports,
                module.floor(suite, environ),
            )
            for suite in SUITES
        }

    def test_a_suite_running_alone_takes_the_whole_budget(self) -> None:
        self.assertEqual(module.workers("unit", [], 20, 0.9, self.reports, 1), 18)

    def test_suites_side_by_side_split_the_budget_by_recorded_time(self) -> None:
        for suite, seconds in zip(SUITES, (900, 600, 400, 100), strict=True):
            _report(self.reports, suite, seconds)
        self.assertEqual(
            self._split(MAKE_TEST, 20, 0.9, 1),
            {"integration": 8, "unit": 5, "lint": 4, "external": 1},
        )

    def test_the_external_floor_adds_workers_on_top_of_the_budget(self) -> None:
        for suite, seconds in zip(SUITES, (900, 600, 400, 100), strict=True):
            _report(self.reports, suite, seconds)
        self.assertEqual(
            self._split(MAKE_TEST, 20, 0.9, 3),
            {"integration": 8, "unit": 5, "lint": 4, "external": 3},
        )

    def test_the_external_floor_holds_for_a_tiny_budget_and_alone(self) -> None:
        for siblings in (MAKE_TEST, [], ["test-external"]):
            with self.subTest(siblings=siblings):
                self.assertEqual(self._split(siblings, 1, 0.9, 3)["external"], 3)

    def test_a_share_above_the_floor_wins(self) -> None:
        self.assertEqual(module.workers("external", [], 20, 0.9, self.reports, 3), 18)

    def test_only_the_external_suite_reads_a_floor(self) -> None:
        environ = {FLOOR_KEY: "3"}
        self.assertEqual(module.floor("external", environ), 3)
        for suite in ("integration", "unit", "lint", "session", "unit-javascript"):
            with self.subTest(suite=suite):
                self.assertEqual(module.floor(suite, environ), module.MIN_WORKERS)

    def test_the_recorded_time_moves_workers_to_the_slow_suite(self) -> None:
        for suite, seconds in zip(SUITES, (100, 900, 400, 100), strict=True):
            _report(self.reports, suite, seconds)
        split = self._split(MAKE_TEST, 20, 0.9, 1)
        self.assertGreater(split["unit"], split["integration"])

    def test_one_missing_report_falls_back_to_the_static_weights(self) -> None:
        for suite in ("integration", "unit", "lint"):
            _report(self.reports, suite, 100)
        self.assertEqual(
            self._split(MAKE_TEST, 4, 4, 1),
            {"integration": 7, "unit": 5, "lint": 3, "external": 1},
        )

    def test_a_nested_dispatch_still_sees_the_outer_suites(self) -> None:
        siblings = [
            *MAKE_TEST,
            "test-unit-python",
            "test-unit-javascript",
            "test-unit-php",
            "test-unit-ruby",
        ]
        self.assertEqual(module.workers("unit", siblings, 20, 0.9, self.reports, 1), 5)

    def test_a_unit_dispatch_alone_gives_python_the_whole_budget(self) -> None:
        siblings = [
            "test-unit-python",
            "test-unit-javascript",
            "test-unit-php",
            "test-unit-ruby",
        ]
        self.assertEqual(module.workers("unit", siblings, 20, 0.9, self.reports, 1), 18)

    def test_every_suite_keeps_at_least_one_worker(self) -> None:
        self.assertEqual(self._split(MAKE_TEST, 1, 0.9, 1)["external"], 1)

    def test_the_target_follows_the_environment(self) -> None:
        cases = {"true": "4", "false": "0.9"}
        for on_ci, expected_target in cases.items():
            env = {
                "INFINITO_RUNNING_ON_GITHUB": on_ci,
                "INFINITO_TEST_CPU_TARGET_CI": "4",
                "INFINITO_TEST_CPU_TARGET_LOCAL": "0.9",
                "PARALLEL_SIBLINGS": "",
            }
            with (
                self.subTest(on_ci=on_ci),
                unittest.mock.patch.dict("os.environ", env),
                unittest.mock.patch.object(module.sys, "argv", ["workers", "unit"]),
                unittest.mock.patch.object(
                    module.os, "sched_getaffinity", return_value=set(range(10))
                ),
                redirect_stdout(io.StringIO()) as out,
            ):
                module.main()
            self.assertEqual(
                out.getvalue().strip(), str(round(10 * float(expected_target)))
            )

    def test_main_reads_the_external_floor_from_the_environment(self) -> None:
        env = {
            "INFINITO_RUNNING_ON_GITHUB": "false",
            "INFINITO_TEST_CPU_TARGET_LOCAL": "0.9",
            FLOOR_KEY: "3",
            "PARALLEL_SIBLINGS": " ".join(MAKE_TEST),
        }
        with (
            unittest.mock.patch.dict("os.environ", env),
            unittest.mock.patch.object(module.sys, "argv", ["workers", "external"]),
            unittest.mock.patch.object(
                module.os, "sched_getaffinity", return_value={0}
            ),
            unittest.mock.patch.object(module, "REPORTS", self.reports),
            redirect_stdout(io.StringIO()) as out,
        ):
            module.main()
        self.assertEqual(out.getvalue().strip(), "3")


if __name__ == "__main__":
    unittest.main()
