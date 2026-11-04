"""Unit test: the maintainer routine's decision nodes route on parsed evidence,
and a stub run (model nodes as passthroughs) reaches a terminal."""

from __future__ import annotations

import unittest

from agents.routines import maintainer

try:
    import langgraph  # noqa: F401

    _HAVE_LANGGRAPH = True
except ImportError:
    _HAVE_LANGGRAPH = False


class TestMaintainerDecisions(unittest.TestCase):
    def test_gate_decision_reads_the_table(self) -> None:
        red = maintainer._gate_verdict({"gate_output": "FAILED TARGETS: lint-python"})
        self.assertEqual(red["D6"], "❌ red")
        green = maintainer._gate_verdict({"gate_output": "FAILED TARGETS:\n"})
        self.assertEqual(green["D6"], "✅ green")

    def test_number_decision_blocks_unbacked(self) -> None:
        state = maintainer._numbers_verdict(
            {"pr_text": "fixed 5 bugs", "evidence": "0 bugs"}
        )
        self.assertEqual(state["D10"], "❌ no")
        self.assertEqual(state["unbacked_numbers"], ["5"])

    def test_change_ran_decision_detects_silence(self) -> None:
        silent = maintainer._change_ran_verdict(
            {"ci_log": "- spec [skipped]", "change_marker": "spec"}
        )
        self.assertEqual(silent["D13"], "❌ no")
        ran = maintainer._change_ran_verdict(
            {"ci_log": "✓ spec passed", "change_marker": "spec"}
        )
        self.assertEqual(ran["D13"], "✅ yes")

    @unittest.skipUnless(
        _HAVE_LANGGRAPH,
        "langgraph ships in the orchestrator image, not the sandbox venv",
    )
    def test_stub_run_reaches_a_terminal(self) -> None:
        result = maintainer.build().invoke({})
        self.assertEqual(result["D13"], "❌ no")


if __name__ == "__main__":
    unittest.main()
