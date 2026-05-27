from __future__ import annotations

import subprocess
import unittest
import unittest.mock

from cli.administration.deploy.dedicated import proc


class TestProcRun(unittest.TestCase):
    @unittest.mock.patch("subprocess.run")
    def test_run_passes_through_cwd_and_check(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["echo", "hi"], 0)

        proc.run(["echo", "hi"], cwd="/tmp", check=False)

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0], ["echo", "hi"])
        self.assertEqual(kwargs["cwd"], "/tmp")
        self.assertEqual(kwargs["check"], False)
        # Ensure passthrough
        self.assertIn("stdout", kwargs)
        self.assertIn("stderr", kwargs)

    @unittest.mock.patch("subprocess.run")
    def test_run_make_builds_correct_command(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["make", "clean"], 0)

        proc.run_make("/repo", "clean", "setup")

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0], ["make", "clean", "setup"])
        self.assertEqual(kwargs["cwd"], "/repo")
        self.assertTrue(kwargs["check"])


if __name__ == "__main__":
    unittest.main()
