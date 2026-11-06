"""Test helpers for the iterate routines: read a step's branch map and walk a
routine the way its compiled graph routes, without LangGraph."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.routines.contract import Step

_STEP_LIMIT = 200


def branch_map(steps: list[Step], step_id: str) -> dict[str, str]:
    """Return ``{label: target}`` of the step ``step_id``, ``{}`` when the
    routine has no such step or the step does not branch.

    Args:
        steps: the routine's ``STEPS``.
        step_id: the id of the step to read.
    """
    for step in steps:
        if step.id == step_id:
            return dict(step.branches)
    return {}


def walk(steps: list[Step], state: dict) -> tuple[list[str], dict]:
    """Follow ``steps`` from the first one the way the compiled graph routes:
    run each step's ``fn``, take the branch whose label the state holds under
    the step id (else the first), and stop at a step with no next step.

    Args:
        steps: the routine's ``STEPS``.
        state: the starting state; a branching step without a decision ``fn``
            follows the label this state holds under its id.

    Returns:
        The visited step ids in order and the final state.

    Raises:
        AssertionError: no terminal within ``_STEP_LIMIT`` steps.
    """
    by_id = {step.id: step for step in steps}
    current = steps[0]
    visited: list[str] = []
    for _ in range(_STEP_LIMIT):
        visited.append(current.id)
        if current.fn is not None:
            state = current.fn(state)
        if current.branches:
            labels = [label for label, _ in current.branches]
            choice = state.get(current.id, labels[0])
            target = dict(current.branches)[choice if choice in labels else labels[0]]
        elif current.nxt:
            target = current.nxt
        else:
            return visited, state
        current = by_id[target]
    raise AssertionError(f"no terminal within {_STEP_LIMIT} steps: {visited[-12:]}")
