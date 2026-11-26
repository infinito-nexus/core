import contextlib
import io
import sys
import unittest
import unittest.mock
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


def _big_xml(cases: int, failures: int) -> str:
    rows = []
    for i in range(cases):
        body = "<failure/>" if i < failures else ""
        rows.append(
            f'<testcase classname="tests.big.Case{i % 50}" '
            f'name="test_{i:06d}_{"x" * 60}" time="{(cases - i) / 100:.2f}">{body}</testcase>'
        )
    return "<testsuites><testsuite>" + "".join(rows) + "</testsuite></testsuites>"


class TestMainBudget(unittest.TestCase):
    def _run(self) -> str:
        with TemporaryDirectory() as tmp:
            Path(tmp, "big.xml").write_text(_big_xml(20000, 30), encoding="utf-8")
            Path(tmp, "small.xml").write_text(_XML, encoding="utf-8")
            buf = io.StringIO()
            with (
                unittest.mock.patch.object(sys, "argv", ["x", tmp]),
                contextlib.redirect_stdout(buf),
            ):
                self.assertEqual(ps.main(), 0)
            return buf.getvalue()

    def test_output_stays_under_github_cap(self) -> None:
        self.assertLessEqual(len(self._run().encode("utf-8")), 1024 * 1024)

    def test_all_failures_and_small_table_kept(self) -> None:
        out = self._run()
        for i in range(30):
            self.assertIn(f"test_{i:06d}_", out)
        self.assertIn("| `tests.unit.test_a.TestA::test_slow` | 🟢 | 2.50s |", out)
        self.assertIn("| `tests.unit.test_b.TestB::test_off` | 🔵 | 0.00s |", out)

    def test_big_table_cut_at_fast_end_with_left_out_line(self) -> None:
        out = self._run()
        big = out.split("### 🧪 small")[0]
        self.assertIn("<summary>All 20000 tests (slowest first)</summary>", big)
        self.assertIn("test_000000_", big)
        self.assertNotIn("test_019999_", big)
        last = big.split("</details>")[0].rstrip().splitlines()[-1]
        self.assertRegex(last, r"^\| _\d+ faster tests left out_ \| \| \|$")


if __name__ == "__main__":
    unittest.main()
