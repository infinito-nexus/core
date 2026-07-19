from __future__ import annotations

import io
import os
import runpy
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from . import PROJECT_ROOT


def _resolved_repo_root() -> Path:
    """Repository root resolution for the script-under-test path.

    The ``INFINITO_REPO_ROOT`` env var still wins when explicitly set
    (used by some CI fixtures); otherwise the canonical ``PROJECT_ROOT``
    constant from the package ``__init__.py`` is returned.
    """
    env = os.environ.get("INFINITO_REPO_ROOT")  # nocheck: test-fixture
    if env:
        return Path(env).expanduser().resolve()
    return PROJECT_ROOT


SCRIPT_PATH = _resolved_repo_root() / "roles/sys-ctl-cln-bkps/files/script.py"


def _fake_psutil(percent: int) -> ModuleType:
    """Create a fake psutil module with disk_usage()."""
    fake = ModuleType("psutil")
    fake.disk_usage = lambda _: SimpleNamespace(percent=percent)
    return fake


class TestSysCtlClnBkpsScript(unittest.TestCase):
    def _run_script(
        self,
        argv: list[str],
        disk_percent: int,
        listdir_map: dict[str, list[str]],
    ) -> tuple[str, object]:
        """
        Execute the script as __main__ with provided argv, returning stdout and rmtree mock.
        Fully mocks psutil and os.listdir so the test does not depend on system packages or FS.
        """
        if not SCRIPT_PATH.is_file():
            raise FileNotFoundError(
                f"script.py not found at expected path: {SCRIPT_PATH} (repo_root={_resolved_repo_root()})"
            )

        fake_psutil = _fake_psutil(disk_percent)

        def listdir_side_effect(path: str) -> list[str]:
            return listdir_map.get(path, [])

        buf = io.StringIO()
        with (
            patch.dict(sys.modules, {"psutil": fake_psutil}),
            patch.object(sys, "argv", argv),
            patch("os.listdir", side_effect=listdir_side_effect),
            patch("shutil.rmtree") as rmtree_mock,
            patch("time.time", return_value=0),
            redirect_stdout(buf),
        ):
            runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

        return buf.getvalue(), rmtree_mock

    def test_exits_immediately_when_disk_usage_below_threshold(self) -> None:
        """
        If disk usage is already <= threshold, the while-loop must not run.
        Script should print final usage and finish message.
        """
        backup_dir = os.environ["INFINITO_DIR_BACKUPS"]
        argv = [
            "script.py",
            "--maximum-backup-size-percent",
            "75",
            "--backups-folder-path",
            backup_dir,
        ]

        out, rmtree_mock = self._run_script(
            argv=argv,
            disk_percent=10,
            listdir_map={backup_dir: []},
        )

        self.assertIn("Cleaning up finished.", out)
        self.assertIn(f"% of disk {backup_dir} are used", out)
        rmtree_mock.assert_not_called()

    def test_breaks_when_no_versions_found_even_if_disk_usage_high(self) -> None:
        """
        Regression test for the busy-loop:
        If disk usage is above threshold but no backup structure exists,
        average_version_directories_per_application() returns 0 and the script
        must break out.
        """
        backup_dir = os.environ["INFINITO_DIR_BACKUPS"]
        argv = [
            "script.py",
            "--maximum-backup-size-percent",
            "75",
            "--backups-folder-path",
            backup_dir,
        ]

        out, rmtree_mock = self._run_script(
            argv=argv,
            disk_percent=90,
            listdir_map={
                backup_dir: [],
            },
        )

        self.assertIn("Delete Iteration: 1", out)
        self.assertIn(
            "No backup versions found to delete (average_version_directories=0). Exiting.",
            out,
        )
        self.assertIn("Cleaning up finished.", out)
        rmtree_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
