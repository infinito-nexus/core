"""Two-value test plan for a new environment key: a routine runs the affected
suites once with the key set to ``true`` and once to ``false``, so a suite that
leaks the key across the two runs is caught.
"""

from __future__ import annotations


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
