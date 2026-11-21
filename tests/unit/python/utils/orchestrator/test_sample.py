"""Unit test: the host and lane load parsed from fixture ``/proc/stat``,
``nvidia-smi`` and ``docker`` outputs; the day rule judges the rest of the
system, so a busy translation lane on an otherwise idle host is not paused."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.orchestrator.load import Load
from utils.orchestrator.sample import (
    cpu_percent,
    gpu_percent,
    lane_cpu,
    lane_gpu,
    lane_sample,
    pids,
)
from utils.orchestrator.scheduler import tick

LANE = "infinito-tools-lane"
STAT_BEFORE = "cpu  0 0 0 0 0 0 0 0 0 0\ncpu0 0 0 0 0 0 0 0 0 0 0\nintr 1\n"
STAT_AFTER = "cpu  900 0 70 20 10 0 0 0 0 0\ncpu0 900 0 70 20 10 0 0 0 0 0\nintr 9\n"
GPU_QUERY = "98\n98\n"
STATS = "\n".join(
    json.dumps({"Name": name, "CPUPerc": cpu, "MemPerc": "1.00%"})
    for name, cpu in ((LANE, "1504.00%"), ("web-app-gitea", "16.00%"))
)
TOP = "PID\n4242\n4243\n"
PMON = (
    "# gpu         pid   type     sm    mem    enc    dec    command\n"
    "# Idx           #    C/G      %      %      %      %    name\n"
    "    0       4242     C     96     40      -      -    python3\n"
    "    1       4243     C     96     38      -      -    python3\n"
    "    1       9999     C      -      -      -      -    ollama\n"
)
CPUS = 16
TRANSLATOR = [
    {**entry, "role": "translator"}
    for entry in load_yaml_any(
        str(PROJECT_ROOT / "agents" / "roles" / "translator" / "cron.yml"),
        default_if_missing=[],
    )
]
DAY = datetime(2026, 11, 10, 12, 10, tzinfo=UTC)


def _pair(container: str = LANE) -> tuple[Load, Load]:
    return lane_sample(
        stat_before=STAT_BEFORE,
        stat_after=STAT_AFTER,
        gpu_query=GPU_QUERY,
        stats=STATS,
        container=container,
        cpus=CPUS,
        pmon=PMON,
        top=TOP,
    )


def _day_action(pair: tuple[Load, Load]) -> dict[str, str]:
    return tick(
        TRANSLATOR,
        DAY,
        sample=pair,
        accelerated=True,
        gate_locked=False,
        held=frozenset(),
        blocked=frozenset(),
    )


class TestHost(unittest.TestCase):
    def test_the_cpu_share_between_two_reads(self) -> None:
        self.assertAlmostEqual(cpu_percent(STAT_BEFORE, STAT_AFTER), 97.0)

    def test_no_elapsed_time_is_no_load(self) -> None:
        self.assertEqual(cpu_percent(STAT_AFTER, STAT_AFTER), 0.0)

    def test_the_gpu_share_is_the_mean_over_every_gpu(self) -> None:
        self.assertEqual(gpu_percent("40\n60\n"), 50.0)
        self.assertEqual(gpu_percent(""), 0.0)


class TestLane(unittest.TestCase):
    def test_the_lane_cpu_is_a_share_of_the_whole_host(self) -> None:
        self.assertEqual(lane_cpu(STATS, LANE, CPUS), 94.0)

    def test_a_lane_that_is_not_running_has_no_load(self) -> None:
        self.assertEqual(lane_cpu(STATS, "other", CPUS), 0.0)

    def test_the_lane_gpu_counts_only_its_own_processes(self) -> None:
        self.assertEqual(pids(TOP), frozenset({4242, 4243}))
        self.assertEqual(lane_gpu(PMON, pids(TOP), 2), 96.0)
        self.assertEqual(lane_gpu(PMON, frozenset({9999}), 2), 0.0)

    def test_the_pair_of_one_tick(self) -> None:
        host, lane = _pair()
        self.assertAlmostEqual(host.cpu, 97.0)
        self.assertEqual(host.gpu, 98.0)
        self.assertEqual(lane, Load(cpu=94.0, gpu=96.0))


class TestDayRuleOverTheSample(unittest.TestCase):
    def test_a_busy_lane_on_an_idle_rest_of_the_system_is_not_paused(self) -> None:
        self.assertEqual(_day_action(_pair()), {"translate": "start"})

    def test_red_fixture_without_the_lane_sample_the_lane_pauses_itself(
        self,
    ) -> None:
        self.assertEqual(_day_action(_pair("other")), {"translate": "pause"})


if __name__ == "__main__":
    unittest.main()
