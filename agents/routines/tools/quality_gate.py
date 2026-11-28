"""Quality-gate verdict: judge a gate run by its ``FAILED TARGETS:`` line, never
by the exit code. A ``make … | tee`` pipeline reports the tee's success even
when the gate ended with ``Error 2``, so the exit status is not evidence.
"""

from __future__ import annotations

import re

_FAILED = re.compile(r"^FAILED TARGETS:[ \t]*(.*)$", re.MULTILINE)
_NONE = ("", "none", "-")


def failed_targets(output: str) -> list[str]:
    """Return the gate's failed targets, read from the last ``FAILED TARGETS:``
    line of ``output``; an absent or empty line means none failed.

    Args:
        output: the captured quality-gate output.
    """
    matches = _FAILED.findall(output)
    if not matches:
        return []
    last = matches[-1].strip()
    if last.lower() in _NONE:
        return []
    return [target.strip() for target in last.split() if target.strip()]


def gate_green(output: str) -> bool:
    """Return whether the gate passed: it names no failed target."""
    return not failed_targets(output)
