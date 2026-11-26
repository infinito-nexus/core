import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch

from cli.core import app


class CLIHelpIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from . import PROJECT_ROOT

        cls.project_root = str(PROJECT_ROOT)
        cls.cli_dir = str(PROJECT_ROOT / "cli")
        cls.main_py = str(PROJECT_ROOT / "cli" / "__main__.py")
        cls.python = sys.executable

    def _discover_command_dirs(self):
        """
        Discover commands as package directories under cli/ that contain __main__.py.

        Rules:
          - cli/<...>/__main__.py marks a command package
          - cli/__main__.py is the dispatcher, not a command
          - ignore __pycache__
        Returns:
          list[list[str]] command segments, e.g. ["deploy","container"]
        """
        commands = []
        for root, dirnames, filenames in os.walk(self.cli_dir):  # nocheck: project-walk
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]

            if "__main__.py" not in filenames:
                continue

            rel_dir = os.path.relpath(root, self.cli_dir)
            if rel_dir == ".":
                continue

            commands.append(list(Path(rel_dir).parts))

        commands.sort(key="/".join)
        return commands

    def test_dispatcher_bootstrap_help(self):
        cmd = [self.python, self.main_py, "--help"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(
            result.returncode,
            0,
            msg=(
                f"Command `{' '.join(cmd)}` failed\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            ),
        )
        self.assertTrue(result.stdout.strip(), "global --help printed nothing")

    def test_all_cli_commands_help(self):
        commands = self._discover_command_dirs()
        self.assertGreater(len(commands), 0, "no CLI commands discovered")
        for segments in commands:
            with self.subTest(command=" ".join(segments)):
                argv = [self.main_py, *segments, "--help"]
                with (
                    patch.object(sys, "argv", argv),
                    patch.object(app.subprocess, "run") as dispatched,
                    self.assertRaises(SystemExit) as raised,
                ):
                    app.main()

                self.assertEqual(
                    raised.exception.code,
                    0,
                    msg=f"Command `{' '.join(argv)}` exited {raised.exception.code}",
                )
                self.assertEqual(
                    dispatched.call_args_list,
                    [
                        call(
                            [
                                sys.executable,
                                "-m",
                                "cli." + ".".join(segments),
                                "--help",
                            ],
                            check=False,
                        )
                    ],
                )


if __name__ == "__main__":
    unittest.main()
