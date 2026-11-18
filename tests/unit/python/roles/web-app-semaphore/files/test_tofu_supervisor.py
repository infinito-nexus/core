from __future__ import annotations

import errno
import signal
import unittest
import unittest.mock as mock

from .provision._fake_provision import load

supervisor = load("tofu_supervisor")

ARGV = ["tofu_supervisor.py", "1", "tofu", "apply"]


class TestTieToRunner(unittest.TestCase):
    def tie(self, answer, runner):
        """Args:
            answer: what the stubbed ``prctl`` returns.
            runner: the runner pid the supervisor checks its parent against.

        Returns:
            ``(result, prctl)``: what :func:`tie_to_runner` returned and the
            stub it called, which keeps the test process untied.
        """
        library = mock.Mock()
        library.prctl.return_value = answer
        with (
            mock.patch.object(supervisor.ctypes, "CDLL", return_value=library),
            mock.patch.object(
                supervisor.ctypes, "get_errno", return_value=errno.EINVAL
            ),
        ):
            return supervisor.tie_to_runner(runner), library.prctl

    def test_a_refused_death_signal_raises(self):
        with self.assertRaises(OSError) as refused:
            self.tie(-1, supervisor.os.getppid())
        self.assertEqual(refused.exception.errno, errno.EINVAL)

    def test_negative_control_a_set_death_signal_ties_to_the_living_runner(self):
        living, prctl = self.tie(0, supervisor.os.getppid())
        self.assertTrue(living)
        prctl.assert_called_once_with(supervisor.PR_SET_PDEATHSIG, int(signal.SIGTERM))

    def test_a_runner_that_died_before_the_tie_is_not_living(self):
        living, _ = self.tie(0, supervisor.os.getppid() + 1)
        self.assertFalse(living)


class TestMain(unittest.TestCase):
    def setUp(self):
        for signum in (signal.SIGTERM, signal.SIGINT):
            self.addCleanup(signal.signal, signum, signal.getsignal(signum))
        patcher = mock.patch.object(supervisor.subprocess, "call", return_value=0)
        self.call = patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_refused_death_signal_starts_no_command(self):
        refused = OSError(errno.EINVAL, "Invalid argument")
        with (
            mock.patch.object(supervisor, "tie_to_runner", side_effect=refused),
            self.assertRaises(OSError),
        ):
            supervisor.main(ARGV)
        self.call.assert_not_called()

    def test_a_runner_that_died_before_the_tie_starts_no_command(self):
        with mock.patch.object(supervisor, "tie_to_runner", return_value=False):
            self.assertEqual(supervisor.main(ARGV), 128 + signal.SIGTERM)
        self.call.assert_not_called()

    def test_negative_control_a_living_runner_starts_the_command(self):
        with mock.patch.object(supervisor, "tie_to_runner", return_value=True):
            self.assertEqual(supervisor.main(ARGV), 0)
        self.call.assert_called_once_with(["tofu", "apply"])
