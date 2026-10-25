"""Unit test: the designer and implementer routine decision nodes route on
parsed evidence and default to their forward branch when the evidence is absent."""

from __future__ import annotations

import unittest

from agents.routines import design, implementer

_JUNIT_RED = (
    '<testsuite><testcase name="t"><failure message="x">boom</failure>'
    "</testcase></testsuite>"
)


class TestDesignerDecisions(unittest.TestCase):
    def test_spec_green_reads_junit(self) -> None:
        self.assertEqual(design._spec_green({"junit_xml": _JUNIT_RED})["D3"], "❌ red")
        self.assertEqual(design._spec_green({})["D3"], "✅ green")

    def test_negative_control_passes_only_red_then_green(self) -> None:
        passed = design._negative_control({"nc_before_red": True, "nc_after_green": True})
        self.assertEqual(passed["D4"], "✅ turns red")
        failed = design._negative_control({"nc_before_red": False, "nc_after_green": True})
        self.assertEqual(failed["D4"], "❌ stays green")
        self.assertEqual(design._negative_control({})["D4"], "✅ turns red")


class TestImplementerDecisions(unittest.TestCase):
    def test_gate_reads_the_table(self) -> None:
        self.assertEqual(implementer._gate({"gate_output": "FAILED TARGETS: x"})["D2"], "❌ red")
        self.assertEqual(implementer._gate({})["D2"], "✅ green")

    def test_watch_flags_a_red_app(self) -> None:
        self.assertEqual(implementer._watch({"app_red": True})["D4"], "🔴 app red")
        self.assertEqual(implementer._watch({})["D4"], "🟢 all green")


if __name__ == "__main__":
    unittest.main()
