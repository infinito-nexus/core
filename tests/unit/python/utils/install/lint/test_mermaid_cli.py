"""Unit tests for :mod:`utils.install.lint.mermaid_cli`."""

from __future__ import annotations

import contextlib
import os
import subprocess
import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from utils.install.lint import mermaid_cli

if TYPE_CHECKING:
    from collections.abc import Iterator

REVISION = "155.0.8059.39"


def _done(returncode: int) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout="out\n", stderr="err\n")


def _write_core(node_modules: Path, revision: str) -> None:
    revisions = node_modules / "puppeteer-core" / "lib" / "puppeteer"
    revisions.mkdir(parents=True)
    (revisions / "revisions.js").write_text(
        f"export const PUPPETEER_REVISIONS = Object.freeze({{\n"
        f"    chrome: '155.0.8059.39',\n"
        f"    'chrome-headless-shell': '{revision}',\n"
        f"}});\n",
        encoding="utf-8",
    )


def _fake_mmdc(
    root: Path, *, revision: str | None = REVISION, nested: str | None = None
) -> Path:
    """Lay out a global mermaid-cli install the way npm does.

    Args:
        root: npm prefix to build the install under.
        revision: chrome-headless-shell revision of the puppeteer-core beside
            puppeteer, or None to install mmdc without a puppeteer next to it.
        nested: revision of a puppeteer-core nested under puppeteer, as npm
            lays it out when mermaid-cli pins another puppeteer-core.

    Returns:
        The ``bin/mmdc`` symlink.
    """
    package = root / "lib" / "node_modules" / "@mermaid-js" / "mermaid-cli"
    (package / "src").mkdir(parents=True)
    (package / "src" / "cli.js").write_text("", encoding="utf-8")
    if revision is not None:
        (package / "node_modules" / "puppeteer").mkdir(parents=True)
        _write_core(package / "node_modules", revision)
    if nested is not None:
        _write_core(package / "node_modules" / "puppeteer" / "node_modules", nested)
    (root / "bin").mkdir()
    mmdc = root / "bin" / "mmdc"
    mmdc.symlink_to(package / "src" / "cli.js")
    return mmdc


def _install_browser(cache: Path, revision: str) -> None:
    build = cache / "chrome-headless-shell" / f"linux-{revision}" / "linux64"
    build.mkdir(parents=True)
    (build / "chrome-headless-shell").write_text("", encoding="utf-8")


@contextlib.contextmanager
def _environment(
    *, revision: str | None = REVISION, nested: str | None = None
) -> Iterator[tuple[Path, Path]]:
    """Patch mmdc's location and the puppeteer cache onto temporary dirs.

    Args:
        revision: passed to :func:`_fake_mmdc`.
        nested: passed to :func:`_fake_mmdc`.

    Yields:
        The npm prefix and the puppeteer cache directory.
    """
    with TemporaryDirectory() as prefix, TemporaryDirectory() as cache:
        mmdc = _fake_mmdc(Path(prefix), revision=revision, nested=nested)
        with (
            mock.patch.dict(os.environ, {"PUPPETEER_CACHE_DIR": cache}),
            mock.patch.object(mermaid_cli, "which", return_value=True),
            mock.patch.object(mermaid_cli.shutil, "which", return_value=str(mmdc)),
        ):
            yield Path(prefix), Path(cache)


