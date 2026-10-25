"""The routine contract: a routine declares ordered steps with typed kinds and
their edges, renders a Mermaid flowchart from them, and compiles them into a
LangGraph graph. LangGraph is imported lazily inside ``build`` so ``show`` needs
only this module, never the graph engine.

A step's ``kind`` shapes its node and states what it may do:

- ``trigger``: the entry event; a stadium.
- ``deterministic``: a node that calls repository logic in ``cli/`` or
  ``utils/`` through a make target or ``python -m``; it runs no model and reads
  no untrusted input into a tool; a rectangle.
- ``decision``: a deterministic yes/no check that branches; a diamond.
- ``model``: the only kind that calls the gateway; it reads untrusted input and
  holds no tools; a hexagon.
- ``ask``: a node that pauses for an owner approval through the orchestrator; a
  diamond.
- ``terminal``: an end state (a report, a pull request, a skip); a stadium.

A step reaches the next through ``nxt`` (one target) or ``branches`` (ordered
``(label, target)`` edges for a decision, ask or looping node); a terminal step
has neither. ``fn`` is the node callable ``(state) -> state`` for a deterministic
or decision step; a step without one compiles to a passthrough, which is also
the stub a model node runs as in a unit test. A decision node writes its chosen
branch label under its own id in the state; the router defaults to the first
branch, so a stub run with empty state follows the forward path to a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

STEP_KINDS = ("trigger", "deterministic", "decision", "model", "ask", "terminal")
_SHAPE = {
    "trigger": ("([", "])"),
    "deterministic": ("[", "]"),
    "decision": ("{", "}"),
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
        nxt: the id of the single next step, or ``None`` for a terminal or a
            branching step.
        branches: for a decision, ask or looping node, the ordered
            ``(label, target)`` edges; the first is the forward path a stub run
            follows.
        fn: the node callable ``(state) -> state`` for a deterministic or
            decision step; ``None`` compiles to a passthrough.
    """

    id: str
    label: str
    kind: str = "deterministic"
    nxt: str | None = None
    branches: tuple[tuple[str, str], ...] = ()
    fn: Callable[[dict], dict] | None = None

    def __post_init__(self) -> None:
        if self.kind not in STEP_KINDS:
            raise ValueError(f"step {self.id!r}: unknown kind {self.kind!r}")
        if self.nxt and self.branches:
            raise ValueError(f"step {self.id!r}: set nxt or branches, not both")


def mermaid(steps: list[Step]) -> str:
    """Return a Mermaid ``flowchart TD`` of ``steps``: each node shaped by its
    kind, each linear edge plain and each branch edge labelled."""
    lines = ["flowchart TD"]
    for step in steps:
        opener, closer = _SHAPE[step.kind]
        lines.append(f'  {step.id}{opener}"{step.label}"{closer}')
    for step in steps:
        if step.nxt:
            lines.append(f"  {step.id} --> {step.nxt}")
        lines.extend(f'  {step.id} -->|"{label}"| {target}' for label, target in step.branches)
    return "\n".join(lines)


def _passthrough(state: dict) -> dict:
    """A node that leaves the state unchanged: the default for a step without a
    callable and the stub a model node runs as in a unit test."""
    return state


def _router(step: Step):
    """Return a LangGraph router that reads the branch label the decision node
    wrote under ``step.id`` and falls back to the first branch."""
    labels = [label for label, _ in step.branches]

    def route(state: dict) -> str:
        choice = state.get(step.id, labels[0])
        return choice if choice in labels else labels[0]

    return route


def build(name: str, steps: list[Step]):
    """Compile ``steps`` into a compiled LangGraph graph.

    Imported lazily: a caller that only renders the routine never loads
    LangGraph. The orchestrator container ships it; the lint and ``show`` do
    not need it.

    Args:
        name: the routine name.
        steps: the ordered steps; each step becomes a node, linear steps a plain
            edge and branching steps a conditional edge.
    """
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(dict)
    for step in steps:
        graph.add_node(step.id, step.fn if step.fn is not None else _passthrough)
    graph.add_edge(START, steps[0].id)
    for step in steps:
        if step.branches:
            graph.add_conditional_edges(step.id, _router(step), dict(step.branches))
        else:
            graph.add_edge(step.id, step.nxt if step.nxt is not None else END)
    return graph.compile()
