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
LDD = (
    "\tlinux-vdso.so.1 (0x00007f5999895000)\n"
    "\tlibnss3.so => not found\n"
    "\tlibglib-2.0.so.0 => /usr/lib/libglib-2.0.so.0 (0x00007f598d09d000)\n"
    "\tlibgbm.so.1 => not found\n"
    "\tlibnss3.so => not found\n"
)


def _done(returncode: int, stdout: str = "out\n") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="err\n")


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


def _install_browser(cache: Path, revision: str) -> Path:
    build = cache / "chrome-headless-shell" / f"linux-{revision}" / "linux64"
    build.mkdir(parents=True, exist_ok=True)
    executable = build / "chrome-headless-shell"
    executable.write_text("", encoding="utf-8")
    return executable


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
            mock.patch.object(mermaid_cli, "missing_libraries", return_value=[]),
            mock.patch.object(mermaid_cli, "fonts_installed", return_value=True),
        ):
            yield Path(prefix), Path(cache)


class TestBrowserProvisioning(unittest.TestCase):
    def provision(
        self, *, euid: int, results: list[int], apt: bool = True
    ) -> list[mock._Call]:
        """Run ``ensure()`` with mmdc present and a stubbed puppeteer.

        Args:
            euid: effective uid the run pretends to have.
            results: exit codes the successive puppeteer calls return; a 0
                lays the pinned browser into the cache.
            apt: whether apt-get is on the PATH.

        Returns:
            The recorded subprocess calls.
        """
        calls: list[mock._Call] = []
        codes = iter(results)
        with _environment() as (_, cache):

            def run(*args, **kwargs):
                calls.append(mock.call(*args, **kwargs))
                code = next(codes)
                if code == 0:
                    _install_browser(cache, REVISION)
                return _done(code)

            with (
                mock.patch.object(mermaid_cli.os, "geteuid", return_value=euid),
                mock.patch.object(
                    mermaid_cli,
                    "which",
                    side_effect=lambda cmd: apt or cmd != "apt-get",
                ),
                mock.patch.object(mermaid_cli.subprocess, "run", side_effect=run),
            ):
                mermaid_cli.ensure()
        return calls

    def test_root_on_apt_installs_the_browser_with_its_libraries(self) -> None:
        calls = self.provision(euid=0, results=[0])
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0].args[0][-2:], ["chrome-headless-shell", "--install-deps"]
        )

    def test_root_without_apt_leaves_the_libraries_to_the_soname_install(
        self,
    ) -> None:
        calls = self.provision(euid=0, results=[0], apt=False)
        self.assertNotIn("--install-deps", calls[0].args[0])

    def test_the_browser_comes_from_the_puppeteer_next_to_mmdc(self) -> None:
        calls = self.provision(euid=0, results=[0])
        self.assertTrue(
            calls[0]
            .args[0][0]
            .endswith("@mermaid-js/mermaid-cli/node_modules/.bin/puppeteer")
        )

    def test_a_user_installs_the_browser_without_libraries(self) -> None:
        calls = self.provision(euid=1000, results=[0])
        self.assertNotIn("--install-deps", calls[0].args[0])

    def test_the_browser_install_downloads_despite_the_mmdc_skip_flag(self) -> None:
        with mock.patch.dict(os.environ, {"PUPPETEER_SKIP_DOWNLOAD": "1"}):
            calls = self.provision(euid=0, results=[0])
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
                if len(seen) == 1:
                    return _done(1)
                _install_browser(cache, REVISION)
                return _done(0)

            with mock.patch.object(mermaid_cli.subprocess, "run", side_effect=run):
                mermaid_cli.ensure()
        self.assertEqual(seen, [(True, True), (False, True)])

    def test_a_second_failure_raises_with_puppeteers_output(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "out\nerr\n"):
            self.provision(euid=0, results=[1, 1])

    def test_the_pinned_browser_is_not_provisioned_again(self) -> None:
        with _environment() as (_, cache):
            _install_browser(cache, REVISION)
            with mock.patch.object(mermaid_cli.subprocess, "run") as run:
                mermaid_cli.ensure()
        run.assert_not_called()

    def test_a_browser_of_another_revision_is_replaced(self) -> None:
        with _environment() as (_, cache):
            _install_browser(cache, "155.0.8059.79")

            def run(*_args, **_kwargs):
                _install_browser(cache, REVISION)
                return _done(0)

            with mock.patch.object(
                mermaid_cli.subprocess, "run", side_effect=run
            ) as stub:
                mermaid_cli.ensure()
        stub.assert_called_once()

    def test_a_reported_success_without_the_browser_raises(self) -> None:
        with (
            _environment(),
            mock.patch.object(mermaid_cli.subprocess, "run", return_value=_done(0)),
            self.assertRaisesRegex(RuntimeError, "still missing"),
        ):
            mermaid_cli.ensure()

    def test_mmdc_without_its_own_puppeteer_raises(self) -> None:
        with (
            _environment(revision=None),
            mock.patch.object(mermaid_cli.subprocess, "run") as run,
            self.assertRaisesRegex(RuntimeError, "no puppeteer next to mmdc"),
        ):
            mermaid_cli.ensure()
        run.assert_not_called()

    def test_a_timeout_propagates(self) -> None:
        with (
            _environment(),
            mock.patch.object(
                mermaid_cli.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("puppeteer", 900),
            ),
            self.assertRaises(subprocess.TimeoutExpired),
        ):
            mermaid_cli.ensure()


