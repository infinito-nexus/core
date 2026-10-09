#!/usr/bin/env python3
import contextlib
import importlib.util
import io
import sys
from types import SimpleNamespace
from unittest import TestCase, main, mock

from . import PROJECT_ROOT

DF_ARGS = ["df", "--output=pcent,size,target"]


def load_target_module():
    repo_root = PROJECT_ROOT
    script_path = (
        repo_root
        / "roles"
        / "sys-ctl-hlth-disc-space"
        / "files"
        / "python"
        / "script.py"
    )

    if not script_path.is_file():
        raise FileNotFoundError(f"Target script not found at: {script_path}")

    spec = importlib.util.spec_from_file_location("target_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


SCRIPT_MODULE = load_target_module()


def _runner(df_output: str):
    def fake_run(args, capture_output=False, text=False, check=False):
        if args == DF_ARGS:
            return SimpleNamespace(stdout=df_output, returncode=0)
        if args == ["df"]:
            return SimpleNamespace(stdout="Filesystem ...\n", returncode=0)
        raise AssertionError(f"Unexpected subprocess.run args: {args}")

    return fake_run


class TestDiskSpaceScript(TestCase):
    def test_get_filesystem_usage_parses_output(self):
        fake_df_output = (
            "Use% 1K-blocks Mounted on\n"
            " 10% 1000000000 /\n"
            " 50% 500000000 /home\n"
            "100% 200000000 /var\n"
        )

        with mock.patch.object(
            SCRIPT_MODULE.subprocess,
            "run",
            return_value=SimpleNamespace(stdout=fake_df_output, returncode=0),
        ):
            result = SCRIPT_MODULE.get_filesystem_usage()

        self.assertEqual(
            result,
            [(10, 1000000000, "/"), (50, 500000000, "/home"), (100, 200000000, "/var")],
        )

    def test_a_tiny_hook_tmpfs_is_reported_but_never_fails_the_check(self):
        df_output = (
            "Use% 1K-blocks Mounted on\n"
            " 10% 1000000000 /\n"
            "100% 4 /run/nvidia-ctk-hookf54b8036\n"
            "100% 512000 /boot\n"
        )

        with (
            mock.patch.object(
                SCRIPT_MODULE.subprocess, "run", side_effect=_runner(df_output)
            ),
            mock.patch.object(sys, "argv", ["script.py", "80"]),
            mock.patch.object(
                SCRIPT_MODULE.sys, "exit", side_effect=SystemExit
            ) as mock_exit,
        ):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit):
                SCRIPT_MODULE.main()

        output = buffer.getvalue()
        self.assertIn("INFO: /run/nvidia-ctk-hookf54b8036 at 100%", output)
        self.assertIn("4 KiB in total", output)
        self.assertNotIn("WARNING: /run/nvidia-ctk-hookf54b8036", output)
        self.assertIn("WARNING: /boot at 100% exceeds the limit of 80%.", output)
        mock_exit.assert_called_once_with(1)

    def test_a_tiny_filesystem_below_the_threshold_says_nothing(self):
        df_output = "Use% 1K-blocks Mounted on\n 10% 4 /run/nvidia-ctk-hook\n"

        with (
            mock.patch.object(
                SCRIPT_MODULE.subprocess, "run", side_effect=_runner(df_output)
            ),
            mock.patch.object(sys, "argv", ["script.py", "80"]),
            mock.patch.object(
                SCRIPT_MODULE.sys, "exit", side_effect=SystemExit
            ) as mock_exit,
        ):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit):
                SCRIPT_MODULE.main()

        self.assertNotIn("INFO:", buffer.getvalue())
        mock_exit.assert_called_once_with(0)

    def test_main_exits_zero_when_below_threshold(self):
        df_output = (
            "Use% 1K-blocks Mounted on\n"
            " 10% 1000000000 /\n"
            " 50% 500000000 /home\n"
            " 80% 200000000 /var\n"
        )

        with (
            mock.patch.object(
                SCRIPT_MODULE.subprocess, "run", side_effect=_runner(df_output)
            ),
            mock.patch.object(sys, "argv", ["script.py", "80"]),
            mock.patch.object(
                SCRIPT_MODULE.sys, "exit", side_effect=SystemExit
            ) as mock_exit,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            SCRIPT_MODULE.main()

        mock_exit.assert_called_once_with(0)

    def test_main_names_the_mountpoint_of_every_breach(self):
        df_output = (
            "Use% 1K-blocks Mounted on\n"
            " 60% 1000000000 /\n"
            " 90% 500000000 /home\n"
            " 95% 200000000 /var\n"
        )

        with (
            mock.patch.object(
                SCRIPT_MODULE.subprocess, "run", side_effect=_runner(df_output)
            ),
            mock.patch.object(sys, "argv", ["script.py", "80"]),
            mock.patch.object(
                SCRIPT_MODULE.sys, "exit", side_effect=SystemExit
            ) as mock_exit,
        ):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit):
                SCRIPT_MODULE.main()

        mock_exit.assert_called_once_with(1)

        output = buffer.getvalue()
        self.assertIn("Checking disk space usage...", output)
        self.assertIn("WARNING: /home at 90% exceeds the limit of 80%.", output)
        self.assertIn("WARNING: /var at 95% exceeds the limit of 80%.", output)
        self.assertNotIn("/ at 60%", output)


if __name__ == "__main__":
    main()
