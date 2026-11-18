"""``utils.tests.pytest.longest_first`` hands the slowest loadscope scopes out first."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from utils.tests.pytest.longest_first import (
    item_counts,
    junit_classname,
    longest_first,
    pytest_collection_modifyitems,
    scope_durations,
)

ITEMS = [
    SimpleNamespace(nodeid=nodeid)
    for nodeid in (
        "tests/a/test_fast.py::TestFast::test_one",
        "tests/a/test_slow.py::TestSlow::test_one",
        "tests/a/test_slow.py::TestSlow::test_two",
        "tests/a/test_new.py::test_function",
        "tests/a/test_many.py::TestMany::test_one",
        "tests/a/test_many.py::TestMany::test_two",
        "tests/a/test_many.py::TestMany::test_three",
    )
]
REPORT = (
    "<testsuites><testsuite>"
    '<testcase classname="tests.a.test_fast.TestFast" name="test_one" time="1"/>'
    '<testcase classname="tests.a.test_slow.TestSlow" name="test_one" time="40"/>'
    '<testcase classname="tests.a.test_slow.TestSlow" name="test_two" time="20"/>'
    '<testcase classname="tests.a.test_many.TestMany" name="test_one" time="5"/>'
    "</testsuite></testsuites>"
)


def _ids(items: list[SimpleNamespace]) -> list[str]:
    return [item.nodeid.split("/")[-1] for item in items]


class TestLongestFirst(unittest.TestCase):
    def test_the_classname_matches_what_junit_records(self) -> None:
        self.assertEqual(junit_classname(ITEMS[1].nodeid), "tests.a.test_slow.TestSlow")
        self.assertEqual(junit_classname(ITEMS[3].nodeid), "tests.a.test_new")

    def test_recorded_scopes_lead_by_time_and_new_ones_keep_collection_order(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "unit.xml"
            report.write_text(REPORT)
            ordered = longest_first(list(ITEMS), scope_durations(report))
        self.assertEqual(
            _ids(ordered),
            [
                "test_slow.py::TestSlow::test_one",
                "test_slow.py::TestSlow::test_two",
                "test_many.py::TestMany::test_one",
                "test_many.py::TestMany::test_two",
                "test_many.py::TestMany::test_three",
                "test_fast.py::TestFast::test_one",
                "test_new.py::test_function",
            ],
        )

    def test_without_a_report_the_largest_scope_leads_like_loadscope_reorder(
        self,
    ) -> None:
        config = SimpleNamespace(
            getoption=lambda name, default=None: "/nonexistent.xml"
        )
        items = list(ITEMS)
        pytest_collection_modifyitems(config, items)
        self.assertEqual(
            _ids(items)[:3],
            [
                "test_many.py::TestMany::test_one",
                "test_many.py::TestMany::test_two",
                "test_many.py::TestMany::test_three",
            ],
        )
        self.assertEqual(item_counts(ITEMS)["tests.a.test_slow.TestSlow"], 2)

    def test_an_unreadable_report_yields_no_durations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "unit.xml"
            broken.write_text("<testsuites>")
            self.assertEqual(scope_durations(broken), {})


if __name__ == "__main__":
    unittest.main()
