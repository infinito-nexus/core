import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.core.run import RunConfig, open_log_file, run_command_once


class TestRun(unittest.TestCase):
    def test_open_log_file_creates_in_given_dir(self):
        with tempfile.TemporaryDirectory() as td:
            log_dir = Path(td) / "logs"

            f, path = open_log_file(log_dir)
            try:
                self.assertTrue(path.exists())
                self.assertIn(log_dir, path.parents)
            finally:
                f.close()

    @patch("cli.core.run.subprocess.Popen")
    def test_run_command_once_nonzero_exits(self, mock_popen):
        proc = unittest.mock.Mock()
        proc.wait.return_value = None
        proc.returncode = 2
        mock_popen.return_value = proc

        cfg = RunConfig(log_enabled=False)

        with self.assertRaises(SystemExit):
            run_command_once(["python", "-c", "print(1)"], cfg, log_file=None)

    @patch("cli.core.run.subprocess.Popen")
    def test_run_command_once_success_returns_true(self, mock_popen):
        proc = unittest.mock.Mock()
        proc.wait.return_value = None
        proc.returncode = 0
        mock_popen.return_value = proc

        cfg = RunConfig(log_enabled=False)

        ok = run_command_once(["python", "-c", "print(1)"], cfg, log_file=None)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