class TestMmdcInstall(unittest.TestCase):
    def test_a_failed_npm_install_propagates(self) -> None:
        with (
            mock.patch.object(mermaid_cli, "which", return_value=False),
            mock.patch.object(mermaid_cli, "install_command_via_pkg"),
            mock.patch.object(
                mermaid_cli, "npm_install_global", side_effect=RuntimeError("npm")
            ),
            mock.patch.object(mermaid_cli, "_ensure_browser") as browser,
            self.assertRaisesRegex(RuntimeError, "npm"),
        ):
            mermaid_cli.ensure()
        browser.assert_not_called()

    def test_mmdc_still_missing_after_npm_raises(self) -> None:
        with (
            mock.patch.object(mermaid_cli, "which", return_value=False),
            mock.patch.object(mermaid_cli, "install_command_via_pkg"),
            mock.patch.object(mermaid_cli, "npm_install_global"),
            mock.patch.object(mermaid_cli, "_ensure_browser") as browser,
            self.assertRaisesRegex(RuntimeError, "mmdc"),
        ):
            mermaid_cli.ensure()
        browser.assert_not_called()


class TestBrowserLibraries(unittest.TestCase):
    def test_ldd_not_found_lines_become_sorted_sonames(self) -> None:
        with mock.patch.object(
            mermaid_cli.subprocess, "run", return_value=_done(0, LDD)
        ) as run:
            missing = mermaid_cli.missing_libraries(Path("/opt/chs"))
        self.assertEqual(missing, ["libgbm.so.1", "libnss3.so"])
        self.assertEqual(run.call_args.args[0], ["ldd", "/opt/chs"])

    def ensure_libraries(
        self, *, manager: str, missing: list[list[str]], files: dict[str, str]
    ) -> mock.Mock:
        """Run the library step with stubbed ldd, package manager and file DB.

        Args:
            manager: the package manager the host reports.
            missing: successive ``missing_libraries`` results.
            files: ``pacman -Fq`` stdout per queried path.

        Returns:
            The stubbed ``run_privileged``.
        """

        def query(argv, **_kwargs):
            return _done(0, files.get(argv[-1], ""))

        with (
            mock.patch.object(mermaid_cli, "missing_libraries", side_effect=missing),
            mock.patch.object(
                mermaid_cli, "detect_package_manager", return_value=manager
            ),
            mock.patch.object(mermaid_cli.subprocess, "run", side_effect=query),
            mock.patch.object(mermaid_cli, "run_privileged") as privileged,
        ):
            mermaid_cli._ensure_browser_libraries(Path("/opt/chs"))
        return privileged

    def test_resolved_libraries_install_nothing(self) -> None:
        privileged = self.ensure_libraries(manager="dnf", missing=[[]], files={})
        privileged.assert_not_called()

    def test_the_redhat_family_installs_by_soname_provide(self) -> None:
        privileged = self.ensure_libraries(
            manager="dnf", missing=[["libgbm.so.1", "libnss3.so"], []], files={}
        )
        privileged.assert_called_once_with(
            ["dnf", "-y", "install", "libgbm.so.1()(64bit)", "libnss3.so()(64bit)"]
        )

    def test_arch_takes_the_first_package_owning_each_soname(self) -> None:
        privileged = self.ensure_libraries(
            manager="pacman",
            missing=[["libgbm.so.1", "libnss3.so"], []],
            files={
                "usr/lib/libgbm.so.1": "extra/mesa\nextra/mesa-amber\n",
                "usr/lib/libnss3.so": "core/nss\n",
            },
        )
        self.assertEqual(
            privileged.call_args_list,
            [
                mock.call(["pacman", "-Fy"]),
                mock.call(["pacman", "-Syu", "--noconfirm", "--needed", "mesa", "nss"]),
            ],
        )

    def test_apt_without_libraries_fails_without_installing(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "--install-deps"):
            self.ensure_libraries(manager="apt-get", missing=[["libnss3.so"]], files={})

    def test_libraries_still_missing_after_the_install_raise(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "still lacks libnss3.so"):
            self.ensure_libraries(
                manager="dnf", missing=[["libnss3.so"], ["libnss3.so"]], files={}
            )


