"""Sweep resume: from the complexity-ordered app list and the app that last
turned red, compute the apps still to run, the last red app included so it is
retried first.
"""

from __future__ import annotations


def remaining_apps(order: list[str], last_red: str) -> list[str]:
    """Return the apps in ``order`` from ``last_red`` onward, inclusive.

    Args:
        order: the apps in complexity order.
        last_red: the app that last failed; it must be a member of ``order``.
    """
    return order[order.index(last_red) :]
