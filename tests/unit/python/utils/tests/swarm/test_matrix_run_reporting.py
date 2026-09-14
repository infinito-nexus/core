import contextlib
import io
import unittest
from unittest import mock

from utils.tests.swarm import matrix


class TestRunReporting(unittest.TestCase):
    """Every matrix phase must state what it cost.

    A phase that only announces its start leaves the reader subtracting
    timestamps by hand, and a phase that produces no output of its own becomes
    invisible: the credential rotation spent 17 minutes of a budget-killed job
    with nothing but the 30-second sampler in between.
    """

    def _run_capturing(self, rc: int) -> tuple[int, str]:
        buffer = io.StringIO()
        with (
            mock.patch.object(matrix, "_run_watched", return_value=rc) as watched,
            contextlib.redirect_stdout(buffer),
        ):
            returned = matrix._run(["true"], env={"A": "b"}, label="demo phase")
        watched.assert_called_once_with(["true"], env={"A": "b"})
        return returned, buffer.getvalue()

    def test_the_exit_code_passes_through(self) -> None:
        returned, _ = self._run_capturing(7)
        self.assertEqual(returned, 7)

    def test_the_phase_announces_its_start(self) -> None:
        _, output = self._run_capturing(0)
        self.assertIn("=== swarm-matrix: demo phase ===", output)

    def test_the_phase_reports_its_duration_and_outcome(self) -> None:
        _, output = self._run_capturing(124)
        self.assertRegex(output, r"demo phase took \d+s \(rc=124\)")


if __name__ == "__main__":
    unittest.main()
