"""The routine contract: a routine declares ordered steps and renders a
Mermaid flowchart from them; ``build`` compiles the steps into a LangGraph
graph. LangGraph is imported lazily inside ``build`` so ``show`` needs only
this module, never the graph engine.

A step's ``kind`` is one of:

- ``deterministic``: a node that calls repository logic in ``cli/`` or
  ``utils/`` through a make target or ``python -m``; it runs no model and
  reads no untrusted input into a tool.
- ``model``: the only kind that calls the gateway; it reads untrusted input
  and holds no tools.
- ``ask``: a node that pauses for an owner approval through the orchestrator.
- ``terminal``: an end state (a report, a pull request, a skip).
"""

from __future__ import annotations

from dataclasses import dataclass

STEP_KINDS = ("deterministic", "model", "ask", "terminal")
_SHAPE = {
    "deterministic": ("[", "]"),
    "model": ("{{", "}}"),
    "ask": ("{", "}"),
    "terminal": ("([", "])"),
}


@dataclass(frozen=True)
class Step:
    """One routine step.

    Args:
        id: a short identifier unique within the routine.
        label: the one-line human description shown by ``show``.
        kind: one of ``STEP_KINDS``.
        nxt: the id of the next step, or ``None`` for a terminal step.
    """

    id: str
    label: str
    kind: str = "deterministic"
    nxt: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in STEP_KINDS:
            raise ValueError(f"step {self.id!r}: unknown kind {self.kind!r}")


def mermaid(steps: list[Step]) -> str:
    """Return a Mermaid ``flowchart TD`` of ``steps``, each shaped by its kind."""
    lines = ["flowchart TD"]
    for step in steps:
        opener, closer = _SHAPE[step.kind]
        lines.append(f'  {step.id}{opener}"{step.label}"{closer}')
    lines.extend(f"  {step.id} --> {step.nxt}" for step in steps if step.nxt)
    return "\n".join(lines)


def build(name: str, steps: list[Step]):
    """Compile ``steps`` into a compiled LangGraph graph.

    Imported lazily: a caller that only renders the routine never loads
    LangGraph. The orchestrator container ships it; the lint and ``show`` do
    not need it.

    Args:
        name: the routine name.
        steps: the ordered steps; each deterministic step becomes a node.
    """
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(dict)
    for step in steps:
        graph.add_node(step.id, lambda state, _s=step: state)
    graph.add_edge(START, steps[0].id)
    for step in steps:
        graph.add_edge(step.id, END if step.nxt is None else step.nxt)
    return graph.compile()
