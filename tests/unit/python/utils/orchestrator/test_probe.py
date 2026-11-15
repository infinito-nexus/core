"""Unit test: the load probe measures nothing on the first tick, without a lane
container or without the docker CLI, logs an unreadable reading instead of
raising, and a CLI read answers None for an absent, failing tool."""

from __future__ import annotations

import sys
import unittest
import unittest.mock as mock

from utils.orchestrator import probe


class TestOutput(unittest.TestCase):
    def test_an_absent_or_failing_tool_answers_none(self) -> None:
        self.assertIsNone(probe.output(["infinito-no-such-tool"], 5))
        self.assertIsNone(
            probe.output([sys.executable, "-c", "import sys; sys.exit(3)"], 5)
        )

    def test_a_working_tool_answers_its_stdout(self) -> None:
        self.assertEqual(probe.output([sys.executable, "-c", "print('ok')"], 5), "ok\n")


class TestLaneLoad(unittest.TestCase):
    def _load(self, previous, container, answers):
        calls: list[list[str]] = []
        logged: list[tuple[str, dict]] = []

        def output(argv, _timeout):
            calls.append(argv)
            return answers.get(argv[0])

        with mock.patch.object(probe, "output", output):
            result = probe.lane_load(
                previous,
                container=container,
                timeout=5,
                log=lambda event, **fields: logged.append((event, fields)),
            )
        return result, calls, logged

    def test_the_first_tick_or_no_lane_container_measures_nothing(self) -> None:
        for previous, container in ((None, "lane"), ("cpu 1 2 3 4", None)):
            with self.subTest(previous=previous, container=container):
                (stat, pair, accelerated), calls, _ = self._load(
                    previous, container, {"docker": "{}"}
                )
                self.assertTrue(stat.startswith("cpu "))
                self.assertEqual((pair, accelerated, calls), (None, False, []))

    def test_without_the_docker_cli_no_load_is_measured(self) -> None:
        (_, pair, accelerated), calls, _ = self._load("cpu 1 2 3 4", "lane", {})
        self.assertEqual((pair, accelerated), (None, False))
        self.assertEqual([argv[0] for argv in calls], ["docker", "docker"])

    def test_an_unreadable_reading_is_logged_not_raised(self) -> None:
        with mock.patch.object(probe.sample, "lane_sample", side_effect=ValueError):
            (_, pair, accelerated), _, logged = self._load(
                "cpu 1 2 3 4", "lane", {"docker": "{}"}
            )
        self.assertEqual((pair, accelerated), (None, False))
        self.assertEqual(logged, [("load_unreadable", {"error": "ValueError"})])


if __name__ == "__main__":
    unittest.main()
