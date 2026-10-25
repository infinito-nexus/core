"""Unit test: the maintainer routine graph carries the same nodes and edges as
the maintainer diagram in requirement 041, its decision nodes route on parsed
evidence, and a stub run (model nodes as passthroughs) reaches a terminal."""

from __future__ import annotations

import re
import unittest
from itertools import pairwise

from agents.routines import maintainer
from utils.cache.files import PROJECT_ROOT, read_text

try:
    import langgraph  # noqa: F401

    _HAVE_LANGGRAPH = True
except ImportError:
    _HAVE_LANGGRAPH = False

_ID = re.compile(r"[A-Za-z0-9_]+")


def _spec_edges() -> set[tuple[str, str]]:
    md = read_text(str(PROJECT_ROOT / "docs" / "requirements" / "041-agents-restructuring.md"))
    block = md.split("Maintainer routine:", 1)[1].split("```mermaid", 1)[1].split("```", 1)[0]
    edges: set[tuple[str, str]] = set()
    for raw in block.splitlines():
        line = re.sub(r"\|[^|]*\|", " ", raw)
        if "-->" not in line:
            continue
        ids = [m.group() for part in line.split("-->") if (m := _ID.match(part.strip()))]
        edges.update(pairwise(ids))
    return edges


def _routine_edges() -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for step in maintainer.STEPS:
        if step.nxt:
            edges.add((step.id, step.nxt))
        edges.update((step.id, target) for _, target in step.branches)
    return edges


class TestMaintainerGraph(unittest.TestCase):
    def test_edges_match_the_041_diagram(self) -> None:
        self.assertEqual(_routine_edges(), _spec_edges())

    def test_node_ids_match_the_041_diagram(self) -> None:
        spec_ids = {node for edge in _spec_edges() for node in edge}
        self.assertEqual({step.id for step in maintainer.STEPS}, spec_ids)

    def test_gate_decision_reads_the_table(self) -> None:
        red = maintainer._gate_verdict({"gate_output": "FAILED TARGETS: lint-python"})
        self.assertEqual(red["D6"], "❌ red")
        green = maintainer._gate_verdict({"gate_output": "FAILED TARGETS:\n"})
        self.assertEqual(green["D6"], "✅ green")

    def test_number_decision_blocks_unbacked(self) -> None:
        state = maintainer._numbers_verdict({"pr_text": "fixed 5 bugs", "evidence": "0 bugs"})
        self.assertEqual(state["D10"], "❌ no")
        self.assertEqual(state["unbacked_numbers"], ["5"])

    def test_change_ran_decision_detects_silence(self) -> None:
        silent = maintainer._change_ran_verdict({"ci_log": "- spec [skipped]", "change_marker": "spec"})
        self.assertEqual(silent["D13"], "❌ no")
        ran = maintainer._change_ran_verdict({"ci_log": "✓ spec passed", "change_marker": "spec"})
        self.assertEqual(ran["D13"], "✅ yes")

    @unittest.skipUnless(_HAVE_LANGGRAPH, "langgraph ships in the orchestrator image, not the sandbox venv")
    def test_stub_run_reaches_a_terminal(self) -> None:
        result = maintainer.build().invoke({})
        self.assertEqual(result["D13"], "❌ no")


if __name__ == "__main__":
    unittest.main()
