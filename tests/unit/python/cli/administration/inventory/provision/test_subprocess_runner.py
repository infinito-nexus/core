import unittest
from unittest.mock import patch

from cli.administration.inventory.provision.subprocess_runner import run_subprocess


class TestSubprocessRunner(unittest.TestCase):
    def test_run_subprocess_raises_on_nonzero(self):
        with patch(
            "cli.administration.inventory.provision.subprocess_runner.subprocess.run"
        ) as sr:
            sr.return_value.returncode = 1
            sr.return_value.stdout = "out"
            sr.return_value.stderr = "err"

            with self.assertRaises(SystemExit):
                run_subprocess(["false"], capture_output=True, env=None)