class TestBrowserProvisioning(unittest.TestCase):
    def provision(self, *, euid: int, results: list[int]) -> tuple[list, list[str]]:
        """Run ``ensure()`` with mmdc present and a stubbed puppeteer.

        Args:
            euid: effective uid the run pretends to have.
            results: exit codes the successive puppeteer calls return.

        Returns:
            The recorded subprocess calls and the warnings emitted.
        """
        warnings: list[str] = []
        with (
            _environment(),
            mock.patch.object(mermaid_cli.os, "geteuid", return_value=euid),
            mock.patch.object(mermaid_cli, "warn", side_effect=warnings.append),
            mock.patch.object(
                mermaid_cli.subprocess,
                "run",
                side_effect=[_done(code) for code in results],
            ) as run,
        ):
            mermaid_cli.ensure()
        return run.call_args_list, warnings

    def test_root_installs_the_browser_with_its_libraries(self) -> None:
        calls, warnings = self.provision(euid=0, results=[0])
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0].args[0][-2:], ["chrome-headless-shell", "--install-deps"]
        )
        self.assertEqual(warnings, [])

    def test_the_browser_comes_from_the_puppeteer_next_to_mmdc(self) -> None:
        calls, _ = self.provision(euid=0, results=[0])
        self.assertTrue(
            calls[0]
            .args[0][0]
            .endswith("@mermaid-js/mermaid-cli/node_modules/.bin/puppeteer")
        )

    def test_a_user_installs_the_browser_without_libraries(self) -> None:
        calls, _ = self.provision(euid=1000, results=[0])
        self.assertNotIn("--install-deps", calls[0].args[0])

    def test_the_browser_install_downloads_despite_the_mmdc_skip_flag(self) -> None:
        with mock.patch.dict(os.environ, {"PUPPETEER_SKIP_DOWNLOAD": "1"}):
            calls, _ = self.provision(euid=0, results=[0])
        self.assertNotIn("PUPPETEER_SKIP_DOWNLOAD", calls[0].kwargs["env"])

    def test_a_failed_install_clears_its_revision_and_retries_once(self) -> None:
        seen: list[tuple[bool, bool]] = []
        with _environment() as (_, cache):
            partial = cache / "chrome-headless-shell" / f"linux-{REVISION}"
            partial.mkdir(parents=True)
            other = cache / "chrome-headless-shell" / "linux-155.0.8059.79"
            other.mkdir(parents=True)

            def run(*_args, **_kwargs):
                seen.append((partial.exists(), other.exists()))
                return _done(1 if len(seen) == 1 else 0)

            with mock.patch.object(mermaid_cli.subprocess, "run", side_effect=run):
                mermaid_cli.ensure()
        self.assertEqual(seen, [(True, True), (False, True)])

    def test_a_second_failure_warns_with_puppeteers_output(self) -> None:
        calls, warnings = self.provision(euid=0, results=[1, 1])
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(warnings), 1)
        self.assertIn("out\nerr\n", warnings[0])

    def test_the_pinned_browser_is_not_provisioned_again(self) -> None:
        with _environment() as (_, cache):
            _install_browser(cache, REVISION)
            with mock.patch.object(mermaid_cli.subprocess, "run") as run:
                mermaid_cli.ensure()
        run.assert_not_called()

    def test_a_browser_of_another_revision_is_replaced(self) -> None:
        with _environment() as (_, cache):
            _install_browser(cache, "155.0.8059.79")
            with mock.patch.object(
                mermaid_cli.subprocess, "run", return_value=_done(0)
            ) as run:
                mermaid_cli.ensure()
        run.assert_called_once()

    def test_mmdc_without_its_own_puppeteer_warns(self) -> None:
        with (
            _environment(revision=None),
            mock.patch.object(mermaid_cli, "warn") as warn,
            mock.patch.object(mermaid_cli.subprocess, "run") as run,
        ):
            mermaid_cli.ensure()
        run.assert_not_called()
        warn.assert_called_once()

    def test_a_timeout_warns_instead_of_raising(self) -> None:
        with (
            _environment(),
            mock.patch.object(
                mermaid_cli.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("puppeteer", 900),
            ),
            mock.patch.object(mermaid_cli, "warn") as warn,
        ):
            mermaid_cli.ensure()
        warn.assert_called_once()


class TestBrowserInstalled(unittest.TestCase):
    def test_only_the_pinned_revision_counts(self) -> None:
        with _environment() as (_, cache):
            _install_browser(cache, "155.0.8059.79")
            self.assertFalse(mermaid_cli.browser_installed())
            _install_browser(cache, REVISION)
            self.assertTrue(mermaid_cli.browser_installed())

    def test_the_revision_is_read_from_mmdcs_puppeteer_core(self) -> None:
        with _environment():
            self.assertEqual(mermaid_cli.browser_revision(), REVISION)

    def test_a_puppeteer_core_nested_under_puppeteer_wins(self) -> None:
        with _environment(revision="155.0.8059.79", nested=REVISION) as (_, cache):
            self.assertEqual(mermaid_cli.browser_revision(), REVISION)
            _install_browser(cache, REVISION)
            self.assertTrue(mermaid_cli.browser_installed())


if __name__ == "__main__":
    unittest.main()
