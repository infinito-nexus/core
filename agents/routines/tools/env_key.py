"""Two-value test plan for a new environment key: a routine runs the affected
suites once with the key set to ``true`` and once to ``false``, so a suite that
leaks the key across the two runs is caught.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


def both_value_runs(key: str) -> list[dict]:
    """Return the two run plans for ``key``: one with ``true``, one with
    ``false``.

    Args:
        key: the new environment key.
    """
    return [
        {"key": key, "value": "true"},
        {"key": key, "value": "false"},
    ]


def run_both(
    key: str, suite: Callable[[Mapping[str, str]], bool], base: Mapping[str, str]
) -> dict[str, bool]:
    """Run ``suite`` once per plan of ``key`` and return whether each passed.

    Each run gets its own copy of ``base`` with the key set to the plan's
    value, so one run never sees the other's.

    Args:
        key: the new environment key.
        suite: the affected suites; called with the run's environment, it
            returns whether every test passed.
        base: the environment the runs start from.
    """
    return {
        plan["value"]: suite({**base, key: plan["value"]})
        for plan in both_value_runs(key)
    }


def leaks(outcomes: Mapping[str, bool]) -> bool:
    """Return whether a suite depends on the key: it failed one of the runs.

    Args:
        outcomes: the result of ``run_both``.
    """
    return not all(outcomes.values())
