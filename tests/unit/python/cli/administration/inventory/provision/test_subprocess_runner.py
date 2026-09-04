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

    def test_an_expected_nonzero_is_handed_back_instead_of_raising(self):
        with patch(
            "cli.administration.inventory.provision.subprocess_runner.subprocess.run"
        ) as sr:
            sr.return_value.returncode = 3
            sr.return_value.stdout = ""
            sr.return_value.stderr = "no such application role"

            result = run_subprocess(
                ["false"], capture_output=True, env=None, ok_returncodes=(0, 3)
            )

        self.assertEqual(result.returncode, 3)

    def test_an_unexpected_nonzero_still_raises_when_another_is_allowed(self):
        with patch(
            "cli.administration.inventory.provision.subprocess_runner.subprocess.run"
        ) as sr:
            sr.return_value.returncode = 1
            sr.return_value.stdout = ""
            sr.return_value.stderr = "roles path not found"

            with self.assertRaises(SystemExit):
                run_subprocess(
                    ["false"], capture_output=True, env=None, ok_returncodes=(0, 3)
                )
