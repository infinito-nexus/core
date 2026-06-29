"""Unit tests for :mod:`utils.install.lint.__main__`."""

from __future__ import annotations

import os
import time
import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.install.lint import __main__ as cli


def _make_repo_root(tmp: str, *, stamp_age_offset: float | None = None) -> Path:
    root = Path(tmp)
    (root / "scripts" / "install").mkdir(parents=True)
    (root / "scripts" / "install" / "lint.sh").write_text("#\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    if stamp_age_offset is not None:
        stamp = root / cli._STAMP
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text("", encoding="utf-8")
        if stamp_age_offset:
            new_time = time.time() + stamp_age_offset
            os.utime(stamp, (new_time, new_time))
    return root


class TestStampLogic(unittest.TestCase):
    def test_fresh_stamp_short_circuits(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp, stamp_age_offset=60.0)
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli.shutil, "which", return_value="/usr/bin/x"),
                mock.patch.object(cli, "_install_all") as inst,
            ):
                rc = cli.main([])
            self.assertEqual(rc, 0)
            inst.assert_not_called()

    def test_missing_tool_invalidates_stamp(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp, stamp_age_offset=60.0)
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli.shutil, "which", return_value=None),
                mock.patch.object(cli, "_install_all") as inst,
            ):
                rc = cli.main([])
            self.assertEqual(rc, 0)
            inst.assert_called_once()

    def test_stale_stamp_triggers_install(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp, stamp_age_offset=-60.0)
            # Touch lint.sh after stamp so dep is newer.
            time.sleep(0.01)
            (root / "scripts" / "install" / "lint.sh").write_text(
                "#updated\n", encoding="utf-8"
            )
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli, "_install_all") as inst,
            ):
                rc = cli.main([])
            self.assertEqual(rc, 0)
            inst.assert_called_once()
            self.assertTrue((root / cli._STAMP).exists())

    def test_no_stamp_triggers_install_and_touches(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp)
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli, "_install_all") as inst,
            ):
                rc = cli.main([])
            self.assertEqual(rc, 0)
            inst.assert_called_once()
            self.assertTrue((root / cli._STAMP).exists())

    def test_force_drops_stamp(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp, stamp_age_offset=60.0)
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli, "_install_all") as inst,
            ):
                rc = cli.main(["--force"])
            self.assertEqual(rc, 0)
            inst.assert_called_once()


class TestGroupDispatch(unittest.TestCase):
    def test_group_only_bypasses_stamp(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp, stamp_age_offset=60.0)
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli, "_install_javascript_tools") as js,
                mock.patch.object(cli, "_install_all") as inst_all,
            ):
                rc = cli.main(["javascript"])
            self.assertEqual(rc, 0)
            js.assert_called_once()
            inst_all.assert_not_called()

    def test_group_does_not_touch_stamp(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp)
            stamp = root / cli._STAMP
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli, "_install_javascript_tools"),
            ):
                cli.main(["javascript"])
            self.assertFalse(stamp.exists())

    def test_ansible_group_calls_all_modules(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp)
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli.ansible_commands, "ensure") as a,
                mock.patch.object(cli.ansible_collections, "ensure") as b,
                mock.patch.object(cli.ansible_lint, "ensure") as c,
            ):
                cli.main(["ansible"])
            a.assert_called_once()
            b.assert_called_once()
            c.assert_called_once()

    def test_unknown_group_returns_1(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp)
            with mock.patch.object(cli, "PROJECT_ROOT", root):
                rc = cli.main(["bogus"])
            self.assertEqual(rc, 1)

    def test_runtime_error_in_ensure_returns_1(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp)
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(
                    cli.eslint, "ensure", side_effect=RuntimeError("boom")
                ),
            ):
                rc = cli.main(["javascript"])
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
