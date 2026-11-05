import contextlib
import io
import unittest
import unittest.mock as mock

from utils.tests.swarm import matrix, run, watchdog


class TestRunReporting(unittest.TestCase):
    """Every matrix phase must state what it cost.

    A phase that only announces its start leaves the reader subtracting
    timestamps by hand, and a phase that produces no output of its own becomes
    invisible: the credential rotation spent 17 minutes of a budget-killed job
    with nothing but the 30-second sampler in between.
    """

    _RUNNERS = ((matrix, "_run"), (run, "run_step"))

    def _run_capturing(self, module, name: str, rc: int) -> tuple[int, str]:
        buffer = io.StringIO()
        with (
            mock.patch.object(module, "run_watched", return_value=rc) as watched,
            contextlib.redirect_stdout(buffer),
        ):
            returned = getattr(module, name)(
                ["true"], env={"A": "b"}, label="demo phase"
            )
        watched.assert_called_once_with(["true"], env={"A": "b"})
        return returned, buffer.getvalue()

    def test_the_exit_code_passes_through(self) -> None:
        for module, name in self._RUNNERS:
            with self.subTest(runner=f"{module.__name__}.{name}"):
                returned, _ = self._run_capturing(module, name, 7)
                self.assertEqual(returned, 7)

    def test_the_phase_announces_its_start(self) -> None:
        for module, name in self._RUNNERS:
            with self.subTest(runner=f"{module.__name__}.{name}"):
                _, output = self._run_capturing(module, name, 0)
                self.assertIn("=== swarm-matrix: demo phase ===", output)

    def test_the_phase_reports_its_duration_and_outcome(self) -> None:
        for module, name in self._RUNNERS:
            with self.subTest(runner=f"{module.__name__}.{name}"):
                _, output = self._run_capturing(module, name, 124)
                self.assertRegex(output, r"demo phase took \d+s \(rc=124\)")


TOP_OUTPUT = """top - 10:00:00 up 1:00,  0 users,  load average: 9.00, 8.00, 7.00
Tasks: 300 total,   2 running
%Cpu(s): 90.0 us

    PID USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND
      1 root      20   0   10000   1000    100 S  99.0   0.1  50:00.00 systemd
      2 root      20   0   10000   1000    100 S  50.0   0.1  10:00.00 dockerd

top - 10:00:03 up 1:00,  0 users,  load average: 9.00, 8.00, 7.00
Tasks: 300 total,   2 running
%Cpu(s): 95.0 us

    PID USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND
    300 999       20   0   10000   1000    100 R 187.5   0.1   1:00.00 postgres
    400 root      20   0   10000   1000    100 S  42.0   0.1   0:30.00 ansible-playbook
    500 root      20   0   10000   1000    100 S  12.3   0.1   0:10.00 etcd
"""


class TestTopProcesses(unittest.TestCase):
    """The CPU sampler must report the measured window, not lifetime averages.

    HA Nextcloud rows ran out of the job budget on a CPU-starved runner, and
    only a per-process view says which nested container burns the CPU.
    """

    def _top(self, stdout: str, rows: int = 12) -> list[str]:
        result = mock.Mock(stdout=stdout)
        with mock.patch.object(watchdog.subprocess, "run", return_value=result):
            return watchdog.top_processes(rows)

    def test_reads_the_second_frame(self) -> None:
        self.assertEqual(
            self._top(TOP_OUTPUT),
            ["187.5 postgres", "42.0 ansible-playbook", "12.3 etcd"],
        )

    def test_limits_the_rows(self) -> None:
        self.assertEqual(self._top(TOP_OUTPUT, rows=1), ["187.5 postgres"])

    def test_unreadable_output_yields_nothing(self) -> None:
        self.assertEqual(self._top("garbage"), [])

    def test_a_missing_top_yields_nothing(self) -> None:
        with mock.patch.object(watchdog.subprocess, "run", side_effect=OSError):
            self.assertEqual(watchdog.top_processes(watchdog.TOP_ROWS), [])


if __name__ == "__main__":
    unittest.main()
