"""Budget analysis for a job that ended with the timeout exit code: a kill is a
timeout whose tests still passed, and the report names the task classes that
grew most against an earlier run rather than raising the budget blindly.
"""

from __future__ import annotations

import re

from agents.routines.tools.quality_gate import gate_green

_TIMEOUT_EXIT = 124

_PROFILE_LINE = re.compile(
    r"^(?P<label>.+?)\s*-{3,}\s*(?P<seconds>\d+(?:\.\d+)?)s\s*$",
    re.MULTILINE,
)


def is_budget_kill(exit_code: int, gate_output: str) -> bool:
    """Return whether the job was killed by its time budget, not by a red test.

    A budget kill is the timeout exit code with a gate output that names no
    failed target: the tests that ran were green and only the clock stopped the
    job.

    Args:
        exit_code: the job's exit status.
        gate_output: the captured gate output, judged by its FAILED TARGETS
            line.
    """
    return exit_code == _TIMEOUT_EXIT and gate_green(gate_output)


def _class_seconds(profile_tasks: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for match in _PROFILE_LINE.finditer(profile_tasks):
        label = match.group("label").strip()
        task_class = label.split(" : ", 1)[0].strip() if " : " in label else label
        totals[task_class] = totals.get(task_class, 0.0) + float(match.group("seconds"))
    return totals


def expensive_classes(profile_tasks: str, prior: str) -> list[str]:
    """Return the task classes whose summed duration grew against ``prior``,
    most-grown first.

    Args:
        profile_tasks: the ``profile_tasks`` summary of this run.
        prior: the ``profile_tasks`` summary of an earlier run of the same job.
    """
    current = _class_seconds(profile_tasks)
    earlier = _class_seconds(prior)
    growth = {
        task_class: seconds - earlier.get(task_class, 0.0)
        for task_class, seconds in current.items()
    }
    return sorted(
        (task_class for task_class, delta in growth.items() if delta > 0),
        key=lambda task_class: (-growth[task_class], task_class),
    )
