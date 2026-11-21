"""Unit tests for :mod:`utils.install.lint.__main__`."""

from __future__ import annotations

import contextlib
import functools
import os
import re
import stat
import subprocess
import sys
import threading
import time
import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.utils import image_slice
from utils.cache.files import PROJECT_ROOT, read_text
from utils.install.lint import __main__ as cli

_RUNS = 6
_INSTALL_SECONDS = 0.1
_WRAPPER = "scripts/install/wrapper.sh"
_DISPATCH = "scripts/make/parallel.sh"
_TOOLCHAIN_STAGE = "toolchain"
_IN_TREE_GROUPS = frozenset({"javascript", "playwright"})
_BAKE = re.compile(r"-m utils\.install\.lint (?P<groups>[a-z ]+?) ;;")
_HOST_SKIPS = "host) ;;"
_SYSTEM_STEP = "INFINITO_(PYTHON|DOCKER_CLI|PACKAGE|INTERPRETERS)_INSTALL_SCRIPT="


def _bake_indexes(runs: list[str]) -> list[int]:
    return [index for index, run in enumerate(runs) if _BAKE.search(run)]


def _baked_groups() -> list[str]:
    for run in image_slice.stage_runs(_TOOLCHAIN_STAGE):
        match = _BAKE.search(run)
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


class _Installer:
    """Stub installer that records how many runs were inside it at once."""

    def __init__(self) -> None:
        self.calls = 0
        self.inside = 0
        self.most = 0
        self._guard = threading.Lock()

    def __call__(self) -> None:
        with self._guard:
            self.calls += 1
            self.inside += 1
            self.most = max(self.most, self.inside)
        time.sleep(_INSTALL_SECONDS)
        with self._guard:
            self.inside -= 1


def _run_at_once(argv: list[str]) -> list[int]:
    """Start ``_RUNS`` installer entries together and return their exit codes.

    Args:
        argv: the arguments every run passes to ``main``.
    """
    start = threading.Barrier(_RUNS)
    codes: list[int] = []

    def run() -> None:
        start.wait()
        codes.append(cli.main(list(argv)))

    threads = [threading.Thread(target=run) for _ in range(_RUNS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return codes


class TestConcurrentRuns(unittest.TestCase):
    def test_parallel_all_mode_runs_install_once(self) -> None:
        installer = _Installer()
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp)
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli.shutil, "which", return_value="/usr/bin/x"),
                mock.patch.object(
                    cli.mermaid_cli, "browser_installed", return_value=True
                ),
                mock.patch.object(cli.os, "chdir"),
                mock.patch.object(cli, "_install_all", installer),
            ):
                codes = _run_at_once([])
        self.assertEqual(codes, [0] * _RUNS)
        self.assertEqual(installer.most, 1)
        self.assertEqual(installer.calls, 1)

    def test_parallel_group_runs_never_overlap(self) -> None:
        installer = _Installer()
        with TemporaryDirectory() as tmp:
            root = _make_repo_root(tmp)
            with (
                mock.patch.object(cli, "PROJECT_ROOT", root),
                mock.patch.object(cli.os, "chdir"),
                mock.patch.object(cli, "_install_sql_tools", installer),
            ):
                codes = _run_at_once(["sql"])
        self.assertEqual(codes, [0] * _RUNS)
        self.assertEqual(installer.most, 1)
        self.assertEqual(installer.calls, _RUNS)

    def test_the_lock_is_readable_but_never_writable_by_other_uids(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = os.umask(0)
            try:
                with cli._exclusive(root):
                    pass
            finally:
                os.umask(previous)
            mode = stat.S_IMODE((root / cli._LOCK).stat().st_mode)
        self.assertEqual(mode & 0o022, 0)
        self.assertEqual(mode & 0o044, 0o044)


def _recipe(makefile: str, target: str) -> list[str]:
    """Return the recipe of ``target`` with continuation lines joined.

    Args:
        makefile: the Makefile text.
        target: the make target.
    """
    lines = makefile.splitlines()
    start = next(
        index for index, line in enumerate(lines) if line.startswith(f"{target}:")
    )
    body: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        if body and body[-1].endswith("\\"):
            body[-1] = body[-1][:-1] + " " + line.strip()
        else:
            body.append(line.strip())
    return body


def _installed_groups(line: str) -> set[str]:
    """Return the groups a recipe line passes to the install wrapper.

    Args:
        line: one recipe line.
    """
    found = re.search(rf"{re.escape(_WRAPPER)}((?:\s+[a-z]+)+)\s*$", line)
    return set(found.group(1).split()) if found else set()


def _late_groups(makefile: str) -> set[str]:
    """Return the groups a dispatched lint target installs that ``lint`` does
    not install before the dispatch starts.

    Args:
        makefile: the Makefile text.
    """
    recipe = _recipe(makefile, "lint")
    dispatch = next(i for i, line in enumerate(recipe) if _DISPATCH in line)
    early = set().union(*(_installed_groups(line) for line in recipe[:dispatch]))
    dispatched = recipe[dispatch].split(_DISPATCH, 1)[1].split()
    late: set[str] = set()
    for target in dispatched:
        for line in _recipe(makefile, target):
            late |= _installed_groups(line)
    return late - early


class TestLintDispatch(unittest.TestCase):
    def test_lint_installs_every_group_before_the_dispatch(self) -> None:
        makefile = read_text(str(PROJECT_ROOT / "Makefile"))
        self.assertEqual(_late_groups(makefile), set())

    def test_a_group_installed_only_inside_the_dispatch_is_found(self) -> None:
        makefile = (
            "lint: install-lint\n"
            "\t@bash scripts/make/parallel.sh lint-sql \\\n"
            "\t\tlint-python\n"
            "\n"
            "lint-python: install-lint\n"
            "\t@bash scripts/lint/wrapper.sh python\n"
            "\n"
            "lint-sql: install-lint\n"
            "\t@bash scripts/install/wrapper.sh sql\n"
            "\t@bash scripts/lint/wrapper.sh sql\n"
        )
        self.assertEqual(_late_groups(makefile), {"sql"})


class TestImageBake(unittest.TestCase):
    def test_the_toolchain_stage_bakes_every_all_mode_group_outside_the_tree(
        self,
    ) -> None:
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
            "the Dockerfile's toolchain stage must bake every all-mode "
            "group except the ones the bind-mounted tree replaces, in order",
        )

    def test_the_bake_follows_the_system_step_and_skips_a_host_runner(
        self,
    ) -> None:
        runs = image_slice.stage_runs(_TOOLCHAIN_STAGE)
        bakes = _bake_indexes(runs)
        self.assertEqual(len(bakes), 1, "the toolchain stage must bake once")
        self.assertIn(
            _SYSTEM_STEP,
            runs[bakes[0] - 1],
            "the bake must run right after the toolchain stage's system "
            "package step, so it resolves packages in the order a runtime "
            "install does",
        )
        self.assertIn(
            _HOST_SKIPS,
            runs[bakes[0]],
            "INFINITO_LINT_RUNNER=host must skip the bake, so CI images stay "
            "without the lint toolchain",
        )

    def test_the_installer_runs_on_the_slice_the_toolchain_stage_copies(
        self,
    ) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        slice_root = Path(tmp.name)
        image_slice.materialise(slice_root, frozenset({_TOOLCHAIN_STAGE}))

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
            "utils.install.lint reached for a module the toolchain stage "
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
