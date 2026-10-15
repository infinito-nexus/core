"""Unit tests for :mod:`utils.install.lint.mermaid_cli`."""

from __future__ import annotations

import os
import subprocess
import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.install.lint import mermaid_cli


def _done(returncode: int) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout="out\n", stderr="err\n")


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
            TemporaryDirectory() as cache,
            mock.patch.dict(os.environ, {"PUPPETEER_CACHE_DIR": cache}),
            mock.patch.object(mermaid_cli, "which", return_value=True),
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

    def test_a_user_installs_the_browser_without_libraries(self) -> None:
        calls, _ = self.provision(euid=1000, results=[0])
        self.assertNotIn("--install-deps", calls[0].args[0])

    def test_the_browser_install_downloads_despite_the_mmdc_skip_flag(self) -> None:
        with mock.patch.dict(os.environ, {"PUPPETEER_SKIP_DOWNLOAD": "1"}):
            calls, _ = self.provision(euid=0, results=[0])
        self.assertNotIn("PUPPETEER_SKIP_DOWNLOAD", calls[0].kwargs["env"])

    def test_a_failed_install_clears_the_browser_cache_and_retries_once(self) -> None:
        with TemporaryDirectory() as cache:
            folder = Path(cache) / "chrome-headless-shell" / "linux-1"
            folder.mkdir(parents=True)
            seen: list[bool] = []

            def run(*_args, **_kwargs):
                seen.append(folder.exists())
                return _done(1 if len(seen) == 1 else 0)

            with (
                mock.patch.dict(os.environ, {"PUPPETEER_CACHE_DIR": cache}),
                mock.patch.object(mermaid_cli, "which", return_value=True),
                mock.patch.object(mermaid_cli.subprocess, "run", side_effect=run),
            ):
                mermaid_cli.ensure()
        self.assertEqual(seen, [True, False])

    def test_a_second_failure_warns_with_puppeteers_output(self) -> None:
        calls, warnings = self.provision(euid=0, results=[1, 1])
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(warnings), 1)
        self.assertIn("out\nerr\n", warnings[0])

    def test_an_installed_browser_is_not_provisioned_again(self) -> None:
        with TemporaryDirectory() as cache:
            build = Path(cache) / "chrome-headless-shell" / "linux-1" / "linux64"
            build.mkdir(parents=True)
            (build / "chrome-headless-shell").write_text("", encoding="utf-8")
            with (
                mock.patch.dict(os.environ, {"PUPPETEER_CACHE_DIR": cache}),
                mock.patch.object(mermaid_cli, "which", return_value=True),
                mock.patch.object(mermaid_cli.subprocess, "run") as run,
            ):
                mermaid_cli.ensure()
        run.assert_not_called()

    def test_a_timeout_warns_instead_of_raising(self) -> None:
        with (
            TemporaryDirectory() as cache,
            mock.patch.dict(os.environ, {"PUPPETEER_CACHE_DIR": cache}),
            mock.patch.object(mermaid_cli, "which", return_value=True),
            mock.patch.object(
                mermaid_cli.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("npx", 900),
            ),
            mock.patch.object(mermaid_cli, "warn") as warn,
        ):
            mermaid_cli.ensure()
        warn.assert_called_once()


class TestBrowserInstalled(unittest.TestCase):
    def test_the_executable_in_the_puppeteer_cache_counts(self) -> None:
        with TemporaryDirectory() as cache:
            build = Path(cache) / "chrome-headless-shell" / "linux-1" / "linux64"
            build.mkdir(parents=True)
            with mock.patch.dict(os.environ, {"PUPPETEER_CACHE_DIR": cache}):
                self.assertFalse(mermaid_cli.browser_installed())
                (build / "chrome-headless-shell").write_text("", encoding="utf-8")
                self.assertTrue(mermaid_cli.browser_installed())


if __name__ == "__main__":
    unittest.main()
