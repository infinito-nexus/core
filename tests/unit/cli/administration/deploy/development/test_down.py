"""Pins the inner-Docker-root wipe: it escalates, and a surviving root is fatal."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli.administration.deploy.development.down import _wipe_docker_root


class TestWipeDockerRoot(unittest.TestCase):
    @patch("cli.administration.deploy.development.down.subprocess.run", autospec=True)
    def test_the_wipe_escalates(self, run_mock: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docker_root = Path(tmp) / "docker"
            docker_root.mkdir()

            _wipe_docker_root(docker_root)

        commands = [call.args[0] for call in run_mock.call_args_list]
        self.assertEqual(commands[0], ["sudo", "rm", "-rf", str(docker_root)])
        self.assertTrue(all(cmd[0] == "sudo" for cmd in commands))

    @patch("cli.administration.deploy.development.down.subprocess.run", autospec=True)
    def test_a_surviving_docker_root_is_a_hard_error(self, run_mock: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docker_root = Path(tmp) / "docker"
            docker_root.mkdir()
            (docker_root / "containers").mkdir()

            with self.assertRaises(RuntimeError) as ctx:
                _wipe_docker_root(docker_root)

        self.assertIn("containers", str(ctx.exception))
        self.assertTrue(run_mock.called)

    @patch("cli.administration.deploy.development.down.subprocess.run", autospec=True)
    def test_a_missing_docker_root_is_not_wiped(self, run_mock: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _wipe_docker_root(Path(tmp) / "absent")

        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
