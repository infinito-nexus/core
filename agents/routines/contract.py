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
  holds no tools; only the keys of its ``output_schema`` and its branch label
  leave it; a hexagon.
- ``ask``: a node that pauses for an owner approval through the orchestrator;
  approve resumes the routine, reject aborts it; a diamond.
- ``terminal``: an end state (a report, a pull request, a skip); a stadium.

A step reaches the next through ``nxt`` (one target) or ``branches`` (ordered
``(label, target)`` edges for a decision, ask or looping node); a terminal step
has neither. ``fn`` is the node callable ``(state) -> state`` for a deterministic
or decision step; a step without one compiles to a passthrough, which is also
the stub a model node runs as in a unit test. A decision node writes its chosen
branch label under its own id in the state; the router defaults to the first
branch, so a stub run with empty state follows the forward path to a terminal.
A decision may record itself through ``decide``, which writes the branch label
and appends one audit record, naming the state's evidence source, to the JSON
Lines ledger the state names.
"""

from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from utils.orchestrator.locks import wait_gate

if TYPE_CHECKING:
    from collections.abc import Callable, MutableMapping

LEDGER_KEY = "ledger"
EVIDENCE_SOURCE_KEY = "evidence_source"
LOCK_DIR_ENV = "ORCHESTRATOR_LOCK_DIR"
GATE_POLL_SECONDS = 5.0

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
        output_schema: for a model step, the ``(key, type)`` pairs its output
            may set; every other key it writes is dropped before the next
            node.
    """

    id: str
    label: str
    kind: str = "deterministic"
    nxt: str | None = None
    branches: tuple[tuple[str, str], ...] = ()
    fn: Callable[[dict], dict] | None = None
    output_schema: tuple[tuple[str, type], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in STEP_KINDS:
            raise ValueError(f"step {self.id!r}: unknown kind {self.kind!r}")
        if self.nxt and self.branches:
            raise ValueError(f"step {self.id!r}: set nxt or branches, not both")
        if self.output_schema and self.kind != "model":
            raise ValueError(f"step {self.id!r}: only a model step has a schema")


class AbortError(RuntimeError):
    """The owner rejected an ``ask`` step, or no owner answered it.

    Args:
        step: the id of the ``ask`` step.
    """

    def __init__(self, step: str) -> None:
        super().__init__(f"step {step!r}: the owner did not approve")
        self.step = step


def _ledger_file(path: str) -> Path:
    ledger = Path(path)
    if not ledger.is_absolute():
        raise ValueError(f"ledger {path!r} must be an absolute path")
    return ledger


def append_record(
    path: str, step: str, inputs: dict, outcome: str, source: str = ""
) -> dict:
    """Append one decision record to the ledger at ``path`` and return it.

    Args:
        path: the JSON Lines ledger file, an absolute path, by convention
            under /tmp; its parent is created. ``""`` writes nothing, so a run
            without a ledger still routes.
        step: the id of the decision step.
        inputs: the evidence the step decided on; a set is written as a sorted
            list. Never a raw log line or a digest of one, which may carry a
            credential.
        outcome: the branch label the step chose.
        source: where the evidence came from (a log path, a CI run); ``""``
            when the step decided on the state alone.

    Raises:
        ValueError: ``path`` is relative.
    """
    record = {
        "step": step,
        "inputs": inputs,
        "outcome": outcome,
        "evidence_source": source,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if path:
        ledger = _ledger_file(path)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=sorted)
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return record


def decide(
    state: MutableMapping, step: str, inputs: dict, outcome: str
) -> MutableMapping:
    """Write ``outcome`` under ``step`` for the router and record the decision
    in the ledger the state names under ``LEDGER_KEY``, with the evidence
    source it names under ``EVIDENCE_SOURCE_KEY``.

    Args:
        state: the routine state; its ``LEDGER_KEY`` entry is the ledger path.
        step: the id of the decision step.
        inputs: the evidence the step decided on, as for ``append_record``.
        outcome: the branch label the step chose.
    """
    append_record(
        state.get(LEDGER_KEY, ""),
        step,
        inputs,
        outcome,
        state.get(EVIDENCE_SOURCE_KEY, ""),
    )
    state[step] = outcome
    return state


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
        lines.extend(
            f'  {step.id} -->|"{label}"| {target}' for label, target in step.branches
        )
    return "\n".join(lines)


def _passthrough(state: dict) -> dict:
    """A node that leaves the state unchanged: the default for a step without a
    callable and the stub a model node runs as in a unit test."""
    return state


def gated(
    fn: Callable[[dict], dict], lock_dir: Path, sleep: Callable[[float], None]
) -> Callable[[dict], dict]:
    """Return a node that reads the machine's gate lock and waits while it is
    held before it runs ``fn``.

    Args:
        fn: the node callable ``(state) -> state``.
        lock_dir: the machine's lock directory.
        sleep: the wait between two reads of the gate lock.
    """

    def node(state: dict) -> dict:
        wait_gate(lock_dir, poll=GATE_POLL_SECONDS, sleep=sleep)
        return fn(state)

    return node


def screened(step: Step, fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
    """Return the node of the model step ``step``: it runs ``fn`` on a copy of
    the state and passes on only the keys of ``step.output_schema`` and a
    branch label under ``step.id``; every other key keeps the value it had
    before, so no raw untrusted content reaches a node with tools.

    Args:
        step: the model step.
        fn: the model callable ``(state) -> state``.

    Raises:
        TypeError: the output holds a schema key with a value of another type.
    """
    schema = dict(step.output_schema)
    labels = {label for label, _ in step.branches}

    def node(state: dict) -> dict:
        output = fn(copy.deepcopy(state))
        passed = {}
        for key, kind in schema.items():
            if key not in output:
                continue
            if not isinstance(output[key], kind):
                raise TypeError(
                    f"step {step.id!r}: output {key!r} is no {kind.__name__}"
                )
            passed[key] = output[key]
        if output.get(step.id) in labels:
            passed[step.id] = output[step.id]
        return {**state, **passed}

    return node


def asked(
    step: Step,
    fn: Callable[[dict], dict],
    approve: Callable[[Step, dict], bool],
) -> Callable[[dict], dict]:
    """Return the node of the ``ask`` step ``step``: it pauses on ``approve``
    until the owner answers, resumes on the first branch on approval and
    aborts the routine otherwise.

    Args:
        step: the ask step.
        fn: the node callable ``(state) -> state`` run after the approval.
        approve: asks the owner about ``step`` and returns the answer.

    Raises:
        AbortError: the owner did not approve.
    """

    def node(state: dict) -> dict:
        if not approve(step, state):
            raise AbortError(step.id)
        if step.branches:
            state = {**state, step.id: step.branches[0][0]}
        return fn(state)

    return node


def _router(step: Step):
    """Return a LangGraph router that reads the branch label the decision node
    wrote under ``step.id`` and falls back to the first branch."""
    labels = [label for label, _ in step.branches]

    def route(state: dict) -> str:
        choice = state.get(step.id, labels[0])
        return choice if choice in labels else labels[0]

    return route


def build(
    name: str,
    steps: list[Step],
    approve: Callable[[Step, dict], bool] | None = None,
):
    """Compile ``steps`` into a compiled LangGraph graph.

    Imported lazily: a caller that only renders the routine never loads
    LangGraph. The orchestrator container ships it; the lint and ``show`` do
    not need it. Where the orchestrator names its lock directory in
    ``ORCHESTRATOR_LOCK_DIR``, every node waits for a free gate lock first.
    A model node passes on only its schema output (``screened``).

    Args:
        name: the routine name.
        steps: the ordered steps; each step becomes a node, linear steps a plain
            edge and branching steps a conditional edge.
        approve: asks the owner about an ``ask`` step (``asked``); ``None``
            runs an ask step as a stub on its first branch.
    """
    from langgraph.graph import END, START, StateGraph

    lock_dir = os.environ.get(LOCK_DIR_ENV)
    graph = StateGraph(dict)
    for step in steps:
        fn = step.fn if step.fn is not None else _passthrough
        if step.kind == "model":
            fn = screened(step, fn)
        if step.kind == "ask" and approve is not None:
            fn = asked(step, fn, approve)
        graph.add_node(
            step.id, gated(fn, Path(lock_dir), time.sleep) if lock_dir else fn
        )
    graph.add_edge(START, steps[0].id)
    for step in steps:
        if step.branches:
            graph.add_conditional_edges(step.id, _router(step), dict(step.branches))
        else:
            graph.add_edge(step.id, step.nxt if step.nxt is not None else END)
    return graph.compile()