class TestBrowserFonts(unittest.TestCase):
    def ensure_fonts(self, *, manager: str, present: list[bool]) -> mock.Mock:
        """Run the font step with a stubbed font check and package manager.

        Args:
            manager: the package manager the host reports.
            present: successive ``fonts_installed`` results.

        Returns:
            The stubbed ``run_privileged``.
        """
        with (
            mock.patch.object(mermaid_cli, "fonts_installed", side_effect=present),
            mock.patch.object(
                mermaid_cli, "detect_package_manager", return_value=manager
            ),
            mock.patch.object(mermaid_cli, "run_privileged") as privileged,
        ):
            mermaid_cli._ensure_fonts()
        return privileged

    def test_a_host_with_a_font_installs_nothing(self) -> None:
        privileged = self.ensure_fonts(manager="dnf", present=[True])
        privileged.assert_not_called()

    def test_the_redhat_family_installs_the_english_font_provide(self) -> None:
        for manager in ("dnf", "yum"):
            with self.subTest(manager=manager):
                privileged = self.ensure_fonts(manager=manager, present=[False, True])
                privileged.assert_called_once_with(
                    [manager, "-y", "install", "font(:lang=en)"]
                )

    def test_arch_installs_the_ttf_font_provide(self) -> None:
        privileged = self.ensure_fonts(manager="pacman", present=[False, True])
        privileged.assert_called_once_with(
            ["pacman", "-Syu", "--noconfirm", "--needed", "ttf-font"]
        )

    def test_apt_without_a_font_fails_without_installing(self) -> None:
        with (
            mock.patch.object(mermaid_cli, "fonts_installed", return_value=False),
            mock.patch.object(
                mermaid_cli, "detect_package_manager", return_value="apt-get"
            ),
            mock.patch.object(mermaid_cli, "run_privileged") as privileged,
            self.assertRaisesRegex(RuntimeError, "--install-deps"),
        ):
            mermaid_cli._ensure_fonts()
        privileged.assert_not_called()

    def test_no_font_after_the_install_raises(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "still finds no font"):
            self.ensure_fonts(manager="dnf", present=[False, False])

    def test_only_a_file_under_the_font_directory_counts(self) -> None:
        with TemporaryDirectory() as fonts:
            directory = Path(fonts)
            with mock.patch.object(mermaid_cli, "FONT_DIRECTORY", directory):
                (directory / "google-noto-vf").mkdir()
                self.assertFalse(mermaid_cli.fonts_installed())
                (directory / "google-noto-vf" / "NotoSans[wght].ttf").write_bytes(b"")
                self.assertTrue(mermaid_cli.fonts_installed())

    def test_a_missing_font_directory_counts_as_no_font(self) -> None:
        with mock.patch.object(
            mermaid_cli, "FONT_DIRECTORY", Path("/nonexistent/fonts")
        ):
            self.assertFalse(mermaid_cli.fonts_installed())


class TestBrowserInstalled(unittest.TestCase):
    def test_a_browser_without_any_font_is_not_installed(self) -> None:
        with _environment() as (_, cache):
            _install_browser(cache, REVISION)
            with mock.patch.object(mermaid_cli, "fonts_installed", return_value=False):
                self.assertFalse(mermaid_cli.browser_installed())

    def test_only_the_pinned_revision_counts(self) -> None:
        with _environment() as (_, cache):
            _install_browser(cache, "155.0.8059.79")
            self.assertFalse(mermaid_cli.browser_installed())
            _install_browser(cache, REVISION)
            self.assertTrue(mermaid_cli.browser_installed())

    def test_a_browser_with_missing_libraries_is_not_installed(self) -> None:
        with _environment() as (_, cache):
            _install_browser(cache, REVISION)
            with mock.patch.object(
                mermaid_cli, "missing_libraries", return_value=["libnss3.so"]
            ):
                self.assertFalse(mermaid_cli.browser_installed())

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
