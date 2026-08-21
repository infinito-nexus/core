import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.github import pytest_summary as ps

_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="4" failures="1" skipped="1" time="3.5">
    <testcase classname="tests.unit.test_a.TestA" name="test_fast" time="0.10"/>
    <testcase classname="tests.unit.test_a.TestA" name="test_slow" time="2.50"/>
    <testcase classname="tests.unit.test_b.TestB" name="test_broken" time="0.40">
      <failure message="boom">trace</failure>
    </testcase>
    <testcase classname="tests.unit.test_b.TestB" name="test_off" time="0.00">
      <skipped message="disabled"/>
    </testcase>
  </testsuite>
</testsuites>
"""


class TestRenderReport(unittest.TestCase):
    def _render(self, xml: str, name: str = "unit.xml") -> str:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            path.write_text(xml, encoding="utf-8")
            return ps._render_report(path)

    def test_headline_counts_and_time(self) -> None:
        out = self._render(_XML)
        self.assertIn("### 🧪 unit — 🟢 2 · 🔴 1 · 🔵 1 · 3.0s", out)

    def test_failures_render_open_and_all_tests_collapsed(self) -> None:
        out = self._render(_XML)
        self.assertIn("| `tests.unit.test_b.TestB::test_broken` | 0.40s |", out)
        self.assertIn("<summary>All 4 tests (slowest first)</summary>", out)
        self.assertIn("| `tests.unit.test_a.TestA::test_slow` | 🟢 | 2.50s |", out)
        self.assertIn("| `tests.unit.test_b.TestB::test_off` | 🔵 | 0.00s |", out)

    def test_slowest_first_ordering(self) -> None:
        out = self._render(_XML)
        self.assertLess(out.index("test_slow"), out.index("test_fast"))

    def test_unparseable_xml_degrades_gracefully(self) -> None:
        out = self._render("not xml at all")
        self.assertIn("_Unparseable junit XML:", out)


if __name__ == "__main__":
    unittest.main()
