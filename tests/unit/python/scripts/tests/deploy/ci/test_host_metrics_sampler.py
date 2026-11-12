from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

SAMPLER = (
    PROJECT_ROOT / "scripts" / "tests" / "deploy" / "ci" / "host-metrics-sampler.sh"
)
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "call-test-deploy.yml"

STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z ")

MEMINFO = (
    "MemTotal:       16384000 kB\n"
    "MemFree:          512000 kB\n"
    "MemAvailable:    4096000 kB\n"
    "SwapCached:        20000 kB\n"
    "SwapTotal:      16777212 kB\n"
    "SwapFree:        9647000 kB\n"
)
LOADAVG = "3.20 2.90 2.10 5/812 45678\n"
CPU_PRESSURE = (
    "some avg10=12.50 avg60=8.00 avg300=4.00 total=123456\n"
    "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
)
MEMORY_PRESSURE = (
    "some avg10=30.10 avg60=22.40 avg300=10.00 total=999\n"
    "full avg10=18.20 avg60=11.00 avg300=5.00 total=555\n"
)
PS_ROWS = [
    "  812 2345678 dockerd",
    " 1001 1800000 beam.smp",
    " 1002 1500000 gunicorn: maste",
    " 1003 1400000 node --passwor",
    " 1004 1300000 mariadbd",
    " 1005 1200000 php-fpm8.3",
    " 1006 1100000 java",
    " 1007 1000000 containerd-shim",
    " 1008  900000 python3",
    " 1009  800000 redis-server",
    " 1010  700000 nginx",
    " 1011  600000 sshd",
]


def _sample() -> tuple[list[str], str]:
    with tempfile.TemporaryDirectory() as tmp:
        proc_root = Path(tmp) / "proc"
        (proc_root / "pressure").mkdir(parents=True)
        (proc_root / "meminfo").write_text(MEMINFO, encoding="utf-8")
        (proc_root / "loadavg").write_text(LOADAVG, encoding="utf-8")
        (proc_root / "pressure" / "cpu").write_text(CPU_PRESSURE, encoding="utf-8")
        (proc_root / "pressure" / "memory").write_text(
            MEMORY_PRESSURE, encoding="utf-8"
        )
        stub_dir = Path(tmp) / "bin"
        stub_dir.mkdir()
        stub = stub_dir / "ps"
        stub.write_text(
            "#!/bin/sh\n"
            "printf 'ps-argv:%s\\n' \"$*\" >&2\n"
            "printf '%s\\n' " + " ".join(f"'{row}'" for row in PS_ROWS) + "\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        proc = subprocess.run(
            [
                "sh",
                "-c",
                'HOST_METRICS_SAMPLER_LIB=1 . "$1" && sample_once "$2"',
                "sh",
                str(SAMPLER),
                str(proc_root),
            ],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}"},
        )
    return proc.stdout.splitlines(), proc.stderr


class SampleBlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lines, cls.stderr = _sample()

    def test_every_line_opens_with_one_shared_utc_stamp(self) -> None:
        stamps = {line[:21] for line in self.lines}
        self.assertEqual(len(stamps), 1, self.lines)
        for line in self.lines:
            self.assertRegex(line, STAMP)

    def _body(self) -> list[str]:
        return [STAMP.sub("", line) for line in self.lines]

    def test_memory_and_swap_come_from_meminfo_in_kb(self) -> None:
        self.assertEqual(
            self._body()[0],
            "mem MemTotal_kB=16384000 MemAvailable_kB=4096000 "
            "SwapTotal_kB=16777212 SwapFree_kB=9647000",
        )

    def test_load_carries_the_three_averages_and_the_task_counts(self) -> None:
        self.assertEqual(self._body()[1], "load 3.20 2.90 2.10 5/812")

    def test_pressure_carries_some_and_full_avg10_and_avg60(self) -> None:
        self.assertEqual(
            self._body()[2:5],
            [
                "psi cpu some avg10=12.50 avg60=8.00 full avg10=0.00 avg60=0.00",
                "psi memory some avg10=30.10 avg60=22.40 full avg10=18.20 avg60=11.00",
                "psi io unavailable",
            ],
        )

    def test_the_ten_largest_processes_follow_with_pid_rss_and_exe(self) -> None:
        self.assertEqual(
            self._body()[5:],
            [
                "top pid=812 rss_kB=2345678 exe=dockerd",
                "top pid=1001 rss_kB=1800000 exe=beam.smp",
                "top pid=1002 rss_kB=1500000 exe=gunicorn",
                "top pid=1003 rss_kB=1400000 exe=node",
                "top pid=1004 rss_kB=1300000 exe=mariadbd",
                "top pid=1005 rss_kB=1200000 exe=php-fpm8.3",
                "top pid=1006 rss_kB=1100000 exe=java",
                "top pid=1007 rss_kB=1000000 exe=containerd-shim",
                "top pid=1008 rss_kB=900000 exe=python3",
                "top pid=1009 rss_kB=800000 exe=redis-server",
            ],
        )

    def test_ps_is_asked_for_pid_rss_and_comm_only(self) -> None:
        self.assertEqual(
            [line for line in self.stderr.splitlines() if line.startswith("ps-argv:")],
            ["ps-argv:-eo pid=,rss=,comm= --sort=-rss"],
        )


class WorkflowWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workflow = load_yaml(str(WORKFLOW))
        cls.steps = workflow["jobs"]["deploy"]["steps"]
        cls.runs = [str(step.get("run", "")) for step in cls.steps]
        cls.sampler = next(
            i for i, run in enumerate(cls.runs) if "host-metrics-sampler.sh" in run
        )

    def _index(self, needle: str) -> int:
        return next(i for i, run in enumerate(self.runs) if needle in run)

    def test_the_sampler_detaches_into_the_rescue_base_on_real_runners(self) -> None:
        self.assertEqual(
            self.runs[self.sampler],
            "nohup ./scripts/tests/deploy/ci/host-metrics-sampler.sh "
            '"${INFINITO_RESCUE_DIAGNOSTICS_BASE}/host-metrics.log" >/dev/null 2>&1 &',
        )
        self.assertEqual(self.steps[self.sampler].get("if"), "${{ !env.ACT }}")

    def test_the_sampler_starts_after_the_rescue_base_and_before_any_deploy(
        self,
    ) -> None:
        self.assertLess(self._index("^INFINITO_RESCUE_DIAGNOSTICS_BASE="), self.sampler)
        self.assertLess(self.sampler, self._index("00_one.sh"))
        self.assertLess(self.sampler, self._index("ci/all.sh"))

    def test_the_rescue_upload_ships_the_base_even_after_a_red_deploy(self) -> None:
        upload = next(
            step
            for step in self.steps
            if str(step.get("with", {}).get("name", "")).startswith(
                "rescue-diagnostics-"
            )
        )
        self.assertEqual(
            upload["with"]["path"], "${{ env.INFINITO_RESCUE_DIAGNOSTICS_BASE }}/"
        )
        self.assertIn("always()", upload["if"])


if __name__ == "__main__":
    unittest.main()
