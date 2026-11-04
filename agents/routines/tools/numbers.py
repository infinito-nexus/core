"""Number-backed check: every number a commit, pull request or comment states
must occur in the run's evidence. A number that appears in neither the evidence
logs nor the probe output is unbacked and blocks the text until it is removed or
proven.
"""

from __future__ import annotations

import re

_NUMBER = re.compile(r"\d[\d,._]*%?")


def _core(token: str) -> str:
    """Return the comparable core of a number token: the thousands separators,
    a trailing percent and a trailing decimal point removed."""
    return token.rstrip("%").replace(",", "").replace("_", "").rstrip(".")


def unbacked_numbers(text: str, evidence: str) -> list[str]:
    """Return, in order and without duplicates, the numbers in ``text`` whose
    core does not occur in ``evidence``.

    Args:
        text: the commit, pull request or comment text to check.
        evidence: the run's collected evidence (logs, probe and oracle output).
    """
    backed = {_core(match.group()) for match in _NUMBER.finditer(evidence)}
    unbacked: list[str] = []
    seen: set[str] = set()
    for match in _NUMBER.finditer(text):
        core = _core(match.group())
        if core and core not in backed and core not in seen:
            seen.add(core)
            unbacked.append(match.group())
    return unbacked
