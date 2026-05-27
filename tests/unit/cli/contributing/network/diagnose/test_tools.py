"""Unit tests for cli.contributing.network.diagnose.tools."""

from __future__ import annotations

import io
import tempfile
import unittest
from unittest.mock import patch

from cli.contributing.network.diagnose import tools as tools_mod
from cli.contributing.network.diagnose.tools import (
    detect_distro_id,
    ensure_tools,
    missing_tools,
)


class TestDetectDistroId(unittest.TestCase):
    def _make_file(self, content: str) -> str:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".env") as f:
            f.write(content)
            return f.name

    def test_reads_quoted_id(self) -> None:
        p = self._make_file('NAME="Debian"\nID="debian"\n')
        self.assertEqual(detect_distro_id(os_release_path=p), "debian")

    def test_reads_unquoted_id(self) -> None:
        p = self._make_file("NAME=Arch\nID=arch\n")
        self.assertEqual(detect_distro_id(os_release_path=p), "arch")

    def test_lowercases_id(self) -> None:
        p = self._make_file("ID=Fedora\n")
        self.assertEqual(detect_distro_id(os_release_path=p), "fedora")

    def test_returns_empty_when_unreadable(self) -> None:
        self.assertEqual(detect_distro_id(os_release_path="/nonexistent/path"), "")

    def test_returns_empty_when_no_id_line(self) -> None:
        p = self._make_file("NAME=Foo\n")
        self.assertEqual(detect_distro_id(os_release_path=p), "")


class TestMissingTools(unittest.TestCase):
    @patch("cli.contributing.network.diagnose.tools.shutil.which")
    def test_returns_all_when_none_present(self, mock_which) -> None:
        mock_which.return_value = None
        self.assertEqual(set(missing_tools()), {"ping", "ip"})

    @patch("cli.contributing.network.diagnose.tools.shutil.which")
    def test_returns_only_missing(self, mock_which) -> None:
        mock_which.side_effect = lambda t: "/bin/ip" if t == "ip" else None
        self.assertEqual(missing_tools(), ["ping"])

    @patch("cli.contributing.network.diagnose.tools.shutil.which")
    def test_returns_empty_when_all_present(self, mock_which) -> None:
        mock_which.return_value = "/bin/x"
        self.assertEqual(missing_tools(), [])


class TestEnsureTools(unittest.TestCase):
    def test_noop_when_nothing_missing(self) -> None:
        with (
            patch.object(tools_mod, "missing_tools", return_value=[]) as mm,
            patch.object(tools_mod, "cmd_capture") as cc,
        ):
            ensure_tools()
            mm.assert_called_once()
            cc.assert_not_called()

    def test_skips_unsupported_distro(self) -> None:
        buf = io.StringIO()
        with (
            patch.object(tools_mod, "missing_tools", return_value=["ping"]),
            patch.object(tools_mod, "detect_distro_id", return_value="gentoo"),
            patch.object(tools_mod, "cmd_capture") as cc,
            patch.object(tools_mod.sys, "stderr", buf),
        ):
            ensure_tools()
        self.assertIn("unsupported", buf.getvalue())
        cc.assert_not_called()

    def test_debian_runs_update_then_install(self) -> None:
        calls: list[list[str]] = []

        def fake_capture(argv, timeout=5.0):
            calls.append(list(argv))
            return 0, ""

        with (
            patch.object(tools_mod, "missing_tools", return_value=["ping"]),
            patch.object(tools_mod, "detect_distro_id", return_value="debian"),
            patch.object(tools_mod, "cmd_capture", side_effect=fake_capture),
            patch.object(tools_mod.os, "geteuid", return_value=0),
            patch.object(tools_mod.shutil, "which", return_value=None),
        ):
            ensure_tools()

        self.assertEqual(calls[0][:2], ["apt-get", "update"])
        self.assertEqual(calls[1][0], "apt-get")
        self.assertIn("iputils-ping", calls[1])

    def test_prepends_sudo_when_non_root_with_sudo(self) -> None:
        seen: list[list[str]] = []

        def fake_capture(argv, timeout=5.0):
            seen.append(list(argv))
            return 0, ""

        with (
            patch.object(tools_mod, "missing_tools", return_value=["ping"]),
            patch.object(tools_mod, "detect_distro_id", return_value="arch"),
            patch.object(tools_mod, "cmd_capture", side_effect=fake_capture),
            patch.object(tools_mod.os, "geteuid", return_value=1000),
            patch.object(tools_mod.shutil, "which", return_value="/usr/bin/sudo"),
        ):
            ensure_tools()

        self.assertEqual(seen[0][0], "sudo")
        self.assertEqual(seen[0][1], "pacman")

    def test_reports_install_failure(self) -> None:
        buf = io.StringIO()
        with (
            patch.object(tools_mod, "missing_tools", return_value=["ping"]),
            patch.object(tools_mod, "detect_distro_id", return_value="arch"),
            patch.object(
                tools_mod, "cmd_capture", return_value=(2, "pacman: package not found")
            ),
            patch.object(tools_mod.os, "geteuid", return_value=0),
            patch.object(tools_mod.shutil, "which", return_value=None),
            patch.object(tools_mod.sys, "stderr", buf),
        ):
            ensure_tools()
        self.assertIn("FAILED rc=2", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
