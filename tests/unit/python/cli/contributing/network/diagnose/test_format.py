"""Unit tests for cli.contributing.network.diagnose.format."""

from __future__ import annotations

import io
import subprocess
import unittest
from unittest.mock import patch

from cli.contributing.network.diagnose.format import cmd_capture, line, section


class TestSection(unittest.TestCase):
    def test_writes_decorated_title(self) -> None:
        buf = io.StringIO()
        section("hello", file=buf)
        self.assertEqual(buf.getvalue(), "\n=== hello ===\n")


class TestLine(unittest.TestCase):
    def test_writes_two_space_indented_pair(self) -> None:
        buf = io.StringIO()
        line("LBL", "value", file=buf)
        self.assertEqual(buf.getvalue(), "  LBL: value\n")


class TestCmdCapture(unittest.TestCase):
    @patch("cli.contributing.network.diagnose.format.subprocess.run")
    def test_returns_rc_and_combined_output(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["x"], returncode=7, stdout="OUT", stderr="ERR"
        )
        rc, out = cmd_capture(["x"])
        self.assertEqual(rc, 7)
        self.assertEqual(out, "OUTERR")

    @patch("cli.contributing.network.diagnose.format.subprocess.run")
    def test_handles_missing_binary(self, mock_run) -> None:
        mock_run.side_effect = FileNotFoundError("no such file")
        rc, out = cmd_capture(["ghost-binary"])
        self.assertEqual(rc, -1)
        self.assertIn("ghost-binary", out)

    @patch("cli.contributing.network.diagnose.format.subprocess.run")
    def test_handles_timeout(self, mock_run) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["slow"], timeout=1.0)
        rc, out = cmd_capture(["slow"], timeout=1.0)
        self.assertEqual(rc, -2)
        self.assertIn("timeout after 1.0s", out)
        self.assertIn("slow", out)

    @patch("cli.contributing.network.diagnose.format.subprocess.run")
    def test_treats_none_streams_as_empty(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["x"], returncode=0, stdout=None, stderr=None
        )
        rc, out = cmd_capture(["x"])
        self.assertEqual((rc, out), (0, ""))


if __name__ == "__main__":
    unittest.main()
