from __future__ import annotations

import unittest

from utils.failover import runner
from utils.failover.checker import parse_checker_output
from utils.failover.sampling import Round
from utils.failover.scenarios import get_scenario

_GOOD = "start r 0\nack 1 200\nack 2 400\npresent 1\npresent 2\ndone\n"
_LOST = "start r 0\nack 1 200\nack 2 400\npresent 1\ndone\n"
_GAP_20S = "start r 0\nack 1 200\nack 2 20200\npresent 1\npresent 2\ndone\n"


class _FakeLab:
    def __init__(self, log: str):
        self.log = log
        self.calls: list[str] = []

    def prepare(self, injection: str) -> None:
        self.calls.append(f"prepare:{injection}")

    def writer_round(self) -> Round:
        return Round(at_ms=0, writers={"a": True})

    def start_checker(self, run_id: str, duration_s: int) -> None:
        self.calls.append("start")

    def checker_log(self) -> str:
        return self.log

    def stop_checker(self, run_id: str) -> None:
        self.calls.append("stop")

    def inject(self, injection: str) -> None:
        self.calls.append(f"inject:{injection}")

    def heal(self, injection: str) -> None:
        self.calls.append(f"heal:{injection}")


class TestRunScenario(unittest.TestCase):
    def _run(
        self, log: str, name: str = "steady-state", engine: str = "postgres", sleep=None
    ):
        lab = _FakeLab(log)
        result = runner.run_scenario(
            lab,
            engine,
            get_scenario(name),
            duration_s=1,
            sleep=sleep or (lambda _s: None),
        )
        return lab, result

    def test_clean_baseline_run_passes_without_touching_the_lab(self):
        lab, result = self._run(_GOOD)
        self.assertEqual(result.failures, [])
        self.assertEqual(lab.calls, ["start", "stop"])

    def test_fault_is_injected_held_and_healed_before_the_checker_stops(self):
        for name, injection in (
            ("instance-kill", "kill"),
            ("node-crash", "node"),
            ("node-hang", "hang"),
            ("node-partition", "partition"),
        ):
            with self.subTest(name):
                lab, result = self._run(_GOOD, name)
                self.assertEqual(
                    lab.calls,
                    [
                        f"prepare:{injection}",
                        "start",
                        f"inject:{injection}",
                        f"heal:{injection}",
                        "stop",
                    ],
                )
                self.assertEqual(result.failures, [])

    def test_fault_is_healed_even_when_the_hold_is_interrupted(self):
        holds: list[float] = []

        def sleep(seconds: float) -> None:
            holds.append(seconds)
            if seconds == runner.FAULT_HOLD_S:
                raise KeyboardInterrupt

        lab = _FakeLab(_GOOD)
        with self.assertRaises(KeyboardInterrupt):
            runner.run_scenario(
                lab, "postgres", get_scenario("node-hang"), duration_s=1, sleep=sleep
            )
        self.assertEqual(
            lab.calls, ["prepare:hang", "start", "inject:hang", "heal:hang", "stop"]
        )

    def test_write_gap_is_judged_against_the_fault_budget(self):
        _, baseline = self._run(_GAP_20S, "steady-state")
        _, crash = self._run(_GAP_20S, "node-crash")
        self.assertTrue(any("write gap" in f for f in baseline.failures))
        self.assertEqual(crash.failures, [])

    def test_lost_acknowledged_write_fails_a_durable_engine(self):
        _, result = self._run(_LOST, "instance-kill", "postgres")
        self.assertTrue(any("lost" in f for f in result.failures))

    def test_short_loss_on_a_best_effort_engine_is_noted_not_failed(self):
        _, result = self._run(_LOST, "instance-kill", "redis")
        self.assertEqual(result.failures, [])
        self.assertTrue(any("lost" in n for n in result.notes))

    def test_unfinished_checker_fails(self):
        _, result = self._run("start r 0\nack 1 100\n")
        self.assertTrue(any("did not finish" in f for f in result.failures))


class TestUnfinished(unittest.TestCase):
    def test_reports_fails_and_when_the_writes_stopped(self) -> None:
        run = parse_checker_output(
            "start r 1000\nack 1 1200\nack 2 1400\nfail 3 30000\nfail 4 61000\n"
        )
        self.assertEqual(
            runner.unfinished(run),
            "checker did not finish its audit dump (2 acks, 2 fails, "
            "last ack 0.4s, last write 60.0s into the run)",
        )


if __name__ == "__main__":
    unittest.main()
