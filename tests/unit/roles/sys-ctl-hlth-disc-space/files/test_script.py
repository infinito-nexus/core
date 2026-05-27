#!/usr/bin/env python3
import contextlib
import importlib.util
import io
import sys
from types import SimpleNamespace
from unittest import TestCase, main, mock

from . import PROJECT_ROOT


def load_target_module():
    repo_root = PROJECT_ROOT  # /opt/src/infinito
    script_path = (
        repo_root / "roles" / "sys-ctl-hlth-disc-space" / "files" / "script.py"
    )

    if not script_path.is_file():
        raise FileNotFoundError(f"Target script not found at: {script_path}")

    spec = importlib.util.spec_from_file_location("target_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# Load the module once for all tests
SCRIPT_MODULE = load_target_module()


class TestDiskSpaceScript(TestCase):
    def test_get_disk_usage_percentages_parses_output(self):
        fake_df_output = "Use%\n 10%\n  50%\n100%\n"

        with mock.patch.object(
            SCRIPT_MODULE.subprocess,
            "run",
            return_value=SimpleNamespace(stdout=fake_df_output, returncode=0),
        ):
            result = SCRIPT_MODULE.get_disk_usage_percentages()

        self.assertEqual(result, [10, 50, 100])

    def test_main_exits_zero_when_below_threshold(self):
        df_print_cp = SimpleNamespace(stdout="Filesystem ...\n", returncode=0)
        df_pcent_cp = SimpleNamespace(stdout="Use%\n 10%\n 50%\n 80%\n", returncode=0)

        def fake_run(args, capture_output=False, text=False, check=False):
            if args == ["df", "--output=pcent"]:
                return df_pcent_cp
            if args == ["df"]:
                return df_print_cp
            raise AssertionError(f"Unexpected subprocess.run args: {args}")

        with (
            mock.patch.object(SCRIPT_MODULE.subprocess, "run", side_effect=fake_run),
            mock.patch.object(sys, "argv", ["script.py", "80"]),
            mock.patch.object(
                SCRIPT_MODULE.sys, "exit", side_effect=SystemExit
            ) as mock_exit,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            SCRIPT_MODULE.main()

        mock_exit.assert_called_once_with(0)

    def test_main_exits_with_error_count_and_prints_warnings(self):
        df_print_cp = SimpleNamespace(stdout="Filesystem ...\n", returncode=0)
        df_pcent_cp = SimpleNamespace(stdout="Use%\n 60%\n 90%\n 95%\n", returncode=0)

        def fake_run(args, capture_output=False, text=False, check=False):
            if args == ["df", "--output=pcent"]:
                return df_pcent_cp
            if args == ["df"]:
                return df_print_cp
            raise AssertionError(f"Unexpected subprocess.run args: {args}")

        with (
            mock.patch.object(SCRIPT_MODULE.subprocess, "run", side_effect=fake_run),
            mock.patch.object(sys, "argv", ["script.py", "80"]),
            mock.patch.object(
                SCRIPT_MODULE.sys, "exit", side_effect=SystemExit
            ) as mock_exit,
        ):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit):
                SCRIPT_MODULE.main()

        mock_exit.assert_called_once_with(2)

        output = buffer.getvalue()
        self.assertIn("Checking disk space usage...", output)
        self.assertIn("WARNING: 90% exceeds the limit of 80%.", output)
        self.assertIn("WARNING: 95% exceeds the limit of 80%.", output)
        self.assertNotIn("60% exceeds the limit of 80%.", output)


if __name__ == "__main__":
    main()
