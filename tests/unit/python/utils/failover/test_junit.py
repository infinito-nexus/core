from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from utils.failover.junit import CaseResult, write_junit


class TestJunit(unittest.TestCase):
    def _write(self, cases: list[CaseResult]) -> ET.Element:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out" / "junit.xml"
            write_junit(path, suite="failover-postgres", cases=cases)
            return ET.parse(path).getroot()  # noqa: S314 - parses the file the test just wrote

    def test_counts_failures_and_skips(self):
        root = self._write(
            [
                CaseResult(name="standalone", seconds=1.5),
                CaseResult(name="node-crash", failures=["gap 99s > 30s"]),
                CaseResult(name="node-hang", skipped="later stage"),
            ]
        )
        suite = root.find("testsuite")
        self.assertEqual(suite.get("tests"), "3")
        self.assertEqual(suite.get("failures"), "1")
        self.assertEqual(suite.get("skipped"), "1")
        failing = suite.find("testcase[@name='node-crash']/failure")
        self.assertIn("gap 99s", failing.get("message"))

    def test_notes_land_in_system_out(self):
        root = self._write([CaseResult(name="rolling-change", notes=["goal missed"])])
        out = root.find("testsuite/testcase/system-out")
        self.assertIn("goal missed", out.text)


if __name__ == "__main__":
    unittest.main()
