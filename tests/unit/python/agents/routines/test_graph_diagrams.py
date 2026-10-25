"""Unit test (criterion 26): every agent routine graph carries the same nodes
and edges as its diagram in the agents restructuring specification."""

from __future__ import annotations

import re
import unittest
from itertools import pairwise
from typing import TYPE_CHECKING

from agents.routines import (
    design,
    discover,
    hacker_scan,
    implementer,
    legal_audit,
    maintainer,
    reviewer,
    support,
)
from utils.cache.files import PROJECT_ROOT, read_text

if TYPE_CHECKING:
    from types import ModuleType

_ID = re.compile(r"[A-Za-z0-9_]+")
_SPEC = PROJECT_ROOT / "docs" / "requirements" / "041-agents-restructuring.md"
_CASES = (
    ("maintainer", maintainer, "Maintainer routine:"),
    ("designer", design, "Designer routine:"),
    ("implementer", implementer, "Implementer routine:"),
    ("reviewer", reviewer, "Reviewer routine:"),
    ("hacker", hacker_scan, "Hacker routine:"),
    ("counsel", legal_audit, "Counsel routine:"),
    ("support", support, "Support routine:"),
)


def _spec_edges(heading: str) -> set[tuple[str, str]]:
    block = (
        read_text(str(_SPEC))
        .split(heading, 1)[1]
        .split("```mermaid", 1)[1]
        .split("```", 1)[0]
    )
    edges: set[tuple[str, str]] = set()
    for raw in block.splitlines():
        line = re.sub(r"\|[^|]*\|", " ", raw)
        if "-->" not in line:
            continue
        ids = [m.group() for part in line.split("-->") if (m := _ID.match(part.strip()))]
        edges.update(pairwise(ids))
    return edges


def _routine_edges(module: ModuleType) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for step in module.STEPS:
        if step.nxt:
            edges.add((step.id, step.nxt))
        edges.update((step.id, target) for _, target in step.branches)
    return edges


class TestGraphDiagrams(unittest.TestCase):
    def test_edges_match_the_diagram(self) -> None:
        for name, module, heading in _CASES:
            with self.subTest(routine=name):
                self.assertEqual(_routine_edges(module), _spec_edges(heading))

    def test_nodes_match_the_diagram(self) -> None:
        for name, module, heading in _CASES:
            with self.subTest(routine=name):
                spec_ids = {node for edge in _spec_edges(heading) for node in edge}
                self.assertEqual({step.id for step in module.STEPS}, spec_ids)

    def test_tool_nodes_are_not_discovered_as_routines(self) -> None:
        names = discover()
        self.assertIn("maintainer", names)
        self.assertIn("implementer", names)
        self.assertFalse([name for name in names if name.startswith("tools")])


if __name__ == "__main__":
    unittest.main()
