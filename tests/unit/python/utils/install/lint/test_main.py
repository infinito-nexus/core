"""Unit tests for :mod:`utils.install.lint.__main__`."""

from __future__ import annotations

import contextlib
import functools
import os
import re
import subprocess
import sys
import time
import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.utils import image_slice
from utils.cache.files import read_text
from utils.install.lint import __main__ as cli

_IN_TREE_GROUPS = frozenset({"javascript", "playwright"})
_BAKE = re.compile(r"^RUN .*-m utils\.install\.lint (?P<groups>[a-z ]+)$")


def _baked_groups() -> list[str]:
    for line in read_text(str(image_slice.DOCKERFILE)).splitlines():
        match = _BAKE.match(line.strip())
        if match:
            return match.group("groups").split()
    return []


def _make_repo_root(tmp: str, *, stamp_age_offset: float | None = None) -> Path:
    root = Path(tmp)
    (root / "scripts" / "install").mkdir(parents=True)
    (root / "scripts" / "install" / "lint.sh").write_text("#\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (root / cli._PINS).parent.mkdir(parents=True)
    (root / cli._PINS).write_text("---\n", encoding="utf-8")
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
                mock.patch.object(
                    cli.mermaid_cli, "browser_installed", return_value=True
                ),
                mock.patch.object(cli, "_install_all") as inst,
            ):
                rc = cli.main([])
            self.assertEqual(rc, 0)
            inst.assert_not_called()

    def test_missing_mermaid_browser_invalidates_stamp(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp, stamp_age_offset=60.0)
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli.shutil, "which", return_value="/usr/bin/x"),
                mock.patch.object(
                    cli.mermaid_cli, "browser_installed", return_value=False
                ),
                mock.patch.object(cli, "_install_all") as inst,
            ):
                rc = cli.main([])
            self.assertEqual(rc, 0)
            inst.assert_called_once()

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

    def test_a_newer_release_pin_triggers_install(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp, stamp_age_offset=60.0)
            pins = root / cli._PINS
            later = time.time() + 120.0
            os.utime(pins, (later, later))
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli.shutil, "which", return_value="/usr/bin/x"),
                mock.patch.object(
                    cli.mermaid_cli, "browser_installed", return_value=True
                ),
                mock.patch.object(cli, "_install_all") as inst,
            ):
                rc = cli.main([])
            self.assertEqual(rc, 0)
            inst.assert_called_once()

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
        with TemporaryDirectory() as tmp, TemporaryDirectory() as cache:
            root = _make_repo_root(tmp, stamp_age_offset=60.0)
            with (
                mock.patch.dict(os.environ, {"PUPPETEER_CACHE_DIR": cache}),
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli, "_install_all") as inst,
            ):
                rc = cli.main(["--force"])
            self.assertEqual(rc, 0)
            inst.assert_called_once()

    def test_force_drops_the_mermaid_browser(self) -> None:
        with TemporaryDirectory() as tmp, TemporaryDirectory() as cache:
            root = _make_repo_root(tmp, stamp_age_offset=60.0)
            browser = Path(cache) / "chrome-headless-shell" / "linux-1"
            browser.mkdir(parents=True)
            with (
                mock.patch.dict(os.environ, {"PUPPETEER_CACHE_DIR": cache}),
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli, "_install_all"),
            ):
                cli.main(["--force"])
            self.assertFalse(browser.exists())


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


class TestImageBake(unittest.TestCase):
    def test_the_lint_stage_bakes_every_all_mode_group_outside_the_tree(self) -> None:
        called: list[str] = []
        with contextlib.ExitStack() as stack:
            for group, name in cli._GROUP_FN_NAMES.items():
                stack.enter_context(
                    mock.patch.object(
                        cli, name, side_effect=functools.partial(called.append, group)
                    )
                )
            cli._install_all()
        self.assertEqual(
            _baked_groups(),
            [group for group in called if group not in _IN_TREE_GROUPS],
            "the Dockerfile's lint-docker stage must install every all-mode "
            "group except the ones the bind-mounted tree replaces, in order",
        )

    def test_the_lint_stage_runs_the_full_stage_system_step_before_the_bake(
        self,
    ) -> None:
        lint_runs = image_slice.stage_runs("lint-docker")
        self.assertEqual(
            lint_runs[:1],
            image_slice.stage_runs("full")[:1],
            "the lint-docker stage must open with the full stage's system "
            "package step, so the bake resolves packages in the order a "
            "runtime install does",
        )
        self.assertRegex(lint_runs[-1], _BAKE)

    def test_the_installer_runs_on_the_slice_the_lint_stage_copies(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        slice_root = Path(tmp.name)
        image_slice.materialise(slice_root, frozenset({"base", "lint-docker"}))

        result = subprocess.run(
            [sys.executable, "-S", "-m", "utils.install.lint", "no-such-group"],
            cwd=str(slice_root),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotIn(
            "ModuleNotFoundError",
            result.stderr,
            "utils.install.lint reached for a module the lint-docker stage "
            "does not copy; copy it there or keep the installer off it",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Usage:", result.stderr)

        interpreters = subprocess.run(
            [sys.executable, "-S", "-c", "import utils.install.interpreters"],
            cwd=str(slice_root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(interpreters.returncode, 0, interpreters.stderr)


if __name__ == "__main__":
    unittest.main()
