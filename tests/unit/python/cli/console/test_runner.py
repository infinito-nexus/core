import signal
import sys
import unittest
from unittest.mock import patch

from cli.console import runner


class TestRunCli(unittest.TestCase):
    @patch("cli.console.runner.subprocess.run")
    def test_invokes_python_m_cli_with_argv(self, mock_run):
        mock_run.return_value.returncode = 0
        rc = runner.run_cli(["meta", "env"])
        self.assertEqual(rc, 0)
        called_argv = mock_run.call_args[0][0]
        self.assertEqual(called_argv[0], sys.executable)
        self.assertEqual(called_argv[1:], ["-m", "cli", "meta", "env"])

    @patch("cli.console.runner.subprocess.run")
    @patch("cli.console.runner.clear_screen")
    def test_clears_screen_before_invocation(self, mock_clear, mock_run):
        mock_run.return_value.returncode = 0
        runner.run_cli(["meta", "env"])
        mock_clear.assert_called_once_with()

    @patch("cli.console.runner.subprocess.run")
    def test_restores_sigint_handler(self, mock_run):
        mock_run.return_value.returncode = 0
        before = signal.signal(signal.SIGINT, signal.SIG_DFL)
        try:
            runner.run_cli(["x"])
            after = signal.getsignal(signal.SIGINT)
            self.assertEqual(after, signal.SIG_DFL)
        finally:
            signal.signal(signal.SIGINT, before)


class TestClearScreen(unittest.TestCase):
    def test_noop_when_not_tty(self):
        with patch("cli.console.runner.sys.stdout") as mock_stdout:
            mock_stdout.isatty.return_value = False
            runner.clear_screen()
            mock_stdout.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
